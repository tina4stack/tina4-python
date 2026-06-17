# Tina4 Queue — File-based (lite) backend. Zero dependencies.
"""
LiteBackend stores each job as a JSON file on disk. No external services needed.
This is the default backend when TINA4_QUEUE_BACKEND is 'file', 'default', or 'lite'.
"""
import json
import os
import time
import threading
import uuid
from datetime import datetime, timezone

from tina4_python.queue.job import Job


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future(seconds: int) -> str:
    return datetime.fromtimestamp(
        time.time() + seconds, tz=timezone.utc
    ).isoformat()


class LiteBackend:
    """File-based queue backend — JSON files on disk. Zero dependencies.

    Matches the file-based queue implementation in PHP, Ruby, and Node.js.
    Each job is stored as a separate .queue-data JSON file.
    """

    def __init__(self, topic: str, max_retries: int, retry_backoff: int = 0):
        self._topic = topic
        self._max_retries = max_retries
        # Seconds to delay a job's next attempt when it is automatically
        # re-enqueued by fail(). 0 (the default) means retry immediately —
        # the next pop()/consume() iteration picks it up straight away.
        self._retry_backoff = retry_backoff
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

    def _available_candidates(self, now: str) -> list:
        """Return (filename, job_data) for every pending, non-delayed job,
        ordered by the dequeue policy: highest priority first, ties broken
        oldest-first by created_at.

        The file *name* is no longer the ordering key — the stored
        ``priority`` and ``created_at`` fields are. This makes pop()/consume()
        honour priority instead of being pure FIFO.
        """
        queue_dir = self._queue_dir()
        try:
            filenames = os.listdir(queue_dir)
        except FileNotFoundError:
            return []

        candidates = []
        for filename in filenames:
            if not filename.endswith(".queue-data"):
                continue
            filepath = os.path.join(queue_dir, filename)
            try:
                with open(filepath) as f:
                    job_data = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                continue
            if job_data.get("status") != "pending":
                continue
            if job_data.get("available_at", "") > now:
                continue  # still delayed
            candidates.append((filename, job_data))

        # priority DESC, then created_at ASC (oldest first). created_at is an
        # ISO-8601 string so lexicographic order == chronological order.
        candidates.sort(
            key=lambda item: (
                -int(item[1].get("priority", 0) or 0),
                item[1].get("created_at", "") or "",
            )
        )
        return candidates

    def pop(self, queue_ref) -> Job | None:
        now = _now()
        queue_dir = self._queue_dir()

        with self._lock:
            for filename, job_data in self._available_candidates(now):
                filepath = os.path.join(queue_dir, filename)
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
                    error=job_data.get("error"),
                )

        return None

    def pop_batch(self, count: int, queue_ref) -> list:
        """Pop up to count jobs in one operation, highest priority first.

        Returns a partial batch if fewer than ``count`` are available.
        """
        now = _now()
        queue_dir = self._queue_dir()
        results = []

        with self._lock:
            for filename, job_data in self._available_candidates(now):
                if len(results) >= count:
                    break
                filepath = os.path.join(queue_dir, filename)
                try:
                    os.unlink(filepath)
                except FileNotFoundError:
                    continue

                results.append(Job(
                    queue=queue_ref,
                    job_id=job_data["id"],
                    topic=job_data.get("topic", self._topic),
                    data=job_data["data"],
                    priority=job_data.get("priority", 0),
                    attempts=job_data.get("attempts", 0),
                    error=job_data.get("error"),
                ))

        return results

    # Status aliases that live in the failed/ directory (dead-lettered jobs)
    # rather than as pending files in the queue directory.
    _DEAD_STATES = ("failed", "dead", "dead_letter")

    def size(self, status: str = "pending") -> int:
        scan_dir = self._failed_dir() if status in self._DEAD_STATES else self._queue_dir()
        count = 0
        try:
            for filename in os.listdir(scan_dir):
                if not filename.endswith(".queue-data"):
                    continue
                filepath = os.path.join(scan_dir, filename)
                try:
                    with open(filepath) as f:
                        job_data = json.load(f)
                except (json.JSONDecodeError, FileNotFoundError):
                    continue
                if status in self._DEAD_STATES:
                    # Every file in failed/ is a dead-letter; count them all
                    # regardless of the exact stored status string.
                    count += 1
                elif job_data.get("status") == status:
                    count += 1
        except FileNotFoundError:
            pass
        return count

    def purge(self, status: str = "completed") -> int:
        scan_dir = self._failed_dir() if status in self._DEAD_STATES else self._queue_dir()
        count = 0
        try:
            for filename in os.listdir(scan_dir):
                if not filename.endswith(".queue-data"):
                    continue
                filepath = os.path.join(scan_dir, filename)
                try:
                    with open(filepath) as f:
                        job_data = json.load(f)
                except (json.JSONDecodeError, FileNotFoundError):
                    continue
                if status in self._DEAD_STATES or job_data.get("status") == status:
                    try:
                        os.unlink(filepath)
                        count += 1
                    except FileNotFoundError:
                        continue
        except FileNotFoundError:
            pass
        return count

    def retry_failed(self, max_retries: int = None) -> int:
        failed_dir = self._failed_dir()
        queue_dir = self._queue_dir()
        limit = max_retries if max_retries is not None else self._max_retries
        count = 0
        try:
            for filename in os.listdir(failed_dir):
                if not filename.endswith(".queue-data"):
                    continue
                filepath = os.path.join(failed_dir, filename)
                try:
                    with open(filepath) as f:
                        job_data = json.load(f)
                    if job_data.get("attempts", 0) < limit:
                        job_data["status"] = "pending"
                        job_data["available_at"] = _now()
                        job_data["created_at"] = _now()
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

    def failed(self) -> list[dict]:
        """Jobs that have failed at least once but are still being retried.

        Under the auto-retry lifecycle a failed-but-retryable job lives in the
        pending queue (not the dead-letter dir), so this scans the queue dir
        for pending jobs with ``attempts > 0`` that have not yet exhausted
        their retries. Dead-lettered jobs are returned by dead_letters().
        """
        queue_dir = self._queue_dir()
        results = []
        try:
            for filename in sorted(os.listdir(queue_dir)):
                if not filename.endswith(".queue-data"):
                    continue
                filepath = os.path.join(queue_dir, filename)
                try:
                    with open(filepath) as f:
                        job_data = json.load(f)
                except (json.JSONDecodeError, FileNotFoundError):
                    continue
                attempts = job_data.get("attempts", 0)
                if attempts > 0 and attempts < self._max_retries:
                    results.append(job_data)
        except FileNotFoundError:
            pass
        return results

    def dead_letters(self, max_retries: int = None) -> list[dict]:
        failed_dir = self._failed_dir()
        limit = max_retries if max_retries is not None else self._max_retries
        results = []
        try:
            for filename in sorted(os.listdir(failed_dir)):
                if not filename.endswith(".queue-data"):
                    continue
                filepath = os.path.join(failed_dir, filename)
                try:
                    with open(filepath) as f:
                        job_data = json.load(f)
                    if job_data.get("attempts", 0) >= limit:
                        results.append(job_data)
                except (json.JSONDecodeError, FileNotFoundError):
                    continue
        except FileNotFoundError:
            pass
        return results

    def retry_job(self, job_id: str, delay_seconds: int = 0) -> bool:
        """Revive a specific dead-letter job by id back to the pending queue.

        This is a manual override (Queue.retry(job_id)) — it always revives a
        dead-letter regardless of attempt count, mirroring job.retry(). Returns
        False only if no dead-letter with that id exists.
        """
        failed_dir = self._failed_dir()
        queue_dir = self._queue_dir()
        filepath = os.path.join(failed_dir, f"{job_id}.queue-data")
        try:
            with open(filepath) as f:
                job_data = json.load(f)
            job_data["status"] = "pending"
            job_data["error"] = None
            job_data["attempts"] = job_data.get("attempts", 0) + 1
            job_data["created_at"] = _now()
            if delay_seconds > 0:
                job_data["available_at"] = _future(delay_seconds)
            else:
                job_data["available_at"] = _now()
            prefix = self._next_prefix()
            new_path = os.path.join(queue_dir, f"{prefix}_{job_id}.queue-data")
            with open(new_path, "w") as f:
                json.dump(job_data, f, indent=2, default=str)
            os.unlink(filepath)
            return True
        except (json.JSONDecodeError, FileNotFoundError):
            return False

    def clear(self) -> int:
        queue_dir = self._queue_dir()
        count = 0
        try:
            for filename in os.listdir(queue_dir):
                if not filename.endswith(".queue-data"):
                    continue
                try:
                    os.unlink(os.path.join(queue_dir, filename))
                    count += 1
                except FileNotFoundError:
                    continue
        except FileNotFoundError:
            pass
        return count

    def complete(self, job: Job):
        # Job file was already deleted on pop — nothing to do. complete() is
        # terminal: the job is done and gone.
        pass

    def _requeue(self, job: Job, delay_seconds: int = 0, error: str | None = None):
        """Write the job back to the pending queue (queue dir).

        Re-enqueued jobs get a fresh ``created_at`` so within a priority tier
        they sort behind jobs that have not yet been attempted. ``attempts``
        already reflects the latest failure count.
        """
        available = _now() if delay_seconds <= 0 else _future(delay_seconds)
        job_data = {
            "id": job.id,
            "topic": job.topic,
            "data": job.payload,
            "status": "pending",
            "priority": job.priority,
            "attempts": job.attempts,
            "error": error,
            "available_at": available,
            "created_at": _now(),
        }
        prefix = self._next_prefix()
        filepath = os.path.join(self._queue_dir(), f"{prefix}_{job.id}.queue-data")
        with open(filepath, "w") as f:
            json.dump(job_data, f, indent=2, default=str)

    def _dead_letter(self, job: Job, error: str = ""):
        """Move the job to the dead-letter (failed) directory. Terminal until
        a manual retry_failed()/retry() revives it."""
        job_data = {
            "id": job.id,
            "topic": job.topic,
            "data": job.payload,
            "status": "dead",
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

    def fail(self, job: Job, error: str = ""):
        """Record a failed attempt.

        Increments ``attempts``. If the job still has retries left
        (``attempts < max_retries``) it is automatically re-enqueued to the
        pending queue — so the next pop()/consume() iteration picks it up
        again — after an optional ``retry_backoff`` delay. Once it has been
        attempted ``max_retries`` times (``attempts >= max_retries``) it is
        moved to the dead-letter store, where dead_letters() returns it.
        """
        job.attempts += 1
        job.error = error
        if job.attempts < self._max_retries:
            self._requeue(job, delay_seconds=self._retry_backoff, error=error)
        else:
            self._dead_letter(job, error)

    def retry(self, job: Job, delay_seconds: int = 0):
        """Explicit re-queue requested by the caller (job.retry()).

        Always re-enqueues regardless of the retry limit — this is a manual
        override, distinct from the automatic fail() path.
        """
        job.attempts += 1
        self._requeue(job, delay_seconds=delay_seconds, error=None)
