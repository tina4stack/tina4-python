"""DocStore - pymongo-style SQLite document store (JSON1 fallback).

Locks the everyday CRUD + filter subset, the built-in ObjectId, value
round-trip (ObjectId/datetime), cursor semantics, and the serverless
selection (SQLite when no Mongo configured).
"""
import re
import pytest
from datetime import datetime, timezone

from tina4_python.docstore import (
    ObjectId, InvalidId, SqliteDatabase, get_collection, is_serverless,
    reset_default_store, compile_filter,
)


@pytest.fixture
def db():
    d = SqliteDatabase(":memory:")
    yield d
    d.close()


@pytest.fixture
def orders(db):
    return db.get_collection("orders")


# ── ObjectId ──────────────────────────────────────────────────────────────

class TestObjectId:
    def test_generates_unique_24_hex(self):
        a, b = ObjectId(), ObjectId()
        assert a != b
        assert re.match(r"^[0-9a-f]{24}$", str(a))

    def test_roundtrip_from_hex(self):
        a = ObjectId()
        assert ObjectId(str(a)) == a
        assert hash(ObjectId(str(a))) == hash(a)

    def test_is_valid(self):
        assert ObjectId.is_valid(str(ObjectId()))
        assert not ObjectId.is_valid("nope")
        assert not ObjectId.is_valid("zz" * 12)

    def test_invalid_raises(self):
        with pytest.raises(InvalidId):
            ObjectId("too-short")

    def test_generation_time_is_utc_datetime(self):
        gt = ObjectId().generation_time
        assert isinstance(gt, datetime) and gt.tzinfo is not None


# ── insert + find ───────────────────────────────────────────────────────────

class TestInsertFind:
    def test_insert_one_returns_objectid(self, orders):
        res = orders.insert_one({"customer_id": 1, "total": 9.99})
        assert isinstance(res.inserted_id, ObjectId)
        got = orders.find_one({"_id": res.inserted_id})
        assert got["customer_id"] == 1 and got["total"] == 9.99
        assert got["_id"] == res.inserted_id  # _id rehydrated to ObjectId

    def test_insert_many(self, orders):
        ids = orders.insert_many([{"n": i} for i in range(5)]).inserted_ids
        assert len(ids) == 5
        assert orders.count_documents({}) == 5

    def test_custom_id_preserved(self, orders):
        orders.insert_one({"_id": "ORD-1", "x": 1})
        assert orders.find_one({"_id": "ORD-1"})["x"] == 1


# ── filter operators (pushed to SQL via json_extract) ───────────────────────

class TestFilters:
    @pytest.fixture(autouse=True)
    def _seed(self, orders):
        orders.insert_many([
            {"customer_id": 1, "status": "new", "total": 10, "tags": ["a"]},
            {"customer_id": 2, "status": "shipped", "total": 50},
            {"customer_id": 3, "status": "shipped", "total": 99, "vip": True},
        ])

    def test_equality(self, orders):
        assert orders.count_documents({"status": "shipped"}) == 2

    def test_in(self, orders):
        got = orders.find({"customer_id": {"$in": [1, 3]}}).to_list()
        assert {d["customer_id"] for d in got} == {1, 3}

    def test_comparisons(self, orders):
        assert orders.count_documents({"total": {"$gt": 10}}) == 2
        assert orders.count_documents({"total": {"$gte": 10, "$lt": 99}}) == 2
        assert orders.count_documents({"total": {"$lte": 10}}) == 1

    def test_ne(self, orders):
        assert orders.count_documents({"status": {"$ne": "shipped"}}) == 1

    def test_exists(self, orders):
        assert orders.count_documents({"vip": {"$exists": True}}) == 1
        assert orders.count_documents({"vip": {"$exists": False}}) == 2

    def test_regex(self, orders):
        assert orders.count_documents({"status": {"$regex": "^ship"}}) == 2

    def test_or(self, orders):
        got = orders.find({"$or": [{"customer_id": 1}, {"total": {"$gt": 90}}]}).to_list()
        assert {d["customer_id"] for d in got} == {1, 3}

    def test_pushdown_uses_json_extract(self):
        where, params = compile_filter({"customer_id": {"$in": [1, 2]}})
        assert "json_extract(doc" in where and "IN (?,?)" in where
        assert params == [1, 2]


# ── cursor: sort / limit / skip / projection ────────────────────────────────

class TestCursor:
    @pytest.fixture(autouse=True)
    def _seed(self, orders):
        orders.insert_many([{"n": i, "grp": "g"} for i in range(10)])

    def test_sort_desc(self, orders):
        got = orders.find({"grp": "g"}).sort("n", -1).to_list()
        assert [d["n"] for d in got] == list(range(9, -1, -1))

    def test_limit_skip(self, orders):
        got = orders.find({"grp": "g"}).sort("n", 1).skip(2).limit(3).to_list()
        assert [d["n"] for d in got] == [2, 3, 4]

    def test_projection_include(self, orders):
        d = orders.find_one({"n": 5}, {"n": 1, "_id": 0})
        assert d == {"n": 5}

    def test_projection_exclude(self, orders):
        d = orders.find_one({"n": 5}, {"grp": 0})
        assert "grp" not in d and d["n"] == 5 and "_id" in d


# ── datetime round-trip + sortability ───────────────────────────────────────

class TestDatetime:
    def test_roundtrip_and_sort(self, orders):
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        orders.insert_many([
            {"k": "b", "created_at": datetime(2024, 3, 1, tzinfo=timezone.utc)},
            {"k": "a", "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc)},
            {"k": "c", "created_at": datetime(2024, 6, 1, tzinfo=timezone.utc)},
        ])
        got = orders.find({}).sort("created_at", -1).to_list()
        assert [d["k"] for d in got] == ["c", "b", "a"]
        assert isinstance(got[0]["created_at"], datetime)
        assert orders.count_documents({"created_at": {"$gte": base}}) == 3


# ── updates ──────────────────────────────────────────────────────────────────

class TestUpdates:
    def test_set_inc_unset(self, orders):
        oid = orders.insert_one({"status": "new", "count": 1, "tmp": "x"}).inserted_id
        orders.update_one({"_id": oid}, {"$set": {"status": "shipped"}})
        orders.update_one({"_id": oid}, {"$inc": {"count": 5}})
        orders.update_one({"_id": oid}, {"$unset": {"tmp": ""}})
        d = orders.find_one({"_id": oid})
        assert d["status"] == "shipped" and d["count"] == 6 and "tmp" not in d

    def test_update_many(self, orders):
        orders.insert_many([{"s": "a"}, {"s": "a"}, {"s": "b"}])
        res = orders.update_many({"s": "a"}, {"$set": {"s": "z"}})
        assert res.matched_count == 2 and res.modified_count == 2
        assert orders.count_documents({"s": "z"}) == 2

    def test_replace_one_keeps_id(self, orders):
        oid = orders.insert_one({"a": 1}).inserted_id
        orders.replace_one({"_id": oid}, {"b": 2})
        d = orders.find_one({"_id": oid})
        assert d["b"] == 2 and "a" not in d and d["_id"] == oid

    def test_upsert(self, orders):
        res = orders.update_one({"sku": "X1"}, {"$set": {"qty": 3}}, upsert=True)
        assert res.upserted_id is not None
        assert orders.find_one({"sku": "X1"})["qty"] == 3

    def test_nested_set(self, orders):
        oid = orders.insert_one({"a": {"b": 1}}).inserted_id
        orders.update_one({"_id": oid}, {"$set": {"a.c": 2}})
        d = orders.find_one({"_id": oid})
        assert d["a"] == {"b": 1, "c": 2}


# ── deletes + nested filter ──────────────────────────────────────────────────

class TestDeleteAndNested:
    def test_delete_one_and_many(self, orders):
        orders.insert_many([{"s": "a"}, {"s": "a"}, {"s": "b"}])
        assert orders.delete_one({"s": "a"}).deleted_count == 1
        assert orders.delete_many({"s": "a"}).deleted_count == 1
        assert orders.count_documents({}) == 1

    def test_nested_dotted_filter(self, orders):
        orders.insert_one({"addr": {"city": "Cape Town"}})
        orders.insert_one({"addr": {"city": "Joburg"}})
        assert orders.count_documents({"addr.city": "Cape Town"}) == 1


# ── serverless selection ─────────────────────────────────────────────────────

class TestSelection:
    def test_serverless_when_no_mongo(self, monkeypatch):
        for k in ("TINA4_MONGO_URI", "TINA4_SESSION_MONGO_URL"):
            monkeypatch.delenv(k, raising=False)
        assert is_serverless() is True

    def test_get_collection_is_sqlite_when_serverless(self, monkeypatch, tmp_path):
        for k in ("TINA4_MONGO_URI", "TINA4_SESSION_MONGO_URL"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("TINA4_DOC_STORE_PATH", str(tmp_path / "ds.db"))
        reset_default_store()
        col = get_collection("widgets")
        from tina4_python.docstore import SqliteCollection
        assert isinstance(col, SqliteCollection)
        col.insert_one({"name": "bolt"})
        assert col.find_one({"name": "bolt"})["name"] == "bolt"
        reset_default_store()

    def test_db_attribute_and_item_access(self, db):
        db.get_collection("a").insert_one({"x": 1})
        assert db["a"].count_documents({}) == 1
        assert db.a.count_documents({}) == 1  # attribute access
