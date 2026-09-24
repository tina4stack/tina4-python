"""Regression: the missing-table hint on save() reaches MSSQL and Firebird.

Bug 8c (book review). When save() hits a missing table it appends a DX hint
("table 'X' does not exist; call Model.create_table() or run a migration").
The matcher only recognised SQLite ("no such table") and Postgres/MySQL
("does not exist"). MSSQL says "Invalid object name 'X'." and Firebird says
"Table unknown", so on those two engines the hint was absent and the developer
saw only the raw driver error.

NO MOCK: live MSSQL and live Firebird. Each engine guards independently; under
TINA4_REQUIRE_SERVICES an unreachable/unconfigured engine FAILS.
"""
from __future__ import annotations

import os
import socket
import uuid

import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, IntegerField, StringField, bind_database


_SUFFIX = uuid.uuid4().hex[:8]


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


class _Ghost(ORM):
    # A table that is never created — every save() hits "missing table".
    table_name = f"ghost_{_SUFFIX}"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()


def _assert_hint(db):
    bind_database(db)
    row = _Ghost({"name": "x"})
    result = row.save()
    assert result is False, "save() into a missing table must fail (False)"
    err = (row.last_error or "").lower()
    assert "does not exist" in err and "create_table" in err, (
        f"missing-table hint absent; last_error={row.last_error!r}"
    )


class TestMssqlMissingTableHint:
    def test_hint_present(self):
        url = os.environ.get("TINA4_TEST_MSSQL_URL")
        host = os.environ.get("TINA4_TEST_MSSQL_HOST", "127.0.0.1")
        port = int(os.environ.get("TINA4_TEST_MSSQL_PORT", "1433"))
        if not (url and _reachable(host, port)):
            if os.environ.get("TINA4_REQUIRE_SERVICES"):
                raise RuntimeError("TINA4_REQUIRE_SERVICES set but MSSQL not reachable/configured")
            pytest.skip("[needs:mssql] MSSQL not reachable / TINA4_TEST_MSSQL_URL unset")
        db = Database(url)
        try:
            _assert_hint(db)
        finally:
            db.close()


class TestFirebirdMissingTableHint:
    def test_hint_present(self):
        url = os.environ.get("TINA4_TEST_FIREBIRD_URL")
        if not url:
            if os.environ.get("TINA4_REQUIRE_SERVICES"):
                raise RuntimeError("TINA4_REQUIRE_SERVICES set but TINA4_TEST_FIREBIRD_URL unset")
            pytest.skip("[needs:firebird] TINA4_TEST_FIREBIRD_URL not set")
        db = Database(url)
        try:
            _assert_hint(db)
        finally:
            db.close()
