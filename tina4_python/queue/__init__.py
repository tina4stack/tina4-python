# Tina4 Queue — Unified job queue with pluggable backends, zero dependencies.
"""
Production-grade queue with auto-detected backends. Switching from SQLite to
RabbitMQ or Kafka is a .env change — no code change needed.

    from tina4_python.queue import Queue, Producer, Consumer

    # Auto-detect backend from TINA4_QUEUE_BACKEND env var (default: sqlite)
    queue = Queue(topic="emails")
    Producer(queue).push({"to": "alice@test.com", "subject": "Hello"})

    for job in Consumer(queue).poll():
        send_email(job.data)
        job.complete()

    # Legacy usage still works:
    queue = Queue(db, topic="emails")

Environment variables:
    TINA4_QUEUE_BACKEND   — 'sqlite' (default), 'rabbitmq', or 'kafka'
    TINA4_QUEUE_URL       — connection URL for rabbitmq/kafka
    TINA4_RABBITMQ_HOST   — RabbitMQ host (default: localhost)
    TINA4_KAFKA_BROKERS   — Kafka brokers (default: localhost:9092)
    DATABASE_URL          — used by sqlite backend when no db passed
"""
import json
import os
import time
import threading
from datetime import datetime, timezone


class Job:
    """A single queue job."""

    def __init__(self, queue, job_id, topic: str, data: dict,
                 priority: int = 0, attempts: int = 0):
        self.queue = queue
        self.id = job_id
        self.topic = topic
        self.data = data
        self.priority = priority
        self.attempts = attempts

    def complete(self):
        """Mark job as completed."""
        self.queue._backend.complete(self)

    def fail(self, error: str = ""):
        """Mark job as failed. Will be retried if attempts < max_retries."""
        self.queue._backend.fail(self, error)

    def retry(self, delay_seconds: int = 0):
        """Re-queue this job with optional delay."""
        self.queue._backend.retry(self, delay_seconds)


class _SqliteAdapter:
    """Backend adapter wrapping the database for the unified Queue API."""

    def __init__(self, db, topic: str, max_retries: int):
        self._db = db
        self._topic = topic
        self._max_retries = max_retries
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
        available = _now() if delay_seconds == 0 else _future(delay_seconds)
        result = self._db.execute(
            "INSERT INTO tina4_queue (topic, data, priority, available_at, created_at) VALUES (?, ?, ?, ?, ?)",
            [self._topic, json.dumps(data, default=str), priority, available, _now()],
        )
        self._db.commit()
        return result.last_id

    def pop(self, queue_ref) -> Job | None:
        now = _now()
        row = self._db.fetch_one(
            "SELECT * FROM tina4_queue WHERE topic = ? AND status = 'pending' AND available_at <= ? "
            "ORDER BY priority DESC, id ASC",
            [self._topic, now],
        )
        if not row:
            return None

        result = self._db.execute(
            "UPDATE tina4_queue SET status = 'reserved', reserved_at = ? WHERE id = ? AND status = 'pending'",
            [now, row["id"]],
        )
        self._db.commit()

        if result.affected_rows == 0:
            return None

        return Job(
            queue=queue_ref,
            job_id=row["id"],
            topic=row["topic"],
            data=json.loads(row["data"]),
            priority=row["priority"],
            attempts=row["attempts"],
        )

    def size(self, status: str = "pending") -> int:
        row = self._db.fetch_one(
            "SELECT COUNT(*) as cnt FROM tina4_queue WHERE topic = ? AND status = ?",
            [self._topic, status],
        )
        return row["cnt"] if row else 0

    def purge(self, status: str = "completed"):
        self._db.execute(
            "DELETE FROM tina4_queue WHERE topic = ? AND status = ?",
            [self._topic, status],
        )
        self._db.commit()

    def retry_failed(self) -> int:
        now = _now()
        result = self._db.execute(
            "UPDATE tina4_queue SET status = 'pending', available_at = ? "
            "WHERE topic = ? AND status = 'failed' AND attempts < ?",
            [now, self._topic, self._max_retries],
        )
        self._db.commit()
        return result.affected_rows

    def dead_letters(self) -> list[dict]:
        result = self._db.fetch(
            "SELECT * FROM tina4_queue WHERE topic = ? AND status = 'failed' AND attempts >= ?",
            [self._topic, self._max_retries],
            limit=1000,
        )
        return result.records

    def complete(self, job: Job):
        self._db.execute(
            "UPDATE tina4_queue SET status = 'completed', completed_at = ? WHERE id = ?",
            [_now(), job.id],
        )
        self._db.commit()

    def fail(self, job: Job, error: str = ""):
        self._db.execute(
            "UPDATE tina4_queue SET status = 'failed', error = ?, attempts = attempts + 1 WHERE id = ?",
            [error, job.id],
        )
        self._db.commit()

    def retry(self, job: Job, delay_seconds: int = 0):
        available_at = _now() if delay_seconds == 0 else _future(delay_seconds)
        self._db.execute(
            "UPDATE tina4_queue SET status = 'pending', available_at = ?, attempts = attempts + 1 WHERE id = ?",
            [available_at, job.id],
        )
        self._db.commit()


class _RabbitMQAdapter:
    """Backend adapter wrapping RabbitMQBackend for the unified Queue API."""

    def __init__(self, topic: str, max_retries: int):
        from tina4_python.queue_backends import RabbitMQBackend

        url = os.environ.get("TINA4_QUEUE_URL", "")
        config = {}
        if url:
            config = _parse_amqp_url(url)
        self._backend = RabbitMQBackend(**config)
        self._topic = topic
        self._max_retries = max_retries
        self._jobs: dict = {}  # track jobs by id for complete/fail/retry

    def push(self, data: dict, priority: int = 0, delay_seconds: int = 0) -> str:
        msg = {"payload": data, "priority": priority, "attempts": 0}
        msg_id = self._backend.enqueue(self._topic, msg)
        return msg_id

    def pop(self, queue_ref) -> Job | None:
        result = self._backend.dequeue(self._topic)
        if result is None:
            return None
        msg_id = result.get("id", "unknown")
        payload = result.get("payload", result)
        attempts = result.get("attempts", 0)
        priority = result.get("priority", 0)
        self._jobs[msg_id] = result
        return Job(
            queue=queue_ref,
            job_id=msg_id,
            topic=self._topic,
            data=payload if isinstance(payload, dict) else result,
            priority=priority,
            attempts=attempts,
        )

    def size(self, status: str = "pending") -> int:
        if status != "pending":
            return 0
        return self._backend.size(self._topic)

    def purge(self, status: str = "completed"):
        if status == "pending":
            self._backend.clear(self._topic)

    def retry_failed(self) -> int:
        return 0  # RabbitMQ handles redelivery natively

    def dead_letters(self) -> list[dict]:
        return []  # Dead letters handled by RabbitMQ DLX config

    def complete(self, job: Job):
        self._backend.acknowledge(self._topic, str(job.id))
        self._jobs.pop(str(job.id), None)

    def fail(self, job: Job, error: str = ""):
        job.attempts += 1
        if job.attempts >= self._max_retries:
            msg = self._jobs.pop(str(job.id), {"payload": job.data, "id": job.id})
            msg["error"] = error
            self._backend.dead_letter(self._topic, msg)
        else:
            self._backend.reject(self._topic, str(job.id), requeue=True)
        self._jobs.pop(str(job.id), None)

    def retry(self, job: Job, delay_seconds: int = 0):
        job.attempts += 1
        self._backend.reject(self._topic, str(job.id), requeue=True)
        self._jobs.pop(str(job.id), None)


class _KafkaAdapter:
    """Backend adapter wrapping KafkaBackend for the unified Queue API."""

    def __init__(self, topic: str, max_retries: int):
        from tina4_python.queue_backends import KafkaBackend

        url = os.environ.get("TINA4_QUEUE_URL", "")
        config = {}
        if url:
            config["brokers"] = url.replace("kafka://", "")
        brokers = os.environ.get("TINA4_KAFKA_BROKERS", "")
        if brokers:
            config["brokers"] = brokers
        self._backend = KafkaBackend(**config)
        self._topic = topic
        self._max_retries = max_retries

    def push(self, data: dict, priority: int = 0, delay_seconds: int = 0) -> str:
        msg = {"payload": data, "priority": priority, "attempts": 0}
        return self._backend.enqueue(self._topic, msg)

    def pop(self, queue_ref) -> Job | None:
        result = self._backend.dequeue(self._topic)
        if result is None:
            return None
        msg_id = result.get("id", "unknown")
        payload = result.get("payload", result)
        attempts = result.get("attempts", 0)
        priority = result.get("priority", 0)
        return Job(
            queue=queue_ref,
            job_id=msg_id,
            topic=self._topic,
            data=payload if isinstance(payload, dict) else result,
            priority=priority,
            attempts=attempts,
        )

    def size(self, status: str = "pending") -> int:
        if status != "pending":
            return 0
        return self._backend.size(self._topic)

    def purge(self, status: str = "completed"):
        pass  # Kafka does not support purging

    def retry_failed(self) -> int:
        return 0

    def dead_letters(self) -> list[dict]:
        return []

    def complete(self, job: Job):
        self._backend.acknowledge(self._topic, str(job.id))

    def fail(self, job: Job, error: str = ""):
        job.attempts += 1
        if job.attempts >= self._max_retries:
            msg = {"id": job.id, "payload": job.data, "error": error}
            self._backend.dead_letter(self._topic, msg)

    def retry(self, job: Job, delay_seconds: int = 0):
        job.attempts += 1
        msg = {"payload": job.data, "attempts": job.attempts}
        self._backend.enqueue(self._topic, msg)


def _resolve_backend(db, topic: str, backend: str | None, max_retries: int):
    """Resolve which backend adapter to use."""
    # If db is passed explicitly, always use sqlite adapter (backward compat)
    if db is not None:
        return _SqliteAdapter(db, topic, max_retries)

    # Determine backend from argument or env
    chosen = backend or os.environ.get("TINA4_QUEUE_BACKEND", "sqlite")
    chosen = chosen.lower().strip()

    if chosen in ("sqlite", "database", "db"):
        # Auto-create a database from DATABASE_URL or default path
        from tina4_python.database import Database
        db_url = os.environ.get("DATABASE_URL", "sqlite:///data/tina4_queue.db")
        auto_db = Database(db_url)
        return _SqliteAdapter(auto_db, topic, max_retries)
    elif chosen == "rabbitmq":
        return _RabbitMQAdapter(topic, max_retries)
    elif chosen == "kafka":
        return _KafkaAdapter(topic, max_retries)
    else:
        raise ValueError(f"Unknown queue backend: {chosen!r}. Use 'sqlite', 'rabbitmq', or 'kafka'.")


class Queue:
    """Unified job queue with pluggable backends.

    Supports SQLite (default), RabbitMQ, and Kafka. Backend is auto-detected
    from the TINA4_QUEUE_BACKEND environment variable.

    Usage:
        # Auto-detect from env (default: sqlite)
        queue = Queue(topic="tasks")

        # Explicit backend
        queue = Queue(topic="tasks", backend="rabbitmq")

        # Legacy (backward compat) — uses sqlite backend
        queue = Queue(db, topic="tasks")
    """

    def __init__(self, db=None, topic: str = "default", max_retries: int = 3,
                 backend: str | None = None):
        # Handle positional args: Queue(topic="x") vs Queue(db, topic="x")
        # If first arg is a string, treat it as topic (no db)
        if isinstance(db, str):
            topic = db
            db = None

        self.topic = topic
        self.max_retries = max_retries
        self._backend = _resolve_backend(db, topic, backend, max_retries)

        # Keep reference for backward compat (some code accesses queue._db)
        if db is not None:
            self._db = db

    def push(self, data: dict, priority: int = 0, delay_seconds: int = 0):
        """Add a job to the queue. Returns job ID."""
        return self._backend.push(data, priority, delay_seconds)

    def pop(self) -> Job | None:
        """Atomically claim the next available job. Returns None if empty."""
        return self._backend.pop(self)

    def size(self, status: str = "pending") -> int:
        """Count jobs by status."""
        return self._backend.size(status)

    def purge(self, status: str = "completed"):
        """Remove all jobs with the given status."""
        self._backend.purge(status)

    def retry_failed(self) -> int:
        """Re-queue failed jobs that haven't exceeded max_retries."""
        return self._backend.retry_failed()

    def dead_letters(self) -> list[dict]:
        """Get jobs that exceeded max retries."""
        return self._backend.dead_letters()


class Producer:
    """Convenience wrapper for pushing jobs."""

    def __init__(self, queue: Queue):
        self._queue = queue

    def push(self, data: dict, priority: int = 0, delay_seconds: int = 0):
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


def _parse_amqp_url(url: str) -> dict:
    """Parse amqp://user:pass@host:port/vhost into config dict."""
    config = {}
    url = url.replace("amqp://", "").replace("amqps://", "")
    if "@" in url:
        creds, rest = url.split("@", 1)
        if ":" in creds:
            config["username"], config["password"] = creds.split(":", 1)
        else:
            config["username"] = creds
    else:
        rest = url
    if "/" in rest:
        hostport, vhost = rest.split("/", 1)
        if vhost:
            config["vhost"] = "/" + vhost if not vhost.startswith("/") else vhost
    else:
        hostport = rest
    if ":" in hostport:
        host, port = hostport.split(":", 1)
        config["host"] = host
        config["port"] = int(port)
    elif hostport:
        config["host"] = hostport
    return config


__all__ = ["Queue", "Producer", "Consumer", "Job"]
