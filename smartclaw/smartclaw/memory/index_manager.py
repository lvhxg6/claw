"""MemoryIndexManager — Vector and BM25 hybrid search for memory chunks.

Provides:
- EmbeddingProvider abstraction for different embedding backends
- Hybrid search combining vector similarity and BM25 keyword search
- Automatic provider fallback when primary provider is unavailable
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiosqlite
import structlog

from smartclaw.memory.schema import (
    initialize_memory_schema,
    initialize_fts_schema,
    initialize_vector_schema,
)

if TYPE_CHECKING:
    from smartclaw.memory.loader import MemoryChunk

logger = structlog.get_logger(component="memory.index_manager")


@dataclass
class SearchResult:
    """Search result from hybrid search."""
    
    chunk_hash: str
    file_path: str
    text: str
    score: float  # Combined score
    vector_score: float
    bm25_score: float


# ---------------------------------------------------------------------------
# Embedding Providers
# ---------------------------------------------------------------------------

class EmbeddingProvider(ABC):
    """Base class for embedding providers."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Convert texts to embedding vectors.
        
        Args:
            texts: List of text strings to embed
            
        Returns:
            List of embedding vectors
        """
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Vector dimension for this provider."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging."""
        ...

    async def is_available(self) -> bool:
        """Check if provider is available.
        
        Returns:
            True if provider can be used
        """
        try:
            # Try a simple embedding to check availability
            await self.embed(["test"])
            return True
        except Exception:
            return False


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embedding provider using text-embedding-3-small."""

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._client: Any = None

    async def _get_client(self) -> Any:
        """Lazy initialize OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(api_key=self._api_key)
            except ImportError:
                raise RuntimeError("openai package not installed")
        return self._client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using OpenAI API."""
        client = await self._get_client()
        response = await client.embeddings.create(
            model=self._model,
            input=texts,
        )
        return [item.embedding for item in response.data]

    @property
    def dimension(self) -> int:
        return 1536

    @property
    def name(self) -> str:
        return f"openai:{self._model}"


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Ollama local embedding provider."""

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
    ) -> None:
        self._model = model
        self._base_url = base_url

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using Ollama API."""
        try:
            import httpx
        except ImportError:
            raise RuntimeError("httpx package not installed")

        embeddings = []
        async with httpx.AsyncClient(timeout=60.0) as client:
            for text in texts:
                response = await client.post(
                    f"{self._base_url}/api/embeddings",
                    json={"model": self._model, "prompt": text},
                )
                response.raise_for_status()
                data = response.json()
                embeddings.append(data["embedding"])
        return embeddings

    @property
    def dimension(self) -> int:
        return 768  # nomic-embed-text dimension

    @property
    def name(self) -> str:
        return f"ollama:{self._model}"


class NoOpEmbeddingProvider(EmbeddingProvider):
    """No-op provider for BM25-only mode."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return empty embeddings."""
        return [[] for _ in texts]

    @property
    def dimension(self) -> int:
        return 0

    @property
    def name(self) -> str:
        return "none"

    async def is_available(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# MemoryIndexManager
# ---------------------------------------------------------------------------

class MemoryIndexManager:
    """Memory index manager for hybrid search.
    
    Combines vector similarity search (sqlite-vec) with BM25 keyword search
    (FTS5) for optimal retrieval quality.
    """

    def __init__(
        self,
        db_path: str = "~/.smartclaw/memory.db",
        embedding_provider: str = "auto",
        vector_weight: float = 0.7,
        text_weight: float = 0.3,
        top_k: int = 5,
    ) -> None:
        """Initialize index manager.
        
        Args:
            db_path: Path to SQLite database
            embedding_provider: Provider name ("auto", "openai", "ollama", "none")
            vector_weight: Weight for vector search results (0.0-1.0)
            text_weight: Weight for BM25 search results (0.0-1.0)
            top_k: Number of results to return
        """
        self._db_path = Path(db_path).expanduser().resolve()
        self._embedding_provider_name = embedding_provider
        self._vector_weight = vector_weight
        self._text_weight = text_weight
        self._top_k = top_k

        self._db: aiosqlite.Connection | None = None
        self._provider: EmbeddingProvider | None = None
        self._vector_enabled: bool = False

    async def initialize(self) -> None:
        """Initialize database and embedding provider."""
        # Create database directory
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Connect to database
        self._db = await aiosqlite.connect(str(self._db_path))
        
        # Initialize schema
        await initialize_memory_schema(self._db)
        await initialize_fts_schema(self._db)
        
        # Try to initialize vector schema
        self._vector_enabled = await initialize_vector_schema(self._db)
        if not self._vector_enabled:
            logger.warning("sqlite_vec_not_available", fallback="bm25_only")
        
        # Initialize embedding provider
        self._provider = await self._create_provider()
        
        logger.info(
            "index_manager_initialized",
            db_path=str(self._db_path),
            provider=self._provider.name,
            vector_enabled=self._vector_enabled,
        )

    async def close(self) -> None:
        """Close database connection."""
        if self._db is not None:
            await self._db.close()
            self._db = None
            logger.debug("index_manager_closed")

    async def _create_provider(self) -> EmbeddingProvider:
        """Create embedding provider with fallback logic.
        
        Property 18: Embedding Provider 降级
        When configured provider is unavailable, falls back to next available.
        """
        providers_to_try: list[EmbeddingProvider] = []
        
        if self._embedding_provider_name == "auto":
            # Try OpenAI first, then Ollama, then none
            providers_to_try = [
                OpenAIEmbeddingProvider(),
                OllamaEmbeddingProvider(),
                NoOpEmbeddingProvider(),
            ]
        elif self._embedding_provider_name == "openai":
            providers_to_try = [
                OpenAIEmbeddingProvider(),
                NoOpEmbeddingProvider(),
            ]
        elif self._embedding_provider_name == "ollama":
            providers_to_try = [
                OllamaEmbeddingProvider(),
                NoOpEmbeddingProvider(),
            ]
        else:
            # "none" or unknown
            providers_to_try = [NoOpEmbeddingProvider()]

        for provider in providers_to_try:
            if await provider.is_available():
                logger.info("embedding_provider_selected", provider=provider.name)
                return provider
            else:
                logger.warning(
                    "embedding_provider_unavailable",
                    provider=provider.name,
                )

        # Should never reach here since NoOpEmbeddingProvider is always available
        return NoOpEmbeddingProvider()

    async def index_chunks(self, chunks: list["MemoryChunk"]) -> int:
        """Index memory chunks for search.
        
        Args:
            chunks: List of MemoryChunk objects to index
            
        Returns:
            Number of chunks indexed
        """
        if not self._db or not chunks:
            return 0

        indexed = 0
        for chunk in chunks:
            try:
                # Insert into memory_chunks (FTS triggers will sync)
                await self._db.execute(
                    """INSERT OR REPLACE INTO memory_chunks
                       (hash, file_path, start_line, end_line, text, embedding_input, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                    (
                        chunk.hash,
                        chunk.file_path,
                        chunk.start_line,
                        chunk.end_line,
                        chunk.text,
                        chunk.embedding_input,
                    ),
                )
                indexed += 1
            except Exception as e:
                logger.warning(
                    "chunk_index_failed",
                    hash=chunk.hash,
                    error=str(e),
                )

        await self._db.commit()
        
        # Index embeddings if vector search is enabled
        if self._vector_enabled and self._provider and self._provider.name != "none":
            await self._index_embeddings(chunks)

        logger.info("chunks_indexed", count=indexed)
        return indexed

    async def _index_embeddings(self, chunks: list["MemoryChunk"]) -> None:
        """Index chunk embeddings for vector search."""
        if not self._provider or not self._db:
            return

        try:
            texts = [c.embedding_input for c in chunks]
            embeddings = await self._provider.embed(texts)
            
            for chunk, embedding in zip(chunks, embeddings):
                if embedding:
                    # sqlite-vec insert
                    await self._db.execute(
                        """INSERT OR REPLACE INTO memory_embeddings (hash, embedding)
                           VALUES (?, ?)""",
                        (chunk.hash, embedding),
                    )
            
            await self._db.commit()
        except Exception as e:
            logger.warning("embedding_index_failed", error=str(e))

    async def search(self, query: str) -> list[SearchResult]:
        """Hybrid search combining vector and BM25.
        
        Property 19: Hybrid Search 权重计算
        Combined score = vector_score * vector_weight + bm25_score * text_weight
        
        Args:
            query: Search query text
            
        Returns:
            List of SearchResult sorted by combined score
        """
        if not self._db:
            return []

        # Run both searches
        vector_results = await self._vector_search(query)
        bm25_results = await self._bm25_search(query)

        # Merge results
        return self._merge_results(vector_results, bm25_results)

    async def _vector_search(self, query: str) -> list[tuple[str, float]]:
        """Vector similarity search.
        
        Returns:
            List of (hash, score) tuples
        """
        if not self._vector_enabled or not self._provider or self._provider.name == "none":
            return []

        try:
            embeddings = await self._provider.embed([query])
            if not embeddings or not embeddings[0]:
                return []

            query_embedding = embeddings[0]
            
            # sqlite-vec KNN search
            cursor = await self._db.execute(
                """SELECT hash, distance
                   FROM memory_embeddings
                   WHERE embedding MATCH ?
                   ORDER BY distance
                   LIMIT ?""",
                (query_embedding, self._top_k * 2),
            )
            rows = await cursor.fetchall()
            
            # Convert distance to similarity score (1 - normalized_distance)
            results = []
            for hash_val, distance in rows:
                # Cosine distance is typically 0-2, normalize to 0-1 similarity
                score = max(0.0, 1.0 - distance / 2.0)
                results.append((hash_val, score))
            
            return results
        except Exception as e:
            logger.warning("vector_search_failed", error=str(e))
            return []

    async def _bm25_search(self, query: str) -> list[tuple[str, float]]:
        """BM25 keyword search using FTS5.
        
        Returns:
            List of (hash, score) tuples
        """
        if not self._db:
            return []

        try:
            # FTS5 BM25 search
            cursor = await self._db.execute(
                """SELECT hash, bm25(memory_fts) as score
                   FROM memory_fts
                   WHERE memory_fts MATCH ?
                   ORDER BY score
                   LIMIT ?""",
                (query, self._top_k * 2),
            )
            rows = await cursor.fetchall()
            
            # BM25 scores are negative (lower is better), convert to positive
            results = []
            for hash_val, score in rows:
                # Normalize: BM25 scores are typically -10 to 0
                normalized = min(1.0, max(0.0, -score / 10.0))
                results.append((hash_val, normalized))
            
            return results
        except Exception as e:
            logger.warning("bm25_search_failed", error=str(e))
            return []

    def _merge_results(
        self,
        vector_results: list[tuple[str, float]],
        bm25_results: list[tuple[str, float]],
    ) -> list[SearchResult]:
        """Merge vector and BM25 results with weighted scoring.
        
        Property 19: Combined score = vector_score * vector_weight + bm25_score * text_weight
        """
        # Normalize weights
        total_weight = self._vector_weight + self._text_weight
        if total_weight <= 0:
            total_weight = 1.0
        norm_vector_weight = self._vector_weight / total_weight
        norm_text_weight = self._text_weight / total_weight

        # Build score maps
        vector_scores: dict[str, float] = dict(vector_results)
        bm25_scores: dict[str, float] = dict(bm25_results)
        
        # Get all unique hashes
        all_hashes = set(vector_scores.keys()) | set(bm25_scores.keys())
        
        # Calculate combined scores
        combined: list[tuple[str, float, float, float]] = []
        for hash_val in all_hashes:
            v_score = vector_scores.get(hash_val, 0.0)
            b_score = bm25_scores.get(hash_val, 0.0)
            combined_score = v_score * norm_vector_weight + b_score * norm_text_weight
            combined.append((hash_val, combined_score, v_score, b_score))
        
        # Sort by combined score descending
        combined.sort(key=lambda x: x[1], reverse=True)
        
        # Fetch chunk details and build results
        return asyncio.get_event_loop().run_until_complete(
            self._build_search_results(combined[:self._top_k])
        )

    async def _build_search_results(
        self,
        scored: list[tuple[str, float, float, float]],
    ) -> list[SearchResult]:
        """Build SearchResult objects from scored hashes."""
        if not self._db or not scored:
            return []

        results = []
        for hash_val, combined_score, v_score, b_score in scored:
            cursor = await self._db.execute(
                """SELECT file_path, text FROM memory_chunks WHERE hash = ?""",
                (hash_val,),
            )
            row = await cursor.fetchone()
            if row:
                results.append(SearchResult(
                    chunk_hash=hash_val,
                    file_path=row[0],
                    text=row[1],
                    score=combined_score,
                    vector_score=v_score,
                    bm25_score=b_score,
                ))
        
        return results

    async def delete_by_file(self, file_path: str) -> int:
        """Delete all chunks from a specific file.
        
        Args:
            file_path: Path of file to delete chunks for
            
        Returns:
            Number of chunks deleted
        """
        if not self._db:
            return 0

        # Get hashes to delete
        cursor = await self._db.execute(
            "SELECT hash FROM memory_chunks WHERE file_path = ?",
            (file_path,),
        )
        hashes = [row[0] for row in await cursor.fetchall()]
        
        if not hashes:
            return 0

        # Delete from memory_chunks (FTS triggers will sync)
        await self._db.execute(
            "DELETE FROM memory_chunks WHERE file_path = ?",
            (file_path,),
        )
        
        # Delete from embeddings if vector enabled
        if self._vector_enabled:
            placeholders = ",".join("?" * len(hashes))
            await self._db.execute(
                f"DELETE FROM memory_embeddings WHERE hash IN ({placeholders})",
                hashes,
            )
        
        await self._db.commit()
        logger.info("chunks_deleted", file_path=file_path, count=len(hashes))
        return len(hashes)

    async def get_indexed_hashes(self) -> set[str]:
        """Get all indexed chunk hashes.
        
        Returns:
            Set of chunk hashes
        """
        if not self._db:
            return set()

        cursor = await self._db.execute("SELECT hash FROM memory_chunks")
        return {row[0] for row in await cursor.fetchall()}

    def get_provider(self) -> EmbeddingProvider | None:
        """Get current embedding provider."""
        return self._provider

    def is_vector_enabled(self) -> bool:
        """Check if vector search is enabled."""
        return self._vector_enabled
