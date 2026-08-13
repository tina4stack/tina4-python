"""MongoDB SQL provider — fail-closed WHERE + mass-delete data-loss guard (feature 14).

Shared contract: plan/v3/fixtures/mongosql_contract.json (MONGO-DEC-01). This is
the Python half; PHP/Ruby/Node carry the same case names against the same real
MongoDB.

WHY THIS FILE EXISTS
    The MongoDB SQL provider translates a SQL WHERE into a Mongo filter with a
    hand-rolled regex parser. Before MONGO-DEC-01 an UNPARSEABLE / UNSUPPORTED
    WHERE silently degraded to an EMPTY filter, so a DELETE/UPDATE then reached
    delete_many({}) / update_many({}) and matched EVERY document -- a silent
    mass wipe. There was ZERO functional test of the parse/CRUD path in any
    framework, which is exactly how the danger shipped.

    The guard is fail-closed: an unparseable WHERE RAISES (never match-all), and
    a DELETE/UPDATE with NO WHERE clause is REFUSED (truncate() is the explicit
    whole-collection spelling). This file proves it against a REAL MongoDB.

NO MOCKS. A real MongoDB over a real socket, real documents seeded and read back.
The witness is a real side effect: after the guard fires, the collection count is
UNCHANGED (nothing was deleted/rewritten). Mutation-proved: disable the guard and
the unparseable-WHERE delete wipes the collection, so "count unchanged" goes red.
"""
import os
import socket
import uuid

import pytest

from tina4_python.database import Database

MONGO_HOST = os.environ.get("TINA4_TEST_MONGO_HOST", "127.0.0.1")
MONGO_PORT = int(os.environ.get("TINA4_TEST_MONGO_PORT", "27017"))
MONGO_URI = os.environ.get(
    "TINA4_TEST_MONGO_URI", f"mongodb://{MONGO_HOST}:{MONGO_PORT}"
)
DB_NAME = "tina4_mongosql_py"


def _mongo_reachable() -> bool:
    """A real connect + ping, not a bare port probe."""
    try:
        import pymongo
    except ImportError:
        return False
    try:
        host = MONGO_URI.split("://", 1)[-1].split("/", 1)[0].split(":")[0]
        port = MONGO_PORT
        with socket.create_connection((host, port), timeout=3):
            pass
        client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        client.admin.command("ping")
        client.close()
        return True
    except Exception:
        return False


needs_mongo = pytest.mark.skipif(
    not _mongo_reachable(),
    reason=f"no reachable MongoDB at {MONGO_URI} (set TINA4_TEST_MONGO_URI)",
)


def _uri_with_db() -> str:
    """Point the connection at a dedicated database, keeping any URI shape valid."""
    base = MONGO_URI.split("://", 1)[-1]
    scheme = MONGO_URI.split("://", 1)[0]
    host_and_path = base.split("?", 1)[0]
    host = host_and_path.split("/", 1)[0]
    query = ("?" + MONGO_URI.split("?", 1)[1]) if "?" in MONGO_URI else ""
    return f"{scheme}://{host}/{DB_NAME}{query}"


@pytest.fixture()
def mongo():
    """A real Mongo-backed Database bound to a UNIQUE collection, cleaned up after."""
    db = Database(_uri_with_db())
    collection = f"widgets_{uuid.uuid4().hex[:12]}"
    yield db, collection
    # Reap: drop the collection and close the client so no state leaks on the lab.
    try:
        db.execute(f"DROP TABLE {collection}")
    except Exception:
        pass
    try:
        db._get_adapter().close()
    except Exception:
        pass


def _seed(db, collection, rows):
    for row in rows:
        db.insert(collection, dict(row))


def _count(db, collection) -> int:
    return db.fetch(f"SELECT * FROM {collection}").count


def _statuses(db, collection):
    return sorted(r.get("status") for r in db.fetch(f"SELECT * FROM {collection}").records)


# ── Guard 1: an unparseable / unsupported WHERE fails closed ─────────────────

@needs_mongo
def test_an_unparseable_where_delete_raises_and_deletes_nothing(mongo):
    db, collection = mongo
    _seed(db, collection, [
        {"id": 1, "status": "keep"},
        {"id": 2, "status": "keep"},
        {"id": 3, "status": "gone"},
    ])
    assert _count(db, collection) == 3

    # UPPER(status) is a function on the column -- unsupported by the regex
    # parser. Before the fix it degraded to {} and delete_many({}) wiped all 3.
    with pytest.raises(Exception) as exc:
        db.execute(f"DELETE FROM {collection} WHERE UPPER(status) = 'GONE'")
    assert "Unsupported" in str(exc.value) or "fail" in str(exc.value).lower()

    # The witness: nothing was deleted.
    assert _count(db, collection) == 3


@needs_mongo
def test_a_partially_unparseable_where_delete_raises_and_deletes_nothing(mongo):
    # A COMPOUND WHERE where one AND-part is valid and one is unsupported. If the
    # parser silently DROPPED the unsupported part it would leave {id: 1} -- a
    # NON-empty but WRONG filter that the empty-filter guard waves through -- and
    # delete id=1 regardless of its status. Only the fail-closed parse catches
    # this: the whole statement must raise, deleting nothing.
    db, collection = mongo
    _seed(db, collection, [
        {"id": 1, "status": "keep"},
        {"id": 2, "status": "gone"},
    ])

    with pytest.raises(Exception):
        db.execute(f"DELETE FROM {collection} WHERE id = 1 AND UPPER(status) = 'GONE'")

    # Neither document was touched.
    assert _count(db, collection) == 2
    assert _statuses(db, collection) == ["gone", "keep"]


@needs_mongo
def test_an_unparseable_where_update_raises_and_changes_nothing(mongo):
    db, collection = mongo
    _seed(db, collection, [
        {"id": 1, "status": "keep"},
        {"id": 2, "status": "keep"},
    ])

    with pytest.raises(Exception):
        db.execute(f"UPDATE {collection} SET status = ? WHERE UPPER(status) = 'KEEP'", ["wiped"])

    # Nothing was rewritten.
    assert _statuses(db, collection) == ["keep", "keep"]


# ── Guard 2: a DELETE/UPDATE with NO WHERE is refused (mass-write guard) ──────

@needs_mongo
def test_a_no_where_delete_is_rejected_and_deletes_nothing(mongo):
    db, collection = mongo
    _seed(db, collection, [
        {"id": 1, "status": "keep"},
        {"id": 2, "status": "keep"},
        {"id": 3, "status": "keep"},
    ])
    assert _count(db, collection) == 3

    with pytest.raises(Exception):
        db.execute(f"DELETE FROM {collection}")

    # A filterless delete must never empty the collection.
    assert _count(db, collection) == 3


@needs_mongo
def test_a_no_where_update_is_rejected_and_changes_nothing(mongo):
    db, collection = mongo
    _seed(db, collection, [
        {"id": 1, "status": "keep"},
        {"id": 2, "status": "keep"},
    ])

    with pytest.raises(Exception):
        db.execute(f"UPDATE {collection} SET status = ?", ["wiped"])

    assert _statuses(db, collection) == ["keep", "keep"]


# ── Positive: a real WHERE scopes the write to only the matching documents ───

@needs_mongo
def test_a_valid_where_delete_removes_only_matching_docs(mongo):
    db, collection = mongo
    _seed(db, collection, [
        {"id": 1, "status": "keep"},
        {"id": 2, "status": "gone"},
        {"id": 3, "status": "keep"},
        {"id": 4, "status": "gone"},
    ])
    assert _count(db, collection) == 4

    db.execute(f"DELETE FROM {collection} WHERE status = ?", ["gone"])

    # Exactly the two matches are gone; the two "keep" rows remain.
    assert _count(db, collection) == 2
    assert _statuses(db, collection) == ["keep", "keep"]


@needs_mongo
def test_a_valid_where_update_changes_only_matching_docs(mongo):
    db, collection = mongo
    _seed(db, collection, [
        {"id": 1, "status": "keep"},
        {"id": 2, "status": "keep"},
        {"id": 3, "status": "keep"},
    ])

    db.execute(f"UPDATE {collection} SET status = ? WHERE id = ?", ["changed", 2])

    # Only id=2 changed.
    assert _statuses(db, collection) == ["changed", "keep", "keep"]


# ── Feature 14b: the explicit 1=1 tautology (truncate) empties the collection ─

@needs_mongo
def test_a_truncate_empties_the_collection(mongo):
    # truncate() issues DELETE ... WHERE 1 = 1. The explicit 1=1 tautology must
    # translate to a MATCH-ALL {} filter so EVERY document is removed -- not the
    # {"1": 1} filter that matched nothing and made truncate() a silent no-op in
    # Python/Ruby/Node (PHP already special-cased it). Mutation-proved: revert
    # the 1=1 -> {} translation in _parse_condition and this count stays 3
    # (truncate deletes 0), while the feature-14 guard cases stay green.
    db, collection = mongo
    _seed(db, collection, [
        {"id": 1, "status": "keep"},
        {"id": 2, "status": "keep"},
        {"id": 3, "status": "gone"},
    ])
    assert _count(db, collection) == 3

    db.truncate(collection)

    # The witness: the collection is actually empty.
    assert _count(db, collection) == 0


@needs_mongo
def test_a_scoped_equality_is_not_widened_to_match_all(mongo):
    # The tautology fix must be TIGHT: only a lone "1 = 1" is match-all. An
    # ordinary numeric equality like "id = 1" -- superficially close to "1 = 1"
    # -- must stay SCOPED to its one match, never widening to a delete-all.
    db, collection = mongo
    _seed(db, collection, [
        {"id": 1, "status": "keep"},
        {"id": 2, "status": "keep"},
    ])

    db.execute(f"DELETE FROM {collection} WHERE id = 1")

    # Only id=1 was removed; id=2 remains.
    assert _count(db, collection) == 1
    assert _statuses(db, collection) == ["keep"]
