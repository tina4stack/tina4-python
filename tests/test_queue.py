# Tests for tina4_python.queue
import os
import pytest
from tina4_python.database import Database
from tina4_python.queue import Queue, Producer, Consumer


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


class TestProducer:
    def test_produce(self, queue):
        p = Producer(queue)
        job_id = p.push({"task": "produced"})
        assert job_id is not None
        assert queue.size() == 1


class TestConsumer:
    def test_poll(self, queue):
        queue.push({"a": 1})
        queue.push({"b": 2})
        c = Consumer(queue)
        jobs = c.poll()
        assert len(jobs) == 2

    def test_run_with_callback(self, queue):
        queue.push({"x": 1})
        queue.push({"x": 2})
        results = []

        def handler(job):
            results.append(job.data["x"])

        c = Consumer(queue, callback=handler)
        processed = c.run()
        assert processed == 2
        assert results == [1, 2]
        assert queue.size("completed") == 2

    def test_run_max_jobs(self, queue):
        for i in range(5):
            queue.push({"i": i})

        c = Consumer(queue, callback=lambda j: None)
        processed = c.run(max_jobs=3)
        assert processed == 3
        assert queue.size("pending") == 2

    def test_callback_failure_marks_failed(self, queue):
        queue.push({"task": "will_fail"})

        def bad_handler(job):
            raise ValueError("boom")

        c = Consumer(queue, callback=bad_handler)
        c.run()
        assert queue.size("failed") == 1


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
