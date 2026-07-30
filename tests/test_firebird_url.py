"""Firebird URL parsing + TINA4_DATABASE_FIREBIRD_PATH override tests.

The Firebird URL is the awkward one in the stack — every other engine
(PostgreSQL, MySQL, MSSQL) has a server-side database name where you can
write `pg://host:port/dbname` and the path component is just a name.
Firebird wants either an absolute file path on the server, a Windows
drive-letter path, or an alias. The classic URI form needs a double
slash to keep the absolute path through ``urlparse``, which is unintuitive.

This suite verifies the framework accepts five equivalent forms and
also honours ``TINA4_DATABASE_FIREBIRD_PATH`` as an explicit override
(useful for Windows backslash paths and ops setups that keep config
split across layers).
"""
from __future__ import annotations

import socket

import pytest

from tina4_python.database.firebird import _normalize_firebird_db_identifier


# ── _normalize_firebird_db_identifier ────────────────────────────────────


class TestFirebirdUrlNormalize:

    def test_classic_double_slash_absolute_path(self):
        # firebird://host:port//abs/path/db.fdb → urlparse path = //abs/path/db.fdb
        assert _normalize_firebird_db_identifier("//firebird/data/app.fdb") \
            == "/firebird/data/app.fdb"

    def test_single_slash_absolute_path(self):
        # firebird://host:port/abs/path/db.fdb → urlparse path = /abs/path/db.fdb
        assert _normalize_firebird_db_identifier("/firebird/data/app.fdb") \
            == "/firebird/data/app.fdb"

    def test_windows_drive_letter_with_leading_slash(self):
        # firebird://host:port/C:/Data/db.fdb → urlparse path = /C:/Data/db.fdb
        assert _normalize_firebird_db_identifier("/C:/Data/app.fdb") \
            == "C:/Data/app.fdb"

    def test_windows_drive_letter_url_encoded(self):
        # firebird://host:port/C%3A/Data/db.fdb → urlparse path = /C%3A/Data/db.fdb
        assert _normalize_firebird_db_identifier("/C%3A/Data/app.fdb") \
            == "C:/Data/app.fdb"

    def test_alias_single_token(self):
        # firebird://host:port/employee → urlparse path = /employee
        assert _normalize_firebird_db_identifier("/employee") == "employee"

    def test_relative_path_with_slash_gets_promoted_to_absolute(self):
        # If user writes a path-like value without a leading slash, we
        # treat it as an absolute path (Firebird doesn't have a notion
        # of relative paths anyway). Prepend a slash so the driver sees
        # an absolute path and errors clearly if it doesn't exist.
        assert _normalize_firebird_db_identifier("data/app.fdb") \
            == "/data/app.fdb"

    def test_url_encoded_unicode_in_path(self):
        # Path with URL-encoded non-ASCII char — decoded correctly.
        assert _normalize_firebird_db_identifier("/data/d%C3%A9j%C3%A0.fdb") \
            == "/data/déjà.fdb"

    def test_lowercase_drive_letter(self):
        # Lowercase drive letters must work the same as uppercase.
        assert _normalize_firebird_db_identifier("/c:/data/app.fdb") \
            == "c:/data/app.fdb"


# ── End-to-end against a live Firebird container ─────────────────────────


def _live_firebird_target() -> tuple[str, int, str]:
    """Resolve the live-Firebird host, port and database path.

    Reads TINA4_TEST_FIREBIRD_URL -- the SAME variable the rest of this suite and
    the Ruby / Node suites already use -- so one export points every framework at
    the same container.

    These three values were hardcoded to localhost:53050 and
    /firebird/data/tina4.fdb. Nothing publishes 53050 on the lab host (Firebird is
    on 3050), so the reachability gate below could NEVER open: the three live
    tests skipped green on every machine, which is indistinguishable from
    "environment not set up" and is exactly how a permanently dead test stays
    invisible. The literals stay as the fallback, so a host that really does
    publish 53050 with that database path behaves precisely as before.
    """
    import os as _os
    from urllib.parse import urlparse

    url = _os.environ.get("TINA4_TEST_FIREBIRD_URL", "").strip()
    if not url:
        return "localhost", 53050, "/firebird/data/tina4.fdb"

    parsed = urlparse(url)
    path = parsed.path or ""
    # `@host:port//abs/path` is the absolute-path spelling; collapse the doubled
    # leading slash so this is a plain absolute path again. The tests below
    # re-add it for the double-slash case and strip it for the single-slash one.
    if path.startswith("//"):
        path = path[1:]
    return (
        parsed.hostname or "localhost",
        parsed.port or 3050,
        path or "/firebird/data/tina4.fdb",
    )


FIREBIRD_HOST, FIREBIRD_PORT, LIVE_DB_PATH_DEFAULT = _live_firebird_target()


def _firebird_reachable() -> bool:
    try:
        with socket.create_connection((FIREBIRD_HOST, FIREBIRD_PORT), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark_live = pytest.mark.skipif(
    not _firebird_reachable(),
    reason=f"Firebird not reachable at {FIREBIRD_HOST}:{FIREBIRD_PORT}",
)

LIVE_DB_PATH = LIVE_DB_PATH_DEFAULT


class TestLiveFirebirdTargetResolution:
    """The gate's own coordinates are resolved, not hardcoded.

    A pure function over a real environment variable -- no doubles. Without these
    the port could silently drift back to a value nothing publishes and the live
    tests would resume skipping green, which is the failure this fix exists to
    end.
    """

    @staticmethod
    def _with_url(value):
        """Set (or clear) TINA4_TEST_FIREBIRD_URL and resolve, then restore."""
        import os as _os

        key = "TINA4_TEST_FIREBIRD_URL"
        previous = _os.environ.get(key)
        try:
            if value is None:
                _os.environ.pop(key, None)
            else:
                _os.environ[key] = value
            return _live_firebird_target()
        finally:
            if previous is None:
                _os.environ.pop(key, None)
            else:
                _os.environ[key] = previous

    def test_unset_falls_back_to_the_historic_literals(self):
        assert self._with_url(None) == ("localhost", 53050, "/firebird/data/tina4.fdb")

    def test_blank_is_treated_as_unset(self):
        assert self._with_url("   ") == ("localhost", 53050, "/firebird/data/tina4.fdb")

    def test_absolute_double_slash_form_is_parsed(self):
        host, port, path = self._with_url(
            "firebird://SYSDBA:masterkey@db.example:3050//var/lib/firebird/data/x.fdb"
        )
        assert (host, port) == ("db.example", 3050)
        # One leading slash, not two -- the callers re-add the second for the
        # double-slash spelling and strip it for the single-slash one.
        assert path == "/var/lib/firebird/data/x.fdb"

    def test_single_slash_form_is_parsed(self):
        assert self._with_url("firebird://SYSDBA:masterkey@h:3050/rel.fdb") == (
            "h",
            3050,
            "/rel.fdb",
        )

    def test_omitted_port_defaults_to_3050_not_53050(self):
        # THE REGRESSION GUARD: 53050 must never come back as a parsed default.
        _, port, _ = self._with_url("firebird://SYSDBA:masterkey@h//data/x.fdb")
        assert port == 3050


@pytestmark_live
class TestFirebirdUrlLive:
    """Each form should connect to the same database when the framework
    is given a live Firebird container."""

    def _connect(self, url: str, **env):
        from tina4_python.database import Database
        # Apply env overrides for this connect call only
        import os as _os
        old = {k: _os.environ.get(k) for k in env}
        try:
            for k, v in env.items():
                if v is None:
                    _os.environ.pop(k, None)
                else:
                    _os.environ[k] = v
            return Database(url)
        finally:
            for k, v in old.items():
                if v is None:
                    _os.environ.pop(k, None)
                else:
                    _os.environ[k] = v

    def test_double_slash_form_connects(self):
        url = f"firebird://SYSDBA:masterkey@{FIREBIRD_HOST}:{FIREBIRD_PORT}/{LIVE_DB_PATH}"
        # Note: by writing /<path>, after urlparse we get path = /<path>
        # _normalize will return /<path> as-is. Live connect.
        db = self._connect(url)
        assert db.fetch_one("SELECT 1 AS x FROM rdb$database")["x"] == 1
        db.close()

    def test_single_slash_form_connects(self):
        # Same path, but written as single-slash relative-from-root form.
        url = f"firebird://SYSDBA:masterkey@{FIREBIRD_HOST}:{FIREBIRD_PORT}/{LIVE_DB_PATH.lstrip('/')}"
        db = self._connect(url)
        # Should work — _normalize promotes "data/app.fdb" → "/data/app.fdb"
        assert db.fetch_one("SELECT 1 AS x FROM rdb$database")["x"] == 1
        db.close()

    def test_env_override_wins_over_url(self):
        # Provide a deliberately wrong URL path; the env override points
        # at the real DB. The framework should connect to the real one.
        wrong_url = (
            f"firebird://SYSDBA:masterkey@{FIREBIRD_HOST}:{FIREBIRD_PORT}"
            "/this/path/does/not/exist.fdb"
        )
        db = self._connect(wrong_url, TINA4_DATABASE_FIREBIRD_PATH=LIVE_DB_PATH)
        assert db.fetch_one("SELECT 1 AS x FROM rdb$database")["x"] == 1
        db.close()
