"""Regression: MongoDB no-arg ``Queue.retry()`` revives dead letters, and
``dead_letters()[i].id`` is the ORIGINAL job id (not the dead-letter doc's
synthetic ``_id``).

Bug 1 (book review). ``dead_letter()`` writes the dead-letter doc with a
FRESH random ``_id`` and keeps the original id on ``data.id``. The Mongo
adapter's ``dead_letters()`` returned ``d["_id"]`` as the job ``id``, but
``retry_job()`` looks a dead letter up by ``data.id`` -- so the two never
matched. The repro from the book:

    push(max_retries=1); pop(); fail()      -> dead_letters() == 1
    retry()                                 -> returned False, job stayed dead

because no-arg ``Queue.retry()`` iterates ``dead_letters()`` and calls
``retry_job(j.id)`` on each, and every ``j.id`` was the synthetic ``_id``.

Distinct from tests/test_queue_mongo_retry_and_purge.py, which calls
``retry(job_id)`` with the ORIGINAL id explicitly and so never exercised the
mismatch.

NOT a mock: real live MongoDB. Skipped when unreachable; the lab provisions
Mongo on 127.0.0.1:27017 and this suite runs there under
TINA4_REQUIRE_SERVICES=1.
"""
from __future__ import annotations

import os
import socket
import uuid

import pytest

pytest.importorskip("pymongo")

from tina4_python.queue import Queue


HOST = os.environ.get("TINA4_TEST_MONGO_HOST", "127.0.0.1")
PORT = int(os.environ.get("TINA4_TEST_MONGO_PORT", "27017"))


def _reachable() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=2):
            return True
    except OSError:
        return False


if not _reachable():
    if os.environ.get("TINA4_REQUIRE_SERVICES"):
        raise RuntimeError(
            f"TINA4_REQUIRE_SERVICES is set but MongoDB is not reachable "
            f"at {HOST}:{PORT}"
        )
    pytest.skip(f"MongoDB not reachable at {HOST}:{PORT}", allow_module_level=True)


@pytest.fixture
def mongo_queue(monkeypatch):
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", "mongodb")
    monkeypatch.setenv("TINA4_QUEUE_URL", f"mongodb://{HOST}:{PORT}")
    q = Queue(topic=f"mongo_retryall_{uuid.uuid4().hex[:10]}", max_retries=1)
    yield q
    try:
        q._backend._backend._ensure_connected()
        coll = q._backend._backend._collection
        coll.delete_many({"topic": q.topic})
        coll.delete_many({"topic": f"{q.topic}.dead_letter"})
        q.close()
    except Exception:
        pass


def _dead_letter_one(q: Queue) -> str:
    prior = len(q.dead_letters())
    job_id = q.push({"task": "doomed"})
    job = q.pop()
    assert job is not None, "prime failed: pop returned None"
    job.fail("boom")   # attempts=1 == max_retries=1 -> dead
    assert len(q.dead_letters()) == prior + 1
    return job_id


class TestMongoDeadLetterIdContinuity:
    def test_positive_dead_letters_surface_original_job_id(self, mongo_queue):
        """dead_letters()[i].id must equal the id push() returned, so a caller
        can retry/replay by it. Before the fix it was a synthetic uuid."""
        q = mongo_queue
        job_id = _dead_letter_one(q)
        dead = q.dead_letters()
        assert len(dead) == 1
        assert dead[0].id == job_id, (
            "dead_letters()[i].id must be the ORIGINAL job id; it was the "
            "dead-letter doc's synthetic _id, so retry-by-id could never match"
        )

    def test_positive_noarg_retry_revives_all_dead_letters(self, mongo_queue):
        """The book repro: push/pop/fail then no-arg retry() must revive the
        job and empty the dead-letter store."""
        q = mongo_queue
        job_id = _dead_letter_one(q)
        assert len(q.dead_letters()) == 1

        assert q.retry() is True, (
            "no-arg Queue.retry() must revive dead letters; it returned False "
            "because retry_job() was handed the synthetic _id, not data.id"
        )
        assert len(q.dead_letters()) == 0, "dead-letter store must be empty after revival"
        assert q.size("pending") == 1, "revived job must be pending"
        revived = q.pop()
        assert revived is not None and revived.id == job_id

    def test_positive_noarg_retry_revives_every_one(self, mongo_queue):
        """Two dead letters, one no-arg retry() -> both revived (not just the
        first; guards the id fix across the whole set)."""
        q = mongo_queue
        _dead_letter_one(q)
        _dead_letter_one(q)
        assert len(q.dead_letters()) == 2

        assert q.retry() is True
        assert len(q.dead_letters()) == 0
        assert q.size("pending") == 2

    def test_negative_noarg_retry_false_when_no_dead_letters(self, mongo_queue):
        """No-arg retry() returns False when there is nothing to revive, and
        creates no ghost pending docs."""
        q = mongo_queue
        assert q.retry() is False
        assert q.size("pending") == 0
