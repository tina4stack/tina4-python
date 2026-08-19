"""Parity Group E — renames + new symbols where docs read better.

* tina4_python.ai: detect_ai / detect_ai_names / install_context / status_report
* queue.consume(job_id=) renamed from consume(id=)
* Api.send_request() — one name in all four (reverted the 3.13.0 Api.send() rename;
  Ruby cannot use bare `send` because it is Object#send)
* I18n(locale=, path=) preferred over I18n(locale_dir=, default_locale=)
* TINA4_TOKEN_EXPIRES_IN env var now controls JWT expiry (was TINA4_TOKEN_LIMIT)
"""
from __future__ import annotations

import pytest


# ─── ai.detect_ai / detect_ai_names / install_context / status_report ─────


@pytest.fixture(autouse=True)
def _sandbox_home_for_ai_installer(tmp_path, monkeypatch):
    """install_context()/install_skills() write to BOTH the target root AND
    Path.home()/.claude/skills (global install, by design). In a shared test
    environment that second write races other tests and can hit a stale root-
    owned file from a prior sudo run -- a per-test HOME redirects the global
    install to a throwaway dir, so each test's Path.home() is exclusive to
    that test."""
    monkeypatch.setenv("HOME", str(tmp_path / "_test_home"))


class TestAINewFunctions:
    def test_detect_ai_returns_list_of_dicts(self, tmp_path):
        from tina4_python.ai import detect_ai
        tools = detect_ai(str(tmp_path))
        assert isinstance(tools, list)
        assert len(tools) > 0
        for tool in tools:
            assert "name" in tool
            assert "installed" in tool
            assert tool["installed"] is False  # tmp_path is empty

    def test_detect_ai_marks_installed_for_existing_context(self, tmp_path):
        from tina4_python.ai import detect_ai
        (tmp_path / "CLAUDE.md").write_text("ctx")

        tools = detect_ai(str(tmp_path))
        claude = next(t for t in tools if t["name"] == "claude-code")
        assert claude["installed"] is True

    def test_detect_ai_names_returns_only_installed(self, tmp_path):
        from tina4_python.ai import detect_ai_names
        names = detect_ai_names(str(tmp_path))
        assert names == []   # nothing installed in empty tmp_path

        (tmp_path / "CLAUDE.md").write_text("ctx")
        (tmp_path / ".cursorules").write_text("ctx")
        names = detect_ai_names(str(tmp_path))
        assert "claude-code" in names
        assert "cursor" in names
        assert "copilot" not in names  # not installed

    def test_status_report_returns_string(self, tmp_path):
        from tina4_python.ai import status_report
        report = status_report(str(tmp_path))
        assert isinstance(report, str)
        assert "AI tool status" in report
        # Should mention each known tool by description
        assert "Claude Code" in report
        assert "Cursor" in report

    def test_status_report_counts_installed(self, tmp_path):
        from tina4_python.ai import status_report
        (tmp_path / "CLAUDE.md").write_text("ctx")
        report = status_report(str(tmp_path))
        # Should show installed marker for Claude
        assert "✓ installed" in report

    def test_install_context_no_args_installs_all(self, tmp_path):
        from tina4_python.ai import install_context, AI_TOOLS
        created = install_context(str(tmp_path))
        assert len(created) > 0
        # Top-level Claude context should exist
        assert (tmp_path / "CLAUDE.md").exists()

    def test_install_context_with_specific_tool(self, tmp_path):
        from tina4_python.ai import install_context
        created = install_context(str(tmp_path), tools=["claude-code"])
        assert (tmp_path / "CLAUDE.md").exists()
        # Cursor should NOT have been installed
        assert not (tmp_path / ".cursorules").exists()

    def test_install_context_unknown_tool_raises(self, tmp_path):
        from tina4_python.ai import install_context
        with pytest.raises(ValueError, match="Unknown AI tool"):
            install_context(str(tmp_path), tools=["nonexistent"])


# ─── queue.consume(job_id=) renamed from consume(id=) ─────────────────────


class TestQueueConsumeJobIdKwarg:
    def test_job_id_kwarg_works(self, tmp_path, monkeypatch):
        from tina4_python.queue import Queue
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path))

        q = Queue(topic="parity-e-consume")
        q.push({"x": 1})
        job = q.pop()

        # consume with job_id=<the id> should single-yield that job
        # (we put it back first since we just popped it)
        q.push({"x": 2, "id": "specific"})
        # Don't actually run the generator — just verify the kwarg is accepted
        gen = q.consume(topic="parity-e-consume", job_id="some-id-that-doesnt-exist", iterations=1)
        # Generator should iterate without crashing
        list(gen)  # empty since job_id doesn't match anything
        q.clear()


# ─── Api.send_request() — the one name all four frameworks share ───────────


class TestApiSendRequestName:
    """The arbitrary-method HTTP call is ``send_request`` in every framework.

    This REVERSES the Python-only rename to ``send`` made in 3.13.0. ``send``
    can never be the shared name: Ruby's ``send`` is ``Object#send`` (the
    metaprogramming primitive that invokes any method by name), so a Ruby class
    cannot expose an HTTP ``send`` without shadowing it. ``send_request`` is the
    only spelling all four can adopt — PHP ``sendRequest``, Ruby
    ``send_request``, Node ``sendRequest`` already do.
    """

    def test_send_request_method_exists(self):
        from tina4_python.api import Api
        api = Api("https://example.test")
        assert callable(api.send_request)

    def test_send_removed(self):
        """The old name is gone — no aliases, the primary is renamed."""
        from tina4_python.api import Api
        api = Api("https://example.test")
        assert not hasattr(api, "send")


# ─── I18n(locale=, path=) ─────────────────────────────────────────────────


class TestI18nNewKwargs:
    def test_new_kwargs(self, tmp_path):
        from tina4_python.i18n import I18n
        (tmp_path / "en.json").write_text('{"hello": "Hello"}')
        i18n = I18n(locale="en", path=str(tmp_path))
        assert i18n.t("hello") == "Hello"

    def test_legacy_kwargs_still_work(self, tmp_path):
        """Legacy kwarg names remain for backward compat with existing apps."""
        from tina4_python.i18n import I18n
        (tmp_path / "en.json").write_text('{"hello": "Hello"}')
        i18n = I18n(locale_dir=str(tmp_path), default_locale="en")
        assert i18n.t("hello") == "Hello"

    def test_new_wins_when_both_set(self, tmp_path):
        from tina4_python.i18n import I18n
        (tmp_path / "fr.json").write_text('{"hello": "Bonjour"}')
        (tmp_path / "en.json").write_text('{"hello": "Hello"}')
        # locale=fr should win over default_locale=en
        i18n = I18n(locale="fr", path=str(tmp_path), default_locale="en")
        assert i18n.t("hello") == "Bonjour"


# ─── TINA4_TOKEN_EXPIRES_IN for JWT ───────────────────────────────────────


class TestJWTTokenExpiresInEnvVar:
    def test_token_expires_in_controls_jwt(self, monkeypatch):
        from tina4_python.auth import Auth
        monkeypatch.delenv("TINA4_TOKEN_LIMIT", raising=False)
        monkeypatch.setenv("TINA4_TOKEN_EXPIRES_IN", "45")
        auth = Auth(secret="parity-e-secret")
        assert auth.expires_in == 45

    def test_token_limit_still_works_legacy(self, monkeypatch):
        from tina4_python.auth import Auth
        monkeypatch.delenv("TINA4_TOKEN_EXPIRES_IN", raising=False)
        monkeypatch.setenv("TINA4_TOKEN_LIMIT", "33")
        auth = Auth(secret="parity-e-secret")
        assert auth.expires_in == 33

    def test_token_expires_in_wins_when_both_set(self, monkeypatch):
        from tina4_python.auth import Auth
        monkeypatch.setenv("TINA4_TOKEN_LIMIT", "100")
        monkeypatch.setenv("TINA4_TOKEN_EXPIRES_IN", "30")
        auth = Auth(secret="parity-e-secret")
        assert auth.expires_in == 30

    def test_constructor_arg_wins_over_env(self, monkeypatch):
        from tina4_python.auth import Auth
        monkeypatch.setenv("TINA4_TOKEN_EXPIRES_IN", "60")
        auth = Auth(secret="parity-e-secret", expires_in=5)
        assert auth.expires_in == 5
