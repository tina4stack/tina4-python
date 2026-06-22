# Tina4 MongoDB Queue Backend — document-based queue via pymongo.
"""
MongoDB queue backend. Uses `pymongo` (required — no raw protocol fallback).

Environment variables:
    TINA4_MONGO_HOST       — hostname (default: localhost)
    TINA4_MONGO_PORT       — port (default: 27017)
    TINA4_MONGO_URI        — full connection URI (overrides host/port)
    TINA4_MONGO_USERNAME   — username (optional)
    TINA4_MONGO_PASSWORD   — password (optional)
    TINA4_MONGO_DB         — database name (default: tina4)
    TINA4_MONGO_COLLECTION — collection name (default: tina4_queue)

Document schema:
    {
        _id: str (uuid),
        topic: str,
        data: dict,
        status: "pending" | "reserved" | "completed" | "failed" | "dead",
        priority: int,
        attempts: int,
        error: str | None,
        available_at: str (ISO 8601),
        created_at: str (ISO 8601),
        completed_at: str | None,
    }
"""
import os
import uuid
from datetime import datetime, timezone


class MongoConnector:
    """MongoDB queue backend implementing the Tina4 queue contract.

    Methods: enqueue, dequeue, acknowledge, reject, size, clear, dead_letter, close.
    """

    def __init__(self, **config):
        self._host = config.get("host", os.environ.get("TINA4_MONGO_HOST", "localhost"))
        self._port = int(config.get("port", os.environ.get("TINA4_MONGO_PORT", "27017")))
        self._uri = config.get("uri", os.environ.get("TINA4_MONGO_URI", ""))
        self._username = config.get("username", os.environ.get("TINA4_MONGO_USERNAME", ""))
        self._password = config.get("password", os.environ.get("TINA4_MONGO_PASSWORD", ""))
        self._db_name = config.get("db", os.environ.get("TINA4_MONGO_DB", "tina4"))
        self._collection_name = config.get(
            "collection", os.environ.get("TINA4_MONGO_COLLECTION", "tina4_queue")
        )
        # Reservation/visibility timeout (seconds): a dequeued message is held
        # reserved with available_at = now + timeout; reclaim_expired() returns
        # it once that passes (consumer died mid-flight). <= 0 disables reclaim.
        try:
            self._visibility_timeout = float(config.get(
                "visibility_timeout",
                os.environ.get("TINA4_QUEUE_VISIBILITY_TIMEOUT", "300"),
            ))
        except (TypeError, ValueError):
            self._visibility_timeout = 300.0
        # Seconds to delay a requeued (rejected/retried) job before it is
        # eligible again. Default 0 = available on the very next dequeue, so a
        # fail()'d job retries immediately (matching the file backend) instead
        # of waiting out the visibility window.
        try:
            self._retry_backoff = float(config.get("retry_backoff", 0))
        except (TypeError, ValueError):
            self._retry_backoff = 0.0

        self._pymongo = None
        self._client = None
        self._db = None
        self._collection = None
        self._indexes_created = False

        try:
            import pymongo
            self._pymongo = pymongo
        except ImportError:
            raise ImportError(
                "pymongo is required for the MongoDB queue backend. Install one of:\n"
                "    uv add tina4-python[mongo]    # extra for projects using uv\n"
                "    pip install pymongo           # bare driver\n"
                "    uv add tina4-python[all-db]   # all five database drivers"
            )

    # ── Public Interface ─────────────────────────────────────────

    def connect(self):
        """Connect to MongoDB and ensure indexes exist."""
        if self._uri:
            self._client = self._pymongo.MongoClient(self._uri)
        else:
            kwargs = {"host": self._host, "port": self._port}
            if self._username:
                kwargs["username"] = self._username
            if self._password:
                kwargs["password"] = self._password
            self._client = self._pymongo.MongoClient(**kwargs)

        self._db = self._client[self._db_name]
        self._collection = self._db[self._collection_name]
        self._ensure_indexes()

    def enqueue(self, topic: str, message: dict) -> str:
        """Push a message onto a queue. Returns the message ID."""
        self._ensure_connected()
        msg_id = message.get("id", str(uuid.uuid4()))
        now = _now()

        doc = {
            "_id": msg_id,
            "topic": topic,
            "data": message,
            "status": "pending",
            "priority": message.get("priority", 0),
            "attempts": message.get("attempts", 0),
            "error": None,
            "available_at": now,
            "created_at": now,
            "completed_at": None,
        }
        self._collection.insert_one(doc)
        return msg_id

    def dequeue(self, topic: str) -> dict | None:
        """Atomically claim the next available message. Returns message dict or None.

        The claim advances ``available_at`` to ``now + visibility_timeout`` and
        records ``reserved_at`` so reclaim_expired() can return the job if the
        consumer dies before acknowledge()/reject(). This is the fix for the
        "reserved forever" bug — previously available_at was left unchanged.
        """
        self._ensure_connected()
        now = _now()

        doc = self._collection.find_one_and_update(
            {
                "topic": topic,
                "status": "pending",
                "available_at": {"$lte": now},
            },
            {"$set": {
                "status": "reserved",
                "reserved_at": now,
                "available_at": _future(self._visibility_timeout),
            }},
            sort=[("priority", self._pymongo.DESCENDING), ("created_at", self._pymongo.ASCENDING)],
            return_document=self._pymongo.ReturnDocument.AFTER,
        )
        if doc is None:
            return None

        result = doc.get("data", {})
        result["id"] = doc["_id"]
        # Surface the LIVE document-level attempts/priority, not the push-time
        # snapshot stored inside ``data``. reclaim_expired()/reject() increment
        # the top-level ``attempts``; without this the consumer always saw the
        # original 0, so fail()'s ``attempts >= max_retries`` check never tripped
        # and a job could be retried forever instead of dead-lettering.
        result["attempts"] = doc.get("attempts", result.get("attempts", 0))
        result["priority"] = doc.get("priority", result.get("priority", 0))
        return result

    def reclaim_expired(self, topic: str, max_retries: int) -> int:
        """Return reservations whose visibility window expired (at-least-once).

        A message left ``reserved`` with ``available_at <= now`` had a consumer
        die before acknowledging. Each is atomically flipped back to ``pending``
        with ``attempts`` incremented (so the next dequeue re-delivers it); once
        ``attempts >= max_retries`` it is dead-lettered instead. Returns the
        number reclaimed. Disabled when visibility_timeout <= 0.
        """
        if not self._visibility_timeout or self._visibility_timeout <= 0:
            return 0
        self._ensure_connected()
        reclaimed = 0
        while True:
            now = _now()
            doc = self._collection.find_one_and_update(
                {
                    "topic": topic,
                    "status": "reserved",
                    "available_at": {"$lte": now},
                },
                {"$set": {"status": "pending", "available_at": now, "reserved_at": None},
                 "$inc": {"attempts": 1}},
                sort=[("available_at", self._pymongo.ASCENDING)],
                return_document=self._pymongo.ReturnDocument.AFTER,
            )
            if doc is None:
                break
            reclaimed += 1
            if doc.get("attempts", 0) >= max_retries:
                # Out of retries — move it to the dead-letter queue and remove
                # the original so it is not re-delivered.
                payload = doc.get("data", {})
                self.dead_letter(topic, {
                    "id": doc["_id"],
                    "payload": payload,
                    "priority": doc.get("priority", 0),
                    "attempts": doc.get("attempts", 0),
                    "error": "reservation timed out — consumer did not "
                             "acknowledge within the visibility timeout",
                })
                self._collection.delete_one({"_id": doc["_id"], "topic": topic})
        return reclaimed

    def acknowledge(self, topic: str, message_id: str):
        """Acknowledge a message as processed."""
        self._ensure_connected()
        self._collection.update_one(
            {"_id": message_id, "topic": topic},
            {"$set": {"status": "completed", "completed_at": _now()}},
        )

    def reject(self, topic: str, message_id: str, requeue: bool = True):
        """Reject a message. Optionally requeue it."""
        self._ensure_connected()
        if requeue:
            # Reset available_at so the requeued job is visible again right away
            # (or after retry_backoff). dequeue() pushed available_at out to the
            # reservation expiry; leaving it there stranded a fail()'d job for the
            # full visibility window instead of retrying it on the next pop().
            available = _future(self._retry_backoff) if self._retry_backoff > 0 else _now()
            self._collection.update_one(
                {"_id": message_id, "topic": topic},
                {"$set": {"status": "pending", "available_at": available,
                          "reserved_at": None},
                 "$inc": {"attempts": 1}},
            )
        else:
            self._collection.update_one(
                {"_id": message_id, "topic": topic},
                {"$set": {"status": "failed"}, "$inc": {"attempts": 1}},
            )

    def size(self, topic: str) -> int:
        """Get the number of pending messages in a queue."""
        self._ensure_connected()
        return self._collection.count_documents({"topic": topic, "status": "pending"})

    def clear(self, topic: str):
        """Remove all messages from a queue."""
        self._ensure_connected()
        self._collection.delete_many({"topic": topic})

    def dead_letter(self, topic: str, message: dict):
        """Send a message to the dead letter queue."""
        self._ensure_connected()
        msg_id = message.get("id", str(uuid.uuid4()))
        now = _now()

        doc = {
            "_id": msg_id if msg_id != message.get("id") else str(uuid.uuid4()),
            "topic": f"{topic}.dead_letter",
            "data": message,
            "status": "dead",
            "priority": message.get("priority", 0),
            "attempts": message.get("attempts", 0),
            "error": message.get("error"),
            "available_at": now,
            "created_at": now,
            "completed_at": None,
        }
        self._collection.insert_one(doc)

    def close(self):
        """Close the connection."""
        if self._client is not None:
            self._client.close()
            self._client = None
            self._db = None
            self._collection = None

    # ── Internal ─────────────────────────────────────────────────

    def _ensure_connected(self):
        if self._client is None or self._collection is None:
            self.connect()

    def _ensure_indexes(self):
        if self._indexes_created:
            return
        self._collection.create_index(
            [("topic", self._pymongo.ASCENDING), ("status", self._pymongo.ASCENDING),
             ("available_at", self._pymongo.ASCENDING)],
            name="idx_topic_status_available",
        )
        self._collection.create_index(
            [("topic", self._pymongo.ASCENDING), ("status", self._pymongo.ASCENDING),
             ("priority", self._pymongo.DESCENDING)],
            name="idx_topic_status_priority",
        )
        self._indexes_created = True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future(seconds: float) -> str:
    import time
    return datetime.fromtimestamp(time.time() + seconds, tz=timezone.utc).isoformat()

# Backwards-compatible alias — external code and tests may use the old name.
MongoBackend = MongoConnector
