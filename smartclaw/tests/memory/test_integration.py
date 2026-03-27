"""Integration tests for memory-skills-enhancement components.

Tests the integration of:
- MemoryLoader
- BootstrapLoader
- SkillsWatcher
- MemoryIndexManager
- FactExtractor
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@dataclass
class MockSettings:
    """Mock settings for testing."""
    
    @dataclass
    class AgentDefaults:
        workspace: str = "/tmp/test_workspace"
    
    @dataclass
    class Memory:
        enabled: bool = True
        db_path: str = "~/.smartclaw/test_memory.db"
        memory_file_enabled: bool = True
        chunk_tokens: int = 512
        chunk_overlap: int = 64
        summary_threshold: int = 10
        keep_recent: int = 5
        summarize_token_percent: float = 0.8
        context_window: int = 4096
    
    @dataclass
    class Skills:
        enabled: bool = True
        workspace_dir: str = "{workspace}/skills"
        global_dir: str = "~/.smartclaw/skills"
        hot_reload: bool = False
        debounce_ms: int = 250
    
    @dataclass
    class Bootstrap:
        enabled: bool = True
        global_dir: str = "~/.smartclaw"
    
    @dataclass
    class MCP:
        enabled: bool = False
    
    @dataclass
    class SubAgent:
        enabled: bool = False
        max_concurrent: int = 2
        max_depth: int = 3
        default_timeout_seconds: int = 60
        concurrency_timeout_seconds: int = 30
    
    @dataclass
    class Model:
        primary: str = "openai/gpt-4o-mini"
        fallbacks: list = None
        
        def __post_init__(self):
            if self.fallbacks is None:
                self.fallbacks = []
    
    agent_defaults: AgentDefaults = None
    memory: Memory = None
    skills: Skills = None
    bootstrap: Bootstrap = None
    mcp: MCP = None
    sub_agent: SubAgent = None
    model: Model = None
    providers: dict = None
    
    def __post_init__(self):
        if self.agent_defaults is None:
            self.agent_defaults = self.AgentDefaults()
        if self.memory is None:
            self.memory = self.Memory()
        if self.skills is None:
            self.skills = self.Skills()
        if self.bootstrap is None:
            self.bootstrap = self.Bootstrap()
        if self.mcp is None:
            self.mcp = self.MCP()
        if self.sub_agent is None:
            self.sub_agent = self.SubAgent()
        if self.model is None:
            self.model = self.Model()


class TestMemoryLoaderIntegration:
    """Integration tests for MemoryLoader."""

    def test_memory_loader_with_memory_md(self, tmp_path):
        """Should load MEMORY.md and build context."""
        from smartclaw.memory.loader import MemoryLoader
        
        # Create MEMORY.md
        memory_file = tmp_path / "MEMORY.md"
        memory_file.write_text("# My Memory\n\n- Fact 1\n- Fact 2")
        
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        context = loader.build_memory_context()
        
        assert "My Memory" in context
        assert "Fact 1" in context

    def test_memory_loader_with_memory_dir(self, tmp_path):
        """Should scan memory/ directory."""
        from smartclaw.memory.loader import MemoryLoader
        
        # Create memory directory with files
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "notes.md").write_text("# Notes\n\nSome notes here")
        (memory_dir / "projects.md").write_text("# Projects\n\nProject info")
        
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        files = loader.load_memory_dir()
        
        assert len(files) == 2

    def test_memory_loader_chunking(self, tmp_path):
        """Should chunk large content."""
        from smartclaw.memory.loader import MemoryLoader
        
        # Create large MEMORY.md
        content = "# Memory\n\n" + "This is a test paragraph. " * 500
        memory_file = tmp_path / "MEMORY.md"
        memory_file.write_text(content)
        
        loader = MemoryLoader(workspace_dir=str(tmp_path), chunk_tokens=100)
        chunks = loader.chunk_markdown(content, str(memory_file))
        
        assert len(chunks) > 1


class TestBootstrapLoaderIntegration:
    """Integration tests for BootstrapLoader."""

    def test_bootstrap_loader_soul_md(self, tmp_path):
        """Should load SOUL.md content."""
        from smartclaw.bootstrap.loader import BootstrapLoader
        
        # Create SOUL.md
        soul_file = tmp_path / "SOUL.md"
        soul_file.write_text("# Agent Personality\n\nI am helpful and friendly.")
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        loader.load_all()
        
        content = loader.get_soul_content()
        assert "Agent Personality" in content
        assert "helpful and friendly" in content

    def test_bootstrap_loader_user_md(self, tmp_path):
        """Should load USER.md content."""
        from smartclaw.bootstrap.loader import BootstrapLoader
        
        # Create USER.md
        user_file = tmp_path / "USER.md"
        user_file.write_text("# User Info\n\nName: Test User\nRole: Developer")
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        loader.load_all()
        
        content = loader.get_user_content()
        assert "User Info" in content
        assert "Test User" in content

    def test_bootstrap_loader_priority(self, tmp_path):
        """Workspace files should override global files."""
        from smartclaw.bootstrap.loader import BootstrapLoader
        
        # Create global SOUL.md
        global_dir = tmp_path / "global"
        global_dir.mkdir()
        (global_dir / "SOUL.md").write_text("# Global Soul")
        
        # Create workspace SOUL.md
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        (workspace_dir / "SOUL.md").write_text("# Workspace Soul")
        
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        loader.load_all()
        
        content = loader.get_soul_content()
        assert "Workspace Soul" in content
        assert "Global Soul" not in content


class TestSkillsWatcherIntegration:
    """Integration tests for SkillsWatcher."""

    def test_skills_watcher_start_stop(self, tmp_path):
        """Should start and stop without errors."""
        from smartclaw.skills.watcher import SkillsWatcher
        
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        
        watcher = SkillsWatcher(
            workspace_dir=str(skills_dir),
            enabled=True,
        )
        
        watcher.start()
        assert watcher._observer is not None
        
        watcher.stop()
        assert watcher._observer is None

    def test_skills_watcher_version_increment(self, tmp_path):
        """Version should increment on reload."""
        from smartclaw.skills.watcher import SkillsWatcher
        
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        
        watcher = SkillsWatcher(
            workspace_dir=str(skills_dir),
            enabled=True,
        )
        
        v1 = watcher.get_version()
        watcher._bump_version()
        v2 = watcher.get_version()
        
        assert v2 > v1


class TestMemoryIndexManagerIntegration:
    """Integration tests for MemoryIndexManager."""

    @pytest.mark.asyncio
    async def test_index_and_search(self, tmp_path):
        """Should index chunks and search."""
        from smartclaw.memory.index_manager import MemoryIndexManager
        from smartclaw.memory.loader import MemoryChunk
        
        db_path = tmp_path / "test.db"
        manager = MemoryIndexManager(
            db_path=str(db_path),
            embedding_provider="none",
        )
        
        await manager.initialize()
        
        # Create test chunks
        chunks = [
            MemoryChunk(
                file_path="/test/file.md",
                start_line=1,
                end_line=10,
                text="Python programming language tutorial",
                hash="hash1",
                embedding_input="Python programming language tutorial",
            ),
            MemoryChunk(
                file_path="/test/file.md",
                start_line=11,
                end_line=20,
                text="JavaScript web development guide",
                hash="hash2",
                embedding_input="JavaScript web development guide",
            ),
        ]
        
        # Index chunks
        indexed = await manager.index_chunks(chunks)
        assert indexed == 2
        
        # Search
        results = await manager._bm25_search("Python")
        assert len(results) >= 1
        
        await manager.close()


class TestFactExtractorIntegration:
    """Integration tests for FactExtractor."""

    @pytest.mark.asyncio
    async def test_save_and_load_facts(self, tmp_path):
        """Should save and load facts."""
        from smartclaw.memory.fact_extractor import Fact, FactExtractor
        
        extractor = FactExtractor(
            workspace_dir=str(tmp_path),
            enabled=True,
        )
        
        # Create test facts
        now = datetime.now(timezone.utc)
        facts = [
            Fact(
                id="fact_1",
                content="User prefers Python",
                category="preference",
                confidence=0.9,
                created_at=now,
                source="session_1",
            ),
        ]
        
        # Save
        await extractor.save_facts(facts)
        
        # Load
        store = await extractor.load_facts()
        
        assert len(store.facts) == 1
        assert store.facts[0].content == "User prefers Python"

    def test_prune_facts(self, tmp_path):
        """Should prune facts to max limit."""
        from smartclaw.memory.fact_extractor import Fact, FactExtractor
        
        extractor = FactExtractor(
            workspace_dir=str(tmp_path),
            max_facts=3,
        )
        
        now = datetime.now(timezone.utc)
        facts = [
            Fact(f"f{i}", f"Fact {i}", "context", 0.5 + i * 0.1, now, "s1")
            for i in range(5)
        ]
        
        pruned = extractor._prune_facts(facts)
        
        assert len(pruned) == 3
        # Should keep highest confidence
        confidences = [f.confidence for f in pruned]
        assert max(confidences) == 0.9


class TestSystemPromptIntegration:
    """Integration tests for system prompt building."""

    def test_prompt_with_all_components(self, tmp_path):
        """System prompt should include all components."""
        from smartclaw.bootstrap.loader import BootstrapLoader
        from smartclaw.memory.loader import MemoryLoader
        
        # Create SOUL.md
        (tmp_path / "SOUL.md").write_text("# Soul\nI am SmartClaw.")
        
        # Create USER.md
        (tmp_path / "USER.md").write_text("# User\nName: Test")
        
        # Create MEMORY.md
        (tmp_path / "MEMORY.md").write_text("# Memory\n- Remember this")
        
        # Load components
        bootstrap = BootstrapLoader(workspace_dir=str(tmp_path))
        bootstrap.load_all()
        
        memory = MemoryLoader(workspace_dir=str(tmp_path))
        memory_context = memory.build_memory_context()
        
        # Build prompt parts
        soul = bootstrap.get_soul_content()
        user = bootstrap.get_user_content()
        
        # Verify all parts present
        assert "Soul" in soul
        assert "User" in user
        assert "Memory" in memory_context


class TestEndToEndIntegration:
    """End-to-end integration tests."""

    def test_full_memory_pipeline(self, tmp_path):
        """Test full memory loading and indexing pipeline."""
        from smartclaw.memory.loader import MemoryLoader
        
        # Setup workspace
        (tmp_path / "MEMORY.md").write_text("# Project Memory\n\n## Tech Stack\n- Python\n- FastAPI")
        
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "notes.md").write_text("# Development Notes\n\nImportant notes here.")
        
        # Load memory
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        # Load MEMORY.md
        content = loader.load_memory_md()
        assert content is not None
        assert "Tech Stack" in content
        
        # Load memory directory
        files = loader.load_memory_dir()
        assert len(files) == 1
        
        # Build context
        context = loader.build_memory_context()
        assert "Project Memory" in context

    def test_full_bootstrap_pipeline(self, tmp_path):
        """Test full bootstrap loading pipeline."""
        from smartclaw.bootstrap.loader import BootstrapLoader, BootstrapFileType
        
        # Setup workspace
        (tmp_path / "SOUL.md").write_text("# Agent Soul\n\nCore values here.")
        (tmp_path / "USER.md").write_text("# User Profile\n\nUser info here.")
        (tmp_path / "TOOLS.md").write_text("# Tool Guidelines\n\nTool usage here.")
        
        # Load bootstrap
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        files = loader.load_all()
        
        assert BootstrapFileType.SOUL in files
        assert BootstrapFileType.USER in files
        assert BootstrapFileType.TOOLS in files
        
        # Get content
        assert "Agent Soul" in loader.get_soul_content()
        assert "User Profile" in loader.get_user_content()
        assert "Tool Guidelines" in loader.get_tools_content()
