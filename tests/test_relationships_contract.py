"""Feature 21 - Declarative ORM relationships: the shared conformance contract.

Shared fixture: tina4-documentation/plan/v3/fixtures/relationships_contract.json

REL-DEC-01 (read-side-only cascade) + REL-DEC-02 (Node declarative auto-wire +
lazy load, soft-delete filter on traversal, bounded eager IN + explicit lazy
paging, PHP static eagerLoad). This runner pins the four-way behaviour with REAL
databases and NO mocks: real SQLite AND real PostgreSQL (:55432, tina4/tina4 by
default). Row presence/absence is asserted by querying the real table; the
"one query per relation" invariant is proven with a REAL executed-statement
counter that instruments the real adapter's fetch (observation, not a mock).

Case names are shared verbatim across the four frameworks and gated by
scripts/audit-contract-fixtures.py. Under TINA4_REQUIRE_SERVICES a postgres skip
is a hard failure (RequireServicesExtension names it 'unreachable').
"""
import os
import socket

import pytest

from tina4_python.database import Database
from tina4_python.orm import (
    ORM,
    IntegerField,
    StringField,
    ForeignKeyField,
    bind_database,
)

_PG = dict(
    host=os.environ.get("TINA4_TEST_PG_HOST", "127.0.0.1"),
    port=int(os.environ.get("TINA4_TEST_PG_PORT", "55432")),
    user=os.environ.get("TINA4_TEST_PG_USERNAME", "tina4"),
    pwd=os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4"),
    db=os.environ.get("TINA4_TEST_PG_DB", "tina4_py"),
)
_ENGINES = ["sqlite", "postgres"]


# ── Models (unique names so ORM.__subclasses__() never collides) ─────────────
class RelAuthor(ORM):
    table_name = "rel_author"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()


class RelPost(ORM):
    table_name = "rel_post"
    soft_delete = True
    id = IntegerField(primary_key=True, auto_increment=True)
    title = StringField()
    is_deleted = IntegerField(default=0)
    author_id = ForeignKeyField(to=RelAuthor, related_name="posts")


def _reachable(host, port):
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def _engine_db(engine, tmp_path):
    if engine == "postgres":
        if not _reachable(_PG["host"], _PG["port"]):
            pytest.skip(f"postgres unreachable at {_PG['host']}:{_PG['port']} (set TINA4_TEST_PG_*)")
        db = Database(f"postgres://{_PG['host']}:{_PG['port']}/{_PG['db']}", _PG["user"], _PG["pwd"])
    else:
        db = Database(f"sqlite:///{tmp_path/'rel.db'}")
    bind_database(db)
    for table in ("rel_post", "rel_author"):
        try:
            db.execute(f"DROP TABLE {table}")
        except Exception:
            pass
    RelAuthor.create_table()
    RelPost.create_table()
    return db


def _raw_count(db, table, where="1=1", params=None):
    return db.fetch_one(f"SELECT COUNT(*) AS c FROM {table} WHERE {where}", params or [])["c"]


class _FetchCounter:
    """Instrument the REAL adapter fetch to count queries touching a table.

    This wraps the framework's own fetch so every counted call still executes
    the REAL SQL against the REAL database -- observation, never a mock.
    """

    def __init__(self, db, table):
        self.db, self.table, self.count = db, table.lower(), 0
        self._orig = db.fetch

    def __enter__(self):
        def wrapped(*args, **kwargs):
            sql = args[0] if args else kwargs.get("sql", "")
            if self.table in str(sql).lower():
                self.count += 1
            return self._orig(*args, **kwargs)

        self.db.fetch = wrapped
        return self

    def __exit__(self, *exc):
        self.db.fetch = self._orig


# ── REL-EAGER: exactly ONE query per relation (no N+1) ───────────────────────
@pytest.mark.parametrize("engine", _ENGINES)
def test_eager_include_runs_one_query_per_relation(engine, tmp_path):
    db = _engine_db(engine, tmp_path)
    for a in range(3):
        author = RelAuthor(name=f"a{a}").save()
        for p in range(2):
            RelPost(title=f"a{a}-p{p}", author_id=author.id).save()

    with _FetchCounter(db, "rel_post") as counter:
        authors = RelAuthor.all(include=["posts"])
        # touch the eager-loaded relation (must already be cached, no extra query)
        total = sum(len(a.posts) for a in authors)

    assert total == 6
    # ONE query for the whole relation across all 3 authors -- not one per author.
    assert counter.count == 1, f"expected 1 relation query, got {counter.count} (N+1)"


# ── REL-SOFTDELETE: a soft-deleted child is excluded from traversal ──────────
@pytest.mark.parametrize("engine", _ENGINES)
def test_soft_deleted_child_excluded_from_lazy_traversal(engine, tmp_path):
    db = _engine_db(engine, tmp_path)
    author = RelAuthor(name="a").save()
    keep = RelPost(title="keep", author_id=author.id).save()
    gone = RelPost(title="gone", author_id=author.id).save()
    gone.delete()  # soft delete -> is_deleted = 1

    # raw row still present (soft, not hard) but absent from traversal
    assert _raw_count(db, "rel_post") == 2
    fresh = RelAuthor.find(author.id)
    titles = [p.title for p in fresh.posts]
    assert titles == ["keep"], titles


@pytest.mark.parametrize("engine", _ENGINES)
def test_soft_deleted_child_excluded_from_eager_traversal(engine, tmp_path):
    db = _engine_db(engine, tmp_path)
    author = RelAuthor(name="a").save()
    RelPost(title="keep", author_id=author.id).save()
    gone = RelPost(title="gone", author_id=author.id).save()
    gone.delete()

    loaded = RelAuthor.all(include=["posts"])
    assert len(loaded) == 1
    titles = [p.title for p in loaded[0].posts]
    assert titles == ["keep"], titles


# ── REL-EAGER-UNBOUNDED: > one page of children is fully reachable ───────────
def test_large_child_set_is_fully_reachable_not_truncated(tmp_path):
    # SQLite only: this proves the PAGING loop returns the tail (was a silent
    # 1000-row cap). The paging is engine-independent; a 1001-row batch keeps the
    # case fast while exceeding every old cap (Python 1000, PHP/Ruby 100).
    db = _engine_db("sqlite", tmp_path)
    author = RelAuthor(name="a").save()
    db.insert("rel_post", [{"title": f"p{i}", "author_id": author.id, "is_deleted": 0} for i in range(1001)])

    fresh = RelAuthor.find(author.id)
    assert len(fresh.posts) == 1001, f"tail lost: got {len(fresh.posts)}"


# ── REL-DEC-02: lazy attribute access returns the related rows ───────────────
@pytest.mark.parametrize("engine", _ENGINES)
def test_lazy_attribute_access_returns_related_rows(engine, tmp_path):
    db = _engine_db(engine, tmp_path)
    author = RelAuthor(name="a").save()
    RelPost(title="p0", author_id=author.id).save()
    RelPost(title="p1", author_id=author.id).save()

    # has_many lazy read
    fresh = RelAuthor.find(author.id)
    assert sorted(p.title for p in fresh.posts) == ["p0", "p1"]

    # belongs_to lazy read from the other side
    post = RelPost.where("title = ?", params=["p0"])[0]
    assert post.author is not None
    assert post.author.name == "a"


# ── REL-DEC-01: read-side-only -- deleting a parent leaves children ──────────
@pytest.mark.parametrize("engine", _ENGINES)
def test_deleting_a_parent_leaves_children_in_the_db(engine, tmp_path):
    db = _engine_db(engine, tmp_path)
    author = RelAuthor(name="a").save()
    RelPost(title="p0", author_id=author.id).save()
    RelPost(title="p1", author_id=author.id).save()

    author.force_delete()  # hard delete the parent

    # No DB-level ON DELETE cascade: the children rows survive.
    assert _raw_count(db, "rel_author", "id = ?", [author.id]) == 0
    assert _raw_count(db, "rel_post", "author_id = ?", [author.id]) == 2


# ── REL-DEC-01: declaring on_delete is rejected (dropped phantom param) ───────
def test_declaring_on_delete_raises_read_side_only():
    # Python-only: the phantom on_delete= param is dropped; using it now raises a
    # clear read-side-only error instead of silently doing nothing.
    with pytest.raises(ValueError) as excinfo:
        ForeignKeyField(to=RelAuthor, on_delete="CASCADE")
    assert "read-side-only" in str(excinfo.value)
