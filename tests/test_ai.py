# Tests for tina4_python.ai — AI tool detection and context scaffolding
import pytest
from pathlib import Path
from tina4_python.ai import (
    detect_ai, detect_ai_names, generate_context,
    install_context, install_all, status_report,
)


class TestDetectAI:
    def test_detect_returns_all_tools(self, tmp_path):
        tools = detect_ai(str(tmp_path))
        names = [t["name"] for t in tools]
        assert "claude-code" in names
        assert "cursor" in names
        assert "copilot" in names
        assert "windsurf" in names

    def test_no_tools_detected_empty_dir(self, tmp_path):
        names = detect_ai_names(str(tmp_path))
        assert names == []

    def test_detect_claude(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        names = detect_ai_names(str(tmp_path))
        assert "claude-code" in names

    def test_detect_claude_md(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Context")
        names = detect_ai_names(str(tmp_path))
        assert "claude-code" in names

    def test_detect_cursor(self, tmp_path):
        (tmp_path / ".cursor").mkdir()
        names = detect_ai_names(str(tmp_path))
        assert "cursor" in names

    def test_detect_cursorules(self, tmp_path):
        (tmp_path / ".cursorules").write_text("rules")
        names = detect_ai_names(str(tmp_path))
        assert "cursor" in names

    def test_detect_copilot(self, tmp_path):
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "copilot-instructions.md").write_text("instructions")
        names = detect_ai_names(str(tmp_path))
        assert "copilot" in names

    def test_detect_windsurf(self, tmp_path):
        (tmp_path / ".windsurfrules").write_text("rules")
        names = detect_ai_names(str(tmp_path))
        assert "windsurf" in names

    def test_detect_cline(self, tmp_path):
        (tmp_path / ".clinerules").write_text("rules")
        names = detect_ai_names(str(tmp_path))
        assert "cline" in names

    def test_detect_codex(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("# Agents")
        names = detect_ai_names(str(tmp_path))
        assert "codex" in names

    def test_detect_aider(self, tmp_path):
        (tmp_path / "CONVENTIONS.md").write_text("# Conventions")
        names = detect_ai_names(str(tmp_path))
        assert "aider" in names

    def test_detect_multiple(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".cursor").mkdir()
        names = detect_ai_names(str(tmp_path))
        assert "claude-code" in names
        assert "cursor" in names


class TestGenerateContext:
    def test_contains_framework_info(self):
        ctx = generate_context()
        assert "Tina4 Python" in ctx
        assert "tina4.com" in ctx
        assert "src/routes/" in ctx

    def test_contains_skills_table(self):
        ctx = generate_context(include_skills=True)
        assert "/tina4-route" in ctx
        assert "/tina4-crud" in ctx
        assert "/tina4-graphql" in ctx

    def test_no_skills_when_disabled(self):
        ctx = generate_context(include_skills=False)
        assert "/tina4-route" not in ctx

    def test_contains_feature_table(self):
        ctx = generate_context()
        assert "GraphQL" in ctx
        assert "WebSocket" in ctx
        assert "SOAP/WSDL" in ctx

    def test_contains_conventions(self):
        ctx = generate_context()
        assert "response()" in ctx
        assert "@noauth" in ctx
        assert "base.twig" in ctx


class TestInstallContext:
    def test_install_for_detected_claude(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        created = install_context(str(tmp_path))
        assert any("CLAUDE.md" in f for f in created)
        assert (tmp_path / "CLAUDE.md").exists()

    def test_install_for_detected_cursor(self, tmp_path):
        (tmp_path / ".cursor").mkdir()
        created = install_context(str(tmp_path))
        assert any(".cursorules" in f for f in created)

    def test_install_specific_tool(self, tmp_path):
        created = install_context(str(tmp_path), tools=["windsurf"])
        assert any(".windsurfrules" in f for f in created)
        assert (tmp_path / ".windsurfrules").exists()

    def test_install_does_not_overwrite(self, tmp_path):
        (tmp_path / ".windsurfrules").write_text("custom rules")
        install_context(str(tmp_path), tools=["windsurf"])
        assert (tmp_path / ".windsurfrules").read_text() == "custom rules"

    def test_install_force_overwrites(self, tmp_path):
        (tmp_path / ".windsurfrules").write_text("custom rules")
        install_context(str(tmp_path), tools=["windsurf"], force=True)
        content = (tmp_path / ".windsurfrules").read_text()
        assert "Tina4" in content

    def test_install_all(self, tmp_path):
        created = install_all(str(tmp_path))
        assert len(created) >= 7  # At least one file per tool
        assert (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / ".cursorules").exists()
        assert (tmp_path / ".windsurfrules").exists()
        assert (tmp_path / ".github" / "copilot-instructions.md").exists()


class TestStatusReport:
    def test_report_no_tools(self, tmp_path):
        report = status_report(str(tmp_path))
        assert "No AI coding tools detected" in report

    def test_report_with_tools(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        report = status_report(str(tmp_path))
        assert "Claude Code" in report
        assert "✓" in report

    def test_report_shows_missing(self, tmp_path):
        report = status_report(str(tmp_path))
        assert "tina4python ai --all" in report
