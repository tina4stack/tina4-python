"""Regression: job.reject() dead-letters IMMEDIATELY, no retry (ADR-0023).

Bug 4 (book review). Python's ``Job.reject()`` was a literal alias for
``fail()`` (``def reject(self, reason=""): self.fail(reason)``). ADR-0023
(Accepted) redefines reject: it is the "this message is poison, do NOT retry
it" path — the job goes straight to the dead-letter store on this call,
without burning the retry budget. This is AMQP basic.reject(requeue=false).

The distinction is the whole point, so the test pins BOTH sides on the same
queue with max_retries=3:
  * reject()  -> dead-lettered NOW (1 attempt), never re-queued
  * fail()    -> re-queued, still pending, NOT dead-lettered (control)

Real filesystem file backend (no mock). Pure-local: needs no external service.
"""
from __future__ import annotations

import uuid

import pytest

from tina4_python.queue import Queue


@pytest.fixture
def file_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
    monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "queue"))
    # retry_backoff 0 so a fail()'d job is immediately visible as pending.
    return Queue(topic=f"reject_{uuid.uuid4().hex[:8]}", max_retries=3)


class TestRejectDeadLettersNow:
    def test_positive_reject_dead_letters_immediately(self, file_queue):
        """reject() on the FIRST delivery dead-letters the job at once, even
        though max_retries=3 leaves retries on the table."""
        q = file_queue
        q.push({"task": "poison"})
        job = q.pop()
        assert job is not None

        job.reject("payload will never parse")

        dead = q.dead_letters()
        assert len(dead) == 1, "reject() must dead-letter on this call, not after max_retries"
        assert dead[0].error == "payload will never parse"
        assert q.size("dead") == 1, "size('dead') must count the rejected job"
        assert q.size("pending") == 0, "a rejected job must NOT be re-queued"

    def test_negative_fail_still_retries_not_dead_letters(self, file_queue):
        """Control: fail() with retries left re-queues (pending), it does NOT
        dead-letter. Proves reject() and fail() are genuinely different — if
        reject were still an alias for fail this queue would show 0 dead here
        AND in the positive test, so one of the two would fail."""
        q = file_queue
        q.push({"task": "transient"})
        job = q.pop()
        assert job is not None

        job.fail("temporary blip")

        assert q.size("dead") == 0, "fail() under max_retries must NOT dead-letter"
        assert q.size("pending") == 1, "fail() under max_retries must re-queue as pending"
        assert len(q.dead_letters()) == 0

    def test_positive_rejected_job_not_redelivered(self, file_queue):
        """After reject(), a subsequent pop() sees nothing — the job is gone
        from the live queue, only reachable via dead_letters()."""
        q = file_queue
        q.push({"task": "poison"})
        job = q.pop()
        job.reject("nope")
        assert q.pop() is None, "a rejected job must never be redelivered to pop()"
