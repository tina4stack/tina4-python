"""MCP endpoint security guard (3.13.40 P0).

Locks in the per-request loopback/remote/token authorisation that replaced
the old config-based `is_localhost()` gate, plus the read-only guard on the
database_query tool. These are regression tests for the audit finding that a
0.0.0.0-bound TINA4_DEBUG box exposed the full MCP tool registry to remote
unauthenticated callers.
"""
import pytest

from tina4_python.mcp import (
    is_loopback, is_enabled, is_request_allowed, _get_default_server,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("TINA4_MCP", "TINA4_DEBUG", "TINA4_MCP_REMOTE",
              "TINA4_MCP_TOKEN", "TINA4_API_KEY", "TINA4_HOST_NAME"):
        monkeypatch.delenv(k, raising=False)
    yield


class TestIsLoopback:
    def test_loopback_addresses(self):
        for ip in ["127.0.0.1", "127.0.0.5", "::1", "::ffff:127.0.0.1", "localhost", ""]:
            assert is_loopback(ip) is True, ip

    def test_non_loopback_addresses(self):
        # 0.0.0.0 is a BIND address, never a client address -> not loopback.
        for ip in ["0.0.0.0", "1.2.3.4", "10.0.0.5", "192.168.1.10",
                   "::ffff:1.2.3.4", "2001:db8::1", "203.0.113.9"]:
            assert is_loopback(ip) is False, ip


class TestIsEnabled:
    def test_off_by_default(self):
        assert is_enabled() is False

    def test_debug_enables(self, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        assert is_enabled() is True

    def test_explicit_true(self, monkeypatch):
        monkeypatch.setenv("TINA4_MCP", "true")
        assert is_enabled() is True

    def test_explicit_false_overrides_debug(self, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        monkeypatch.setenv("TINA4_MCP", "false")
        assert is_enabled() is False

    def test_host_name_is_not_the_gate(self, monkeypatch):
        # Old bug: the configured 0.0.0.0 host flipped the gate on. is_enabled()
        # is now pure capability (debug/explicit) and ignores the host entirely.
        monkeypatch.setenv("TINA4_DEBUG", "true")
        monkeypatch.setenv("TINA4_HOST_NAME", "0.0.0.0:7145")
        assert is_enabled() is True


class TestIsRequestAllowed:
    def test_disabled_denies_even_loopback(self):
        assert is_request_allowed("127.0.0.1") is False

    def test_loopback_allowed_when_enabled(self, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        assert is_request_allowed("127.0.0.1") is True
        assert is_request_allowed("") is True  # in-process / built-in dev server

    def test_remote_denied_without_opt_in(self, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        assert is_request_allowed("1.2.3.4") is False

    def test_remote_denied_without_token(self, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        monkeypatch.setenv("TINA4_MCP_REMOTE", "true")
        assert is_request_allowed("1.2.3.4", has_valid_token=False) is False

    def test_remote_allowed_with_opt_in_and_token(self, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        monkeypatch.setenv("TINA4_MCP_REMOTE", "true")
        assert is_request_allowed("1.2.3.4", has_valid_token=True) is True

    def test_0000_bind_does_not_admit_remote(self, monkeypatch):
        # THE regression: a debug box bound to 0.0.0.0 must NOT auto-allow a
        # remote caller just because the configured host looks "local".
        monkeypatch.setenv("TINA4_DEBUG", "true")
        monkeypatch.setenv("TINA4_HOST_NAME", "0.0.0.0:7145")
        assert is_request_allowed("203.0.113.9") is False


class _FakeReq:
    def __init__(self, remote_ip="", headers=None):
        self.remote_ip = remote_ip
        self.headers = headers or {}


class TestHandlerGate:
    def test_loopback_request_allowed(self, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        from tina4_python.dev_admin import _mcp_request_allowed
        assert _mcp_request_allowed(_FakeReq("127.0.0.1")) is True

    def test_remote_request_denied(self, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        from tina4_python.dev_admin import _mcp_request_allowed
        assert _mcp_request_allowed(_FakeReq("8.8.8.8")) is False

    def test_remote_request_with_valid_bearer_token(self, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        monkeypatch.setenv("TINA4_MCP_REMOTE", "true")
        monkeypatch.setenv("TINA4_MCP_TOKEN", "s3cr3t-token")
        from tina4_python.dev_admin import _mcp_request_allowed
        assert _mcp_request_allowed(
            _FakeReq("8.8.8.8", {"authorization": "Bearer s3cr3t-token"})) is True
        assert _mcp_request_allowed(
            _FakeReq("8.8.8.8", {"authorization": "Bearer wrong"})) is False
        assert _mcp_request_allowed(_FakeReq("8.8.8.8", {})) is False


class TestDatabaseQueryReadOnly:
    def _query_tool(self):
        return _get_default_server()._tools["database_query"]["handler"]

    def _bind_memory_db(self):
        from tina4_python.orm import bind_database
        from tina4_python.database import Database
        bind_database(Database("sqlite:///:memory:"))

    def test_allows_select(self):
        self._bind_memory_db()
        out = self._query_tool()("SELECT 1 as n")
        assert "records" in out and "error" not in out

    def test_rejects_update(self):
        self._bind_memory_db()
        out = self._query_tool()("UPDATE users SET is_admin = 1")
        assert "error" in out and "read-only" in out["error"].lower()

    def test_rejects_delete_and_drop(self):
        self._bind_memory_db()
        assert "error" in self._query_tool()("DELETE FROM users")
        assert "error" in self._query_tool()("DROP TABLE users")

    def test_rejects_stacked_statement(self):
        self._bind_memory_db()
        out = self._query_tool()("SELECT 1; DROP TABLE users")
        assert "error" in out and "multiple statements" in out["error"].lower()
