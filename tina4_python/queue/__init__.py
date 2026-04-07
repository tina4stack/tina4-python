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
        jobs = self.failed()
        count = 0
        for job in jobs:
            job_id = job.get("id", "")
            if self.retry_job(job_id):
                count += 1
        return count

    def failed(self) -> list[dict]:
        """Drain the dead_letter queue, re-enqueue, and return jobs still under max_retries."""
        dl_topic = f"{self._topic}.dead_letter"
        results = []
        requeue = []
        while True:
            msg = self._backend.dequeue(dl_topic)
            if msg is None:
                break
            payload = msg.get("payload", msg)
            attempts = msg.get("attempts", 0)
            if attempts < self._max_retries:
                results.append({"id": msg.get("id"), "data": payload,
                                 "attempts": attempts, "error": msg.get("error")})
            requeue.append(msg)
        for msg in requeue:
            self._backend.enqueue(dl_topic, msg)
        return results

    def dead_letters(self) -> list[dict]:
        """Drain the dead_letter queue, re-enqueue, and return jobs at/over max_retries."""
        dl_topic = f"{self._topic}.dead_letter"
        results = []
        requeue = []
        while True:
            msg = self._backend.dequeue(dl_topic)
            if msg is None:
                break
            payload = msg.get("payload", msg)
            attempts = msg.get("attempts", 0)
            if attempts >= self._max_retries:
                results.append({"id": msg.get("id"), "data": payload,
                                 "attempts": attempts, "error": msg.get("error")})
            requeue.append(msg)
        for msg in requeue:
            self._backend.enqueue(dl_topic, msg)
        return results

    def retry_job(self, job_id: str, delay_seconds: int = 0) -> bool:
        """Move a job from the dead_letter queue back to the main topic."""
        dl_topic = f"{self._topic}.dead_letter"
        found = None
        requeue = []
        while True:
            msg = self._backend.dequeue(dl_topic)
            if msg is None:
                break
            if msg.get("id") == job_id and found is None:
                found = msg
            else:
                requeue.append(msg)
        for msg in requeue:
            self._backend.enqueue(dl_topic, msg)
        if found is None:
            return False
        found["attempts"] = found.get("attempts", 0) + 1
        found["status"] = "pending"
        found.pop("error", None)
        self._backend.enqueue(self._topic, found)
        return True

    def clear(self) -> int:
        self._backend.clear(self._topic)
        return 0

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
        jobs = self.failed()
        count = 0
        for job in jobs:
            if self.retry_job(job.get("id", "")):
                count += 1
        return count

    def failed(self) -> list[dict]:
        """Consume dead_letter topic, republish, return jobs under max_retries."""
        dl_topic = f"{self._topic}.dead_letter"
        results = []
        requeue = []
        while True:
            msg = self._backend.dequeue(dl_topic)
            if msg is None:
                break
            payload = msg.get("payload", msg)
            attempts = msg.get("attempts", 0)
            if attempts < self._max_retries:
                results.append({"id": msg.get("id"), "data": payload,
                                 "attempts": attempts, "error": msg.get("error")})
            requeue.append(msg)
        for msg in requeue:
            self._backend.enqueue(dl_topic, msg)
        return results

    def dead_letters(self) -> list[dict]:
        """Consume dead_letter topic, republish, return jobs at/over max_retries."""
        dl_topic = f"{self._topic}.dead_letter"
        results = []
        requeue = []
        while True:
            msg = self._backend.dequeue(dl_topic)
            if msg is None:
                break
            payload = msg.get("payload", msg)
            attempts = msg.get("attempts", 0)
            if attempts >= self._max_retries:
                results.append({"id": msg.get("id"), "data": payload,
                                 "attempts": attempts, "error": msg.get("error")})
            requeue.append(msg)
        for msg in requeue:
            self._backend.enqueue(dl_topic, msg)
        return results

    def retry_job(self, job_id: str, delay_seconds: int = 0) -> bool:
        """Move job from dead_letter topic back to main topic."""
        dl_topic = f"{self._topic}.dead_letter"
        found = None
        requeue = []
        while True:
            msg = self._backend.dequeue(dl_topic)
            if msg is None:
                break
            if msg.get("id") == job_id and found is None:
                found = msg
            else:
                requeue.append(msg)
        for msg in requeue:
            self._backend.enqueue(dl_topic, msg)
        if found is None:
            return False
        found["attempts"] = found.get("attempts", 0) + 1
        found["status"] = "pending"
        found.pop("error", None)
        self._backend.enqueue(self._topic, found)
        return True

    def clear(self) -> int:
        return 0  # Kafka does not support topic purging without admin API

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


class _MongoDBAdapter:
    """Backend adapter wrapping MongoBackend for the unified Queue API."""

    def __init__(self, topic: str, max_retries: int):
        from tina4_python.queue_backends import MongoBackend

        url = os.environ.get("TINA4_QUEUE_URL", "")
        config = {}
        if url:
            config["uri"] = url
        self._backend = MongoBackend(**config)
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
        if status == "pending":
            self._backend.clear(self._topic)

    def retry_failed(self) -> int:
        self._backend._ensure_connected()
        result = self._backend._collection.update_many(
            {"topic": self._topic, "status": "failed",
             "attempts": {"$lt": self._max_retries}},
            {"$set": {"status": "pending", "error": None}},
        )
        return result.modified_count

    def failed(self) -> list[dict]:
        """Query MongoDB for jobs with status=failed and attempts < max_retries."""
        self._backend._ensure_connected()
        docs = self._backend._collection.find(
            {"topic": self._topic, "status": "failed",
             "attempts": {"$lt": self._max_retries}}
        )
        return [{"id": d.get("_id"), "data": d.get("payload", d.get("data")),
                 "attempts": d.get("attempts", 0), "error": d.get("error")}
                for d in docs]

    def dead_letters(self) -> list[dict]:
        """Query the dead_letter collection in MongoDB."""
        self._backend._ensure_connected()
        dl_topic = f"{self._topic}.dead_letter"
        docs = self._backend._collection.find({"topic": dl_topic})
        return [{"id": d.get("_id"), "data": d.get("data", d.get("payload")),
                 "attempts": d.get("attempts", 0), "error": d.get("error")}
                for d in docs]

    def retry_job(self, job_id: str, delay_seconds: int = 0) -> bool:
        """Reset a failed job back to pending by ID."""
        self._backend._ensure_connected()
        available = _now() if delay_seconds == 0 else _future(delay_seconds)
        result = self._backend._collection.update_one(
            {"_id": job_id, "topic": self._topic, "status": "failed"},
            {"$set": {"status": "pending", "error": None,
                      "available_at": available},
             "$inc": {"attempts": 1}},
        )
        return result.modified_count == 1

    def clear(self) -> int:
        result = self._backend._collection.delete_many(
            {"topic": self._topic, "status": "pending"}
        )
        return result.deleted_count

    def complete(self, job: Job):
        self._backend.acknowledge(self._topic, str(job.id))

    def fail(self, job: Job, error: str = ""):
        job.attempts += 1
        if job.attempts >= self._max_retries:
            msg = {"id": job.id, "payload": job.data, "error": error}
            self._backend.dead_letter(self._topic, msg)
            self._backend.acknowledge(self._topic, str(job.id))
        else:
            self._backend.reject(self._topic, str(job.id), requeue=True)

    def retry(self, job: Job, delay_seconds: int = 0):
        job.attempts += 1
        self._backend.reject(self._topic, str(job.id), requeue=True)


def _resolve_backend(topic: str, backend: str | None, max_retries: int):
    """Resolve which backend adapter to use."""
    chosen = backend or os.environ.get("TINA4_QUEUE_BACKEND", "file")
    chosen = chosen.lower().strip()

    if chosen in ("file", "default", "lite"):
        return LiteBackend(topic, max_retries)
    elif chosen == "rabbitmq":
        return _RabbitMQAdapter(topic, max_retries)
    elif chosen == "kafka":
        return _KafkaAdapter(topic, max_retries)
    elif chosen in ("mongodb", "mongo"):
        return _MongoDBAdapter(topic, max_retries)
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
                iterations: int = 0):
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


__all__ = ["Queue", "Job", "LiteBackend"]
