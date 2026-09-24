"""Regression/guard: Kafka dead-lettering is deterministic.

Bug 3 (book review): "Kafka dead letters unreliable/timing-dependent." The
produce path confirms delivery (KafkaConnector._produce_confirmed reads the
delivery report AND flush's undelivered count, purges + raises on failure) and
the consume path drives the consumer-group assignment in a bounded loop
(TINA4_KAFKA_ASSIGN_TIMEOUT). This test pins the end-to-end determinism: a job
failed past max_retries must ALWAYS be observable via dead_letters() right
after — no sleep, no flakiness.

Run the whole push -> pop -> fail -> dead_letters cycle several times on fresh
topics; a timing-dependent dead-letter path would fail intermittently across
the iterations.

NO MOCK: live Kafka via confluent-kafka.
"""
from __future__ import annotations

import os
import socket
import uuid

import pytest

pytest.importorskip("confluent_kafka")

from tina4_python.queue import Queue


KAFKA_URL = os.environ.get("TINA4_TEST_KAFKA_URL", "127.0.0.1:9092")
KHOST, _, KPORT = KAFKA_URL.partition(":")
KPORT = int(KPORT or "9092")


def _reachable() -> bool:
    try:
        with socket.create_connection((KHOST, KPORT), timeout=2):
            return True
    except OSError:
        return False


if not _reachable():
    if os.environ.get("TINA4_REQUIRE_SERVICES"):
        raise RuntimeError(f"TINA4_REQUIRE_SERVICES set but Kafka unreachable at {KAFKA_URL}")
    pytest.skip(f"Kafka not reachable at {KAFKA_URL}", allow_module_level=True)


def _make_queue():
    os.environ["TINA4_QUEUE_BACKEND"] = "kafka"
    os.environ["TINA4_QUEUE_URL"] = KAFKA_URL
    return Queue(topic=f"kdl_{uuid.uuid4().hex[:10]}", max_retries=1)


class TestKafkaDeadLetterDeterministic:
    def test_dead_letter_is_observable_every_iteration(self):
        """Across 5 fresh topics, a failed-past-retries job is ALWAYS returned
        by dead_letters() on the very next call — no timing flake."""
        for i in range(5):
            q = _make_queue()
            try:
                job_id = q.push({"task": "doomed", "i": i})
                job = q.pop()
                assert job is not None, f"iteration {i}: pop returned None"
                job.fail("boom")

                dead = q.dead_letters()
                ids = [d.id for d in dead]
                assert job_id in ids, (
                    f"iteration {i}: dead letter {job_id} not observable "
                    f"immediately (got {ids}) — non-deterministic dead-lettering"
                )
            finally:
                q.close()

    def test_reject_dead_letter_is_observable(self):
        """reject() (immediate dead-letter, ADR-0023) is equally deterministic
        on Kafka."""
        q = _make_queue()
        try:
            job_id = q.push({"task": "poison"})
            job = q.pop()
            assert job is not None
            job.reject("never parses")
            ids = [d.id for d in q.dead_letters()]
            assert job_id in ids, f"rejected job {job_id} not observable (got {ids})"
        finally:
            q.close()
