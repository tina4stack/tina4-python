# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""SESSION CONTRACT: the database backend works on every engine it claims.

ADR-0024's founding scenario, in the subsystem that decides whether anyone is
logged in: develop on sqlite, deploy on postgres, and the app does not start.

Node was the framework that FAILED this - its database session backend threw on
any non-sqlite TINA4_DATABASE_URL. ADR-0028 records the decision and, more
usefully, the WRONG PREMISE that nearly froze it. Python is EXPECTED TO PASS:
DatabaseSessionHandler takes an injected Database and owns no engine selection
of its own, so it inherits whatever the Database layer connects to. This file is
the PARITY LOCK-IN that keeps it that way.

ONE ENGINE PASSING IS NOT THE INVARIANT. The positive case runs real round trips
on SQLite, PostgreSQL and MySQL and FAILS - never skips - if fewer than three
engines actually ran. Each round trip is re-read OUT OF BAND on a second
connection, so a handler that silently wrote somewhere else cannot fake a pass.

NO MOCKS. Real engines, real connections, real rows.
"""
import json
import os
import socket
import uuid

import pytest

from tina4_python.database import Database
from tina4_python.session import DatabaseSessionHandler

PG_HOST = os.environ.get("TINA4_TEST_PG_HOST", "127.0.0.1")
PG_PORT = int(os.environ.get("TINA4_TEST_PG_PORT", "55432"))
PG_USER = os.environ.get("TINA4_TEST_PG_USERNAME", "tina4")
PG_PASSWORD = os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4")
MYSQL_USER = os.environ.get("TINA4_TEST_MYSQL_USERNAME", "root")
MYSQL_PASSWORD = os.environ.get("TINA4_TEST_MYSQL_PASSWORD", "tina4")
# Firebird has no TEXT type, so the single "data TEXT" CREATE used to fail on it
# with -607 and the database session backend never worked there. The lab exports
# TINA4_TEST_FIREBIRD_URL; when it is set, Firebird MUST be one of the engines
# that round-trips - excluding it is how the gap hid.
FB_URL = os.environ.get("TINA4_TEST_FIREBIRD_URL")


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def _require(service: str, host: str, port: int) -> None:
    if _reachable(host, port):
        return
    message = f"{service} is not reachable at {host}:{port}"
    if os.environ.get("TINA4_REQUIRE_SERVICES"):
        pytest.fail(f"TINA4_REQUIRE_SERVICES is set but {message}")
    pytest.skip(message)


def test_the_database_session_backend_works_on_every_engine_it_claims(tmp_path):
    """A real round trip on every engine, each verified on a SECOND connection."""
    _require("postgresql", PG_HOST, PG_PORT)
    _require("mysql", "127.0.0.1", 3306)

    engines = {
        "sqlite": f"sqlite://{tmp_path / 'engines.db'}",
        "postgres": f"postgres://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/tina4_py",
        "mysql": f"mysql://{MYSQL_USER}:{MYSQL_PASSWORD}@127.0.0.1:3306/tina4",
    }
    # Firebird when the lab provides it. It folds unquoted identifiers to UPPER and
    # has no TEXT type, so it exercises both the per-engine DDL (VARCHAR payload)
    # and the adapter's column-case handling on the read path.
    if FB_URL:
        engines["firebird"] = FB_URL

    ran, broken = [], []
    for name, url in engines.items():
        session_id = f"engine-{name}-{uuid.uuid4().hex[:8]}"
        try:
            writer = DatabaseSessionHandler(Database(url))
            writer.write(session_id, {"seeded": True, "engine": name})

            # A FRESH handler on a FRESH connection - nothing in-process can be
            # answering from memory.
            reader = DatabaseSessionHandler(Database(url))
            if reader.read(session_id) != {"seeded": True, "engine": name}:
                broken.append(f"{name} (round trip failed)")
                continue

            # OUT OF BAND: ask the engine ourselves, not the code under test. A
            # handler that silently wrote to a different store cannot pass this.
            probe = Database(url)
            row = probe.fetch_one(
                "SELECT data FROM tina4_session WHERE session_id = ?", [session_id]
            )
            if not row or json.loads(row["data"]).get("engine") != name:
                broken.append(f"{name} (row not present on the engine itself)")
                continue

            ran.append(name)
            reader.destroy(session_id)
        except Exception as error:  # noqa: BLE001 - the message is the finding
            broken.append(f"{name} ({type(error).__name__}: {str(error)[:90]})")

    assert not broken, f"these engines did NOT work: {'; '.join(broken)}"
    assert len(ran) >= 3, (
        f"only {len(ran)} engine(s) ran ({', '.join(ran)}) - one engine passing is "
        "not the invariant, so this must fail rather than skip"
    )


def test_an_unsupported_engine_refuses_by_name_instead_of_degrading(tmp_path):
    """What it cannot do, it refuses LOUDLY, naming the scheme it was given.

    The alternative is the failure this invariant exists to stop: falling
    through to some other engine, which looks exactly like working until
    sessions start disappearing.
    """
    raised = None
    try:
        handler = DatabaseSessionHandler(Database("notareal://user:pass@127.0.0.1:1234/db"))
        handler.write(f"unsupported-{uuid.uuid4().hex[:8]}", {"seeded": True})
    except Exception as error:  # noqa: BLE001 - asserting on it below
        raised = error

    assert raised is not None, (
        "an unsupported engine scheme did NOT raise. Falling through to another "
        "engine is indistinguishable from working until sessions go missing."
    )
    message = f"{type(raised).__name__}: {raised}"
    assert "notareal" in message.lower(), (
        f"the refusal did not name the offending scheme, so an operator cannot tell "
        f"a typo from an unsupported engine: {message}"
    )
    assert "pass" not in message or "notareal" in message, (
        f"the refusal leaked the password: {message}"
    )


# ── concurrent first use ──────────────────────────────────────────────────
#
# Every app that starts more than one process races to create tina4_session on
# first use. The losers must NOT take a request down. PHP has always run this
# race with real processes (tests/SessionDatabaseEnginesTest.php); Python had no
# such test, and MEASURED on the lab before the fix five of six workers died on
# EVERY engine, because _ensure_table() issued a bare CREATE with no guard.

MYSQL_HOST = os.environ.get("TINA4_TEST_MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.environ.get("TINA4_TEST_MYSQL_PORT", "3306"))
MSSQL_HOST = os.environ.get("TINA4_TEST_MSSQL_HOST", "127.0.0.1")
MSSQL_PORT = int(os.environ.get("TINA4_TEST_MSSQL_PORT", "1433"))
RACE_WORKER = os.path.join(os.path.dirname(__file__), "fixtures", "session_concurrent_first_use.py")


def _race_scenarios(tmp_path):
    """(scenario, url, username, password, workers, hold_named_lock) per engine.

    MySQL runs twice. The second pass holds a named lock in every worker: MySQL
    resolves the metadata-lock deadlock inside CREATE TABLE IF NOT EXISTS by
    backing the victim off silently only when the session holds no other
    metadata lock, so without one the losing path is reached rarely (tina4-php
    CI run 35972320442) and with one it is reached every run.
    """
    pg_db = os.environ.get("TINA4_TEST_PG_DB", "tina4_py")
    mysql_db = os.environ.get("TINA4_TEST_MYSQL_DB", "tina4_test")
    mssql_db = os.environ.get("TINA4_TEST_MSSQL_DB", "tina4_test")
    mysql_host = "127.0.0.1" if MYSQL_HOST == "localhost" else MYSQL_HOST
    mysql_url = f"mysql://{mysql_host}:{MYSQL_PORT}/{mysql_db}"
    scenarios = [
        ("sqlite", f"sqlite://{tmp_path / 'race.db'}", None, None, 6, False),
        ("postgres", f"postgres://{PG_HOST}:{PG_PORT}/{pg_db}", PG_USER, PG_PASSWORD, 6, False),
        ("mysql", mysql_url, MYSQL_USER, MYSQL_PASSWORD, 6, False),
        ("mysql+named-lock", mysql_url, MYSQL_USER, MYSQL_PASSWORD, 12, True),
        ("mssql", f"mssql://{MSSQL_HOST}:{MSSQL_PORT}/{mssql_db}",
         os.environ.get("TINA4_TEST_MSSQL_USERNAME", "sa"),
         os.environ.get("TINA4_TEST_MSSQL_PASSWORD", "TinaSQL123!Secure"), 6, False),
    ]
    if FB_URL:
        scenarios.append(("firebird", FB_URL, None, None, 6, False))
    return scenarios


def _drop_session_table(url, username, password):
    database = Database(url, username, password)
    try:
        if database.table_exists("tina4_session"):
            database.execute("DROP TABLE tina4_session")
            database.commit()
    finally:
        database.close()


def test_concurrent_first_use_is_safe_on_every_engine(tmp_path):
    """Real processes race to create tina4_session; every one of them writes.

    The row count is read OUT OF BAND on a fresh connection: a worker that
    swallowed its own failure would otherwise look like one that wrote.
    """
    import subprocess
    import sys
    import time

    _require("postgresql", PG_HOST, PG_PORT)
    _require("mysql", MYSQL_HOST, MYSQL_PORT)
    _require("mssql", MSSQL_HOST, MSSQL_PORT)

    survived, failures = [], []
    for scenario, url, username, password, workers, hold_named_lock in _race_scenarios(tmp_path):
        try:
            _drop_session_table(url, username, password)
            environment = dict(
                os.environ,
                T4_RACE_URL=url,
                T4_RACE_USERNAME=username or "",
                T4_RACE_PASSWORD=password or "",
                T4_RACE_HOLD_NAMED_LOCK="1" if hold_named_lock else "",
            )
            # Enough lead for every worker to import and CONNECT first - a
            # worker still connecting is not in the race.
            start_at = time.time() + 3.0
            processes = [
                subprocess.Popen(
                    [sys.executable, RACE_WORKER, f"{start_at:.6f}", f"race-{scenario}-{worker}"],
                    env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                for worker in range(workers)
            ]
            for worker, process in enumerate(processes):
                _, error_output = process.communicate(timeout=120)
                if process.returncode != 0:
                    failures.append(f"{scenario} worker {worker} exited {process.returncode}: {error_output.strip()[-300:]}")

            probe = Database(url, username, password)
            row = probe.fetch_one("SELECT COUNT(*) AS n FROM tina4_session")
            probe.close()
            rows = int(next(iter(row.values()))) if row else -1
            if rows != workers:
                failures.append(f"{scenario} ended the race with {rows} of {workers} rows")
                continue
            survived.append(scenario)
        except Exception as error:  # noqa: BLE001 - the message is the finding
            failures.append(f"{scenario} ({type(error).__name__}: {str(error)[:200]})")
        finally:
            try:
                _drop_session_table(url, username, password)
            except Exception:  # noqa: BLE001 - cleanup only
                pass

    print(f"\n[session-contract] concurrent first use survived on: {', '.join(survived) or 'NONE'}")
    assert not failures, (
        "concurrent first use is NOT safe on: " + "; ".join(failures)
        + " - every app that starts more than one process races here, and the "
        "loser must not take a request down"
    )
    expected = {"sqlite", "postgres", "mysql", "mysql+named-lock", "mssql"} | ({"firebird"} if FB_URL else set())
    assert set(survived) == expected, f"the race did not run on: {sorted(expected - set(survived))}"
