# Tina4 Queue — Unified job queue with pluggable backends, zero dependencies.
"""
Production-grade queue with auto-detected backends. Switching from file to
RabbitMQ, Kafka, or MongoDB is a .env change — no code change needed.

    from tina4_python.queue import Queue

    # Auto-detect backend from TINA4_QUEUE_BACKEND env var (default: file)
    queue = Queue(topic="emails")
    queue.push({"to": "alice@test.com", "subject": "Hello"})

    for job in queue.consume("emails"):
        send_email(job.data)
        job.complete()

Environment variables:
    TINA4_QUEUE_BACKEND   — 'file' (default), 'rabbitmq', 'kafka', or 'mongodb'
    TINA4_QUEUE_URL       — connection URL for rabbitmq/kafka
    TINA4_QUEUE_PATH      — file backend storage path (default: data/queue)
    TINA4_RABBITMQ_HOST   — RabbitMQ host (default: localhost)
    TINA4_KAFKA_BROKERS   — Kafka brokers (default: localhost:9092)
    TINA4_MONGO_HOST      — MongoDB host (default: localhost)
"""
import json
import os
import time
import threading
from datetime import datetime, timezone

from tina4_python.queue.job import Job
from tina4_python.queue.lite_backend import LiteBackend
from tina4_python.queue.rabbitmq_backend import RabbitMQBackend
from tina4_python.queue.kafka_backend import KafkaBackend
from tina4_python.queue.mongo_backend import MongoBackend


def _resolve_backend(topic: str, backend: str | None, max_retries: int):
    """Resolve which backend adapter to use."""
    chosen = backend or os.environ.get("TINA4_QUEUE_BACKEND", "file")
    chosen = chosen.lower().strip()

    if chosen in ("file", "default", "lite"):
        return LiteBackend(topic, max_retries)
    elif chosen == "rabbitmq":
        return RabbitMQBackend(topic, max_retries)
    elif chosen == "kafka":
        return KafkaBackend(topic, max_retries)
    elif chosen in ("mongodb", "mongo"):
        return MongoBackend(topic, max_retries)
    else:
        raise ValueError(f"Unknown queue backend: {chosen!r}. Use 'file', 'rabbitmq', 'kafka', or 'mongodb'.")


class Queue:
    """Unified job queue with pluggable backends.

    Supports file (default), RabbitMQ, Kafka, and MongoDB. Backend is
    auto-detected from the TINA4_QUEUE_BACKEND environment variable.

    Usage:
        queue = Queue(topic="tasks")
        queue = Queue(topic="tasks", backend="rabbitmq")
    """

    def __init__(self, topic: str = "default", max_retries: int = 3,
                 backend: str | None = None):
        self.topic = topic
        self.max_retries = max_retries
        self._backend = _resolve_backend(topic, backend, max_retries)

    def push(self, data: dict, priority: int = 0, delay_seconds: int = 0):
        """Add a job to the queue. Returns job ID."""
        return self._backend.push(data, priority, delay_seconds)

    def pop(self) -> Job | None:
        """Atomically claim the next available job. Returns None if empty."""
        return self._backend.pop(self)

    def pop_batch(self, count: int) -> list:
        """Pop up to count jobs at once. Returns a partial batch if fewer available."""
        if hasattr(self._backend, "pop_batch"):
            return self._backend.pop_batch(count, self)
        # Fallback for backends that don't implement pop_batch
        jobs = []
        for _ in range(count):
            job = self._backend.pop(self)
            if job is None:
                break
            jobs.append(job)
        return jobs

    def get_topic(self) -> str:
        """Return the topic name this queue was constructed with."""
        return self.topic

    def process(self, handler, topic: str = None, *, max_jobs: int = None, batch_size: int = 1) -> None:
        """Consume all available jobs and pass each to handler, then stop.

        Simpler alternative to consume() for drain-and-exit use cases.

        Args:
            handler:    Callable that receives a Job (or list of Jobs when batch_size > 1).
                        Should call job.complete() or job.fail() when done.
            topic:      Override the queue's default topic.
            max_jobs:   Stop after processing this many jobs (None = drain all).
            batch_size: Number of jobs to pass to handler at once (default 1).
                        When > 1, handler receives a list of Jobs.
        """
        processed = 0
        while max_jobs is None or processed < max_jobs:
            if batch_size > 1:
                remaining = (max_jobs - processed) if max_jobs else batch_size
                jobs = self.pop_batch(min(batch_size, remaining))
                if not jobs:
                    break
                try:
                    handler(jobs)
                except Exception as exc:  # noqa: BLE001
                    for job in jobs:
                        job.fail(str(exc))
                processed += len(jobs)
            else:
                job = self._backend.pop(self)
                if job is None:
                    break
                try:
                    handler(job)
                except Exception as exc:  # noqa: BLE001
                    job.fail(str(exc))
                processed += 1

    def size(self, status: str = "pending") -> int:
        """Count jobs by status."""
        return self._backend.size(status)

    def purge(self, status: str = "completed") -> int:
        """Remove all jobs with the given status. Returns count removed."""
        return self._backend.purge(status)

    def retry_failed(self) -> int:
        """Re-queue failed jobs that haven't exceeded max_retries."""
        return self._backend.retry_failed()

    def failed(self) -> list[dict]:
        """Get jobs that failed but are still eligible for retry."""
        return self._backend.failed()

    def dead_letters(self) -> list[dict]:
        """Get jobs that exceeded max retries."""
        return self._backend.dead_letters()

    def retry(self, job_id: str, delay_seconds: int = 0) -> bool:
        """Retry a specific failed job by ID. Returns True if found and re-queued."""
        return self._backend.retry_job(job_id, delay_seconds)

    def clear(self) -> int:
        """Remove all pending jobs from the queue. Returns count removed."""
        return self._backend.clear()

    def produce(self, topic: str, data: dict, priority: int = 0, delay_seconds: int = 0):
        """Produce a message onto a topic. Convenience wrapper around push()."""
        old_topic = self.topic
        self.topic = topic
        self._backend = _resolve_backend(topic, None, self.max_retries)
        try:
            return self.push(data, priority, delay_seconds)
        finally:
            self.topic = old_topic
            self._backend = _resolve_backend(old_topic, None, self.max_retries)

    def consume(self, topic: str = None, job_id: str = None, poll_interval: float = 1.0,
                iterations: int = 0, batch_size: int = 1):
        """Consume jobs from a topic using a long-running generator.

        Polls the queue continuously. When empty, sleeps for poll_interval
        seconds before polling again. No external while-loop or sleep needed.

        Usage:
            for job in queue.consume("emails"):
                process(job)
                job.complete()

            # Process exactly 5 jobs then stop:
            for job in queue.consume("emails", iterations=5):
                process(job)
                job.complete()

            # Custom poll interval (check every 5 seconds when idle):
            for job in queue.consume("emails", poll_interval=5):
                process(job)

            # Consume a specific job by ID (single yield, no polling):
            for job in queue.consume("emails", job_id="abc-123"):
                process(job)
                job.complete()

        Args:
            topic: Topic/queue name (defaults to constructor topic)
            job_id: Optional job ID — only yield this specific job
            poll_interval: Seconds to sleep when queue is empty (default 1.0)
            iterations: Max number of jobs to consume (0 = unlimited, default 0)
        """
        import time

        topic = topic or self.topic

        if job_id is not None:
            # Consume a specific job by ID — single yield, no polling
            job = self.pop_by_id(job_id)
            if job is not None:
                yield job
            return

        # poll_interval=0 → single-pass drain (returns when empty)
        # poll_interval>0 → long-running poll (sleeps when empty, never returns)
        consumed = 0
        while True:
            if batch_size > 1:
                jobs = self.pop_batch(batch_size)
                if not jobs:
                    if poll_interval <= 0:
                        break
                    time.sleep(poll_interval)
                    continue
                yield jobs
                consumed += len(jobs)
            else:
                job = self.pop()
                if job is None:
                    if poll_interval <= 0:
                        break
                    time.sleep(poll_interval)
                    continue
                yield job
                consumed += 1
            if iterations > 0 and consumed >= iterations:
                break

    def pop_by_id(self, job_id: str) -> Job | None:
        """Pop a specific job by ID from the queue."""
        if not isinstance(self._backend, LiteBackend):
            return None
        queue_dir = self._backend._queue_dir()
        try:
            for filename in os.listdir(queue_dir):
                if not filename.endswith(".queue-data"):
                    continue
                if job_id not in filename:
                    continue
                filepath = os.path.join(queue_dir, filename)
                try:
                    with open(filepath) as f:
                        job_data = json.load(f)
                    if job_data.get("id") == job_id and job_data.get("status") == "pending":
                        os.unlink(filepath)
                        return Job(
                            queue=self, job_id=job_data["id"],
                            topic=job_data.get("topic", self.topic),
                            data=job_data["data"],
                            priority=job_data.get("priority", 0),
                            attempts=job_data.get("attempts", 0),
                        )
                except (json.JSONDecodeError, FileNotFoundError):
                    continue
        except FileNotFoundError:
            pass
        return None



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


__all__ = ["Queue", "Job", "LiteBackend", "RabbitMQBackend", "KafkaBackend", "MongoBackend"]
