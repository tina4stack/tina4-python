"""A Kafka push that no broker confirmed is a failure, never a message id.

THE BUG, MEASURED on the lab at v3 (958377c): with confluent-kafka installed,
``Queue(backend="kafka").push(...)`` against a REAL closed port waited out
``flush(timeout=5)`` and then returned a message id - a job that exists
nowhere, reported as queued. ``flush()`` returns how many messages are still
undelivered and the delivery report carries the broker's error; the code
looked at neither.

The fix reads both: a message not confirmed within the timeout is purged from
the producer's queue (so it cannot surface later as a surprise duplicate) and
push raises "Kafka connection failed: ...". The positive - a real push to the
lab Kafka is confirmed and read back - is TestKafkaConnectorLive in
test_queue_backends.py, plus the round trip below through the Queue API.
"""
import os
import secrets
import socket
import time

import pytest

from tina4_python.queue import Queue

KAFKA_BROKERS = os.environ.get("TINA4_KAFKA_BROKERS", "")


def _closed_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_push_to_an_unreachable_broker_raises(monkeypatch):
    pytest.importorskip("confluent_kafka", reason="confluent-kafka not installed (uv sync --extra test)")
    port = _closed_port()
    monkeypatch.delenv("TINA4_QUEUE_URL", raising=False)
    monkeypatch.setenv("TINA4_KAFKA_BROKERS", f"127.0.0.1:{port}")
    queue = Queue(topic="tina4_unreachable_" + secrets.token_hex(6), backend="kafka")
    try:
        started = time.monotonic()
        with pytest.raises(RuntimeError) as raised:
            queue.push({"job": "never-delivered"})
        assert time.monotonic() - started < 30
        message = str(raised.value)
        assert message.startswith("Kafka connection failed:"), message
        assert f"127.0.0.1:{port}" in message, message
    finally:
        queue.close()


def test_push_to_the_real_broker_is_confirmed_and_read_back(monkeypatch):
    """Positive control: delivery confirmation does not break a real push."""
    pytest.importorskip("confluent_kafka", reason="confluent-kafka not installed (uv sync --extra test)")
    if not KAFKA_BROKERS:
        pytest.skip("kafka not set: export TINA4_KAFKA_BROKERS (e.g. 127.0.0.1:9092)")
    monkeypatch.delenv("TINA4_QUEUE_URL", raising=False)
    monkeypatch.setenv("TINA4_KAFKA_GROUP_ID", "tina4_test_" + secrets.token_hex(8))
    topic = "tina4_confirmed_" + secrets.token_hex(6)
    producer = Queue(topic=topic, backend="kafka")
    try:
        job_id = producer.push({"job": "delivered"})
    finally:
        producer.close()
    consumer = Queue(topic=topic, backend="kafka")
    try:
        job = consumer.pop()
        assert job is not None and job.id == job_id and job.payload == {"job": "delivered"}
        job.complete()
    finally:
        consumer.close()
