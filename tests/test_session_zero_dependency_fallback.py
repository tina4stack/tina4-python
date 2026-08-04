"""SESSION CONTRACT invariant 6: a zero-dependency transport in EVERY framework.

ADR-0024 / session_contract.json #6: "Where three frameworks ship a
zero-dependency transport for a backend, the fourth does too. A backend must not
hard-require a third-party client in one framework and not the others."

WHY THIS MATTERS, stated as the operator sees it: the SAME .env works in three
frameworks and raises in the fourth. Nothing about the configuration hints at
it, there is no warning to read, and the failure lands at Session construction
on the first request. An asymmetric broken promise is worse than a consistent
one, because nobody can plan around it.

RUBY was the framework that FAILED this - its mongodb session handler did
`require "mongo"` and raised "MongoDB session handler requires the 'mongo' gem"
when the gem was absent. It has been closed there with a zero-dependency
MongoWireClient. THIS FILE IS THE PARITY LOCK-IN FOR PYTHON, not a bug fix:
Python has shipped raw-socket transports the whole time, and this pins them so
they can never be quietly replaced by a hard dependency.

MEASURED at this HEAD, in a REAL subprocess with NO third-party package
resolvable at all (see _run_with_no_third_party_packages below), driving
tina4_python.session.Session per backend exactly as a request does:

    file       ok   redis      ok   valkey     ok   memcached  ok
    mongodb    ok   database   ok

    tina4_python/session_handlers/mongodb_handler.py:62   try: import pymongo
    tina4_python/session_handlers/mongodb_handler.py:201  raw OP_MSG wire path
    tina4_python/session_handlers/redis_handler.py:41     try: import redis
    tina4_python/session_handlers/redis_handler.py:117    raw RESP path
    tina4_python/session_handlers/valkey_handler.py:43    try: import redis
    tina4_python/session_handlers/memcached_handler.py    raw text protocol only

HOW THE PACKAGE IS MADE GENUINELY UNAVAILABLE, WITHOUT ANY DOUBLE.

    A REAL subprocess whose sys.path cannot reach site-packages. The child is
    launched with `python -S`, which stops the `site` module from running at
    all, so NEITHER the virtualenv's site-packages NOR the user site directory
    NOR any .pth file is ever added to sys.path. Every PYTHON* variable is
    dropped from the child's environment and PYTHONPATH is then set to the
    repository root alone, so the framework under test is reachable and nothing
    else is.

    Nothing is shimmed, stubbed, monkeypatched or faked. `import pymongo` is the
    REAL import statement, pymongo genuinely does not exist anywhere the process
    can see, and the ImportError is the one CPython really raises. It is not a
    pymongo-shaped hole either: NO third-party package resolves in that process
    at all, which is the strongest possible statement of the zero-dependency
    claim and is why one subprocess can answer for six backends at once.

    Every subprocess SELF-VERIFIES the instrument and reports it: whether
    `import pymongo` really failed, whether `import redis` really failed, how
    many site-packages directories are on sys.path, and which tina4_python was
    actually imported. Each test asserts those FIRST. Without that check a
    subprocess that quietly inherited the venv would pass every assertion below
    while measuring nothing at all - the same trap the counting listener in
    test_session_handler_construction.py guards.

TINA4_SESSION_STRICT=true IS SET IN EVERY SUBPROCESS, and it is load-bearing.
Session._safe_read / _safe_write catch Exception, log, and degrade to an empty
session (ADR-0021). Without strict mode a genuinely dead backend would be
swallowed into a clean-looking {} and case 1 would go green against nothing at
all. Strict mode makes a real failure re-raise, so "it completed" is a fact
rather than a shrug.

WHAT EACH CASE IS FOR, and why three are needed:
  1. the transport EXISTS for every backend and can be constructed and driven
     with no third-party client. On its own this is satisfiable by a transport
     that does nothing, which is exactly why case 2 exists.
  2. the transport really WORKS: a session written through it is really in
     MongoDB, confirmed OUT OF BAND by an independent client (real pymongo, in
     this process, which shares no code with the hand-rolled BSON/OP_MSG path).
  3. NEGATIVE CONTROL: with pymongo present the PYMONGO path is still the one
     taken. Without this, deleting the pymongo path entirely passes 1 and 2.

THE BOUND, STATED RATHER THAN HIDDEN: the `database` backend. Its third-party
client is the SQL driver. Python's runtime ships stdlib `sqlite3`, so unlike
Ruby - which declares `sqlite3` as a runtime gem dependency because Ruby ships
no SQL engine - Python's database session backend really does construct AND
round-trip inside the zero-package subprocess, against a real SQLite file. That
is measured here rather than argued. PostgreSQL/MySQL/MSSQL still need their
drivers, but that is the Database layer's dependency and not something the
session handler carries: DatabaseSessionHandler imports no client of its own.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

MONGO_HOST = os.environ.get("TINA4_TEST_MONGO_HOST", "127.0.0.1")
MONGO_PORT = int(os.environ.get("TINA4_TEST_MONGO_PORT", "27017"))
MONGO_URI = os.environ.get("TINA4_TEST_MONGO_URI", f"mongodb://{MONGO_HOST}:{MONGO_PORT}")
MONGO_DATABASE = "tina4_zero_dependency"

REDIS_HOST = os.environ.get("TINA4_SESSION_REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.environ.get("TINA4_SESSION_REDIS_PORT", "6379"))
VALKEY_HOST = os.environ.get("TINA4_SESSION_VALKEY_HOST", "127.0.0.1")
VALKEY_PORT = int(os.environ.get("TINA4_SESSION_VALKEY_PORT", "6380"))
MEMCACHED_HOST = os.environ.get("TINA4_SESSION_MEMCACHED_HOST", "127.0.0.1")
MEMCACHED_PORT = int(os.environ.get("TINA4_SESSION_MEMCACHED_PORT", "11211"))

REPORT_MARKER = "TINA4_REPORT "


def _unique_collection() -> str:
    """A collection nobody else is using.

    An index or a document left by an earlier run can never make an assertion
    true for the wrong reason.
    """
    return "sessions_" + uuid.uuid4().hex[:16]


# -- The instrument: a real subprocess with nowhere to find a package --------

#: The preamble every subprocess runs: prove the package really is gone, and say
#: so in the report, BEFORE anything is measured.
_INSTRUMENT_SOURCE = '''
import json
import sys


def _package_unavailable(name):
    try:
        __import__(name)
        return False
    except ImportError:
        return True


instrument = {
    "pymongo_gone": _package_unavailable("pymongo"),
    "redis_gone": _package_unavailable("redis"),
    "site_package_paths": len([
        entry for entry in sys.path
        if "site-packages" in entry or "dist-packages" in entry
    ]),
    "executable": sys.executable,
}

import tina4_python

instrument["framework_file"] = tina4_python.__file__
'''


def _run_with_no_third_party_packages(source: str, extra_environment: dict | None = None) -> dict:
    """Run `source` in a REAL python subprocess that cannot resolve ANY
    third-party package, and return the JSON object it reported.

    `-S` stops the `site` module from running, so site-packages, the user site
    directory and every .pth file are all absent from sys.path. Dropping every
    PYTHON* variable and then setting PYTHONPATH to the repository root alone
    means the framework is importable and nothing else is. This is a genuine
    environment change: no import hook is installed, sys.modules is untouched,
    and the ImportError the child sees is the real one.
    """
    with tempfile.TemporaryDirectory(prefix="tina4-no-packages-") as sandbox:
        script = Path(sandbox) / "case.py"
        script.write_text(source, encoding="utf-8")

        environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith("PYTHON")
        }
        environment.update({
            "PYTHONPATH": str(REPOSITORY_ROOT),
            "PYTHONNOUSERSITE": "1",
            # No .pyc anywhere: a stale bytecode file has faked a negative proof
            # on this project before.
            "PYTHONDONTWRITEBYTECODE": "1",
            # Strict mode is what stops a dead backend degrading into a green {}.
            "TINA4_SESSION_STRICT": "true",
            "TINA4_DEBUG": "false",
        })
        environment.update(extra_environment or {})

        completed = subprocess.run(
            [sys.executable, "-S", str(script)],
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
        )
        return _parse_subprocess_report(completed)


def _parse_subprocess_report(completed: subprocess.CompletedProcess) -> dict:
    """The subprocess reports exactly one marked line, so ordinary framework
    logging on stdout cannot be mistaken for the result."""
    for line in completed.stdout.splitlines():
        if line.startswith(REPORT_MARKER):
            return json.loads(line[len(REPORT_MARKER):])
    raise AssertionError(
        "the zero-package subprocess reported nothing.\n"
        f"exit status: {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )


def _assert_packages_really_unavailable(report: dict) -> None:
    """Assert the subprocess really had no third-party packages.

    Every test calls this first: the whole file's meaning depends on it.
    """
    instrument = report["instrument"]
    assert instrument["pymongo_gone"] is True, (
        "the subprocess could still import pymongo, so it measured the PYMONGO "
        "path while claiming to measure the zero-dependency one. Every "
        "assertion in this test would be vacuous."
    )
    assert instrument["redis_gone"] is True, (
        "the subprocess could still import redis, so its environment is not the "
        "package-free one this file claims to run in."
    )
    assert instrument["site_package_paths"] == 0, (
        f"the subprocess had {instrument['site_package_paths']} site-packages "
        "directories on sys.path - the site module ran after all, so no "
        "third-party client was actually unavailable."
    )
    assert instrument["framework_file"].startswith(str(REPOSITORY_ROOT)), (
        "the subprocess imported tina4_python from "
        f"{instrument['framework_file']}, which is not the working tree at "
        f"{REPOSITORY_ROOT}. It measured some other copy of the framework."
    )


def _reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _require_service(name: str, host: str, port: int) -> None:
    """TINA4_REQUIRE_SERVICES turns these skips into a hard FAILURE (conftest),
    which is exactly right on any machine that provisions the services. The
    messages carry the gate's own keywords on purpose."""
    if _reachable(host, port):
        return
    message = f"{name} not reachable at {host}:{port}"
    if os.environ.get("TINA4_REQUIRE_SERVICES"):
        pytest.fail(f"TINA4_REQUIRE_SERVICES is set but {message}")
    pytest.skip(message)


def _require_mongo() -> None:
    _require_service("mongo", MONGO_HOST, MONGO_PORT)


def _require_every_service() -> None:
    _require_mongo()
    _require_service("redis", REDIS_HOST, REDIS_PORT)
    _require_service("valkey", VALKEY_HOST, VALKEY_PORT)
    _require_service("memcached", MEMCACHED_HOST, MEMCACHED_PORT)


def _service_environment(session_directory: Path, database_path: Path, collection: str) -> dict:
    """Every backend pointed at a real service, for the child process."""
    return {
        "TINA4_SESSION_PATH": str(session_directory),
        "TINA4_SESSION_REDIS_HOST": REDIS_HOST,
        "TINA4_SESSION_REDIS_PORT": str(REDIS_PORT),
        "TINA4_SESSION_VALKEY_HOST": VALKEY_HOST,
        "TINA4_SESSION_VALKEY_PORT": str(VALKEY_PORT),
        "TINA4_SESSION_MEMCACHED_HOST": MEMCACHED_HOST,
        "TINA4_SESSION_MEMCACHED_PORT": str(MEMCACHED_PORT),
        "TINA4_SESSION_MONGO_URI": MONGO_URI,
        "TINA4_SESSION_MONGO_DB": MONGO_DATABASE,
        "TINA4_SESSION_MONGO_COLLECTION": collection,
        # Four slashes is the absolute form; stdlib sqlite3 needs no driver.
        "TINA4_DATABASE_URL": "sqlite:///" + str(database_path),
    }


def _independent_mongo_client():
    """An INDEPENDENT client, sharing no code with the transport under test.

    Real pymongo, used only to observe MongoDB from outside - never to drive the
    framework. It is the only observer a stub cannot satisfy by lying
    consistently, because it does not run any of the code under test.
    """
    import pymongo

    return pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)


def _drop_collection(collection: str) -> None:
    try:
        client = _independent_mongo_client()
        try:
            client[MONGO_DATABASE][collection].drop()
        finally:
            client.close()
    except Exception:  # noqa: BLE001 - cleanup must never mask the real result
        pass


# -- 1. EVERY BACKEND HAS A ZERO-DEPENDENCY TRANSPORT ------------------------

_EVERY_BACKEND_SOURCE = _INSTRUMENT_SOURCE + '''
import os
import traceback

from tina4_python.session import Session

backends = {}

# Driven through Session(), NOT through a directly-constructed handler, because
# Session._resolve_handler is the code a REQUEST runs. A fallback that is correct
# on the object and bypassed on the request path is the failure mode this file
# exists to catch.
for name in ("file", "redis", "valkey", "mongodb", "memcached", "database"):
    os.environ["TINA4_SESSION_BACKEND"] = name
    outcome = {"ok": False}
    try:
        writer = Session()
        handler = writer._handler
        outcome["handler"] = type(handler).__name__
        outcome["third_party_client_in_use"] = bool(
            getattr(handler, "_use_pymongo", False)
            or getattr(handler, "_use_redis_pkg", False)
        )
        session_id = writer.start()
        writer.set("backend", name)
        outcome["saved"] = writer.save()

        reader = Session()          # a FRESH Session, therefore a FRESH handler
        reader.start(session_id)

        # gc too, so the sweep really goes over the zero-dependency wire rather
        # than shipping as the one operation nothing ever runs. It deletes only
        # records whose deadline has already passed, so the session just written
        # is never a candidate.
        writer.gc()
        outcome["ok"] = True
    except BaseException as error:
        outcome["error"] = type(error).__name__ + ": " + str(error)
        outcome["traceback"] = traceback.format_exc()
    backends[name] = outcome

print("TINA4_REPORT " + json.dumps({"instrument": instrument, "backends": backends}))
'''


def test_every_backend_has_a_zero_dependency_transport(tmp_path):
    """Every session backend constructs AND drives with no third-party client.

    Six backends, one subprocess, zero packages. The database backend is
    included rather than excused: Python ships stdlib sqlite3, so it really does
    round-trip in there against a real file.
    """
    _require_every_service()

    session_directory = tmp_path / "sessions"
    session_directory.mkdir()
    database_path = tmp_path / "zero_dependency_sessions.db"
    collection = _unique_collection()

    try:
        report = _run_with_no_third_party_packages(
            _EVERY_BACKEND_SOURCE,
            _service_environment(session_directory, database_path, collection),
        )
        _assert_packages_really_unavailable(report)

        failures = {
            name: outcome for name, outcome in report["backends"].items()
            if not outcome["ok"]
        }
        assert not failures, (
            "with NO third-party client available, these session backends could "
            "not be constructed and used at all: "
            + "; ".join(
                f"{name} ({outcome.get('error')})" for name, outcome in failures.items()
            )
            + ". Three frameworks ship a zero-dependency transport for every one "
            "of these; the fourth must too, or the same .env works in three and "
            "raises in one.\n\n"
            + "\n\n".join(
                outcome.get("traceback", "") for outcome in failures.values()
            )
        )

        delegated = {
            name: outcome["handler"] for name, outcome in report["backends"].items()
            if outcome.get("third_party_client_in_use")
        }
        assert not delegated, (
            f"in a process with NO packages at all, {delegated} still reported a "
            "third-party client in use. The zero-dependency transport is not the "
            "one the request path actually took, so this test measured the wrong "
            "path while reporting a green."
        )

        # The database backend really wrote to a real SQLite file, through stdlib
        # sqlite3, inside the zero-package subprocess. If the handler had carried
        # a client requirement of its own, no file would exist.
        assert database_path.exists() and database_path.stat().st_size > 0, (
            "the database session backend reported success but wrote no SQLite "
            f"file at {database_path} - nothing was actually stored."
        )
    finally:
        _drop_collection(collection)


# -- 2. THE ZERO-DEPENDENCY TRANSPORT REALLY WORKS ---------------------------
#
# Case 1 is satisfiable by a transport that accepts every call and does nothing.
# This is the case that is not. It writes through the wire protocol, reads back
# through a FRESH handler, and then asks MongoDB itself - through an independent
# client that shares no code with the transport under test - whether the
# document is really there.

_ROUND_TRIP_SOURCE = _INSTRUMENT_SOURCE + '''
import os
import traceback

from tina4_python.session import Session

os.environ["TINA4_SESSION_BACKEND"] = "mongodb"
payload = json.loads(os.environ["TINA4_ZERO_DEPENDENCY_PAYLOAD"])

result = {"ok": False}
try:
    writer = Session()
    handler = writer._handler
    result["handler"] = type(handler).__name__
    result["use_pymongo"] = bool(getattr(handler, "_use_pymongo", False))

    session_id = writer.start()
    for key, value in payload.items():
        writer.set(key, value)
    result["session_id"] = session_id
    result["saved"] = writer.save()

    # A FRESH Session, therefore a FRESH handler and a FRESH socket. A transport
    # that only remembers what it was just handed cannot pass this; the value has
    # to come back off the wire. Session.start() adopts an id ONLY when the store
    # really answers with that session, so a resumed id that matches is itself a
    # statement about the wire.
    reader = Session()
    result["resumed_session_id"] = reader.start(session_id)
    result["read"] = reader.all()
    result["raw_socket_open"] = handler._socket is not None
    result["ok"] = True
except BaseException as error:
    result["error"] = type(error).__name__ + ": " + str(error)
    result["traceback"] = traceback.format_exc()

print("TINA4_REPORT " + json.dumps({"instrument": instrument, "result": result}))
'''


def test_the_zero_dependency_transport_really_round_trips(tmp_path):
    """A session written with pymongo unavailable is REALLY in MongoDB."""
    _require_mongo()

    collection = _unique_collection()
    payload = {
        "user": "andre",
        "roles": ["admin", "editor"],
        "visits": 42,
        "score": 9.5,
        "verified": True,
        "note": 'unicode: éèê and a quote " inside',
    }

    session_directory = tmp_path / "sessions"
    session_directory.mkdir()
    database_path = tmp_path / "unused.db"

    try:
        environment = _service_environment(session_directory, database_path, collection)
        environment["TINA4_ZERO_DEPENDENCY_PAYLOAD"] = json.dumps(payload)
        report = _run_with_no_third_party_packages(_ROUND_TRIP_SOURCE, environment)
        _assert_packages_really_unavailable(report)

        result = report["result"]
        assert result["ok"] is True, (
            "the zero-dependency MongoDB transport failed outright: "
            f"{result.get('error')}\n\n{result.get('traceback', '')}"
        )
        assert result["use_pymongo"] is False, (
            "the session did not resolve to the zero-dependency transport at all "
            "(pymongo reported in use inside a process with no packages), so this "
            "test proved nothing about it"
        )
        assert result["raw_socket_open"] is True, (
            "the raw transport never opened a TCP socket, so whatever answered "
            "the read did not come off the MongoDB wire"
        )
        assert result["resumed_session_id"] == result["session_id"], (
            "a FRESH Session did not resume the id that was written. "
            "Session.start() adopts an id only when the store really returns that "
            "session, so this is a transport that accepted a write and answered "
            "the read with nothing."
        )
        assert result["read"] == payload, (
            "a session written through the zero-dependency MongoDB transport did "
            f"not read back through a FRESH handler. Got {result['read']!r}. A "
            "transport that accepts writes and answers reads with nothing looks "
            "identical to a working one until this assertion runs."
        )

        # OUT OF BAND. The framework is no longer involved: this is real pymongo
        # asking the real server what is actually stored. It is the only
        # assertion here that a stub cannot satisfy by lying consistently.
        client = _independent_mongo_client()
        try:
            document = client[MONGO_DATABASE][collection].find_one(
                {"_id": result["session_id"]}
            )
            assert document is not None, (
                "an INDEPENDENT MongoDB client cannot find "
                f"_id={result['session_id']} in {MONGO_DATABASE}.{collection}. "
                "The framework reported a successful round trip, so the "
                "zero-dependency transport is not talking to MongoDB at all."
            )
            assert document["data"] == payload, (
                "the document really in MongoDB does not carry the payload that "
                f"was written: {document['data']!r}"
            )
            assert float(document["expires_at"]) > time.time(), (
                "the stored absolute deadline is not in the future, so the wire "
                "transport wrote a record that is already expired"
            )
        finally:
            client.close()
    finally:
        _drop_collection(collection)


# -- 3. NEGATIVE CONTROL: PYMONGO IS STILL PREFERRED -------------------------
#
# Without this, "delete the pymongo path entirely" passes cases 1 and 2. The
# zero-dependency transport is a FALLBACK: where the real driver is installed it
# stays in charge, with its connection pool, its topology monitoring and its
# server selection.


def _connections_tagged(app_name: str) -> int:
    """Connections this MongoDB server sees carrying `app_name`.

    An appName is sent in the driver's HANDSHAKE. The zero-dependency transport
    performs no handshake at all - it opens a socket and sends OP_MSG commands -
    so a connection tagged with our appName can ONLY have been opened by
    pymongo. That is an observation made by the SERVER, not an assertion about
    code shape, and it is the Python equivalent of Ruby's TTL-index evidence.
    """
    client = _independent_mongo_client()
    try:
        counted = client.admin.aggregate([
            {"$currentOp": {"allUsers": True, "idleConnections": True, "localOps": True}},
            {"$match": {"appName": app_name}},
            {"$count": "n"},
        ])
        return next(iter(counted), {"n": 0})["n"]
    finally:
        client.close()


def test_the_third_party_client_is_still_used_when_present(monkeypatch):
    """With pymongo installed, the PYMONGO path is the one a request takes."""
    _require_mongo()

    # Guard the premise. If pymongo is missing here the test must say so, not
    # quietly assert that the fallback was used and call that a pass.
    try:
        import pymongo
    except ImportError:
        message = "pymongo not installed, so the pymongo path cannot be the one under test"
        if os.environ.get("TINA4_REQUIRE_SERVICES"):
            pytest.fail(f"TINA4_REQUIRE_SERVICES is set but {message}")
        pytest.skip(message)

    from tina4_python.session import Session
    from tina4_python.session_handlers import MongoDBSessionHandler

    collection = _unique_collection()
    app_name = "tina4_zero_dep_negative_" + uuid.uuid4().hex[:10]
    tagged_uri = MONGO_URI + ("&" if "?" in MONGO_URI else "/?") + "appName=" + app_name
    session_id = "pymongo-path-" + uuid.uuid4().hex
    payload = {"user": "andre", "path": "pymongo"}

    handler = None
    request_handler = None
    try:
        handler = MongoDBSessionHandler(
            url=tagged_uri,
            database=MONGO_DATABASE,
            collection=collection,
            ttl=300,
        )
        assert handler._use_pymongo is True, (
            "pymongo is installed and the handler still selected the "
            "zero-dependency transport. The fallback has REPLACED the working "
            "path instead of backing it up: no connection pool, no topology "
            "monitoring, no server selection."
        )

        handler.write(session_id, payload, 300)
        assert handler.read(session_id) == payload, (
            "the pymongo path no longer round-trips a session"
        )

        assert isinstance(handler._collection, pymongo.collection.Collection), (
            "the transport the read/write path used is "
            f"{type(handler._collection)!r}, not a pymongo Collection"
        )
        assert handler._socket is None, (
            "the raw transport opened a TCP socket of its own while pymongo is "
            "installed - both paths ran, or the wrong one did"
        )

        # OUT OF BAND, and the assertion a code-shape check cannot make: the
        # SERVER reports connections carrying this run's appName. Only a driver
        # handshake sends one, and the appName is unique per run, so a leftover
        # from an earlier run cannot make it true.
        assert _connections_tagged(app_name) > 0, (
            "MongoDB reports no connection tagged with this run's appName "
            f"({app_name}). An appName travels in the driver handshake, which "
            "the zero-dependency transport never performs - so the real driver "
            "is installed and was not the path taken."
        )

        # The SAME resolution on the REQUEST path. A handler built directly by a
        # test is not proof about the path a request takes; Session._resolve_handler
        # is that path, and it is where a wrong default would actually bite.
        monkeypatch.setenv("TINA4_SESSION_BACKEND", "mongodb")
        monkeypatch.setenv("TINA4_SESSION_MONGO_URI", tagged_uri)
        monkeypatch.setenv("TINA4_SESSION_MONGO_DB", MONGO_DATABASE)
        monkeypatch.setenv("TINA4_SESSION_MONGO_COLLECTION", collection)
        request_handler = Session()._handler
        assert isinstance(request_handler, MongoDBSessionHandler), (
            f"the request path resolved to {type(request_handler)!r}, not the "
            "MongoDB handler"
        )
        assert request_handler._use_pymongo is True, (
            "the REQUEST path resolved to the zero-dependency transport while "
            "pymongo is installed. A policy that is right on a directly-"
            "constructed handler and wrong on the path a request takes is not a "
            "policy at all."
        )
    finally:
        # A pymongo MongoClient owns a REAL connection pool. Close every client
        # this test opened, or the connection-count gate in
        # test_docstore_substitutability.py starts failing for reasons that have
        # nothing to do with the doc store.
        for owned in (handler, request_handler):
            if owned is None:
                continue
            try:
                owned.close()
            except Exception:  # noqa: BLE001 - cleanup must never mask the result
                pass
        _drop_collection(collection)
