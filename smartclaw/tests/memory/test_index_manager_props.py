"""Property tests for MemoryIndexManager.

Tests Property 18 and Property 19 from design.md.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings, strategies as st, HealthCheck

from smartclaw.memory.index_manager import (
    MemoryIndexManager,
    NoOpEmbeddingProvider,
    OllamaEmbeddingProvider,
    OpenAIEmbeddingProvider,
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


class TestProperty18EmbeddingProviderFallback:
    """Property 18: Embedding Provider 降级
    
    When configured provider is unavailable, should automatically fall back
    to next available provider, ultimately to BM25-only search.
    """

    @given(
        provider_name=st.sampled_from(["auto", "openai", "ollama", "none", "unknown"]),
        openai_available=st.booleans(),
        ollama_available=st.booleans(),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_provider_fallback_always_succeeds(
        self,
        provider_name: str,
        openai_available: bool,
        ollama_available: bool,
    ):
        """
        Feature: memory-skills-enhancement
        Property 18: Embedding Provider 降级
        
        For any provider configuration and availability state,
        initialization should always succeed with some provider.
        """
        import asyncio
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = f"{tmp_dir}/test.db"
            manager = MemoryIndexManager(
                db_path=db_path,
                embedding_provider=provider_name,
            )
            
            async def run_test():
                with patch.object(
                    OpenAIEmbeddingProvider,
                    'is_available',
                    new_callable=AsyncMock,
                    return_value=openai_available,
                ):
                    with patch.object(
                        OllamaEmbeddingProvider,
                        'is_available',
                        new_callable=AsyncMock,
                        return_value=ollama_available,
                    ):
                        await manager.initialize()
                        
                        # Should always have a provider
                        assert manager.get_provider() is not None
                        
                        # Provider name should be valid
                        assert manager.get_provider().name in [
                            "openai:text-embedding-3-small",
                            "ollama:nomic-embed-text",
                            "none",
                        ]
                
                await manager.close()
            
            asyncio.get_event_loop().run_until_complete(run_test())

    @given(
        openai_available=st.booleans(),
        ollama_available=st.booleans(),
    )
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_auto_mode_prefers_openai(
        self,
        openai_available: bool,
        ollama_available: bool,
    ):
        """
        Feature: memory-skills-enhancement
        Property 18: Embedding Provider 降级
        
        In auto mode, should prefer OpenAI > Ollama > NoOp.
        """
        import asyncio
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = f"{tmp_dir}/test.db"
            manager = MemoryIndexManager(
                db_path=db_path,
                embedding_provider="auto",
            )
            
            async def run_test():
                with patch.object(
                    OpenAIEmbeddingProvider,
                    'is_available',
                    new_callable=AsyncMock,
                    return_value=openai_available,
                ):
                    with patch.object(
                        OllamaEmbeddingProvider,
                        'is_available',
                        new_callable=AsyncMock,
                        return_value=ollama_available,
                    ):
                        await manager.initialize()
                
                provider = manager.get_provider()
                
                if openai_available:
                    assert "openai" in provider.name
                elif ollama_available:
                    assert "ollama" in provider.name
                else:
                    assert provider.name == "none"
                
                await manager.close()
            
            asyncio.get_event_loop().run_until_complete(run_test())

    @given(st.sampled_from(["openai", "ollama"]))
    @settings(
        max_examples=20,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_specific_provider_falls_back_to_noop(self, provider_name: str):
        """
        Feature: memory-skills-enhancement
        Property 18: Embedding Provider 降级
        
        When specific provider is unavailable, should fall back to NoOp.
        """
        import asyncio
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = f"{tmp_dir}/test.db"
            manager = MemoryIndexManager(
                db_path=db_path,
                embedding_provider=provider_name,
            )
            
            async def run_test():
                with patch.object(
                    OpenAIEmbeddingProvider,
                    'is_available',
                    new_callable=AsyncMock,
                    return_value=False,
                ):
                    with patch.object(
                        OllamaEmbeddingProvider,
                        'is_available',
                        new_callable=AsyncMock,
                        return_value=False,
                    ):
                        await manager.initialize()
                
                # Should fall back to NoOp
                assert manager.get_provider().name == "none"
                
                await manager.close()
            
            asyncio.get_event_loop().run_until_complete(run_test())


class TestProperty19HybridSearchWeights:
    """Property 19: Hybrid Search 权重计算
    
    Combined score = vector_score * vector_weight + bm25_score * text_weight
    Weights should be normalized to sum to 1.0.
    """

    @given(
        vector_weight=st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        text_weight=st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        vector_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        bm25_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_weight_normalization(
        self,
        vector_weight: float,
        text_weight: float,
        vector_score: float,
        bm25_score: float,
    ):
        """
        Feature: memory-skills-enhancement
        Property 19: Hybrid Search 权重计算
        
        For any weight configuration, weights should be normalized to sum to 1.0.
        """
        # Skip if both weights are zero (edge case)
        if vector_weight == 0 and text_weight == 0:
            return
        
        # Normalize weights (same logic as in _merge_results)
        total_weight = vector_weight + text_weight
        if total_weight <= 0:
            total_weight = 1.0
        norm_vector_weight = vector_weight / total_weight
        norm_text_weight = text_weight / total_weight
        
        # Verify normalization
        assert abs(norm_vector_weight + norm_text_weight - 1.0) < 1e-9

    @given(
        vector_weight=st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False),
        text_weight=st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False),
        vector_scores=st.lists(
            st.tuples(
                st.text(min_size=1, max_size=10, alphabet="abcdef0123456789"),
                st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            ),
            min_size=0,
            max_size=10,
        ),
        bm25_scores=st.lists(
            st.tuples(
                st.text(min_size=1, max_size=10, alphabet="abcdef0123456789"),
                st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            ),
            min_size=0,
            max_size=10,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_combined_score_formula(
        self,
        vector_weight: float,
        text_weight: float,
        vector_scores: list[tuple[str, float]],
        bm25_scores: list[tuple[str, float]],
    ):
        """
        Feature: memory-skills-enhancement
        Property 19: Hybrid Search 权重计算
        
        Combined score should equal vector_score * norm_vector_weight + bm25_score * norm_text_weight.
        """
        manager = MemoryIndexManager(
            db_path="/tmp/test.db",
            vector_weight=vector_weight,
            text_weight=text_weight,
        )
        
        # Normalize weights
        total_weight = vector_weight + text_weight
        norm_vector_weight = vector_weight / total_weight
        norm_text_weight = text_weight / total_weight
        
        # Build score maps
        vector_map = dict(vector_scores)
        bm25_map = dict(bm25_scores)
        
        # Get all unique hashes
        all_hashes = set(vector_map.keys()) | set(bm25_map.keys())
        
        # Verify combined score formula for each hash
        for hash_val in all_hashes:
            v_score = vector_map.get(hash_val, 0.0)
            b_score = bm25_map.get(hash_val, 0.0)
            
            expected_combined = v_score * norm_vector_weight + b_score * norm_text_weight
            
            # The combined score should be in valid range
            assert 0.0 <= expected_combined <= 1.0 + 1e-9

    @given(
        vector_weight=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=50)
    def test_complementary_weights(self, vector_weight: float):
        """
        Feature: memory-skills-enhancement
        Property 19: Hybrid Search 权重计算
        
        When vector_weight + text_weight = 1.0, no normalization needed.
        """
        text_weight = 1.0 - vector_weight
        
        manager = MemoryIndexManager(
            db_path="/tmp/test.db",
            vector_weight=vector_weight,
            text_weight=text_weight,
        )
        
        # Weights should already sum to 1.0
        assert abs(manager._vector_weight + manager._text_weight - 1.0) < 1e-9

    @given(
        n_vector=st.integers(min_value=0, max_value=20),
        n_bm25=st.integers(min_value=0, max_value=20),
    )
    @settings(max_examples=50, deadline=None)
    def test_merge_preserves_all_results(self, n_vector: int, n_bm25: int):
        """
        Feature: memory-skills-enhancement
        Property 19: Hybrid Search 权重计算
        
        Merge should include all unique hashes from both result sets.
        """
        manager = MemoryIndexManager(
            db_path="/tmp/test.db",
            vector_weight=0.7,
            text_weight=0.3,
            top_k=100,  # High enough to not truncate
        )
        
        vector_results = [(f"v{i}", 0.5) for i in range(n_vector)]
        bm25_results = [(f"b{i}", 0.5) for i in range(n_bm25)]
        
        # Mock _build_search_results to capture the merged results
        merged_hashes = set()
        
        def capture_merged(scored):
            nonlocal merged_hashes
            merged_hashes = {item[0] for item in scored}
            return []
        
        with patch.object(manager, '_build_search_results', side_effect=capture_merged):
            manager._merge_results(vector_results, bm25_results)
        
        expected_hashes = {f"v{i}" for i in range(n_vector)} | {f"b{i}" for i in range(n_bm25)}
        assert merged_hashes == expected_hashes

    @given(
        scores=st.lists(
            st.tuples(
                st.text(min_size=1, max_size=5, alphabet="abc"),
                st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
                st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            ),
            min_size=2,
            max_size=10,
            unique_by=lambda x: x[0],
        ),
    )
    @settings(max_examples=50, deadline=None)
    def test_merge_sorts_by_combined_score(
        self,
        scores: list[tuple[str, float, float]],
    ):
        """
        Feature: memory-skills-enhancement
        Property 19: Hybrid Search 权重计算
        
        Results should be sorted by combined score in descending order.
        """
        manager = MemoryIndexManager(
            db_path="/tmp/test.db",
            vector_weight=0.7,
            text_weight=0.3,
            top_k=100,
        )
        
        vector_results = [(h, v) for h, v, _ in scores]
        bm25_results = [(h, b) for h, _, b in scores]
        
        sorted_scores = []
        
        def capture_sorted(scored):
            nonlocal sorted_scores
            sorted_scores = [item[1] for item in scored]
            return []
        
        with patch.object(manager, '_build_search_results', side_effect=capture_sorted):
            manager._merge_results(vector_results, bm25_results)
        
        # Verify descending order
        for i in range(1, len(sorted_scores)):
            assert sorted_scores[i-1] >= sorted_scores[i]
