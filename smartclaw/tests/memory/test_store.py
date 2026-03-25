"""Unit tests for MemoryStore."""

from __future__ import annotations

from pathlib import Path

from smartclaw.memory.store import MemoryStore


class TestEmptySession:
    """Tests for empty/non-existent sessions."""

    async def test_get_history_returns_empty_list(self, tmp_path: Path) -> None:
        """Empty session get_history returns empty list. (Req 1.3)"""
        store = MemoryStore(db_path=str(tmp_path / "test.db"))
        await store.initialize()
        try:
            history = await store.get_history("nonexistent-session")
            assert history == []
        finally:
            await store.close()

    async def test_get_summary_returns_empty_string(self, tmp_path: Path) -> None:
        """Empty summary get_summary returns empty string. (Req 1.5)"""
        store = MemoryStore(db_path=str(tmp_path / "test.db"))
        await store.initialize()
        try:
            summary = await store.get_summary("nonexistent-session")
            assert summary == ""
        finally:
            await store.close()


class TestTruncateHistory:
    """Tests for truncate_history edge cases."""

    async def test_keep_last_zero_clears_all(self, tmp_path: Path) -> None:
        """keep_last<=0 clears all messages. (Req 1.8)"""
        store = MemoryStore(db_path=str(tmp_path / "test.db"))
        await store.initialize()
        try:
            await store.add_message("s1", "human", "hello")
            await store.add_message("s1", "ai", "hi")
            await store.add_message("s1", "human", "bye")

            await store.truncate_history("s1", 0)
            history = await store.get_history("s1")
            assert history == []
        finally:
            await store.close()

    async def test_keep_last_negative_clears_all(self, tmp_path: Path) -> None:
        """keep_last < 0 also clears all messages. (Req 1.8)"""
        store = MemoryStore(db_path=str(tmp_path / "test.db"))
        await store.initialize()
        try:
            await store.add_message("s1", "human", "hello")
            await store.add_message("s1", "ai", "hi")

            await store.truncate_history("s1", -5)
            history = await store.get_history("s1")
            assert history == []
        finally:
            await store.close()


class TestDatabaseAutoCreation:
    """Tests for database file auto-creation."""

    async def test_db_file_auto_created(self, tmp_path: Path) -> None:
        """Database file auto-created on initialize. (Req 1.14)"""
        db_path = tmp_path / "subdir" / "nested" / "memory.db"
        assert not db_path.exists()

        store = MemoryStore(db_path=str(db_path))
        await store.initialize()
        try:
            assert db_path.exists()
        finally:
            await store.close()


class TestClose:
    """Tests for close and resource release."""

    async def test_close_releases_resources(self, tmp_path: Path) -> None:
        """close() releases the SQLite connection."""
        store = MemoryStore(db_path=str(tmp_path / "test.db"))
        await store.initialize()
        assert store._db is not None

        await store.close()
        assert store._db is None

    async def test_close_idempotent(self, tmp_path: Path) -> None:
        """Calling close() twice does not raise."""
        store = MemoryStore(db_path=str(tmp_path / "test.db"))
        await store.initialize()
        await store.close()
        await store.close()  # Should not raise
