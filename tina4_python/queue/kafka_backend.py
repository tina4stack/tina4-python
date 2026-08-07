# Tina4 Queue — Kafka backend adapter. Zero dependencies on this file.
"""
KafkaBackend wraps the external KafkaBackend from tina4_python.queue_backends
and adapts it to the unified Queue API expected by Queue._backend.
"""
import os

from tina4_python.queue.job import Job


class KafkaBackend:
    """Backend adapter wrapping KafkaBackend for the unified Queue API."""

    def __init__(self, topic: str, max_retries: int):
        from tina4_python.queue_backends import KafkaConnector as _KafkaBackend

        url = os.environ.get("TINA4_QUEUE_URL", "")
        config = {}
        if url:
            config["brokers"] = url.replace("kafka://", "")
        brokers = os.environ.get("TINA4_KAFKA_BROKERS", "")
        if brokers:
            config["brokers"] = brokers
        self._backend = _KafkaBackend(**config)
        self._topic = topic
        self._max_retries = max_retries

    def push(self, data: dict, priority: int = 0, delay_seconds: int = 0) -> str:
        if priority > 0:
            raise NotImplementedError(
                "The kafka queue backend cannot honour push(priority): Kafka has "
                "no priority concept at all — a consumer reads a partition in "
                "offset order. Use the file or mongodb backend for prioritised "
                "jobs."
            )
        if delay_seconds > 0:
            raise NotImplementedError(
                "The kafka queue backend cannot honour push(delay_seconds): "
                "Kafka has no per-message delay at all. A consumer reads a "
                "partition in offset order, so a delayed record would stall "
                "every record behind it. Use the file or mongodb backend for "
                "delayed jobs, or schedule the push itself."
            )
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
        """Not performable on Kafka — raises naming the backend and the operation.

        purge(status) removes jobs SELECTED BY STATUS. A Kafka log has no notion
        of job status and cannot delete records on demand: a partition is read
        in offset order and records leave only by retention. This used to be a
        bare ``pass``, so a caller who ran purge() believed jobs were removed
        when nothing happened (ADR-0022 invariant 6: a backend that cannot
        perform an operation refuses by name, it never silently no-ops).
        """
        raise NotImplementedError(
            "The kafka queue backend cannot perform purge(): Kafka has no notion "
            "of job status to purge by — a log is read in offset order and "
            "records leave only by retention. Returning without doing anything "
            "would claim jobs were purged when none were. Configure topic "
            "retention, or use the file or mongodb backend."
        )

    def retry_failed(self, max_retries: int = None) -> int:
        """Not performable on Kafka — raises naming the backend and the operation.

        It is built on failed(), which cannot be answered here (see above). It
        gets its OWN refusal rather than letting failed()'s message escape,
        because invariant 6 requires the raise to name the operation the caller
        actually invoked.
        """
        raise NotImplementedError(
            "The kafka queue backend cannot perform retry_failed(): it must "
            "first enumerate the failed-but-retryable jobs, which a log cannot "
            "be queried for. Returning 0 would claim nothing needed retrying. "
            "Use retry(job_id) with an id you already hold, or the file or "
            "mongodb backend."
        )

    def failed(self, max_retries: int = None) -> list[dict]:
        """Not answerable on Kafka — raises naming the backend and the operation.

        failed() means "died at least once and is STILL eligible for retry".
        On this backend fail() re-produces such a record to the MAIN topic, so
        it is indistinguishable from any other pending record — a log cannot be
        queried by job state. It is NOT on the .dead_letter topic; only jobs
        that exhausted max_retries are produced there.

        This used to consume .dead_letter looking for attempts < max_retries.
        Nothing there ever satisfies that predicate, so it returned [] every
        time, and an empty list claims "nothing has failed"
        (ADR-0022 decision 7). Refusing by name is the honest answer.

        dead_letters() is unaffected and still works here: this backend keeps
        its own <topic>.dead_letter topic and can enumerate it.
        """
        raise NotImplementedError(
            "The kafka queue backend cannot answer failed(): a job that failed "
            "but is still retryable is re-produced to the main topic, and a log "
            "cannot be queried by job state, so it cannot be told apart from a "
            "normal pending record. Returning an empty list would claim nothing "
            "has failed. Use dead_letters() for exhausted jobs, or the file or "
            "mongodb backend to enumerate retryable failures."
        )

    def dead_letters(self, max_retries: int = None) -> list[dict]:
        """Consume dead_letter topic, republish, return jobs at/over max_retries.

        Accepts max_retries to match the LiteBackend contract — Queue.dead_letters()
        passes it as a kwarg, so without this signature the call raised TypeError.
        """
        mr = max_retries if max_retries is not None else self._max_retries
        dl_topic = f"{self._topic}.dead_letter"
        results = []
        requeue = []
        while True:
            msg = self._backend.dequeue(dl_topic)
            if msg is None:
                break
            payload = msg.get("payload", msg)
            attempts = msg.get("attempts", 0)
            if attempts >= mr:
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
        """Not performable on Kafka — raises naming the backend and the operation.

        clear() empties the queue. A Kafka log cannot delete records on demand:
        a partition is read in offset order and records leave only by retention.
        This used to ``return 0``, which claimed the queue was emptied when it
        was untouched — the silent no-op ADR-0022 invariant 6 forbids. Refusing
        by name is the honest answer.
        """
        raise NotImplementedError(
            "The kafka queue backend cannot perform clear(): Kafka has no notion "
            "of job status and cannot delete records on demand — a log is read "
            "in offset order and records leave only by retention. Returning 0 "
            "would claim the queue was emptied when it was not. Configure topic "
            "retention, or use the file or mongodb backend."
        )

    def complete(self, job: Job):
        self._backend.acknowledge(self._topic, str(job.id))

    def fail(self, job: Job, error: str = ""):
        """Record a failed attempt, then either retry it or dead-letter it.

        Kafka has no per-record nack: a consumer group commits an OFFSET, so a
        record cannot be returned to its position without replaying everything
        after it. The retry is therefore a RE-PRODUCE carrying the incremented
        attempt count, followed by a commit past the original record - the same
        retry-topic shape Confluent documents and Spring Kafka implements in
        DeadLetterPublishingRecoverer.

        Both branches acknowledge. Leaving the original uncommitted would make a
        rebalance replay a record that has already been re-produced or
        dead-lettered, duplicating it.
        """
        job.attempts += 1
        if job.attempts >= self._max_retries:
            msg = {"id": job.id, "payload": job.data,
                   "attempts": job.attempts, "error": error}
            self._backend.dead_letter(self._topic, msg)
        else:
            # Re-produce so the job is actually retried. Without this a job
            # failing below max_retries was dropped outright: the consumer
            # position had already moved past it and nothing re-published it.
            self._backend.enqueue(self._topic, {
                "payload": job.data,
                "priority": job.priority,
                "attempts": job.attempts,
                "error": error,
            })
        self._backend.acknowledge(self._topic, str(job.id))

    def retry(self, job: Job, delay_seconds: int = 0):
        job.attempts += 1
        msg = {"payload": job.data, "priority": job.priority, "attempts": job.attempts}
        self._backend.enqueue(self._topic, msg)
        self._backend.acknowledge(self._topic, str(job.id))

    def close(self) -> None:
        """Flush the producer, leave the consumer group, and release the socket.

        Idempotent: the connector drops its producer/consumer/socket handles on
        the first call, so a second call finds nothing to close and returns.
        """
        self._backend.close()
