"""Regression: Queue.retry() with no args must revive EVERY dead letter.

PY-12-04 (3.13.105). Before the fix the no-arg branch used
``any(self._backend.retry_job(j.id, delay_seconds) for j in dead)``,
so as soon as the FIRST dead-letter revived (``retry_job`` returning
truthy) Python's short-circuiting ``any`` stopped iterating -- the
second and third jobs were never re-queued and stayed silently in
the dead-letter store.

The invariant: with N dead letters, ``retry()`` moves ALL N to
pending. Named positive AND negative cases below; proven a real
gate by mutation (revert the fix; both tests fail).

NOT a mock: a real file-backed queue, real dead-letters written to
disk, real pop/fail lifecycle.
"""
import pytest

from tina4_python.queue import Queue


class TestRetryReviveEveryDeadLetter:
    def _dead_letter_three_jobs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "revive_all"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="revive_all", max_retries=1)
        for i in range(3):
            q.push({"task": f"doomed-{i}"})
        # Dead-letter each -- attempts=1 == max_retries=1 -> dead.
        for _ in range(3):
            job = q.pop()
            assert job is not None, "prime failed: could not pop the job"
            job.fail(f"err")
        assert len(q.dead_letters()) == 3, "prime failed: three dead letters expected"
        assert q.size("pending") == 0
        return q

    def test_positive_retry_no_arg_revives_all_three(self, tmp_path, monkeypatch):
        """With three dead letters, ``retry()`` must revive all three,
        not just the first (the short-circuit-any() footgun)."""
        q = self._dead_letter_three_jobs(tmp_path, monkeypatch)

        ok = q.retry()

        assert ok is True, "at least one dead letter should have been revived"
        assert q.size("pending") == 3, (
            f"expected all three dead letters revived, got size(pending)={q.size('pending')}; "
            "any() short-circuit only re-queues the first"
        )

    def test_negative_retry_no_arg_leaves_dead_store_empty(self, tmp_path, monkeypatch):
        """After a successful ``retry()`` no dead letter must remain
        on disk -- the retry path must fully consume the dead-letter
        store, not leave two behind for a future accidental re-run."""
        q = self._dead_letter_three_jobs(tmp_path, monkeypatch)

        q.retry()

        assert q.dead_letters() == [], (
            "no dead letter must remain after retry() revives all three; "
            "stale entries lead to double-processing on a later retry()"
        )
