# Tests for Tina4 Queue Backends — RabbitMQ, Kafka, and MongoDB connectors.
"""
Tests cover:
- One consolidated interface/contract test (cheap rename guard) per backend family
- REAL behavioural tests against live RabbitMQ / Kafka / MongoDB (no mocks)
- Config-resolution tests (pure constructor state from real env/kwargs)

NO MOCKS. Every test that touches a broker exercises the real service and is
skip-guarded on reachability so the suite stays green where infra is absent.
The earlier mock-based classes (MagicMock pika/confluent/pymongo) were deleted:
a mock-passing queue test is exactly what let the Node Mongo redelivery bug ship
for two releases. Their behaviour is now proven against the real dependency below.
"""
import os
import socket
import secrets
import time

import pytest


def _pymongo_available():
    try:
        import pymongo  # noqa: F401
        return True
    except ImportError:
        return False


def _reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ── Interface Contract Tests ─────────────────────────────────────



@pytest.fixture()
def no_backend_env(monkeypatch):
    """Assert a DEFAULT against the code's defaults, not the machine's environment.

    A test that constructs a backend with no arguments and asserts
    "host == localhost" is only testing the default when the environment holds
    no override. These tests took no monkeypatch, so on any box that exports
    TINA4_RABBITMQ_HOST -- a CI runner, or the lab once the suites were given
    per-framework namespaces -- they asserted the machine's configuration and
    failed. A default is a property of the code; establish the condition rather
    than assuming it.
    """
    for name in [k for k in os.environ if k.startswith(("TINA4_RABBITMQ", "TINA4_KAFKA", "TINA4_MONGO", "TINA4_QUEUE"))]:
        monkeypatch.delenv(name, raising=False)

class TestQueueBackendContract:
    """One rename guard for the whole backend family.

    The Queue facade calls a fixed method set on whatever backend is active;
    if a connector drops one (e.g. a rename) it must fail loudly here rather
    than at runtime against a live broker. The real BEHAVIOUR of these methods
    is covered by the live tests further down — this is only the cheap,
    infra-free contract check, looping the method set over every connector.
    """

    REQUIRED = (
        "enqueue", "dequeue", "acknowledge", "reject",
        "size", "clear", "dead_letter", "close", "connect",
    )

    def _connector_classes(self):
        from tina4_python.queue_backends.rabbitmq_backend import RabbitMQConnector
        from tina4_python.queue_backends.kafka_backend import KafkaConnector
        classes = {"rabbitmq": RabbitMQConnector, "kafka": KafkaConnector}
        if _pymongo_available():
            from tina4_python.queue_backends.mongo_backend import MongoConnector
            classes["mongodb"] = MongoConnector
        return classes

    def test_every_backend_implements_the_required_interface(self):
        for name, cls in self._connector_classes().items():
            backend = cls()
            for method in self.REQUIRED:
                attr = getattr(backend, method, None)
                assert callable(attr), f"{name} connector is missing {method}()"


# ── RabbitMQ Backend Config (pure constructor state) ─────────────


class TestRabbitMQBackendConfig:
    """Constructor resolves host/port/credentials from kwargs and env — no broker."""

    def test_default_config(self, no_backend_env):
        from tina4_python.queue_backends.rabbitmq_backend import RabbitMQBackend

        backend = RabbitMQBackend()
        assert backend._host == "localhost"
        assert backend._port == 5672
        assert backend._username == "guest"
        assert backend._password == "guest"
        assert backend._vhost == "/"

    def test_custom_config(self):
        from tina4_python.queue_backends.rabbitmq_backend import RabbitMQBackend

        backend = RabbitMQBackend(
            host="rabbitmq.example.com",
            port=5673,
            username="admin",
            password="secret",
            vhost="/test",
        )
        assert backend._host == "rabbitmq.example.com"
        assert backend._port == 5673
        assert backend._username == "admin"
        assert backend._password == "secret"
        assert backend._vhost == "/test"

    def test_env_config(self, monkeypatch):
        from tina4_python.queue_backends.rabbitmq_backend import RabbitMQBackend

        monkeypatch.setenv("TINA4_RABBITMQ_HOST", "rmq-host")
        monkeypatch.setenv("TINA4_RABBITMQ_PORT", "5680")
        monkeypatch.setenv("TINA4_RABBITMQ_USERNAME", "envuser")
        monkeypatch.setenv("TINA4_RABBITMQ_PASSWORD", "envpass")
        monkeypatch.setenv("TINA4_RABBITMQ_VHOST", "/env")

        backend = RabbitMQBackend()
        assert backend._host == "rmq-host"
        assert backend._port == 5680
        assert backend._username == "envuser"
        assert backend._password == "envpass"
        assert backend._vhost == "/env"

    def test_close_when_never_connected_leaves_no_connection(self):
        # Real behaviour: close() before connect() is a safe no-op AND leaves the
        # backend in the disconnected state (no socket/connection objects).
        from tina4_python.queue_backends.rabbitmq_backend import RabbitMQBackend

        backend = RabbitMQBackend()
        backend.close()
        assert backend._connection is None
        assert backend._socket is None

    def test_acknowledge_without_delivery_tag_is_inert(self):
        # Real behaviour: ack for a message that is not in flight does nothing —
        # no broker call attempted, no state change. Same guarantee as before
        # ADR-0022; only the state it reads changed, from a single
        # _last_delivery_tag slot to the per-message _delivery_tags map.
        from tina4_python.queue_backends.rabbitmq_backend import RabbitMQBackend

        backend = RabbitMQBackend()
        assert backend._delivery_tags == {}
        backend.acknowledge("test", "msg-1")
        assert backend._delivery_tags == {}

    def test_reject_without_delivery_tag_is_inert(self):
        from tina4_python.queue_backends.rabbitmq_backend import RabbitMQBackend

        backend = RabbitMQBackend()
        assert backend._delivery_tags == {}
        backend.reject("test", "msg-1")
        assert backend._delivery_tags == {}


# ── Kafka Backend Config (pure constructor state) ────────────────


class TestKafkaBackendConfig:
    """Constructor resolves brokers/group/client from kwargs and env — no broker."""

    def test_default_config(self, no_backend_env):
        from tina4_python.queue_backends.kafka_backend import KafkaBackend

        backend = KafkaBackend()
        assert backend._brokers == "localhost:9092"
        assert backend._group_id == "tina4_consumer_group"
        assert backend._client_id == "tina4-python"

    def test_custom_config(self):
        from tina4_python.queue_backends.kafka_backend import KafkaBackend

        backend = KafkaBackend(
            brokers="kafka1:9092,kafka2:9092",
            group_id="my-app",
            client_id="test-client",
        )
        assert backend._brokers == "kafka1:9092,kafka2:9092"
        assert backend._group_id == "my-app"
        assert backend._client_id == "test-client"

    def test_env_config(self, monkeypatch):
        from tina4_python.queue_backends.kafka_backend import KafkaBackend

        monkeypatch.setenv("TINA4_KAFKA_BROKERS", "kafka-host:9093")
        monkeypatch.setenv("TINA4_KAFKA_GROUP_ID", "env-group")

        backend = KafkaBackend()
        assert backend._brokers == "kafka-host:9093"
        assert backend._group_id == "env-group"

    def test_close_when_never_connected_leaves_no_connection(self):
        from tina4_python.queue_backends.kafka_backend import KafkaBackend

        backend = KafkaBackend()
        backend.close()
        assert backend._socket is None

    def test_size_is_always_zero(self):
        # Kafka has no queue-size concept; size() is documented to always
        # return 0 regardless of how much has been produced. Assert the real
        # contract value (a constant, not a mock).
        from tina4_python.queue_backends.kafka_backend import KafkaBackend

        backend = KafkaBackend()
        assert backend.size("anything") == 0

    def test_dead_letter_topic_naming(self):
        # dead_letter() routes to "<topic>.dead_letter". Prove the real naming
        # by capturing the topic enqueue() is called with — no producer mock,
        # we intercept the connector's own enqueue.
        from tina4_python.queue_backends.kafka_backend import KafkaBackend

        backend = KafkaBackend()
        seen = {}
        backend.enqueue = lambda topic, msg: seen.update(topic=topic, msg=msg) or "id"
        backend.dead_letter("orders", {"id": "msg-1", "error": "timeout"})
        assert seen["topic"] == "orders.dead_letter"
        assert seen["msg"]["error"] == "timeout"


# ── MongoDB Backend Config (pure constructor state) ──────────────


_skip_no_pymongo = pytest.mark.skipif(
    not _pymongo_available(),
    reason="pymongo not installed"
)


@_skip_no_pymongo
class TestMongoDBBackendConfig:
    """Constructor resolves host/port/db/collection from kwargs and env — no broker."""

    def test_default_config(self, no_backend_env):
        from tina4_python.queue_backends.mongo_backend import MongoBackend

        backend = MongoBackend()
        assert backend._host == "localhost"
        assert backend._port == 27017
        assert backend._db_name == "tina4"
        assert backend._collection_name == "tina4_queue"

    def test_env_override(self, monkeypatch):
        from tina4_python.queue_backends.mongo_backend import MongoBackend

        monkeypatch.setenv("TINA4_MONGO_HOST", "mongo-env")
        monkeypatch.setenv("TINA4_MONGO_PORT", "27020")
        monkeypatch.setenv("TINA4_MONGO_DB", "envdb")
        monkeypatch.setenv("TINA4_MONGO_COLLECTION", "env_queue")

        backend = MongoBackend()
        assert backend._host == "mongo-env"
        assert backend._port == 27020
        assert backend._db_name == "envdb"
        assert backend._collection_name == "env_queue"

    def test_constructor_override(self):
        from tina4_python.queue_backends.mongo_backend import MongoBackend

        backend = MongoBackend(
            host="custom-host",
            port=27030,
            db="customdb",
            collection="custom_queue",
        )
        assert backend._host == "custom-host"
        assert backend._port == 27030
        assert backend._db_name == "customdb"
        assert backend._collection_name == "custom_queue"

    def test_close_when_never_connected_leaves_no_client(self):
        from tina4_python.queue_backends.mongo_backend import MongoBackend

        backend = MongoBackend()
        backend.close()
        assert backend._client is None

    def test_visibility_timeout_from_env(self, monkeypatch):
        from tina4_python.queue_backends.mongo_backend import MongoBackend

        monkeypatch.setenv("TINA4_QUEUE_VISIBILITY_TIMEOUT", "45")
        assert MongoBackend()._visibility_timeout == 45.0


# ── Live MongoDB Connector Behaviour (real Mongo, no mocks) ──────


_MONGO_TEST_URL = os.environ.get("TINA4_TEST_MONGO_URI", "mongodb://localhost:27017")


def _mongo_reachable() -> bool:
    import re
    m = re.match(r"mongodb://([^:/]+)(?::(\d+))?", _MONGO_TEST_URL)
    host = m.group(1) if m else "localhost"
    port = int(m.group(2)) if (m and m.group(2)) else 27017
    return _reachable(host, port)


@pytest.mark.skipif(not _pymongo_available(), reason="pymongo not installed")
@pytest.mark.skipif(not _mongo_reachable(), reason="MongoDB not reachable")
class TestMongoConnectorLive:
    """Exercise the MongoConnector directly against a LIVE MongoDB.

    Replaces the deleted TestMongoDBBackendMocked (which wired a MagicMock
    collection onto the connector — forbidden by the no-mock rule and the reason
    real queue bugs slipped through). Each test uses a throwaway namespaced
    database that is dropped on teardown, so application data is never touched.
    """

    DB_NAME = "tina4_test_queue_connector"
    COLLECTION = "tina4_test_queue_connector_jobs"

    @pytest.fixture()
    def backend(self):
        from tina4_python.queue_backends.mongo_backend import MongoConnector
        b = MongoConnector(
            uri=_MONGO_TEST_URL,
            db=self.DB_NAME,
            collection=self.COLLECTION,
            visibility_timeout=300.0,
        )
        b.connect()
        yield b
        try:
            b._client.drop_database(self.DB_NAME)
        finally:
            b.close()

    def _topic(self):
        return "conn_" + secrets.token_hex(6)

    def test_enqueue_then_size_counts_pending(self, backend):
        topic = self._topic()
        assert backend.size(topic) == 0
        mid = backend.enqueue(topic, {"to": "alice@test.com"})
        assert isinstance(mid, str) and mid
        assert backend.size(topic) == 1
        # The stored document is real: pending, on the right topic.
        doc = backend._collection.find_one({"_id": mid})
        assert doc["topic"] == topic
        assert doc["status"] == "pending"

    def test_dequeue_returns_payload_and_reserves(self, backend):
        topic = self._topic()
        mid = backend.enqueue(topic, {"to": "alice@test.com", "priority": 7})
        msg = backend.dequeue(topic)
        assert msg["id"] == mid
        assert msg["to"] == "alice@test.com"
        # Live document-level priority surfaces (not the data snapshot).
        assert msg["priority"] == 7
        # Reserved, so no longer counted as pending.
        assert backend.size(topic) == 0
        assert backend._collection.find_one({"_id": mid})["status"] == "reserved"

    def test_dequeue_empty_topic_returns_none(self, backend):
        assert backend.dequeue(self._topic()) is None

    def test_priority_ordering_pops_highest_first(self, backend):
        topic = self._topic()
        backend.enqueue(topic, {"n": "low", "priority": 1})
        backend.enqueue(topic, {"n": "high", "priority": 9})
        backend.enqueue(topic, {"n": "mid", "priority": 5})
        order = [backend.dequeue(topic)["n"] for _ in range(3)]
        assert order == ["high", "mid", "low"]

    def test_acknowledge_marks_completed(self, backend):
        topic = self._topic()
        mid = backend.enqueue(topic, {"x": 1})
        backend.dequeue(topic)
        backend.acknowledge(topic, mid)
        doc = backend._collection.find_one({"_id": mid})
        assert doc["status"] == "completed"
        assert doc["completed_at"] is not None

    def test_reject_requeue_makes_visible_again(self, backend):
        topic = self._topic()
        mid = backend.enqueue(topic, {"x": 1})
        backend.dequeue(topic)
        assert backend.size(topic) == 0          # reserved
        backend.reject(topic, mid, requeue=True)
        assert backend.size(topic) == 1          # back to pending immediately
        doc = backend._collection.find_one({"_id": mid})
        assert doc["status"] == "pending"
        assert doc["attempts"] == 1              # attempt counted

    def test_reject_no_requeue_marks_failed(self, backend):
        topic = self._topic()
        mid = backend.enqueue(topic, {"x": 1})
        backend.dequeue(topic)
        backend.reject(topic, mid, requeue=False)
        assert backend._collection.find_one({"_id": mid})["status"] == "failed"
        assert backend.size(topic) == 0

    def test_dead_letter_writes_to_dead_letter_topic(self, backend):
        topic = self._topic()
        backend.dead_letter(topic, {"id": "m1", "error": "failed"})
        dead = backend._collection.find_one({"topic": f"{topic}.dead_letter"})
        assert dead is not None
        assert dead["status"] == "dead"
        assert dead["error"] == "failed"

    def test_clear_removes_all_topic_documents(self, backend):
        topic = self._topic()
        backend.enqueue(topic, {"x": 1})
        backend.enqueue(topic, {"x": 2})
        assert backend.size(topic) == 2
        backend.clear(topic)
        assert backend.size(topic) == 0
        assert backend._collection.count_documents({"topic": topic}) == 0

    def test_reclaim_expired_requeues_dead_consumers_reservation(self):
        # Visibility-timeout reclaim against real Mongo: a reservation whose
        # consumer died (never acked) becomes visible again after the window,
        # with attempts incremented. Short timeout so the test is fast.
        from tina4_python.queue_backends.mongo_backend import MongoConnector
        b = MongoConnector(
            uri=_MONGO_TEST_URL, db=self.DB_NAME, collection=self.COLLECTION,
            visibility_timeout=1.0,
        )
        b.connect()
        topic = self._topic()
        try:
            b.enqueue(topic, {"x": 1})
            b.dequeue(topic)                 # reserve; consumer then "dies"
            assert b.size(topic) == 0
            time.sleep(1.3)                  # let the reservation window expire
            reclaimed = b.reclaim_expired(topic, max_retries=3)
            assert reclaimed == 1
            assert b.size(topic) == 1        # requeued -> pending
            doc = b._collection.find_one({"topic": topic, "status": "pending"})
            assert doc["attempts"] == 1
        finally:
            b._client.drop_database(self.DB_NAME)
            b.close()

    def test_reclaim_dead_letters_past_max_retries(self):
        from tina4_python.queue_backends.mongo_backend import MongoConnector
        b = MongoConnector(
            uri=_MONGO_TEST_URL, db=self.DB_NAME, collection=self.COLLECTION,
            visibility_timeout=1.0,
        )
        b.connect()
        topic = self._topic()
        try:
            b.enqueue(topic, {"x": 1})
            # Drive it past max_retries=1: dequeue, let it expire, reclaim ->
            # attempts hits 1 -> dead-lettered, original removed.
            b.dequeue(topic)
            time.sleep(1.3)
            b.reclaim_expired(topic, max_retries=1)
            assert b._collection.count_documents({"topic": f"{topic}.dead_letter"}) == 1
            assert b.size(topic) == 0
            assert b._collection.count_documents({"topic": topic}) == 0
        finally:
            b._client.drop_database(self.DB_NAME)
            b.close()

    def test_reclaim_disabled_when_timeout_zero(self):
        from tina4_python.queue_backends.mongo_backend import MongoConnector
        b = MongoConnector(
            uri=_MONGO_TEST_URL, db=self.DB_NAME, collection=self.COLLECTION,
            visibility_timeout=0,
        )
        b.connect()
        topic = self._topic()
        try:
            b.enqueue(topic, {"x": 1})
            b.dequeue(topic)
            assert b.reclaim_expired(topic, max_retries=3) == 0
        finally:
            b._client.drop_database(self.DB_NAME)
            b.close()

    def test_close_resets_client(self):
        from tina4_python.queue_backends.mongo_backend import MongoConnector
        b = MongoConnector(
            uri=_MONGO_TEST_URL, db=self.DB_NAME, collection=self.COLLECTION,
        )
        b.connect()
        assert b._client is not None
        b.close()
        assert b._client is None
        assert b._collection is None


# ── Live RabbitMQ Connector Behaviour (real broker via pika, no mocks) ──


_RABBIT_HOST = os.environ.get("TINA4_RABBITMQ_HOST", "localhost")
_RABBIT_PORT = int(os.environ.get("TINA4_RABBITMQ_PORT", "5672"))


def _pika_available():
    try:
        import pika  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _pika_available(), reason="pika not installed")
@pytest.mark.skipif(
    not _reachable(_RABBIT_HOST, _RABBIT_PORT),
    reason="RabbitMQ not reachable",
)
class TestRabbitMQConnectorLive:
    """Exercise the RabbitMQConnector over the real broker via pika (no mocks).

    Replaces the deleted TestRabbitMQBackendMocked (MagicMock pika channel).
    Producer and reader use SEPARATE connector instances (separate connections):
    RabbitMQ's queue_declare message_count does not reflect a message still
    in flight on the *publishing* channel right after basic_publish, so a
    same-connection size() check would race — the at-least-once contract is
    verified across connections, the way a real producer/worker split runs.
    """

    def _connector(self):
        from tina4_python.queue_backends.rabbitmq_backend import RabbitMQConnector
        b = RabbitMQConnector(host=_RABBIT_HOST, port=_RABBIT_PORT)
        assert b._use_pika is True   # this class targets the pika path
        b.connect()
        return b

    def test_size_on_fresh_queue_is_zero(self):
        # Regression: size() on a never-declared queue used to raise
        # ChannelClosedByBroker (404) on the pika path because it declared
        # passive=True. It must return 0 (declare-then-count, like the raw path).
        topic = "tina4_test_" + secrets.token_hex(8)
        b = self._connector()
        try:
            assert b.size(topic) == 0
        finally:
            b.clear(topic)
            b.close()

    def test_full_enqueue_dequeue_acknowledge_cycle(self):
        topic = "tina4_test_" + secrets.token_hex(8)

        producer = self._connector()
        try:
            assert producer.size(topic) == 0
            msg_id = producer.enqueue(topic, {"to": "alice@test.com", "value": 7})
            assert isinstance(msg_id, str) and msg_id
        finally:
            producer.close()

        reader = self._connector()
        try:
            assert reader.size(topic) == 1                 # separate connection sees it
            msg = reader.dequeue(topic)
            assert msg["to"] == "alice@test.com"
            assert msg["value"] == 7
            assert msg["id"] == msg_id
            # The tag is now recorded AGAINST THE MESSAGE ID (ADR-0022), so an
            # ack can name the delivery it means. Was a single
            # _last_delivery_tag slot, which acked whatever was popped last.
            assert msg_id in reader._delivery_tags        # delivery tag captured
            reader.acknowledge(topic, msg_id)
            assert msg_id not in reader._delivery_tags    # cleared after ack
        finally:
            reader.close()

        verifier = self._connector()
        try:
            assert verifier.size(topic) == 0               # acked -> empty
            verifier.clear(topic)
        finally:
            verifier.close()

    def test_reject_requeue_returns_message_to_queue(self):
        topic = "tina4_test_" + secrets.token_hex(8)

        producer = self._connector()
        try:
            producer.enqueue(topic, {"task": "retry-me"})
        finally:
            producer.close()

        rejecter = self._connector()
        try:
            msg = rejecter.dequeue(topic)
            assert msg["task"] == "retry-me"
            rejecter.reject(topic, msg["id"], requeue=True)   # nack + requeue
        finally:
            rejecter.close()

        reader = self._connector()
        try:
            assert reader.size(topic) == 1                    # requeued, redelivered
            again = reader.dequeue(topic)
            assert again["task"] == "retry-me"
            reader.acknowledge(topic, again["id"])
            reader.clear(topic)
        finally:
            reader.close()

    def test_dead_letter_publishes_to_dead_letter_queue(self):
        topic = "tina4_test_" + secrets.token_hex(8)
        producer = self._connector()
        try:
            producer.dead_letter(topic, {"id": "d1", "error": "boom"})
        finally:
            producer.close()

        reader = self._connector()
        try:
            assert reader.size(f"{topic}.dead_letter") == 1
            dead = reader.dequeue(f"{topic}.dead_letter")
            assert dead["error"] == "boom"
            reader.acknowledge(f"{topic}.dead_letter", "d1")
            reader.clear(f"{topic}.dead_letter")
        finally:
            reader.close()

    def test_clear_purges_pending_messages(self):
        topic = "tina4_test_" + secrets.token_hex(8)
        producer = self._connector()
        try:
            producer.enqueue(topic, {"x": 1})
            producer.enqueue(topic, {"x": 2})
        finally:
            producer.close()

        cleaner = self._connector()
        try:
            assert cleaner.size(topic) == 2
            cleaner.clear(topic)
            assert cleaner.size(topic) == 0
        finally:
            cleaner.close()

    def test_close_resets_connection(self):
        b = self._connector()
        assert b._connection is not None
        b.close()
        assert b._connection is None
        assert b._channel is None


# ── Live Kafka Connector Behaviour (real broker via confluent, no mocks) ──


def _confluent_available():
    try:
        import confluent_kafka  # noqa: F401
        return True
    except ImportError:
        return False


_KAFKA_BROKER = os.environ.get("TINA4_KAFKA_BROKERS", "localhost:9092")


def _kafka_reachable() -> bool:
    first = _KAFKA_BROKER.split(",")[0]
    host, _, port = first.partition(":")
    return _reachable(host or "localhost", int(port or "9092"))


@pytest.mark.skipif(not _confluent_available(), reason="confluent-kafka not installed")
@pytest.mark.skipif(not _kafka_reachable(), reason="Kafka not reachable")
class TestKafkaConnectorLive:
    """Exercise the KafkaConnector over the real broker via confluent (no mocks).

    Replaces the deleted TestKafkaBackendMocked (MagicMock producer/consumer).
    Each test uses a unique topic and a unique consumer group so the
    earliest-offset read is deterministic and cold-broker partition assignment
    (the bounded first-poll loop) is exercised for real.
    """

    def _connector(self):
        from tina4_python.queue_backends.kafka_backend import KafkaConnector
        b = KafkaConnector(
            brokers=_KAFKA_BROKER,
            group_id="tina4_test_" + secrets.token_hex(8),
        )
        assert b._use_confluent is True   # this class targets the confluent path
        b.connect()
        return b

    def test_enqueue_dequeue_roundtrip(self):
        topic = "tina4_test_" + secrets.token_hex(8)
        producer = self._connector()
        try:
            msg_id = producer.enqueue(topic, {"type": "click", "value": 42})
            assert isinstance(msg_id, str) and msg_id
        finally:
            producer.close()

        consumer = self._connector()
        try:
            msg = consumer.dequeue(topic)   # first poll drives group join/assignment
            assert msg is not None, "expected the produced message back from Kafka"
            assert msg["type"] == "click"
            assert msg["value"] == 42
            assert msg["id"] == msg_id
            # The polled Message is now held AGAINST ITS MESSAGE ID (ADR-0022)
            # so the commit names the record it means. Was a single
            # _last_message slot, which committed past whatever was polled last
            # and buried any record failed before it.
            assert msg_id in consumer._in_flight
            consumer.acknowledge(topic, msg_id)   # commits the offset
            assert msg_id not in consumer._in_flight  # cleared after commit
        finally:
            consumer.close()

    def test_dequeue_unknown_topic_returns_none(self):
        # A topic that has never been produced to yields no message within the
        # assignment deadline (kept short here so the test stays fast).
        consumer = self._connector()
        try:
            os.environ["TINA4_KAFKA_ASSIGN_TIMEOUT"] = "3"
            assert consumer.dequeue("tina4_test_empty_" + secrets.token_hex(8)) is None
        finally:
            os.environ.pop("TINA4_KAFKA_ASSIGN_TIMEOUT", None)
            consumer.close()

    def test_dead_letter_round_trips_through_dead_letter_topic(self):
        topic = "tina4_test_" + secrets.token_hex(8)
        producer = self._connector()
        try:
            producer.dead_letter(topic, {"id": "d1", "error": "timeout"})
        finally:
            producer.close()

        consumer = self._connector()
        try:
            msg = consumer.dequeue(f"{topic}.dead_letter")
            assert msg is not None
            assert msg["error"] == "timeout"
        finally:
            consumer.close()


# ── Kafka RecordBatch v2 wire format (pure functions, no dependency) ──


class TestKafkaRecordBatchV2:
    """Lock in the wire-level invariants of the hand-rolled RecordBatch v2 encoder.

    The bug these pin down: the client spoke Produce v0 / Fetch v0, which Kafka 4.x
    REMOVED along with message formats v0/v1. A removed version is not answered
    with an error code -- the broker logs

        UnsupportedVersionException: Received request for api with key 0 (Produce)
        and unsupported version 0

    and CLOSES THE SOCKET. The client saw a bare EOF, so the symptom ("Failed to
    read Kafka response length") named neither the cause nor the fix. A plain
    "does produce work" test is not enough; these assert the byte-level facts that
    make it work, so a regression shows up here instead of as a mystery disconnect.

    The encoder is a pure function over its inputs -- no socket, no broker, no
    double -- so this class needs no live service. The real round trip is
    TestKafkaRawPathLive below.
    """

    def _connector(self):
        from tina4_python.queue_backends.kafka_backend import KafkaConnector
        return KafkaConnector(brokers="127.0.0.1:9092")

    # ── API versions: the actual bug ─────────────────────────────

    def test_produce_and_fetch_versions_are_not_the_removed_ones(self):
        # NEGATIVE: a regression here does not fail loudly, it makes the broker
        # hang up mid-conversation -- so it has to be asserted, not assumed.
        from tina4_python.queue_backends.kafka_backend import KafkaConnector

        assert KafkaConnector.PRODUCE_VERSION >= 3, (
            "Produce v0-v2 carry message format v0/v1, which Kafka 4.x REMOVED; "
            "a broker answers those by closing the socket, not by erroring"
        )
        assert KafkaConnector.FETCH_VERSION >= 4, (
            "Fetch v0-v3 went with the old message formats; Kafka 4.3 advertises "
            "Fetch(1): 4 to 18"
        )

    # ── CRC32C, not CRC32 ────────────────────────────────────────

    def test_crc32c_is_castagnoli_not_iso_hdlc(self):
        # NEGATIVE: record format v2 needs CRC32C (Castagnoli, poly 0x82F63B78),
        # NOT the CRC32 that format v0 used and that zlib.crc32 computes. Swapping
        # them builds a batch the encoder accepts and the broker silently rejects,
        # so pin the algorithm to its published vectors.
        import zlib

        crc32c = self._connector()._crc32c
        assert crc32c(b"123456789") == 0xE3069283, "published CRC32C check value"
        assert crc32c(b"") == 0
        assert crc32c(b"123456789") != zlib.crc32(b"123456789"), (
            "zlib.crc32 is ISO-HDLC and must never be used for a v2 batch"
        )

    # ── Varints ──────────────────────────────────────────────────

    def test_varint_matches_the_zigzag_vectors(self):
        # POSITIVE: zigzag LEB128 against the published vectors. -1 (the null
        # key/value sentinel) must cost ONE byte; get zigzag wrong and it costs
        # ten, which shifts every field that follows it.
        varint = self._connector()._varint
        vectors = {
            0: "00", -1: "01", 1: "02", -2: "03",
            2: "04", 63: "7e", 64: "8001", -64: "7f",
        }
        for value, expected in vectors.items():
            assert varint(value).hex() == expected, f"varint({value})"

    def test_varint_round_trips(self):
        # POSITIVE: encode/decode agree across the int32 range and the sentinel,
        # and the reader reports the exact byte count it consumed.
        conn = self._connector()
        for value in (0, -1, 1, -2, 300, -300, 65535, -65535, 2147483647, -2147483648):
            buf = conn._varint(value)
            decoded, pos = conn._read_varint(buf, 0)
            assert decoded == value, f"round-trip {value}"
            assert pos == len(buf), f"consumed every byte for {value}"

    # ── Batch layout ─────────────────────────────────────────────

    def test_record_batch_header_layout(self):
        # POSITIVE: the header fields land at the offsets the spec fixes them at
        # -- the same offsets _decode_first_record reads back. An encoder change
        # that shifts them fails here rather than at the broker.
        import struct

        batch = self._connector()._encode_record_batch(b"k1", b'{"v":1}')

        assert len(batch) > 61, "a v2 batch header alone is 61 bytes"
        assert struct.unpack("!q", batch[0:8])[0] == 0, "baseOffset"
        assert struct.unpack("!i", batch[8:12])[0] == len(batch) - 12, (
            "batchLength counts everything after itself"
        )
        assert batch[16] == 2, "magic byte MUST be 2 (record format v2)"
        assert struct.unpack("!H", batch[21:23])[0] == 0, "attributes: no compression"
        assert struct.unpack("!i", batch[57:61])[0] == 1, "record count"

    def test_record_batch_crc_covers_everything_after_it(self):
        # NEGATIVE: a wrong CRC range (or a wrong algorithm) still produces four
        # plausible bytes. Recompute over the region the spec defines -- attributes
        # to the end -- and compare, so only a correct CRC passes.
        import struct

        conn = self._connector()
        batch = conn._encode_record_batch(b"k1", b'{"v":1}')

        stored = struct.unpack("!I", batch[17:21])[0]
        assert stored == conn._crc32c(batch[21:]), (
            "the stored CRC32C must match a recomputation over attributes..end"
        )

    def test_encode_then_decode_returns_the_same_value(self):
        # POSITIVE: the payload survives its own encoder/decoder pair.
        conn = self._connector()
        batch = conn._encode_record_batch(b"thekey", b'{"hello":"world"}')
        decoded = conn._decode_first_record(batch)

        assert decoded is not None, "a freshly encoded batch must decode"
        value, offset = decoded
        assert value == b'{"hello":"world"}'
        assert offset == 0, "baseOffset 0 + offsetDelta 0"


# ── Live Kafka over the RAW hand-rolled path (real broker, no confluent) ──


@pytest.mark.skipif(not _kafka_reachable(), reason="Kafka not reachable")
class TestKafkaRawPathLive:
    """Round-trip a real message over the zero-dependency socket implementation.

    This class exists because TestKafkaConnectorLive above proves nothing about
    this code: confluent-kafka is installed in CI, so the constructor always
    picks the librdkafka path and the hand-rolled protocol NEVER RUNS. That blind
    spot is how the Produce-v0 break reached users -- the suite was green the
    whole time. Here the connector is switched onto its own raw path, so the
    frames on the wire are the ones this file builds.

    Not a mock: nothing is substituted for anything. `_use_confluent` is the flag
    the constructor itself sets from an import probe, and flipping it selects a
    code path -- the broker is a real Kafka, the socket is a real socket, and the
    bytes are the real protocol. Deliberately NOT skipped when confluent-kafka is
    present; that is the whole point.
    """

    def _raw_connector(self):
        from tina4_python.queue_backends.kafka_backend import KafkaConnector
        conn = KafkaConnector(brokers=_KAFKA_BROKER)
        conn._use_confluent = False
        conn._confluent = None
        conn.connect()
        assert conn._socket is not None, "the raw path must own a real socket"
        return conn

    def test_raw_enqueue_dequeue_roundtrip(self):
        topic = "tina4_raw_" + secrets.token_hex(8)
        payload = {"type": "click", "value": 42, "proof": secrets.token_hex(4)}

        producer = self._raw_connector()
        try:
            msg_id = producer.enqueue(topic, dict(payload))
            assert isinstance(msg_id, str) and msg_id
        finally:
            producer.close()

        consumer = self._raw_connector()
        try:
            msg = consumer.dequeue(topic)
            assert msg is not None, (
                "the raw path produced and then failed to read its own message back"
            )
            assert msg["type"] == "click"
            assert msg["value"] == 42
            assert msg["proof"] == payload["proof"]
            assert msg["id"] == msg_id
        finally:
            consumer.close()

    def test_raw_dequeue_advances_the_offset(self):
        # POSITIVE: two messages come back in order and the second read does not
        # re-deliver the first -- the fetch offset really moves.
        topic = "tina4_raw_" + secrets.token_hex(8)

        producer = self._raw_connector()
        try:
            producer.enqueue(topic, {"seq": 1})
            producer.enqueue(topic, {"seq": 2})
        finally:
            producer.close()

        consumer = self._raw_connector()
        try:
            first = consumer.dequeue(topic)
            second = consumer.dequeue(topic)
            assert first is not None and second is not None
            assert first["seq"] == 1
            assert second["seq"] == 2, "offset did not advance past the first record"
        finally:
            consumer.close()

    def test_raw_dequeue_on_an_empty_topic_returns_none(self):
        # NEGATIVE: an empty topic yields None, not a hang and not a stray record.
        consumer = self._raw_connector()
        try:
            assert consumer.dequeue("tina4_raw_empty_" + secrets.token_hex(8)) is None
        finally:
            consumer.close()


# ── Backend Resolution ───────────────────────────────────────────


class TestResolveBackend:
    """_resolve_backend returns the correct adapter for mongodb."""

    @_skip_no_pymongo
    def test_resolve_backend_mongodb(self, monkeypatch):
        from tina4_python.queue import _resolve_backend, MongoBackend

        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "mongodb")
        adapter = _resolve_backend("test", None, 3)
        assert isinstance(adapter, MongoBackend)


# ── Integration Tests (require actual services) ─────────────────


@pytest.mark.skipif(
    not os.environ.get("TINA4_TEST_RABBITMQ_URL"),
    reason="TINA4_TEST_RABBITMQ_URL not set"
)
class TestRabbitMQIntegration:
    """Integration tests that require an actual RabbitMQ server."""

    def test_enqueue_dequeue_cycle(self):
        from tina4_python.queue_backends.rabbitmq_backend import RabbitMQBackend

        backend = RabbitMQBackend()
        backend.connect()
        try:
            backend.clear("test_integration")
            msg_id = backend.enqueue("test_integration", {"hello": "world"})
            msg = backend.dequeue("test_integration")
            assert msg is not None
            assert msg["hello"] == "world"
            backend.acknowledge("test_integration", msg_id)
            assert backend.size("test_integration") == 0
        finally:
            backend.close()


@pytest.mark.skipif(
    not os.environ.get("TINA4_TEST_KAFKA_URL"),
    reason="TINA4_TEST_KAFKA_URL not set"
)
class TestKafkaIntegration:
    """Integration tests that require an actual Kafka server."""

    def test_enqueue_dequeue_cycle(self):
        from tina4_python.queue_backends.kafka_backend import KafkaBackend

        backend = KafkaBackend()
        backend.connect()
        try:
            msg_id = backend.enqueue("test_integration", {"hello": "world"})
            msg = backend.dequeue("test_integration")
            assert msg is not None
            assert msg["hello"] == "world"
            backend.acknowledge("test_integration", msg_id)
        finally:
            backend.close()


# ── Import Tests ─────────────────────────────────────────────────


class TestImports:
    """Test that backends can be imported from the package."""

    def test_import_from_package(self):
        from tina4_python.queue_backends import RabbitMQBackend, KafkaBackend

        assert RabbitMQBackend is not None
        assert KafkaBackend is not None

    def test_instantiate_without_connection(self):
        from tina4_python.queue_backends import RabbitMQBackend, KafkaBackend

        rmq = RabbitMQBackend()
        kafka = KafkaBackend()
        assert rmq is not None
        assert kafka is not None


class TestKafkaSecurityConfig:
    """Lock-in for KafkaConnector._security_config() (PR #52 + TINA4_KAFKA_* alias).

    SSL/SASL settings are read from the Tina4-namespaced env var first, then the
    bare librdkafka name; unset keys leave librdkafka's PLAINTEXT default.
    """

    _VARS = [
        "TINA4_KAFKA_SECURITY_PROTOCOL", "KAFKA_SECURITY_PROTOCOL",
        "TINA4_KAFKA_SSL_CA_LOCATION", "KAFKA_SSL_CA_LOCATION",
        "TINA4_KAFKA_SASL_MECHANISM", "KAFKA_SASL_MECHANISM",
        "TINA4_KAFKA_SASL_USERNAME", "KAFKA_SASL_USERNAME",
        "TINA4_KAFKA_SASL_PASSWORD", "KAFKA_SASL_PASSWORD",
    ]

    def _clean(self, monkeypatch):
        for v in self._VARS:
            monkeypatch.delenv(v, raising=False)

    def _cfg(self):
        from tina4_python.queue_backends.kafka_backend import KafkaBackend
        return KafkaBackend._security_config()

    def test_no_env_is_empty(self, monkeypatch):
        # NEGATIVE: nothing set -> {} (librdkafka keeps its PLAINTEXT default).
        self._clean(monkeypatch)
        assert self._cfg() == {}

    def test_bare_kafka_names(self, monkeypatch):
        # POSITIVE: the contributor's exact env (bare KAFKA_*) still works.
        self._clean(monkeypatch)
        monkeypatch.setenv("KAFKA_SECURITY_PROTOCOL", "SSL")
        monkeypatch.setenv("KAFKA_SSL_CA_LOCATION", "/etc/ssl/ca.pem")
        assert self._cfg() == {"security.protocol": "SSL", "ssl.ca.location": "/etc/ssl/ca.pem"}

    def test_tina4_namespaced_names(self, monkeypatch):
        # POSITIVE: Tina4-namespaced env vars are honoured.
        self._clean(monkeypatch)
        monkeypatch.setenv("TINA4_KAFKA_SECURITY_PROTOCOL", "SASL_SSL")
        assert self._cfg() == {"security.protocol": "SASL_SSL"}

    def test_tina4_takes_precedence_over_bare(self, monkeypatch):
        # PRECEDENCE: TINA4_KAFKA_* wins when both are set.
        self._clean(monkeypatch)
        monkeypatch.setenv("KAFKA_SECURITY_PROTOCOL", "SSL")
        monkeypatch.setenv("TINA4_KAFKA_SECURITY_PROTOCOL", "SASL_SSL")
        assert self._cfg()["security.protocol"] == "SASL_SSL"

    def test_sasl_keys_mapped(self, monkeypatch):
        # POSITIVE: optional SASL creds map to the rdkafka sasl.* keys.
        self._clean(monkeypatch)
        monkeypatch.setenv("TINA4_KAFKA_SASL_MECHANISM", "PLAIN")
        monkeypatch.setenv("KAFKA_SASL_USERNAME", "user")
        monkeypatch.setenv("KAFKA_SASL_PASSWORD", "secret")
        cfg = self._cfg()
        assert cfg == {"sasl.mechanism": "PLAIN", "sasl.username": "user", "sasl.password": "secret"}


_MONGO_TEST_URL_FACADE = os.environ.get("TINA4_TEST_MONGO_URI", "mongodb://localhost:27017")


@pytest.mark.skipif(not _pymongo_available(), reason="pymongo not installed")
@pytest.mark.skipif(not _mongo_reachable(), reason="MongoDB not reachable for the live queue dead-letter test")
class TestMongoQueueDeadLetterLive:
    """Dead-letter + retry_failed end-to-end through the Queue facade against a
    LIVE MongoDB (no mocks).

    This replaces an earlier contract test that wired a MagicMock collection onto
    the adapter -- a test double standing in for the real dependency, which the
    project's no-mock rule forbids and which never exercised real Mongo (the kind
    of gap that let the queue bugs ship). The kwarg contract is now locked
    mock-free by TestQueueAdapterSignatureContract; THIS test proves the actual
    behaviour against a real broker. It uses a throwaway, namespaced
    tina4_test_* database and drops it on teardown, so it never touches
    application data.
    """

    TOPIC = "tina4_test_dead_letter"
    DB_NAME = "tina4_test_queue"
    COLLECTION = "tina4_test_queue_jobs"

    @pytest.fixture()
    def queue(self, monkeypatch):
        from tina4_python.queue import Queue
        # Point the Mongo queue backend at a throwaway, namespaced database.
        monkeypatch.setenv("TINA4_MONGO_URI", _MONGO_TEST_URL_FACADE)
        monkeypatch.setenv("TINA4_MONGO_DB", self.DB_NAME)
        monkeypatch.setenv("TINA4_MONGO_COLLECTION", self.COLLECTION)
        monkeypatch.delenv("TINA4_QUEUE_URL", raising=False)
        q = Queue(topic=self.TOPIC, backend="mongodb", max_retries=2)
        backend = q._backend._backend
        backend._ensure_connected()
        coll = backend._collection
        # Pristine slate, even if a prior run left state behind.
        coll.delete_many({"topic": self.TOPIC})
        coll.delete_many({"topic": f"{self.TOPIC}.dead_letter"})
        yield q
        coll.delete_many({"topic": self.TOPIC})
        coll.delete_many({"topic": f"{self.TOPIC}.dead_letter"})
        try:
            backend._client.drop_database(self.DB_NAME)
        except Exception:
            pass

    def test_fail_past_max_retries_lands_in_dead_letters(self, queue):
        """push -> pop+fail until attempts hit max_retries (2) -> the job moves to
        the dead-letter store and is gone from pending. Real Mongo, no mocks."""
        queue.push({"to": "a@example.com"})
        for _ in range(5):                      # bounded; converges in 2 cycles
            job = queue.pop()
            if job is None:
                break
            job.fail("smtp 550")
            if queue.dead_letters():
                break
        dead = queue.dead_letters()
        assert len(dead) == 1
        assert dead[0].error == "smtp 550"      # failure reason survives to the DLQ
        assert queue.size("pending") == 0       # original no longer pending

    def test_retry_failed_requeues_failed_jobs(self, queue):
        """retry_failed() flips status=failed docs (attempts < max_retries) back to
        pending against a real collection. The auto-retry fail() path never leaves
        a job in "failed" (it re-queues or dead-letters), so seed one real failed
        document directly in the live collection -- real data, not a mock -- to
        exercise the real update_many."""
        coll = queue._backend._backend._collection
        coll.insert_one({
            "_id": "tina4-test-failed-1", "topic": self.TOPIC, "status": "failed",
            "attempts": 1, "payload": {"x": 1}, "error": "boom",
            "available_at": "1970-01-01T00:00:00+00:00",
        })
        n = queue.retry_failed(max_retries=3)
        assert n == 1
        doc = coll.find_one({"_id": "tina4-test-failed-1"})
        assert doc["status"] == "pending"       # requeued
        assert doc["error"] is None             # cleared on requeue


class TestQueueAdapterSignatureContract:
    """Every queue backend adapter must accept the kwargs the Queue passes.

    Queue.dead_letters()/retry_failed() pass max_retries= to whatever backend is
    active. A missing kwarg raised TypeError at call time on MongoDB, RabbitMQ,
    AND Kafka. This inspect-based test guards the whole family at once — no broker
    or driver needed — so the class of bug cannot silently reappear on any backend.
    """

    def _adapter_classes(self):
        from tina4_python.queue.lite_backend import LiteBackend
        from tina4_python.queue.mongo_backend import MongoBackend
        from tina4_python.queue.rabbitmq_backend import RabbitMQBackend
        from tina4_python.queue.kafka_backend import KafkaBackend
        return {
            "file": LiteBackend, "mongodb": MongoBackend,
            "rabbitmq": RabbitMQBackend, "kafka": KafkaBackend,
        }

    def test_dead_letters_accepts_max_retries_on_every_backend(self):
        import inspect
        for name, cls in self._adapter_classes().items():
            params = inspect.signature(cls.dead_letters).parameters
            assert "max_retries" in params, f"{name}.dead_letters() missing max_retries"

    def test_retry_failed_accepts_max_retries_on_every_backend(self):
        import inspect
        for name, cls in self._adapter_classes().items():
            params = inspect.signature(cls.retry_failed).parameters
            assert "max_retries" in params, f"{name}.retry_failed() missing max_retries"


# ── Live RabbitMQ Integration (real broker, no mocks) ────────────────

def _parse_amqp_url(url):
    """Parse amqp://[user:pass@]host[:port][/vhost] into a config dict."""
    import re
    rest = re.sub(r"^amqps?://", "", url)
    username, password, vhost = "guest", "guest", "/"
    if "@" in rest:
        creds, rest = rest.split("@", 1)
        if ":" in creds:
            username, password = creds.split(":", 1)
        else:
            username = creds
    hostport = rest
    if "/" in rest:
        hostport, vh = rest.split("/", 1)
        if vh:
            vhost = vh if vh.startswith("/") else "/" + vh
    host = hostport
    port = 5672
    if ":" in hostport:
        host, port_s = hostport.split(":", 1)
        port = int(port_s)
    return {"host": host or "localhost", "port": port or 5672,
            "username": username, "password": password, "vhost": vhost}


def _rabbitmq_reachable(host, port):
    return _reachable(host, port)


_RABBIT_URL = os.environ.get("TINA4_TEST_RABBITMQ_URL", "")
_RABBIT_CFG = _parse_amqp_url(_RABBIT_URL) if _RABBIT_URL else None


@pytest.mark.skipif(
    not _RABBIT_URL,
    reason="Set TINA4_TEST_RABBITMQ_URL (e.g. amqp://guest:guest@localhost:5672) for the live RabbitMQ test.",
)
@pytest.mark.skipif(
    _RABBIT_CFG is not None and not _rabbitmq_reachable(_RABBIT_CFG["host"], _RABBIT_CFG["port"]),
    reason="RabbitMQ broker unreachable.",
)
class TestRabbitMQLiveRawHandshake:
    """Exercise the REAL broker over the RAW AMQP path (no pika, no mocks).

    Locks in the Connection.TuneOk negotiation fix: the raw fallback must echo
    the broker's channel-max from Connection.Tune rather than hardcode 0 (which
    RabbitMQ treats as exceeding its proposed 2047 and aborts the handshake).
    Forcing ``_use_pika = False`` targets the raw code path specifically — pika
    negotiates Tune itself, so it would not cover the bug. A full
    connect -> size(0) -> enqueue -> size(1) -> dequeue -> acknowledge -> size(0)
    cycle on a fresh queue proves the raw handshake and lifecycle work.
    """

    def _raw_backend(self):
        from tina4_python.queue_backends.rabbitmq_backend import RabbitMQConnector
        backend = RabbitMQConnector(**_RABBIT_CFG)
        backend._use_pika = False  # force the raw AMQP socket path
        return backend

    def test_raw_full_lifecycle(self):
        topic = "tina4_test_" + secrets.token_hex(8)

        backend = self._raw_backend()
        backend.connect()  # raw AMQP 0-9-1 handshake — the bug threw here
        try:
            assert backend.size(topic) == 0
            msg_id = backend.enqueue(topic, {"task": "live", "value": 7})
            assert msg_id
        finally:
            backend.close()

        reader = self._raw_backend()
        reader.connect()
        try:
            assert reader.size(topic) == 1
            message = reader.dequeue(topic)
            assert isinstance(message, dict)
            assert message.get("task") == "live"
            assert message.get("value") == 7
            assert message.get("id") == msg_id
            reader.acknowledge(topic, msg_id)
        finally:
            reader.close()

        verifier = self._raw_backend()
        verifier.connect()
        try:
            assert verifier.size(topic) == 0
            # Cleanup: purge the now-empty durable queue.
            verifier._queue_purge_raw(topic)
        finally:
            verifier.close()


# ── Feature 48 audit: job lifecycle over REAL brokers (ADR-0022) ─────
#
# The suite above proves the CONNECTORS work against live RabbitMQ/Kafka. It
# never drove Job.complete()/Job.fail() through those connectors, and that gap
# is where three data-loss bugs lived undetected. These lock the LIFECYCLE.
# No mocks: every case below talks to a real broker.


@pytest.mark.skipif(not _confluent_available(), reason="confluent-kafka not installed")
@pytest.mark.skipif(not _kafka_reachable(), reason="Kafka not reachable")
class TestKafkaJobLifecycleLive:
    """Kafka has no per-record nack, so a retry is a re-produce + an offset commit.

    Authority: Kafka commits a consumer-group OFFSET, not individual records, so
    the only way to retry one record without replaying its successors is to
    re-produce it and commit past the original. Confluent's retry-topic pattern
    and Spring Kafka's DeadLetterPublishingRecoverer both work this way.
    """

    def _queue(self, topic, max_retries=3, group=None):
        # group=None mints a fresh consumer group. Pass an explicit group to
        # model a RESTARTED worker rejoining the same group, which is the only
        # way to observe a committed offset.
        os.environ["TINA4_KAFKA_BROKERS"] = _KAFKA_BROKER
        os.environ["TINA4_KAFKA_GROUP_ID"] = group or ("tina4_test_" + secrets.token_hex(8))
        os.environ.pop("TINA4_QUEUE_URL", None)
        from tina4_python.queue import Queue
        return Queue(topic=topic, backend="kafka", max_retries=max_retries)

    @staticmethod
    def _close(queue):
        try:
            queue._backend._backend.close()
        except Exception:  # noqa: BLE001
            pass

    def test_kafka_fail_with_retries_left_redelivers_instead_of_dropping(self):
        """fail() below max_retries must re-deliver, not silently destroy the job.

        Regression: KafkaBackend.fail() had no else branch. A job failing its
        FIRST attempt (the common case) was neither re-published nor
        dead-lettered - the consumer position had already advanced past the
        record, so the job simply vanished.
        """
        topic = "tina4_test_" + secrets.token_hex(8)
        queue = self._queue(topic, max_retries=3)
        try:
            queue.push({"work": "retry-me"})
            job = queue.pop()
            assert job is not None, "real Kafka did not return the pushed job"
            job.fail("first attempt blew up")

            again = queue.pop()
            assert again is not None, (
                "a job failed with retries remaining was DROPPED: neither "
                "re-delivered nor dead-lettered"
            )
            assert again.payload == {"work": "retry-me"}
            assert again.attempts == 1, (
                "the retry must carry the incremented attempt count, otherwise "
                "the job can never reach the dead-letter topic"
            )
        finally:
            self._close(queue)

    def test_kafka_fail_then_complete_does_not_bury_the_failed_job(self):
        """Completing a LATER job must not commit an offset past a failed one.

        Regression: complete() committed the consumer offset, so completing B
        after failing A moved the group past A permanently. A was unrecoverable
        even by a brand-new consumer in the same group.
        """
        topic = "tina4_test_" + secrets.token_hex(8)
        group = "tina4_test_" + secrets.token_hex(8)
        queue = self._queue(topic, max_retries=3, group=group)
        try:
            queue.push({"which": "A"})
            queue.push({"which": "B"})
            job_a = queue.pop()
            assert job_a is not None and job_a.payload == {"which": "A"}
            job_a.fail("A blew up but has retries left")
            job_b = queue.pop()
            assert job_b is not None and job_b.payload == {"which": "B"}
            job_b.complete()
        finally:
            self._close(queue)

        # SAME group: a restarted worker resumes from the committed offset.
        survivor = self._queue(topic, max_retries=3, group=group)
        try:
            os.environ["TINA4_KAFKA_ASSIGN_TIMEOUT"] = "25"
            seen = []
            for _ in range(3):
                job = survivor.pop()
                if job is None:
                    break
                seen.append(job.payload)
            assert {"which": "A"} in seen, (
                "completing B buried the failed A: a fresh consumer in the same "
                "group can no longer see it. Failed work must survive a "
                "successor's commit."
            )
        finally:
            self._close(survivor)

    def test_kafka_fail_past_max_retries_reaches_dead_letters(self):
        """attempts must survive the re-produce so the job can finally die.

        Regression: attempts was re-read from the pushed body (always 0), so
        the dead-letter branch was only reachable when max_retries <= 1.
        """
        topic = "tina4_test_" + secrets.token_hex(8)
        queue = self._queue(topic, max_retries=2)
        try:
            queue.push({"work": "poison"})
            for attempt in range(4):
                job = queue.pop()
                if job is None:
                    break
                job.fail("attempt %d" % attempt)
            dead = queue.dead_letters()
            assert dead, (
                "a job failed more times than max_retries never reached the "
                "dead-letter topic - it would be retried forever"
            )
            assert dead[0].payload == {"work": "poison"}
        finally:
            self._close(queue)


@pytest.mark.skipif(not _pika_available(), reason="pika not installed")
@pytest.mark.skipif(
    not _reachable(_RABBIT_HOST, _RABBIT_PORT),
    reason="RabbitMQ not reachable",
)
class TestRabbitMQJobLifecycleLive:
    """AMQP 0-9-1 basic.nack(requeue=1) returns the body UNMODIFIED.

    The spec carries no delivery counter, so a retry count cannot ride on a
    requeue. Every mainstream AMQP client that counts attempts (Celery,
    Spring AMQP's RepublishMessageRecoverer, laravel-queue-rabbitmq)
    acknowledges the original and re-publishes a body carrying the new count.
    """

    @pytest.fixture(autouse=True)
    def _contain_the_queue_url(self):
        """TINA4_QUEUE_URL is set to an amqp:// URL below and MUST NOT escape.

        MEASURED on the lab 2026-08-04: it was set with a RAW os.environ
        assignment and never unset, so it survived this class and every LATER
        test that built a MongoDB queue received 'amqp://guest:guest@host:5672/'
        as its Mongo URI and died with pymongo InvalidURI. That made all five
        mongodb cases of test_queue_failure_lifecycle.py red while this file
        itself stayed green - a leak whose only symptom is somebody else's suite
        failing, which is the worst kind to debug.

        It only bites where RabbitMQ is actually reachable (this class is
        skipped otherwise), so it was invisible on a developer machine and red
        on the lab, where the broker is up and TINA4_REQUIRE_SERVICES is set.
        """
        saved = os.environ.get("TINA4_QUEUE_URL")
        try:
            yield
        finally:
            if saved is None:
                os.environ.pop("TINA4_QUEUE_URL", None)
            else:
                os.environ["TINA4_QUEUE_URL"] = saved

    def _queue(self, topic, max_retries=3):
        os.environ["TINA4_QUEUE_URL"] = "amqp://guest:guest@%s:%d/" % (_RABBIT_HOST, _RABBIT_PORT)
        from tina4_python.queue import Queue
        return Queue(topic=topic, backend="rabbitmq", max_retries=max_retries)

    @staticmethod
    def _close(queue, topic):
        connector = queue._backend._backend
        try:
            connector.clear(topic)
            connector.clear(topic + ".dead_letter")
        except Exception:  # noqa: BLE001
            pass
        try:
            connector.close()
        except Exception:  # noqa: BLE001
            pass

    def test_rabbitmq_fail_past_max_retries_reaches_dead_letters(self):
        """A persistently failing job must die, not spin forever.

        Regression: fail() nacked with requeue=True. AMQP returns the ORIGINAL
        body, so attempts came back as 0 on every redelivery and
        attempts >= max_retries could never trip for max_retries >= 2. The job
        was redelivered forever with no dead-letter escape.
        """
        topic = "tina4_test_" + secrets.token_hex(8)
        queue = self._queue(topic, max_retries=2)
        try:
            queue.push({"work": "poison"})
            for attempt in range(5):
                job = queue.pop()
                if job is None:
                    break
                job.fail("attempt %d" % attempt)
            dead = queue.dead_letters()
            assert dead, (
                "a job failed more times than max_retries never reached the "
                "dead-letter queue - the consumer would spin on it forever"
            )
            assert dead[0].payload == {"work": "poison"}
        finally:
            self._close(queue, topic)

    def test_rabbitmq_fail_carries_the_attempt_count_across_a_redelivery(self):
        """attempts must be observable on the NEXT pop, not reset to zero."""
        topic = "tina4_test_" + secrets.token_hex(8)
        queue = self._queue(topic, max_retries=5)
        try:
            queue.push({"work": "count-me"})
            first = queue.pop()
            assert first is not None and first.attempts == 0
            first.fail("one")
            second = queue.pop()
            assert second is not None, "the failed job was not re-delivered"
            assert second.attempts == 1, (
                "attempts reset to 0 across the redelivery, so the job can "
                "never reach max_retries"
            )
        finally:
            self._close(queue, topic)

    def test_rabbitmq_complete_acknowledges_that_job_not_the_last_popped(self):
        """Two pops before an ack must not make complete(A) acknowledge B.

        Authority: AMQP 0-9-1 s1.8.3.12 - delivery-tag identifies ONE delivery
        on the channel. Regression: the connector kept a single
        _last_delivery_tag slot, so the second pop overwrote the first and
        complete(A) acked B. A was redelivered (duplicate work) and B was
        acked without ever being completed (lost work).
        """
        topic = "tina4_test_" + secrets.token_hex(8)
        queue = self._queue(topic, max_retries=3)
        connector = queue._backend._backend
        try:
            queue.push({"which": "A"})
            queue.push({"which": "B"})
            job_a = queue.pop()
            job_b = queue.pop()
            assert job_a.payload == {"which": "A"}
            assert job_b.payload == {"which": "B"}

            job_a.complete()
            # Dropping the channel requeues everything still unacked. Whatever
            # comes back is what complete(A) did NOT acknowledge.
            connector.close()

            verifier = self._queue(topic, max_retries=3)
            try:
                survivors = []
                while True:
                    job = verifier.pop()
                    if job is None:
                        break
                    survivors.append(job.payload)
                assert survivors == [{"which": "B"}], (
                    "complete(A) acknowledged the wrong delivery: expected B "
                    "to survive unacked, got %r" % (survivors,)
                )
            finally:
                self._close(verifier, topic)
        finally:
            try:
                connector.close()
            except Exception:  # noqa: BLE001
                pass
