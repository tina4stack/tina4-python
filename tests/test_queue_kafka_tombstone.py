# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Kafka tombstone (null-value record) must not crash the consumer (#303).

A tombstone is a record whose value is ``null``. They are normal on Kafka:
Debezium emits them for deletes, and log-compacted topics use them as delete
markers. The confluent path decoded ``msg.value().decode("utf-8")``; for a
tombstone ``msg.value()`` is ``None``, so ``None.decode()`` raised
``AttributeError`` -- NOT in the ``except`` -- and the exception escaped
``consume()``, killing the consumer thread. Because the tombstone sits at the
committed offset it is a poison pill: every restart re-reads it and re-crashes,
so the topic silently stops consuming.

These are REAL round trips against a live broker (no mock): a real tombstone is
produced with confluent-kafka's own Producer (value=None is exactly what Debezium
writes), then consumed through the Tina4 connector. They are gated on
TINA4_KAFKA_BROKERS + confluent-kafka, the same gate as the other live Kafka
tests. Mutation proof: revert the null guard in ``_dequeue`` and
``test_tombstone_does_not_crash_consumer`` raises AttributeError instead of
passing.
"""
import json
import os
import secrets

import pytest

from tina4_python.queue_backends import KafkaConnector

KAFKA_BROKERS = os.environ.get("TINA4_KAFKA_BROKERS", "")


def _require_broker():
    pytest.importorskip(
        "confluent_kafka",
        reason="confluent-kafka not installed (uv sync --extra test)",
    )
    if not KAFKA_BROKERS:
        pytest.skip("kafka not set: export TINA4_KAFKA_BROKERS (e.g. 127.0.0.1:9092)")


def _produce(records):
    """Produce (key, value) pairs with the REAL confluent Producer. A value of
    None is a genuine tombstone on the wire, exactly like a Debezium delete."""
    from confluent_kafka import Producer

    topic = "tina4_tombstone_" + secrets.token_hex(6)
    producer = Producer({"bootstrap.servers": KAFKA_BROKERS})
    for key, value in records:
        payload = None if value is None else json.dumps(value).encode("utf-8")
        producer.produce(topic, key=key, value=payload)
    producer.flush(15)
    return topic


def _drain(reader, topic, want_key, max_calls=12):
    """Call dequeue up to max_calls times, returning the first message whose
    'event' equals want_key (or None). Never swallows an exception -- a crash in
    _dequeue propagates, which is the whole point of the regression."""
    for _ in range(max_calls):
        message = reader.dequeue(topic)
        if isinstance(message, dict) and message.get("event") == want_key:
            return message
    return None


def test_tombstone_does_not_crash_consumer():
    """A tombstone at the committed offset is skipped, and a following real
    record is still delivered -- the consumer never crashes."""
    _require_broker()
    # Tombstone FIRST (the poison-pill position: at the committed offset), then a
    # real record after it.
    topic = _produce([
        (b"deleted-key", None),
        (b"live-key", {"event": "after_tombstone", "n": 1}),
    ])

    reader = KafkaConnector(
        brokers=KAFKA_BROKERS,
        group_id="tina4_tomb_r_" + secrets.token_hex(8),
    )
    try:
        # Without the guard this raises AttributeError on the tombstone. With it,
        # the tombstone yields no job (None) and the consumer advances to the real
        # record, which we must be able to read.
        delivered = _drain(reader, topic, "after_tombstone")
        assert delivered is not None, "real record after the tombstone was not delivered"
        assert delivered["n"] == 1, delivered
    finally:
        reader.close()


def test_only_a_tombstone_yields_no_job_and_no_crash():
    """A topic holding ONLY a tombstone returns None (no job) without raising --
    the degenerate poison-pill case on its own."""
    _require_broker()
    topic = _produce([(b"deleted-key", None)])

    reader = KafkaConnector(
        brokers=KAFKA_BROKERS,
        group_id="tina4_tomb_only_" + secrets.token_hex(8),
    )
    try:
        # One dequeue consumes the tombstone and must return None, not crash.
        assert reader.dequeue(topic) is None
    finally:
        reader.close()
