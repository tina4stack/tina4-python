# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Parity lock for tina4-php#280: the `pgsql://` scheme (and every documented
alias) resolves, and resolves to the same engine as its canonical spelling.

Python already accepts `pgsql` (added under issue #58); this LOCKS that contract
so it cannot silently regress the way PHP's did (DatabaseUrl mapped `pgsql` but
Database::create refused it). The canonical scheme set is shared by all four
frameworks:

    sqlite / sqlite3            -> sqlite
    postgres / postgresql / pgsql -> postgres   (pgsql is PDO / Laravel / Doctrine)
    mysql                       -> mysql
    mssql / sqlserver           -> mssql
    firebird                    -> firebird

No mocks: the sqlite aliases are proven end to end against a real in-memory
database; the server-engine aliases are proven against the real driver registry
(resolving a live server here would need that server). A genuinely unknown scheme
is NOT resolvable — it must never quietly fall through to SQLite.
"""

import pytest

from tina4_python.database import Database
from tina4_python.database.connection import known_drivers, _LAZY_DRIVERS


def test_sqlite_aliases_resolve_to_the_sqlite_engine():
    # Real round-trip: both spellings open an in-memory SQLite database and the
    # adapter reports the canonical engine. `sqlite3://` is normalised to sqlite.
    for url in ("sqlite:///:memory:", "sqlite3:///:memory:"):
        db = Database(url)
        try:
            assert db.get_database_type() == "sqlite", f"{url} must resolve to sqlite"
        finally:
            db.close()


@pytest.mark.parametrize("scheme", [
    "sqlite", "postgres", "postgresql", "pgsql", "mysql", "mssql", "sqlserver", "firebird",
])
def test_every_server_scheme_is_a_known_driver(scheme):
    assert scheme in known_drivers(), f"{scheme}:// must be an accepted database scheme (#280)"


def test_pgsql_and_postgresql_resolve_to_the_postgres_adapter():
    # The exact #280 point: the alias maps to the SAME adapter as `postgres`,
    # not merely to "something". _LAZY_DRIVERS value is (module, class).
    assert _LAZY_DRIVERS["pgsql"] == _LAZY_DRIVERS["postgres"]
    assert _LAZY_DRIVERS["postgresql"] == _LAZY_DRIVERS["postgres"]
    assert _LAZY_DRIVERS["sqlserver"] == _LAZY_DRIVERS["mssql"]


def test_an_unknown_scheme_is_not_resolvable():
    # It must be refused, never fall through to SQLite (the footgun #280's PHP
    # sibling and Ruby's old detect_driver both warn about).
    assert "bogus" not in known_drivers()
    assert "postgre" not in known_drivers()  # a near-miss typo is still unknown
