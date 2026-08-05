"""SESSION CONTRACT: TINA4_SESSION_TTL is honoured by EVERY backend.

ADR-0024: swapping file for redis, valkey, mongodb, memcached or database
changes ONE env var and NOTHING ELSE. The configured session lifetime is part of
that contract. An operator who sets a 15-minute session must GET a 15-minute
session, whichever backend is selected.

WHY THIS FILE EXISTS. Measured 2026-08-04 across all four frameworks: Ruby read
TINA4_SESSION_TTL in exactly ONE handler (memcached) and hard-coded 86400 in the
other five, so a 15-minute session really lived 24 hours on five of six
backends. Python is the reference implementation and already honours the
variable; this file is the PARITY LOCK-IN that keeps it that way, and it is the
same four cases with the same names in all four frameworks.

A session that does not expire when told is an AUTH outcome, not a storage one,
which is why this is held to a security bar.

NO MOCKS. Every backend here is the real service (real Redis, real Valkey, real
memcached, real MongoDB, a real SQLite file, real files on disk) and every
expiry is real wall-clock time - no clock patching, no freezegun, no doubles. A
skip is a FAILURE under TINA4_REQUIRE_SERVICES.

THE FOUR CASES, and why each is load-bearing:
  1. positive     - a short TINA4_SESSION_TTL really expires the record.
  2. negative     - a long TINA4_SESSION_TTL really does NOT expire it. Without
                    this, deleting all expiry logic passes case 1 and ships.
  3. out-of-band  - the stored deadline is read back with an INDEPENDENT client.
                    Cases 1 and 2 both ask the code under test whether a record
                    is alive; this one asks the SERVER.
  4. Session-level - the public Session forwards its OWN ttl to the store, not
                    just into the cookie. Cases 1-3 drive handlers directly, so
                    without this the forwarding is an inert mutation.
"""
import json
import os
import socket
import time
import uuid

import pytest

from tina4_python.database import Database
from tina4_python.session import DatabaseSessionHandler, FileSessionHandler, Session

REDIS_HOST = os.environ.get("TINA4_SESSION_REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.environ.get("TINA4_SESSION_REDIS_PORT", "6379"))
VALKEY_HOST = os.environ.get("TINA4_SESSION_VALKEY_HOST", "127.0.0.1")
VALKEY_PORT = int(os.environ.get("TINA4_SESSION_VALKEY_PORT", "6380"))
MEMCACHED_HOST = os.environ.get("TINA4_TEST_MEMCACHED_HOST", "127.0.0.1")
MEMCACHED_PORT = int(os.environ.get("TINA4_TEST_MEMCACHED_PORT", "11211"))
MONGO_HOST = os.environ.get("TINA4_TEST_MONGO_HOST", "127.0.0.1")
MONGO_PORT = int(os.environ.get("TINA4_TEST_MONGO_PORT", "27017"))

# The real sleep every timing case shares. Longer than the 2s ttl under test and
# short enough that four cases stay cheap.
REAL_SLEEP = 4
SHORT_TTL = 2


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def _require_all() -> None:
    """Every backend must be REAL. A skip is a failure when services are required."""
    down = [
        f"{name} is not reachable at {host}:{port}"
        for name, host, port in (
            ("redis", REDIS_HOST, REDIS_PORT),
            ("valkey", VALKEY_HOST, VALKEY_PORT),
            ("memcached", MEMCACHED_HOST, MEMCACHED_PORT),
            ("mongodb", MONGO_HOST, MONGO_PORT),
        )
        if not _reachable(host, port)
    ]
    if not down:
        return
    message = "; ".join(down)
    if os.environ.get("TINA4_REQUIRE_SERVICES"):
        pytest.fail(f"TINA4_REQUIRE_SERVICES is set but {message}")
    pytest.skip(message)


BACKENDS = ("file", "database", "redis", "valkey", "mongodb", "memcached")


def _build(backend: str, tmp_path, db_path):
    """Build each handler the way Session._resolve_handler builds it.

    Valkey is pointed at its own host/port explicitly: the handler defaults to
    Redis's 6379 AND shares the "tina4:session:" key prefix, so without this the
    valkey rows would land in Redis and the two backends would be
    indistinguishable.
    """
    if backend == "file":
        return FileSessionHandler(str(tmp_path))
    if backend == "database":
        return DatabaseSessionHandler(Database(f"sqlite://{db_path}"))
    if backend == "redis":
        from tina4_python.session_handlers import RedisSessionHandler
        return RedisSessionHandler(host=REDIS_HOST, port=REDIS_PORT)
    if backend == "valkey":
        from tina4_python.session_handlers import ValkeySessionHandler
        return ValkeySessionHandler(host=VALKEY_HOST, port=VALKEY_PORT)
    if backend == "mongodb":
        from tina4_python.session_handlers import MongoDBSessionHandler
        return MongoDBSessionHandler(host=MONGO_HOST, port=MONGO_PORT)
    if backend == "memcached":
        from tina4_python.session_handlers import MemcachedSessionHandler
        return MemcachedSessionHandler(host=MEMCACHED_HOST, port=MEMCACHED_PORT)
    raise AssertionError(f"unknown backend {backend}")


def _stored(value) -> bool:
    """A record is ABSENT when the handler returns None OR an empty mapping.

    The handlers disagree about which they use for a miss, and {} is falsy in
    Python but a bare truthiness check would still be ambiguous to a reader, so
    the rule is written once, here.
    """
    return value is not None and value != {}


@pytest.fixture(autouse=True)
def _real_env():
    """Set and restore REAL environment variables - never a monkeypatched ENV.

    A partial double on os.environ intercepts one read path and leaves
    os.environ.get, os.getenv and anything memoised at import time seeing the
    unstubbed environment, so a gate can test green while the real gate is open.
    """
    watched = (
        "TINA4_SESSION_TTL",
        "TINA4_SESSION_VALKEY_HOST",
        "TINA4_SESSION_VALKEY_PORT",
    )
    saved = {key: os.environ.get(key) for key in watched}
    os.environ["TINA4_SESSION_VALKEY_HOST"] = VALKEY_HOST
    os.environ["TINA4_SESSION_VALKEY_PORT"] = str(VALKEY_PORT)
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _write_all(tmp_path, db_path, tag):
    """Write one record per backend with NO explicit ttl, and return the ids.

    No explicit ttl on purpose: the handler's own default is what must come from
    TINA4_SESSION_TTL. Passing a ttl here would test the argument, which already
    works, instead of the environment variable, which is the invariant.
    """
    ids = {}
    for backend in BACKENDS:
        handler = _build(backend, tmp_path, db_path)
        session_id = f"{tag}-{backend}-{uuid.uuid4().hex[:8]}"
        handler.write(session_id, {"seeded": True})
        assert _stored(handler.read(session_id)), f"{backend}: the record was never stored"
        ids[backend] = session_id
    return ids


def test_session_ttl_env_var_expires_the_record_on_every_backend(tmp_path):
    """A short TINA4_SESSION_TTL really expires the record, on every backend."""
    _require_all()
    os.environ["TINA4_SESSION_TTL"] = str(SHORT_TTL)
    db_path = tmp_path / "ttl_contract.db"

    ids = _write_all(tmp_path, db_path, "ttlshort")

    # ONE shared REAL sleep for all six backends: cheaper than six, and it cannot
    # accidentally give one backend more grace than another.
    time.sleep(REAL_SLEEP)

    survived = [
        backend
        for backend, session_id in ids.items()
        if _stored(_build(backend, tmp_path, db_path).read(session_id))
    ]
    assert not survived, (
        f"TINA4_SESSION_TTL={SHORT_TTL} was ignored by: {', '.join(survived)} "
        f"(the record survived {REAL_SLEEP} real seconds)"
    )


def test_session_ttl_env_var_keeps_a_long_lived_record_on_every_backend(tmp_path):
    """NEGATIVE CONTROL: a long TINA4_SESSION_TTL must NOT expire the record.

    Without this, "delete all the expiry logic" passes the positive case and
    ships a session store that throws every session away.
    """
    _require_all()
    os.environ["TINA4_SESSION_TTL"] = "3600"
    db_path = tmp_path / "ttl_contract.db"

    ids = _write_all(tmp_path, db_path, "ttllong")

    time.sleep(REAL_SLEEP)  # the SAME real sleep that reaped everything above

    died = [
        backend
        for backend, session_id in ids.items()
        if not _stored(_build(backend, tmp_path, db_path).read(session_id))
    ]
    assert not died, f"TINA4_SESSION_TTL=3600 still expired the record on: {', '.join(died)}"


def test_session_ttl_env_var_reaches_the_stored_deadline_out_of_band(tmp_path):
    """The stored deadline is now+TTL, read back by a client we do not own.

    memcached is absent by design: its text protocol exposes no per-key TTL to
    read back, so it is proven behaviourally by the two timing cases instead of
    being asserted through the very code under test.
    """
    _require_all()
    configured = 1800
    os.environ["TINA4_SESSION_TTL"] = str(configured)
    db_path = tmp_path / "ttl_contract.db"
    now = time.time()
    observed = {}

    # file - read the JSON straight off disk
    file_id = f"ttloob-file-{uuid.uuid4().hex[:8]}"
    _build("file", tmp_path, db_path).write(file_id, {"seeded": True})
    stored = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    observed["file"] = stored["_expires"] - now

    # database - raw SQL on a SEPARATE connection
    db_id = f"ttloob-db-{uuid.uuid4().hex[:8]}"
    _build("database", tmp_path, db_path).write(db_id, {"seeded": True})
    probe = Database(f"sqlite://{db_path}")
    row = probe.fetch_one("SELECT expires_at FROM tina4_session WHERE session_id = ?", [db_id])
    assert row, "database: no row was written"
    observed["database"] = float(row["expires_at"]) - now

    # redis / valkey - ask the SERVER for the key's own remaining TTL, over a
    # socket this test opens itself.
    for name, host, port, db_env in (
        ("redis", REDIS_HOST, REDIS_PORT, "TINA4_SESSION_REDIS_DB"),
        ("valkey", VALKEY_HOST, VALKEY_PORT, "TINA4_SESSION_VALKEY_DB"),
    ):
        session_id = f"ttloob-{name}-{uuid.uuid4().hex[:8]}"
        _build(name, tmp_path, db_path).write(session_id, {"seeded": True})
        # Read from the SAME db number the handler used, not a hardcoded 0.
        db_num = int(os.environ.get(db_env, "0") or 0)
        observed[name] = _raw_redis_ttl(host, port, f"tina4:session:{session_id}", db_num)

    # mongodb - read the document's own absolute deadline with an independent client
    mongo_id = f"ttloob-mongo-{uuid.uuid4().hex[:8]}"
    _build("mongodb", tmp_path, db_path).write(mongo_id, {"seeded": True})
    observed["mongodb"] = _raw_mongo_expires_at(mongo_id) - now

    wrong = {b: d for b, d in observed.items() if abs(d - configured) >= 60}
    assert not wrong, (
        f"the stored deadline did not come from TINA4_SESSION_TTL={configured}: "
        + ", ".join(f"{b} stored now+{d:.0f}s" for b, d in wrong.items())
    )


def _raw_redis_ttl(host: str, port: int, key: str, db: int = 0) -> float:
    """Issue a real TTL command over our own socket - not the handler's.

    SELECT the SAME database the handler wrote to. A fresh Redis connection is
    always DB 0, so without this the probe looked in DB 0 while the handler had
    written to whatever TINA4_SESSION_REDIS_DB says. Redis answers TTL on a
    missing key with -2, and the assertion then read "the stored deadline did
    not come from TINA4_SESSION_TTL" - a config-mismatch reported as a TTL bug.
    MEASURED when the four suites began running side by side, each on its own
    redis DB number: this failed in three frameworks at once and looked like a
    real framework defect.

    The sibling _raw_mongo_expires_at already honours TINA4_SESSION_MONGO_DB;
    this one simply never got the same treatment.
    """
    with socket.create_connection((host, port), timeout=3) as sock:
        if db:
            dbs = str(db)
            sock.sendall(f"*2\r\n$6\r\nSELECT\r\n${len(dbs)}\r\n{dbs}\r\n".encode())
            selected = sock.recv(128).decode()
            assert selected.startswith("+OK"), f"SELECT {db} refused: {selected!r}"
        payload = f"*2\r\n$3\r\nTTL\r\n${len(key)}\r\n{key}\r\n".encode()
        sock.sendall(payload)
        reply = sock.recv(128).decode()
    assert reply.startswith(":"), f"unexpected TTL reply for {key}: {reply!r}"
    ttl = float(reply[1:].strip())
    assert ttl != -2, (
        f"{key} does not exist in redis db {db} - the probe and the handler "
        "disagree about where the session was written"
    )
    return ttl


def _raw_mongo_expires_at(session_id: str) -> float:
    """Read expires_at with an independent pymongo client."""
    import pymongo

    client = pymongo.MongoClient(f"mongodb://{MONGO_HOST}:{MONGO_PORT}")
    try:
        database = os.environ.get("TINA4_SESSION_MONGO_DB", "tina4")
        collection = os.environ.get("TINA4_SESSION_MONGO_COLLECTION", "sessions")
        doc = client[database][collection].find_one({"_id": session_id})
        assert doc is not None, "mongodb: no document was written"
        return float(doc.get("expires_at", 0))
    finally:
        client.close()


def test_session_ttl_option_on_the_session_reaches_the_stored_record(tmp_path):
    """The PUBLIC Session forwards its OWN ttl to the store, not just the cookie.

    The other three cases drive the handlers directly, so they gate handler
    defaults and nothing else. This is the case that catches a save() which
    drops the ttl on the way to the backend - the exact defect measured in Ruby,
    where the cookie carried Max-Age and the stored record did not.
    """
    # The environment says one hour. The Session says two seconds. The Session
    # must win, IN THE STORE, not only in the cookie.
    os.environ["TINA4_SESSION_TTL"] = "3600"

    session = Session(handler=FileSessionHandler(str(tmp_path)), ttl=SHORT_TTL)
    session_id = session.start()
    session.set("seeded", True)
    assert session.save() is True

    immediate = Session(handler=FileSessionHandler(str(tmp_path)), ttl=SHORT_TTL)
    immediate.start(session_id)
    assert immediate.get("seeded") is True, "the session was never stored"

    time.sleep(REAL_SLEEP)  # REAL wall clock, past the Session's own 2s ttl

    resumed = Session(handler=FileSessionHandler(str(tmp_path)), ttl=SHORT_TTL)
    resumed.start(session_id)
    assert resumed.get("seeded") is None, (
        "Session(ttl=2) never reached the store - the record outlived its own ttl "
        "because save() dropped it"
    )
