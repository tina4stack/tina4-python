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

    def failed(self) -> list[dict]:
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
                    if job_data.get("attempts", 0) < self._max_retries:
                        results.append(job_data)
                except (json.JSONDecodeError, FileNotFoundError):
                    continue
        except FileNotFoundError:
            pass
        return results

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

    def retry_job(self, job_id: str, delay_seconds: int = 0) -> bool:
        failed_dir = self._failed_dir()
        queue_dir = self._queue_dir()
        filepath = os.path.join(failed_dir, f"{job_id}.queue-data")
        try:
            with open(filepath) as f:
                job_data = json.load(f)
            if job_data.get("attempts", 0) >= self._max_retries:
                return False
            job_data["status"] = "pending"
            job_data["error"] = None
            job_data["attempts"] = job_data.get("attempts", 0) + 1
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
