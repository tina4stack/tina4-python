# Tests for Tina4 Queue Backends — RabbitMQ and Kafka.
"""
Tests cover:
- Backend interface/contract verification
- In-memory operation without external services
- Skip markers for tests requiring actual RabbitMQ/Kafka
"""
import json
import os
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


def _pymongo_available():
    try:
        import pymongo
        return True
    except ImportError:
        return False


# ── Interface Contract Tests ─────────────────────────────────────


class TestQueueBackendContract:
    """Verify that all backends implement the required interface."""

    def test_rabbitmq_backend_has_required_methods(self):
        from tina4_python.queue_backends.rabbitmq_backend import RabbitMQBackend

        backend = RabbitMQBackend()
        assert callable(getattr(backend, "enqueue", None))
        assert callable(getattr(backend, "dequeue", None))
        assert callable(getattr(backend, "acknowledge", None))
        assert callable(getattr(backend, "reject", None))
        assert callable(getattr(backend, "size", None))
        assert callable(getattr(backend, "clear", None))
        assert callable(getattr(backend, "dead_letter", None))
        assert callable(getattr(backend, "close", None))
        assert callable(getattr(backend, "connect", None))

    def test_kafka_backend_has_required_methods(self):
        from tina4_python.queue_backends.kafka_backend import KafkaBackend

        backend = KafkaBackend()
        assert callable(getattr(backend, "enqueue", None))
        assert callable(getattr(backend, "dequeue", None))
        assert callable(getattr(backend, "acknowledge", None))
        assert callable(getattr(backend, "reject", None))
        assert callable(getattr(backend, "size", None))
        assert callable(getattr(backend, "clear", None))
        assert callable(getattr(backend, "dead_letter", None))
        assert callable(getattr(backend, "close", None))
        assert callable(getattr(backend, "connect", None))

    @pytest.mark.skipif(
        not _pymongo_available(),
        reason="pymongo not installed"
    )
    def test_mongodb_backend_has_required_methods(self):
        from tina4_python.queue_backends.mongo_backend import MongoBackend

        backend = MongoBackend()
        assert callable(getattr(backend, "enqueue", None))
        assert callable(getattr(backend, "dequeue", None))
        assert callable(getattr(backend, "acknowledge", None))
        assert callable(getattr(backend, "reject", None))
        assert callable(getattr(backend, "size", None))
        assert callable(getattr(backend, "clear", None))
        assert callable(getattr(backend, "dead_letter", None))
        assert callable(getattr(backend, "close", None))
        assert callable(getattr(backend, "connect", None))


# ── RabbitMQ Backend Tests ───────────────────────────────────────


class TestRabbitMQBackendConfig:
    """Test RabbitMQ backend configuration without connecting."""

    def test_default_config(self):
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

    def test_close_without_connect(self):
        from tina4_python.queue_backends.rabbitmq_backend import RabbitMQBackend

        backend = RabbitMQBackend()
        backend.close()  # Should not raise

    def test_acknowledge_without_delivery_tag(self):
        from tina4_python.queue_backends.rabbitmq_backend import RabbitMQBackend

        backend = RabbitMQBackend()
        backend.acknowledge("test", "msg-1")  # Should not raise

    def test_reject_without_delivery_tag(self):
        from tina4_python.queue_backends.rabbitmq_backend import RabbitMQBackend

        backend = RabbitMQBackend()
        backend.reject("test", "msg-1")  # Should not raise


class TestRabbitMQBackendMocked:
    """Test RabbitMQ backend with mocked pika connection."""

    def _make_backend_with_mock_pika(self):
        from tina4_python.queue_backends.rabbitmq_backend import RabbitMQBackend

        backend = RabbitMQBackend()
        backend._use_pika = True

        # Mock pika module
        mock_pika = MagicMock()
        backend._pika = mock_pika

        # Mock connection and channel
        mock_connection = MagicMock()
        mock_connection.is_open = True
        mock_channel = MagicMock()
        backend._connection = mock_connection
        backend._channel = mock_channel

        return backend, mock_channel

    def test_enqueue_with_pika(self):
        backend, mock_channel = self._make_backend_with_mock_pika()
        msg_id = backend.enqueue("emails", {"to": "alice@test.com"})
        assert isinstance(msg_id, str)
        mock_channel.basic_publish.assert_called_once()
        call_kwargs = mock_channel.basic_publish.call_args
        assert call_kwargs[1]["routing_key"] == "emails"

    def test_dequeue_with_pika_returns_none_when_empty(self):
        backend, mock_channel = self._make_backend_with_mock_pika()
        mock_channel.basic_get.return_value = (None, None, None)
        result = backend.dequeue("emails")
        assert result is None

    def test_dequeue_with_pika_returns_message(self):
        backend, mock_channel = self._make_backend_with_mock_pika()
        mock_method = MagicMock()
        mock_method.delivery_tag = 42
        body = json.dumps({"id": "msg-1", "to": "alice@test.com"}).encode()
        mock_channel.basic_get.return_value = (mock_method, MagicMock(), body)

        result = backend.dequeue("emails")
        assert result is not None
        assert result["id"] == "msg-1"
        assert result["to"] == "alice@test.com"
        assert backend._last_delivery_tag == 42

    def test_acknowledge_with_pika(self):
        backend, mock_channel = self._make_backend_with_mock_pika()
        backend._last_delivery_tag = 42
        backend.acknowledge("emails", "msg-1")
        mock_channel.basic_ack.assert_called_once_with(delivery_tag=42)
        assert backend._last_delivery_tag is None

    def test_reject_with_pika(self):
        backend, mock_channel = self._make_backend_with_mock_pika()
        backend._last_delivery_tag = 42
        backend.reject("emails", "msg-1", requeue=False)
        mock_channel.basic_nack.assert_called_once_with(delivery_tag=42, requeue=False)

    def test_size_with_pika(self):
        backend, mock_channel = self._make_backend_with_mock_pika()
        mock_result = MagicMock()
        mock_result.method.message_count = 15
        mock_channel.queue_declare.return_value = mock_result
        assert backend.size("emails") == 15

    def test_clear_with_pika(self):
        backend, mock_channel = self._make_backend_with_mock_pika()
        backend.clear("emails")
        mock_channel.queue_purge.assert_called_once_with(queue="emails")

    def test_dead_letter_with_pika(self):
        backend, mock_channel = self._make_backend_with_mock_pika()
        backend.dead_letter("emails", {"id": "msg-1", "error": "failed"})
        call_kwargs = mock_channel.basic_publish.call_args
        assert call_kwargs[1]["routing_key"] == "emails.dead_letter"

    def test_close_with_pika(self):
        backend, _ = self._make_backend_with_mock_pika()
        connection = backend._connection
        backend.close()
        connection.close.assert_called_once()
        assert backend._connection is None


# ── Kafka Backend Tests ──────────────────────────────────────────


class TestKafkaBackendConfig:
    """Test Kafka backend configuration without connecting."""

    def test_default_config(self):
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

    def test_close_without_connect(self):
        from tina4_python.queue_backends.kafka_backend import KafkaBackend

        backend = KafkaBackend()
        backend.close()  # Should not raise

    def test_size_returns_zero(self):
        """Kafka doesn't natively support queue size."""
        from tina4_python.queue_backends.kafka_backend import KafkaBackend

        backend = KafkaBackend()
        backend._use_confluent = False
        backend._socket = MagicMock()
        backend._known_topics.add("test")
        assert backend.size("test") == 0

    def test_clear_is_noop(self):
        from tina4_python.queue_backends.kafka_backend import KafkaBackend

        backend = KafkaBackend()
        backend.clear("test")  # Should not raise

    def test_dead_letter_topic_naming(self):
        from tina4_python.queue_backends.kafka_backend import KafkaBackend

        backend = KafkaBackend()
        backend._use_confluent = True

        mock_producer = MagicMock()
        backend._producer = mock_producer

        backend.dead_letter("orders", {"id": "msg-1", "error": "timeout"})
        call_kwargs = mock_producer.produce.call_args
        assert call_kwargs[1]["topic"] == "orders.dead_letter"


class TestKafkaBackendMocked:
    """Test Kafka backend with mocked confluent-kafka."""

    def _make_backend_with_mock_confluent(self):
        from tina4_python.queue_backends.kafka_backend import KafkaBackend

        backend = KafkaBackend()
        backend._use_confluent = True

        mock_producer = MagicMock()
        mock_consumer = MagicMock()
        backend._producer = mock_producer
        backend._consumer = mock_consumer

        return backend, mock_producer, mock_consumer

    def test_enqueue_with_confluent(self):
        backend, mock_producer, _ = self._make_backend_with_mock_confluent()
        msg_id = backend.enqueue("events", {"type": "click"})
        assert isinstance(msg_id, str)
        mock_producer.produce.assert_called_once()
        mock_producer.flush.assert_called_once()

    def test_dequeue_with_confluent_returns_none(self):
        backend, _, mock_consumer = self._make_backend_with_mock_confluent()
        mock_consumer.poll.return_value = None
        result = backend.dequeue("events")
        assert result is None

    def test_dequeue_with_confluent_returns_message(self):
        backend, _, mock_consumer = self._make_backend_with_mock_confluent()
        mock_msg = MagicMock()
        mock_msg.error.return_value = None
        mock_msg.value.return_value = json.dumps({"id": "msg-1", "type": "click"}).encode()
        mock_consumer.poll.return_value = mock_msg

        result = backend.dequeue("events")
        assert result is not None
        assert result["id"] == "msg-1"
        assert result["type"] == "click"

    def test_acknowledge_with_confluent(self):
        backend, _, mock_consumer = self._make_backend_with_mock_confluent()
        mock_msg = MagicMock()
        backend._last_message = mock_msg
        backend.acknowledge("events", "msg-1")
        mock_consumer.commit.assert_called_once_with(message=mock_msg)

    def test_close_with_confluent(self):
        backend, mock_producer, mock_consumer = self._make_backend_with_mock_confluent()
        backend.close()
        mock_producer.flush.assert_called_once()
        mock_consumer.close.assert_called_once()


# ── MongoDB Backend Tests ────────────────────────────────────────


_skip_no_pymongo = pytest.mark.skipif(
    not _pymongo_available(),
    reason="pymongo not installed"
)


@_skip_no_pymongo
class TestMongoDBBackendConfig:
    """Test MongoDB backend configuration without connecting."""

    def test_default_config(self):
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

    def test_close_without_connect(self):
        from tina4_python.queue_backends.mongo_backend import MongoBackend

        backend = MongoBackend()
        backend.close()  # Should not raise


@_skip_no_pymongo
class TestMongoDBBackendMocked:
    """Test MongoDB backend with mocked pymongo client."""

    def _make_backend_with_mock(self):
        from tina4_python.queue_backends.mongo_backend import MongoBackend

        backend = MongoBackend()
        mock_collection = MagicMock()
        backend._collection = mock_collection
        backend._client = MagicMock()
        backend._db = MagicMock()
        return backend, mock_collection

    def test_enqueue_inserts_document(self):
        backend, mock_collection = self._make_backend_with_mock()
        msg_id = backend.enqueue("emails", {"to": "alice@test.com"})
        assert isinstance(msg_id, str)
        mock_collection.insert_one.assert_called_once()
        doc = mock_collection.insert_one.call_args[0][0]
        assert doc["topic"] == "emails"
        assert doc["status"] == "pending"

    def test_dequeue_returns_none_when_empty(self):
        backend, mock_collection = self._make_backend_with_mock()
        mock_collection.find_one_and_update.return_value = None
        result = backend.dequeue("emails")
        assert result is None

    def test_dequeue_returns_message(self):
        backend, mock_collection = self._make_backend_with_mock()
        mock_collection.find_one_and_update.return_value = {
            "_id": "msg-1",
            "data": {"to": "alice@test.com"},
            "topic": "emails",
            "status": "reserved",
        }
        result = backend.dequeue("emails")
        assert result is not None
        assert result["id"] == "msg-1"
        assert result["to"] == "alice@test.com"

    def test_acknowledge_updates_status(self):
        backend, mock_collection = self._make_backend_with_mock()
        backend.acknowledge("emails", "msg-1")
        mock_collection.update_one.assert_called_once()
        call_args = mock_collection.update_one.call_args[0]
        assert call_args[0] == {"_id": "msg-1", "topic": "emails"}
        assert call_args[1]["$set"]["status"] == "completed"

    def test_reject_requeues(self):
        backend, mock_collection = self._make_backend_with_mock()
        backend.reject("emails", "msg-1", requeue=True)
        mock_collection.update_one.assert_called_once()
        call_args = mock_collection.update_one.call_args[0]
        assert call_args[1]["$set"]["status"] == "pending"

    def test_reject_fails(self):
        backend, mock_collection = self._make_backend_with_mock()
        backend.reject("emails", "msg-1", requeue=False)
        mock_collection.update_one.assert_called_once()
        call_args = mock_collection.update_one.call_args[0]
        assert call_args[1]["$set"]["status"] == "failed"

    def test_size(self):
        backend, mock_collection = self._make_backend_with_mock()
        mock_collection.count_documents.return_value = 5
        assert backend.size("emails") == 5
        mock_collection.count_documents.assert_called_once_with(
            {"topic": "emails", "status": "pending"}
        )

    def test_clear(self):
        backend, mock_collection = self._make_backend_with_mock()
        backend.clear("emails")
        mock_collection.delete_many.assert_called_once_with({"topic": "emails"})

    def test_dead_letter(self):
        backend, mock_collection = self._make_backend_with_mock()
        backend.dead_letter("emails", {"id": "msg-1", "error": "failed"})
        mock_collection.insert_one.assert_called_once()
        doc = mock_collection.insert_one.call_args[0][0]
        assert doc["topic"] == "emails.dead_letter"
        assert doc["status"] == "dead"

    def test_close(self):
        backend, _ = self._make_backend_with_mock()
        client = backend._client
        backend.close()
        client.close.assert_called_once()
        assert backend._client is None


class TestResolveBackend:
    """Test _resolve_backend returns the correct adapter for mongodb."""

    @_skip_no_pymongo
    def test_resolve_backend_mongodb(self, monkeypatch):
        from tina4_python.queue import _resolve_backend, _MongoDBAdapter

        monkeypatch.setenv("TINA4_QUEUE_BACKEND", "mongodb")
        adapter = _resolve_backend(None, "test", None, 3)
        assert isinstance(adapter, _MongoDBAdapter)


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
