"""Feature 22 - Imperative ORM relationships: the shared conformance contract.

Shared fixture: tina4-documentation/plan/v3/fixtures/imperative_relationships_contract.json

IMPREL-DEC-01 (OWNER-DECISIONS.md Batch 4): imperative relationships are a
PER-LANGUAGE IDIOM. Python/PHP/Node expose a distinct instance-method API
(has_one/has_many/belongs_to taking a related CLASS + fk); Ruby has NO separate
API - its imperative form is the declarative class method invoked at runtime.
IMPREL-DEC-02: fix Node's serialize-orphan, de-duplicate PHP's parallel impl,
and unify Python's imperative has_many cap with the lazy path.

This runner pins the four-way behaviour with REAL databases and NO mocks: real
SQLite AND real PostgreSQL (:55432, tina4/tina4 by default). Row presence/absence
is asserted by querying real rows. Positive AND negative throughout.

Case names are shared verbatim across the four frameworks and gated by
scripts/audit-contract-fixtures.py. Under TINA4_REQUIRE_SERVICES a postgres skip
is a hard failure.
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


# ── Models (unique names; table name != lowercased class name on purpose, so the
#    Node serialize-orphan bug -- keyed on the TABLE name -- would bite) ────────
class ImpRelAuthor(ORM):
    table_name = "imp_rel_author"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()


class ImpRelPost(ORM):
    table_name = "imp_rel_post"
    id = IntegerField(primary_key=True, auto_increment=True)
    title = StringField()
    author_id = ForeignKeyField(to=ImpRelAuthor, related_name="posts")


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
        db = Database(f"sqlite:///{tmp_path/'imprel.db'}")
    bind_database(db)
    for table in ("imp_rel_post", "imp_rel_author"):
        try:
            db.execute(f"DROP TABLE {table}")
        except Exception:
            pass
    ImpRelAuthor.create_table()
    ImpRelPost.create_table()
    return db


# ── IMPREL-DEC-02: an imperatively-loaded relation SERIALIZES ────────────────
@pytest.mark.parametrize("engine", _ENGINES)
def test_imperative_relation_serializes(engine, tmp_path):
    db = _engine_db(engine, tmp_path)
    author = ImpRelAuthor(name="a").save()
    for i in range(3):
        ImpRelPost(title=f"p{i}", author_id=author.id).save()

    # Imperative load: instance method taking the related CLASS + fk (Python idiom).
    rel = author.has_many(ImpRelPost, "author_id")
    assert len(rel) == 3

    # Serialization with include= contains the relation with the same rows.
    d = author.to_dict(include=["posts"])
    assert "posts" in d
    assert len(d["posts"]) == 3
    assert sorted(p["title"] for p in d["posts"]) == ["p0", "p1", "p2"]

    # Negative: WITHOUT include the relation is not serialized (fields only).
    assert "posts" not in author.to_dict()


# ── IMPREL-PY-CAP: imperative and lazy paths return the SAME row count ────────
def test_imperative_and_lazy_same_row_count(tmp_path):
    # SQLite only: paging is engine-independent. 150 > the old imperative cap of
    # 100, so a still-capped imperative path would return fewer than the lazy one.
    db = _engine_db("sqlite", tmp_path)
    author = ImpRelAuthor(name="a").save()
    n = 150
    db.insert("imp_rel_post", [{"title": f"p{i}", "author_id": author.id} for i in range(n)])

    imperative = author.has_many(ImpRelPost, "author_id")
    lazy = ImpRelAuthor.find(author.id).posts

    assert len(imperative) == n, f"imperative capped: {len(imperative)}"
    assert len(lazy) == n, f"lazy capped: {len(lazy)}"
    assert len(imperative) == len(lazy)

    # Negative: an EXPLICIT limit still pages (proves the default is genuinely
    # uncapped, not just a larger fixed cap).
    assert len(author.has_many(ImpRelPost, "author_id", limit=100)) == 100


# ── IMPREL-DEC-01: the imperative surface behaves the same (per-language idiom) ─
@pytest.mark.parametrize("engine", _ENGINES)
def test_imperative_surface_behaves_same_all_four(engine, tmp_path):
    db = _engine_db(engine, tmp_path)
    author = ImpRelAuthor(name="a").save()
    ImpRelPost(title="p0", author_id=author.id).save()
    ImpRelPost(title="p1", author_id=author.id).save()
    child = ImpRelPost.where("title = ?", params=["p0"])[0]

    # has_one -> a single related child
    one = author.has_one(ImpRelPost, "author_id")
    assert one is not None and one.title in ("p0", "p1")

    # has_many -> all the children
    many = author.has_many(ImpRelPost, "author_id")
    assert sorted(p.title for p in many) == ["p0", "p1"]

    # belongs_to -> the parent
    parent = child.belongs_to(ImpRelAuthor, "author_id")
    assert parent is not None and parent.name == "a"

    # Negative: belongs_to whose FK resolves to no parent returns None
    # (read-side-only: no DB FK constraint, so a dangling FK inserts fine).
    orphan = ImpRelPost(title="orphan", author_id=999999).save()
    assert orphan.belongs_to(ImpRelAuthor, "author_id") is None
