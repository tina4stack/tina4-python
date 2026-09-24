# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

class Job:
    """A single queue job."""

    def __init__(self, queue, job_id, topic: str, data: dict,
                 priority: int = 0, attempts: int = 0, error: str | None = None):
        self.queue = queue
        self.id = job_id
        self.topic = topic
        self.payload = data
        self.priority = priority
        self.attempts = attempts
        # Populated by fail()/reject() — why the job last died. Surfaces
        # in dead_letters() so consumers can see the failure reason
        # without trawling logs.
        self.error: str | None = error

    @property
    def data(self):
        """Alias for payload — deprecated, use .payload instead."""
        return self.payload

    def complete(self):
        """Mark job as completed. Terminal — the job is done and removed."""
        self.queue._backend.complete(self)

    def fail(self, error: str = ""):
        """Record a failed attempt.

        Increments ``attempts``. If the job still has retries left
        (``attempts < max_retries``) it is automatically re-enqueued to the
        pending queue, so the next ``pop()``/``consume()`` picks it up again
        (after the queue's ``retry_backoff`` delay, if any). Once it has been
        attempted ``max_retries`` times it is moved to the dead-letter store,
        where ``queue.dead_letters()`` returns it. No manual ``retry_failed()``
        is required.
        """
        self.queue._backend.fail(self, error)

    def reject(self, reason: str = ""):
        """Reject a job permanently — dead-letter it NOW, no retry (ADR-0023).

        Distinct from ``fail()``: ``fail()`` records a failed attempt and only
        dead-letters once ``max_retries`` is exhausted, so the job is retried
        first. ``reject()`` is for a message the consumer KNOWS is poison (a
        payload that will never parse) — it goes straight to the dead-letter
        store on this call, without burning the retry budget. This is AMQP's
        ``basic.reject(requeue=false)`` semantics, and matches SQS / Celery /
        Spring AMQP. Was a literal alias for ``fail()`` before 3.13.139.
        """
        self.queue._backend.reject(self, reason)

    def retry(self, delay_seconds: int = 0):
        """Re-queue this job with optional delay."""
        self.queue._backend.retry(self, delay_seconds)

    def to_array(self) -> list:
        """Return job fields as a flat list of values."""
        return [self.id, self.topic, self.payload, self.priority, self.attempts]

    def to_hash(self) -> dict:
        """Return job as a dict."""
        return {
            "id": self.id,
            "topic": self.topic,
            "payload": self.payload,
            "priority": self.priority,
            "attempts": self.attempts,
            "error": self.error,
        }

    def to_json(self) -> str:
        """Return job as a JSON string."""
        import json
        return json.dumps(self.to_hash())
