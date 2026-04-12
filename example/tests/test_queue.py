"""Test Queue system — demonstrates: push/pop, size tracking, job lifecycle
(complete/fail), and consume generator with poll_interval=0 for single-pass drain.
"""
import pytest
import shutil
import os
from tina4_python.queue import Queue


# Use a dedicated temp directory for queue files so tests don't pollute the store
QUEUE_PATH = os.path.join(os.path.dirname(__file__), "_test_queue_data")


@pytest.fixture(autouse=True)
def clean_queue_dir():
    """Remove test queue data before and after each test."""
    if os.path.exists(QUEUE_PATH):
        shutil.rmtree(QUEUE_PATH)
    os.environ["TINA4_QUEUE_PATH"] = QUEUE_PATH
    yield
    if os.path.exists(QUEUE_PATH):
        shutil.rmtree(QUEUE_PATH)
    os.environ.pop("TINA4_QUEUE_PATH", None)


class TestQueuePushPop:
    def test_push_returns_job_id(self):
        q = Queue(topic="test_push")
        job_id = q.push({"action": "send_email", "to": "alice@test.com"})
        assert job_id is not None

    def test_pop_returns_job(self):
        q = Queue(topic="test_pop")
        q.push({"task": "resize_image"})
        job = q.pop()
        assert job is not None
        assert job.payload["task"] == "resize_image"

    def test_pop_empty_returns_none(self):
        q = Queue(topic="test_empty")
        assert q.pop() is None

    def test_fifo_order(self):
        q = Queue(topic="test_fifo")
        q.push({"seq": 1})
        q.push({"seq": 2})
        first = q.pop()
        second = q.pop()
        assert first.payload["seq"] == 1
        assert second.payload["seq"] == 2


class TestQueueSize:
    def test_size_empty(self):
        q = Queue(topic="test_size_empty")
        assert q.size() == 0

    def test_size_after_push(self):
        q = Queue(topic="test_size_push")
        q.push({"a": 1})
        q.push({"b": 2})
        assert q.size() == 2

    def test_size_after_pop(self):
        q = Queue(topic="test_size_pop")
        q.push({"x": 1})
        q.push({"y": 2})
        q.pop()
        assert q.size() == 1


class TestJobLifecycle:
    def test_complete_marks_done(self):
        q = Queue(topic="test_complete")
        q.push({"order": 42})
        job = q.pop()
        job.complete()
        # After completing, pending size should be 0
        assert q.size("pending") == 0

    def test_fail_marks_failed(self):
        q = Queue(topic="test_fail")
        q.push({"order": 99})
        job = q.pop()
        job.fail("Payment declined")
        # Job should no longer be pending
        assert q.size("pending") == 0

    def test_job_payload_accessible(self):
        q = Queue(topic="test_payload")
        q.push({"product_id": 5, "quantity": 3})
        job = q.pop()
        assert job.payload["product_id"] == 5
        assert job.payload["quantity"] == 3
        job.complete()

    def test_job_to_hash(self):
        q = Queue(topic="test_hash")
        q.push({"info": "test"})
        job = q.pop()
        h = job.to_hash()
        assert "id" in h
        assert "topic" in h
        assert h["payload"]["info"] == "test"
        job.complete()


class TestQueueConsume:
    def test_consume_drains_all_jobs(self):
        q = Queue(topic="test_consume")
        q.push({"n": 1})
        q.push({"n": 2})
        q.push({"n": 3})

        collected = []
        for job in q.consume(poll_interval=0):
            collected.append(job.payload["n"])
            job.complete()

        assert collected == [1, 2, 3]

    def test_consume_empty_queue_returns_immediately(self):
        q = Queue(topic="test_consume_empty")
        collected = []
        for job in q.consume(poll_interval=0):
            collected.append(job)
            job.complete()
        assert collected == []

    def test_consume_with_iterations_limit(self):
        q = Queue(topic="test_iterations")
        for i in range(5):
            q.push({"n": i})

        collected = []
        for job in q.consume(poll_interval=0, iterations=3):
            collected.append(job.payload["n"])
            job.complete()

        assert len(collected) == 3
