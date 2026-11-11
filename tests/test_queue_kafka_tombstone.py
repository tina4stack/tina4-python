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
        got = [reader.dequeue_record(topic), reader.dequeue_record(topic)]
        assert [m and m.get("n") for m, _ in got] == [1, 2], got
        # The key names the delivered record's own offset, not the tombstone's.
        assert [key for _, key in got] == [f"{topic}:0:0", f"{topic}:0:2"], got
    finally:
        reader.close()


def test_raw_path_still_waits_out_its_deadline_for_a_record_after_tombstones():
    """Past a tombstone the fetch still long-polls, only for the time left.

    Capping the broker's wait must not turn it into no wait: a record produced
    while the capped fetch waits is delivered by that same dequeue().
    """
    import threading
    import time

    _require_broker()
    from confluent_kafka import Producer

    topic = _produce([(b"k0", {"n": 0}), (b"k1", None), (b"k1", None)], one_per_batch=True)
    reader = _raw_connector("tina4_tomb_rawwait_" + secrets.token_hex(8))
    try:
        assert (reader.dequeue(topic) or {}).get("n") == 0
        # Connected before the wait starts, so only the send lands inside it.
        producer = Producer({"bootstrap.servers": KAFKA_BROKERS})
        producer.list_topics(topic, timeout=15)
        def late():
            time.sleep(0.4)
            producer.produce(topic, value=json.dumps({"n": "late"}).encode(), partition=0)
            producer.flush(15)
        sender = threading.Thread(target=late, daemon=True)
        sender.start()
        started = time.monotonic()
        message, key = reader.dequeue_record(topic)
        took = time.monotonic() - started
        sender.join(20)
        assert message == {"n": "late"}, f"the capped fetch did not wait for the record: {message!r}"
        assert key == f"{topic}:0:3", key
        assert took < 1.6, f"dequeue() took {took:.1f}s (deadline ~1s)"
    finally:
        reader.close()


def test_raw_path_cannot_spin_on_a_tombstone_it_cannot_step_past():
    """A tombstone batched ahead of a record must not loop the socket path.

    The fetch hands back the whole batch and the raw decoder reads only its
    first record, so the tombstone comes back at an offset the reader already
    passed. The skip loop must return at once rather than fetch the same offset
    until the deadline. (The record after it is still not delivered by the raw
    path: that is the separate batch-decoding limit, not covered here.)
    """
    import threading
    import time

    _require_broker()
    topic = _produce([(b"k1", None), (b"k2", {"n": 1})])  # one batch
    reader = _raw_connector("tina4_tomb_spin_" + secrets.token_hex(8))
    took = []
    def run():
        for _ in range(2):
            started = time.monotonic()
            reader.dequeue(topic)
            took.append(time.monotonic() - started)
    worker = threading.Thread(target=run, daemon=True)
    try:
        worker.start()
        worker.join(30)
        assert not worker.is_alive(), "dequeue() spun on the tombstone for 30s"
        # The first call includes the metadata round trip; the second must not
        # sit re-fetching the same offset for the whole ~1 s deadline.
        assert took[1] < 0.5, f"dequeue() re-fetched the same offset for {took[1]:.2f}s"
    finally:
        if not worker.is_alive():
            reader.close()


def _committed(topic, group_id):
    """The group's durably committed offset for partition 0 (negative = none)."""
    from confluent_kafka import Consumer, TopicPartition

    probe = Consumer({"bootstrap.servers": KAFKA_BROKERS, "group.id": group_id,
                      "enable.auto.commit": False})
    try:
        return probe.committed([TopicPartition(topic, 0)], timeout=15)[0].offset
    finally:
        probe.close()


@pytest.mark.parametrize("client", ["confluent", "raw"])
def test_dequeue_keeps_its_deadline_under_a_stream_of_tombstones(client):
    """Skipping tombstones must not hold dequeue() past its ~1 s deadline.

    The skip went straight back to poll and never reached the deadline check, so
    while tombstones kept arriving (a burst of CDC deletes) one dequeue() blocked
    for as long as the stream lasted: 8 s for an 8 s stream.
    """
    import threading
    import time

    _require_broker()
    from confluent_kafka import Producer

    topic = _produce([(b"k0", {"n": 0})])
    group = "tina4_tomb_deadline_" + secrets.token_hex(8)
    reader = (KafkaConnector(brokers=KAFKA_BROKERS, group_id=group)
              if client == "confluent" else _raw_connector(group))
    try:
        assert (reader.dequeue(topic) or {}).get("n") == 0  # warm: joined + assigned
        stop = time.monotonic() + 6
        def feed():
            producer = Producer({"bootstrap.servers": KAFKA_BROKERS})
            while time.monotonic() < stop:
                producer.produce(topic, value=None, partition=0)
                producer.flush(5)
                time.sleep(0.1)
        threading.Thread(target=feed, daemon=True).start()
        time.sleep(0.3)
        started = time.monotonic()
        outcome = []
        worker = threading.Thread(target=lambda: outcome.append(reader.dequeue(topic)), daemon=True)
        worker.start()
        worker.join(20)
        took = time.monotonic() - started
        assert not worker.is_alive(), "dequeue() never returned under the tombstone stream"
        assert outcome == [None]
        assert took < 1.6, f"dequeue() took {took:.1f}s under a tombstone stream (deadline ~1s)"
    finally:
        reader.close()


def test_raw_path_keeps_its_deadline_when_the_tombstones_end_the_topic():
    """Past a tombstone the broker's long-poll wait is held to the deadline too.

    The fetch asks the broker to wait up to 5 s for data. After stepping past
    tombstones to the end of the topic, the next fetch sat out the whole 5 s,
    so dequeue() took 5 s instead of its ~1 s.
    """
    import time

    _require_broker()
    topic = _produce([(b"k", {"n": 0})])
    reader = _raw_connector("tina4_tomb_rawtail_" + secrets.token_hex(8))
    try:
        assert (reader.dequeue(topic) or {}).get("n") == 0
        from confluent_kafka import Producer
        producer = Producer({"bootstrap.servers": KAFKA_BROKERS})
        for _ in range(3):
            producer.produce(topic, value=None, partition=0)
            producer.flush(15)
        started = time.monotonic()
        assert reader.dequeue(topic) is None
        took = time.monotonic() - started
        assert took < 1.6, f"dequeue() took {took:.1f}s past the tombstones (deadline ~1s)"
        # The offset moved past them, so the next call does not rescan them.
        assert reader._offsets[topic] == 4
    finally:
        reader.close()


def test_raw_path_steps_over_an_empty_value():
    """The raw decoder treats an empty value like a null one and steps past it.

    Both used to stop the reader on the spot for ever. (The confluent path is
    unchanged for an empty value: it returns no message and moves on.)
    """
    _require_broker()
    from confluent_kafka import Producer

    topic = "tina4_tombstone_" + secrets.token_hex(6)
    producer = Producer({"bootstrap.servers": KAFKA_BROKERS})
    producer.produce(topic, value=b"", partition=0)
    producer.flush(15)
    producer.produce(topic, value=json.dumps({"n": 1}).encode(), partition=0)
    producer.flush(15)
    reader = _raw_connector("tina4_tomb_empty_" + secrets.token_hex(8))
    try:
        assert (reader.dequeue(topic) or {}).get("n") == 1
    finally:
        reader.close()


def test_raw_path_keeps_its_deadline_through_a_backlog_of_tombstones():
    """A backlog of tombstones longer than one deadline is cut off at it.

    Each fetch of a tombstone returns at once, so only the deadline check stops
    the loop: without it one dequeue() walked the whole backlog.
    """
    import time

    from confluent_kafka import Producer

    _require_broker()
    topic = "tina4_tombstone_" + secrets.token_hex(6)
    # One record per batch, so the raw decoder can step over every one.
    producer = Producer({"bootstrap.servers": KAFKA_BROKERS,
                         "batch.num.messages": 1, "linger.ms": 0})
    total = 6000
    for i in range(total):
        producer.produce(topic, value=None, partition=0)
        if i % 500 == 0:
            producer.poll(0)
    producer.flush(60)
    reader = _raw_connector("tina4_tomb_backlog_" + secrets.token_hex(8))
    try:
        started = time.monotonic()
        assert reader.dequeue(topic) is None
        took = time.monotonic() - started
        assert took < 1.6, f"dequeue() took {took:.1f}s on a tombstone backlog (deadline ~1s)"
        assert 0 < reader._offsets[topic] < total, reader._offsets
    finally:
        reader.close()


def test_a_fresh_process_gets_past_a_tombstone_through_the_normal_ack():
    """Nothing commits on the tombstone path; acknowledging the record after it
    commits past both, so a restart in the same group neither stops at the
    tombstone nor redelivers anything."""
    _require_broker()
    topic = _produce([(b"k1", {"n": 1}), (b"k1", None), (b"k2", {"n": 2})])
    group = "tina4_tomb_restart_" + secrets.token_hex(8)
    first = KafkaConnector(brokers=KAFKA_BROKERS, group_id=group)
    try:
        message, key = first.dequeue_record(topic)
        assert message == {"n": 1}
        first.acknowledge(topic, key)
        assert _committed(topic, group) == 1  # at the tombstone
    finally:
        first.close()
    second = KafkaConnector(brokers=KAFKA_BROKERS, group_id=group)
    try:
        message, key = second.dequeue_record(topic)
        assert message == {"n": 2}, f"a restart did not get past the tombstone: {message!r}"
        second.acknowledge(topic, key)
        assert _committed(topic, group) == 3
    finally:
        second.close()
    third = KafkaConnector(brokers=KAFKA_BROKERS, group_id=group)
    try:
        assert third.dequeue_record(topic) == (None, None)
    finally:
        third.close()
