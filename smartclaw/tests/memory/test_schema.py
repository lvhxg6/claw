"""Tests for memory schema definitions."""

from __future__ import annotations

import pytest
import aiosqlite

from smartclaw.memory.schema import (
    CREATE_MEMORY_CHUNKS_TABLE,
    CREATE_MEMORY_CHUNKS_FILE_INDEX,
    CREATE_MEMORY_FTS_TABLE,
    CREATE_MEMORY_FTS_INSERT_TRIGGER,
    CREATE_MEMORY_FTS_DELETE_TRIGGER,
    CREATE_MEMORY_FTS_UPDATE_TRIGGER,
    CREATE_FACTS_TABLE,
    CREATE_FACTS_CONFIDENCE_INDEX,
    MEMORY_SCHEMA_STATEMENTS,
    FTS_SCHEMA_STATEMENTS,
    initialize_memory_schema,
    initialize_fts_schema,
)


class TestMemoryChunksTable:
    """Tests for memory_chunks table schema."""

    @pytest.mark.asyncio
    async def test_create_memory_chunks_table(self, tmp_path):
        """Should create memory_chunks table with correct columns."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute(CREATE_MEMORY_CHUNKS_TABLE)
            await db.commit()
            
            # Verify table exists
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_chunks'"
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == "memory_chunks"

    @pytest.mark.asyncio
    async def test_memory_chunks_columns(self, tmp_path):
        """Should have all required columns."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute(CREATE_MEMORY_CHUNKS_TABLE)
            await db.commit()
            
            cursor = await db.execute("PRAGMA table_info(memory_chunks)")
            columns = {row[1]: row[2] for row in await cursor.fetchall()}
            
            assert "hash" in columns
            assert "file_path" in columns
            assert "start_line" in columns
            assert "end_line" in columns
            assert "text" in columns
            assert "embedding_input" in columns
            assert "created_at" in columns
            assert "updated_at" in columns

    @pytest.mark.asyncio
    async def test_memory_chunks_primary_key(self, tmp_path):
        """hash should be primary key."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute(CREATE_MEMORY_CHUNKS_TABLE)
            await db.commit()
            
            # Insert a row
            await db.execute(
                """INSERT INTO memory_chunks 
                   (hash, file_path, start_line, end_line, text, embedding_input)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("abc123", "/path/to/file.md", 1, 10, "test text", "test input")
            )
            await db.commit()
            
            # Try to insert duplicate hash - should fail
            with pytest.raises(aiosqlite.IntegrityError):
                await db.execute(
                    """INSERT INTO memory_chunks 
                       (hash, file_path, start_line, end_line, text, embedding_input)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    ("abc123", "/other/file.md", 1, 5, "other text", "other input")
                )

    @pytest.mark.asyncio
    async def test_memory_chunks_file_index(self, tmp_path):
        """Should create index on file_path."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute(CREATE_MEMORY_CHUNKS_TABLE)
            await db.execute(CREATE_MEMORY_CHUNKS_FILE_INDEX)
            await db.commit()
            
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_memory_chunks_file'"
            )
            row = await cursor.fetchone()
            assert row is not None


class TestFactsTable:
    """Tests for facts table schema."""

    @pytest.mark.asyncio
    async def test_create_facts_table(self, tmp_path):
        """Should create facts table with correct columns."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute(CREATE_FACTS_TABLE)
            await db.commit()
            
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='facts'"
            )
            row = await cursor.fetchone()
            assert row is not None

    @pytest.mark.asyncio
    async def test_facts_columns(self, tmp_path):
        """Should have all required columns."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute(CREATE_FACTS_TABLE)
            await db.commit()
            
            cursor = await db.execute("PRAGMA table_info(facts)")
            columns = {row[1]: row[2] for row in await cursor.fetchall()}
            
            assert "id" in columns
            assert "content" in columns
            assert "category" in columns
            assert "confidence" in columns
            assert "created_at" in columns
            assert "source" in columns

    @pytest.mark.asyncio
    async def test_facts_confidence_index(self, tmp_path):
        """Should create descending index on confidence."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute(CREATE_FACTS_TABLE)
            await db.execute(CREATE_FACTS_CONFIDENCE_INDEX)
            await db.commit()
            
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_facts_confidence'"
            )
            row = await cursor.fetchone()
            assert row is not None


class TestFTSTable:
    """Tests for FTS5 full-text search table."""

    @pytest.mark.asyncio
    async def test_create_fts_table(self, tmp_path):
        """Should create FTS5 virtual table."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as db:
            # FTS5 requires the content table to exist first
            await db.execute(CREATE_MEMORY_CHUNKS_TABLE)
            await db.execute(CREATE_MEMORY_FTS_TABLE)
            await db.commit()
            
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_fts'"
            )
            row = await cursor.fetchone()
            assert row is not None

    @pytest.mark.asyncio
    async def test_fts_triggers(self, tmp_path):
        """Should create sync triggers for FTS index."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute(CREATE_MEMORY_CHUNKS_TABLE)
            await db.execute(CREATE_MEMORY_FTS_TABLE)
            await db.execute(CREATE_MEMORY_FTS_INSERT_TRIGGER)
            await db.execute(CREATE_MEMORY_FTS_DELETE_TRIGGER)
            await db.execute(CREATE_MEMORY_FTS_UPDATE_TRIGGER)
            await db.commit()
            
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
            triggers = [row[0] for row in await cursor.fetchall()]
            
            assert "memory_chunks_ai" in triggers
            assert "memory_chunks_ad" in triggers
            assert "memory_chunks_au" in triggers

    @pytest.mark.asyncio
    async def test_fts_insert_sync(self, tmp_path):
        """FTS should sync on insert via trigger."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute(CREATE_MEMORY_CHUNKS_TABLE)
            await db.execute(CREATE_MEMORY_FTS_TABLE)
            await db.execute(CREATE_MEMORY_FTS_INSERT_TRIGGER)
            await db.commit()
            
            # Insert into memory_chunks
            await db.execute(
                """INSERT INTO memory_chunks 
                   (hash, file_path, start_line, end_line, text, embedding_input)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("hash1", "/test.md", 1, 10, "hello world python", "hello world python")
            )
            await db.commit()
            
            # Search in FTS
            cursor = await db.execute(
                "SELECT hash FROM memory_fts WHERE memory_fts MATCH 'python'"
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == "hash1"

    @pytest.mark.asyncio
    async def test_fts_delete_sync(self, tmp_path):
        """FTS should sync on delete via trigger."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute(CREATE_MEMORY_CHUNKS_TABLE)
            await db.execute(CREATE_MEMORY_FTS_TABLE)
            await db.execute(CREATE_MEMORY_FTS_INSERT_TRIGGER)
            await db.execute(CREATE_MEMORY_FTS_DELETE_TRIGGER)
            await db.commit()
            
            # Insert
            await db.execute(
                """INSERT INTO memory_chunks 
                   (hash, file_path, start_line, end_line, text, embedding_input)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("hash1", "/test.md", 1, 10, "hello world", "hello world")
            )
            await db.commit()
            
            # Delete
            await db.execute("DELETE FROM memory_chunks WHERE hash = ?", ("hash1",))
            await db.commit()
            
            # FTS should be empty
            cursor = await db.execute(
                "SELECT hash FROM memory_fts WHERE memory_fts MATCH 'hello'"
            )
            row = await cursor.fetchone()
            assert row is None


class TestInitializeFunctions:
    """Tests for schema initialization functions."""

    @pytest.mark.asyncio
    async def test_initialize_memory_schema(self, tmp_path):
        """Should initialize all memory tables."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as db:
            await initialize_memory_schema(db)
            
            # Check memory_chunks table
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_chunks'"
            )
            assert await cursor.fetchone() is not None
            
            # Check facts table
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='facts'"
            )
            assert await cursor.fetchone() is not None
            
            # Check indexes
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_memory_chunks_file'"
            )
            assert await cursor.fetchone() is not None
            
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_facts_confidence'"
            )
            assert await cursor.fetchone() is not None

    @pytest.mark.asyncio
    async def test_initialize_fts_schema(self, tmp_path):
        """Should initialize FTS tables and triggers."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as db:
            # FTS requires memory_chunks first
            await initialize_memory_schema(db)
            await initialize_fts_schema(db)
            
            # Check FTS table
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_fts'"
            )
            assert await cursor.fetchone() is not None
            
            # Check triggers
            cursor = await db.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'memory_chunks_%'"
            )
            row = await cursor.fetchone()
            assert row[0] == 3  # ai, ad, au triggers

    @pytest.mark.asyncio
    async def test_idempotent_initialization(self, tmp_path):
        """Schema initialization should be idempotent."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as db:
            # Initialize twice
            await initialize_memory_schema(db)
            await initialize_memory_schema(db)
            
            await initialize_fts_schema(db)
            await initialize_fts_schema(db)
            
            # Should not raise any errors
            cursor = await db.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            )
            row = await cursor.fetchone()
            assert row[0] >= 3  # memory_chunks, facts, memory_fts
