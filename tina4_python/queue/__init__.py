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
    TINA4_QUEUE_VISIBILITY_TIMEOUT — seconds a popped job stays reserved before
                            a dead consumer's job is reclaimed (default 300;
                            <= 0 disables reclaim). File + MongoDB backends only;
                            RabbitMQ/Kafka delegate visibility to the broker.
    TINA4_RABBITMQ_HOST   — RabbitMQ host (default: localhost)
    TINA4_KAFKA_BROKERS   — Kafka brokers (default: localhost:9092)
    TINA4_MONGO_HOST      — MongoDB host (default: localhost)
"""
import json
import os
import time
from datetime import datetime, timezone

from tina4_python.queue.job import Job
from tina4_python.queue.lite_backend import LiteBackend
from tina4_python.queue.rabbitmq_backend import RabbitMQBackend
from tina4_python.queue.kafka_backend import KafkaBackend
from tina4_python.queue.mongo_backend import MongoBackend


def _default_visibility_timeout() -> float:
    """Reservation/visibility timeout in seconds, from env (default 300 = 5 min)."""
    try:
        return float(os.environ.get("TINA4_QUEUE_VISIBILITY_TIMEOUT", "300"))
    except (TypeError, ValueError):
        return 300.0


def _resolve_backend(topic: str, backend: str | None, max_retries: int,
                     retry_backoff: int = 0, visibility_timeout: float = 300.0):
    """Resolve which backend adapter to use."""
    chosen = backend or os.environ.get("TINA4_QUEUE_BACKEND", "file")
    chosen = chosen.lower().strip()

    if chosen in ("file", "default", "lite"):
        return LiteBackend(topic, max_retries, retry_backoff, visibility_timeout)
    elif chosen == "rabbitmq":
        # Broker manages visibility/redelivery (unacked messages requeue on
        # channel close) — the framework timeout is accepted but not used.
        return RabbitMQBackend(topic, max_retries)
    elif chosen == "kafka":
        # Consumer-group offsets manage redelivery — framework timeout N/A.
        return KafkaBackend(topic, max_retries)
    elif chosen in ("mongodb", "mongo"):
        return MongoBackend(topic, max_retries, visibility_timeout, retry_backoff)
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
                 backend: str | None = None, retry_backoff: int = 0,
                 visibility_timeout: float | None = None):
        self.topic = topic
        self.max_retries = max_retries
        # Seconds to wait before a failed job is re-attempted.
        # Default 0 = retry on the very next pop()/consume() iteration.
        self.retry_backoff = retry_backoff
        # Remember an explicit backend= so retargeting a topic (produce/consume)
        # does not silently fall back to the TINA4_QUEUE_BACKEND env default.
        self._backend_choice = backend
        # Reservation/visibility timeout (seconds). A popped job is reserved for
        # this long; if the consumer dies before complete()/fail() the next
        # pop() reclaims it (at-least-once delivery). Falls back to
        # TINA4_QUEUE_VISIBILITY_TIMEOUT, else 300 (5 min). <= 0 disables reclaim.
        self.visibility_timeout = (
            visibility_timeout if visibility_timeout is not None
            else _default_visibility_timeout()
        )
        self._backend = _resolve_backend(topic, backend, max_retries, retry_backoff,
                                         self.visibility_timeout)

    def _retarget(self, topic: str) -> None:
        """Point this queue (and its backend) at ``topic`` in place.

        produce()/consume()/process() call this so a topic argument actually
        changes which topic is read or written. Without it the argument was
        accepted but ignored on the read path — pop() always used the
        construction-time topic, so ``consume("other")`` silently drained the
        wrong queue. Reuses the explicit backend choice (``_backend_choice``)
        so an explicit ``backend=`` is preserved across the switch.
        """
        if topic == self.topic:
            return
        self.topic = topic
        self._backend = _resolve_backend(
            topic, self._backend_choice, self.max_retries,
            self.retry_backoff, self.visibility_timeout,
        )

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
        if topic is not None:
            self._retarget(topic)
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

    def purge(self, status: str, max_retries: int = None) -> int:
        """Remove all jobs with the given status. Returns count removed."""
        return self._backend.purge(status)

    def retry_failed(self, max_retries: int = None) -> int:
        """Re-queue failed jobs that haven't exceeded max_retries."""
        return self._backend.retry_failed(max_retries=max_retries if max_retries is not None else self.max_retries)

    def failed(self) -> list[dict]:
        """Get jobs that failed but are still eligible for retry."""
        return self._backend.failed()

    def dead_letters(self, max_retries: int = None) -> list[Job]:
        """Get jobs that exceeded max retries.

        Returns ``Job`` objects with the failure reason on ``.error``,
        not raw dicts — so callers can iterate uniformly with the rest
        of the queue API (``for job in queue.consume()``).

            for job in queue.dead_letters():
                logger.error(f"Dead: {job.id} after {job.attempts} attempts: {job.error}")
                job.retry()  # or just leave it dead

        Backends still return dicts internally; this method wraps each
        into a Job whose ``.error`` field is populated from the dict's
        ``error`` key (when present).
        """
        max_r = max_retries if max_retries is not None else self.max_retries
        raw = self._backend.dead_letters(max_retries=max_r)
        return [
            Job(
                queue=self,
                job_id=d.get("id"),
                topic=d.get("topic", self.topic),
                data=d.get("payload") if "payload" in d else d.get("data", {}),
                priority=d.get("priority", 0),
                attempts=d.get("attempts", 0),
                error=d.get("error"),
            )
            for d in raw
        ]

    def retry(self, job_id: str = None, delay_seconds: int = 0) -> bool:
        """Retry a failed job by ID, or all dead-letter jobs if no ID given."""
        if job_id is None:
            dead = self.dead_letters()
            if not dead:
                return False
            # dead is now list[Job] — pull the id off each
            return any(self._backend.retry_job(j.id, delay_seconds) for j in dead)
        return self._backend.retry_job(job_id, delay_seconds)

    def clear(self) -> int:
        """Remove all pending jobs from the queue. Returns count removed."""
        return self._backend.clear()

    def produce(self, topic: str, data: dict, priority: int = 0,
                delay_seconds: int = 0, delay_until: datetime | None = None):
        """Produce a message onto a topic. Convenience wrapper around push().

        Either ``delay_seconds`` (integer offset) or ``delay_until``
        (absolute ``datetime``) may be passed for scheduled jobs. ``delay_until``
        takes precedence when both are set — naive datetimes are interpreted
        as local time; aware datetimes use their tzinfo.

            queue.produce("reports", data, delay_seconds=300)
            queue.produce("reports", data, delay_until=datetime(2026,6,1,18,0))
        """
        if delay_until is not None:
            now = datetime.now(delay_until.tzinfo) if delay_until.tzinfo else datetime.now()
            offset = int((delay_until - now).total_seconds())
            delay_seconds = max(0, offset)

        old_topic = self.topic
        self._retarget(topic)
        try:
            return self.push(data, priority, delay_seconds)
        finally:
            self._retarget(old_topic)

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
            job_id: Optional job ID — only yield this specific job. Renamed from
                ``id`` in 3.13.0 to stop shadowing the ``id`` builtin and to
                match the documented kwarg name.
            poll_interval: Seconds to sleep when queue is empty (default 1.0)
            iterations: Max number of jobs to consume (0 = unlimited, default 0)
        """
        import time

        topic = topic or self.topic
        # Honor the topic argument: point the queue (and the backend that
        # pop()/job.complete()/job.fail() route through) at it. Previously the
        # argument was ignored and consume() drained the construction-time topic.
        self._retarget(topic)

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

    def pop_by_id(self, id: str) -> Job | None:
        """Pop a specific job by ID from the queue."""
        job_id = id
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
                        # Reserve (so a dead consumer's job is reclaimable) then
                        # claim the pending file — mirrors LiteBackend.pop().
                        self._backend._write_reserved(job_data)
                        os.unlink(filepath)
                        return Job(
                            queue=self, job_id=job_data["id"],
                            topic=job_data.get("topic", self.topic),
                            data=job_data["data"],
                            priority=job_data.get("priority", 0),
                            attempts=job_data.get("attempts", 0),
                            error=job_data.get("error"),
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
