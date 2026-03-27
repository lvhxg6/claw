"""Tests for FactExtractor."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from smartclaw.memory.fact_extractor import (
    Fact,
    FactExtractor,
    FactStore,
    FACT_CATEGORIES,
)


class TestFact:
    """Tests for Fact dataclass."""

    def test_fact_to_dict(self):
        """Should convert to dictionary correctly."""
        now = datetime(2024, 1, 15, 10, 30, 0)
        fact = Fact(
            id="fact_abc123",
            content="User prefers Python",
            category="preference",
            confidence=0.85,
            created_at=now,
            source="session_xyz",
        )
        
        result = fact.to_dict()
        
        assert result["id"] == "fact_abc123"
        assert result["content"] == "User prefers Python"
        assert result["category"] == "preference"
        assert result["confidence"] == 0.85
        assert result["createdAt"] == "2024-01-15T10:30:00"
        assert result["source"] == "session_xyz"

    def test_fact_from_dict(self):
        """Should create from dictionary correctly."""
        data = {
            "id": "fact_abc123",
            "content": "User prefers Python",
            "category": "preference",
            "confidence": 0.85,
            "createdAt": "2024-01-15T10:30:00",
            "source": "session_xyz",
        }
        
        fact = Fact.from_dict(data)
        
        assert fact.id == "fact_abc123"
        assert fact.content == "User prefers Python"
        assert fact.category == "preference"
        assert fact.confidence == 0.85
        assert fact.created_at == datetime(2024, 1, 15, 10, 30, 0)
        assert fact.source == "session_xyz"


class TestFactStore:
    """Tests for FactStore dataclass."""

    def test_factstore_to_dict(self):
        """Should convert to dictionary correctly."""
        now = datetime(2024, 1, 15, 10, 30, 0)
        fact = Fact(
            id="fact_1",
            content="Test fact",
            category="context",
            confidence=0.9,
            created_at=now,
            source="session_1",
        )
        store = FactStore(
            version="1.0",
            last_updated=now,
            facts=[fact],
        )
        
        result = store.to_dict()
        
        assert result["version"] == "1.0"
        assert result["lastUpdated"] == "2024-01-15T10:30:00"
        assert len(result["facts"]) == 1
        assert result["facts"][0]["id"] == "fact_1"

    def test_factstore_from_dict(self):
        """Should create from dictionary correctly."""
        data = {
            "version": "1.0",
            "lastUpdated": "2024-01-15T10:30:00",
            "facts": [
                {
                    "id": "fact_1",
                    "content": "Test fact",
                    "category": "context",
                    "confidence": 0.9,
                    "createdAt": "2024-01-15T10:30:00",
                    "source": "session_1",
                }
            ],
        }
        
        store = FactStore.from_dict(data)
        
        assert store.version == "1.0"
        assert len(store.facts) == 1
        assert store.facts[0].content == "Test fact"

    def test_factstore_empty(self):
        """Should handle empty facts list."""
        store = FactStore()
        
        assert store.version == "1.0"
        assert store.facts == []


class TestFactExtractorInit:
    """Tests for FactExtractor initialization."""

    def test_init_defaults(self, tmp_path):
        """Should initialize with default values."""
        extractor = FactExtractor(workspace_dir=str(tmp_path))
        
        assert extractor.confidence_threshold == 0.7
        assert extractor.max_facts == 100
        assert extractor.enabled is False

    def test_init_custom_values(self, tmp_path):
        """Should accept custom configuration."""
        extractor = FactExtractor(
            workspace_dir=str(tmp_path),
            model="gpt-4",
            confidence_threshold=0.8,
            max_facts=50,
            enabled=True,
        )
        
        assert extractor.confidence_threshold == 0.8
        assert extractor.max_facts == 50
        assert extractor.enabled is True


class TestFactExtractorDeduplicate:
    """Tests for fact deduplication."""

    def test_deduplicate_identical_content(self, tmp_path):
        """Should remove facts with identical content."""
        extractor = FactExtractor(workspace_dir=str(tmp_path))
        now = datetime.utcnow()
        
        facts = [
            Fact("f1", "User prefers Python", "preference", 0.8, now, "s1"),
            Fact("f2", "User prefers Python", "preference", 0.9, now, "s2"),
        ]
        
        result = extractor._deduplicate_facts(facts)
        
        assert len(result) == 1
        assert result[0].confidence == 0.9  # Higher confidence kept

    def test_deduplicate_case_insensitive(self, tmp_path):
        """Should treat different cases as duplicates."""
        extractor = FactExtractor(workspace_dir=str(tmp_path))
        now = datetime.utcnow()
        
        facts = [
            Fact("f1", "User prefers Python", "preference", 0.8, now, "s1"),
            Fact("f2", "user prefers python", "preference", 0.7, now, "s2"),
        ]
        
        result = extractor._deduplicate_facts(facts)
        
        assert len(result) == 1
        assert result[0].confidence == 0.8  # Higher confidence kept

    def test_deduplicate_different_content(self, tmp_path):
        """Should keep facts with different content."""
        extractor = FactExtractor(workspace_dir=str(tmp_path))
        now = datetime.utcnow()
        
        facts = [
            Fact("f1", "User prefers Python", "preference", 0.8, now, "s1"),
            Fact("f2", "User prefers TypeScript", "preference", 0.9, now, "s2"),
        ]
        
        result = extractor._deduplicate_facts(facts)
        
        assert len(result) == 2


class TestFactExtractorPrune:
    """Tests for fact pruning (Property 21)."""

    def test_prune_under_limit(self, tmp_path):
        """Should not prune when under limit."""
        extractor = FactExtractor(workspace_dir=str(tmp_path), max_facts=10)
        now = datetime.utcnow()
        
        facts = [
            Fact(f"f{i}", f"Fact {i}", "context", 0.5 + i * 0.05, now, "s1")
            for i in range(5)
        ]
        
        result = extractor._prune_facts(facts)
        
        assert len(result) == 5

    def test_prune_over_limit(self, tmp_path):
        """Should prune to max_facts when over limit."""
        extractor = FactExtractor(workspace_dir=str(tmp_path), max_facts=3)
        now = datetime.utcnow()
        
        facts = [
            Fact("f1", "Fact 1", "context", 0.7, now, "s1"),
            Fact("f2", "Fact 2", "context", 0.9, now, "s1"),
            Fact("f3", "Fact 3", "context", 0.8, now, "s1"),
            Fact("f4", "Fact 4", "context", 0.6, now, "s1"),
            Fact("f5", "Fact 5", "context", 0.95, now, "s1"),
        ]
        
        result = extractor._prune_facts(facts)
        
        assert len(result) == 3
        # Should keep highest confidence facts
        confidences = [f.confidence for f in result]
        assert 0.95 in confidences
        assert 0.9 in confidences
        assert 0.8 in confidences

    def test_prune_keeps_highest_confidence(self, tmp_path):
        """Should keep facts with highest confidence."""
        extractor = FactExtractor(workspace_dir=str(tmp_path), max_facts=2)
        now = datetime.utcnow()
        
        facts = [
            Fact("f1", "Low confidence", "context", 0.5, now, "s1"),
            Fact("f2", "High confidence", "context", 0.95, now, "s1"),
            Fact("f3", "Medium confidence", "context", 0.75, now, "s1"),
        ]
        
        result = extractor._prune_facts(facts)
        
        assert len(result) == 2
        contents = [f.content for f in result]
        assert "High confidence" in contents
        assert "Medium confidence" in contents
        assert "Low confidence" not in contents


class TestFactExtractorBuildPrompt:
    """Tests for extraction prompt building."""

    def test_build_prompt_simple(self, tmp_path):
        """Should build prompt from simple messages."""
        extractor = FactExtractor(workspace_dir=str(tmp_path))
        
        messages = [
            {"role": "user", "content": "I prefer Python for backend"},
            {"role": "assistant", "content": "Got it, Python is great!"},
        ]
        
        prompt = extractor._build_extraction_prompt(messages)
        
        assert "user: I prefer Python for backend" in prompt
        assert "assistant: Got it, Python is great!" in prompt
        assert "preference" in prompt  # Category should be in prompt

    def test_build_prompt_multipart_content(self, tmp_path):
        """Should handle multi-part content."""
        extractor = FactExtractor(workspace_dir=str(tmp_path))
        
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Part 1"},
                    {"type": "text", "text": "Part 2"},
                ],
            },
        ]
        
        prompt = extractor._build_extraction_prompt(messages)
        
        assert "Part 1" in prompt
        assert "Part 2" in prompt


class TestFactExtractorSaveLoad:
    """Tests for saving and loading facts."""

    @pytest.mark.asyncio
    async def test_save_facts_creates_file(self, tmp_path):
        """Should create facts.json file."""
        extractor = FactExtractor(workspace_dir=str(tmp_path))
        now = datetime.utcnow()
        
        facts = [
            Fact("f1", "Test fact", "context", 0.9, now, "s1"),
        ]
        
        await extractor.save_facts(facts)
        
        facts_path = tmp_path / ".smartclaw" / "facts.json"
        assert facts_path.exists()

    @pytest.mark.asyncio
    async def test_save_facts_content(self, tmp_path):
        """Should save facts with correct content."""
        extractor = FactExtractor(workspace_dir=str(tmp_path))
        now = datetime.utcnow()
        
        facts = [
            Fact("f1", "Test fact", "context", 0.9, now, "s1"),
        ]
        
        await extractor.save_facts(facts)
        
        facts_path = tmp_path / ".smartclaw" / "facts.json"
        with open(facts_path) as f:
            data = json.load(f)
        
        assert data["version"] == "1.0"
        assert len(data["facts"]) == 1
        assert data["facts"][0]["content"] == "Test fact"

    @pytest.mark.asyncio
    async def test_load_facts_empty(self, tmp_path):
        """Should return empty store when file doesn't exist."""
        extractor = FactExtractor(workspace_dir=str(tmp_path))
        
        store = await extractor.load_facts()
        
        assert store.facts == []

    @pytest.mark.asyncio
    async def test_load_facts_existing(self, tmp_path):
        """Should load existing facts."""
        # Create facts file
        facts_dir = tmp_path / ".smartclaw"
        facts_dir.mkdir(parents=True)
        facts_path = facts_dir / "facts.json"
        
        data = {
            "version": "1.0",
            "lastUpdated": "2024-01-15T10:30:00",
            "facts": [
                {
                    "id": "f1",
                    "content": "Existing fact",
                    "category": "preference",
                    "confidence": 0.85,
                    "createdAt": "2024-01-15T10:30:00",
                    "source": "s1",
                }
            ],
        }
        with open(facts_path, "w") as f:
            json.dump(data, f)
        
        extractor = FactExtractor(workspace_dir=str(tmp_path))
        store = await extractor.load_facts()
        
        assert len(store.facts) == 1
        assert store.facts[0].content == "Existing fact"

    @pytest.mark.asyncio
    async def test_save_merges_with_existing(self, tmp_path):
        """Should merge new facts with existing."""
        # Create existing facts
        facts_dir = tmp_path / ".smartclaw"
        facts_dir.mkdir(parents=True)
        facts_path = facts_dir / "facts.json"
        
        data = {
            "version": "1.0",
            "lastUpdated": "2024-01-15T10:30:00",
            "facts": [
                {
                    "id": "f1",
                    "content": "Existing fact",
                    "category": "preference",
                    "confidence": 0.85,
                    "createdAt": "2024-01-15T10:30:00",
                    "source": "s1",
                }
            ],
        }
        with open(facts_path, "w") as f:
            json.dump(data, f)
        
        # Save new fact
        extractor = FactExtractor(workspace_dir=str(tmp_path))
        now = datetime.utcnow()
        new_facts = [
            Fact("f2", "New fact", "context", 0.9, now, "s2"),
        ]
        
        await extractor.save_facts(new_facts)
        
        # Load and verify
        store = await extractor.load_facts()
        assert len(store.facts) == 2


class TestFactExtractorExtract:
    """Tests for fact extraction."""

    @pytest.mark.asyncio
    async def test_extract_disabled(self, tmp_path):
        """Should return empty when disabled."""
        extractor = FactExtractor(workspace_dir=str(tmp_path), enabled=False)
        
        messages = [{"role": "user", "content": "I prefer Python"}]
        result = await extractor.extract_facts(messages, "session_1")
        
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_empty_messages(self, tmp_path):
        """Should return empty for empty messages."""
        extractor = FactExtractor(workspace_dir=str(tmp_path), enabled=True)
        
        result = await extractor.extract_facts([], "session_1")
        
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_filters_low_confidence(self, tmp_path):
        """Should filter facts below confidence threshold (Property 20)."""
        extractor = FactExtractor(
            workspace_dir=str(tmp_path),
            enabled=True,
            confidence_threshold=0.7,
        )
        
        # Mock LLM response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps([
            {"content": "High confidence fact", "category": "preference", "confidence": 0.9},
            {"content": "Low confidence fact", "category": "preference", "confidence": 0.5},
        ])
        
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        
        with patch.object(extractor, '_get_llm_client', return_value=mock_client):
            messages = [{"role": "user", "content": "Test message"}]
            result = await extractor.extract_facts(messages, "session_1")
        
        assert len(result) == 1
        assert result[0].content == "High confidence fact"


class TestFactExtractorBuildContext:
    """Tests for building facts context."""

    def test_build_context_empty(self, tmp_path):
        """Should return empty string when no facts."""
        extractor = FactExtractor(workspace_dir=str(tmp_path))
        
        with patch.object(extractor, 'load_facts', return_value=FactStore()):
            import asyncio
            # Mock the async load
            with patch('asyncio.get_event_loop') as mock_loop:
                mock_loop.return_value.run_until_complete.return_value = FactStore()
                result = extractor.build_facts_context()
        
        assert result == ""

    def test_build_context_with_facts(self, tmp_path):
        """Should format facts by category."""
        extractor = FactExtractor(workspace_dir=str(tmp_path))
        now = datetime.utcnow()
        
        store = FactStore(facts=[
            Fact("f1", "Prefers Python", "preference", 0.9, now, "s1"),
            Fact("f2", "Uses VS Code", "preference", 0.85, now, "s1"),
            Fact("f3", "Working on SmartClaw", "project", 0.8, now, "s1"),
        ])
        
        with patch('asyncio.get_event_loop') as mock_loop:
            mock_loop.return_value.run_until_complete.return_value = store
            result = extractor.build_facts_context()
        
        assert "Known Facts About User" in result
        assert "Preference" in result
        assert "Prefers Python" in result
        assert "Project" in result
        assert "Working on SmartClaw" in result
