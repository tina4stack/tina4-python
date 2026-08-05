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


def queue_base_path() -> str:
    """Where the file-backed queue stores its jobs — ``TINA4_QUEUE_PATH``, else
    ``data/queue`` (relative to the working directory).

    Public because it is the ONE answer to "where do the queue files live", and
    anything that reads the store directly (the dev-admin queue panel) must ask
    here rather than re-derive it. The dev admin hardcoded
    ``os.getcwd()/data/queue/<topic>`` and so listed a DIFFERENT directory from
    the one ``Queue.size()`` counted the moment ``TINA4_QUEUE_PATH`` was set.
    """
    return os.environ.get("TINA4_QUEUE_PATH", "data/queue")


class LiteBackend:
    """File-based queue backend — JSON files on disk. Zero dependencies.

    Matches the file-based queue implementation in PHP, Ruby, and Node.js.
    Each job is stored as a separate .queue-data JSON file.
    """

    def __init__(self, topic: str, max_retries: int, retry_backoff: int = 0,
                 visibility_timeout: float = 300.0):
        self._topic = topic
        self._max_retries = max_retries
        # Seconds to delay a job's next attempt when it is automatically
        # re-enqueued by fail(). 0 (the default) means retry immediately —
        # the next pop()/consume() iteration picks it up straight away.
        self._retry_backoff = retry_backoff
        # Reservation/visibility timeout (seconds). When a job is popped it is
        # held in reserved/ with available_at = now + visibility_timeout. If the
        # consumer dies before complete()/fail() (crash, OOM, k8s eviction), the
        # next pop() reclaims it once the window expires — incrementing attempts
        # and re-enqueuing, or dead-lettering past max_retries. <= 0 disables the
        # reclaim (a reservation then lasts until the consumer acks — the old
        # at-most-once behaviour).
        self._visibility_timeout = visibility_timeout
        self._base_path = queue_base_path()
        self._lock = threading.Lock()
        self._seq = 0
        self._ensure_dirs()

    def _ensure_dirs(self):
        queue_dir = os.path.join(self._base_path, self._topic)
        failed_dir = os.path.join(queue_dir, "failed")
        os.makedirs(queue_dir, exist_ok=True)
        os.makedirs(failed_dir, exist_ok=True)
        os.makedirs(self._reserved_dir(), exist_ok=True)

    def _queue_dir(self) -> str:
        return os.path.join(self._base_path, self._topic)

    def _failed_dir(self) -> str:
        return os.path.join(self._base_path, self._topic, "failed")

    def _reserved_dir(self) -> str:
        return os.path.join(self._base_path, self._topic, "reserved")

    def _reserved_path(self, job_id: str) -> str:
        return os.path.join(self._reserved_dir(), f"{job_id}.queue-data")

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

    def _write_reserved(self, job_data: dict, attempts: int | None = None):
        """Persist a reservation record so a dead consumer's job is reclaimable.

        Stores reserved_at + available_at = now + visibility_timeout. The next
        pop() reclaims this job once available_at has passed (see
        _reclaim_expired). complete()/fail()/retry() delete the record.
        """
        now = _now()
        vt = self._visibility_timeout or 0
        record = {
            "id": job_data["id"],
            "topic": job_data.get("topic", self._topic),
            "data": job_data.get("data", {}),
            "status": "reserved",
            "priority": job_data.get("priority", 0),
            "attempts": job_data.get("attempts", 0) if attempts is None else attempts,
            "error": job_data.get("error"),
            "reserved_at": now,
            "available_at": _future(vt) if vt > 0 else now,
            "created_at": job_data.get("created_at", now),
        }
        os.makedirs(self._reserved_dir(), exist_ok=True)
        with open(self._reserved_path(record["id"]), "w") as f:
            json.dump(record, f, indent=2, default=str)

    def _reclaim_expired(self, now: str):
        """Return expired reservations to the queue (at-least-once delivery).

        A reserved job whose ``available_at <= now`` means its consumer never
        acknowledged in time (crash / OOM / pod eviction). Increment attempts
        and either re-enqueue it (so the next pop picks it up) or dead-letter it
        once it has hit max_retries. Disabled when visibility_timeout <= 0.
        """
        if not self._visibility_timeout or self._visibility_timeout <= 0:
            return
        reserved_dir = self._reserved_dir()
        try:
            filenames = os.listdir(reserved_dir)
        except FileNotFoundError:
            return
        for filename in filenames:
            if not filename.endswith(".queue-data"):
                continue
            filepath = os.path.join(reserved_dir, filename)
            try:
                with open(filepath) as f:
                    job_data = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                continue
            if job_data.get("available_at", "") > now:
                continue  # reservation still valid
            # Atomically claim the expired reservation by deleting its file.
            try:
                os.unlink(filepath)
            except FileNotFoundError:
                continue  # another worker reclaimed it first
            attempts = job_data.get("attempts", 0) + 1
            error = ("reservation timed out — consumer did not acknowledge "
                     "within the visibility timeout")
            job = Job(
                queue=None,
                job_id=job_data["id"],
                topic=job_data.get("topic", self._topic),
                data=job_data.get("data", {}),
                priority=job_data.get("priority", 0),
                attempts=attempts,
                error=error,
            )
            if attempts >= self._max_retries:
                self._dead_letter(job, error)
            else:
                self._requeue(job, delay_seconds=0, error=error)

    def pop(self, queue_ref) -> Job | None:
        queue_dir = self._queue_dir()

        with self._lock:
            # First return any reservations whose consumer died mid-flight.
            self._reclaim_expired(_now())
            now = _now()
            for filename, job_data in self._available_candidates(now):
                filepath = os.path.join(queue_dir, filename)
                # Write the reservation BEFORE claiming the pending file, so a
                # crash between claim and reserve can never strand the job.
                # Only the worker that wins the unlink owns — and returns — it.
                self._write_reserved(job_data)
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
        queue_dir = self._queue_dir()
        results = []

        with self._lock:
            self._reclaim_expired(_now())
            now = _now()
            for filename, job_data in self._available_candidates(now):
                if len(results) >= count:
                    break
                filepath = os.path.join(queue_dir, filename)
                self._write_reserved(job_data)
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
        if status == "reserved":
            scan_dir = self._reserved_dir()
        elif status in self._DEAD_STATES:
            scan_dir = self._failed_dir()
        else:
            scan_dir = self._queue_dir()
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
                if status in self._DEAD_STATES or status == "reserved":
                    # Every file in the failed/ (or reserved/) dir matches the
                    # requested status; count them all.
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
        count = 0
        for scan_dir in (self._queue_dir(), self._reserved_dir()):
            try:
                for filename in os.listdir(scan_dir):
                    if not filename.endswith(".queue-data"):
                        continue
                    try:
                        os.unlink(os.path.join(scan_dir, filename))
                        count += 1
                    except FileNotFoundError:
                        continue
            except FileNotFoundError:
                pass
        return count

    def close(self) -> None:
        """No-op: the file backend holds no connection to release.

        It exists so ``Queue.close()`` can call ONE method on every backend
        instead of testing for it, and so switching TINA4_QUEUE_BACKEND to
        'file' never turns a working close() into an AttributeError. Idempotent
        by construction — there is nothing to drop.
        """

    def _clear_reservation(self, job_id: str):
        """Delete a job's reservation record (best-effort)."""
        try:
            os.unlink(self._reserved_path(job_id))
        except FileNotFoundError:
            pass

    def complete(self, job: Job):
        # The pending file was claimed on pop and a reservation record written;
        # complete() is terminal, so drop the reservation. The job is done.
        self._clear_reservation(job.id)

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
        # Clear the reservation — the consumer acknowledged (with a failure).
        self._clear_reservation(job.id)
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
        self._clear_reservation(job.id)
        job.attempts += 1
        self._requeue(job, delay_seconds=delay_seconds, error=None)
