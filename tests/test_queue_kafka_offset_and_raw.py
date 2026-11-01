# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Kafka consumer offset-reset override (#263) and raw producer option (#264).

#263: the confluent consumer hardcoded ``auto.offset.reset: earliest``, so every
NEW consumer group replayed the whole retained backlog on first start with no way
to opt into 'latest'. It now reads TINA4_KAFKA_AUTO_OFFSET_RESET (then bare
KAFKA_AUTO_OFFSET_RESET), defaulting to earliest so current behaviour is unchanged.

#264: the Kafka adapter always wrapped the value in the {payload, priority,
attempts} job envelope, which breaks a non-Tina4 consumer that expects a specific
top-level schema. push(raw=True) now emits the value exactly as given — no
envelope, no injected id. It is a Kafka-only option; the file/rabbitmq/mongodb
backends refuse raw=True by name rather than silently ignore it.

The offset-reset resolution and the raw refusals are pure and run everywhere. The
live round trips need a real broker (TINA4_KAFKA_BROKERS) and confluent-kafka.
"""
import os
import secrets

import pytest

from tina4_python.queue import Queue
from tina4_python.queue_backends import KafkaConnector

KAFKA_BROKERS = os.environ.get("TINA4_KAFKA_BROKERS", "")


# ── #263: auto.offset.reset resolution (pure, runs everywhere) ───────────────

def test_offset_reset_defaults_to_earliest(monkeypatch):
    monkeypatch.delenv("TINA4_KAFKA_AUTO_OFFSET_RESET", raising=False)
    monkeypatch.delenv("KAFKA_AUTO_OFFSET_RESET", raising=False)
    assert KafkaConnector._offset_reset() == "earliest"


def test_offset_reset_honours_tina4_env(monkeypatch):
    monkeypatch.setenv("TINA4_KAFKA_AUTO_OFFSET_RESET", "latest")
    monkeypatch.delenv("KAFKA_AUTO_OFFSET_RESET", raising=False)
    assert KafkaConnector._offset_reset() == "latest"


def test_offset_reset_falls_back_to_bare_kafka_env(monkeypatch):
    monkeypatch.delenv("TINA4_KAFKA_AUTO_OFFSET_RESET", raising=False)
    monkeypatch.setenv("KAFKA_AUTO_OFFSET_RESET", "latest")
    assert KafkaConnector._offset_reset() == "latest"


def test_tina4_env_wins_over_bare_kafka_env(monkeypatch):
    monkeypatch.setenv("TINA4_KAFKA_AUTO_OFFSET_RESET", "latest")
    monkeypatch.setenv("KAFKA_AUTO_OFFSET_RESET", "earliest")
    assert KafkaConnector._offset_reset() == "latest"


def test_blank_offset_reset_falls_through_to_default(monkeypatch):
    monkeypatch.setenv("TINA4_KAFKA_AUTO_OFFSET_RESET", "")
    monkeypatch.delenv("KAFKA_AUTO_OFFSET_RESET", raising=False)
    assert KafkaConnector._offset_reset() == "earliest"


# ── #264: raw is Kafka-only — other backends refuse by name (real, offline) ──

def test_push_raw_on_file_backend_is_refused_by_name():
    queue = Queue(topic="tina4_raw_refusal_" + secrets.token_hex(4), backend="file")
    try:
        with pytest.raises(NotImplementedError) as raised:
            queue.push({"event": "x"}, raw=True)
        message = str(raised.value)
        assert "file queue backend" in message, message
        assert "raw=True" in message, message
    finally:
        queue.close()


def test_push_without_raw_on_file_backend_is_unchanged():
    """Positive control: the default raw=False path is untouched."""
    queue = Queue(topic="tina4_raw_default_" + secrets.token_hex(4), backend="file")
    try:
        job_id = queue.push({"event": "x"})
        assert job_id
        job = queue.pop()
        assert job is not None and job.data == {"event": "x"}
        job.complete()
    finally:
        queue.close()


# ── #264 live: a raw produce carries no envelope and no injected id ──────────

def test_raw_push_emits_unenveloped_value(monkeypatch):
    pytest.importorskip("confluent_kafka", reason="confluent-kafka not installed (uv sync --extra test)")
    if not KAFKA_BROKERS:
        pytest.skip("kafka not set: export TINA4_KAFKA_BROKERS (e.g. 127.0.0.1:9092)")
    monkeypatch.delenv("TINA4_QUEUE_URL", raising=False)
    monkeypatch.setenv("TINA4_KAFKA_GROUP_ID", "tina4_raw_" + secrets.token_hex(8))
    topic = "tina4_raw_" + secrets.token_hex(6)
    external_schema = {"event_type": "order.created", "order_id": 42, "amount": 9.99}

    producer = Queue(topic=topic, backend="kafka")
    try:
        producer.push(external_schema, raw=True)
    finally:
        producer.close()

    # Read the raw value with the low-level connector — exactly what a non-Tina4
    # consumer would see off the wire. It must be the schema as given: no
    # "payload"/"priority"/"attempts" envelope and no injected "id".
    reader = KafkaConnector(brokers=KAFKA_BROKERS, group_id="tina4_raw_r_" + secrets.token_hex(8))
    try:
        value = reader.dequeue(topic)
        assert value == external_schema, value
        assert "payload" not in value and "id" not in value, value
    finally:
        reader.close()


def test_non_raw_push_still_carries_the_envelope(monkeypatch):
    """Positive control for #264: the default push is still enveloped + id'd."""
    pytest.importorskip("confluent_kafka", reason="confluent-kafka not installed (uv sync --extra test)")
    if not KAFKA_BROKERS:
        pytest.skip("kafka not set: export TINA4_KAFKA_BROKERS (e.g. 127.0.0.1:9092)")
    monkeypatch.delenv("TINA4_QUEUE_URL", raising=False)
    monkeypatch.setenv("TINA4_KAFKA_GROUP_ID", "tina4_env_" + secrets.token_hex(8))
    topic = "tina4_env_" + secrets.token_hex(6)

    producer = Queue(topic=topic, backend="kafka")
    try:
        producer.push({"event": "y"})
    finally:
        producer.close()

    reader = KafkaConnector(brokers=KAFKA_BROKERS, group_id="tina4_env_r_" + secrets.token_hex(8))
    try:
        value = reader.dequeue(topic)
        assert value.get("payload") == {"event": "y"}, value
        assert "id" in value, value
    finally:
        reader.close()
