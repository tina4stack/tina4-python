"""One MQTT 3.1.1 application message as delivered by the broker."""

from __future__ import annotations

from typing import Any


class MqttMessage:
    """One MQTT 3.1.1 application message as delivered by the broker.

    Shaped like tina4_python.queue.Job (the Queue's unit of work): it carries
    the payload plus the delivery metadata a consumer needs, and it knows how to
    acknowledge itself back to the client it came from.

    The two flags matter for correctness, not decoration:

      retained  -- the broker replayed the topic's last known value to us
                   because we subscribed AFTER it was published. It is current
                   state, not a fresh event.
      duplicate -- the DUP flag. The broker is REDELIVERING a QoS 1 message it
                   never saw acknowledged. QoS 1 is at-least-once, so a
                   duplicate is guaranteed eventually; a consumer that treats a
                   DUP delivery as a new sample double-counts energy or mileage.
                   Key the ingest on (device_id, device_timestamp) and it is
                   harmless.
    """

    __slots__ = (
        "topic", "payload", "qos", "packet_id",
        "_retained", "_duplicate", "_client", "_acknowledged",
    )

    def __init__(self, topic: str, payload: bytes, qos: int = 0,
                 retained: bool = False, duplicate: bool = False,
                 packet_id: int | None = None, client: Any = None) -> None:
        self.topic = topic
        self.payload = payload
        self.qos = qos
        self.packet_id = packet_id
        self._retained = retained
        self._duplicate = duplicate
        self._client = client
        self._acknowledged = False

    @property
    def retained(self) -> bool:
        """True when the broker replayed this as the topic's retained (last known) value."""
        return self._retained

    @property
    def duplicate(self) -> bool:
        """True when the broker set the DUP flag -- a REDELIVERY of a QoS 1 message
        we never acknowledged, not a new sample."""
        return self._duplicate

    def acknowledge(self) -> bool:
        """PUBACK a QoS 1 delivery so the broker stops redelivering it.

        A QoS 0 message needs no acknowledgement, and a second call is a no-op,
        so this is always safe to call once processing succeeded.
        """
        if self._acknowledged or self.qos == 0 or self.packet_id is None or self._client is None:
            return False
        self._client.acknowledge(self.packet_id)
        self._acknowledged = True
        return True

    @property
    def acknowledged(self) -> bool:
        """True once this message has been acknowledged back to the broker."""
        return self._acknowledged

    def text(self, encoding: str = "utf-8") -> str:
        """The payload decoded as text (errors replaced), for JSON / string payloads."""
        return self.payload.decode(encoding, errors="replace")

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "payload": self.payload,
            "qos": self.qos,
            "retained": self._retained,
            "duplicate": self._duplicate,
            "packet_id": self.packet_id,
        }

    def __str__(self) -> str:
        return self.text()

    def __repr__(self) -> str:
        return (f"<MqttMessage topic={self.topic!r} qos={self.qos} "
                f"retained={self._retained} duplicate={self._duplicate} "
                f"bytes={len(self.payload)}>")
