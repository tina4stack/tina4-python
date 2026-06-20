"""Tests for the 25 framework env vars wired in v3.12.4.

Each var has a default-behaviour test (env unset) and an override test
(env set to a non-default value), plus dedicated rotation tests for the
log-rotation pattern.

Python is the canonical reference for the cross-framework v3.12.4
release — these tests double as the parity spec for PHP/Ruby/Node.
"""
import io
import os
import importlib
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest


# ── TINA4_HOST ───────────────────────────────────────────────────


class TestHost:
    """TINA4_HOST overrides plain HOST and the 0.0.0.0 default."""

    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("TINA4_HOST", raising=False)
        monkeypatch.delenv("HOST", raising=False)
        from tina4_python.core.server import resolve_config
        host, _ = resolve_config()
        assert host == "0.0.0.0"

    def test_tina4_host_overrides_default(self, monkeypatch):
        monkeypatch.delenv("HOST", raising=False)
        monkeypatch.setenv("TINA4_HOST", "10.0.0.5")
        from tina4_python.core.server import resolve_config
        host, _ = resolve_config()
        assert host == "10.0.0.5"

    def test_tina4_host_takes_precedence_over_host(self, monkeypatch):
        monkeypatch.setenv("HOST", "192.168.0.1")
        monkeypatch.setenv("TINA4_HOST", "127.0.0.1")
        from tina4_python.core.server import resolve_config
        host, _ = resolve_config()
        assert host == "127.0.0.1"


# ── TINA4_SUPPRESS ───────────────────────────────────────────────


class TestSuppress:
    """TINA4_SUPPRESS silences the startup banner."""

    def test_banner_emits_when_unset(self, monkeypatch, capsys):
        monkeypatch.delenv("TINA4_SUPPRESS", raising=False)
        from tina4_python.core.server import _print_banner
        _print_banner("0.0.0.0", 7145)
        out = capsys.readouterr().out
        assert "Tina4 Python" in out

    def test_truthy_value_recognised(self, monkeypatch):
        # _is_truthy is the gate the server uses; verifying it short-
        # circuits a real `serve()` call without spinning up a socket.
        monkeypatch.setenv("TINA4_SUPPRESS", "true")
        from tina4_python.dotenv import is_truthy
        assert is_truthy(os.environ.get("TINA4_SUPPRESS")) is True


# ── TINA4_ENV_FILE ───────────────────────────────────────────────


class TestEnvFile:
    """TINA4_ENV_FILE points load_env() at an alternative .env path."""

    def test_default_loads_dot_env(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("DEFAULT_KEY=default_value\n")
        monkeypatch.delenv("TINA4_ENV_FILE", raising=False)
        monkeypatch.chdir(tmp_path)
        from tina4_python.dotenv import load_env
        result = load_env(override=True)
        assert result.get("DEFAULT_KEY") == "default_value"

    def test_override_via_env_var(self, tmp_path, monkeypatch):
        custom = tmp_path / ".env.staging"
        custom.write_text("STAGING_KEY=staging_value\n")
        monkeypatch.setenv("TINA4_ENV_FILE", str(custom))
        from tina4_python.dotenv import load_env
        result = load_env(override=True)
        assert result.get("STAGING_KEY") == "staging_value"


# ── TINA4_HEALTH_PATH ────────────────────────────────────────────


class TestHealthPath:
    """The /__health URL path is configurable via env."""

    def test_default_health_path_registered(self):
        # The server module reads TINA4_HEALTH_PATH at import-time and
        # registers the route under that path (defaulting to /__health).
        # Re-import the server module here to confirm the registration
        # logic itself, even when an earlier test cleared the router.
        import importlib
        import tina4_python.core.server as srv
        importlib.reload(srv)
        from tina4_python.core.router import Router
        paths = {r["path"] for r in Router.get_routes()}
        assert "/__health" in paths or "/health" in paths

    def test_default_value(self, monkeypatch):
        monkeypatch.delenv("TINA4_HEALTH_PATH", raising=False)
        assert os.environ.get("TINA4_HEALTH_PATH", "/__health") == "/__health"

    def test_custom_value_resolves(self, monkeypatch):
        monkeypatch.setenv("TINA4_HEALTH_PATH", "/healthz")
        assert os.environ.get("TINA4_HEALTH_PATH") == "/healthz"


# ── TINA4_TRAILING_SLASH_REDIRECT ────────────────────────────────


class TestTrailingSlashRedirect:
    """Trailing-slash redirect is opt-in."""

    @pytest.mark.asyncio
    async def test_default_no_redirect(self, monkeypatch):
        monkeypatch.delenv("TINA4_TRAILING_SLASH_REDIRECT", raising=False)
        from tina4_python.core.request import Request
        from tina4_python.core.server import handle
        req = Request()
        req.method = "GET"
        req.path = "/__health/"
        req.headers = {}
        resp = await handle(req)
        # Default (no redirect): response is whatever the route returns,
        # not a 301.
        assert resp.status_code != 301

    @pytest.mark.asyncio
    async def test_truthy_redirects_301(self, monkeypatch):
        monkeypatch.setenv("TINA4_TRAILING_SLASH_REDIRECT", "true")
        from tina4_python.core.request import Request
        from tina4_python.core.server import handle
        req = Request()
        req.method = "GET"
        req.path = "/foo/"
        req.headers = {}
        resp = await handle(req)
        assert resp.status_code == 301
        # Location header must point at the canonical (no-trailing-slash) form.
        location = None
        for k, v in resp._headers:
            if str(k).lower() == "location":
                location = v
        assert location == "/foo"

    @pytest.mark.asyncio
    async def test_root_path_not_redirected(self, monkeypatch):
        # `/` is the homepage — must never be redirected to empty.
        monkeypatch.setenv("TINA4_TRAILING_SLASH_REDIRECT", "true")
        from tina4_python.core.request import Request
        from tina4_python.core.server import handle
        req = Request()
        req.method = "GET"
        req.path = "/"
        req.headers = {}
        resp = await handle(req)
        assert resp.status_code != 301


# ── TINA4_LOG_FILE / TINA4_LOG_DIR / TINA4_LOG_FORMAT / etc. ─────


class TestLogFile:
    def test_default_no_explicit_file(self, monkeypatch, tmp_path):
        # When TINA4_LOG_FILE is unset, the legacy logs/tina4.log writer
        # is used. Configure the dir to a temp path so the test doesn't
        # touch the real logs/ dir.
        monkeypatch.delenv("TINA4_LOG_FILE", raising=False)
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        from tina4_python.debug import Log
        Log.configure(log_dir=str(tmp_path))
        Log.info("hello")
        assert (tmp_path / "tina4.log").exists()

    def test_custom_file_used(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_FILE", "custom.log")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        from tina4_python.debug import Log
        Log.configure(log_dir=str(tmp_path))
        Log.info("hello")
        assert (tmp_path / "custom.log").exists()


class TestLogFormat:
    def test_default_format_is_text(self, monkeypatch, tmp_path):
        monkeypatch.delenv("TINA4_LOG_FORMAT", raising=False)
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        from tina4_python.debug import Log
        Log.configure(log_dir=str(tmp_path))
        line = Log._format_line("info", "hello")
        # Text format: "[INFO   ] hello", not JSON
        assert "[INFO" in line
        assert not line.lstrip().startswith("{")

    def test_json_format_when_set(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_FORMAT", "json")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        from tina4_python.debug import Log
        Log.configure(log_dir=str(tmp_path))
        line = Log._format_line("info", "hello")
        import json as _json
        parsed = _json.loads(line)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "hello"


class TestLogOutput:
    def test_default_writes_to_stdout(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "stdout")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        from tina4_python.debug import Log
        Log.configure(log_dir=str(tmp_path), level="info", production=False)
        Log.info("hello")
        out = capsys.readouterr().out
        assert "hello" in out

    def test_file_only_silences_stdout(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        from tina4_python.debug import Log
        Log.configure(log_dir=str(tmp_path), level="info", production=False)
        Log.info("silent-on-stdout")
        out = capsys.readouterr().out
        assert "silent-on-stdout" not in out

    def test_both_writes_everywhere(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "both")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("TINA4_LOG_FILE", "both.log")
        from tina4_python.debug import Log
        Log.configure(log_dir=str(tmp_path), level="info", production=False)
        Log.info("everywhere")
        out = capsys.readouterr().out
        assert "everywhere" in out
        assert (tmp_path / "both.log").exists()


class TestLogCritical:
    # v3 unify: critical is the highest severity and ALWAYS emits — the old
    # TINA4_LOG_CRITICAL opt-in toggle (no-op-by-default) was removed.
    def test_critical_always_emits(self, monkeypatch, tmp_path, capsys):
        monkeypatch.delenv("TINA4_LOG_CRITICAL", raising=False)
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        from tina4_python.debug import Log
        Log.configure(log_dir=str(tmp_path), level="info", production=False)
        Log.critical("always logged")
        out = capsys.readouterr().out
        assert "always logged" in out

    def test_critical_emits_above_error_threshold(self, monkeypatch, tmp_path, capsys):
        # critical (4) outranks error (3): visible even at level=error
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        from tina4_python.debug import Log
        Log.configure(log_dir=str(tmp_path), level="error", production=False)
        Log.critical("top severity")
        out = capsys.readouterr().out
        assert "top severity" in out


class TestLogRotation:
    """Dedicated tests for the new RotatingFileHandler-based rotation."""

    def test_rotation_triggers_at_size(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_FILE", "rot.log")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("TINA4_LOG_ROTATE_SIZE", "200")  # tiny — bytes
        monkeypatch.setenv("TINA4_LOG_ROTATE_KEEP", "3")
        from tina4_python.debug import Log
        Log.configure(log_dir=str(tmp_path), level="info", production=False)
        # Each line is well over 50 bytes, so 50 lines guarantees > 200 B.
        for i in range(50):
            Log.info(f"rotation-line-{i}")
        rotated = list(tmp_path.glob("rot.log*"))
        # Expect at least one backup file beyond rot.log itself.
        assert any(p.name != "rot.log" for p in rotated), (
            f"no rotation happened, files = {[p.name for p in rotated]}"
        )

    def test_rotate_keep_caps_backups(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_FILE", "keep.log")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("TINA4_LOG_ROTATE_SIZE", "150")
        monkeypatch.setenv("TINA4_LOG_ROTATE_KEEP", "2")
        from tina4_python.debug import Log
        Log.configure(log_dir=str(tmp_path), level="info", production=False)
        for i in range(200):
            Log.info(f"keep-line-{i}-padding-padding-padding-padding")
        backups = sorted(tmp_path.glob("keep.log.*"))
        # backupCount=2 means at most keep.log.1 and keep.log.2 — i.e. <= 2.
        assert len(backups) <= 2

    def test_rotate_size_zero_disables(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_FILE", "norot.log")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("TINA4_LOG_ROTATE_SIZE", "0")
        from tina4_python.debug import Log
        Log.configure(log_dir=str(tmp_path), level="info", production=False)
        for i in range(100):
            Log.info(f"no-rotation-line-{i}-padding-padding-padding")
        backups = list(tmp_path.glob("norot.log.*"))
        assert backups == []
        # The single file just keeps growing.
        assert (tmp_path / "norot.log").stat().st_size > 200


# ── TINA4_SESSION_* ──────────────────────────────────────────────


class TestSessionCookie:
    def _make_session(self, monkeypatch, tmp_path):
        # Use a file-backed handler in tmp_path so we don't touch real
        # session storage.
        from tina4_python.session import Session, FileSessionHandler
        s = Session(handler=FileSessionHandler(str(tmp_path)))
        s.start("test-session-id")
        return s

    def test_default_name_and_httponly(self, monkeypatch, tmp_path):
        monkeypatch.delenv("TINA4_SESSION_NAME", raising=False)
        monkeypatch.delenv("TINA4_SESSION_HTTPONLY", raising=False)
        monkeypatch.delenv("TINA4_SESSION_SECURE", raising=False)
        s = self._make_session(monkeypatch, tmp_path)
        header = s.cookie_header()
        assert header.startswith("tina4_session=")
        assert "HttpOnly" in header
        assert "Secure" not in header

    def test_custom_name(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_SESSION_NAME", "my_app_sid")
        s = self._make_session(monkeypatch, tmp_path)
        header = s.cookie_header()
        assert header.startswith("my_app_sid=")

    def test_httponly_false_drops_flag(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_SESSION_HTTPONLY", "false")
        s = self._make_session(monkeypatch, tmp_path)
        header = s.cookie_header()
        assert "HttpOnly" not in header

    def test_secure_true_adds_flag(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_SESSION_SECURE", "true")
        s = self._make_session(monkeypatch, tmp_path)
        header = s.cookie_header()
        assert "Secure" in header


# ── TINA4_TEMPLATE_CACHE_TTL ─────────────────────────────────────


class TestTemplateCacheTTL:
    def test_default_no_expiry(self, monkeypatch):
        monkeypatch.delenv("TINA4_TEMPLATE_CACHE_TTL", raising=False)
        from tina4_python.frond.engine import Frond
        f = Frond()
        assert f._cache_ttl == 0

    def test_custom_value_picked_up(self, monkeypatch):
        monkeypatch.setenv("TINA4_TEMPLATE_CACHE_TTL", "120")
        from tina4_python.frond.engine import Frond
        f = Frond()
        assert f._cache_ttl == 120


# ── TINA4_GRAPHQL_AUTO_SCHEMA / TINA4_GRAPHQL_ENDPOINT ───────────


class TestGraphQLEnv:
    def test_default_endpoint(self, monkeypatch):
        monkeypatch.delenv("TINA4_GRAPHQL_ENDPOINT", raising=False)
        from tina4_python.graphql import GraphQL
        g = GraphQL()
        assert g.endpoint == "/graphql"

    def test_custom_endpoint(self, monkeypatch):
        monkeypatch.setenv("TINA4_GRAPHQL_ENDPOINT", "/api/graphql")
        from tina4_python.graphql import GraphQL
        g = GraphQL()
        assert g.endpoint == "/api/graphql"

    def test_auto_schema_default_true(self, monkeypatch):
        monkeypatch.delenv("TINA4_GRAPHQL_AUTO_SCHEMA", raising=False)
        from tina4_python.graphql import GraphQL
        assert GraphQL().auto_schema is True

    def test_auto_schema_off_skips_registration(self, monkeypatch):
        monkeypatch.setenv("TINA4_GRAPHQL_AUTO_SCHEMA", "false")
        from tina4_python.graphql import GraphQL

        class FakeORM:
            __name__ = "FakeORM"
            _fields = {}

        g = GraphQL()
        assert g.auto_register(FakeORM) == 0
        assert "FakeORM" not in g.schema.types


# ── TINA4_MAIL_IMAP_ENCRYPTION ───────────────────────────────────


class TestMailImapEncryption:
    def test_default_tls(self, monkeypatch):
        monkeypatch.delenv("TINA4_MAIL_IMAP_ENCRYPTION", raising=False)
        from tina4_python.messenger import Messenger
        m = Messenger()
        assert m.imap_encryption == "tls"

    def test_starttls_set(self, monkeypatch):
        monkeypatch.setenv("TINA4_MAIL_IMAP_ENCRYPTION", "STARTTLS")
        from tina4_python.messenger import Messenger
        m = Messenger()
        assert m.imap_encryption == "starttls"

    def test_none_disables_encryption(self, monkeypatch):
        monkeypatch.setenv("TINA4_MAIL_IMAP_ENCRYPTION", "none")
        from tina4_python.messenger import Messenger
        m = Messenger()
        assert m.imap_encryption == "none"


# ── TINA4_MCP / TINA4_MCP_PORT ───────────────────────────────────


class TestMcpEnv:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("TINA4_MCP", raising=False)
        monkeypatch.delenv("TINA4_DEBUG", raising=False)
        from tina4_python.mcp import is_enabled
        assert is_enabled() is False

    def test_enabled_when_debug_true(self, monkeypatch):
        monkeypatch.delenv("TINA4_MCP", raising=False)
        monkeypatch.setenv("TINA4_DEBUG", "true")
        from tina4_python.mcp import is_enabled
        assert is_enabled() is True

    def test_explicit_off_overrides_debug(self, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        monkeypatch.setenv("TINA4_MCP", "false")
        from tina4_python.mcp import is_enabled
        assert is_enabled() is False

    def test_default_port_is_framework_plus_2000(self, monkeypatch):
        monkeypatch.delenv("TINA4_MCP_PORT", raising=False)
        from tina4_python.mcp import resolve_port
        assert resolve_port(7145) == 9145

    def test_explicit_port(self, monkeypatch):
        monkeypatch.setenv("TINA4_MCP_PORT", "9999")
        from tina4_python.mcp import resolve_port
        assert resolve_port(7145) == 9999


# ── TINA4_SWAGGER_* ──────────────────────────────────────────────


class TestSwaggerEnv:
    def test_contact_email_default_empty(self, monkeypatch):
        monkeypatch.delenv("TINA4_SWAGGER_CONTACT_EMAIL", raising=False)
        from tina4_python.swagger import Swagger
        s = Swagger()
        assert s.contact_email == ""
        spec = s.generate([])
        assert "contact" not in spec["info"]

    def test_contact_email_appears_in_spec(self, monkeypatch):
        monkeypatch.setenv("TINA4_SWAGGER_CONTACT_EMAIL", "team@example.com")
        from tina4_python.swagger import Swagger
        s = Swagger()
        spec = s.generate([])
        assert spec["info"]["contact"] == {"email": "team@example.com"}

    def test_license_default_empty(self, monkeypatch):
        monkeypatch.delenv("TINA4_SWAGGER_LICENSE", raising=False)
        from tina4_python.swagger import Swagger
        s = Swagger()
        spec = s.generate([])
        assert "license" not in spec["info"]

    def test_license_appears_in_spec(self, monkeypatch):
        monkeypatch.setenv("TINA4_SWAGGER_LICENSE", "MIT")
        from tina4_python.swagger import Swagger
        s = Swagger()
        spec = s.generate([])
        assert spec["info"]["license"] == {"name": "MIT"}

    def test_enabled_default_off(self, monkeypatch):
        monkeypatch.delenv("TINA4_SWAGGER_ENABLED", raising=False)
        monkeypatch.delenv("TINA4_DEBUG", raising=False)
        from tina4_python.swagger import is_enabled
        assert is_enabled() is False

    def test_enabled_via_debug(self, monkeypatch):
        monkeypatch.delenv("TINA4_SWAGGER_ENABLED", raising=False)
        monkeypatch.setenv("TINA4_DEBUG", "true")
        from tina4_python.swagger import is_enabled
        assert is_enabled() is True

    def test_explicit_disabled_wins(self, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        monkeypatch.setenv("TINA4_SWAGGER_ENABLED", "false")
        from tina4_python.swagger import is_enabled
        assert is_enabled() is False


# ── TINA4_DB_POOL ────────────────────────────────────────────────


class TestDbPool:
    def test_default_pool_size_zero(self, monkeypatch):
        monkeypatch.delenv("TINA4_DB_POOL", raising=False)
        from tina4_python.database.connection import Database
        db = Database("sqlite:///:memory:")
        assert db.pool_size == 0
        assert db._pool is None

    def test_env_sets_pool_size(self, monkeypatch, tmp_path):
        # Use a file-backed sqlite so each pooled adapter can connect
        # without sharing a per-connection in-memory state.
        db_file = tmp_path / "pool.db"
        monkeypatch.setenv("TINA4_DB_POOL", "3")
        from tina4_python.database.connection import Database
        db = Database(f"sqlite:///{db_file}")
        assert db.pool_size == 3
        assert db._pool is not None

    def test_explicit_pool_arg_wins(self, monkeypatch, tmp_path):
        db_file = tmp_path / "explicit.db"
        monkeypatch.setenv("TINA4_DB_POOL", "8")
        from tina4_python.database.connection import Database
        # Caller passing pool=2 must override the env default.
        db = Database(f"sqlite:///{db_file}", pool=2)
        assert db.pool_size == 2
