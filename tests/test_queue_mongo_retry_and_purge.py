"""Regression: MongoDB Queue.retry_job(id) revives a dead letter, and
Queue.purge(status) returns a real deleted count for every status.

MongoDB retry_job/purge (3.13.105). Two definite bugs in the
MongoDB backend before this release:

  * ``retry_job(job_id)`` searched
    ``{_id: job_id, topic: self._topic, status: "failed"}`` -- three
    reasons that could never match a dead letter:
      1. ``dead_letter()`` writes a NEW doc with a fresh ``_id``; the
         original id lives on ``data.id`` (never on ``_id``).
      2. The dead-letter topic is ``f"{self._topic}.dead_letter"``,
         not ``self._topic``.
      3. Dead letters carry ``status="dead"`` -- the original doc
         under ``self._topic`` was already acked to ``"completed"``.
    So every retry_job call returned False. A caller iterating
    ``dead_letters()`` and calling ``retry_job(j.id)`` on each got no
    revival and no error -- the dead-letter store stayed put.

  * ``purge(status)`` returned ``None`` (not a count), swallowed every
    status other than ``pending``, and even for ``pending`` called
    ``clear()`` which nuked EVERY doc under the topic regardless of
    status -- so ``purge("pending")`` also removed completed and
    reserved docs from that topic.

Named positive AND negative cases below; each proven a real gate by
mutation of the fix.

NOT a mock: real live MongoDB. Skipped when unreachable; the lab
provisions Mongo on 127.0.0.1:27017 and this suite runs there under
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
    pytest.skip(
        f"MongoDB not reachable at {HOST}:{PORT}",
        allow_module_level=True,
    )


@pytest.fixture
def mongo_queue(monkeypatch):
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", "mongodb")
    monkeypatch.setenv("TINA4_QUEUE_URL", f"mongodb://{HOST}:{PORT}")
    q = Queue(topic=f"mongo_retry_{uuid.uuid4().hex[:10]}", max_retries=1)
    yield q
    # Housekeeping: drop the topic and its dead-letter counterpart so
    # a re-run against the same Mongo doesn't accumulate cruft.
    try:
        q._backend._backend._ensure_connected()
        coll = q._backend._backend._collection
        coll.delete_many({"topic": q.topic})
        coll.delete_many({"topic": f"{q.topic}.dead_letter"})
        q.close()
    except Exception:
        pass


def _dead_letter_one(q: Queue) -> str:
    """Push a job, fail it enough times to dead-letter, return its id.

    Does NOT assert the total dead-letter count -- callers may stack
    several calls to build up N dead letters."""
    prior = len(q.dead_letters())
    job_id = q.push({"task": "doomed"})
    job = q.pop()
    assert job is not None, "prime failed: pop returned None"
    job.fail("boom")   # attempts=1 == max_retries=1 -> dead
    assert len(q.dead_letters()) == prior + 1, (
        f"prime failed: dead_letters grew by {len(q.dead_letters()) - prior}, "
        f"expected +1"
    )
    return job_id


class TestMongoRetryJob:
    def test_positive_retry_job_revives_dead_letter(self, mongo_queue):
        """retry_job(id) on a genuinely dead-lettered job returns True
        and puts the job back in pending; a re-pop must see it."""
        q = mongo_queue
        job_id = _dead_letter_one(q)

        assert q.retry(job_id) is True, (
            "retry_job(id) must revive an existing dead letter; before "
            "3.13.105 it returned False for every dead letter because the "
            "search filter never matched"
        )
        assert len(q.dead_letters()) == 0, (
            "the dead-letter store must be empty after a successful revival; "
            "leftovers cause double-processing"
        )
        assert q.size("pending") == 1, (
            "the revived job must be visible to pop() as pending"
        )
        revived = q.pop()
        assert revived is not None and revived.id == job_id, (
            "revived job's id must match the original (payload continuity)"
        )

    def test_negative_retry_job_returns_false_for_unknown_id(self, mongo_queue):
        """retry_job on an id that never existed must return False and
        not create ghost pending docs."""
        q = mongo_queue
        assert q.retry("does-not-exist-" + uuid.uuid4().hex) is False, (
            "retry_job(id) must return False when no dead letter matches"
        )
        assert q.size("pending") == 0
        assert len(q.dead_letters()) == 0


class TestMongoPurge:
    def test_positive_purge_returns_deleted_count(self, mongo_queue):
        """purge('pending') deletes only pending docs under the topic and
        returns the deleted count (pre-3.13.105 returned None)."""
        q = mongo_queue
        q.push({"n": 1})
        q.push({"n": 2})
        q.push({"n": 3})
        assert q.size("pending") == 3

        removed = q.purge("pending")

        assert removed == 3, (
            f"purge('pending') must return the deleted count, got {removed!r}"
        )
        assert q.size("pending") == 0

    def test_negative_purge_pending_leaves_dead_letters_alone(self, mongo_queue):
        """purge('pending') MUST NOT touch dead letters (pre-3.13.105 it
        used clear() which delete_many on the topic, taking everything)."""
        q = mongo_queue
        _dead_letter_one(q)                   # 1 dead letter
        q.push({"n": "keep-pending"})         # 1 fresh pending
        assert q.size("pending") == 1
        assert len(q.dead_letters()) == 1

        q.purge("pending")

        assert q.size("pending") == 0, "purge should have removed the pending"
        assert len(q.dead_letters()) == 1, (
            "purge('pending') removed the dead letter -- purge must scope by "
            "status, never nuke the whole topic"
        )

    def test_positive_purge_dead_removes_dead_letters(self, mongo_queue):
        """purge('dead') must remove dead letters and return the count."""
        q = mongo_queue
        _dead_letter_one(q)
        _dead_letter_one(q)
        assert len(q.dead_letters()) == 2

        removed = q.purge("dead")

        assert removed == 2, (
            f"purge('dead') must return the deleted dead-letter count, "
            f"got {removed!r}"
        )
        assert len(q.dead_letters()) == 0
