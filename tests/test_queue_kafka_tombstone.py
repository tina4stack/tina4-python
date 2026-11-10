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


def _produce(records, one_per_batch=False):
    """Produce (key, value) pairs with the REAL confluent Producer. A value of
    None is a genuine tombstone on the wire, exactly like a Debezium delete.

    one_per_batch flushes after every record so each lands in its own record
    batch: the raw socket path decodes only the first record of a fetched batch.
    """
    from confluent_kafka import Producer

    topic = "tina4_tombstone_" + secrets.token_hex(6)
    producer = Producer({"bootstrap.servers": KAFKA_BROKERS})
    for key, value in records:
        payload = None if value is None else json.dumps(value).encode("utf-8")
        producer.produce(topic, key=key, value=payload, partition=0)
        if one_per_batch:
            producer.flush(15)
    producer.flush(15)
    return topic


def _raw_connector(group_id):
    """The zero-dependency socket path, selected the way TestKafkaRawPathLive
    does: the flag the constructor sets from its import probe."""
    reader = KafkaConnector(brokers=KAFKA_BROKERS, group_id=group_id)
    reader._use_confluent = False
    reader._confluent = None
    return reader


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


def test_single_pass_drain_reads_past_a_tombstone(monkeypatch):
    """consume(poll_interval=0) drains to the end of the topic, tombstone or not.

    Answering a tombstone with "no message" reads as an empty queue, so a
    single-pass drain stopped at it and left every later record behind; a fresh
    process (a cron drain) resumed at the tombstone's committed offset and
    stopped there again, every run.
    """
    _require_broker()
    from tina4_python.queue import Queue

    topic = _produce([
        (b"k1", {"n": 1}),
        (b"k1", None),
        (b"k2", {"n": 2}),
    ])
    monkeypatch.setenv("TINA4_KAFKA_GROUP_ID", "tina4_tomb_drain_" + secrets.token_hex(8))
    queue = Queue(topic=topic, backend="kafka")
    try:
        got = []
        for job in queue.consume(topic, poll_interval=0):
            got.append(job.data.get("n"))
            job.complete()
        assert got == [1, 2], f"the drain stopped at the tombstone: {got}"
    finally:
        queue.close()


def test_raw_path_reads_past_a_tombstone():
    """The socket path steps over a tombstone instead of re-fetching it for ever.

    _decode_first_record answered a null value with None, so dequeue() returned
    None without moving its offset: every later fetch asked for the tombstone
    again, and the record after it was never delivered. No exception, so nothing
    said the consumer had stopped.
    """
    _require_broker()
    topic = _produce([
        (b"k1", {"n": 1}),
        (b"k1", None),
        (b"k2", {"n": 2}),
    ], one_per_batch=True)
    reader = _raw_connector("tina4_tomb_raw_" + secrets.token_hex(8))
    try:
        got = [reader.dequeue(topic), reader.dequeue(topic)]
        assert [m and m.get("n") for m in got] == [1, 2], got
    finally:
        reader.close()


def test_raw_path_cannot_spin_on_a_tombstone_it_cannot_step_past():
    """A tombstone batched ahead of a record must not loop the socket path.

    The fetch hands back the whole batch and the decoder reads its first record,
    so the tombstone can come back at an offset the reader already passed. The
    skip loop must return rather than fetch the same offset for ever. Run in a
    thread with a cap so a regression fails here instead of hanging the suite.
    """
    import threading

    _require_broker()
    topic = _produce([(b"k1", None), (b"k2", {"n": 1})])  # one batch
    reader = _raw_connector("tina4_tomb_spin_" + secrets.token_hex(8))
    outcome = []
    worker = threading.Thread(
        target=lambda: outcome.extend([reader.dequeue(topic), reader.dequeue(topic)]),
        daemon=True,
    )
    try:
        worker.start()
        worker.join(30)
        assert not worker.is_alive(), "dequeue() spun on the tombstone for 30s"
    finally:
        if not worker.is_alive():
            reader.close()
