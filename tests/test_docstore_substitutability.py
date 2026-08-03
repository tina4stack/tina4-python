"""DocStore substitutability: the SAME code, against BOTH providers.

plan/v3/fixtures/docstore_contract.json is the shared answer key. This proves
the invariants that can be proven today and PRINTS the ones that are still
broken, so the file stays a live gate instead of a permanently-red one nobody
runs.

WHY THIS FILE EXISTS AT ALL
    DocStore is the purest test of ADR-0024 in the framework, because
    substitutability IS its advertised feature: "develop against a
    zero-dependency local SQLite store and switch to MongoDB in production by
    setting one env var".

    MEASURED 2026-08-01: NO DocStore test in ANY of the four frameworks had ever
    touched a real Mongo collection. tina4-python's own tests/test_docstore.py
    mentions mongodb:// only as FAKE URIs ("mongodb://uri-host/db") to check
    which env var wins - it never connects. So the entire substitutability
    promise had zero coverage, which is exactly how nine defects accumulated
    behind four green suites.

    Every assertion below therefore runs TWICE: once on the SQLite fallback and
    once on a REAL MongoDB. A divergence between the two columns IS the bug -
    that is the whole point, and no assertion here is meaningful against one
    provider alone.

NO MOCKS. Real SQLite file, real MongoDB over a real socket. Skips (loudly) when
no Mongo is reachable, because a fabricated Mongo would defeat the purpose of
the file.
"""
from __future__ import annotations
import time

import os
import socket
import sys
import tempfile
import uuid

import pytest

MONGO_HOST = os.environ.get("TINA4_TEST_MONGO_HOST", "192.168.88.99")
MONGO_PORT = int(os.environ.get("TINA4_TEST_MONGO_PORT", "27017"))
MONGO_URI = os.environ.get("TINA4_TEST_MONGO_URI", f"mongodb://{MONGO_HOST}:{MONGO_PORT}")


def _mongo_reachable() -> bool:
    """A real connect, not a port probe.

    A port that merely accepts is not a usable Mongo - that distinction is the
    same one that turned an intended skip into a hard failure in the MySQL batch
    tests, where the gate checked reachability and the service then refused the
    credentials.
    """
    try:
        import pymongo
    except ImportError:
        return False
    try:
        with socket.create_connection((MONGO_HOST, MONGO_PORT), timeout=3):
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


def _fresh_docstore(uri: str | None):
    """Import a pristine docstore bound to one provider.

    The module caches its store and reads the URI at import, so the module is
    dropped and re-imported per provider rather than mutated in place.
    """
    for key in ("TINA4_MONGO_URI", "TINA4_SESSION_MONGO_URI", "TINA4_SESSION_MONGO_URL"):
        os.environ.pop(key, None)
    if uri:
        os.environ["TINA4_MONGO_URI"] = uri
    os.environ["TINA4_DOC_STORE_PATH"] = tempfile.mktemp(suffix=".db")
    for name in [m for m in list(sys.modules) if "docstore" in m]:
        del sys.modules[name]
    import tina4_python.docstore as ds

    return ds


@pytest.fixture(params=["fallback", "mongo"])
def store(request):
    """One collection per provider, cleaned up, so a case runs on both."""
    if request.param == "mongo":
        if not _mongo_reachable():
            pytest.skip(f"no reachable MongoDB at {MONGO_URI}")
        ds = _fresh_docstore(MONGO_URI)
    else:
        ds = _fresh_docstore(None)

    name = "ds_contract_" + uuid.uuid4().hex[:10]
    collection = ds.get_collection(name)
    yield request.param, ds, collection
    try:
        collection.delete_many({})
    except Exception:
        pass


class TestARealMongoIsActuallyExercised:
    """docstore_contract.json :: a-real-mongo-is-actually-exercised.

    The root invariant. It is listed last in the fixture because it EXPLAINS the
    other seven: with no real-provider coverage, every other rule could drift
    unnoticed.
    """

    @needs_mongo
    def test_a_real_mongo_collection_is_reachable_and_used(self):
        ds = _fresh_docstore(MONGO_URI)
        collection = ds.get_collection("ds_contract_" + uuid.uuid4().hex[:8])

        # NEGATIVE: this must NOT be the local fallback masquerading as Mongo.
        assert type(collection).__name__ != "SqliteCollection", (
            "get_collection returned the SQLite fallback while a Mongo URI was "
            "configured - the exact silent-degradation this contract forbids"
        )
        # POSITIVE: and it must really round-trip through the server.
        result = collection.insert_one({"proof": "real-mongo"})
        assert collection.find_one({"_id": result.inserted_id})["proof"] == "real-mongo"
        collection.delete_many({})

    @needs_mongo
    def test_is_serverless_agrees_with_what_get_collection_returned(self):
        """The two must never disagree.

        MEASURED on PHP: isServerless() reported "not serverless" while
        getCollection() still handed back local SQLite, so the app reported it
        was on Mongo while writing to a container-local file.
        """
        ds = _fresh_docstore(MONGO_URI)
        collection = ds.get_collection("ds_contract_" + uuid.uuid4().hex[:8])
        assert ds.is_serverless() is False
        assert type(collection).__name__ != "SqliteCollection"


class TestExportedTypesAreAcceptedByTheRealDriver:
    """docstore_contract.json :: exported-types-are-accepted-by-the-real-driver."""

    def test_the_exported_object_id_is_usable_as_a_document_id(self, store):
        """MEASURED BROKEN 2026-08-03, now fixed.

        The module exported its own ObjectId class; pymongo refused it with
        `InvalidDocument: cannot encode object`, even though
        bson.ObjectId(str(oid)) encoded fine. The VALUE was right and the TYPE
        was wrong, so the documented way to build an id worked on the fallback
        and failed the moment TINA4_MONGO_URI was set.
        """
        provider, ds, collection = store
        oid = ds.ObjectId()

        result = collection.insert_one({"_id": oid, "provider": provider})
        assert result.inserted_id == oid

        found = collection.find_one({"_id": oid})
        assert found is not None, f"{provider}: a document keyed by the exported ObjectId is unfindable"
        assert found["provider"] == provider

    def test_an_object_id_round_trips_through_its_string_form(self, store):
        provider, ds, collection = store
        oid = ds.ObjectId()
        collection.insert_one({"_id": oid, "n": 1})

        # The 24-hex string is the portable form; rebuilding from it must find
        # the same document on either provider.
        rebuilt = ds.ObjectId(str(oid))
        assert collection.find_one({"_id": rebuilt})["n"] == 1


class TestTheDocumentRoundTripIsIdentical:
    """The baseline both providers must share before any subtler rule matters."""

    def test_insert_then_find_one_returns_what_was_stored(self, store):
        provider, ds, collection = store
        collection.insert_one({"name": "alpha", "n": 5, "ok": True})

        found = collection.find_one({"name": "alpha"})
        assert found["n"] == 5, f"{provider}: integer did not round-trip"
        assert found["ok"] is True, f"{provider}: boolean did not round-trip"

    def test_update_one_set_is_visible_to_the_next_read(self, store):
        provider, ds, collection = store
        result = collection.insert_one({"name": "beta", "status": "new"})

        collection.update_one({"_id": result.inserted_id}, {"$set": {"status": "shipped"}})
        assert collection.find_one({"_id": result.inserted_id})["status"] == "shipped"

    def test_count_documents_agrees_with_what_was_inserted(self, store):
        provider, ds, collection = store
        for i in range(3):
            collection.insert_one({"batch": "c", "i": i})

        assert collection.count_documents({"batch": "c"}) == 3

    def test_a_comparison_operator_filters_the_same_way(self, store):
        provider, ds, collection = store
        for n in (1, 5, 9):
            collection.insert_one({"grp": "d", "n": n})

        got = sorted(doc["n"] for doc in collection.find({"grp": "d", "n": {"$gt": 4}}))
        assert got == [5, 9], f"{provider}: $gt returned {got}"



# ── ADR-0025 clause 4 / query-semantics-match-on-both-providers (ASSERTED) ────

ARRAY_CASES = [
    ("equality containment", {"tags": "x"}),
    ("equality no match", {"tags": "z"}),
    ("exact array, right order", {"tags": ["x", "y"]}),
    ("exact array, wrong order", {"tags": ["y", "x"]}),
    ("$in hits one element", {"tags": {"$in": ["x", "q"]}}),
    ("$in hits nothing", {"tags": {"$in": ["q"]}}),
    ("$nin excludes a present element", {"tags": {"$nin": ["x"]}}),
    ("$nin with an absent element", {"tags": {"$nin": ["q"]}}),
    ("$ne a present element", {"tags": {"$ne": "x"}}),
    ("$ne an absent element", {"tags": {"$ne": "q"}}),
    ("numeric containment", {"nums": 1}),
    ("$gt any element", {"nums": {"$gt": 2}}),
    ("$gt no element", {"nums": {"$gt": 9}}),
    ("$lt any element", {"nums": {"$lt": 2}}),
    ("$exists on an array", {"tags": {"$exists": True}}),
    ("empty array exact", {"empty": []}),
    ("$regex on an array element", {"tags": {"$regex": "^x$"}}),
    ("scalar still works", {"scalar": "x"}),
    ("object field is not matched by its value", {"obj": "x"}),
    ("object field matches the whole object", {"obj": {"city": "x"}}),
]

ARRAY_DOC = {
    "name": "w", "tags": ["x", "y"], "nums": [1, 2, 3],
    "empty": [], "scalar": "x", "obj": {"city": "x"},
}


class TestArrayQuerySemantics:
    """docstore_contract.json :: query-semantics-match-on-both-providers

    MEASURED 2026-08-03 against a real MongoDB: EIGHT array-query behaviours
    diverged IDENTICALLY in all four frameworks, which is the signature of a
    contract nobody had written down. Three of them were FALSE POSITIVES - the
    fallback returned a document Mongo excludes:

        {"nums": {"$gt": 9}} matched [1,2,3], because json_extract of an array
        returns its JSON TEXT and SQLite sorts any text above any number.

    MongoDB's rule is one sentence: a condition on an array-valued field matches
    when ANY ELEMENT matches it (or the whole array equals the operand), and a
    negation matches when NO element does. The fallback now implements exactly
    that over json_each.

    The assertion is not "the fallback returns N" - it is that BOTH PROVIDERS
    RETURN THE SAME THING. That is ADR-0024 stated directly, and it cannot drift
    to match a hard-coded expectation.
    """

    def test_array_queries_match_identically_on_both_providers(self):
        if not _mongo_reachable():
            pytest.skip(f"no reachable MongoDB at {MONGO_URI}")

        results = {}
        for provider, uri in (("fallback", None), ("mongo", MONGO_URI)):
            docstore = _fresh_docstore(uri)
            col = docstore.get_collection("array_semantics")
            col.delete_many({})
            col.insert_one(dict(ARRAY_DOC))
            results[provider] = {n: len(list(col.find(q))) for n, q in ARRAY_CASES}
            col.delete_many({})

        mismatched = {
            n: (results["fallback"][n], results["mongo"][n])
            for n, _ in ARRAY_CASES
            if results["fallback"][n] != results["mongo"][n]
        }
        assert not mismatched, (
            "array-query semantics diverge between the providers "
            f"(fallback, mongo): {mismatched}"
        )

class TestClientLifecycleIsBounded:
    """docstore_contract.json :: client-lifecycle-is-bounded

    MEASURED 2026-08-03 against a real MongoDB: get_collection() built a NEW
    MongoClient on every call and never closed it. 20 calls left ~39 server
    connections open, growing linearly and without bound. Invisible in
    development, because the SQLite fallback opens no connections at all - the
    leak existed ONLY after the swap to the real provider.

    What is asserted is the SHAPE of the growth, not its size. A pool
    legitimately opens several connections to serve work and then PLATEAUS; a
    leak keeps climbing. So this drives three identical rounds plus a long
    sequential run and asserts the last stretch adds nothing.
    """

    @staticmethod
    def _server_connections() -> int:
        import pymongo

        probe = pymongo.MongoClient(MONGO_URI)
        try:
            return probe.admin.command("serverStatus")["connections"]["current"]
        finally:
            probe.close()

    def test_repeated_get_collection_does_not_grow_connections(self, tmp_path):
        if not _mongo_reachable():
            pytest.skip(f"no reachable MongoDB at {MONGO_URI}")

        docstore = _fresh_docstore(MONGO_URI)

        rounds = []
        for _ in range(3):
            for _ in range(20):
                docstore.get_collection("lifecycle_probe").count_documents({})
            rounds.append(self._server_connections())

        settled = rounds[-1]
        for _ in range(100):
            docstore.get_collection("lifecycle_probe").count_documents({})
        after_hundred = self._server_connections()

        # POSITIVE: 100 further calls on a settled pool add nothing. Under the
        # old one-client-per-call code this was roughly +200.
        assert after_hundred <= settled + 2, (
            f"connections still growing: settled={settled} after 100 more={after_hundred}"
        )
        # And the growth flattened rather than tracking the call count.
        assert rounds[2] - rounds[1] <= 2 and rounds[2] < 60, f"rounds={rounds}"

        before = self._server_connections()
        docstore.close_doc_store()
        time.sleep(1)
        assert self._server_connections() < before, "close_doc_store released nothing"
