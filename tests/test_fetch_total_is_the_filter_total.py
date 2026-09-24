# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""fetch()'s ``count`` is the total for the FILTER, never the length of the page.

Found in tina4-nodejs: on SQL Server and MySQL its COUNT probe lacked the
derived-table alias and kept a trailing ORDER BY (SQL Server error 1033), the
probe failed, and fetch() reported the PAGE length as the total - so every
pager showed one page. Python's probe aliases the derived table and strips a
trailing ORDER BY for SQL Server (``_strip_trailing_order_by``); this file is
the lock-in that proves it on each engine: 25 rows, a filter matching 22, a
10-row page - ``count`` must be 22 with and without a trailing ORDER BY.

NO MOCKS: real SQLite, PostgreSQL, MySQL and SQL Server.
"""
import os
import socket
from urllib.parse import urlparse

import pytest

TABLE = "fetch_total_py_{engine}"
ENGINES = {
    "sqlite": {"url": None, "id": "INTEGER PRIMARY KEY AUTOINCREMENT"},
    "postgres": {"url": os.environ.get("TINA4_TEST_PG_URL"), "port": 5432, "service": "PostgreSQL",
                 "id": "serial PRIMARY KEY"},
    "mysql": {"url": os.environ.get("TINA4_TEST_MYSQL_URL"), "port": 3306, "service": "MySQL",
              "id": "INT AUTO_INCREMENT PRIMARY KEY"},
    "mssql": {"url": os.environ.get("TINA4_TEST_MSSQL_URL"), "port": 1433, "service": "MSSQL",
              "id": "INT IDENTITY(1,1) PRIMARY KEY"},
}


def _reachable(url, port) -> bool:
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or port), timeout=1.0):
            return True
    except OSError:
        return False


@pytest.fixture(params=list(ENGINES))
def table(request, tmp_path):
    from tina4_python.database import Database
    name = request.param
    spec = ENGINES[name]
    url = f"sqlite:///{tmp_path}/fetch_total.db" if name == "sqlite" else spec["url"]
    if not url:
        pytest.skip(f"[needs:{name}] {spec['service']} not configured for the fetch-total test (env var not set)")
    if spec.get("port") and not _reachable(url, spec["port"]):
        pytest.skip(f"[needs:{name}] {spec['service']} not reachable - skip integration test")
    table_name = TABLE.format(engine=name)
    database = Database(url)
    if database.table_exists(table_name):
        database.execute(f"DROP TABLE {table_name}")
    database.execute(f"CREATE TABLE {table_name} (id {spec['id']}, kind VARCHAR(10), rank_no INTEGER)")
    for number in range(1, 26):
        # 22 rows are 'keep', 3 are 'skip' - the filter below matches 22.
        database.execute(
            f"INSERT INTO {table_name} (kind, rank_no) VALUES (?, ?)",
            ["skip" if number in (5, 12, 19) else "keep", number],
        )
    database.commit()
    yield name, database, table_name
    database.execute(f"DROP TABLE {table_name}")
    database.commit()
    database.close()


@pytest.mark.parametrize("order_by", ["", " ORDER BY rank_no DESC"])
def test_fetch_count_is_the_filter_total_not_the_page_length(table, order_by):
    engine, database, table_name = table
    result = database.fetch(
        f"SELECT id, rank_no FROM {table_name} WHERE kind = ?{order_by}", ["keep"], limit=10, offset=0,
        no_cache=True,
    )
    assert len(result.records) == 10, f"{engine}: the page itself is not 10 rows: {len(result.records)}"
    assert result.count == 22, (
        f"{engine}{' with ORDER BY' if order_by else ''}: count={result.count}, expected the "
        "filter total 22 (a page-length count means the COUNT probe failed)"
    )
    if order_by:
        assert [row["rank_no"] for row in result.records][:3] == [25, 24, 23]
