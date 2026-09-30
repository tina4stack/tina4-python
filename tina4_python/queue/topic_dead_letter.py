# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# Tina4 Queue — dead-letter helpers shared by the topic-log backends.
"""
Dead-letter enumeration and single-job retry, shared by the broker backends
that keep dead jobs on a ``<topic>.dead_letter`` topic (Kafka and RabbitMQ).

Both backends adapt an external connector to the same ``dequeue``/``enqueue``
interface, so these two operations are pure over that interface — they carry
no broker specifics at all. The broker differences (push, pop, fail, retry,
reject, purge, clear) stay in each backend; only these two identical
drain-filter-requeue loops live here.

A host class must expose ``self._backend`` (a connector with ``dequeue`` and
``enqueue``), ``self._topic`` (str), and ``self._max_retries`` (int).
"""


class TopicDeadLetterMixin:
    """dead_letters() and retry_job() for a ``<topic>.dead_letter`` backend."""

    def dead_letters(self, max_retries: int = None) -> list[dict]:
        """Drain the dead_letter topic, re-enqueue it, and return jobs at/over max_retries.

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
        """Move a job from the dead_letter topic back to the main topic."""
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
