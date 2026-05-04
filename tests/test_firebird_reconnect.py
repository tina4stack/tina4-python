"""
Regression tests for FirebirdAdapter dead-connection recovery.

Idle Firebird connections die silently behind NAT timeouts, server-side
ConnectionIdleTimeout, or Docker network rotation. Without a transparent
reconnect, the next cursor.execute() crashes with one of:

    "Error writing data to the connection."
    "Error reading data from the connection."
    "connection shutdown"
    "Connection is not active"

Shipped in 3.11.35: FirebirdAdapter caches connection params and runs a
one-shot reconnect+retry on cursor.execute when those markers appear.
Skipped inside an explicit transaction — atomicity wins there.
"""

import pytest
from unittest.mock import MagicMock

from tina4_python.database.firebird import FirebirdAdapter


# ── Dead-connection matcher ─────────────────────────────────────────────


@pytest.mark.parametrize("msg", [
    "Error writing data to the connection.",
    "Error reading data from the connection.",
    "connection shutdown",
    "Connection lost",
    "network error",
    "Connection is not active",
    "Broken pipe",
    # Mixed case + extra context — substring match must still trigger
    "isc_dsql_prepare: Error writing data to the connection. attached to db",
])
def test_is_dead_connection_matches_real_world_markers(msg):
    assert FirebirdAdapter._is_dead_connection(Exception(msg)) is True


@pytest.mark.parametrize("msg", [
    "syntax error at line 1, column 17",
    "table USERS does not exist",
    "violation of FOREIGN KEY constraint",
    "",
    "lock conflict on no wait transaction",
])
def test_is_dead_connection_does_not_match_logical_errors(msg):
    assert FirebirdAdapter._is_dead_connection(Exception(msg)) is False


# ── Reconnect-and-retry semantics ───────────────────────────────────────


def _adapter_with_mock_conn(conn):
    a = FirebirdAdapter()
    a._conn = conn
    a._connect_params = {
        "host": "localhost", "port": 3050, "db_path": "/tmp/test.fdb",
        "user": "SYSDBA", "password": "masterkey", "charset": "UTF8",
        "extra": {},
    }
    return a


def test_safe_cursor_execute_retries_once_on_dead_connection(monkeypatch):
    """First execute() raises a dead-connection error; reconnect happens;
    the retry on a fresh cursor succeeds. Result: caller sees no error."""
    a = _adapter_with_mock_conn(MagicMock())

    # First cursor.execute() raises the dead-conn error
    dead_cursor = MagicMock()
    dead_cursor.execute.side_effect = Exception("Error writing data to the connection.")

    # After reconnect we hand out a fresh cursor whose execute succeeds
    fresh_cursor = MagicMock()
    fresh_cursor.execute.return_value = None

    reconnect_called = {"n": 0}

    def fake_reconnect():
        reconnect_called["n"] += 1
        new_conn = MagicMock()
        new_conn.cursor.return_value = fresh_cursor
        a._conn = new_conn

    monkeypatch.setattr(a, "_reconnect", fake_reconnect)

    result = a._safe_cursor_execute(dead_cursor, "SELECT 1 FROM RDB$DATABASE", [])

    assert reconnect_called["n"] == 1, "reconnect must be invoked exactly once"
    assert result is fresh_cursor, "must return the fresh cursor for the caller to fetch from"
    fresh_cursor.execute.assert_called_once_with("SELECT 1 FROM RDB$DATABASE", [])


def test_safe_cursor_execute_does_not_retry_on_logical_errors(monkeypatch):
    """SQL syntax / FK / lock errors must surface to the caller — they're
    not network failures and retrying would mask real bugs."""
    a = _adapter_with_mock_conn(MagicMock())

    dead_cursor = MagicMock()
    dead_cursor.execute.side_effect = Exception("syntax error at line 1, column 17")

    monkeypatch.setattr(a, "_reconnect", lambda: pytest.fail("must not reconnect on logical errors"))

    with pytest.raises(Exception, match="syntax error"):
        a._safe_cursor_execute(dead_cursor, "SELECT BOGUS", [])


def test_safe_cursor_execute_does_not_retry_inside_transaction(monkeypatch):
    """Inside an explicit transaction, retrying would silently break atomicity.
    The error surfaces; the caller decides whether to rollback or restart the
    whole transaction."""
    a = _adapter_with_mock_conn(MagicMock())
    a._in_transaction = True

    dead_cursor = MagicMock()
    dead_cursor.execute.side_effect = Exception("Error writing data to the connection.")

    monkeypatch.setattr(a, "_reconnect", lambda: pytest.fail("must not reconnect inside transaction"))

    with pytest.raises(Exception, match="Error writing data"):
        a._safe_cursor_execute(dead_cursor, "INSERT INTO t VALUES (1)", [])


def test_reconnect_uses_cached_params(monkeypatch):
    """_reconnect must reopen using the params connect() cached — not just
    forget the old handle. Caller never re-passes credentials."""
    a = FirebirdAdapter()
    a._conn = None
    a._connect_params = {
        "host": "fb.example.com", "port": 3050, "db_path": "/srv/app.fdb",
        "user": "SYSDBA", "password": "masterkey", "charset": "UTF8",
        "extra": {},
    }

    opened = {"called": False, "params_seen": None}

    def fake_open():
        opened["called"] = True
        opened["params_seen"] = a._connect_params
        a._conn = MagicMock()

    monkeypatch.setattr(a, "_open", fake_open)

    a._reconnect()

    assert opened["called"], "_reconnect must call _open()"
    assert opened["params_seen"]["db_path"] == "/srv/app.fdb"
    assert opened["params_seen"]["user"] == "SYSDBA"
    # Transaction state is reset — a dead connection can never have held one
    assert a._in_transaction is False


def test_reconnect_swallows_close_errors():
    """If the stale connection's close() raises (because the socket is
    already gone), reconnect must continue rather than propagating the
    cleanup error — the new connection is what matters."""
    a = FirebirdAdapter()
    bad_conn = MagicMock()
    bad_conn.close.side_effect = Exception("connection is not active")
    a._conn = bad_conn
    a._connect_params = {
        "host": "h", "port": 3050, "db_path": "/x", "user": "u",
        "password": "p", "charset": "UTF8", "extra": {},
    }

    # Stub _open so we don't actually try to connect to a real server
    a._open = lambda: setattr(a, "_conn", MagicMock())

    a._reconnect()  # must not raise

    assert a._conn is not None
