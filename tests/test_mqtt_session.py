"""MQTT sessions and resilience -- real broker, no mocks.

Mirrors tina4-ruby spec/mqtt_session_spec.rb. Drives a real Mosquitto on 1883:
the offline replay a durable session provides, and the awkward ordering (queued
QoS 1 messages arriving BEFORE the SUBACK on a clean_session=False resume) that
is exactly why the ack-wait inbox has to cover SUBSCRIBE and not just PUBLISH.
"""
from __future__ import annotations

import socket
import uuid

import pytest

from tina4_python.mqtt import Mqtt

BROKER = "mqtt://127.0.0.1:1883"


def _broker_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 1883), timeout=1):
            return True
    except OSError:
        return False


requires_broker = pytest.mark.skipif(not _broker_up(), reason="no MQTT broker on 127.0.0.1:1883")


@requires_broker
class TestDurableSession:
    def test_replays_qos1_messages_published_while_offline_in_order(self):
        run = uuid.uuid4().hex[:8]
        topic = f"tina4/pytest/session/{run}/offline"
        durable_id = f"tina4-pytest-durable-{run}"

        # Establish the durable subscription, then go offline.
        first = Mqtt(url=BROKER, client_id=durable_id, clean_session=False)
        first.subscribe(topic, qos=1)
        first.disconnect()

        # Publish while the durable subscriber is offline.
        pub = Mqtt(url=BROKER, client_id=f"tina4-pytest-pub-{run}")
        for i in range(3):
            pub.publish(topic, f'{{"n":{i}}}', qos=1)
        pub.disconnect()

        # Resume the SAME client id, clean_session=False -- the broker hands over
        # what it queued for us while we were gone.
        resumed = Mqtt(url=BROKER, client_id=durable_id, clean_session=False)
        replayed = [resumed.receive(timeout=5).text() for _ in range(3)]
        assert replayed == ['{"n":0}', '{"n":1}', '{"n":2}']
        resumed.disconnect()

    def test_replayed_publishes_stay_out_of_the_suback_wait(self):
        # On a clean_session=False resume the broker starts replaying queued QoS 1
        # messages the moment it sends anything -- a replayed PUBLISH can arrive
        # BEFORE the SUBACK of a fresh subscribe. The ack-wait inbox must park it,
        # not mistake it for the SUBACK, or the durable replay is lost.
        run = uuid.uuid4().hex[:8]
        topic = f"tina4/pytest/session/{run}/replay-suback"
        durable_id = f"tina4-pytest-replay-{run}"

        first = Mqtt(url=BROKER, client_id=durable_id, clean_session=False)
        first.subscribe(topic, qos=1)
        first.disconnect()

        pub = Mqtt(url=BROKER, client_id=f"tina4-pytest-replay-pub-{run}")
        for i in range(3):
            pub.publish(topic, f"queued-{i}", qos=1)
        pub.disconnect()

        # Resume and immediately issue ANOTHER subscribe: its SUBACK now competes
        # with the replayed PUBLISHes already streaming in.
        resumed = Mqtt(url=BROKER, client_id=durable_id, clean_session=False)
        assert resumed.subscribe(topic, qos=1) == 1  # must not choke on an interleaved PUBLISH
        replayed = [resumed.receive(timeout=5).text() for _ in range(3)]
        assert replayed == ["queued-0", "queued-1", "queued-2"]
        resumed.disconnect()

    def test_clean_session_true_does_not_replay(self):
        # The flag is real: a default clean_session=True must NOT look like a
        # durable session, or an app would silently lose data it thought queued.
        run = uuid.uuid4().hex[:8]
        topic = f"tina4/pytest/session/{run}/clean"
        clean_id = f"tina4-pytest-clean-{run}"

        first = Mqtt(url=BROKER, client_id=clean_id, clean_session=True)
        first.subscribe(topic, qos=1)
        first.disconnect()  # clean_session=True -> broker throws the subscription away

        pub = Mqtt(url=BROKER, client_id=f"tina4-pytest-clean-pub-{run}")
        pub.publish(topic, "lost", qos=1)
        pub.disconnect()

        resumed = Mqtt(url=BROKER, client_id=clean_id, clean_session=True)
        resumed.subscribe(topic, qos=1)
        with pytest.raises(Exception):  # nothing was queued -> times out
            resumed.receive(timeout=1)
        resumed.disconnect()
