"""Tests for MemoryIndexManager."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from smartclaw.memory.index_manager import (
    EmbeddingProvider,
    MemoryIndexManager,
    NoOpEmbeddingProvider,
    OllamaEmbeddingProvider,
    OpenAIEmbeddingProvider,
    SearchResult,
)


@dataclass
class MockMemoryChunk:
    """Mock MemoryChunk for testing."""
    
    hash: str
    file_path: str
    start_line: int
    end_line: int
    text: str
    embedding_input: str


class TestEmbeddingProviders:
    """Tests for embedding provider classes."""

    def test_noop_provider_dimension(self):
        """NoOp provider should have dimension 0."""
        provider = NoOpEmbeddingProvider()
        assert provider.dimension == 0

    def test_noop_provider_name(self):
        """NoOp provider should have name 'none'."""
        provider = NoOpEmbeddingProvider()
        assert provider.name == "none"

    @pytest.mark.asyncio
    async def test_noop_provider_embed(self):
        """NoOp provider should return empty embeddings."""
        provider = NoOpEmbeddingProvider()
        result = await provider.embed(["test1", "test2"])
        assert result == [[], []]

    @pytest.mark.asyncio
    async def test_noop_provider_always_available(self):
        """NoOp provider should always be available."""
        provider = NoOpEmbeddingProvider()
        assert await provider.is_available() is True

    def test_openai_provider_dimension(self):
        """OpenAI provider should have dimension 1536."""
        provider = OpenAIEmbeddingProvider()
        assert provider.dimension == 1536

    def test_openai_provider_name(self):
        """OpenAI provider name should include model."""
        provider = OpenAIEmbeddingProvider(model="text-embedding-3-small")
        assert provider.name == "openai:text-embedding-3-small"

    def test_ollama_provider_dimension(self):
        """Ollama provider should have dimension 768."""
        provider = OllamaEmbeddingProvider()
        assert provider.dimension == 768

    def test_ollama_provider_name(self):
        """Ollama provider name should include model."""
        provider = OllamaEmbeddingProvider(model="nomic-embed-text")
        assert provider.name == "ollama:nomic-embed-text"


class TestMemoryIndexManagerInit:
    """Tests for MemoryIndexManager initialization."""

    @pytest.mark.asyncio
    async def test_initialize_creates_db(self, tmp_path):
        """Should create database file on initialize."""
        db_path = tmp_path / "test.db"
        manager = MemoryIndexManager(db_path=str(db_path), embedding_provider="none")
        
        await manager.initialize()
        
        assert db_path.exists()
        await manager.close()

    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, tmp_path):
        """Should create required tables on initialize."""
        db_path = tmp_path / "test.db"
        manager = MemoryIndexManager(db_path=str(db_path), embedding_provider="none")
        
        await manager.initialize()
        
        import aiosqlite
        async with aiosqlite.connect(str(db_path)) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in await cursor.fetchall()}
        
        assert "memory_chunks" in tables
        assert "facts" in tables
        assert "memory_fts" in tables
        
        await manager.close()

    @pytest.mark.asyncio
    async def test_provider_none_uses_noop(self, tmp_path):
        """embedding_provider='none' should use NoOpEmbeddingProvider."""
        db_path = tmp_path / "test.db"
        manager = MemoryIndexManager(db_path=str(db_path), embedding_provider="none")
        
        await manager.initialize()
        
        assert manager.get_provider() is not None
        assert manager.get_provider().name == "none"
        
        await manager.close()

    @pytest.mark.asyncio
    async def test_close_releases_connection(self, tmp_path):
        """close() should release database connection."""
        db_path = tmp_path / "test.db"
        manager = MemoryIndexManager(db_path=str(db_path), embedding_provider="none")
        
        await manager.initialize()
        assert manager._db is not None
        
        await manager.close()
        assert manager._db is None


class TestMemoryIndexManagerIndexing:
    """Tests for chunk indexing."""

    @pytest.mark.asyncio
    async def test_index_chunks_empty_list(self, tmp_path):
        """Should handle empty chunk list."""
        db_path = tmp_path / "test.db"
        manager = MemoryIndexManager(db_path=str(db_path), embedding_provider="none")
        await manager.initialize()
        
        result = await manager.index_chunks([])
        
        assert result == 0
        await manager.close()

    @pytest.mark.asyncio
    async def test_index_chunks_stores_data(self, tmp_path):
        """Should store chunk data in database."""
        db_path = tmp_path / "test.db"
        manager = MemoryIndexManager(db_path=str(db_path), embedding_provider="none")
        await manager.initialize()
        
        chunks = [
            MockMemoryChunk(
                hash="abc123",
                file_path="/test/file.md",
                start_line=1,
                end_line=10,
                text="Hello world",
                embedding_input="Hello world",
            )
        ]
        
        result = await manager.index_chunks(chunks)
        
        assert result == 1
        
        # Verify data in database
        import aiosqlite
        async with aiosqlite.connect(str(db_path)) as db:
            cursor = await db.execute(
                "SELECT hash, file_path, text FROM memory_chunks WHERE hash = ?",
                ("abc123",),
            )
            row = await cursor.fetchone()
        
        assert row is not None
        assert row[0] == "abc123"
        assert row[1] == "/test/file.md"
        assert row[2] == "Hello world"
        
        await manager.close()

    @pytest.mark.asyncio
    async def test_index_chunks_updates_existing(self, tmp_path):
        """Should update existing chunk on re-index."""
        db_path = tmp_path / "test.db"
        manager = MemoryIndexManager(db_path=str(db_path), embedding_provider="none")
        await manager.initialize()
        
        # Index first version
        chunks1 = [
            MockMemoryChunk(
                hash="abc123",
                file_path="/test/file.md",
                start_line=1,
                end_line=10,
                text="Original text",
                embedding_input="Original text",
            )
        ]
        await manager.index_chunks(chunks1)
        
        # Index updated version
        chunks2 = [
            MockMemoryChunk(
                hash="abc123",
                file_path="/test/file.md",
                start_line=1,
                end_line=15,
                text="Updated text",
                embedding_input="Updated text",
            )
        ]
        await manager.index_chunks(chunks2)
        
        # Verify only one row with updated text
        import aiosqlite
        async with aiosqlite.connect(str(db_path)) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM memory_chunks WHERE hash = ?",
                ("abc123",),
            )
            count = (await cursor.fetchone())[0]
            
            cursor = await db.execute(
                "SELECT text FROM memory_chunks WHERE hash = ?",
                ("abc123",),
            )
            text = (await cursor.fetchone())[0]
        
        assert count == 1
        assert text == "Updated text"
        
        await manager.close()


class TestMemoryIndexManagerSearch:
    """Tests for search functionality."""

    @pytest.mark.asyncio
    async def test_bm25_search_finds_match(self, tmp_path):
        """BM25 search should find matching chunks."""
        db_path = tmp_path / "test.db"
        manager = MemoryIndexManager(db_path=str(db_path), embedding_provider="none")
        await manager.initialize()
        
        # Index some chunks
        chunks = [
            MockMemoryChunk(
                hash="hash1",
                file_path="/test/file1.md",
                start_line=1,
                end_line=10,
                text="Python programming language",
                embedding_input="Python programming language",
            ),
            MockMemoryChunk(
                hash="hash2",
                file_path="/test/file2.md",
                start_line=1,
                end_line=10,
                text="JavaScript web development",
                embedding_input="JavaScript web development",
            ),
        ]
        await manager.index_chunks(chunks)
        
        # Search for Python
        results = await manager._bm25_search("Python")
        
        assert len(results) >= 1
        hashes = [r[0] for r in results]
        assert "hash1" in hashes
        
        await manager.close()

    @pytest.mark.asyncio
    async def test_search_returns_empty_when_no_match(self, tmp_path):
        """Search should return empty list when no match."""
        db_path = tmp_path / "test.db"
        manager = MemoryIndexManager(db_path=str(db_path), embedding_provider="none")
        await manager.initialize()
        
        # Index a chunk
        chunks = [
            MockMemoryChunk(
                hash="hash1",
                file_path="/test/file.md",
                start_line=1,
                end_line=10,
                text="Hello world",
                embedding_input="Hello world",
            )
        ]
        await manager.index_chunks(chunks)
        
        # Search for non-existent term
        results = await manager._bm25_search("nonexistent")
        
        assert results == []
        
        await manager.close()

    def test_merge_results_combines_scores(self):
        """Should combine vector and BM25 scores with weights."""
        manager = MemoryIndexManager(
            db_path="/tmp/test.db",
            vector_weight=0.7,
            text_weight=0.3,
        )
        
        vector_results = [("hash1", 0.9), ("hash2", 0.5)]
        bm25_results = [("hash1", 0.6), ("hash3", 0.8)]
        
        # Mock _build_search_results to avoid async issues
        with patch.object(manager, '_build_search_results') as mock_build:
            mock_build.return_value = []
            manager._merge_results(vector_results, bm25_results)
            
            # Verify the call was made with correct scoring
            call_args = mock_build.call_args[0][0]
            
            # hash1: 0.9 * 0.7 + 0.6 * 0.3 = 0.63 + 0.18 = 0.81
            # hash2: 0.5 * 0.7 + 0.0 * 0.3 = 0.35
            # hash3: 0.0 * 0.7 + 0.8 * 0.3 = 0.24
            
            scores = {item[0]: item[1] for item in call_args}
            assert abs(scores["hash1"] - 0.81) < 0.01
            assert abs(scores["hash2"] - 0.35) < 0.01
            assert abs(scores["hash3"] - 0.24) < 0.01


class TestMemoryIndexManagerDelete:
    """Tests for delete functionality."""

    @pytest.mark.asyncio
    async def test_delete_by_file_removes_chunks(self, tmp_path):
        """Should delete all chunks from specified file."""
        db_path = tmp_path / "test.db"
        manager = MemoryIndexManager(db_path=str(db_path), embedding_provider="none")
        await manager.initialize()
        
        # Index chunks from two files
        chunks = [
            MockMemoryChunk(
                hash="hash1",
                file_path="/test/file1.md",
                start_line=1,
                end_line=10,
                text="Content 1",
                embedding_input="Content 1",
            ),
            MockMemoryChunk(
                hash="hash2",
                file_path="/test/file1.md",
                start_line=11,
                end_line=20,
                text="Content 2",
                embedding_input="Content 2",
            ),
            MockMemoryChunk(
                hash="hash3",
                file_path="/test/file2.md",
                start_line=1,
                end_line=10,
                text="Content 3",
                embedding_input="Content 3",
            ),
        ]
        await manager.index_chunks(chunks)
        
        # Delete file1 chunks
        deleted = await manager.delete_by_file("/test/file1.md")
        
        assert deleted == 2
        
        # Verify only file2 chunks remain
        hashes = await manager.get_indexed_hashes()
        assert hashes == {"hash3"}
        
        await manager.close()

    @pytest.mark.asyncio
    async def test_delete_by_file_nonexistent(self, tmp_path):
        """Should return 0 when deleting non-existent file."""
        db_path = tmp_path / "test.db"
        manager = MemoryIndexManager(db_path=str(db_path), embedding_provider="none")
        await manager.initialize()
        
        deleted = await manager.delete_by_file("/nonexistent/file.md")
        
        assert deleted == 0
        
        await manager.close()


class TestMemoryIndexManagerGetIndexedHashes:
    """Tests for get_indexed_hashes."""

    @pytest.mark.asyncio
    async def test_get_indexed_hashes_empty(self, tmp_path):
        """Should return empty set when no chunks indexed."""
        db_path = tmp_path / "test.db"
        manager = MemoryIndexManager(db_path=str(db_path), embedding_provider="none")
        await manager.initialize()
        
        hashes = await manager.get_indexed_hashes()
        
        assert hashes == set()
        
        await manager.close()

    @pytest.mark.asyncio
    async def test_get_indexed_hashes_returns_all(self, tmp_path):
        """Should return all indexed hashes."""
        db_path = tmp_path / "test.db"
        manager = MemoryIndexManager(db_path=str(db_path), embedding_provider="none")
        await manager.initialize()
        
        chunks = [
            MockMemoryChunk(
                hash=f"hash{i}",
                file_path="/test/file.md",
                start_line=i,
                end_line=i + 10,
                text=f"Content {i}",
                embedding_input=f"Content {i}",
            )
            for i in range(5)
        ]
        await manager.index_chunks(chunks)
        
        hashes = await manager.get_indexed_hashes()
        
        assert hashes == {"hash0", "hash1", "hash2", "hash3", "hash4"}
        
        await manager.close()


class TestProviderFallback:
    """Tests for embedding provider fallback logic."""

    @pytest.mark.asyncio
    async def test_auto_falls_back_to_noop(self, tmp_path):
        """Auto mode should fall back to NoOp when others unavailable."""
        db_path = tmp_path / "test.db"
        manager = MemoryIndexManager(db_path=str(db_path), embedding_provider="auto")
        
        # Mock providers to be unavailable
        with patch.object(OpenAIEmbeddingProvider, 'is_available', return_value=False):
            with patch.object(OllamaEmbeddingProvider, 'is_available', return_value=False):
                await manager.initialize()
        
        assert manager.get_provider().name == "none"
        
        await manager.close()

    @pytest.mark.asyncio
    async def test_openai_falls_back_to_noop(self, tmp_path):
        """OpenAI mode should fall back to NoOp when unavailable."""
        db_path = tmp_path / "test.db"
        manager = MemoryIndexManager(db_path=str(db_path), embedding_provider="openai")
        
        with patch.object(OpenAIEmbeddingProvider, 'is_available', return_value=False):
            await manager.initialize()
        
        assert manager.get_provider().name == "none"
        
        await manager.close()
