"""FactExtractor — Extract structured facts from conversations using LLM.

Provides:
- Automatic fact extraction from conversation history
- Confidence scoring for extracted facts
- Fact deduplication and pruning
- Persistent storage in facts.json
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(component="memory.fact_extractor")

# Valid fact categories
FACT_CATEGORIES = ["preference", "project", "context", "personal", "technical"]

# Extraction prompt template
EXTRACTION_PROMPT = """\
Analyze the following conversation and extract structured facts about the user.
Focus on:
- User preferences (coding style, tools, languages)
- Project information (tech stack, architecture, goals)
- Work context (current tasks, deadlines, team)
- Personal information (name, role, timezone)
- Technical knowledge (expertise areas, learning goals)

For each fact, provide:
- content: The fact statement (concise, specific)
- category: One of {categories}
- confidence: 0.0-1.0 (how certain you are about this fact)

Return a JSON array of facts. Only include facts with confidence >= 0.5.

Conversation:
{conversation}

Response format:
[
  {{"content": "User prefers Python for backend development", "category": "preference", "confidence": 0.85}},
  ...
]
"""


@dataclass
class Fact:
    """Structured fact extracted from conversation."""
    
    id: str
    content: str
    category: str
    confidence: float
    created_at: datetime
    source: str  # Session ID
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "confidence": self.confidence,
            "createdAt": self.created_at.isoformat(),
            "source": self.source,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Fact":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            content=data["content"],
            category=data["category"],
            confidence=data["confidence"],
            created_at=datetime.fromisoformat(data["createdAt"]),
            source=data["source"],
        )


@dataclass
class FactStore:
    """Container for facts with metadata."""
    
    version: str = "1.0"
    last_updated: datetime = field(default_factory=datetime.utcnow)
    facts: list[Fact] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "version": self.version,
            "lastUpdated": self.last_updated.isoformat(),
            "facts": [f.to_dict() for f in self.facts],
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FactStore":
        """Create from dictionary."""
        return cls(
            version=data.get("version", "1.0"),
            last_updated=datetime.fromisoformat(data["lastUpdated"]),
            facts=[Fact.from_dict(f) for f in data.get("facts", [])],
        )


class FactExtractor:
    """Extract and manage facts from conversations.
    
    Uses LLM to analyze conversation history and extract structured facts
    about user preferences, project information, and work context.
    """

    def __init__(
        self,
        workspace_dir: str,
        model: str = "gpt-4o-mini",
        confidence_threshold: float = 0.7,
        max_facts: int = 100,
        enabled: bool = False,
    ) -> None:
        """Initialize fact extractor.
        
        Args:
            workspace_dir: Workspace directory path
            model: LLM model to use for extraction
            confidence_threshold: Minimum confidence to keep a fact (Property 20)
            max_facts: Maximum number of facts to store (Property 21)
            enabled: Whether fact extraction is enabled
        """
        self._workspace_dir = Path(workspace_dir).expanduser().resolve()
        self._model = model
        self._confidence_threshold = confidence_threshold
        self._max_facts = max_facts
        self._enabled = enabled
        
        self._facts_path = self._workspace_dir / ".smartclaw" / "facts.json"
        self._llm_client: Any = None

    async def _get_llm_client(self) -> Any:
        """Lazy initialize LLM client."""
        if self._llm_client is None:
            try:
                from openai import AsyncOpenAI
                self._llm_client = AsyncOpenAI()
            except ImportError:
                raise RuntimeError("openai package not installed")
        return self._llm_client

    async def extract_facts(
        self,
        messages: list[dict[str, Any]],
        session_id: str,
    ) -> list[Fact]:
        """Extract facts from conversation messages.
        
        Args:
            messages: List of conversation messages
            session_id: Session identifier for tracking fact source
            
        Returns:
            List of extracted Fact objects
        """
        if not self._enabled or not messages:
            return []

        try:
            # Build extraction prompt
            prompt = self._build_extraction_prompt(messages)
            
            # Call LLM
            client = await self._get_llm_client()
            response = await client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": "You are a fact extraction assistant. Extract structured facts from conversations."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            
            # Parse response
            content = response.choices[0].message.content
            raw_facts = json.loads(content)
            
            # Handle both array and object with "facts" key
            if isinstance(raw_facts, dict):
                raw_facts = raw_facts.get("facts", [])
            
            # Convert to Fact objects
            facts = []
            now = datetime.utcnow()
            for raw in raw_facts:
                if not isinstance(raw, dict):
                    continue
                    
                content_str = raw.get("content", "")
                category = raw.get("category", "context")
                confidence = float(raw.get("confidence", 0.0))
                
                # Validate category
                if category not in FACT_CATEGORIES:
                    category = "context"
                
                # Property 20: Filter by confidence threshold
                if confidence < self._confidence_threshold:
                    continue
                
                fact = Fact(
                    id=f"fact_{uuid.uuid4().hex[:12]}",
                    content=content_str,
                    category=category,
                    confidence=confidence,
                    created_at=now,
                    source=session_id,
                )
                facts.append(fact)
            
            logger.info(
                "facts_extracted",
                count=len(facts),
                session_id=session_id,
            )
            return facts
            
        except Exception as e:
            logger.error("fact_extraction_failed", error=str(e))
            return []

    def _build_extraction_prompt(self, messages: list[dict[str, Any]]) -> str:
        """Build the extraction prompt from messages.
        
        Args:
            messages: Conversation messages
            
        Returns:
            Formatted prompt string
        """
        # Format conversation
        conversation_lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                # Handle multi-part content
                content = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
            conversation_lines.append(f"{role}: {content}")
        
        conversation = "\n".join(conversation_lines)
        
        return EXTRACTION_PROMPT.format(
            categories=", ".join(FACT_CATEGORIES),
            conversation=conversation,
        )

    async def save_facts(self, facts: list[Fact]) -> None:
        """Save facts to facts.json.
        
        Merges with existing facts, deduplicates, and prunes.
        
        Args:
            facts: New facts to save
        """
        # Load existing facts
        store = await self.load_facts()
        
        # Merge new facts
        store.facts.extend(facts)
        
        # Deduplicate
        store.facts = self._deduplicate_facts(store.facts)
        
        # Prune to max_facts (Property 21)
        store.facts = self._prune_facts(store.facts)
        
        # Update timestamp
        store.last_updated = datetime.utcnow()
        
        # Write to file
        try:
            self._facts_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._facts_path, "w", encoding="utf-8") as f:
                json.dump(store.to_dict(), f, indent=2, ensure_ascii=False)
            
            logger.info(
                "facts_saved",
                path=str(self._facts_path),
                count=len(store.facts),
            )
        except Exception as e:
            logger.error("facts_save_failed", error=str(e))

    async def load_facts(self) -> FactStore:
        """Load facts from facts.json.
        
        Returns:
            FactStore with loaded facts, or empty store if file doesn't exist
        """
        if not self._facts_path.exists():
            return FactStore()
        
        try:
            with open(self._facts_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return FactStore.from_dict(data)
        except Exception as e:
            logger.warning("facts_load_failed", error=str(e))
            return FactStore()

    def _deduplicate_facts(self, facts: list[Fact]) -> list[Fact]:
        """Remove duplicate facts based on content similarity.
        
        Keeps the fact with higher confidence when duplicates found.
        
        Args:
            facts: List of facts to deduplicate
            
        Returns:
            Deduplicated list
        """
        seen: dict[str, Fact] = {}
        
        for fact in facts:
            # Normalize content for comparison
            key = fact.content.lower().strip()
            
            if key in seen:
                # Keep higher confidence
                if fact.confidence > seen[key].confidence:
                    seen[key] = fact
            else:
                seen[key] = fact
        
        return list(seen.values())

    def _prune_facts(self, facts: list[Fact]) -> list[Fact]:
        """Prune facts to max_facts limit.
        
        Property 21: Keep top max_facts by confidence score.
        
        Args:
            facts: List of facts to prune
            
        Returns:
            Pruned list with at most max_facts items
        """
        if len(facts) <= self._max_facts:
            return facts
        
        # Sort by confidence descending
        sorted_facts = sorted(facts, key=lambda f: f.confidence, reverse=True)
        
        # Keep top max_facts
        return sorted_facts[:self._max_facts]

    def get_facts_by_category(self, category: str) -> list[Fact]:
        """Get facts filtered by category (sync version for prompt building).
        
        Args:
            category: Category to filter by
            
        Returns:
            List of facts in the category
        """
        import asyncio
        store = asyncio.get_event_loop().run_until_complete(self.load_facts())
        return [f for f in store.facts if f.category == category]

    def build_facts_context(self) -> str:
        """Build facts context string for system prompt.
        
        Returns:
            Formatted facts context
        """
        import asyncio
        store = asyncio.get_event_loop().run_until_complete(self.load_facts())
        
        if not store.facts:
            return ""
        
        lines = ["## Known Facts About User\n"]
        
        # Group by category
        by_category: dict[str, list[Fact]] = {}
        for fact in store.facts:
            by_category.setdefault(fact.category, []).append(fact)
        
        for category in FACT_CATEGORIES:
            if category not in by_category:
                continue
            
            lines.append(f"### {category.title()}")
            for fact in by_category[category]:
                lines.append(f"- {fact.content}")
            lines.append("")
        
        return "\n".join(lines)

    @property
    def enabled(self) -> bool:
        """Check if fact extraction is enabled."""
        return self._enabled

    @property
    def confidence_threshold(self) -> float:
        """Get confidence threshold."""
        return self._confidence_threshold

    @property
    def max_facts(self) -> int:
        """Get max facts limit."""
        return self._max_facts
