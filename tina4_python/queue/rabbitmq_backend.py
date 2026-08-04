# Tina4 Queue — RabbitMQ backend adapter. Zero dependencies on this file.
"""
RabbitMQBackend wraps the external RabbitMQBackend from tina4_python.queue_backends
and adapts it to the unified Queue API expected by Queue._backend.
"""
import os

from tina4_python.queue.job import Job


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


class RabbitMQBackend:
    """Backend adapter wrapping RabbitMQBackend for the unified Queue API."""

    def __init__(self, topic: str, max_retries: int):
        from tina4_python.queue_backends import RabbitMQConnector as _RabbitMQBackend

        url = os.environ.get("TINA4_QUEUE_URL", "")
        config = {}
        if url:
            config = _parse_amqp_url(url)
        self._backend = _RabbitMQBackend(**config)
        self._topic = topic
        self._max_retries = max_retries
        self._jobs: dict = {}  # track jobs by id for complete/fail/retry

    def push(self, data: dict, priority: int = 0, delay_seconds: int = 0) -> str:
        if priority > 0:
            raise NotImplementedError(
                "The rabbitmq queue backend cannot honour push(priority): "
                "RabbitMQ orders a queue FIFO. Native priority needs the queue "
                "DECLARED with an x-max-priority argument, and an existing queue "
                "cannot be redeclared with one (the broker answers "
                "PRECONDITION_FAILED), so enabling it would break every queue "
                "already in service. Use the file or mongodb backend for "
                "prioritised jobs."
            )
        if delay_seconds > 0:
            raise NotImplementedError(
                "The rabbitmq queue backend cannot honour push(delay_seconds): "
                "RabbitMQ has no per-message delay in core. The "
                "rabbitmq_delayed_message_exchange plugin is not part of a "
                "standard broker, and the TTL + dead-letter workaround "
                "head-of-line blocks (a long-delayed job holds up every shorter "
                "one behind it in the same queue). Use the file or mongodb "
                "backend for delayed jobs, or schedule the push itself."
            )
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

    def retry_failed(self, max_retries: int = None) -> int:
        """Not performable on RabbitMQ — raises naming the backend and the operation.

        It is built on failed(), which cannot be answered here (see above). It
        gets its OWN refusal rather than letting failed()'s message escape,
        because invariant 6 requires the raise to name the operation the caller
        actually invoked.
        """
        raise NotImplementedError(
            "The rabbitmq queue backend cannot perform retry_failed(): it must "
            "first enumerate the failed-but-retryable jobs, which are back on "
            "the main topic and indistinguishable from pending work. Returning "
            "0 would claim nothing needed retrying. Use retry(job_id) with an "
            "id you already hold, or the file or mongodb backend."
        )

    def failed(self, max_retries: int = None) -> list[dict]:
        """Not answerable on RabbitMQ — raises naming the backend and the operation.

        failed() means "died at least once and is STILL eligible for retry".
        On this backend fail() re-publishes such a job to the MAIN topic (that
        is what makes the next pop() redeliver it), so a retryable failure is
        indistinguishable from any other pending message without draining the
        live queue. It is NOT in the .dead_letter queue — only jobs that
        exhausted max_retries go there.

        This used to drain .dead_letter looking for attempts < max_retries.
        Nothing in that queue ever satisfies that predicate, so it returned []
        every time — and an empty list claims "nothing has failed"
        (ADR-0022 decision 7). Refusing by name is the honest answer.

        dead_letters() is unaffected and still works here: this backend keeps
        its own <topic>.dead_letter queue and can enumerate it.
        """
        raise NotImplementedError(
            "The rabbitmq queue backend cannot answer failed(): a job that "
            "failed but is still retryable is re-published to the main topic, "
            "so it cannot be told apart from a normal pending message without "
            "draining the live queue. Returning an empty list would claim "
            "nothing has failed. Use dead_letters() for exhausted jobs, or the "
            "file or mongodb backend to enumerate retryable failures."
        )

    def dead_letters(self, max_retries: int = None) -> list[dict]:
        """Drain the dead_letter queue, re-enqueue, and return jobs at/over max_retries.

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
        """Record a failed attempt, then either retry it or dead-letter it.

        AMQP 0-9-1 basic.nack(requeue=1) returns the ORIGINAL body to the queue,
        unmodified - the protocol carries no delivery counter. Re-queueing that
        way meant ``attempts`` came back as 0 on every redelivery, so
        ``attempts >= max_retries`` never tripped and a poison job spun forever.

        So the retry acknowledges the original delivery and RE-PUBLISHES a body
        carrying the new count. That is what every AMQP client that counts
        attempts does (Celery, Spring AMQP's RepublishMessageRecoverer,
        laravel-queue-rabbitmq).
        """
        job.attempts += 1
        msg = self._jobs.pop(str(job.id), None) or {"payload": job.data, "id": job.id}
        msg["attempts"] = job.attempts
        if job.attempts >= self._max_retries:
            msg["error"] = error
            self._backend.dead_letter(self._topic, msg)
        else:
            msg["error"] = error
            self._backend.enqueue(self._topic, msg)
        # Ack LAST: the re-publish (or dead-letter) is durable before the
        # original leaves the queue, so a crash in between redelivers rather
        # than loses. That is at-least-once, which is the contract.
        self._backend.acknowledge(self._topic, str(job.id))

    def retry(self, job: Job, delay_seconds: int = 0):
        job.attempts += 1
        msg = self._jobs.pop(str(job.id), None) or {"payload": job.data, "id": job.id}
        msg["attempts"] = job.attempts
        msg.pop("error", None)
        self._backend.enqueue(self._topic, msg)
        self._backend.acknowledge(self._topic, str(job.id))
