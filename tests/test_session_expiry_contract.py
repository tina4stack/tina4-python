"""Session expiry contract - regression gates for the session-backend defect batch (2026-08-01).

THE CONTRACT, settled against real mainstream implementations rather than internal
precedent. PHP's own native files handler, express-session 1.19.0, Django 6.0.7
(file and db), Laravel illuminate/session 13.23.0, connect-redis 10.0.0 and
connect-mongo 6.0.0 were each measured with real runs. ZERO of the seven delete a
record that carries no expiry: six return it, and Django's db backend declines to
load it but still keeps it. connect-mongo whitelists the case deliberately with
``$or: [{expires: {$exists: false}}, {expires: {$gt: now}}]``.

    1. An ABSENT or ZERO expiry stamp means "never expires". It is guarded OUT of
       the comparison, never fed INTO it, and the record is returned and kept.
    2. A stamp genuinely PRESENT and in the PAST still expires the record, and the
       record is still reaped. THE DANGEROUS FIX IS THE OBVIOUS ONE - making the
       round-trip pass by weakening expiry turns data loss into a
       sessions-never-expire security bug. Every positive gate below is paired
       with a negative control.
    3. The PERSISTENCE LAYER owns the stamp, never the caller's payload.
    4. The ttl is consumed at WRITE time; nothing at read time needs it.

NO MOCKS. The file gates use a real temp directory, the database gates a real SQL
engine, the mongo gates a real MongoDB. Every "did the record survive?" assertion
is made with an INDEPENDENT client (a directory listing, raw SQL, a separate
pymongo handle) - never through the code under test.

A missing service SKIPS LOUDLY naming host and port, unless TINA4_REQUIRE_SERVICES
is set - then it is a FAILURE, because a suite that silently skips its only real
verification is not verification.
"""
import json
import os
import socket
import time

import pytest

from tina4_python.session import FileSessionHandler

MONGO_HOST = os.environ.get("TINA4_TEST_MONGO_HOST", "127.0.0.1")
MONGO_PORT = int(os.environ.get("TINA4_TEST_MONGO_PORT", "27017"))


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def _require(service: str, host: str, port: int) -> None:
    """Skip LOUDLY naming host and port, or FAIL when services are required."""
    if _reachable(host, port):
        return
    message = f"{service} is not reachable at {host}:{port}"
    if os.environ.get("TINA4_REQUIRE_SERVICES"):
        pytest.fail(f"TINA4_REQUIRE_SERVICES is set but {message}")
    pytest.skip(message)


# ── File backend ─────────────────────────────────────────────────────────


def _stored_files(path) -> list:
    """Out-of-band existence check - a directory listing, not the code under test."""
    return sorted(p.name for p in path.glob("*.json"))


def test_session_missing_expiry_stamp_survives_read(tmp_path):
    """A record carrying NO expiry stamp must be RETURNED and KEPT.

    This is the shape that killed tina4-php: the absent stamp defaulted to 0 and
    was fed into a subtraction that is then unconditionally true, and the failure
    branch unlinks.
    """
    handler = FileSessionHandler(str(tmp_path))
    target = handler._file("naked")
    target.write_text(json.dumps({"_data": {"seeded": True}}), encoding="utf-8")

    assert handler.read("naked") == {"seeded": True}, "an unstamped record must be returned"
    assert _stored_files(tmp_path), "an unstamped record must NOT be deleted"


def test_session_zero_expiry_stamp_survives_read(tmp_path):
    """A stamp that is present but ZERO means the same thing: never expires."""
    handler = FileSessionHandler(str(tmp_path))
    handler._file("zeroed").write_text(
        json.dumps({"_data": {"seeded": True}, "_expires": 0}), encoding="utf-8"
    )

    assert handler.read("zeroed") == {"seeded": True}
    assert _stored_files(tmp_path), "a zero stamp must not delete the record"


def test_session_genuinely_expired_record_is_reaped(tmp_path):
    """THE NEGATIVE CONTROL. Real wall-clock time, no clock mocking.

    Without this, a "fix" that simply removes all expiry passes every positive
    gate above and ships a sessions-never-expire security bug.
    """
    handler = FileSessionHandler(str(tmp_path))
    handler.write("expiring", {"seeded": True}, 1)
    assert _stored_files(tmp_path), "precondition: the record was written"

    time.sleep(3)

    assert handler.read("expiring") == {}, "a genuinely expired record must read as empty"
    assert not _stored_files(tmp_path), "a genuinely expired record must still be REAPED"


def test_session_past_expiry_stamp_is_reaped(tmp_path):
    """A stamp planted in the past is expired and reaped, with no waiting."""
    handler = FileSessionHandler(str(tmp_path))
    handler._file("stale").write_text(
        json.dumps({"_data": {"seeded": True}, "_expires": time.time() - 99999}),
        encoding="utf-8",
    )

    assert handler.read("stale") == {}
    assert not _stored_files(tmp_path), "a past-stamped record must be reaped"


def test_session_public_write_read_facade_round_trips(tmp_path):
    """write() then read() through a FRESH handler must round-trip and survive."""
    FileSessionHandler(str(tmp_path)).write("my-session-id", {"seeded": True}, 3600)

    assert FileSessionHandler(str(tmp_path)).read("my-session-id") == {"seeded": True}
    assert _stored_files(tmp_path), "read() must not destroy a live record"


def test_session_write_stamps_expiry_itself(tmp_path):
    """The persistence layer owns the stamp - write() must produce one itself."""
    handler = FileSessionHandler(str(tmp_path))
    handler.write("stamped", {"seeded": True}, 3600)

    stored = json.loads(handler._file("stamped").read_text(encoding="utf-8"))

    assert "_expires" in stored, "the persistence layer must stamp, not the caller"
    assert stored["_expires"] > time.time(), "the stamp must be a real future deadline"


def test_session_write_ttl_argument_is_honoured(tmp_path):
    """A per-call ttl must actually shorten the session, not be discarded."""
    handler = FileSessionHandler(str(tmp_path))
    handler.write("shortlived", {"seeded": True}, 1)

    time.sleep(3)

    assert handler.read("shortlived") == {}, "a per-call ttl of 1s must expire the record"
    assert not _stored_files(tmp_path)


def test_session_gc_keeps_unstamped_but_reaps_expired(tmp_path):
    """gc() obeys the same contract as read(): unstamped is never a candidate."""
    handler = FileSessionHandler(str(tmp_path))
    handler._file("naked").write_text(json.dumps({"_data": {"a": 1}}), encoding="utf-8")
    handler._file("zeroed").write_text(
        json.dumps({"_data": {"a": 1}, "_expires": 0}), encoding="utf-8"
    )
    handler._file("stale").write_text(
        json.dumps({"_data": {"a": 1}, "_expires": time.time() - 99999}), encoding="utf-8"
    )

    handler.gc(0)

    survivors = _stored_files(tmp_path)
    assert len(survivors) == 2, f"gc must keep the unstamped and zero-stamped records, kept {survivors}"
    assert handler.read("naked") == {"a": 1}
    assert handler.read("zeroed") == {"a": 1}
    assert handler.read("stale") == {}, "the genuinely expired record must be gone"


def test_session_boundary_sweep_of_every_stamp_state(tmp_path):
    """All five stamp states on one read path - the contract pinned in one place."""
    handler = FileSessionHandler(str(tmp_path))
    cases = {
        "absent": ({"_data": {"v": 1}}, True),
        "zero": ({"_data": {"v": 1}, "_expires": 0}, True),
        "future": ({"_data": {"v": 1}, "_expires": time.time() + 3600}, True),
        "past": ({"_data": {"v": 1}, "_expires": time.time() - 3600}, False),
    }
    for name, (payload, should_survive) in cases.items():
        handler._file(name).write_text(json.dumps(payload), encoding="utf-8")

    for name, (_, should_survive) in cases.items():
        returned = handler.read(name)
        survived = handler._file(name).exists()
        assert survived is should_survive, f"{name}: expected survival={should_survive}, got {survived}"
        assert (returned == {"v": 1}) is should_survive, f"{name}: payload disagreed with survival"


# ── Database backend: the expires_at column must not be single precision ──


def test_session_expires_at_column_is_not_single_precision():
    """REAL is float4 on PostgreSQL - one ULP is 128 SECONDS at the current epoch.

    Measured 111.99s worst-case drift over 500 real PostgreSQL 16.14 round-trips,
    so a session shorter than about two minutes can be judged expired the instant
    it is written. The loss compounds: float4 storage rounding, then a text wire
    format that does not round-trip back into a 64-bit double.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "tina4_python" / "session" / "__init__.py").read_text()

    assert "expires_at REAL" not in source, (
        "REAL is float4 on PostgreSQL - use DOUBLE PRECISION"
    )
    assert "expires_at DOUBLE PRECISION" in source


def test_session_expires_at_survives_a_postgres_round_trip():
    """The precision contract against a REAL PostgreSQL, not just the DDL string."""
    pg_host = os.environ.get("TINA4_TEST_PG_HOST", "127.0.0.1")
    pg_port = int(os.environ.get("TINA4_TEST_PG_PORT", "55432"))
    _require("PostgreSQL", pg_host, pg_port)
    psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 is not installed")

    conn = psycopg2.connect(
        host=pg_host,
        port=pg_port,
        dbname=os.environ.get("TINA4_TEST_PG_DB", "postgres"),
        user=os.environ.get("TINA4_TEST_PG_USER", "tina4"),
        password=os.environ.get("TINA4_TEST_PG_PASS", "tina4"),
    )
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS tina4_session_precision")
        cur.execute(
            "CREATE TABLE tina4_session_precision ("
            "  session_id TEXT PRIMARY KEY,"
            "  data TEXT NOT NULL,"
            "  expires_at DOUBLE PRECISION NOT NULL)"
        )

        # Repeat to defeat the 128-second float4 bucket: a single sample can land
        # near a representable value and look fine.
        worst = 0.0
        for i in range(20):
            intended = time.time() + 3600 + i * 0.37
            cur.execute(
                "INSERT INTO tina4_session_precision VALUES (%s, %s, %s)",
                (f"p{i}", "{}", intended),
            )
            cur.execute(
                "SELECT expires_at FROM tina4_session_precision WHERE session_id = %s",
                (f"p{i}",),
            )
            worst = max(worst, abs(cur.fetchone()[0] - intended))

        assert worst < 1.0, f"expires_at drifted {worst}s - that is single-precision loss, not clock skew"

        cur.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'tina4_session_precision' AND column_name = 'expires_at'"
        )
        assert cur.fetchone()[0] != "real", "the column must not be declared float4"
        cur.execute("DROP TABLE tina4_session_precision")
    finally:
        conn.close()


# ── MongoDB: the latent destroy-on-unstamped defect, and the discarded ttl ──


@pytest.fixture
def mongo_handler():
    """A real MongoDB-backed handler against a real server. No mocks."""
    _require("MongoDB", MONGO_HOST, MONGO_PORT)
    pytest.importorskip("pymongo", reason="pymongo is not installed")
    from tina4_python.session_handlers.mongodb_handler import MongoDBSessionHandler

    handler = MongoDBSessionHandler(
        url=f"mongodb://{MONGO_HOST}:{MONGO_PORT}",
        database="tina4_test",
        collection="session_contract",
        ttl=3600,
    )
    yield handler
    try:
        handler._collection.delete_many({})
    finally:
        handler.close()


def _mongo_probe():
    """An INDEPENDENT client for out-of-band assertions - never the code under test."""
    import pymongo

    return pymongo.MongoClient(
        f"mongodb://{MONGO_HOST}:{MONGO_PORT}", serverSelectionTimeoutMS=3000
    )["tina4_test"]["session_contract"]


def test_session_mongo_missing_expiry_stamp_survives_read(mongo_handler):
    """The latent PHP-shaped defect, proved against a REAL MongoDB.

    Planting a document with no stamp is exactly what a direct insert, an older
    version, or another framework writes. Before the fix read() returned {} and
    the document was DESTROYED.
    """
    probe = _mongo_probe()
    probe.delete_one({"_id": "naked"})
    probe.insert_one({"_id": "naked", "data": {"seeded": True}})

    assert mongo_handler.read("naked") == {"seeded": True}, "an unstamped doc must be returned"
    assert probe.find_one({"_id": "naked"}) is not None, "an unstamped doc must NOT be destroyed"


def test_session_mongo_genuinely_expired_document_is_reaped(mongo_handler):
    """The negative control for mongo: real expiry still destroys."""
    probe = _mongo_probe()
    probe.delete_one({"_id": "stale"})
    probe.insert_one({"_id": "stale", "data": {"seeded": True}, "expires_at": time.time() - 99999})

    assert mongo_handler.read("stale") == {}, "a genuinely expired doc must read as empty"
    assert probe.find_one({"_id": "stale"}) is None, "a genuinely expired doc must be REAPED"


def test_session_mongo_write_ttl_argument_is_honoured(mongo_handler):
    """Session(ttl=60) on mongo must give 60s, not TINA4_SESSION_TTL."""
    mongo_handler.write("shortlived", {"seeded": True}, 1)

    stored = _mongo_probe().find_one({"_id": "shortlived"})
    assert stored is not None and stored.get("expires_at", 0) > 0, "the ttl must be stored, not discarded"
    assert stored["expires_at"] - time.time() < 5, "a ttl of 1s must not become the 3600s default"

    time.sleep(3)
    assert mongo_handler.read("shortlived") == {}, "the per-call ttl must actually expire the doc"


def test_session_mongo_gc_keeps_unstamped_but_reaps_expired(mongo_handler):
    """gc() obeys the same contract: an unstamped doc is never a candidate."""
    probe = _mongo_probe()
    probe.delete_many({})
    probe.insert_one({"_id": "naked", "data": {"a": 1}})
    probe.insert_one({"_id": "zeroed", "data": {"a": 1}, "expires_at": 0})
    probe.insert_one({"_id": "stale", "data": {"a": 1}, "expires_at": time.time() - 99999})

    mongo_handler.gc(0)

    assert probe.find_one({"_id": "naked"}) is not None, "gc must keep an unstamped doc"
    assert probe.find_one({"_id": "zeroed"}) is not None, "gc must keep a zero-stamped doc"
    assert probe.find_one({"_id": "stale"}) is None, "gc must reap a genuinely expired doc"


def test_session_mongo_read_verdict_does_not_depend_on_the_readers_ttl():
    """The ttl must not be in scope at read time.

    A read path that knows the ttl can always fabricate an expiry for a record
    that carries none, which is the entire bug class. Behavioural gate rather
    than a source grep: two handlers with wildly different ttls must reach the
    SAME verdict for the same stored document, because the verdict comes from the
    document's own absolute deadline.

    Under the old relative shape a ttl=1 reader destroyed a document that a
    ttl=100000 reader happily returned.
    """
    _require("MongoDB", MONGO_HOST, MONGO_PORT)
    pytest.importorskip("pymongo", reason="pymongo is not installed")
    from tina4_python.session_handlers.mongodb_handler import MongoDBSessionHandler

    def handler(ttl):
        return MongoDBSessionHandler(
            url=f"mongodb://{MONGO_HOST}:{MONGO_PORT}",
            database="tina4_test",
            collection="session_contract",
            ttl=ttl,
        )

    impatient, patient = handler(1), handler(100000)
    probe = _mongo_probe()
    try:
        # Written long ago, but with a deadline far in the future.
        probe.delete_one({"_id": "shared"})
        probe.insert_one({
            "_id": "shared",
            "data": {"seeded": True},
            "last_accessed": time.time() - 99999,
            "expires_at": time.time() + 3600,
        })

        assert impatient.read("shared") == {"seeded": True}, (
            "a reader with a 1s ttl must not expire a document whose own deadline is in the future"
        )
        assert patient.read("shared") == {"seeded": True}
        assert probe.find_one({"_id": "shared"}) is not None, "neither reader may destroy it"
    finally:
        probe.delete_many({})
        impatient.close()
        patient.close()
