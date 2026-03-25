"""Unit tests for placeholder substitution functions.

Tests: multi-param substitution, default fallback, missing param error,
non-string conversion, {workspace} handling, substitute_args.
"""

from __future__ import annotations

import pytest

from smartclaw.skills.models import ParameterDef
from smartclaw.skills.native_command import substitute_args, substitute_placeholders


class TestSubstitutePlaceholders:
    """Tests for substitute_placeholders()."""

    def test_multi_param_substitution(self) -> None:
        """Multiple placeholders are all replaced."""
        template = "du -sh {path} --max-depth {depth}"
        params = {"path": "/tmp", "depth": 2}
        param_defs = {
            "path": ParameterDef(type="string", description="dir"),
            "depth": ParameterDef(type="integer", description="depth"),
        }
        result = substitute_placeholders(template, params, param_defs)
        assert result == "du -sh /tmp --max-depth 2"

    def test_default_value_fallback(self) -> None:
        """When param not in params but has default, use default."""
        template = "deploy --env {env}"
        params: dict = {}
        param_defs = {
            "env": ParameterDef(type="string", description="environment", default="staging"),
        }
        result = substitute_placeholders(template, params, param_defs)
        assert result == "deploy --env staging"

    def test_missing_required_param_raises(self) -> None:
        """When param not in params and no default, raise ValueError."""
        template = "cmd {required_param}"
        params: dict = {}
        param_defs = {
            "required_param": ParameterDef(type="string", description="required", default=None),
        }
        with pytest.raises(ValueError, match="Missing required parameter: required_param"):
            substitute_placeholders(template, params, param_defs)

    def test_non_string_int_conversion(self) -> None:
        """Integer values are converted to string."""
        template = "echo {count}"
        params = {"count": 42}
        param_defs = {"count": ParameterDef(type="integer", description="count")}
        result = substitute_placeholders(template, params, param_defs)
        assert result == "echo 42"

    def test_non_string_bool_conversion(self) -> None:
        """Boolean values are converted to string."""
        template = "cmd --verbose {flag}"
        params = {"flag": True}
        param_defs = {"flag": ParameterDef(type="boolean", description="flag")}
        result = substitute_placeholders(template, params, param_defs)
        assert result == "cmd --verbose True"

    def test_workspace_placeholder(self) -> None:
        """{workspace} is treated like any other placeholder."""
        template = "{workspace}/scripts/run.sh"
        params = {"workspace": "/home/user/project"}
        param_defs = {"workspace": ParameterDef(type="string", description="workspace dir")}
        result = substitute_placeholders(template, params, param_defs)
        assert result == "/home/user/project/scripts/run.sh"

    def test_no_placeholders(self) -> None:
        """Template without placeholders is returned unchanged."""
        template = "echo hello"
        result = substitute_placeholders(template, {}, {})
        assert result == "echo hello"

    def test_same_placeholder_multiple_times(self) -> None:
        """Same placeholder appearing multiple times is replaced everywhere."""
        template = "{name} and {name}"
        params = {"name": "foo"}
        param_defs = {"name": ParameterDef(type="string")}
        result = substitute_placeholders(template, params, param_defs)
        assert result == "foo and foo"

    def test_param_overrides_default(self) -> None:
        """When param is in both params and param_defs with default, params wins."""
        template = "cmd {val}"
        params = {"val": "override"}
        param_defs = {"val": ParameterDef(type="string", default="fallback")}
        result = substitute_placeholders(template, params, param_defs)
        assert result == "cmd override"

    def test_unknown_placeholder_no_def_raises(self) -> None:
        """Placeholder not in params or param_defs raises ValueError."""
        template = "cmd {unknown}"
        with pytest.raises(ValueError, match="Missing required parameter: unknown"):
            substitute_placeholders(template, {}, {})


class TestSubstituteArgs:
    """Tests for substitute_args()."""

    def test_substitute_args_list(self) -> None:
        """Each element in args list gets placeholders replaced."""
        args = ["--config", "{config_path}", "{target}"]
        params = {"config_path": ".golangci.yaml", "target": "./..."}
        param_defs = {
            "config_path": ParameterDef(type="string"),
            "target": ParameterDef(type="string"),
        }
        result = substitute_args(args, params, param_defs)
        assert result == ["--config", ".golangci.yaml", "./..."]

    def test_substitute_args_empty_list(self) -> None:
        """Empty args list returns empty list."""
        result = substitute_args([], {}, {})
        assert result == []

    def test_substitute_args_with_defaults(self) -> None:
        """Args with defaults are substituted correctly."""
        args = ["{env}", "--verbose"]
        params: dict = {}
        param_defs = {"env": ParameterDef(type="string", default="staging")}
        result = substitute_args(args, params, param_defs)
        assert result == ["staging", "--verbose"]
