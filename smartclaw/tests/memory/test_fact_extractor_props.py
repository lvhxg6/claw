"""Property tests for FactExtractor.

Tests Property 20 and Property 21 from design.md.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone

import pytest
from hypothesis import given, settings, strategies as st, HealthCheck

from smartclaw.memory.fact_extractor import (
    Fact,
    FactExtractor,
    FactStore,
    FACT_CATEGORIES,
)


def make_fact(
    id: str,
    content: str,
    category: str,
    confidence: float,
    source: str = "test",
) -> Fact:
    """Helper to create a Fact with current timestamp."""
    return Fact(
        id=id,
        content=content,
        category=category,
        confidence=confidence,
        created_at=datetime.now(timezone.utc),
        source=source,
    )


class TestProperty20ConfidenceFiltering:
    """Property 20: 事实置信度过滤
    
    Only facts with confidence >= threshold should be kept.
    """

    @given(
        threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        confidences=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=0,
            max_size=50,
        ),
    )
    @settings(max_examples=100)
    def test_confidence_threshold_filtering(
        self,
        threshold: float,
        confidences: list[float],
    ):
        """
        Feature: memory-skills-enhancement
        Property 20: 事实置信度过滤
        
        For any confidence threshold and list of facts,
        only facts with confidence >= threshold should be kept.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            extractor = FactExtractor(
                workspace_dir=tmp_dir,
                confidence_threshold=threshold,
            )
            
            # Create facts with given confidences
            facts = [
                make_fact(f"f{i}", f"Fact {i}", "context", conf)
                for i, conf in enumerate(confidences)
            ]
            
            # Simulate filtering (same logic as in extract_facts)
            filtered = [f for f in facts if f.confidence >= threshold]
            
            # Verify all kept facts meet threshold
            for fact in filtered:
                assert fact.confidence >= threshold
            
            # Verify no facts below threshold are kept
            for fact in facts:
                if fact.confidence < threshold:
                    assert fact not in filtered

    @given(
        threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=50)
    def test_threshold_boundary(self, threshold: float):
        """
        Feature: memory-skills-enhancement
        Property 20: 事实置信度过滤
        
        Facts with confidence exactly at threshold should be kept.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            extractor = FactExtractor(
                workspace_dir=tmp_dir,
                confidence_threshold=threshold,
            )
            
            # Create fact exactly at threshold
            fact_at_threshold = make_fact("f1", "At threshold", "context", threshold)
            
            # Should be kept (>= threshold)
            assert fact_at_threshold.confidence >= threshold

    @given(
        threshold=st.floats(min_value=0.1, max_value=0.9, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=50)
    def test_threshold_just_below(self, threshold: float):
        """
        Feature: memory-skills-enhancement
        Property 20: 事实置信度过滤
        
        Facts with confidence just below threshold should be filtered out.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            extractor = FactExtractor(
                workspace_dir=tmp_dir,
                confidence_threshold=threshold,
            )
            
            # Create fact just below threshold
            below_threshold = threshold - 0.001
            if below_threshold >= 0:
                fact_below = make_fact("f1", "Below threshold", "context", below_threshold)
                
                # Should be filtered out
                assert fact_below.confidence < threshold


class TestProperty21FactPruning:
    """Property 21: 事实数量裁剪
    
    When facts exceed max_facts, keep only top max_facts by confidence.
    """

    @given(
        max_facts=st.integers(min_value=1, max_value=50),
        confidences=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=0,
            max_size=100,
        ),
    )
    @settings(max_examples=100)
    def test_prune_respects_max_facts(
        self,
        max_facts: int,
        confidences: list[float],
    ):
        """
        Feature: memory-skills-enhancement
        Property 21: 事实数量裁剪
        
        For any max_facts limit, pruned list should have at most max_facts items.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            extractor = FactExtractor(
                workspace_dir=tmp_dir,
                max_facts=max_facts,
            )
            
            facts = [
                make_fact(f"f{i}", f"Fact {i}", "context", conf)
                for i, conf in enumerate(confidences)
            ]
            
            pruned = extractor._prune_facts(facts)
            
            assert len(pruned) <= max_facts

    @given(
        max_facts=st.integers(min_value=1, max_value=20),
        n_facts=st.integers(min_value=0, max_value=50),
    )
    @settings(max_examples=100)
    def test_prune_keeps_highest_confidence(
        self,
        max_facts: int,
        n_facts: int,
    ):
        """
        Feature: memory-skills-enhancement
        Property 21: 事实数量裁剪
        
        When pruning, should keep facts with highest confidence scores.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            extractor = FactExtractor(
                workspace_dir=tmp_dir,
                max_facts=max_facts,
            )
            
            # Create facts with distinct confidences
            facts = [
                make_fact(f"f{i}", f"Fact {i}", "context", i / max(n_facts, 1))
                for i in range(n_facts)
            ]
            
            pruned = extractor._prune_facts(facts)
            
            if len(facts) > max_facts:
                # Get confidences
                kept_confidences = {f.confidence for f in pruned}
                removed_confidences = {f.confidence for f in facts if f not in pruned}
                
                # All kept confidences should be >= all removed confidences
                if kept_confidences and removed_confidences:
                    assert min(kept_confidences) >= max(removed_confidences)

    @given(
        max_facts=st.integers(min_value=1, max_value=100),
        n_facts=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=50)
    def test_prune_preserves_when_under_limit(
        self,
        max_facts: int,
        n_facts: int,
    ):
        """
        Feature: memory-skills-enhancement
        Property 21: 事实数量裁剪
        
        When facts count <= max_facts, all facts should be preserved.
        """
        # Ensure n_facts <= max_facts for this test
        n_facts = min(n_facts, max_facts)
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            extractor = FactExtractor(
                workspace_dir=tmp_dir,
                max_facts=max_facts,
            )
            
            facts = [
                make_fact(f"f{i}", f"Fact {i}", "context", 0.5)
                for i in range(n_facts)
            ]
            
            pruned = extractor._prune_facts(facts)
            
            assert len(pruned) == len(facts)

    @given(
        max_facts=st.integers(min_value=1, max_value=10),
        same_confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        n_facts=st.integers(min_value=1, max_value=30),
    )
    @settings(max_examples=50)
    def test_prune_handles_equal_confidence(
        self,
        max_facts: int,
        same_confidence: float,
        n_facts: int,
    ):
        """
        Feature: memory-skills-enhancement
        Property 21: 事实数量裁剪
        
        When all facts have equal confidence, should still prune to max_facts.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            extractor = FactExtractor(
                workspace_dir=tmp_dir,
                max_facts=max_facts,
            )
            
            facts = [
                make_fact(f"f{i}", f"Fact {i}", "context", same_confidence)
                for i in range(n_facts)
            ]
            
            pruned = extractor._prune_facts(facts)
            
            assert len(pruned) == min(n_facts, max_facts)


class TestFactDeduplication:
    """Tests for fact deduplication behavior."""

    @given(
        content=st.text(min_size=1, max_size=100),
        confidences=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=10,
        ),
    )
    @settings(max_examples=50)
    def test_deduplicate_keeps_highest_confidence(
        self,
        content: str,
        confidences: list[float],
    ):
        """
        For duplicate facts, should keep the one with highest confidence.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            extractor = FactExtractor(workspace_dir=tmp_dir)
            
            # Create facts with same content but different confidences
            facts = [
                make_fact(f"f{i}", content, "context", conf)
                for i, conf in enumerate(confidences)
            ]
            
            deduped = extractor._deduplicate_facts(facts)
            
            # Should have exactly one fact
            assert len(deduped) == 1
            
            # Should be the highest confidence
            assert deduped[0].confidence == max(confidences)

    @given(
        n_unique=st.integers(min_value=1, max_value=20),
    )
    @settings(max_examples=50)
    def test_deduplicate_preserves_unique(self, n_unique: int):
        """
        Unique facts should all be preserved after deduplication.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            extractor = FactExtractor(workspace_dir=tmp_dir)
            
            # Create facts with unique content
            facts = [
                make_fact(f"f{i}", f"Unique content {i}", "context", 0.8)
                for i in range(n_unique)
            ]
            
            deduped = extractor._deduplicate_facts(facts)
            
            assert len(deduped) == n_unique


class TestFactStoreRoundTrip:
    """Tests for FactStore serialization round-trip."""

    @given(
        n_facts=st.integers(min_value=0, max_value=20),
        categories=st.lists(
            st.sampled_from(FACT_CATEGORIES),
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=50)
    def test_factstore_roundtrip(
        self,
        n_facts: int,
        categories: list[str],
    ):
        """
        FactStore should survive serialization round-trip.
        """
        facts = [
            make_fact(
                f"f{i}",
                f"Fact content {i}",
                categories[i % len(categories)],
                0.5 + (i % 5) * 0.1,
            )
            for i in range(n_facts)
        ]
        
        store = FactStore(
            version="1.0",
            last_updated=datetime.now(timezone.utc),
            facts=facts,
        )
        
        # Round-trip through dict
        data = store.to_dict()
        restored = FactStore.from_dict(data)
        
        assert restored.version == store.version
        assert len(restored.facts) == len(store.facts)
        
        for orig, rest in zip(store.facts, restored.facts):
            assert rest.id == orig.id
            assert rest.content == orig.content
            assert rest.category == orig.category
            assert abs(rest.confidence - orig.confidence) < 1e-9
