"""CACHE CONTRACT - a query-cache key carries DATABASE IDENTITY.

Pins ``the-cache-key-carries-database-identity`` from
``plan/v3/fixtures/cache_contract.json`` (ADR-0024).

    A query-cache key identifies the DATABASE it came from. Two databases
    sharing one cache backend can never serve each other's rows.

This is a DATA ISOLATION failure wearing a caching costume. The key was
``sha256(sql + params)`` with nothing naming the connection, so on ANY shared
backend two databases cross-served each other's rows: two apps pointed at one
Redis, or one app with a primary and an analytics connection, silently read each
other's data. The identical SQL text is exactly what a multi-tenant deployment
runs, so the collision is the common case, not an edge case.

Everything here runs against REAL databases (two real SQLite files and two real
PostgreSQL databases) and a REAL shared cache backend. Nothing is simulated.

SERVICE ADDRESSES
        TINA4_TEST_CACHE_REDIS_URL   (default redis://localhost:6379)
        TINA4_TEST_PG_HOST / _PORT / _USERNAME / _PASSWORD
"""
import os
import socket
import uuid
from urllib.parse import urlparse

import pytest

from tina4_python.database import Database

REDIS_URL = os.environ.get("TINA4_TEST_CACHE_REDIS_URL", "redis://localhost:6379")
PG_HOST = os.environ.get("TINA4_TEST_PG_HOST", "localhost")
PG_PORT = int(os.environ.get("TINA4_TEST_PG_PORT", "55432"))
PG_USER = os.environ.get("TINA4_TEST_PG_USERNAME", "tina4")
PG_PASS = os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4")
# Databases this contract OWNS. Never touch one we did not create.
PG_DB_A = "tina4_cache_contract_a"
PG_DB_B = "tina4_cache_contract_b"


def _reachable(host: str, port: int) -> bool:
    try:
        sock = socket.create_connection((host, port), timeout=2)
        sock.close()
        return True
    except OSError:
        return False


_redis_parsed = urlparse(REDIS_URL if "://" in REDIS_URL else "//" + REDIS_URL)
redis_up = pytest.mark.skipif(
    not _reachable(_redis_parsed.hostname or "localhost", _redis_parsed.port or 6379),
    reason="redis service not reachable",
)
postgres_up = pytest.mark.skipif(
    not _reachable(PG_HOST, PG_PORT), reason="postgresql service not reachable"
)


@pytest.fixture
def shared_redis_cache(monkeypatch):
    """Point the persistent DB query cache at ONE real shared Redis."""
    monkeypatch.setenv("TINA4_DB_CACHE", "true")
    monkeypatch.setenv("TINA4_DB_CACHE_TTL", "60")
    monkeypatch.setenv("TINA4_DB_CACHE_BACKEND", "redis")
    monkeypatch.setenv("TINA4_DB_CACHE_URL", REDIS_URL)


def _seed_sqlite(path, marker):
    db = Database(f"sqlite:///{path}")
    db.execute("CREATE TABLE IF NOT EXISTS widget (id INTEGER PRIMARY KEY, owner TEXT)")
    db.execute("DELETE FROM widget")
    db.insert("widget", {"id": 1, "owner": marker})
    return db


# ── the rule ──────────────────────────────────────────────────────


@redis_up
def test_two_databases_sharing_one_cache_backend_do_not_cross_serve(
    tmp_path, shared_redis_cache
):
    """The whole invariant, on real files and a real shared Redis.

    Two SQLite databases, identical schema, identical SQL, DIFFERENT rows, one
    Redis. Reading A then B must return B's row. With no database identity in
    the key, B gets a HIT on A's entry and reads A's data.
    """
    db_a = _seed_sqlite(tmp_path / "primary.db", "database-a")
    db_b = _seed_sqlite(tmp_path / "analytics.db", "database-b")
    db_a.cache_clear()
    db_b.cache_clear()

    sql = "SELECT owner FROM widget WHERE id = ?"
    rows_a = db_a.fetch(sql, [1]).records
    rows_b = db_b.fetch(sql, [1]).records

    assert rows_a[0]["owner"] == "database-a"
    assert rows_b[0]["owner"] == "database-b", (
        "database B was served database A's cached row - the cache key carries "
        "no database identity, so a shared backend cross-serves between "
        "databases. This is a data-isolation failure, not a cache miss."
    )


@redis_up
def test_the_cache_key_changes_when_the_database_changes(tmp_path, shared_redis_cache):
    """Direct assertion on the key itself, so the reason is unambiguous."""
    db_a = Database(f"sqlite:///{tmp_path / 'one.db'}")
    db_b = Database(f"sqlite:///{tmp_path / 'two.db'}")
    sql = "SELECT owner FROM widget WHERE id = ?"

    assert db_a._cache_key(sql, [1]) != db_b._cache_key(sql, [1]), (
        "the same SQL against two different databases produces the SAME cache "
        "key, so either can serve the other's rows"
    )


@redis_up
def test_the_cache_key_is_stable_for_the_same_database(tmp_path, shared_redis_cache):
    """NEGATIVE: identity must not be per-connection or per-process.

    A key that folds in something instance-specific (an object id, a pid, a
    random salt) would isolate the databases by accident and destroy the whole
    point of a SHARED cache: no instance would ever hit another's entry.
    """
    path = tmp_path / "same.db"
    first = Database(f"sqlite:///{path}")
    second = Database(f"sqlite:///{path}")
    sql = "SELECT owner FROM widget WHERE id = ?"

    assert first._cache_key(sql, [1]) == second._cache_key(sql, [1]), (
        "two connections to the SAME database produce different cache keys, so "
        "a shared cache can never hit across instances"
    )


def test_the_cache_key_excludes_credentials():
    """NEGATIVE: credentials must never reach the key.

    Two reasons. A credential in a key means every rotation silently cold-starts
    the cache; and a shared backend's key namespace is readable by every tenant
    of that backend, so a secret must never be folded into it.

    A pure function over its inputs, so it needs no live service and uses no
    stand-in: ``_cache_identity`` is called directly rather than through a
    connection, because the constructor connects eagerly and a deliberately
    wrong password would fail before the key is ever computed.
    """
    plain = Database._cache_identity("postgres://db.internal:5432/ledger")
    with_user = Database._cache_identity("postgres://reader@db.internal:5432/ledger")
    with_secret = Database._cache_identity(
        "postgres://reader:hunter2@db.internal:5432/ledger"
    )
    rotated = Database._cache_identity(
        "postgres://reader:rotated-p4ss@db.internal:5432/ledger"
    )

    assert plain == with_user == with_secret == rotated, (
        "the identity changed with the credentials - a rotation cold-starts the "
        "cache and a secret leaks into a shared key namespace"
    )
    assert "hunter2" not in with_secret and "rotated-p4ss" not in rotated, (
        "a password appears verbatim in the cache identity, which is visible to "
        "every tenant of a shared cache backend"
    )
    # And the identity still SEPARATES databases on that same server.
    assert plain != Database._cache_identity("postgres://db.internal:5432/analytics")


@redis_up
@postgres_up
def test_two_postgres_databases_do_not_cross_serve(shared_redis_cache):
    """The primary-and-analytics case, on a REAL PostgreSQL server.

    Same host, same port, same user, same SQL - only the database name differs.
    That is the deployment ADR-0024 describes, and it is the one where the
    SQLite path's differing file names could mask a partial fix.
    """
    table = f"widget_{uuid.uuid4().hex[:8]}"
    urls = {
        "database-a": f"postgres://{PG_HOST}:{PG_PORT}/{PG_DB_A}",
        "database-b": f"postgres://{PG_HOST}:{PG_PORT}/{PG_DB_B}",
    }
    handles = {}
    try:
        for marker, url in urls.items():
            db = Database(url, PG_USER, PG_PASS)
            db.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, owner VARCHAR(50))")
            db.insert(table, {"id": 1, "owner": marker})
            db.cache_clear()
            handles[marker] = db

        sql = f"SELECT owner FROM {table} WHERE id = ?"
        got_a = handles["database-a"].fetch(sql, [1]).records[0]["owner"]
        got_b = handles["database-b"].fetch(sql, [1]).records[0]["owner"]

        assert got_a == "database-a"
        assert got_b == "database-b", (
            "the analytics database was served the primary database's cached "
            "row - one PostgreSQL server, two databases, one shared cache, and "
            "the key cannot tell them apart"
        )
    finally:
        # Drop only the table WE created. Never drop a database we did not make.
        for db in handles.values():
            try:
                db.execute(f"DROP TABLE IF EXISTS {table}")
            except Exception:
                pass
