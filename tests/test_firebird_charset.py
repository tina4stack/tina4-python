"""#160 — the Firebird adapter must honour a charset override.

The adapter used to hardcode the connection charset to UTF8 with no override,
double-encoding UTF-8 bytes stored under a legacy NONE database. The charset is
now resolved from, in precedence order:

    1. the connection URL query   firebird://host:port/path?charset=NONE
    2. an explicit charset= kwarg passed to connect()
    3. the TINA4_DATABASE_CHARSET environment variable
    4. the UTF8 default (unchanged — non-breaking)

These exercise the PURE config resolver ``_resolve_firebird_charset`` directly.
It opens NO connection (it only parses a URL, a kwarg, and an env var), so this
is pure-logic — not a mocked DB. The live double-encode fix itself is verified
in the PHP mirror where php #160 was reported (real Firebird is not available
on this runner).
"""
import pytest

from tina4_python.database.firebird import _resolve_firebird_charset


def test_default_is_utf8(monkeypatch):
    monkeypatch.delenv("TINA4_DATABASE_CHARSET", raising=False)
    assert _resolve_firebird_charset("firebird://localhost:3050/employee") == "UTF8"


def test_url_query_charset_wins(monkeypatch):
    monkeypatch.delenv("TINA4_DATABASE_CHARSET", raising=False)
    assert _resolve_firebird_charset(
        "firebird://localhost:3050/employee?charset=NONE"
    ) == "NONE"


def test_url_query_charset_overrides_env(monkeypatch):
    monkeypatch.setenv("TINA4_DATABASE_CHARSET", "WIN1252")
    assert _resolve_firebird_charset(
        "firebird://localhost:3050/employee?charset=NONE"
    ) == "NONE", "URL query param must win over the env var"


def test_env_used_when_no_url_param(monkeypatch):
    monkeypatch.setenv("TINA4_DATABASE_CHARSET", "ISO8859_1")
    assert _resolve_firebird_charset(
        "firebird://localhost:3050/employee"
    ) == "ISO8859_1"


def test_kwarg_used_when_no_url_param(monkeypatch):
    """An explicit charset kwarg (Database(url, charset=...)) beats env/default
    but yields to a URL query param."""
    monkeypatch.delenv("TINA4_DATABASE_CHARSET", raising=False)
    assert _resolve_firebird_charset(
        "firebird://localhost:3050/employee", "WIN1251"
    ) == "WIN1251"


def test_url_param_beats_kwarg(monkeypatch):
    monkeypatch.delenv("TINA4_DATABASE_CHARSET", raising=False)
    assert _resolve_firebird_charset(
        "firebird://localhost:3050/employee?charset=NONE", "UTF8"
    ) == "NONE"


def test_charset_query_does_not_pollute_db_path(monkeypatch):
    """A ?charset= query must not leak into the resolved DB identifier — the
    double-slash absolute path form still resolves cleanly alongside it."""
    from tina4_python.database.firebird import _normalize_firebird_db_identifier
    from urllib.parse import urlparse

    parsed = urlparse("firebird://localhost:3050//data/app.fdb?charset=NONE")
    assert _normalize_firebird_db_identifier(parsed.path) == "/data/app.fdb"
    assert _resolve_firebird_charset(
        "firebird://localhost:3050//data/app.fdb?charset=NONE"
    ) == "NONE"
