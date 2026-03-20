# Tina4 Queue — Database-backed job queue, zero dependencies.
"""
Production-grade queue using the connected database as storage.
No Redis, no RabbitMQ, no external dependencies needed.

    from tina4_python.queue import Queue, Producer, Consumer

    queue = Queue(db, topic="emails")
    Producer(queue).push({"to": "alice@test.com", "subject": "Hello"})

    for job in Consumer(queue).poll():
        send_email(job.data)
        job.complete()
"""
import json
import time
import threading
from datetime import datetime, timezone


class Job:
    """A single queue job."""

    def __init__(self, queue, job_id: int, topic: str, data: dict,
                 priority: int = 0, attempts: int = 0):
        self.queue = queue
        self.id = job_id
        self.topic = topic
        self.data = data
        self.priority = priority
        self.attempts = attempts

    def complete(self):
        """Mark job as completed."""
        self.queue._db.execute(
            "UPDATE tina4_queue SET status = 'completed', completed_at = ? WHERE id = ?",
            [_now(), self.id],
        )
        self.queue._db.commit()

    def fail(self, error: str = ""):
        """Mark job as failed. Will be retried if attempts < max_retries."""
        self.queue._db.execute(
            "UPDATE tina4_queue SET status = 'failed', error = ?, attempts = attempts + 1 WHERE id = ?",
            [error, self.id],
        )
        self.queue._db.commit()

    def retry(self, delay_seconds: int = 0):
        """Re-queue this job with optional delay."""
        available_at = _now() if delay_seconds == 0 else _future(delay_seconds)
        self.queue._db.execute(
            "UPDATE tina4_queue SET status = 'pending', available_at = ?, attempts = attempts + 1 WHERE id = ?",
            [available_at, self.id],
        )
        self.queue._db.commit()


class Queue:
    """Database-backed job queue.

    Creates a tina4_queue table automatically.
    Supports priority, delayed jobs, retry, and dead letter.
    """

    def __init__(self, db, topic: str = "default", max_retries: int = 3):
        self._db = db
        self.topic = topic
        self.max_retries = max_retries
        self._ensure_table()

    def _ensure_table(self):
        if not self._db.table_exists("tina4_queue"):
            self._db.execute("""
                CREATE TABLE tina4_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    data TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    priority INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    available_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    reserved_at TEXT
                )
            """)
            self._db.commit()

    def push(self, data: dict, priority: int = 0, delay_seconds: int = 0) -> int:
        """Add a job to the queue. Returns job ID."""
        available = _now() if delay_seconds == 0 else _future(delay_seconds)
        result = self._db.execute(
            "INSERT INTO tina4_queue (topic, data, priority, available_at, created_at) VALUES (?, ?, ?, ?, ?)",
            [self.topic, json.dumps(data, default=str), priority, available, _now()],
        )
        self._db.commit()
        return result.last_id

    def pop(self) -> Job | None:
        """Atomically claim the next available job. Returns None if empty."""
        now = _now()
        # Get highest-priority pending job
        row = self._db.fetch_one(
            "SELECT * FROM tina4_queue WHERE topic = ? AND status = 'pending' AND available_at <= ? "
            "ORDER BY priority DESC, id ASC",
            [self.topic, now],
        )
        if not row:
            return None

        # Reserve it (atomic via UPDATE with status check)
        result = self._db.execute(
            "UPDATE tina4_queue SET status = 'reserved', reserved_at = ? WHERE id = ? AND status = 'pending'",
            [now, row["id"]],
        )
        self._db.commit()

        if result.affected_rows == 0:
            return None  # Another worker got it

        return Job(
            queue=self,
            job_id=row["id"],
            topic=row["topic"],
            data=json.loads(row["data"]),
            priority=row["priority"],
            attempts=row["attempts"],
        )

    def size(self, status: str = "pending") -> int:
        """Count jobs by status."""
        row = self._db.fetch_one(
            "SELECT COUNT(*) as cnt FROM tina4_queue WHERE topic = ? AND status = ?",
            [self.topic, status],
        )
        return row["cnt"] if row else 0

    def purge(self, status: str = "completed"):
        """Remove all jobs with the given status."""
        self._db.execute(
            "DELETE FROM tina4_queue WHERE topic = ? AND status = ?",
            [self.topic, status],
        )
        self._db.commit()

    def retry_failed(self) -> int:
        """Re-queue failed jobs that haven't exceeded max_retries."""
        now = _now()
        result = self._db.execute(
            "UPDATE tina4_queue SET status = 'pending', available_at = ? "
            "WHERE topic = ? AND status = 'failed' AND attempts < ?",
            [now, self.topic, self.max_retries],
        )
        self._db.commit()
        return result.affected_rows

    def dead_letters(self) -> list[dict]:
        """Get jobs that exceeded max retries."""
        result = self._db.fetch(
            "SELECT * FROM tina4_queue WHERE topic = ? AND status = 'failed' AND attempts >= ?",
            [self.topic, self.max_retries],
            limit=1000,
        )
        return result.records


class Producer:
    """Convenience wrapper for pushing jobs."""

    def __init__(self, queue: Queue):
        self._queue = queue

    def push(self, data: dict, priority: int = 0, delay_seconds: int = 0) -> int:
        return self._queue.push(data, priority, delay_seconds)


class Consumer:
    """Job consumer — polls the queue and processes jobs."""

    def __init__(self, queue: Queue, callback: callable = None,
                 poll_interval: float = 1.0):
        self._queue = queue
        self._callback = callback
        self._poll_interval = poll_interval
        self._running = False

    def poll(self) -> list[Job]:
        """Poll once and return all available jobs."""
        jobs = []
        while True:
            job = self._queue.pop()
            if job is None:
                break
            jobs.append(job)
        return jobs

    def run(self, max_jobs: int = None):
        """Process jobs until queue is empty or max_jobs reached."""
        if not self._callback:
            raise ValueError("No callback set — pass callback to Consumer()")
        processed = 0
        while max_jobs is None or processed < max_jobs:
            job = self._queue.pop()
            if job is None:
                break
            try:
                self._callback(job)
                job.complete()
            except Exception as e:
                job.fail(str(e))
            processed += 1
        return processed

    def run_forever(self):
        """Poll continuously (blocking). Call stop() from another thread."""
        if not self._callback:
            raise ValueError("No callback set — pass callback to Consumer()")
        self._running = True
        while self._running:
            job = self._queue.pop()
            if job is None:
                time.sleep(self._poll_interval)
                continue
            try:
                self._callback(job)
                job.complete()
            except Exception as e:
                job.fail(str(e))

    def stop(self):
        """Stop the consumer loop."""
        self._running = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future(seconds: int) -> str:
    return datetime.fromtimestamp(
        time.time() + seconds, tz=timezone.utc
    ).isoformat()


__all__ = ["Queue", "Producer", "Consumer", "Job"]
