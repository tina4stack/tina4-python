"""Regression: size("dead"/"failed"/"dead_letter") counts the dead-letter
store on Mongo and RabbitMQ; Kafka honestly returns 0 (ADR-0022 dec 5).

Bug 2 (book review). The Mongo, RabbitMQ and Kafka adapters all did
``if status != "pending": return 0`` — so size("dead") reported 0 while
dead_letters() returned N. ADR-0022 decision 7: size(status) must never answer
a different question than the one asked.

Decision (coordinator, this pass):
  * Mongo + RabbitMQ CAN enumerate their dead-letter store, so size("dead")
    must equal len(dead_letters()).
  * Kafka STAYS 0: ADR-0022 decision 5 — "Kafka size() returns 0. A log has no
    queue depth." That 0 is the documented answer, NOT a bug; the test pins it
    so a future change cannot silently regress the ADR.

The file backend already counts correctly and is the reference (see
lite_backend.size); it is covered by the existing queue suite.

NO MOCKS: live MongoDB / RabbitMQ / Kafka. Each class guards its own service;
under TINA4_REQUIRE_SERVICES an unreachable service FAILS rather than skips.
"""
from __future__ import annotations

import os
import socket
import uuid

import pytest


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def _guard(host: str, port: int, name: str):
    if _reachable(host, port):
        return
    if os.environ.get("TINA4_REQUIRE_SERVICES"):
        raise RuntimeError(f"TINA4_REQUIRE_SERVICES set but {name} unreachable at {host}:{port}")
    pytest.skip(f"{name} not reachable at {host}:{port}", allow_module_level=False)


MONGO_HOST = os.environ.get("TINA4_TEST_MONGO_HOST", "127.0.0.1")
MONGO_PORT = int(os.environ.get("TINA4_TEST_MONGO_PORT", "27017"))
RABBIT_HOST = os.environ.get("TINA4_TEST_RABBITMQ_HOST", "127.0.0.1")
RABBIT_PORT = int(os.environ.get("TINA4_TEST_RABBITMQ_PORT", "5672"))
KAFKA_URL = os.environ.get("TINA4_TEST_KAFKA_URL", "127.0.0.1:9092")
KAFKA_HOST, _, KAFKA_PORT = KAFKA_URL.partition(":")
KAFKA_PORT = int(KAFKA_PORT or "9092")


def _prime_dead_letter(q):
    """push -> pop -> fail with max_retries=1 -> one dead letter."""
    q.push({"task": "doomed"})
    job = q.pop()
    assert job is not None, "prime failed: pop returned None"
    job.fail("boom")


class TestMongoSizeDead:
    @pytest.fixture
    def q(self, monkeypatch):
        pytest.importorskip("pymongo")
        _guard(MONGO_HOST, MONGO_PORT, "MongoDB")
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "mongodb")
        monkeypatch.setenv("TINA4_QUEUE_URL", f"mongodb://{MONGO_HOST}:{MONGO_PORT}")
        from tina4_python.queue import Queue
        queue = Queue(topic=f"size_dead_{uuid.uuid4().hex[:10]}", max_retries=1)
        yield queue
        try:
            queue._backend._backend._ensure_connected()
            coll = queue._backend._backend._collection
            coll.delete_many({"topic": queue.topic})
            coll.delete_many({"topic": f"{queue.topic}.dead_letter"})
            queue.close()
        except Exception:
            pass

    def test_positive_size_dead_counts_store(self, q):
        _prime_dead_letter(q)
        _prime_dead_letter(q)
        assert len(q.dead_letters()) == 2
        assert q.size("dead") == 2, "Mongo size('dead') must count the dead-letter store"
        assert q.size("failed") == 2, "'failed' is an alias for the dead count"
        assert q.size("dead_letter") == 2

    def test_negative_size_dead_zero_when_empty(self, q):
        assert q.size("dead") == 0
        q.push({"task": "live"})
        assert q.size("pending") == 1
        assert q.size("dead") == 0, "a pending job must not count under 'dead'"


class TestRabbitMQSizeDead:
    @pytest.fixture
    def q(self, monkeypatch):
        _guard(RABBIT_HOST, RABBIT_PORT, "RabbitMQ")
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "rabbitmq")
        monkeypatch.setenv("TINA4_QUEUE_URL", f"amqp://guest:guest@{RABBIT_HOST}:{RABBIT_PORT}")
        from tina4_python.queue import Queue
        queue = Queue(topic=f"size_dead_{uuid.uuid4().hex[:10]}", max_retries=1)
        yield queue
        try:
            queue.clear()
            queue.close()
        except Exception:
            pass

    def test_positive_size_dead_counts_store(self, q):
        _prime_dead_letter(q)
        assert q.size("dead") == 1, "RabbitMQ size('dead') must count the .dead_letter queue depth"
        assert q.size("failed") == 1

    def test_negative_size_dead_zero_when_empty(self, q):
        assert q.size("dead") == 0


class TestKafkaSizeDeadStaysZero:
    @pytest.fixture
    def q(self, monkeypatch):
        pytest.importorskip("confluent_kafka")
        _guard(KAFKA_HOST, KAFKA_PORT, "Kafka")
        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "kafka")
        monkeypatch.setenv("TINA4_QUEUE_URL", KAFKA_URL)
        from tina4_python.queue import Queue
        queue = Queue(topic=f"size_dead_{uuid.uuid4().hex[:10]}", max_retries=1)
        yield queue
        try:
            queue.close()
        except Exception:
            pass

    def test_kafka_size_dead_is_zero_documented(self, q):
        """ADR-0022 dec 5: Kafka size() returns 0 (a log has no depth). Even
        with a real dead letter present, size('dead') is the documented 0 —
        pinning it so the answer can't silently drift from the ADR."""
        _prime_dead_letter(q)
        assert q.size("dead") == 0, "Kafka size('dead') stays 0 per ADR-0022 decision 5"
        assert q.size("failed") == 0
