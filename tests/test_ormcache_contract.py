"""ORM result caching contract -- feature 25 (CACHE-DEC-01).

Shared conformance fixture: tina4-documentation/plan/v3/fixtures/ormcache_contract.json

Proves, against a REAL SQLite database with REAL rows and REAL ORM writes (NO
mocks), that Model.cached():

  * caches within the TTL (a DIRECT db write between two reads is NOT seen), and
    ttl<=0 means NO-CACHE (every read hits the DB);
  * is busted by a save/delete/force_delete/restore THROUGH THE ORM;
  * is tagged by every table it touches, so a write to a JOINed table busts it
    while a write to an UNRELATED table leaves it intact.

"It cached" is proven POSITIVELY: the ONLY way the second within-TTL read can be
stale is that it came from the cache. The direct write uses db.update() -- the
low-level facade -- which never touches the model query cache, so it is a genuine
"someone changed the row behind the cache's back" event.

Mutation proof (run by the maintainer, not asserted here): dropping the
clear_cache() call from any write turns the matching bust case RED; making the
ttl<=0 path store an entry turns 'ttl zero does not cache' RED; making the bust a
wholesale _query_cache.clear() turns the unrelated-table case RED.
"""
import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, bind_database, IntegerField, StringField
from tina4_python.orm.model import _query_cache


class CacheAuthor(ORM):
    table_name = "cacheauthor"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()


class CacheBook(ORM):
    table_name = "cachebook"
    id = IntegerField(primary_key=True, auto_increment=True)
    title = StringField()
    author_id = IntegerField()
    is_deleted = IntegerField(default=0)
    soft_delete = True


BOOK_SQL = "SELECT id, title FROM cachebook WHERE is_deleted = 0"
ALL_BOOK_SQL = "SELECT id, title FROM cachebook"
# A JOIN that touches BOTH tables and filters on the author's name, so a rename
# of the author changes the RESULT SET (row count) -- no reliance on an extra
# column being exposed as an attribute.
JOIN_SQL = (
    "SELECT b.id FROM cachebook b "
    "JOIN cacheauthor a ON a.id = b.author_id WHERE a.name = ?"
)


@pytest.fixture
def db(tmp_path):
    """Fresh real SQLite DB per test, tables created, model query cache cleared."""
    database = Database(f"sqlite:///{tmp_path/'ormcache.db'}")
    bind_database(database)
    CacheAuthor.create_table()
    CacheBook.create_table()
    _query_cache.clear()
    yield database


# ── Invariant: caches within ttl; ttl=0 = no-cache ───────────────────────────

def test_a_cached_query_is_served_from_cache_within_ttl(db):
    CacheBook(title="A", author_id=0).save()

    first = CacheBook.cached(BOOK_SQL, ttl=60)
    assert [b.title for b in first] == ["A"]

    # Direct db write behind the cache's back (NOT an ORM write -> no bust).
    db.update("cachebook", {"id": 1, "title": "CHANGED"})

    second = CacheBook.cached(BOOK_SQL, ttl=60)
    # Stale on purpose: the only way this is "A" is that it was served from cache.
    assert [b.title for b in second] == ["A"]


def test_ttl_zero_does_not_cache(db):
    CacheBook(title="A", author_id=0).save()

    first = CacheBook.cached(BOOK_SQL, ttl=0)
    assert [b.title for b in first] == ["A"]

    db.update("cachebook", {"id": 1, "title": "CHANGED"})

    second = CacheBook.cached(BOOK_SQL, ttl=0)
    # ttl<=0 stores nothing, so this read hit the DB and sees the change.
    assert [b.title for b in second] == ["CHANGED"]


# ── Invariant: busts on every ORM write ──────────────────────────────────────

def test_a_save_through_the_orm_busts_the_cached_read(db):
    CacheBook(title="A", author_id=0).save()

    assert [b.title for b in CacheBook.cached(BOOK_SQL, ttl=60)] == ["A"]

    book = CacheBook.select_one("SELECT * FROM cachebook WHERE id = 1")
    book.title = "B"
    book.save()

    assert [b.title for b in CacheBook.cached(BOOK_SQL, ttl=60)] == ["B"]


def test_a_delete_through_the_orm_busts_the_cached_read(db):
    CacheBook(title="A", author_id=0).save()
    CacheBook(title="B", author_id=0).save()

    assert len(CacheBook.cached(BOOK_SQL, ttl=60)) == 2

    CacheBook.select_one("SELECT * FROM cachebook WHERE id = 1").delete()  # soft

    assert len(CacheBook.cached(BOOK_SQL, ttl=60)) == 1


def test_a_force_delete_through_the_orm_busts_the_cached_read(db):
    CacheBook(title="A", author_id=0).save()
    CacheBook(title="B", author_id=0).save()

    assert len(CacheBook.cached(ALL_BOOK_SQL, ttl=60)) == 2

    CacheBook.select_one("SELECT * FROM cachebook WHERE id = 1").force_delete()

    assert len(CacheBook.cached(ALL_BOOK_SQL, ttl=60)) == 1


def test_a_restore_through_the_orm_busts_the_cached_read(db):
    CacheBook(title="A", author_id=0).save()
    book = CacheBook.select_one("SELECT * FROM cachebook WHERE id = 1")
    book.delete()  # soft-delete -> is_deleted = 1

    # Cached view of ACTIVE rows is empty...
    assert CacheBook.cached(BOOK_SQL, ttl=60) == []

    book.restore()  # ORM write -> must bust

    # ...and the restore is seen, not the stale empty result.
    assert [b.title for b in CacheBook.cached(BOOK_SQL, ttl=60)] == ["A"]


# ── Invariant: tagged by table (cross-table bust; unrelated left intact) ──────

def test_a_write_to_a_joined_table_busts_the_cross_table_cached_read(db):
    CacheAuthor(name="A1").save()
    CacheBook(title="A", author_id=1).save()

    first = CacheBook.cached(JOIN_SQL, ["A1"], ttl=60)
    assert len(first) == 1

    author = CacheAuthor.select_one("SELECT * FROM cacheauthor WHERE id = 1")
    author.name = "A2"
    author.save()  # writes cacheauthor -> must bust the cross-table cached JOIN

    second = CacheBook.cached(JOIN_SQL, ["A1"], ttl=60)
    assert len(second) == 0


def test_a_write_to_an_unrelated_table_leaves_the_cached_read_intact(db):
    CacheAuthor(name="A1").save()
    CacheBook(title="A", author_id=1).save()

    assert [b.title for b in CacheBook.cached(BOOK_SQL, ttl=60)] == ["A"]

    # Change the book row directly (no ORM bust), then write an UNRELATED table.
    db.update("cachebook", {"id": 1, "title": "RAW"})
    author = CacheAuthor.select_one("SELECT * FROM cacheauthor WHERE id = 1")
    author.name = "A2"
    author.save()  # writes cacheauthor only -> must NOT bust the cachebook query

    # The cachebook entry survived (tag-scoped bust, not a wholesale flush): the
    # direct RAW change is still invisible, so this is served from cache.
    assert [b.title for b in CacheBook.cached(BOOK_SQL, ttl=60)] == ["A"]
