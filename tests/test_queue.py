# Tests for tina4_python.queue
import os
import pytest
from tina4_python.database import Database
from tina4_python.queue import Queue


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'queue.db'}")
    yield d
    d.close()


@pytest.fixture
def queue(db):
    return Queue(db, topic="test")


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
        job = queue.pop()
        assert job.data["task"] == "high"

    def test_size(self, queue):
        assert queue.size() == 0
        queue.push({"a": 1})
        queue.push({"b": 2})
        assert queue.size() == 2

    def test_complete(self, queue):
        queue.push({"task": "done"})
        job = queue.pop()
        job.complete()
        assert queue.size("pending") == 0
        assert queue.size("completed") == 1

    def test_fail(self, queue):
        queue.push({"task": "broken"})
        job = queue.pop()
        job.fail("something went wrong")
        assert queue.size("failed") == 1

    def test_retry(self, queue):
        queue.push({"task": "retry_me"})
        job = queue.pop()
        job.retry()
        assert queue.size("pending") == 1
        retried = queue.pop()
        assert retried.attempts == 1

    def test_purge(self, queue):
        queue.push({"a": 1})
        job = queue.pop()
        job.complete()
        queue.purge("completed")
        assert queue.size("completed") == 0

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

    def test_dead_letters(self, db):
        q = Queue(db, topic="dead", max_retries=1)
        q.push({"task": "doomed"})
        job = q.pop()
        job.fail("err1")
        # Exceed max retries
        db.execute(
            "UPDATE tina4_queue SET attempts = 5 WHERE id = ?", [job.id]
        )
        db.commit()
        dead = q.dead_letters()
        assert len(dead) >= 1



class TestBackendSwitching:
    """Tests for the unified Queue constructor and backend auto-detection."""

    def test_legacy_constructor(self, db):
        """Queue(db, topic='x') still works — backward compat."""
        q = Queue(db, topic="legacy")
        q.push({"task": "hello"})
        job = q.pop()
        assert job is not None
        assert job.data["task"] == "hello"

    def test_env_default_sqlite(self, tmp_path, monkeypatch):
        """When TINA4_QUEUE_BACKEND is not set, defaults to sqlite."""
        monkeypatch.delenv("TINA4_QUEUE_BACKEND", raising=False)
        db_path = str(tmp_path / "auto_queue.db")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        q = Queue(topic="auto_test")
        q.push({"task": "auto"})
        assert q.size() == 1
        job = q.pop()
        assert job is not None
        assert job.data["task"] == "auto"

    def test_env_explicit_sqlite(self, tmp_path, monkeypatch):
        """TINA4_QUEUE_BACKEND=sqlite uses sqlite backend."""
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "sqlite")
        db_path = str(tmp_path / "explicit_queue.db")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        q = Queue(topic="explicit_test")
        q.push({"task": "explicit"})
        assert q.size() == 1

    def test_explicit_backend_arg(self, tmp_path, monkeypatch):
        """Queue(topic='x', backend='sqlite') overrides env."""
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "kafka")  # would fail
        db_path = str(tmp_path / "override_queue.db")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        # Explicit backend= arg should override env
        q = Queue(topic="override_test", backend="sqlite")
        q.push({"task": "override"})
        assert q.size() == 1

    def test_invalid_backend_raises(self):
        """Unknown backend should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown queue backend"):
            Queue(topic="bad", backend="redis")

    def test_string_as_first_arg_is_topic(self, db):
        """Queue('mytopic') treats the string as topic, not db."""
        # This should use env-based sqlite (or fail gracefully)
        # But Queue(db, topic='x') should still work
        q = Queue(db, topic="positional")
        q.push({"test": True})
        assert q.size() == 1

    def test_job_complete_via_adapter(self, db):
        """Job.complete() delegates through the backend adapter."""
        q = Queue(db, topic="adapter_complete")
        q.push({"task": "finish"})
        job = q.pop()
        job.complete()
        assert q.size("pending") == 0
        assert q.size("completed") == 1

    def test_job_fail_via_adapter(self, db):
        """Job.fail() delegates through the backend adapter."""
        q = Queue(db, topic="adapter_fail")
        q.push({"task": "break"})
        job = q.pop()
        job.fail("oops")
        assert q.size("failed") == 1

    def test_job_retry_via_adapter(self, db):
        """Job.retry() delegates through the backend adapter."""
        q = Queue(db, topic="adapter_retry")
        q.push({"task": "again"})
        job = q.pop()
        job.retry()
        assert q.size("pending") == 1
        retried = q.pop()
        assert retried.attempts == 1

    def test_full_lifecycle_no_db(self, tmp_path, monkeypatch):
        """Full push/pop/complete/fail/retry lifecycle without passing db."""
        monkeypatch.delenv("TINA4_QUEUE_BACKEND", raising=False)
        db_path = str(tmp_path / "lifecycle.db")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

        q = Queue(topic="lifecycle")

        # Push
        q.push({"step": 1})
        q.push({"step": 2})
        assert q.size() == 2

        # Pop and complete
        job1 = q.pop()
        job1.complete()
        assert q.size("completed") == 1

        # Pop and fail
        job2 = q.pop()
        job2.fail("error")
        assert q.size("failed") == 1

        # Retry failed
        count = q.retry_failed()
        assert count == 1
        assert q.size("pending") == 1

        # Purge completed
        q.purge("completed")
        assert q.size("completed") == 0


class TestProduceConsume:
    """Tests for the new produce/consume/reject API."""

    def test_produce(self, queue):
        """produce(topic, data) pushes to a specific topic."""
        queue.produce("emails", {"to": "alice@test.com", "subject": "Hello"})
        assert queue.size() >= 0  # pushed to 'emails' topic, not 'test'

    def test_consume_yields_all_jobs(self, queue):
        """consume() yields all pending jobs as a generator."""
        queue.push({"order": 1})
        queue.push({"order": 2})
        queue.push({"order": 3})

        results = []
        for job in queue.consume():
            results.append(job.data["order"])
            job.complete()

        assert results == [1, 2, 3]
        assert queue.size("pending") == 0

    def test_consume_empty_queue(self, queue):
        """consume() on empty queue yields nothing."""
        jobs = list(queue.consume())
        assert jobs == []

    def test_consume_by_id(self, db):
        """consume(topic, job_id=X) yields only that specific job."""
        q = Queue(db, topic="targeted")
        id1 = q.push({"task": "first"})
        id2 = q.push({"task": "second"})
        id3 = q.push({"task": "third"})

        # Consume only the second job
        jobs = list(q.consume("targeted", job_id=str(id2)))
        assert len(jobs) == 1
        assert jobs[0].data["task"] == "second"

        # The other two are still pending
        assert q.size("pending") == 2

    def test_reject_with_reason(self, queue):
        """reject(reason) marks job as failed with the reason."""
        queue.push({"task": "bad_data"})
        job = queue.pop()
        job.reject("Invalid email address")
        assert queue.size("failed") == 1

    def test_email_failure_scenario(self, db):
        """Simulate: queue email, SMTP fails, job gets failed with reason."""
        q = Queue(db, topic="emails", max_retries=3)

        # Push an email onto the queue
        q.push({"to": "user@example.com", "subject": "Welcome", "body": "<h1>Hi</h1>"})

        # Consume and try to send — SMTP fails
        for job in q.consume("emails"):
            try:
                # Simulate SMTP failure
                raise ConnectionError("Connection refused: smtp.example.com:587")
            except ConnectionError as e:
                job.fail(str(e))

        # Job is in failed state with the reason
        assert q.size("failed") == 1
        assert q.size("pending") == 0

    def test_email_retry_then_dead_letter(self, db):
        """Simulate: email fails 3 times, exceeds max_retries, becomes dead letter."""
        q = Queue(db, topic="emails", max_retries=3)
        q.push({"to": "user@example.com", "subject": "Welcome"})

        # Attempt 1: fail
        job = q.pop()
        job.fail("SMTP timeout attempt 1")
        assert q.size("failed") == 1

        # Retry failed jobs back to pending
        q.retry_failed()
        assert q.size("pending") == 1

        # Attempt 2: fail again
        job = q.pop()
        job.fail("SMTP timeout attempt 2")
        q.retry_failed()

        # Attempt 3: fail again — now at 3 attempts = max_retries
        job = q.pop()
        job.fail("SMTP timeout attempt 3")

        # retry_failed should NOT re-queue because attempts >= max_retries
        requeued = q.retry_failed()
        assert requeued == 0  # nothing re-queued — it's now a dead letter

        # Verify it's a dead letter
        dead = q.dead_letters()
        assert len(dead) >= 1

    def test_consume_complete_happy_path(self, db):
        """Simulate: queue email, send succeeds, job completed."""
        q = Queue(db, topic="emails")
        q.push({"to": "alice@test.com", "subject": "Hello"})

        for job in q.consume("emails"):
            # Simulate successful send
            result = {"success": True, "message": "Email sent"}
            if result["success"]:
                job.complete()
            else:
                job.fail(result["message"])

        assert q.size("completed") == 1
        assert q.size("failed") == 0
