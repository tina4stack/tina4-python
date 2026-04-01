# Tests for tina4_python.ai — AI tool installer (menu-based)
import pytest
from pathlib import Path
from tina4_python.ai import (
    AI_TOOLS,
    is_installed,
    install_selected,
    install_all,
    generate_context,
)


class TestAITools:
    def test_tools_is_list(self):
        assert isinstance(AI_TOOLS, list)
        assert len(AI_TOOLS) > 0

    def test_tools_have_seven_entries(self):
        assert len(AI_TOOLS) == 7

    def test_tools_have_required_keys(self):
        for tool in AI_TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "context_file" in tool

    def test_tools_include_expected_names(self):
        names = [t["name"] for t in AI_TOOLS]
        assert "claude-code" in names
        assert "cursor" in names
        assert "copilot" in names
        assert "windsurf" in names
        assert "aider" in names
        assert "cline" in names
        assert "codex" in names


class TestIsInstalled:
    def test_false_when_context_file_absent(self, tmp_path):
        tool = {"name": "cursor", "context_file": ".cursorules"}
        assert not is_installed(str(tmp_path), tool)

    def test_true_when_context_file_present(self, tmp_path):
        tool = {"name": "claude-code", "context_file": "CLAUDE.md"}
        (tmp_path / "CLAUDE.md").write_text("context")
        assert is_installed(str(tmp_path), tool)

    def test_handles_nested_path(self, tmp_path):
        tool = {"name": "copilot", "context_file": ".github/copilot-instructions.md"}
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "copilot-instructions.md").write_text("ctx")
        assert is_installed(str(tmp_path), tool)

    def test_false_for_copilot_without_file(self, tmp_path):
        tool = {"name": "copilot", "context_file": ".github/copilot-instructions.md"}
        (tmp_path / ".github").mkdir()  # dir exists but not the file
        assert not is_installed(str(tmp_path), tool)


class TestInstallSelected:
    def test_install_single_tool_by_number(self, tmp_path):
        created = install_selected(str(tmp_path), "2")  # cursor
        assert any(".cursorules" in f for f in created)
        assert (tmp_path / ".cursorules").exists()

    def test_install_multiple_tools(self, tmp_path):
        created = install_selected(str(tmp_path), "1,2")
        assert (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / ".cursorules").exists()

    def test_install_all_selection(self, tmp_path):
        install_selected(str(tmp_path), "all")
        assert (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / ".cursorules").exists()
        assert (tmp_path / ".windsurfrules").exists()
        assert (tmp_path / "CONVENTIONS.md").exists()
        assert (tmp_path / ".clinerules").exists()
        assert (tmp_path / "AGENTS.md").exists()

    def test_always_overwrites(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("old content")
        install_selected(str(tmp_path), "1")
        content = (tmp_path / "CLAUDE.md").read_text()
        assert content != "old content"

    def test_creates_parent_directories(self, tmp_path):
        install_selected(str(tmp_path), "3")  # copilot
        assert (tmp_path / ".github" / "copilot-instructions.md").exists()

    def test_returns_list(self, tmp_path):
        result = install_selected(str(tmp_path), "4")  # windsurf
        assert isinstance(result, list)
        assert len(result) > 0

    def test_ignores_invalid_numbers(self, tmp_path):
        result = install_selected(str(tmp_path), "99")
        assert isinstance(result, list)

    def test_handles_empty_selection(self, tmp_path):
        result = install_selected(str(tmp_path), "")
        assert isinstance(result, list)


class TestInstallAll:
    def test_installs_all_context_files(self, tmp_path):
        install_all(str(tmp_path))
        assert (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / ".cursorules").exists()
        assert (tmp_path / ".windsurfrules").exists()
        assert (tmp_path / "CONVENTIONS.md").exists()
        assert (tmp_path / ".clinerules").exists()
        assert (tmp_path / "AGENTS.md").exists()
        assert (tmp_path / ".github" / "copilot-instructions.md").exists()

    def test_returns_list(self, tmp_path):
        result = install_all(str(tmp_path))
        assert isinstance(result, list)
        assert len(result) >= len(AI_TOOLS)

    def test_creates_subdirectories(self, tmp_path):
        install_all(str(tmp_path))
        assert (tmp_path / ".claude").exists()
        assert (tmp_path / ".github").exists()


class TestGenerateContext:
    def test_returns_string(self):
        ctx = generate_context()
        assert isinstance(ctx, str)
        assert len(ctx) > 0

    def test_contains_framework_info(self):
        ctx = generate_context()
        assert "Tina4" in ctx
        assert "tina4.com" in ctx

    def test_contains_skills_table(self):
        ctx = generate_context()
        assert "Skill" in ctx

    def test_contains_feature_info(self):
        ctx = generate_context()
        assert "GraphQL" in ctx or "WebSocket" in ctx or "ORM" in ctx
