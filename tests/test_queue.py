# Tests for tina4_python.queue
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
