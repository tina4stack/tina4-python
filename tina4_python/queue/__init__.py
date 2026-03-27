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


class Job:
    """A single queue job."""

    def __init__(self, queue, job_id, topic: str, data: dict,
                 priority: int = 0, attempts: int = 0):
        self.queue = queue
        self.id = job_id
        self.topic = topic
        self.payload = data
        self.priority = priority
        self.attempts = attempts

    @property
    def data(self):
        """Alias for payload — deprecated, use .payload instead."""
        return self.payload

    def complete(self):
        """Mark job as completed."""
        self.queue._backend.complete(self)

    def fail(self, error: str = ""):
        """Mark job as failed. Will be retried if attempts < max_retries."""
        self.queue._backend.fail(self, error)

    def reject(self, reason: str = ""):
        """Reject a job with a reason. Alias for fail()."""
        self.fail(reason)

    def retry(self, delay_seconds: int = 0):
        """Re-queue this job with optional delay."""
        self.queue._backend.retry(self, delay_seconds)


class _FileAdapter:
    """File-based queue backend — JSON files on disk. Zero dependencies.

    Matches the file-based queue implementation in PHP, Ruby, and Node.js.
    Each job is stored as a separate .queue-data JSON file.
    """

    def __init__(self, topic: str, max_retries: int):
        self._topic = topic
        self._max_retries = max_retries
        self._base_path = os.environ.get("TINA4_QUEUE_PATH", "data/queue")
        self._lock = threading.Lock()
        self._seq = 0
        self._ensure_dirs()

    def _ensure_dirs(self):
        queue_dir = os.path.join(self._base_path, self._topic)
        failed_dir = os.path.join(queue_dir, "failed")
        os.makedirs(queue_dir, exist_ok=True)
        os.makedirs(failed_dir, exist_ok=True)

    def _queue_dir(self) -> str:
        return os.path.join(self._base_path, self._topic)

    def _failed_dir(self) -> str:
        return os.path.join(self._base_path, self._topic, "failed")

    def _next_prefix(self) -> str:
        self._seq += 1
        return f"{int(time.time() * 1000)}-{self._seq:06d}"

    def push(self, data: dict, priority: int = 0, delay_seconds: int = 0) -> str:
        import uuid
        job_id = str(uuid.uuid4())
        available = _now() if delay_seconds == 0 else _future(delay_seconds)
        job = {
            "id": job_id,
            "topic": self._topic,
            "data": data,
            "status": "pending",
            "priority": priority,
            "attempts": 0,
            "error": None,
            "available_at": available,
            "created_at": _now(),
        }
        prefix = self._next_prefix()
        filepath = os.path.join(self._queue_dir(), f"{prefix}_{job_id}.queue-data")
        with open(filepath, "w") as f:
            json.dump(job, f, indent=2, default=str)
        return job_id

    def pop(self, queue_ref) -> Job | None:
        now = _now()
        queue_dir = self._queue_dir()

        with self._lock:
            try:
                files = sorted(f for f in os.listdir(queue_dir) if f.endswith(".queue-data"))
            except FileNotFoundError:
                return None

            for filename in files:
                filepath = os.path.join(queue_dir, filename)
                try:
                    with open(filepath) as f:
                        job_data = json.load(f)
                except (json.JSONDecodeError, FileNotFoundError):
                    continue

                if job_data.get("status") != "pending":
                    continue
                if job_data.get("available_at", "") > now:
                    continue

                # Claim the job by deleting the file
                try:
                    os.unlink(filepath)
                except FileNotFoundError:
                    continue  # Already consumed by another worker

                return Job(
                    queue=queue_ref,
                    job_id=job_data["id"],
                    topic=job_data.get("topic", self._topic),
                    data=job_data["data"],
                    priority=job_data.get("priority", 0),
                    attempts=job_data.get("attempts", 0),
                )

        return None

    def size(self, status: str = "pending") -> int:
        queue_dir = self._queue_dir()
        count = 0
        try:
            for filename in os.listdir(queue_dir):
                if not filename.endswith(".queue-data"):
                    continue
                filepath = os.path.join(queue_dir, filename)
                try:
                    with open(filepath) as f:
                        job_data = json.load(f)
                    if job_data.get("status") == status:
                        count += 1
                except (json.JSONDecodeError, FileNotFoundError):
                    continue
        except FileNotFoundError:
            pass
        return count

    def purge(self, status: str = "completed") -> int:
        queue_dir = self._queue_dir()
        count = 0
        try:
            for filename in os.listdir(queue_dir):
                if not filename.endswith(".queue-data"):
                    continue
                filepath = os.path.join(queue_dir, filename)
                try:
                    with open(filepath) as f:
                        job_data = json.load(f)
                    if job_data.get("status") == status:
                        os.unlink(filepath)
                        count += 1
                except (json.JSONDecodeError, FileNotFoundError):
                    continue
        except FileNotFoundError:
            pass
        return count

    def retry_failed(self) -> int:
        failed_dir = self._failed_dir()
        queue_dir = self._queue_dir()
        count = 0
        try:
            for filename in os.listdir(failed_dir):
                if not filename.endswith(".queue-data"):
                    continue
                filepath = os.path.join(failed_dir, filename)
                try:
                    with open(filepath) as f:
                        job_data = json.load(f)
                    if job_data.get("attempts", 0) < self._max_retries:
                        job_data["status"] = "pending"
                        job_data["available_at"] = _now()
                        prefix = self._next_prefix()
                        new_path = os.path.join(queue_dir, f"{prefix}_{job_data['id']}.queue-data")
                        with open(new_path, "w") as f:
                            json.dump(job_data, f, indent=2, default=str)
                        os.unlink(filepath)
                        count += 1
                except (json.JSONDecodeError, FileNotFoundError):
                    continue
        except FileNotFoundError:
            pass
        return count

    def dead_letters(self) -> list[dict]:
        failed_dir = self._failed_dir()
        results = []
        try:
            for filename in sorted(os.listdir(failed_dir)):
                if not filename.endswith(".queue-data"):
                    continue
                filepath = os.path.join(failed_dir, filename)
                try:
                    with open(filepath) as f:
                        job_data = json.load(f)
                    if job_data.get("attempts", 0) >= self._max_retries:
                        results.append(job_data)
                except (json.JSONDecodeError, FileNotFoundError):
                    continue
        except FileNotFoundError:
            pass
        return results

    def complete(self, job: Job):
        # Job file was already deleted on pop — nothing to do
        pass

    def fail(self, job: Job, error: str = ""):
        job.attempts += 1
        job_data = {
            "id": job.id,
            "topic": job.topic,
            "data": job.payload,
            "status": "failed",
            "priority": job.priority,
            "attempts": job.attempts,
            "error": error,
            "failed_at": _now(),
        }
        failed_dir = self._failed_dir()
        os.makedirs(failed_dir, exist_ok=True)
        filepath = os.path.join(failed_dir, f"{job.id}.queue-data")
        with open(filepath, "w") as f:
            json.dump(job_data, f, indent=2, default=str)

    def retry(self, job: Job, delay_seconds: int = 0):
        job.attempts += 1
        available = _now() if delay_seconds == 0 else _future(delay_seconds)
        job_data = {
            "id": job.id,
            "topic": job.topic,
            "data": job.payload,
            "status": "pending",
            "priority": job.priority,
            "attempts": job.attempts,
            "available_at": available,
            "created_at": _now(),
        }
        prefix = self._next_prefix()
        filepath = os.path.join(self._queue_dir(), f"{prefix}_{job.id}.queue-data")
        with open(filepath, "w") as f:
            json.dump(job_data, f, indent=2, default=str)


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
        return 0  # MongoDB backend handles retries via reject(requeue=True)

    def dead_letters(self) -> list[dict]:
        return []  # Dead letters stored in topic.dead_letter collection docs

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
        return _FileAdapter(topic, max_retries)
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

    def dead_letters(self) -> list[dict]:
        """Get jobs that exceeded max retries."""
        return self._backend.dead_letters()


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

    def consume(self, topic: str = None, job_id: str = None):
        """Consume jobs from a topic using a generator (yield pattern).

        Usage:
            for job in queue.consume("emails"):
                process(job)
                job.complete()

            # Consume a specific job by ID:
            for job in queue.consume("emails", job_id="abc-123"):
                process(job)
                job.complete()

        Args:
            topic: Topic/queue name (defaults to constructor topic)
            job_id: Optional job ID — only yield this specific job
        """
        topic = topic or self.topic

        if job_id is not None:
            # Consume a specific job by ID
            job = self.pop_by_id(topic, job_id)
            if job is not None:
                yield job
            return

        # Yield all available jobs
        while True:
            job = self.pop()
            if job is None:
                break
            yield job

    def pop_by_id(self, topic: str, job_id: str) -> Job | None:
        """Pop a specific job by ID from the queue."""
        if not isinstance(self._backend, _FileAdapter):
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
                            topic=job_data.get("topic", topic),
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


__all__ = ["Queue", "Job"]
