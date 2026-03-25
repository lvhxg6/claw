"""Unit tests for SKILL.md parsing and SkillsLoader Markdown skill support."""

from __future__ import annotations

from pathlib import Path

import yaml

from smartclaw.skills.loader import SkillsLoader
from smartclaw.skills.markdown_skill import parse_skill_md, split_frontmatter


class TestSplitFrontmatter:
    """Tests for split_frontmatter()."""

    def test_with_frontmatter(self) -> None:
        """Frontmatter between --- delimiters is extracted."""
        content = "---\nname: test\ndescription: A test\n---\n# Hello\n\nBody."
        fm, body = split_frontmatter(content)
        assert "name: test" in fm
        assert "description: A test" in fm
        assert body.startswith("# Hello")
        assert "---" not in body

    def test_no_frontmatter(self) -> None:
        """Content without --- returns empty frontmatter."""
        content = "# Just Markdown\n\nSome text."
        fm, body = split_frontmatter(content)
        assert fm == ""
        assert body == content

    def test_unclosed_frontmatter(self) -> None:
        """Unclosed --- returns empty frontmatter."""
        content = "---\nname: test\n# No closing delimiter"
        fm, body = split_frontmatter(content)
        assert fm == ""
        assert body == content

    def test_empty_frontmatter(self) -> None:
        """Empty frontmatter between --- delimiters."""
        content = "---\n---\nBody text."
        fm, body = split_frontmatter(content)
        assert fm == ""
        assert body == "Body text."


class TestParseSkillMd:
    """Tests for parse_skill_md()."""

    def test_frontmatter_happy_path(self) -> None:
        """Extracts name, description from frontmatter. (Req 11.2)"""
        content = "---\nname: code-reviewer\ndescription: Expert code review\n---\n# Code Reviewer\n\nYou are an expert."
        name, desc, body = parse_skill_md(content, "fallback")
        assert name == "code-reviewer"
        assert desc == "Expert code review"
        assert body.startswith("# Code Reviewer")
        assert "---" not in body

    def test_no_frontmatter_fallback(self) -> None:
        """Falls back to dir_name and first paragraph. (Req 11.3)"""
        content = "This is the first paragraph.\n\nSecond paragraph."
        name, desc, body = parse_skill_md(content, "my-skill")
        assert name == "my-skill"
        assert desc == "This is the first paragraph."
        assert body == content

    def test_invalid_frontmatter_fallback(self) -> None:
        """Invalid YAML frontmatter falls back gracefully. (Req 11.11)"""
        content = "---\n{{invalid yaml: [\n---\nBody content here."
        name, desc, body = parse_skill_md(content, "fallback-dir")
        assert name == "fallback-dir"
        assert desc == "Body content here."
        assert body == "Body content here."

    def test_frontmatter_missing_name(self) -> None:
        """Missing name in frontmatter uses dir_name."""
        content = "---\ndescription: A description\n---\n# Title\n\nBody."
        name, desc, body = parse_skill_md(content, "dir-name")
        assert name == "dir-name"
        assert desc == "A description"

    def test_frontmatter_missing_description(self) -> None:
        """Missing description in frontmatter uses first paragraph."""
        content = "---\nname: my-skill\n---\nFirst paragraph text.\n\nMore."
        name, desc, body = parse_skill_md(content, "fallback")
        assert name == "my-skill"
        assert desc == "First paragraph text."

    def test_heading_skipped_for_first_paragraph(self) -> None:
        """Headings are skipped when extracting first paragraph."""
        content = "# Title\n\nActual first paragraph.\n\nMore."
        name, desc, body = parse_skill_md(content, "dir")
        assert desc == "Actual first paragraph."


class TestHybridDiscovery:
    """Tests for skill directory discovery with SKILL.md."""

    def test_pure_md_skill_discovered(self, tmp_path: Path) -> None:
        """Pure SKILL.md skill (no skill.yaml) is discovered. (Req 11.6)"""
        skill_dir = tmp_path / "workspace" / "code-reviewer"
        skill_dir.mkdir(parents=True)
        md_content = "---\nname: code-reviewer\ndescription: Expert code review\n---\n# Code Reviewer\n\nYou are an expert."
        (skill_dir / "SKILL.md").write_text(md_content, encoding="utf-8")

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
            builtin_dir=None,
        )
        skills = loader.list_skills()
        assert len(skills) == 1
        assert skills[0].name == "code-reviewer"
        assert skills[0].description == "Expert code review"

    def test_hybrid_skill_discovered(self, tmp_path: Path) -> None:
        """Hybrid skill (skill.yaml + SKILL.md) is discovered. (Req 11.5)"""
        skill_dir = tmp_path / "workspace" / "go-analyzer"
        skill_dir.mkdir(parents=True)

        yaml_data = {
            "name": "go-analyzer",
            "description": "Go code analysis",
            "entry_point": "pkg.go:create_tools",
        }
        (skill_dir / "skill.yaml").write_text(
            yaml.dump(yaml_data), encoding="utf-8"
        )
        (skill_dir / "SKILL.md").write_text(
            "---\nname: go-analyzer\ndescription: Go analysis prompt\n---\n# Go Analyzer\n\nAnalyze Go code.",
            encoding="utf-8",
        )

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
            builtin_dir=None,
        )
        skills = loader.list_skills()
        assert len(skills) == 1
        # YAML takes priority for metadata
        assert skills[0].name == "go-analyzer"
        assert skills[0].description == "Go code analysis"

    def test_empty_dir_ignored(self, tmp_path: Path) -> None:
        """Directory without skill.yaml or SKILL.md is ignored. (Req 12.2)"""
        empty_dir = tmp_path / "workspace" / "not-a-skill"
        empty_dir.mkdir(parents=True)

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
            builtin_dir=None,
        )
        skills = loader.list_skills()
        assert len(skills) == 0


class TestPureMdSkillLoading:
    """Tests for loading pure SKILL.md skills."""

    def test_load_pure_md_skill(self, tmp_path: Path) -> None:
        """load_skill returns body content for pure MD skill. (Req 11.7)"""
        skill_dir = tmp_path / "workspace" / "code-reviewer"
        skill_dir.mkdir(parents=True)
        md_content = "---\nname: code-reviewer\ndescription: Expert code review\n---\n# Code Reviewer\n\nYou are an expert."
        (skill_dir / "SKILL.md").write_text(md_content, encoding="utf-8")

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
            builtin_dir=None,
        )
        result, definition = loader.load_skill("code-reviewer")
        assert definition is None
        assert isinstance(result, str)
        assert "You are an expert" in result
        assert "---" not in result


class TestBuildSkillsSummaryWithMd:
    """Tests for build_skills_summary including MD skills."""

    def test_summary_includes_md_skill(self, tmp_path: Path) -> None:
        """build_skills_summary includes Markdown skills. (Req 11.8)"""
        skill_dir = tmp_path / "workspace" / "code-reviewer"
        skill_dir.mkdir(parents=True)
        md_content = "---\nname: code-reviewer\ndescription: Expert code review\n---\n# Code Reviewer\n\nContent."
        (skill_dir / "SKILL.md").write_text(md_content, encoding="utf-8")

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
            builtin_dir=None,
        )
        summary = loader.build_skills_summary()
        assert "code-reviewer" in summary
        assert "Expert code review" in summary


class TestLoadSkillsForContextWithMd:
    """Tests for load_skills_for_context including MD skills."""

    def test_context_includes_md_skill_body(self, tmp_path: Path) -> None:
        """load_skills_for_context loads SKILL.md body. (Req 11.9)"""
        skill_dir = tmp_path / "workspace" / "code-reviewer"
        skill_dir.mkdir(parents=True)
        md_content = "---\nname: code-reviewer\ndescription: Expert code review\n---\n# Code Reviewer\n\nYou are an expert."
        (skill_dir / "SKILL.md").write_text(md_content, encoding="utf-8")

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
            builtin_dir=None,
        )
        context = loader.load_skills_for_context(["code-reviewer"])
        assert "code-reviewer" in context
        assert "You are an expert" in context
