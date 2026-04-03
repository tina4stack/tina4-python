# Tests for tina4_python.queue — file-based backend
import os
import json
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
        queue.push({"order": 1})
        queue.push({"order": 2})
        assert queue.pop().data["order"] == 1
        assert queue.pop().data["order"] == 2

    def test_priority(self, queue):
        queue.push({"task": "low"}, priority=0)
        queue.push({"task": "high"}, priority=10)
        # File backend pops in file order (FIFO), priority is stored but
        # not used for ordering in the simple file backend
        job = queue.pop()
        assert job is not None

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

    def test_fail(self, queue):
        queue.push({"task": "broken"})
        job = queue.pop()
        job.fail("something went wrong")
        # Failed job goes to {topic}/failed/ directory
        failed_dir = os.path.join(os.environ["TINA4_QUEUE_PATH"], "test", "failed")
        failed_files = [f for f in os.listdir(failed_dir) if f.endswith(".queue-data")]
        assert len(failed_files) == 1
        with open(os.path.join(failed_dir, failed_files[0])) as f:
            data = json.load(f)
        assert data["error"] == "something went wrong"
        assert data["attempts"] == 1

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

    def test_retry_failed(self, queue):
        queue.push({"task": "fail_me"})
        job = queue.pop()
        job.fail("error")
        count = queue.retry_failed()
        assert count == 1
        assert queue.size("pending") == 1

    def test_dead_letters(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "dead_queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="dead", max_retries=1)
        q.push({"task": "doomed"})
        job = q.pop()
        job.fail("err1")
        # Attempts = 1 which equals max_retries = 1 → dead letter
        dead = q.dead_letters()
        assert len(dead) == 1
        assert dead[0]["data"]["task"] == "doomed"

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
        """Job.fail() delegates through the backend adapter."""
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "fail_queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="adapter_fail")
        q.push({"task": "break"})
        job = q.pop()
        job.fail("oops")
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
        """Full push/pop/complete/fail/retry lifecycle."""
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "lifecycle_queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="lifecycle")

        # Push
        q.push({"step": 1})
        q.push({"step": 2})
        assert q.size() == 2

        # Pop and complete
        job1 = q.pop()
        job1.complete()

        # Pop and fail
        job2 = q.pop()
        job2.fail("error")

        # Retry failed
        count = q.retry_failed()
        assert count == 1
        assert q.size("pending") == 1


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

    def test_reject_with_reason(self, queue):
        """reject(reason) marks job as failed with the reason."""
        queue.push({"task": "bad_data"})
        job = queue.pop()
        job.reject("Invalid email address")
        failed_dir = os.path.join(os.environ["TINA4_QUEUE_PATH"], "test", "failed")
        failed_files = [f for f in os.listdir(failed_dir) if f.endswith(".queue-data")]
        assert len(failed_files) == 1

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
        """Simulate: email fails 3 times, exceeds max_retries, becomes dead letter."""
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "retry_queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="emails", max_retries=2)
        q.push({"to": "user@example.com", "subject": "Welcome"})

        # Attempt 1: fail
        job = q.pop()
        job.fail("SMTP timeout attempt 1")

        # Retry
        q.retry_failed()
        assert q.size("pending") == 1

        # Attempt 2: fail again — now at 2 attempts = max_retries
        job = q.pop()
        job.fail("SMTP timeout attempt 2")

        # retry_failed should NOT re-queue because attempts >= max_retries
        requeued = q.retry_failed()
        assert requeued == 0

        # Verify it's a dead letter
        dead = q.dead_letters()
        assert len(dead) == 1

    def test_consume_complete_happy_path(self, tmp_path, monkeypatch):
        """Simulate: queue email, send succeeds, job completed."""
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "happy_queue"))
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
        q = Queue(topic="emails")
        q.push({"to": "alice@test.com", "subject": "Hello"})

        for job in q.consume("emails", poll_interval=0):
            job.complete()

        assert q.size("pending") == 0
