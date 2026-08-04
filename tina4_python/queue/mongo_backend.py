# Tina4 Queue — MongoDB backend adapter. Zero dependencies on this file.
"""
MongoBackend wraps the external MongoBackend from tina4_python.queue_backends
and adapts it to the unified Queue API expected by Queue._backend.
"""
import os
import time
from datetime import datetime, timezone

from tina4_python.queue.job import Job


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future(seconds: int) -> str:
    return datetime.fromtimestamp(
        time.time() + seconds, tz=timezone.utc
    ).isoformat()


class MongoBackend:
    """Backend adapter wrapping MongoBackend for the unified Queue API."""

    def __init__(self, topic: str, max_retries: int, visibility_timeout: float = 300.0,
                 retry_backoff: float = 0):
        from tina4_python.queue_backends import MongoConnector as _MongoBackend

        url = os.environ.get("TINA4_QUEUE_URL", "")
        config = {"visibility_timeout": visibility_timeout, "retry_backoff": retry_backoff}
        if url:
            config["uri"] = url
        self._backend = _MongoBackend(**config)
        self._topic = topic
        self._max_retries = max_retries

    def push(self, data: dict, priority: int = 0, delay_seconds: int = 0) -> str:
        msg = {"payload": data, "priority": priority, "attempts": 0}
        return self._backend.enqueue(self._topic, msg, delay_seconds)

    def pop(self, queue_ref) -> Job | None:
        # Reclaim any reservations whose consumer died before acking, then take
        # the next available message (at-least-once delivery).
        try:
            self._backend.reclaim_expired(self._topic, self._max_retries)
        except AttributeError:
            pass  # older connector without reclaim support
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

    def pop_by_id(self, queue_ref, job_id: str) -> Job | None:
        """Claim ONE specific job by id, the same way pop() claims the head.

        Queue.pop_by_id used to `return None` on every non-file backend - a
        silent no-op indistinguishable from "no such job".
        """
        self._backend._ensure_connected()
        doc = self._backend._collection.find_one_and_update(
            {"_id": job_id, "topic": self._topic, "status": "pending"},
            {"$set": {"status": "processing",
                      "reserved_at": _now(),
                      "available_at": _future(self._backend._visibility_timeout)}},
            return_document=self._backend._pymongo.ReturnDocument.AFTER,
        )
        if doc is None:
            return None
        payload = (doc.get("data") or {}).get("payload", doc.get("data"))
        return Job(
            queue=queue_ref,
            job_id=doc.get("_id"),
            topic=self._topic,
            data=payload if isinstance(payload, dict) else doc.get("data"),
            priority=doc.get("priority", 0),
            attempts=doc.get("attempts", 0),
        )

    def size(self, status: str = "pending") -> int:
        if status != "pending":
            return 0
        return self._backend.size(self._topic)

    def purge(self, status: str = "completed"):
        if status == "pending":
            self._backend.clear(self._topic)

    def retry_failed(self, max_retries: int = None) -> int:
        # Accept max_retries to match the LiteBackend contract (Queue passes it
        # as a kwarg) — without this signature, Queue.retry_failed() raised
        # TypeError on MongoDB.
        mr = max_retries if max_retries is not None else self._max_retries
        self._backend._ensure_connected()
        result = self._backend._collection.update_many(
            {"topic": self._topic, "status": "failed",
             "attempts": {"$lt": mr}},
            # Reset available_at so re-queued failed jobs are visible again
            # (they were reserved with available_at in the future at dequeue).
            {"$set": {"status": "pending", "error": None, "available_at": _now(),
                      "reserved_at": None}},
        )
        return result.modified_count

    def failed(self) -> list[dict]:
        """Jobs that failed but are still eligible for retry.

        Found by the ATTEMPTS COUNTER, not by a "failed" status. fail() under
        max_retries re-queues the job as ``pending`` (that is what makes the
        next pop() pick it up), so no document ever carries status="failed" on
        the normal path — querying for one returned an empty list forever, and
        an empty list is indistinguishable from "nothing has failed"
        (ADR-0022 decision 7). ``attempts > 0`` is the real marker of a job
        that has already died at least once.
        """
        self._backend._ensure_connected()
        # status="pending" is REQUIRED, not decoration. The final fail() writes a
        # dead-letter copy and acknowledges the original, but the original keeps
        # the attempts value it had BEFORE that last increment (the last one is
        # in-memory only). Without the status clause that acknowledged doc still
        # matched the attempts range, so failed() returned a job that was
        # already dead - file returned 0 for the same sequence.
        docs = self._backend._collection.find(
            {"topic": self._topic, "status": "pending",
             "attempts": {"$gt": 0, "$lt": self._max_retries}}
        )
        return [{"id": d.get("_id"), "data": d.get("payload", d.get("data")),
                 "attempts": d.get("attempts", 0), "error": d.get("error")}
                for d in docs]

    def dead_letters(self, max_retries: int = None) -> list[dict]:
        """Query the dead_letter collection in MongoDB.

        Accepts max_retries (unused — dead letters are terminal) to match the
        LiteBackend contract; Queue.dead_letters() passes it as a kwarg, so
        without this parameter the call raised TypeError on MongoDB.
        """
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
        # The only one of this adapter's six _collection users that forgot to
        # connect first, so clear() on a fresh Queue raised AttributeError on
        # NoneType instead of clearing anything.
        self._backend._ensure_connected()
        result = self._backend._collection.delete_many(
            {"topic": self._topic, "status": "pending"}
        )
        return result.deleted_count

    def complete(self, job: Job):
        self._backend.acknowledge(self._topic, str(job.id))

    def fail(self, job: Job, error: str = ""):
        job.attempts += 1
        job.error = error
        if job.attempts >= self._max_retries:
            # attempts MUST ride along: dead_letters() reads it back, and
            # omitting it reported every Mongo dead letter as attempts=0 while
            # file/rabbitmq/kafka reported the real count. A dead-letter handler
            # logging "died after N attempts" printed 0 on Mongo only.
            msg = {"id": job.id, "payload": job.data,
                   "attempts": job.attempts, "error": error}
            self._backend.dead_letter(self._topic, msg)
            self._backend.acknowledge(self._topic, str(job.id))
        else:
            self._backend.reject(self._topic, str(job.id), requeue=True, error=error)

    def retry(self, job: Job, delay_seconds: int = 0):
        job.attempts += 1
        self._backend.reject(self._topic, str(job.id), requeue=True)
