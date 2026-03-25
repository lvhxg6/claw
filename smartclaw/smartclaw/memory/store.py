"""MemoryStore — async SQLite-backed conversation history storage.

Provides persistent storage for conversation messages and summaries
using aiosqlite. Adapted from PicoClaw's ``pkg/memory/store.go``
interface and ``jsonl.go`` implementation, using SQLite instead of JSONL.
"""

from __future__ import annotations

import json
from pathlib import Path

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
        msg: BaseMessage
        if role == "human" or role == "user":
            msg = HumanMessage(content=content)
        else:
            msg = AIMessage(content=content)
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
