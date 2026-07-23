"""MQTT 3.1.1 client -- real-broker tests (no mocks).

Mirrors tina4-ruby spec/mqtt_spec.rb. Every network test hits a REAL Eclipse
Mosquitto on 127.0.0.1:1883 (the anonymous listener from
plan/v3/spikes/mqtt-infra.sh). No test double stands in for the broker: a
mock-passing MQTT test proves nothing about the wire protocol, which is the
whole point of a hand-rolled client. Tests that need no broker (varint, url
parse, QoS-2 refusal) are pure-logic and use no double.

The broker-backed tests skip cleanly when nothing is listening on 1883, and the
TINA4_REQUIRE_SERVICES gate (conftest) turns that skip into a failure in CI.
"""
from __future__ import annotations

import socket
import time
import uuid

import pytest

from tina4_python.mqtt import Mqtt, MqttMessage, MqttError

BROKER = "mqtt://127.0.0.1:1883"


def _broker_up(host: str = "127.0.0.1", port: int = 1883) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


requires_broker = pytest.mark.skipif(not _broker_up(), reason="no MQTT broker on 127.0.0.1:1883")


def _topic(suffix: str) -> str:
    return f"tina4/pytest/{uuid.uuid4().hex[:8]}/{suffix}"


# -- pure logic (no broker) -------------------------------------------------

class TestRemainingLengthVarint:
    @pytest.mark.parametrize("value,expected", [
        (0, b"\x00"), (127, b"\x7f"), (128, b"\x80\x01"), (16383, b"\xff\x7f"),
        (268_435_455, b"\xff\xff\xff\x7f"),
    ])
    def test_encode(self, value, expected):
        assert Mqtt.encode_remaining_length(value) == expected

    def test_rejects_out_of_range(self):
        with pytest.raises(ValueError):
            Mqtt.encode_remaining_length(268_435_456)
        with pytest.raises(ValueError):
            Mqtt.encode_remaining_length(-1)


class TestParseUrl:
    def test_plain(self):
        assert Mqtt.parse_url("mqtt://host:1883") == {
            "host": "host", "port": 1883, "tls": False, "username": None, "password": None}

    def test_defaults_port_by_scheme(self):
        assert Mqtt.parse_url("mqtt://host")["port"] == 1883
        assert Mqtt.parse_url("mqtts://host")["port"] == 8883
        assert Mqtt.parse_url("mqtts://host")["tls"] is True

    def test_userinfo_percent_decoded(self):
        p = Mqtt.parse_url("mqtt://user:p%40ss%2Fword@host:1883")
        assert p["username"] == "user" and p["password"] == "p@ss/word"

    def test_plus_is_not_a_space(self):
        # unquote, NOT unquote_plus: a "+" in a password must survive verbatim.
        assert Mqtt.parse_url("mqtt://u:a+b@host")["password"] == "a+b"

    def test_ipv6_bracketed(self):
        p = Mqtt.parse_url("mqtt://[::1]:1883")
        assert p["host"] == "::1" and p["port"] == 1883

    def test_last_at_wins_for_unencoded_at_in_password(self):
        p = Mqtt.parse_url("mqtt://u:pa@ss@host:1883")
        assert p["host"] == "host" and p["password"] == "pa@ss"

    def test_empty_url_raises(self):
        with pytest.raises(ValueError):
            Mqtt.parse_url("   ")

    def test_unsupported_scheme_raises(self):
        with pytest.raises(ValueError):
            Mqtt.parse_url("ws://host:9001")


class TestQos2RefusedLoudly:
    def test_publish_qos2_raises_naming_limit_and_alternative(self):
        m = Mqtt(connect=False)
        with pytest.raises(ValueError) as exc:
            m.publish("t", "x", qos=2)
        text = str(exc.value)
        assert "QoS 2" in text                          # names the limit
        assert "idempotent" in text and "device_timestamp" in text  # names the alternative

    def test_subscribe_qos2_raises(self):
        m = Mqtt(connect=False)
        with pytest.raises(ValueError):
            m.subscribe("t", qos=2)

    def test_invalid_qos_raises(self):
        m = Mqtt(connect=False)
        with pytest.raises(ValueError):
            m.publish("t", "x", qos=5)


class TestConstruction:
    def test_password_without_username_raises(self):
        with pytest.raises(ValueError):
            Mqtt(url="mqtt://host", password="secret", connect=False)

    def test_generates_client_id(self):
        m = Mqtt(connect=False)
        assert m.client_id.startswith("tina4-")

    def test_repr_never_leaks_password(self):
        m = Mqtt(url="mqtt://user:topsecret@host", connect=False)
        assert "topsecret" not in repr(m)


# -- real broker ------------------------------------------------------------

@requires_broker
class TestLiveBroker:
    def test_connect_and_disconnect(self):
        m = Mqtt(url=BROKER, client_id="tina4-pytest-conn")
        assert m.connected is True
        m.disconnect()
        assert m.connected is False

    def test_publish_qos0_returns_none(self):
        m = Mqtt(url=BROKER)
        assert m.publish(_topic("q0"), "hello", qos=0) is None
        m.disconnect()

    def test_publish_qos1_returns_packet_id_and_pubacks(self):
        m = Mqtt(url=BROKER)
        pid = m.publish(_topic("q1"), "hello", qos=1)
        assert isinstance(pid, int) and 1 <= pid <= 0xFFFF
        m.disconnect()

    def test_subscribe_returns_granted_qos(self):
        m = Mqtt(url=BROKER)
        assert m.subscribe(_topic("sub"), qos=1) == 1
        m.disconnect()

    def test_qos1_round_trip_topic_and_payload_intact(self):
        t = _topic("telemetry")
        sub = Mqtt(url=BROKER, client_id="tina4-pytest-sub")
        sub.subscribe(t, qos=1)
        pub = Mqtt(url=BROKER, client_id="tina4-pytest-pub")
        pub.publish(t, '{"kwh":12.5}', qos=1)
        msg = sub.receive(timeout=5)
        assert msg.topic == t
        assert msg.text() == '{"kwh":12.5}'
        assert msg.qos == 1
        assert msg.acknowledged is True
        sub.disconnect(); pub.disconnect()

    def test_wildcard_subscription(self):
        base = _topic("dev")
        sub = Mqtt(url=BROKER, client_id="tina4-pytest-wild")
        sub.subscribe(base + "/+/telemetry", qos=1)
        pub = Mqtt(url=BROKER)
        pub.publish(base + "/meter-42/telemetry", "x", qos=1)
        msg = sub.receive(timeout=5)
        assert msg.topic == base + "/meter-42/telemetry"
        sub.disconnect(); pub.disconnect()

    def test_retained_message_delivered_to_late_subscriber(self):
        t = _topic("state")
        pub = Mqtt(url=BROKER)
        pub.publish(t, "online", qos=1, retain=True)
        late = Mqtt(url=BROKER, client_id="tina4-pytest-late")
        late.subscribe(t, qos=1)
        msg = late.receive(timeout=5)
        assert msg.payload == b"online"
        assert msg.retained is True
        pub.publish(t, "", qos=1, retain=True)  # clear
        pub.disconnect(); late.disconnect()

    def test_retained_cleared_by_empty_payload(self):
        t = _topic("clearme")
        pub = Mqtt(url=BROKER)
        pub.publish(t, "value", qos=1, retain=True)
        pub.publish(t, "", qos=1, retain=True)  # documented reset
        late = Mqtt(url=BROKER, client_id="tina4-pytest-cleared")
        late.subscribe(t, qos=1)
        with pytest.raises(Exception):  # nothing retained -> times out
            late.receive(timeout=1)
        pub.disconnect(); late.disconnect()

    def test_ping_round_trip(self):
        m = Mqtt(url=BROKER)
        assert m.ping(timeout=5) is True
        m.disconnect()

    def test_consume_generator_acks_after_body(self):
        t = _topic("consume")
        sub = Mqtt(url=BROKER, client_id="tina4-pytest-consume")
        sub.subscribe(t, qos=1)
        pub = Mqtt(url=BROKER)
        for i in range(3):
            pub.publish(t, f"msg-{i}", qos=1)
        seen = []
        for msg in sub.consume(qos=1, iterations=3, timeout=5):
            seen.append(msg.text())
        assert seen == ["msg-0", "msg-1", "msg-2"]
        sub.disconnect(); pub.disconnect()

    def test_publish_and_subscribe_on_one_connection_does_not_mistake_publish_for_ack(self):
        # The ack-inbox correction: an inbound PUBLISH must not be mistaken for a
        # PUBACK when the same connection both publishes and subscribes.
        t = _topic("selfpub")
        c = Mqtt(url=BROKER, client_id="tina4-pytest-selfpub")
        c.subscribe(t, qos=1)
        # publish to our own subscription at QoS1: the broker may push the
        # PUBLISH before our PUBACK -- _await_ack must loop past it.
        pid = c.publish(t, "roundtrip", qos=1)
        assert isinstance(pid, int)
        msg = c.receive(timeout=5)
        assert msg.text() == "roundtrip"
        c.disconnect()

    def test_last_will_fires_on_ungraceful_close(self):
        will_topic = _topic("will")
        watcher = Mqtt(url=BROKER, client_id="tina4-pytest-watch")
        watcher.subscribe(will_topic, qos=1)
        dying = Mqtt(url=BROKER, client_id="tina4-pytest-dying", keepalive=1,
                     will_topic=will_topic, will_payload="device-died", will_qos=1)
        dying.kill()  # drop the socket WITHOUT a DISCONNECT
        msg = watcher.receive(timeout=8)  # broker fires the will past 1.5x keepalive
        assert msg.payload == b"device-died"
        watcher.disconnect()

    def test_write_after_disconnect_raises(self):
        m = Mqtt(url=BROKER)
        m.disconnect()
        with pytest.raises(MqttError):
            m.publish("t", "x", qos=0)
