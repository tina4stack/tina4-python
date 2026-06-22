# Tests for tina4_python.queue — file-based backend
import os
import json
import time
import pytest
from tina4_python.queue import Queue


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "queue"))
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
    return Queue(topic="test")


class TestQueue:
    def test_push_and_pop(self, queue):
        queue.push({"task": "send_email"})
        job = queue.pop()
        assert job is not None
        assert job.data["task"] == "send_email"

    def test_pop_empty(self, queue):
        assert queue.pop() is None

    def test_fifo_order(self, queue):
        # Equal priority (default 0) → oldest-first, so insertion order holds.
        queue.push({"order": 1})
        queue.push({"order": 2})
        assert queue.pop().data["order"] == 1
        assert queue.pop().data["order"] == 2

    def test_priority(self, queue):
        # Higher priority pops first even though it was pushed later.
        queue.push({"task": "low"}, priority=0)
        queue.push({"task": "high"}, priority=10)
        assert queue.pop().data["task"] == "high"
        assert queue.pop().data["task"] == "low"

    def test_priority_beats_older_lower_priority_job(self, queue):
        # A higher-priority job pops before a lower-priority OLDER job.
        queue.push({"task": "old_low"}, priority=1)
        queue.push({"task": "mid"}, priority=5)
        queue.push({"task": "new_high"}, priority=10)
        order = [queue.pop().data["task"], queue.pop().data["task"], queue.pop().data["task"]]
        assert order == ["new_high", "mid", "old_low"]

    def test_priority_tie_broken_oldest_first(self, queue):
        # Same priority → oldest (earliest created_at) first.
        queue.push({"n": 1}, priority=5)
        queue.push({"n": 2}, priority=5)
        queue.push({"n": 3}, priority=5)
        assert [queue.pop().data["n"], queue.pop().data["n"], queue.pop().data["n"]] == [1, 2, 3]

    def test_priority_pop_batch_orders_by_priority(self, queue):
        queue.push({"t": "low"}, priority=0)
        queue.push({"t": "high"}, priority=10)
        queue.push({"t": "mid"}, priority=5)
        jobs = queue.pop_batch(3)
        assert [j.data["t"] for j in jobs] == ["high", "mid", "low"]

    def test_delayed_high_priority_skipped_until_available(self, queue):
        # A delayed high-priority job must not jump ahead while still delayed;
        # an available lower-priority job pops first.
        queue.push({"t": "delayed_high"}, priority=100, delay_seconds=3600)
        queue.push({"t": "available_low"}, priority=0)
        job = queue.pop()
        assert job.data["t"] == "available_low"
        # The delayed job is still not available
        assert queue.pop() is None

    def test_size(self, queue):
        assert queue.size() == 0
        queue.push({"a": 1})
        queue.push({"b": 2})
        assert queue.size() == 2

    def test_size_after_pop(self, queue):
        queue.push({"a": 1})
        queue.push({"b": 2})
        queue.pop()
        assert queue.size() == 1

    def test_complete(self, queue):
        queue.push({"task": "done"})
        job = queue.pop()
        job.complete()
        # File adapter deletes on pop, complete is a no-op
        assert queue.size("pending") == 0

    def test_fail_requeues_while_retries_remain(self, queue):
        # Default max_retries=3: a single failure (attempts=1 < 3) is
        # automatically re-enqueued to pending — NOT moved to dead-letter.
        queue.push({"task": "broken"})
        job = queue.pop()
        job.fail("something went wrong")
        # Not dead yet: failed/ directory stays empty
        failed_dir = os.path.join(os.environ["TINA4_QUEUE_PATH"], "test", "failed")
        failed_files = [f for f in os.listdir(failed_dir) if f.endswith(".queue-data")]
        assert len(failed_files) == 0
        # The job is back in the pending queue with attempts incremented
        assert queue.size("pending") == 1
        requeued = queue.pop()
        assert requeued.attempts == 1
        assert requeued.error == "something went wrong"

    def test_retry(self, queue):
        queue.push({"task": "retry_me"})
        job = queue.pop()
        job.retry()
        assert queue.size("pending") == 1
        retried = queue.pop()
        assert retried.attempts == 1

    def test_purge(self, queue):
        queue.push({"a": 1})
        queue.push({"b": 2})
        queue.purge("pending")
        assert queue.size("pending") == 0

    def test_delayed_job(self, queue):
        queue.push({"task": "later"}, delay_seconds=3600)
        assert queue.pop() is None  # Not available yet

    def test_fail_then_consume_retries_then_dead_letters(self, tmp_path, monkeypatch):
        # A job that fails on every attempt is retried exactly max_retries
        # times via a plain consume loop, then lands in dead_letters — with
        # NO manual retry_failed() call.
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "auto_dl"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="auto", max_retries=3)
        q.push({"task": "always_fails"})

        attempts = 0
        for job in q.consume("auto", poll_interval=0):
            attempts += 1
            job.fail(f"boom {attempts}")

        assert attempts == 3  # executed max_retries times total
        assert q.size("pending") == 0
        dead = q.dead_letters()
        assert len(dead) == 1
        assert dead[0].attempts == 3
        assert dead[0].payload["task"] == "always_fails"

    def test_retry_failed_revives_dead_letter_under_raised_limit(self, tmp_path, monkeypatch):
        # retry_failed() re-queues dead-letter jobs that are under the limit.
        # With the original max_retries they have exhausted retries, so a
        # raised limit is needed to give them another chance.
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "revive"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="revive", max_retries=1)
        q.push({"task": "fail_me"})
        job = q.pop()
        job.fail("error")  # attempts=1 >= max_retries=1 → dead-lettered
        assert len(q.dead_letters()) == 1
        assert q.size("pending") == 0

        # At the original limit, nothing is revived
        assert q.retry_failed() == 0
        # Raise the limit → the dead-letter is re-queued to pending
        count = q.retry_failed(max_retries=5)
        assert count == 1
        assert q.size("pending") == 1

    def test_dead_letters(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "dead_queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="dead", max_retries=1)
        q.push({"task": "doomed"})
        job = q.pop()
        job.fail("err1")
        # Attempts = 1 which equals max_retries = 1 → dead letter
        # dead_letters() returns list[Job] (was list[dict] in 3.12.x)
        dead = q.dead_letters()
        assert len(dead) == 1
        from tina4_python.queue.job import Job
        assert isinstance(dead[0], Job)
        assert dead[0].payload["task"] == "doomed"

    def test_failed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "failed_queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="ftopic", max_retries=3)
        q.push({"task": "will_fail"})
        job = q.pop()
        job.fail("first error")
        # attempts=1, max_retries=3 → still retryable → shows in failed()
        failed = q.failed()
        assert len(failed) == 1
        assert failed[0]["data"]["task"] == "will_fail"
        # Should NOT appear in dead_letters yet
        assert len(q.dead_letters()) == 0

    def test_retry_by_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "retry_id_queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        # max_retries=1 so a single failure dead-letters the job, making it
        # addressable by id for an explicit retry.
        q = Queue(topic="rtopic", max_retries=1)
        q.push({"task": "retry_me"})
        job = q.pop()
        job.fail("oops")  # attempts=1 >= 1 → dead-lettered
        job_id = job.id
        assert len(q.dead_letters()) == 1
        # Explicit retry by ID revives the dead-letter into pending
        assert q.retry(job_id) is True
        assert q.size("pending") == 1
        # Non-existent ID returns False
        assert q.retry("no-such-id") is False

    def test_clear(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "clear_queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="ctopic")
        q.push({"task": "a"})
        q.push({"task": "b"})
        q.push({"task": "c"})
        assert q.size("pending") == 3
        removed = q.clear()
        assert removed == 3
        assert q.size("pending") == 0

    def test_push_creates_queue_data_file(self, queue):
        queue.push({"task": "test"})
        queue_dir = os.path.join(os.environ["TINA4_QUEUE_PATH"], "test")
        files = [f for f in os.listdir(queue_dir) if f.endswith(".queue-data")]
        assert len(files) == 1
        with open(os.path.join(queue_dir, files[0])) as f:
            data = json.load(f)
        assert data["data"]["task"] == "test"
        assert data["status"] == "pending"
        assert "id" in data

    def test_pop_deletes_file(self, queue):
        queue.push({"task": "claim"})
        queue_dir = os.path.join(os.environ["TINA4_QUEUE_PATH"], "test")
        assert len([f for f in os.listdir(queue_dir) if f.endswith(".queue-data")]) == 1
        queue.pop()
        assert len([f for f in os.listdir(queue_dir) if f.endswith(".queue-data")]) == 0

    def test_custom_queue_path(self, tmp_path, monkeypatch):
        custom = str(tmp_path / "custom" / "queues")
        monkeypatch.setenv("TINA4_QUEUE_PATH", custom)
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="custom_topic")
        q.push({"path": "custom"})
        assert os.path.isdir(os.path.join(custom, "custom_topic"))
        assert q.size() == 1


class TestBackendSwitching:
    """Tests for backend auto-detection."""

    def test_env_default_file(self, tmp_path, monkeypatch):
        """When TINA4_QUEUE_BACKEND is not set, defaults to file."""
        monkeypatch.delenv("TINA4_QUEUE_BACKEND", raising=False)
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "auto_queue"))
        q = Queue(topic="auto_test")
        q.push({"task": "auto"})
        assert q.size() == 1
        job = q.pop()
        assert job is not None
        assert job.data["task"] == "auto"

    def test_env_explicit_file(self, tmp_path, monkeypatch):
        """TINA4_QUEUE_BACKEND=file uses file backend."""
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "explicit_queue"))
        q = Queue(topic="explicit_test")
        q.push({"task": "explicit"})
        assert q.size() == 1

    def test_explicit_backend_arg(self, tmp_path, monkeypatch):
        """Queue(topic='x', backend='file') overrides env."""
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "kafka")  # would fail
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "override_queue"))
        q = Queue(topic="override_test", backend="file")
        q.push({"task": "override"})
        assert q.size() == 1

    def test_invalid_backend_raises(self):
        """Unknown backend should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown queue backend"):
            Queue(topic="bad", backend="redis")

    def test_job_complete_via_adapter(self, tmp_path, monkeypatch):
        """Job.complete() delegates through the backend adapter."""
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "complete_queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="adapter_complete")
        q.push({"task": "finish"})
        job = q.pop()
        job.complete()
        assert q.size("pending") == 0

    def test_job_fail_via_adapter(self, tmp_path, monkeypatch):
        """Job.fail() delegates through the backend adapter — once retries are
        exhausted (max_retries=1) the job is written to the dead-letter dir."""
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "fail_queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="adapter_fail", max_retries=1)
        q.push({"task": "break"})
        job = q.pop()
        job.fail("oops")  # attempts=1 >= max_retries=1 → dead-letter
        failed_dir = os.path.join(str(tmp_path / "fail_queue"), "adapter_fail", "failed")
        failed_files = [f for f in os.listdir(failed_dir) if f.endswith(".queue-data")]
        assert len(failed_files) == 1

    def test_job_retry_via_adapter(self, tmp_path, monkeypatch):
        """Job.retry() delegates through the backend adapter."""
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "retry_queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="adapter_retry")
        q.push({"task": "again"})
        job = q.pop()
        job.retry()
        assert q.size("pending") == 1
        retried = q.pop()
        assert retried.attempts == 1

    def test_full_lifecycle(self, tmp_path, monkeypatch):
        """Full push/pop/complete/fail lifecycle.

        fail() auto-requeues while retries remain, so the failed job is back
        in pending without any manual retry_failed() call.
        """
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "lifecycle_queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="lifecycle", max_retries=3)

        # Push
        q.push({"step": 1})
        q.push({"step": 2})
        assert q.size() == 2

        # Pop and complete (terminal)
        job1 = q.pop()
        job1.complete()
        assert q.size("pending") == 1

        # Pop and fail — auto re-enqueued (attempts=1 < 3)
        job2 = q.pop()
        assert q.size("pending") == 0
        job2.fail("error")
        assert q.size("pending") == 1

        # The requeued job carries the incremented attempt count
        requeued = q.pop()
        assert requeued.attempts == 1


class TestProduceConsume:
    """Tests for produce/consume/reject API."""

    def test_consume_yields_all_jobs(self, queue):
        """consume() yields all pending jobs as a generator."""
        queue.push({"order": 1})
        queue.push({"order": 2})
        queue.push({"order": 3})

        results = []
        for job in queue.consume(poll_interval=0):
            results.append(job.data["order"])
            job.complete()

        assert results == [1, 2, 3]

    def test_consume_empty_queue(self, queue):
        """consume() on empty queue yields nothing."""
        jobs = list(queue.consume(poll_interval=0))
        assert jobs == []

    def test_consume_by_id(self, tmp_path, monkeypatch):
        """consume(topic, job_id=X) yields only that specific job."""
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "targeted_queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="targeted")
        id1 = q.push({"task": "first"})
        id2 = q.push({"task": "second"})
        id3 = q.push({"task": "third"})

        # Consume only the second job
        jobs = list(q.consume("targeted", job_id=str(id2), poll_interval=0))
        assert len(jobs) == 1
        assert jobs[0].data["task"] == "second"

        # The other two are still pending
        assert q.size("pending") == 2

    def test_reject_with_reason(self, tmp_path, monkeypatch):
        """reject(reason) is an alias for fail(): with retries exhausted
        (max_retries=1) the job is dead-lettered carrying the reason."""
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "reject_queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="reject_test", max_retries=1)
        q.push({"task": "bad_data"})
        job = q.pop()
        job.reject("Invalid email address")
        failed_dir = os.path.join(str(tmp_path / "reject_queue"), "reject_test", "failed")
        failed_files = [f for f in os.listdir(failed_dir) if f.endswith(".queue-data")]
        assert len(failed_files) == 1
        dead = q.dead_letters()
        assert len(dead) == 1
        assert dead[0].error == "Invalid email address"

    def test_email_failure_scenario(self, tmp_path, monkeypatch):
        """Simulate: queue email, SMTP fails, job gets failed with reason."""
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "email_queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="emails", max_retries=3)

        q.push({"to": "user@example.com", "subject": "Welcome"})

        for job in q.consume("emails", poll_interval=0):
            try:
                raise ConnectionError("Connection refused: smtp.example.com:587")
            except ConnectionError as e:
                job.fail(str(e))

        failed_dir = os.path.join(str(tmp_path / "email_queue"), "emails", "failed")
        failed_files = [f for f in os.listdir(failed_dir) if f.endswith(".queue-data")]
        assert len(failed_files) == 1

    def test_email_retry_then_dead_letter(self, tmp_path, monkeypatch):
        """Email fails on every attempt → retried automatically up to
        max_retries, then dead-lettered. No manual retry_failed() needed."""
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "retry_queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="emails", max_retries=2)
        q.push({"to": "user@example.com", "subject": "Welcome"})

        # Attempt 1: fail → auto re-enqueued (attempts=1 < 2)
        job = q.pop()
        job.fail("SMTP timeout attempt 1")
        assert q.size("pending") == 1
        assert len(q.dead_letters()) == 0

        # Attempt 2: fail again → attempts=2 == max_retries → dead-lettered
        job = q.pop()
        assert job.attempts == 1  # carries prior failure count
        job.fail("SMTP timeout attempt 2")

        # Nothing left pending; the job is now a dead letter
        assert q.size("pending") == 0
        dead = q.dead_letters()
        assert len(dead) == 1
        assert dead[0].attempts == 2
        assert dead[0].error == "SMTP timeout attempt 2"

    def test_consume_complete_happy_path(self, tmp_path, monkeypatch):
        """Simulate: queue email, send succeeds, job completed."""
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "happy_queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="emails")
        q.push({"to": "alice@test.com", "subject": "Hello"})

        for job in q.consume("emails", poll_interval=0):
            job.complete()

        assert q.size("pending") == 0


class TestAutoRetryDeadLetter:
    """The documented promise: a consume loop that calls job.fail() on error
    retries up to max_retries, then dead-letters — with no manual
    retry_failed()."""

    def test_persistent_failure_retried_exactly_max_retries_then_dead_letter(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "auto"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="work", max_retries=3)
        q.push({"job": "doomed"})

        executions = 0
        # poll_interval=0 → single-pass drain that also re-drains re-enqueued
        # jobs, so the whole retry sequence runs in one for-loop.
        for job in q.consume("work", poll_interval=0):
            executions += 1
            try:
                raise RuntimeError("always fails")
            except RuntimeError as exc:
                job.fail(str(exc))

        # Executed exactly max_retries times total, then stopped (dead-lettered)
        assert executions == 3
        assert q.size("pending") == 0
        dead = q.dead_letters()
        assert len(dead) == 1
        assert dead[0].attempts == 3
        assert dead[0].payload["job"] == "doomed"
        assert dead[0].error == "always fails"

    def test_success_on_second_attempt_is_not_dead_lettered(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "flaky"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="flaky", max_retries=3)
        q.push({"job": "flaky"})

        executions = 0
        for job in q.consume("flaky", poll_interval=0):
            executions += 1
            if executions == 1:
                job.fail("transient error")   # re-enqueued
            else:
                job.complete()                 # succeeds on 2nd attempt
                break

        assert executions == 2
        assert q.size("pending") == 0
        assert len(q.dead_letters()) == 0

    def test_no_manual_retry_failed_needed(self, tmp_path, monkeypatch):
        # Prove retry_failed() is never called and the job still dead-letters.
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "nomanual"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="nomanual", max_retries=2)
        q.push({"job": "x"})
        for job in q.consume("nomanual", poll_interval=0):
            job.fail("boom")
        assert len(q.dead_letters()) == 1

    def test_retry_backoff_delays_reattempt(self, tmp_path, monkeypatch):
        # With a backoff, a failed job is re-enqueued but not immediately
        # available, so an immediate pop() returns None.
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "backoff"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="backoff", max_retries=3, retry_backoff=3600)
        q.push({"job": "slow_retry"})
        job = q.pop()
        job.fail("needs backoff")
        # Re-enqueued (still pending) but delayed → not yet poppable
        assert q.size("pending") == 1
        assert q.pop() is None


# --- batch tests ---

def test_pop_batch_returns_list(tmp_path, monkeypatch):
    monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path))
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
    queue = Queue(topic="batch_test")
    queue.push({"n": 1})
    queue.push({"n": 2})
    queue.push({"n": 3})
    jobs = queue.pop_batch(2)
    assert isinstance(jobs, list)
    assert len(jobs) == 2


def test_pop_batch_partial(tmp_path, monkeypatch):
    """Returns fewer than requested when queue has less."""
    monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path))
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
    queue = Queue(topic="batch_partial")
    queue.push({"n": 1})
    jobs = queue.pop_batch(10)
    assert len(jobs) == 1


def test_pop_batch_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path))
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
    queue = Queue(topic="batch_empty")
    jobs = queue.pop_batch(5)
    assert jobs == []


def test_consume_batch_size(tmp_path, monkeypatch):
    monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path))
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
    queue = Queue(topic="batch_consume")
    for i in range(5):
        queue.push({"n": i})
    batches = []
    for jobs in queue.consume(batch_size=2, poll_interval=0):
        batches.append(jobs)
        for job in jobs:
            job.complete()
    # 5 jobs, batch_size=2 → batches of [2, 2, 1]
    assert sum(len(b) for b in batches) == 5
    assert all(isinstance(b, list) for b in batches)


def test_process_batch_size(tmp_path, monkeypatch):
    monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path))
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
    queue = Queue(topic="batch_process")
    for i in range(6):
        queue.push({"n": i})
    received = []

    def handler(jobs):
        for job in jobs:
            received.append(job.data["n"])
            job.complete()

    queue.process(handler, batch_size=3)
    assert len(received) == 6


class TestQueueIsolation:
    """Contract: queues are isolated by topic and by storage path.

    A job pushed to one topic must never leak into another topic, and a queue
    pointed at a fresh storage path must start empty. Locks in the per-topic
    directory layout so a future backend change can't silently cross-contaminate.
    """

    def test_topics_are_isolated_same_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        topic_a = Queue(topic="topic_a")
        topic_b = Queue(topic="topic_b")

        topic_a.push({"to": "a"})
        topic_a.push({"to": "a2"})

        # topic_b shares the base path but must see none of topic_a's jobs.
        assert topic_b.size() == 0
        assert topic_b.pop() is None
        assert topic_a.size() == 2

    def test_draining_one_topic_leaves_the_other_intact(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        topic_a = Queue(topic="topic_a")
        topic_b = Queue(topic="topic_b")
        topic_a.push({"to": "a"})
        topic_b.push({"to": "b"})

        # Drain topic_a completely.
        assert topic_a.pop().data["to"] == "a"
        assert topic_a.pop() is None

        # topic_b is untouched.
        assert topic_b.size() == 1
        assert topic_b.pop().data["to"] == "b"

    def test_fresh_storage_path_starts_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "queue_one"))
        first = Queue(topic="jobs")
        first.push({"n": 1})
        first.push({"n": 2})
        assert first.size() == 2

        # A second queue on a DIFFERENT base path sees zero jobs.
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "queue_two"))
        second = Queue(topic="jobs")
        assert second.size() == 0
        assert second.pop() is None


class TestVisibilityTimeout:
    """Reservation / visibility timeout contract (file backend).

    Regression lock for the production bug where a consumer that dies before
    job.complete() left the message stuck forever — never re-delivered, never
    retried, never dead-lettered. A popped job is now reserved for
    visibility_timeout seconds; if it is not acked in time the next pop()
    reclaims it (incrementing attempts) or dead-letters it past max_retries.
    """

    def test_reserved_job_reclaimed_after_timeout(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        queue = Queue(topic="vt", visibility_timeout=0.05)

        queue.push({"job": "import"})
        job = queue.pop()                       # consumer A reserves it
        assert job is not None
        assert job.attempts == 0
        assert queue.size("pending") == 0       # claimed out of pending
        assert queue.size("reserved") == 1      # held as a reservation

        # Consumer A "dies" — never calls complete()/fail(). After the window
        # expires the next pop() reclaims the abandoned reservation.
        time.sleep(0.12)
        reclaimed = queue.pop()
        assert reclaimed is not None
        assert reclaimed.data["job"] == "import"
        assert reclaimed.attempts == 1          # reclaim counted as one attempt

    def test_reserved_job_not_reclaimed_before_timeout(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        queue = Queue(topic="vt", visibility_timeout=30)

        queue.push({"job": "import"})
        assert queue.pop() is not None          # reserved
        # The reservation is still valid — a second consumer must NOT get it.
        assert queue.pop() is None
        assert queue.size("reserved") == 1

    def test_reclaim_dead_letters_after_max_retries(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        queue = Queue(topic="vt", max_retries=1, visibility_timeout=0.05)

        queue.push({"job": "import"})
        assert queue.pop() is not None          # reserve (attempts 0)
        time.sleep(0.12)
        # Reclaim bumps attempts to 1 (>= max_retries) -> dead-letter, not re-served.
        assert queue.pop() is None
        assert queue.size("reserved") == 0
        dead = queue.dead_letters()
        assert len(dead) == 1
        assert dead[0].data["job"] == "import"

    def test_complete_removes_reservation_no_reclaim(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        queue = Queue(topic="vt", visibility_timeout=0.05)

        queue.push({"job": "import"})
        job = queue.pop()
        job.complete()                          # acked — reservation cleared
        assert queue.size("reserved") == 0
        time.sleep(0.12)
        assert queue.pop() is None              # nothing to reclaim

    def test_fail_removes_reservation(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        queue = Queue(topic="vt", max_retries=3, visibility_timeout=0.05)

        queue.push({"job": "import"})
        job = queue.pop()
        job.fail("boom")                        # acked with failure -> requeued
        assert queue.size("reserved") == 0      # reservation cleared by fail()
        # The requeued job is pending again with attempts incremented.
        retried = queue.pop()
        assert retried is not None and retried.attempts == 1

    def test_default_visibility_timeout_is_300(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "queue"))
        monkeypatch.delenv("TINA4_QUEUE_VISIBILITY_TIMEOUT", raising=False)
        assert Queue(topic="vt").visibility_timeout == 300.0

    def test_visibility_timeout_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "queue"))
        monkeypatch.setenv("TINA4_QUEUE_VISIBILITY_TIMEOUT", "42")
        assert Queue(topic="vt").visibility_timeout == 42.0

    def test_zero_visibility_timeout_disables_reclaim(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        queue = Queue(topic="vt", visibility_timeout=0)

        queue.push({"job": "import"})
        assert queue.pop() is not None
        time.sleep(0.05)
        # Reclaim is disabled — the reservation stays put (opt-out / old behaviour).
        assert queue.pop() is None
        assert queue.size("reserved") == 1


class TestConsumeTopicTargeting:
    """consume()/process()/produce() must honor an explicit topic argument.

    Regression: consume(topic) used to be ignored on the read path — pop()
    drained the construction-time topic, so consuming a topic the queue was
    not constructed with silently yielded nothing. Engine-agnostic (file
    backend), so it guards every backend.
    """

    def _q(self, tmp_path, monkeypatch, topic="default"):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "qtt"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        return Queue(topic=topic)

    def test_consume_uses_argument_topic_not_construction_topic(self, tmp_path, monkeypatch):
        q = self._q(tmp_path, monkeypatch, topic="default")
        q.push({"where": "default"})              # lands on 'default'
        q.produce("alerts", {"where": "alerts"})  # lands on 'alerts'

        drained = []
        for job in q.consume("alerts", poll_interval=0):
            drained.append(job.data)
            job.complete()
        assert drained == [{"where": "alerts"}]   # only alerts, not the default job

        leftover = []
        for job in q.consume("default", poll_interval=0):
            leftover.append(job.data)
            job.complete()
        assert leftover == [{"where": "default"}]  # the default job was untouched

    def test_consume_with_no_topic_uses_construction_topic(self, tmp_path, monkeypatch):
        q = self._q(tmp_path, monkeypatch, topic="orders")
        q.push({"id": 1})
        drained = [job.data for job in q.consume(poll_interval=0) if job.complete() is None]
        assert drained == [{"id": 1}]

    def test_process_targets_requested_topic(self, tmp_path, monkeypatch):
        q = self._q(tmp_path, monkeypatch, topic="default")
        q.produce("work", {"v": 1})
        q.produce("work", {"v": 2})
        seen = []

        def handler(job):
            seen.append(job.data)
            job.complete()

        q.process(handler, topic="work")
        assert [s["v"] for s in seen] == [1, 2]

    def test_topic_isolation_drain_one_leaves_other(self, tmp_path, monkeypatch):
        q = self._q(tmp_path, monkeypatch, topic="default")
        for i in range(3):
            q.produce("orders", {"k": "order", "i": i})
        for i in range(2):
            q.produce("emails", {"k": "email", "i": i})

        drained = []
        for job in q.consume("orders", poll_interval=0):
            drained.append(job.data)
            job.complete()
        assert len(drained) == 3
        assert all(d["k"] == "order" for d in drained)

        remaining = [job.data for job in q.consume("emails", poll_interval=0) if job.complete() is None]
        assert len(remaining) == 2
        assert all(d["k"] == "email" for d in remaining)

    def test_explicit_backend_survives_retarget(self, tmp_path, monkeypatch):
        # produce()/consume() retargeting must reuse the explicit backend= choice,
        # not silently fall back to the TINA4_QUEUE_BACKEND env value.
        from tina4_python.queue.lite_backend import LiteBackend
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "x"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "rabbitmq")   # env says rabbitmq
        q = Queue(topic="default", backend="file")              # explicit file wins
        q.produce("t", {"n": 1})                                # retargets to 't' then back
        assert isinstance(q._backend, LiteBackend)
        for job in q.consume("t", poll_interval=0):             # retargets to 't'
            job.complete()
        assert isinstance(q._backend, LiteBackend)              # still file, never rabbitmq
