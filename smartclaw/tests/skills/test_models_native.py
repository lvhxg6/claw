"""Unit tests for ParameterDef, ToolDef validation, and SkillDefinition native command support."""

from __future__ import annotations

from smartclaw.skills.models import ParameterDef, SkillDefinition, ToolDef


# ---------------------------------------------------------------------------
# ParameterDef defaults
# ---------------------------------------------------------------------------


class TestParameterDefDefaults:
    """Test ParameterDef field defaults. (Req 1.10)"""

    def test_default_type_is_string(self) -> None:
        p = ParameterDef()
        assert p.type == "string"

    def test_default_description_is_empty(self) -> None:
        p = ParameterDef()
        assert p.description == ""

    def test_default_default_is_none(self) -> None:
        p = ParameterDef()
        assert p.default is None

    def test_custom_values(self) -> None:
        p = ParameterDef(type="integer", description="count", default=10)
        assert p.type == "integer"
        assert p.description == "count"
        assert p.default == 10


# ---------------------------------------------------------------------------
# ToolDef validation
# ---------------------------------------------------------------------------


class TestToolDefValidation:
    """Test ToolDef.validate() for various type/command/function combos."""

    # --- Valid cases ---

    def test_shell_with_command_valid(self) -> None:
        t = ToolDef(name="t", description="d", type="shell", command="echo hi")
        assert t.validate() == []

    def test_script_with_command_valid(self) -> None:
        t = ToolDef(name="t", description="d", type="script", command="./run.sh")
        assert t.validate() == []

    def test_exec_with_command_valid(self) -> None:
        t = ToolDef(name="t", description="d", type="exec", command="golangci-lint")
        assert t.validate() == []

    def test_python_with_function_valid(self) -> None:
        t = ToolDef(name="t", description="d", function="pkg.mod:func", type=None)
        assert t.validate() == []

    def test_python_type_none_implicit(self) -> None:
        """type defaults to None, function provided → valid."""
        t = ToolDef(name="t", description="d", function="pkg:f")
        assert t.validate() == []

    # --- Invalid cases ---

    def test_shell_empty_command_error(self) -> None:
        t = ToolDef(name="t", description="d", type="shell", command="")
        errors = t.validate()
        assert len(errors) == 1
        assert "command" in errors[0]

    def test_script_empty_command_error(self) -> None:
        t = ToolDef(name="t", description="d", type="script", command="")
        errors = t.validate()
        assert len(errors) == 1
        assert "command" in errors[0]

    def test_exec_empty_command_error(self) -> None:
        t = ToolDef(name="t", description="d", type="exec", command="")
        errors = t.validate()
        assert len(errors) == 1
        assert "command" in errors[0]

    def test_python_empty_function_error(self) -> None:
        t = ToolDef(name="t", description="d", type=None, function="")
        errors = t.validate()
        assert len(errors) == 1
        assert "function" in errors[0]

    def test_unrecognized_type_error(self) -> None:
        t = ToolDef(name="t", description="d", type="unknown")
        errors = t.validate()
        assert len(errors) == 1
        assert "unrecognized" in errors[0]

    def test_unrecognized_type_banana(self) -> None:
        t = ToolDef(name="t", description="d", type="banana")
        errors = t.validate()
        assert len(errors) > 0

    # --- ToolDef new field defaults ---

    def test_default_fields(self) -> None:
        t = ToolDef(name="t", description="d")
        assert t.type is None
        assert t.command == ""
        assert t.args == []
        assert t.working_dir is None
        assert t.timeout == 60
        assert t.max_output_chars == 10_000
        assert t.deny_patterns == []
        assert t.parameters == {}


# ---------------------------------------------------------------------------
# SkillDefinition validation with native command tools
# ---------------------------------------------------------------------------


class TestSkillDefinitionNativeValidation:
    """Test SkillDefinition.validate() with native command tools. (Req 9.1, 9.2, 9.3)"""

    def test_pure_native_tools_no_entry_point_valid(self) -> None:
        """No entry_point but has native command tools → valid."""
        defn = SkillDefinition(
            name="devops",
            description="DevOps tools",
            entry_point="",
            tools=[
                ToolDef(name="disk", description="disk usage", type="shell", command="du -sh"),
            ],
        )
        assert defn.validate() == []

    def test_mixed_entry_point_and_native_valid(self) -> None:
        """Has entry_point AND native command tools → valid (hybrid)."""
        defn = SkillDefinition(
            name="hybrid",
            description="Hybrid skill",
            entry_point="pkg.mod:func",
            tools=[
                ToolDef(name="lint", description="lint code", type="exec", command="golangci-lint"),
                ToolDef(name="helper", description="helper func", function="pkg:helper"),
            ],
        )
        assert defn.validate() == []

    def test_entry_point_only_valid(self) -> None:
        """Has entry_point, no native tools → valid (existing behavior)."""
        defn = SkillDefinition(
            name="classic",
            description="Classic skill",
            entry_point="pkg:func",
        )
        assert defn.validate() == []

    def test_no_entry_point_no_native_tools_error(self) -> None:
        """No entry_point and no native command tools → error."""
        defn = SkillDefinition(
            name="empty",
            description="Empty skill",
            entry_point="",
            tools=[],
        )
        errors = defn.validate()
        assert len(errors) > 0
        assert any("entry_point" in e or "native" in e for e in errors)

    def test_no_entry_point_only_python_tools_error(self) -> None:
        """No entry_point, only Python-type tools (type=None) → error."""
        defn = SkillDefinition(
            name="py-only",
            description="Python only tools",
            entry_point="",
            tools=[
                ToolDef(name="helper", description="helper", function="pkg:f"),
            ],
        )
        errors = defn.validate()
        assert len(errors) > 0

    def test_multiple_native_types_valid(self) -> None:
        """Multiple native tool types (shell + script + exec) → valid."""
        defn = SkillDefinition(
            name="multi",
            description="Multi-type tools",
            entry_point="",
            tools=[
                ToolDef(name="sh", description="shell", type="shell", command="echo"),
                ToolDef(name="sc", description="script", type="script", command="./run.sh"),
                ToolDef(name="ex", description="exec", type="exec", command="mybin"),
            ],
        )
        assert defn.validate() == []
