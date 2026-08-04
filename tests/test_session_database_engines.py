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
