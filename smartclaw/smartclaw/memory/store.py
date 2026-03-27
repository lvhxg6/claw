"""MemoryStore — async SQLite-backed conversation history storage.

Provides persistent storage for conversation messages and summaries
using aiosqlite. Adapted from PicoClaw's ``pkg/memory/store.go``
interface and ``jsonl.go`` implementation, using SQLite instead of JSONL.
"""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path
from typing import Any

import aiosqlite
import structlog
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    message_to_dict,
    messages_from_dict,
)

logger = structlog.get_logger(component="memory.store")

# ---------------------------------------------------------------------------
# SQL constants
# ---------------------------------------------------------------------------

_CREATE_MESSAGES_TABLE = """\
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key TEXT NOT NULL,
    message_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)"""

_CREATE_MESSAGES_INDEX = """\
CREATE INDEX IF NOT EXISTS idx_messages_session
    ON messages(session_key, id)"""

_CREATE_SUMMARIES_TABLE = """\
CREATE TABLE IF NOT EXISTS summaries (
    session_key TEXT PRIMARY KEY,
    summary TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)"""

_CREATE_SESSION_CONFIG_TABLE = """\
CREATE TABLE IF NOT EXISTS session_config (
    session_key TEXT PRIMARY KEY,
    model_override TEXT,
    config_json TEXT DEFAULT '{}',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)"""

_CREATE_COOLDOWN_STATE_TABLE = """\
CREATE TABLE IF NOT EXISTS cooldown_state (
    profile_id TEXT PRIMARY KEY,
    error_count INTEGER NOT NULL DEFAULT 0,
    cooldown_end_utc TEXT NOT NULL,
    last_failure_utc TEXT NOT NULL,
    failure_counts_json TEXT DEFAULT '{}'
)"""

_CREATE_ATTACHMENTS_TABLE = """\
CREATE TABLE IF NOT EXISTS attachments (
    asset_id TEXT PRIMARY KEY,
    session_key TEXT,
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    kind TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'uploaded',
    extract_status TEXT NOT NULL DEFAULT 'pending',
    extract_text TEXT DEFAULT '',
    extract_summary TEXT DEFAULT '',
    error_message TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)"""

_CREATE_ATTACHMENTS_SESSION_INDEX = """\
CREATE INDEX IF NOT EXISTS idx_attachments_session
    ON attachments(session_key, created_at DESC)"""


class MemoryStore:
    """Async SQLite conversation memory store."""

    def __init__(self, db_path: str = "~/.smartclaw/memory.db") -> None:
        expanded = Path(db_path).expanduser()
        self._db_path = expanded
        self._db: aiosqlite.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the database file, tables, and indexes if they don't exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        await self._db.execute(_CREATE_MESSAGES_TABLE)
        await self._db.execute(_CREATE_MESSAGES_INDEX)
        await self._db.execute(_CREATE_SUMMARIES_TABLE)
        await self._db.execute(_CREATE_SESSION_CONFIG_TABLE)
        await self._db.execute(_CREATE_COOLDOWN_STATE_TABLE)
        await self._db.execute(_CREATE_ATTACHMENTS_TABLE)
        await self._db.execute(_CREATE_ATTACHMENTS_SESSION_INDEX)
        await self._db.commit()
        logger.info("memory_store_initialized", db_path=str(self._db_path))

    async def close(self) -> None:
        """Release the SQLite connection."""
        if self._db is not None:
            await self._db.close()
            self._db = None
            logger.debug("memory_store_closed")

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def add_message(
        self, session_key: str, role: str, content: str
    ) -> None:
        """Append a simple text message (human or ai) to the session."""
        assert self._db is not None, "MemoryStore not initialized"
        msg: BaseMessage = (
            HumanMessage(content=content)
            if role == "human" or role == "user"
            else AIMessage(content=content)
        )
        await self._insert_message(session_key, msg)

    async def add_full_message(
        self, session_key: str, message: BaseMessage
    ) -> None:
        """Append a complete LangChain BaseMessage (with tool_calls, etc.)."""
        assert self._db is not None, "MemoryStore not initialized"
        await self._insert_message(session_key, message)

    async def get_history(self, session_key: str) -> list[BaseMessage]:
        """Return all messages for *session_key* in insertion order.

        Returns an empty list when the session does not exist.
        """
        assert self._db is not None, "MemoryStore not initialized"
        cursor = await self._db.execute(
            "SELECT message_json FROM messages WHERE session_key = ? ORDER BY id",
            (session_key,),
        )
        rows = await cursor.fetchall()
        if not rows:
            return []

        dicts: list[dict] = []  # type: ignore[type-arg]
        for (raw_json,) in rows:
            try:
                dicts.append(json.loads(raw_json))
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "skipping_corrupt_message",
                    session_key=session_key,
                    raw=raw_json[:200] if raw_json else None,
                )
        if not dicts:
            return []
        return messages_from_dict(dicts)

    async def set_history(
        self, session_key: str, messages: list[BaseMessage]
    ) -> None:
        """Atomically replace all messages in a session (DELETE + INSERT)."""
        assert self._db is not None, "MemoryStore not initialized"
        async with self._db.cursor() as cur:
            await cur.execute(
                "DELETE FROM messages WHERE session_key = ?",
                (session_key,),
            )
            for msg in messages:
                msg_json = json.dumps(message_to_dict(msg), ensure_ascii=False)
                await cur.execute(
                    "INSERT INTO messages (session_key, message_json) VALUES (?, ?)",
                    (session_key, msg_json),
                )
        await self._db.commit()
        logger.debug(
            "history_replaced",
            session_key=session_key,
            count=len(messages),
        )

    async def truncate_history(
        self, session_key: str, keep_last: int
    ) -> None:
        """Keep the last *keep_last* messages, delete the rest.

        When *keep_last* <= 0, all messages are removed.
        """
        assert self._db is not None, "MemoryStore not initialized"
        if keep_last <= 0:
            await self._db.execute(
                "DELETE FROM messages WHERE session_key = ?",
                (session_key,),
            )
        else:
            # Delete all except the N rows with the highest id values.
            await self._db.execute(
                """
                DELETE FROM messages
                WHERE session_key = ?
                  AND id NOT IN (
                      SELECT id FROM messages
                      WHERE session_key = ?
                      ORDER BY id DESC
                      LIMIT ?
                  )
                """,
                (session_key, session_key, keep_last),
            )
        await self._db.commit()
        logger.debug(
            "history_truncated",
            session_key=session_key,
            keep_last=keep_last,
        )

    # ------------------------------------------------------------------
    # Summaries
    # ------------------------------------------------------------------

    async def get_summary(self, session_key: str) -> str:
        """Return the summary for *session_key*, or ``""`` if none exists."""
        assert self._db is not None, "MemoryStore not initialized"
        cursor = await self._db.execute(
            "SELECT summary FROM summaries WHERE session_key = ?",
            (session_key,),
        )
        row = await cursor.fetchone()
        if row is None:
            return ""
        return row[0]

    async def set_summary(self, session_key: str, summary: str) -> None:
        """Upsert the summary for *session_key*."""
        assert self._db is not None, "MemoryStore not initialized"
        await self._db.execute(
            """
            INSERT INTO summaries (session_key, summary, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(session_key) DO UPDATE
                SET summary = excluded.summary,
                    updated_at = excluded.updated_at
            """,
            (session_key, summary),
        )
        await self._db.commit()
        logger.debug("summary_set", session_key=session_key)

    async def delete_summary(self, session_key: str) -> None:
        """Delete the summary row for *session_key*."""
        assert self._db is not None, "MemoryStore not initialized"
        await self._db.execute(
            "DELETE FROM summaries WHERE session_key = ?",
            (session_key,),
        )
        await self._db.commit()
        logger.debug("summary_deleted", session_key=session_key)

    # ------------------------------------------------------------------
    # Session Config
    # ------------------------------------------------------------------

    async def get_session_config(self, session_key: str) -> dict[str, Any] | None:
        """Return session config dict, or None if not found."""
        assert self._db is not None, "MemoryStore not initialized"
        cursor = await self._db.execute(
            "SELECT model_override, config_json FROM session_config WHERE session_key = ?",
            (session_key,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        model_override, config_json = row
        result: dict[str, Any] = {"model_override": model_override}
        if config_json:
            try:
                result["config"] = json.loads(config_json)
            except (json.JSONDecodeError, TypeError):
                result["config"] = {}
        return result

    async def set_session_config(
        self,
        session_key: str,
        model_override: str | None = None,
        config_json: str | None = None,
    ) -> None:
        """Upsert session config."""
        assert self._db is not None, "MemoryStore not initialized"
        await self._db.execute(
            """
            INSERT INTO session_config (session_key, model_override, config_json, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(session_key) DO UPDATE
                SET model_override = excluded.model_override,
                    config_json = excluded.config_json,
                    updated_at = excluded.updated_at
            """,
            (session_key, model_override, config_json or "{}"),
        )
        await self._db.commit()
        logger.debug("session_config_set", session_key=session_key)

    async def delete_session_config(self, session_key: str) -> None:
        """Delete persisted config for *session_key*."""
        assert self._db is not None, "MemoryStore not initialized"
        await self._db.execute(
            "DELETE FROM session_config WHERE session_key = ?",
            (session_key,),
        )
        await self._db.commit()
        logger.debug("session_config_deleted", session_key=session_key)

    async def delete_session(self, session_key: str) -> None:
        """Delete all persisted message, summary, and config rows for a session."""
        assert self._db is not None, "MemoryStore not initialized"
        async with self._db.cursor() as cur:
            await cur.execute(
                "DELETE FROM messages WHERE session_key = ?",
                (session_key,),
            )
            await cur.execute(
                "DELETE FROM summaries WHERE session_key = ?",
                (session_key,),
            )
            await cur.execute(
                "DELETE FROM session_config WHERE session_key = ?",
                (session_key,),
            )
        await self._db.commit()
        logger.debug("session_deleted", session_key=session_key)

    async def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent sessions with lightweight metadata for navigation UIs."""
        assert self._db is not None, "MemoryStore not initialized"
        capped_limit = max(1, min(int(limit), 200))
        cursor = await self._db.execute(
            """
            WITH session_keys AS (
                SELECT session_key FROM messages
                UNION
                SELECT session_key FROM summaries
                UNION
                SELECT session_key FROM session_config
                UNION
                SELECT session_key FROM attachments WHERE session_key IS NOT NULL
            )
            SELECT
                sk.session_key,
                COALESCE(msg.message_count, 0) AS message_count,
                COALESCE(att.attachment_count, 0) AS attachment_count,
                CASE
                    WHEN msg.last_message_at IS NULL THEN COALESCE(sum.updated_at, cfg.updated_at, att.last_attachment_at)
                    WHEN sum.updated_at IS NULL THEN COALESCE(msg.last_message_at, cfg.updated_at, att.last_attachment_at)
                    WHEN cfg.updated_at IS NULL THEN COALESCE(msg.last_message_at, sum.updated_at, att.last_attachment_at)
                    WHEN att.last_attachment_at IS NULL THEN MAX(msg.last_message_at, sum.updated_at, cfg.updated_at)
                    ELSE MAX(msg.last_message_at, sum.updated_at, cfg.updated_at, att.last_attachment_at)
                END AS last_activity_at,
                COALESCE(sum.summary, '') AS summary,
                cfg.model_override
            FROM session_keys sk
            LEFT JOIN (
                SELECT session_key, COUNT(*) AS message_count, MAX(created_at) AS last_message_at
                FROM messages
                GROUP BY session_key
            ) msg ON msg.session_key = sk.session_key
            LEFT JOIN (
                SELECT session_key, COUNT(*) AS attachment_count, MAX(created_at) AS last_attachment_at
                FROM attachments
                WHERE session_key IS NOT NULL
                GROUP BY session_key
            ) att ON att.session_key = sk.session_key
            LEFT JOIN summaries sum ON sum.session_key = sk.session_key
            LEFT JOIN session_config cfg ON cfg.session_key = sk.session_key
            WHERE COALESCE(msg.message_count, 0) > 0
               OR COALESCE(att.attachment_count, 0) > 0
               OR COALESCE(sum.summary, '') != ''
            ORDER BY last_activity_at DESC, sk.session_key DESC
            LIMIT ?
            """,
            (capped_limit,),
        )
        rows = await cursor.fetchall()
        sessions: list[dict[str, Any]] = []
        for row in rows:
            session_key, message_count, attachment_count, updated_at, summary, model_override = row
            title, preview = await self._get_session_title_and_preview(session_key)
            display_count = int(message_count or 0)
            if display_count <= 0 and int(attachment_count or 0) > 0:
                display_count = int(attachment_count or 0)
            sessions.append(
                {
                    "session_key": session_key,
                    "title": title or session_key,
                    "preview": preview or summary or "",
                    "updated_at": updated_at,
                    "message_count": display_count,
                    "model_override": model_override,
                }
            )
        return sessions

    # ------------------------------------------------------------------
    # Cooldown State
    # ------------------------------------------------------------------

    async def get_cooldown_states(self) -> list[dict[str, Any]]:
        """Return all cooldown state records."""
        assert self._db is not None, "MemoryStore not initialized"
        cursor = await self._db.execute(
            "SELECT profile_id, error_count, cooldown_end_utc, "
            "last_failure_utc, failure_counts_json FROM cooldown_state"
        )
        rows = await cursor.fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            profile_id, error_count, cooldown_end_utc, last_failure_utc, fc_json = row
            failure_counts: dict[str, int] = {}
            if fc_json:
                with suppress(json.JSONDecodeError, TypeError):
                    failure_counts = json.loads(fc_json)
            results.append({
                "profile_id": profile_id,
                "error_count": error_count,
                "cooldown_end_utc": cooldown_end_utc,
                "last_failure_utc": last_failure_utc,
                "failure_counts": failure_counts,
            })
        return results

    async def set_cooldown_state(
        self,
        profile_id: str,
        error_count: int,
        cooldown_end_utc: str,
        last_failure_utc: str,
        failure_counts_json: str,
    ) -> None:
        """Upsert a cooldown state record."""
        assert self._db is not None, "MemoryStore not initialized"
        await self._db.execute(
            """
            INSERT INTO cooldown_state
                (profile_id, error_count, cooldown_end_utc, last_failure_utc, failure_counts_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE
                SET error_count = excluded.error_count,
                    cooldown_end_utc = excluded.cooldown_end_utc,
                    last_failure_utc = excluded.last_failure_utc,
                    failure_counts_json = excluded.failure_counts_json
            """,
            (profile_id, error_count, cooldown_end_utc, last_failure_utc, failure_counts_json),
        )
        await self._db.commit()

    async def delete_cooldown_state(self, profile_id: str) -> None:
        """Delete a cooldown state record."""
        assert self._db is not None, "MemoryStore not initialized"
        await self._db.execute(
            "DELETE FROM cooldown_state WHERE profile_id = ?",
            (profile_id,),
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------

    async def upsert_attachment(self, record: dict[str, Any]) -> None:
        """Insert or update an attachment record."""
        assert self._db is not None, "MemoryStore not initialized"
        await self._db.execute(
            """
            INSERT INTO attachments (
                asset_id, session_key, filename, media_type, kind, storage_path,
                size_bytes, sha256, status, extract_status, extract_text,
                extract_summary, error_message, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(asset_id) DO UPDATE SET
                session_key = excluded.session_key,
                filename = excluded.filename,
                media_type = excluded.media_type,
                kind = excluded.kind,
                storage_path = excluded.storage_path,
                size_bytes = excluded.size_bytes,
                sha256 = excluded.sha256,
                status = excluded.status,
                extract_status = excluded.extract_status,
                extract_text = excluded.extract_text,
                extract_summary = excluded.extract_summary,
                error_message = excluded.error_message,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                record["asset_id"],
                record.get("session_key"),
                record["filename"],
                record["media_type"],
                record["kind"],
                record["storage_path"],
                int(record["size_bytes"]),
                record["sha256"],
                record.get("status", "uploaded"),
                record.get("extract_status", "pending"),
                record.get("extract_text", ""),
                record.get("extract_summary", ""),
                record.get("error_message", ""),
            ),
        )
        await self._db.commit()

    async def get_attachment(self, asset_id: str) -> dict[str, Any] | None:
        """Return an attachment record, or None if missing."""
        assert self._db is not None, "MemoryStore not initialized"
        cursor = await self._db.execute(
            """
            SELECT asset_id, session_key, filename, media_type, kind, storage_path,
                   size_bytes, sha256, status, extract_status, extract_text,
                   extract_summary, error_message, created_at, updated_at
            FROM attachments
            WHERE asset_id = ?
            """,
            (asset_id,),
        )
        row = await cursor.fetchone()
        return _attachment_row_to_dict(row)

    async def get_attachments(self, asset_ids: list[str]) -> list[dict[str, Any]]:
        """Return attachment records preserving input order for existing ids."""
        assert self._db is not None, "MemoryStore not initialized"
        results: list[dict[str, Any]] = []
        for asset_id in asset_ids:
            record = await self.get_attachment(asset_id)
            if record is not None:
                results.append(record)
        return results

    async def list_attachments(self, session_key: str) -> list[dict[str, Any]]:
        """Return all attachments linked to a session."""
        assert self._db is not None, "MemoryStore not initialized"
        cursor = await self._db.execute(
            """
            SELECT asset_id, session_key, filename, media_type, kind, storage_path,
                   size_bytes, sha256, status, extract_status, extract_text,
                   extract_summary, error_message, created_at, updated_at
            FROM attachments
            WHERE session_key = ?
            ORDER BY created_at DESC, asset_id DESC
            """,
            (session_key,),
        )
        rows = await cursor.fetchall()
        return [record for row in rows if (record := _attachment_row_to_dict(row)) is not None]

    async def delete_attachment(self, asset_id: str) -> None:
        """Delete an attachment metadata record."""
        assert self._db is not None, "MemoryStore not initialized"
        await self._db.execute(
            "DELETE FROM attachments WHERE asset_id = ?",
            (asset_id,),
        )
        await self._db.commit()

    async def delete_attachments_for_session(self, session_key: str) -> None:
        """Delete all attachment metadata records linked to a session."""
        assert self._db is not None, "MemoryStore not initialized"
        await self._db.execute(
            "DELETE FROM attachments WHERE session_key = ?",
            (session_key,),
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _insert_message(
        self, session_key: str, message: BaseMessage
    ) -> None:
        msg_json = json.dumps(message_to_dict(message), ensure_ascii=False)
        await self._db.execute(  # type: ignore[union-attr]
            "INSERT INTO messages (session_key, message_json) VALUES (?, ?)",
            (session_key, msg_json),
        )
        await self._db.commit()  # type: ignore[union-attr]

    async def _get_session_title_and_preview(self, session_key: str) -> tuple[str, str]:
        assert self._db is not None, "MemoryStore not initialized"
        first_cursor = await self._db.execute(
            """
            SELECT message_json
            FROM messages
            WHERE session_key = ?
            ORDER BY id ASC
            LIMIT 20
            """,
            (session_key,),
        )
        first_rows = await first_cursor.fetchall()
        title = ""
        fallback_title = ""
        for (raw_json,) in first_rows:
            message_type, content = _extract_message_type_and_text(raw_json)
            if not content:
                continue
            shortened = _shorten_text(content, 48)
            if not fallback_title:
                fallback_title = shortened
            if message_type in {"human", "user"}:
                title = shortened
                break
        if not title:
            title = fallback_title

        last_cursor = await self._db.execute(
            """
            SELECT message_json
            FROM messages
            WHERE session_key = ?
            ORDER BY id DESC
            LIMIT 20
            """,
            (session_key,),
        )
        last_rows = await last_cursor.fetchall()
        preview = ""
        fallback_preview = ""
        for (raw_json,) in last_rows:
            message_type, content = _extract_message_type_and_text(raw_json)
            if not content:
                continue
            shortened = _shorten_text(content, 88)
            if not fallback_preview:
                fallback_preview = shortened
            if message_type in {"human", "user", "ai", "assistant"}:
                preview = shortened
                break
        if not preview:
            preview = fallback_preview
        return title, _shorten_text(preview, 88)


def _extract_text_content(raw_json: str | None) -> str:
    return _extract_message_type_and_text(raw_json)[1]


def _extract_message_type_and_text(raw_json: str | None) -> tuple[str, str]:
    if not raw_json:
        return "", ""
    try:
        payload = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return "", ""
    message_type = str(payload.get("type", "")).strip().lower()
    content = payload.get("data", {}).get("content")
    if isinstance(content, str):
        return message_type, content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return message_type, " ".join(parts).strip()
    return message_type, ""


def _shorten_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(1, limit - 1)] + "…"


def _attachment_row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    (
        asset_id,
        session_key,
        filename,
        media_type,
        kind,
        storage_path,
        size_bytes,
        sha256,
        status,
        extract_status,
        extract_text,
        extract_summary,
        error_message,
        created_at,
        updated_at,
    ) = row
    return {
        "asset_id": asset_id,
        "session_key": session_key,
        "filename": filename,
        "media_type": media_type,
        "kind": kind,
        "storage_path": storage_path,
        "size_bytes": int(size_bytes or 0),
        "sha256": sha256,
        "status": status,
        "extract_status": extract_status,
        "extract_text": extract_text or "",
        "extract_summary": extract_summary or "",
        "error_message": error_message or "",
        "created_at": created_at,
        "updated_at": updated_at,
    }
