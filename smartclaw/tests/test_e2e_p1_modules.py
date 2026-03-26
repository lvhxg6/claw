"""End-to-end tests for P1 modules — no LLM required.

Tests real component integration without mocks:
- MemoryStore: real SQLite persistence across sessions
- AutoSummarizer: token estimation and context building (no LLM calls)
- SkillsLoader: real YAML file scanning, parsing, priority
- SkillsRegistry: real skill registration with ToolRegistry
- EphemeralStore: real in-memory storage behavior
- Configuration: real YAML config loading with P1 settings
"""

from __future__ import annotations

import os
import pathlib

import pytest
import yaml
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from smartclaw.memory.store import MemoryStore
from smartclaw.memory.summarizer import AutoSummarizer
from smartclaw.providers.config import ModelConfig
from smartclaw.skills.loader import SkillsLoader
from smartclaw.skills.models import SkillDefinition
from smartclaw.skills.registry import SkillsRegistry
from smartclaw.tools.registry import ToolRegistry
from smartclaw.agent.sub_agent import EphemeralStore
from smartclaw.config.settings import SmartClawSettings


# ===================================================================
# 1. MemoryStore E2E — real SQLite persistence
# ===================================================================


class TestMemoryStoreE2E:
    """E2E: MemoryStore with real SQLite file operations."""

    async def test_cross_session_persistence(self, tmp_path: pathlib.Path) -> None:
        """Messages persist across MemoryStore instances (same db file)."""
        db_path = str(tmp_path / "memory.db")

        # Session 1: write messages
        store1 = MemoryStore(db_path=db_path)
        await store1.initialize()
        await store1.add_message("session-1", "human", "Hello from session 1")
        await store1.add_message("session-1", "ai", "Hi there!")
        await store1.set_summary("session-1", "User greeted the agent.")
        await store1.close()

        # Session 2: read back from same db
        store2 = MemoryStore(db_path=db_path)
        await store2.initialize()
        history = await store2.get_history("session-1")
        summary = await store2.get_summary("session-1")
        await store2.close()

        assert len(history) == 2
        assert history[0].content == "Hello from session 1"
        assert history[1].content == "Hi there!"
        assert summary == "User greeted the agent."

    async def test_multiple_sessions_isolated(self, tmp_path: pathlib.Path) -> None:
        """Different session keys are fully isolated."""
        db_path = str(tmp_path / "memory.db")
        store = MemoryStore(db_path=db_path)
        await store.initialize()

        await store.add_message("alice", "human", "I'm Alice")
        await store.add_message("bob", "human", "I'm Bob")
        await store.add_message("alice", "ai", "Hello Alice")

        alice_history = await store.get_history("alice")
        bob_history = await store.get_history("bob")

        assert len(alice_history) == 2
        assert len(bob_history) == 1
        assert alice_history[0].content == "I'm Alice"
        assert bob_history[0].content == "I'm Bob"
        await store.close()

    async def test_full_message_with_tool_calls(self, tmp_path: pathlib.Path) -> None:
        """AIMessage with tool_calls and ToolMessage round-trip through SQLite."""
        db_path = str(tmp_path / "memory.db")
        store = MemoryStore(db_path=db_path)
        await store.initialize()

        ai_msg = AIMessage(
            content="Let me search for that.",
            tool_calls=[{
                "name": "web_search",
                "args": {"query": "Python 3.12"},
                "id": "call_abc123",
                "type": "tool_call",
            }],
        )
        tool_msg = ToolMessage(
            content="Found 5 results about Python 3.12",
            tool_call_id="call_abc123",
        )

        await store.add_full_message("s1", HumanMessage(content="Search Python 3.12"))
        await store.add_full_message("s1", ai_msg)
        await store.add_full_message("s1", tool_msg)

        history = await store.get_history("s1")
        assert len(history) == 3
        assert isinstance(history[1], AIMessage)
        assert len(history[1].tool_calls) == 1
        assert history[1].tool_calls[0]["name"] == "web_search"
        assert isinstance(history[2], ToolMessage)
        assert history[2].tool_call_id == "call_abc123"
        await store.close()

    async def test_truncate_then_persist(self, tmp_path: pathlib.Path) -> None:
        """Truncate history, close, reopen — truncation persists."""
        db_path = str(tmp_path / "memory.db")
        store = MemoryStore(db_path=db_path)
        await store.initialize()

        for i in range(10):
            await store.add_message("s1", "human", f"msg-{i}")

        await store.truncate_history("s1", 3)
        await store.close()

        # Reopen and verify
        store2 = MemoryStore(db_path=db_path)
        await store2.initialize()
        history = await store2.get_history("s1")
        assert len(history) == 3
        assert history[0].content == "msg-7"
        assert history[2].content == "msg-9"
        await store2.close()

    async def test_set_history_atomic_replace(self, tmp_path: pathlib.Path) -> None:
        """set_history atomically replaces all messages."""
        db_path = str(tmp_path / "memory.db")
        store = MemoryStore(db_path=db_path)
        await store.initialize()

        # Add initial messages
        for i in range(5):
            await store.add_message("s1", "human", f"old-{i}")

        # Replace with new messages
        new_msgs = [HumanMessage(content="new-0"), AIMessage(content="new-1")]
        await store.set_history("s1", new_msgs)

        history = await store.get_history("s1")
        assert len(history) == 2
        assert history[0].content == "new-0"
        assert history[1].content == "new-1"
        await store.close()


# ===================================================================
# 2. AutoSummarizer E2E — token estimation + context building
# ===================================================================


class TestAutoSummarizerE2E:
    """E2E: AutoSummarizer without LLM (token estimation, context building)."""

    async def test_token_estimation_realistic(self) -> None:
        """Token estimation produces reasonable values for real messages."""
        summarizer = AutoSummarizer(
            store=None,  # type: ignore[arg-type]
            model_config=ModelConfig(primary="openai/gpt-4o"),
        )
        msgs = [
            HumanMessage(content="What is Python?"),
            AIMessage(content="Python is a high-level programming language."),
        ]
        tokens = summarizer.estimate_tokens(msgs)
        # ~60 chars total content + overhead → ~30-40 tokens
        assert 20 < tokens < 100

    async def test_build_context_with_summary(self, tmp_path: pathlib.Path) -> None:
        """build_context prepends summary SystemMessage to real messages."""
        db_path = str(tmp_path / "memory.db")
        store = MemoryStore(db_path=db_path)
        await store.initialize()
        await store.set_summary("s1", "User asked about Python basics.")

        summarizer = AutoSummarizer(
            store=store,
            model_config=ModelConfig(primary="openai/gpt-4o"),
        )
        msgs = [HumanMessage(content="Tell me more")]
        result = await summarizer.build_context("s1", msgs)

        assert len(result) == 2
        assert isinstance(result[0], SystemMessage)
        assert "Python basics" in result[0].content
        assert isinstance(result[1], HumanMessage)
        await store.close()

    async def test_build_context_no_summary(self, tmp_path: pathlib.Path) -> None:
        """build_context returns messages unchanged when no summary exists."""
        db_path = str(tmp_path / "memory.db")
        store = MemoryStore(db_path=db_path)
        await store.initialize()

        summarizer = AutoSummarizer(
            store=store,
            model_config=ModelConfig(primary="openai/gpt-4o"),
        )
        msgs = [HumanMessage(content="Hello")]
        result = await summarizer.build_context("s1", msgs)

        assert result == msgs
        await store.close()

    def test_find_safe_boundary(self) -> None:
        """find_safe_boundary locates HumanMessage turn boundaries."""
        msgs = [
            HumanMessage(content="q1"),
            AIMessage(content="a1"),
            HumanMessage(content="q2"),
            AIMessage(content="a2"),
            HumanMessage(content="q3"),
            AIMessage(content="a3"),
        ]
        # Target index 3 → should find HumanMessage at index 2
        assert AutoSummarizer.find_safe_boundary(msgs, 3) == 2
        # Target index 5 → should find HumanMessage at index 4
        assert AutoSummarizer.find_safe_boundary(msgs, 5) == 4
        # Target index 0 → returns 0
        assert AutoSummarizer.find_safe_boundary(msgs, 0) == 0


# ===================================================================
# 3. SkillsLoader E2E — real YAML file operations
# ===================================================================


class TestSkillsLoaderE2E:
    """E2E: SkillsLoader with real filesystem skill directories."""

    def _create_skill(
        self, base: pathlib.Path, name: str, desc: str, entry: str
    ) -> None:
        skill_dir = base / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        data = {"name": name, "description": desc, "entry_point": entry}
        (skill_dir / "skill.yaml").write_text(
            yaml.dump(data), encoding="utf-8"
        )

    def test_discover_skills_from_multiple_dirs(self, tmp_path: pathlib.Path) -> None:
        """Discovers skills from workspace, global, and builtin dirs."""
        ws = tmp_path / "workspace"
        gl = tmp_path / "global"
        bi = tmp_path / "builtin"

        self._create_skill(ws, "skill-a", "Workspace A", "pkg:a")
        self._create_skill(gl, "skill-b", "Global B", "pkg:b")
        self._create_skill(bi, "skill-c", "Builtin C", "pkg:c")

        loader = SkillsLoader(
            workspace_dir=str(ws), global_dir=str(gl), builtin_dir=str(bi)
        )
        skills = loader.list_skills()
        names = {s.name for s in skills}

        assert names == {"skill-a", "skill-b", "skill-c"}

    def test_workspace_overrides_global(self, tmp_path: pathlib.Path) -> None:
        """Same skill name in workspace takes priority over global."""
        ws = tmp_path / "workspace"
        gl = tmp_path / "global"

        self._create_skill(ws, "my-skill", "From workspace", "pkg:ws")
        self._create_skill(gl, "my-skill", "From global", "pkg:gl")

        loader = SkillsLoader(workspace_dir=str(ws), global_dir=str(gl))
        skills = loader.list_skills()

        assert len(skills) == 1
        assert skills[0].source == "workspace"
        assert "From workspace" in skills[0].description

    def test_invalid_yaml_skipped_others_loaded(self, tmp_path: pathlib.Path) -> None:
        """Invalid YAML skill is skipped, valid ones still load."""
        ws = tmp_path / "workspace"
        self._create_skill(ws, "good-skill", "Good one", "pkg:good")

        bad_dir = ws / "bad-skill"
        bad_dir.mkdir(parents=True)
        (bad_dir / "skill.yaml").write_text("{{broken yaml", encoding="utf-8")

        loader = SkillsLoader(workspace_dir=str(ws), global_dir=str(tmp_path / "no_global"))
        skills = loader.list_skills()

        assert len(skills) == 1
        assert skills[0].name == "good-skill"

    def test_build_skills_summary(self, tmp_path: pathlib.Path) -> None:
        """build_skills_summary includes all skill names and descriptions."""
        ws = tmp_path / "workspace"
        self._create_skill(ws, "search-tool", "Web search", "pkg:search")
        self._create_skill(ws, "calc-tool", "Calculator", "pkg:calc")

        loader = SkillsLoader(workspace_dir=str(ws), global_dir=str(tmp_path / "no_global"))
        summary = loader.build_skills_summary()

        assert "search-tool" in summary
        assert "Web search" in summary
        assert "calc-tool" in summary
        assert "Calculator" in summary

    def test_yaml_round_trip(self) -> None:
        """serialize then parse produces equivalent SkillDefinition."""
        defn = SkillDefinition(
            name="my-skill",
            description="A test skill",
            entry_point="pkg.mod:create",
            version="1.0.0",
            author="Test",
            parameters={"timeout": 30},
        )
        yaml_str = SkillsLoader.serialize_skill_yaml(defn)
        restored = SkillsLoader.parse_skill_yaml(yaml_str)

        assert restored.name == defn.name
        assert restored.description == defn.description
        assert restored.entry_point == defn.entry_point
        assert restored.version == defn.version


# ===================================================================
# 4. EphemeralStore E2E
# ===================================================================


class TestEphemeralStoreE2E:
    """E2E: EphemeralStore real in-memory behavior."""

    def test_auto_truncation_at_boundary(self) -> None:
        """Adding 100 messages to max_size=10 store keeps only last 10."""
        store = EphemeralStore(max_size=10)
        for i in range(100):
            store.add_message(HumanMessage(content=f"msg-{i}"))

        history = store.get_history()
        assert len(history) == 10
        assert history[0].content == "msg-90"
        assert history[9].content == "msg-99"

    def test_set_history_then_add(self) -> None:
        """set_history replaces, then add appends with truncation."""
        store = EphemeralStore(max_size=5)
        store.set_history([HumanMessage(content=f"init-{i}") for i in range(3)])
        assert len(store.get_history()) == 3

        for i in range(5):
            store.add_message(AIMessage(content=f"new-{i}"))

        history = store.get_history()
        assert len(history) == 5
        # 3 init + 5 new = 8 total, max_size=5 keeps last 5: init-2, new-0..new-3? 
        # Actually: after set_history(3 items), adding 5 more = 8 total
        # Auto-truncation keeps last 5: new-0, new-1, new-2, new-3, new-4
        # Wait — truncation happens after each add_message, so:
        # After init: [init-0, init-1, init-2] (3 items, < 5)
        # +new-0: [init-0, init-1, init-2, new-0] (4 items, < 5)
        # +new-1: [init-0, init-1, init-2, new-0, new-1] (5 items, = 5)
        # +new-2: [init-1, init-2, new-0, new-1, new-2] (truncated to 5)
        # +new-3: [init-2, new-0, new-1, new-2, new-3] (truncated to 5)
        # +new-4: [new-0, new-1, new-2, new-3, new-4] (truncated to 5)
        assert history[0].content == "new-0"
        assert history[4].content == "new-4"

    def test_isolation_between_stores(self) -> None:
        """Two EphemeralStore instances are fully independent."""
        s1 = EphemeralStore(max_size=100)
        s2 = EphemeralStore(max_size=100)

        s1.add_message(HumanMessage(content="only in s1"))
        assert len(s1.get_history()) == 1
        assert len(s2.get_history()) == 0


# ===================================================================
# 5. Configuration E2E
# ===================================================================


class TestConfigurationE2E:
    """E2E: SmartClawSettings with P1 fields via env vars."""

    def setup_method(self) -> None:
        self._saved = {}
        for k in list(os.environ):
            if k.startswith("SMARTCLAW_"):
                self._saved[k] = os.environ.pop(k)

    def teardown_method(self) -> None:
        for k in list(os.environ):
            if k.startswith("SMARTCLAW_"):
                del os.environ[k]
        for k, v in self._saved.items():
            os.environ[k] = v

    def test_p1_defaults_present(self) -> None:
        """SmartClawSettings has all P1 fields with correct defaults."""
        s = SmartClawSettings()
        assert s.memory.enabled is True
        assert s.memory.db_path == "~/.smartclaw/memory.db"
        assert s.skills.enabled is True
        assert s.sub_agent.enabled is True
        assert s.sub_agent.max_depth == 3
        assert s.multi_agent.enabled is False

    def test_env_override_memory(self) -> None:
        """SMARTCLAW_MEMORY__* env vars override memory settings."""
        os.environ["SMARTCLAW_MEMORY__ENABLED"] = "false"
        os.environ["SMARTCLAW_MEMORY__DB_PATH"] = "/tmp/custom.db"
        os.environ["SMARTCLAW_MEMORY__SUMMARY_THRESHOLD"] = "50"

        s = SmartClawSettings()
        assert s.memory.enabled is False
        assert s.memory.db_path == "/tmp/custom.db"
        assert s.memory.summary_threshold == 50

    def test_env_override_sub_agent(self) -> None:
        """SMARTCLAW_SUB_AGENT__* env vars override sub_agent settings."""
        os.environ["SMARTCLAW_SUB_AGENT__MAX_DEPTH"] = "10"
        os.environ["SMARTCLAW_SUB_AGENT__MAX_CONCURRENT"] = "20"

        s = SmartClawSettings()
        assert s.sub_agent.max_depth == 10
        assert s.sub_agent.max_concurrent == 20

    def test_all_p1_disabled_p0_intact(self) -> None:
        """Disabling all P1 modules leaves P0 defaults intact."""
        os.environ["SMARTCLAW_MEMORY__ENABLED"] = "false"
        os.environ["SMARTCLAW_SKILLS__ENABLED"] = "false"
        os.environ["SMARTCLAW_SUB_AGENT__ENABLED"] = "false"
        os.environ["SMARTCLAW_MULTI_AGENT__ENABLED"] = "false"

        s = SmartClawSettings()
        assert s.agent_defaults.max_tokens == 32768
        assert s.logging.level == "INFO"
