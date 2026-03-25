"""Unit tests for SkillsLoader native command YAML parsing and serialization."""

from __future__ import annotations

import yaml

from smartclaw.skills.loader import SkillsLoader
from smartclaw.skills.models import ParameterDef, SkillDefinition, ToolDef


class TestNativeCommandYamlParsing:
    """Tests for parsing native command tool fields from YAML."""

    def test_parse_shell_tool(self) -> None:
        """Parse a shell type tool with all fields. (Req 2.1)"""
        yaml_str = """\
name: devops-tools
description: DevOps utilities
tools:
  - name: disk-usage
    description: Check disk usage
    type: shell
    command: "du -sh {path}"
    timeout: 30
    parameters:
      path:
        type: string
        description: Directory path
"""
        defn = SkillsLoader.parse_skill_yaml(yaml_str)
        assert len(defn.tools) == 1
        tool = defn.tools[0]
        assert tool.name == "disk-usage"
        assert tool.type == "shell"
        assert tool.command == "du -sh {path}"
        assert tool.timeout == 30
        assert "path" in tool.parameters
        assert tool.parameters["path"].type == "string"
        assert tool.parameters["path"].description == "Directory path"

    def test_parse_script_tool(self) -> None:
        """Parse a script type tool. (Req 2.1)"""
        yaml_str = """\
name: deploy-tools
description: Deployment tools
tools:
  - name: deploy-check
    description: Run deploy check
    type: script
    command: "./scripts/deploy-check.sh"
    working_dir: "{workspace}"
    timeout: 120
    deny_patterns:
      - "\\\\brm\\\\s+-rf\\\\b"
    parameters:
      env:
        type: string
        description: Deploy environment
        default: staging
"""
        defn = SkillsLoader.parse_skill_yaml(yaml_str)
        tool = defn.tools[0]
        assert tool.type == "script"
        assert tool.command == "./scripts/deploy-check.sh"
        assert tool.working_dir == "{workspace}"
        assert tool.timeout == 120
        assert len(tool.deny_patterns) == 1
        assert tool.parameters["env"].default == "staging"

    def test_parse_exec_tool(self) -> None:
        """Parse an exec type tool with args. (Req 2.1, 2.3)"""
        yaml_str = """\
name: lint-tools
description: Linting tools
tools:
  - name: lint-go
    description: Run golangci-lint
    type: exec
    command: golangci-lint
    args: ["run", "--config", "{config}"]
    working_dir: "{workspace}"
    timeout: 180
    max_output_chars: 20000
    parameters:
      config:
        type: string
        description: Config file path
        default: ".golangci.yaml"
"""
        defn = SkillsLoader.parse_skill_yaml(yaml_str)
        tool = defn.tools[0]
        assert tool.type == "exec"
        assert tool.command == "golangci-lint"
        assert tool.args == ["run", "--config", "{config}"]
        assert tool.max_output_chars == 20000
        assert tool.parameters["config"].default == ".golangci.yaml"


class TestParametersParsing:
    """Tests for parameters field parsing into ParameterDef objects."""

    def test_parameters_parsed_as_parameter_def(self) -> None:
        """Parameters are parsed as ParameterDef objects. (Req 2.4)"""
        yaml_str = """\
name: test-skill
description: Test
tools:
  - name: test-tool
    description: Test tool
    type: shell
    command: echo
    parameters:
      name:
        type: string
        description: The name
      count:
        type: integer
        description: How many
        default: 5
      verbose:
        type: boolean
        description: Verbose output
        default: true
"""
        defn = SkillsLoader.parse_skill_yaml(yaml_str)
        params = defn.tools[0].parameters
        assert len(params) == 3

        assert isinstance(params["name"], ParameterDef)
        assert params["name"].type == "string"
        assert params["name"].default is None

        assert params["count"].type == "integer"
        assert params["count"].default == 5

        assert params["verbose"].type == "boolean"
        assert params["verbose"].default is True

    def test_empty_parameters(self) -> None:
        """Tool with no parameters has empty dict."""
        yaml_str = """\
name: test-skill
description: Test
tools:
  - name: simple
    description: Simple tool
    type: shell
    command: echo hello
"""
        defn = SkillsLoader.parse_skill_yaml(yaml_str)
        assert defn.tools[0].parameters == {}


class TestNativeYamlRoundTrip:
    """Tests for serialize then parse round-trip with native tools."""

    def test_round_trip_shell_tool(self) -> None:
        """Shell tool survives serialize/parse round-trip. (Req 2.6, 2.7)"""
        defn = SkillDefinition(
            name="my-skill",
            description="A skill",
            tools=[
                ToolDef(
                    name="my-tool",
                    description="A tool",
                    type="shell",
                    command="echo {msg}",
                    timeout=30,
                    parameters={
                        "msg": ParameterDef(type="string", description="Message"),
                    },
                ),
            ],
        )
        yaml_str = SkillsLoader.serialize_skill_yaml(defn)
        restored = SkillsLoader.parse_skill_yaml(yaml_str)

        assert len(restored.tools) == 1
        tool = restored.tools[0]
        assert tool.type == "shell"
        assert tool.command == "echo {msg}"
        assert tool.timeout == 30
        assert "msg" in tool.parameters
        assert tool.parameters["msg"].type == "string"

    def test_round_trip_exec_tool_with_args(self) -> None:
        """Exec tool with args survives round-trip. (Req 2.6, 2.7)"""
        defn = SkillDefinition(
            name="exec-skill",
            description="Exec skill",
            tools=[
                ToolDef(
                    name="run-bin",
                    description="Run binary",
                    type="exec",
                    command="/usr/bin/myapp",
                    args=["--flag", "{value}"],
                    working_dir="/tmp",
                    max_output_chars=5000,
                    deny_patterns=[r"\brm\b"],
                    parameters={
                        "value": ParameterDef(
                            type="integer", description="A value", default=42
                        ),
                    },
                ),
            ],
        )
        yaml_str = SkillsLoader.serialize_skill_yaml(defn)
        restored = SkillsLoader.parse_skill_yaml(yaml_str)

        tool = restored.tools[0]
        assert tool.type == "exec"
        assert tool.args == ["--flag", "{value}"]
        assert tool.working_dir == "/tmp"
        assert tool.max_output_chars == 5000
        assert tool.deny_patterns == [r"\brm\b"]
        assert tool.parameters["value"].default == 42


class TestBackwardCompatibility:
    """Tests that existing skill.yaml without type fields parse unchanged."""

    def test_traditional_tool_no_type(self) -> None:
        """Traditional Python tool without type field. (Req 2.2, 10.2)"""
        yaml_str = """\
name: web-scraper
description: Web scraping
entry_point: "pkg.scraper:create_tools"
tools:
  - name: scrape
    description: Scrape a page
    function: "pkg.scraper:scrape"
"""
        defn = SkillsLoader.parse_skill_yaml(yaml_str)
        assert defn.entry_point == "pkg.scraper:create_tools"
        assert len(defn.tools) == 1
        tool = defn.tools[0]
        assert tool.type is None
        assert tool.function == "pkg.scraper:scrape"
        assert tool.command == ""
        assert tool.args == []
        assert tool.parameters == {}

    def test_serialize_traditional_tool_no_extra_fields(self) -> None:
        """Serializing a traditional tool doesn't add native fields. (Req 10.3)"""
        defn = SkillDefinition(
            name="my-skill",
            description="A skill",
            entry_point="pkg:func",
            tools=[
                ToolDef(
                    name="my-tool",
                    description="A tool",
                    function="pkg:tool_func",
                ),
            ],
        )
        yaml_str = SkillsLoader.serialize_skill_yaml(defn)
        parsed = yaml.safe_load(yaml_str)
        tool_data = parsed["tools"][0]
        # Should not have native command fields
        assert "type" not in tool_data
        assert "command" not in tool_data
        assert "args" not in tool_data
        assert "working_dir" not in tool_data
        assert "deny_patterns" not in tool_data
        assert "parameters" not in tool_data

    def test_existing_yaml_parse_identical(self) -> None:
        """Existing skill.yaml parses identically to before extension. (Req 10.3)"""
        yaml_str = """\
name: web-scraper
description: Web page scraping
entry_point: "pkg.scraper:create_tools"
version: "1.0.0"
author: SmartClaw Team
tools:
  - name: scrape
    description: Scrape a page
    function: "pkg.scraper:scrape"
parameters:
  timeout: 30
"""
        defn = SkillsLoader.parse_skill_yaml(yaml_str)
        assert defn.name == "web-scraper"
        assert defn.description == "Web page scraping"
        assert defn.entry_point == "pkg.scraper:create_tools"
        assert defn.version == "1.0.0"
        assert defn.author == "SmartClaw Team"
        assert len(defn.tools) == 1
        assert defn.tools[0].name == "scrape"
        assert defn.tools[0].function == "pkg.scraper:scrape"
        assert defn.tools[0].type is None
        assert defn.parameters["timeout"] == 30
