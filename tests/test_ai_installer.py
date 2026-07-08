"""Tests for v3.13.9 non-destructive AI installer.

The pre-v3.13.9 installer clobbered the user's CLAUDE.md (and the
equivalent context files for Cursor / Copilot / Windsurf / etc.) on
every install. v3.13.9 switches to a marker-bracketed skill block that
preserves whatever the user had in the file.

Four branches covered here:

1. Fresh install — file doesn't exist, full framework guide + block.
2. Refresh — file exists with markers, just the block gets replaced.
3. Migration — file starts with a pre-v3.13.9 framework header, the
   old dump gets replaced (preamble above the header preserved).
4. Preserve — file exists with user content, block appended at end.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tina4_python.ai import (
    _has_markers,
    _looks_like_old_framework_install,
    _markers_for,
    _replace_marker_block,
    _skill_block,
    _write_or_merge,
)


# ── Marker selection ────────────────────────────────────────────────


class TestMarkerSelection:
    def test_markdown_files_use_html_comment_markers(self):
        start, end = _markers_for("CLAUDE.md")
        assert start == "<!-- tina4-skills:start -->"
        assert end == "<!-- tina4-skills:end -->"

    def test_nested_markdown_files_use_html_comment_markers(self):
        start, end = _markers_for(".github/copilot-instructions.md")
        assert start.startswith("<!--") and end.startswith("<!--")

    def test_rule_files_use_hash_comment_markers(self):
        start, end = _markers_for(".cursorules")
        assert start == "# tina4-skills:start"
        assert end == "# tina4-skills:end"

    def test_each_supported_rule_file(self):
        for name in (".cursorules", ".windsurfrules", ".clinerules"):
            start, _ = _markers_for(name)
            assert start.startswith("#"), f"{name} should get hash markers"


# ── Block content ───────────────────────────────────────────────────


class TestSkillBlock:
    def test_markdown_block_has_heading_and_three_skills(self):
        block = _skill_block("CLAUDE.md")
        assert "<!-- tina4-skills:start -->" in block
        assert "<!-- tina4-skills:end -->" in block
        assert "## Tina4 Skills" in block
        assert "tina4-developer" in block
        assert "tina4-js" in block
        assert "tina4-maintainer" in block
        assert "tina4.com" in block
        # Every generated context tells the assistant how to report a stale/wrong skill.
        assert "report-a-skill" in block

    def test_rule_block_has_no_markdown_syntax(self):
        block = _skill_block(".cursorules")
        # No headings, no bold markers in rule-file blocks
        assert "##" not in block
        assert "**" not in block
        # But still references all three skills
        assert "tina4-developer" in block
        assert "tina4-js" in block
        assert "tina4-maintainer" in block


# ── Marker detection ────────────────────────────────────────────────


class TestMarkerDetection:
    def test_both_markers_present_in_order(self):
        start, end = "<!-- tina4-skills:start -->", "<!-- tina4-skills:end -->"
        text = f"Some user notes\n\n{start}\nblock\n{end}\n\nMore notes"
        assert _has_markers(text, start, end)

    def test_end_marker_before_start_is_not_a_match(self):
        start, end = "<!-- tina4-skills:start -->", "<!-- tina4-skills:end -->"
        text = f"{end}\nstray\n{start}\nblock"
        # We require end AFTER start.
        assert not _has_markers(text, start, end)

    def test_only_start_marker_is_not_a_match(self):
        start, end = "<!-- tina4-skills:start -->", "<!-- tina4-skills:end -->"
        text = f"User notes\n\n{start}\nincomplete"
        assert not _has_markers(text, start, end)


# ── Block replacement ───────────────────────────────────────────────


class TestReplaceMarkerBlock:
    def test_replaces_block_in_place(self):
        start, end = "<!-- tina4-skills:start -->", "<!-- tina4-skills:end -->"
        existing = f"# Project\n\n{start}\nOLD\n{end}\n\nUser notes"
        new_block = f"{start}\nNEW\n{end}"
        result = _replace_marker_block(existing, new_block, start, end)
        assert "NEW" in result
        assert "OLD" not in result
        assert "# Project" in result, "preamble preserved"
        assert "User notes" in result, "trailing content preserved"

    def test_replace_leaves_no_extra_blank_lines(self):
        start, end = "<!-- tina4-skills:start -->", "<!-- tina4-skills:end -->"
        existing = f"# Project\n\n{start}\nOLD\n{end}\n\nUser notes"
        new_block = f"{start}\nNEW\n{end}"
        result = _replace_marker_block(existing, new_block, start, end)
        # No more than two consecutive newlines anywhere.
        assert "\n\n\n" not in result


# ── Old-framework header detection ──────────────────────────────────


class TestOldFrameworkHeaderDetection:
    @pytest.mark.parametrize(
        "header",
        [
            "# Tina4 Python — Developer Guidelines",
            "# Tina4 PHP",
            "# Tina4 Ruby",
            "# CLAUDE.md — AI Developer Guide for tina4-nodejs (v3.13.5)",
        ],
    )
    def test_recognises_pre_v3_13_9_headers(self, header):
        text = f"{header}\n\nA bunch of framework guide content..."
        assert _looks_like_old_framework_install(text)

    def test_user_authored_claude_md_is_not_old(self):
        text = "# My Project Notes\n\nDeploy to staging via `make deploy`."
        assert not _looks_like_old_framework_install(text)

    def test_blank_file_is_not_old(self):
        assert not _looks_like_old_framework_install("")


# ── Integration: _write_or_merge end-to-end ─────────────────────────


@pytest.fixture
def tmp_claude(tmp_path: Path) -> Path:
    return tmp_path / "CLAUDE.md"


FRAMEWORK_GUIDE = "# Tina4 Python — Developer Guidelines\n\nFramework boilerplate here."


class TestWriteOrMerge:
    def test_fresh_install_writes_guide_plus_block(self, tmp_claude):
        action = _write_or_merge(tmp_claude, "CLAUDE.md", FRAMEWORK_GUIDE)
        assert action == "Installed"
        body = tmp_claude.read_text(encoding="utf-8")
        assert "Framework boilerplate" in body
        assert "<!-- tina4-skills:start -->" in body
        assert "<!-- tina4-skills:end -->" in body

    def test_existing_with_markers_only_refreshes_block(self, tmp_claude):
        # User's hand-curated CLAUDE.md with an existing (older) block.
        tmp_claude.write_text(
            "# My Project Notes\n\n"
            "Deploy to staging via `make deploy`.\n\n"
            "<!-- tina4-skills:start -->\n"
            "OLD BLOCK CONTENT — should be replaced\n"
            "<!-- tina4-skills:end -->\n\n"
            "Don't forget to bump the version before tagging.",
            encoding="utf-8",
        )
        action = _write_or_merge(tmp_claude, "CLAUDE.md", FRAMEWORK_GUIDE)
        assert action == "Refreshed skill block in"
        body = tmp_claude.read_text(encoding="utf-8")
        # Old block gone, new block in.
        assert "OLD BLOCK CONTENT" not in body
        assert "tina4-developer" in body
        # User content preserved on both sides.
        assert "# My Project Notes" in body
        assert "Deploy to staging via `make deploy`." in body
        assert "Don't forget to bump the version before tagging." in body
        # Framework guide is NOT injected when the user already has
        # a marker block — we only refresh the bracketed content.
        assert "Framework boilerplate" not in body

    def test_refresh_is_idempotent(self, tmp_claude):
        """Re-running the installer twice produces the same file."""
        tmp_claude.write_text("# My Notes\n", encoding="utf-8")
        _write_or_merge(tmp_claude, "CLAUDE.md", FRAMEWORK_GUIDE)
        first_pass = tmp_claude.read_text(encoding="utf-8")
        _write_or_merge(tmp_claude, "CLAUDE.md", FRAMEWORK_GUIDE)
        second_pass = tmp_claude.read_text(encoding="utf-8")
        assert first_pass == second_pass, "second run should be a no-op"

    def test_old_framework_install_is_migrated(self, tmp_claude):
        """A CLAUDE.md left behind by the pre-v3.13.9 installer always
        starts with the framework header (the old installer wrote
        from byte 0). Migration replaces that dump with the new
        framework guide + skill block."""
        tmp_claude.write_text(
            "# Tina4 Python — Developer Guidelines\n\n"
            "Old framework guide content (should be replaced)...\n"
            "More framework boilerplate the user can no longer see.\n",
            encoding="utf-8",
        )
        action = _write_or_merge(tmp_claude, "CLAUDE.md", FRAMEWORK_GUIDE)
        assert action == "Migrated (replaced old framework dump in)"
        body = tmp_claude.read_text(encoding="utf-8")
        assert "Old framework guide content" not in body, "old dump gone"
        assert "Framework boilerplate here." in body, "new guide written"
        assert "<!-- tina4-skills:start -->" in body, "skill block added"

    def test_user_content_above_old_header_is_not_migrated(self, tmp_claude):
        """Edge case: user added content ABOVE the old framework
        header (unlikely — old installer wrote at byte 0). Don't
        risk clobbering. Treat the file as user-owned and append the
        block to the end. The 'old header' string survives in the
        file, which is fine — it's just user content to us."""
        tmp_claude.write_text(
            "These are my notes above the old framework dump.\n\n"
            "# Tina4 Python — Developer Guidelines\n\n"
            "Old framework guide content...",
            encoding="utf-8",
        )
        action = _write_or_merge(tmp_claude, "CLAUDE.md", FRAMEWORK_GUIDE)
        assert action == "Appended skill block to"
        body = tmp_claude.read_text(encoding="utf-8")
        assert "These are my notes above" in body, "user content preserved"
        # The old-style header survives — it's just text to us now.
        # Safer than risking a destructive guess.
        assert "Tina4 Python — Developer Guidelines" in body
        assert "<!-- tina4-skills:start -->" in body

    def test_user_content_is_preserved_and_block_appended(self, tmp_claude):
        """A CLAUDE.md the user wrote from scratch (no markers, no
        old header) gets the skill block appended; nothing else is
        touched."""
        original = (
            "# 24rent App\n\n"
            "## Conventions\n\n"
            "- Branch naming: `feature/<jira>-<slug>`\n"
            "- Deploy: `make deploy ENV=staging`\n"
            "- Database migrations: never edit a migration once merged.\n"
        )
        tmp_claude.write_text(original, encoding="utf-8")
        action = _write_or_merge(tmp_claude, "CLAUDE.md", FRAMEWORK_GUIDE)
        assert action == "Appended skill block to"
        body = tmp_claude.read_text(encoding="utf-8")
        # Every line of the user's content is still in place.
        for line in original.splitlines():
            if line.strip():
                assert line in body, f"lost user line: {line!r}"
        # And the block was added.
        assert "<!-- tina4-skills:start -->" in body

    def test_rule_file_uses_hash_markers(self, tmp_path: Path):
        rules = tmp_path / ".cursorules"
        rules.write_text("Rule: keep handlers under 50 lines\n", encoding="utf-8")
        _write_or_merge(rules, ".cursorules", "# Cursor framework guide")
        body = rules.read_text(encoding="utf-8")
        assert "# tina4-skills:start" in body
        assert "# tina4-skills:end" in body
        assert "<!--" not in body, ".cursorules must not get HTML markers"
        assert "Rule: keep handlers under 50 lines" in body, "user rule kept"
