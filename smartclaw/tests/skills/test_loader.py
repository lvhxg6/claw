"""Unit tests for SkillsLoader."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import yaml

from smartclaw.skills.loader import SkillsLoader
from smartclaw.skills.models import SkillDefinition


class TestInvalidYamlSkipped:
    """Tests for invalid YAML handling."""

    def test_invalid_yaml_skipped_with_warning(self, tmp_path: Path, caplog: logging.LogRecord) -> None:
        """Invalid YAML is skipped with a warning. (Req 5.6)"""
        skill_dir = tmp_path / "workspace" / "bad-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "skill.yaml").write_text("{{invalid yaml: [", encoding="utf-8")

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
            builtin_dir=None,
        )
        skills = loader.list_skills()
        assert len(skills) == 0


class TestMissingRequiredFields:
    """Tests for missing required fields."""

    def test_missing_name_skipped(self, tmp_path: Path) -> None:
        """Skill with missing name is skipped. (Req 5.7)"""
        skill_dir = tmp_path / "workspace" / "no-name"
        skill_dir.mkdir(parents=True)
        data = {"description": "A skill", "entry_point": "pkg:func"}
        (skill_dir / "skill.yaml").write_text(yaml.dump(data), encoding="utf-8")

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
            builtin_dir=None,
        )
        skills = loader.list_skills()
        assert len(skills) == 0

    def test_missing_description_skipped(self, tmp_path: Path) -> None:
        """Skill with missing description is skipped. (Req 5.7)"""
        skill_dir = tmp_path / "workspace" / "no-desc"
        skill_dir.mkdir(parents=True)
        data = {"name": "no-desc", "entry_point": "pkg:func"}
        (skill_dir / "skill.yaml").write_text(yaml.dump(data), encoding="utf-8")

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
            builtin_dir=None,
        )
        skills = loader.list_skills()
        assert len(skills) == 0

    def test_missing_entry_point_skipped(self, tmp_path: Path) -> None:
        """Skill with missing entry_point is skipped. (Req 5.7)"""
        skill_dir = tmp_path / "workspace" / "no-ep"
        skill_dir.mkdir(parents=True)
        data = {"name": "no-ep", "description": "A skill"}
        (skill_dir / "skill.yaml").write_text(yaml.dump(data), encoding="utf-8")

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
            builtin_dir=None,
        )
        skills = loader.list_skills()
        assert len(skills) == 0


class TestEntryPointImportFailure:
    """Tests for entry_point import failures."""

    def test_import_failure_raises_import_error(self, tmp_path: Path) -> None:
        """entry_point import failure raises ImportError. (Req 5.11)"""
        skill_dir = tmp_path / "workspace" / "bad-import"
        skill_dir.mkdir(parents=True)
        data = {
            "name": "bad-import",
            "description": "A skill with bad import",
            "entry_point": "nonexistent.module.path:create_tools",
        }
        (skill_dir / "skill.yaml").write_text(yaml.dump(data), encoding="utf-8")

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
            builtin_dir=None,
        )

        try:
            loader.load_skill("bad-import")
            assert False, "Expected ImportError"
        except ImportError as exc:
            assert "nonexistent.module.path" in str(exc)
            assert "bad-import" in str(exc)

    def test_invalid_entry_point_format_raises(self, tmp_path: Path) -> None:
        """entry_point without ':' raises ImportError."""
        skill_dir = tmp_path / "workspace" / "bad-format"
        skill_dir.mkdir(parents=True)
        data = {
            "name": "bad-format",
            "description": "Bad entry point format",
            "entry_point": "no_colon_here",
        }
        (skill_dir / "skill.yaml").write_text(yaml.dump(data), encoding="utf-8")

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
            builtin_dir=None,
        )

        try:
            loader.load_skill("bad-format")
            assert False, "Expected ImportError"
        except ImportError as exc:
            assert "Invalid entry_point format" in str(exc)


class TestNonExistentDirectory:
    """Tests for non-existent skill directories."""

    def test_nonexistent_directory_silently_skipped(self, tmp_path: Path) -> None:
        """Non-existent skill directory is silently skipped."""
        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "does_not_exist"),
            global_dir=str(tmp_path / "also_missing"),
            builtin_dir=str(tmp_path / "nope"),
        )
        skills = loader.list_skills()
        assert skills == []

    def test_skill_not_found_raises(self, tmp_path: Path) -> None:
        """load_skill for non-existent skill raises ImportError."""
        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "empty"),
            global_dir=str(tmp_path / "empty2"),
            builtin_dir=None,
        )
        try:
            loader.load_skill("ghost-skill")
            assert False, "Expected ImportError"
        except ImportError as exc:
            assert "ghost-skill" in str(exc)


class TestParseAndSerialize:
    """Tests for parse_skill_yaml and serialize_skill_yaml."""

    def test_parse_valid_yaml(self) -> None:
        """parse_skill_yaml handles a complete skill.yaml."""
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
        assert defn.parameters["timeout"] == 30

    def test_serialize_minimal(self) -> None:
        """serialize_skill_yaml produces valid YAML for minimal definition."""
        defn = SkillDefinition(
            name="my-skill",
            description="A skill",
            entry_point="pkg:func",
        )
        yaml_str = SkillsLoader.serialize_skill_yaml(defn)
        parsed = yaml.safe_load(yaml_str)
        assert parsed["name"] == "my-skill"
        assert parsed["description"] == "A skill"
        assert parsed["entry_point"] == "pkg:func"
        assert "version" not in parsed
        assert "author" not in parsed
