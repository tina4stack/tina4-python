"""Regression: job.retry() on a dead-lettered job must remove the
dead-letter file, not leave a duplicate on disk.

PY-12-05 (3.13.105). Before the fix, ``LiteBackend.retry(job)`` (the
path ``Job.retry()`` calls) re-queued the job to the pending directory
but never unlinked the file in ``_failed_dir()``. Because
``dead_letters()`` scans that directory, a manual dead-letter recovery
loop -- ``for j in q.dead_letters(): j.retry()`` -- left the dead-letter
store carrying every "revived" job, so ``dead_letters()`` reported the
same items on the next call and a consumer that acted on both lists
processed the job twice.

Contrast: ``Queue.retry(job_id)`` and no-arg ``Queue.retry()`` route
through ``LiteBackend.retry_job(id)`` (a different method) which DID
unlink correctly. Two spellings of the same intent that diverged --
the fix aligns them.

NOT a mock: a real file-backed queue on disk.
"""
import os
import pytest

from tina4_python.queue import Queue


class TestJobRetryRemovesDeadLetter:
    def _dead_letter_two_jobs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "job_retry_clean"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="job_retry_clean", max_retries=1)
        for i in range(2):
            q.push({"task": f"doomed-{i}"})
        for _ in range(2):
            j = q.pop()
            j.fail("boom")
        assert len(q.dead_letters()) == 2, "prime: expected two dead letters"
        return q

    def test_positive_job_retry_removes_dead_letter_file(self, tmp_path, monkeypatch):
        """After ``for j in q.dead_letters(): j.retry()``, the failed/
        directory is empty -- no duplicate carrying the same id."""
        q = self._dead_letter_two_jobs(tmp_path, monkeypatch)
        for j in q.dead_letters():
            j.retry()

        assert q.dead_letters() == [], (
            "dead-letter store must be empty after j.retry() revives every "
            "job; a leftover file re-appears on the next dead_letters() call "
            "and the job is processed twice"
        )

    def test_negative_job_retry_still_places_job_in_pending(self, tmp_path, monkeypatch):
        """Revival still puts every job back in pending -- the unlink
        must not accidentally drop the requeue path."""
        q = self._dead_letter_two_jobs(tmp_path, monkeypatch)
        for j in q.dead_letters():
            j.retry()

        assert q.size("pending") == 2, (
            f"expected two pending jobs after revival, got {q.size('pending')}"
        )
