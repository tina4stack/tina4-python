# Tina4 Queue Backends — pluggable message queue backends, zero core dependencies.
"""
Optional queue backends for RabbitMQ, Kafka, and MongoDB.
Each backend implements the same interface: enqueue, dequeue, acknowledge,
reject, size, clear, dead_letter.

All external packages are optional imports with clear error messages.

    from tina4_python.queue_backends import RabbitMQBackend, KafkaBackend, MongoBackend

    backend = RabbitMQBackend(host="localhost")
    backend.enqueue("emails", {"to": "alice@test.com"})
    msg = backend.dequeue("emails")
    backend.acknowledge("emails", msg["id"])
"""

from tina4_python.queue_backends.rabbitmq_backend import RabbitMQBackend
from tina4_python.queue_backends.kafka_backend import KafkaBackend
from tina4_python.queue_backends.mongo_backend import MongoBackend

__all__ = ["RabbitMQBackend", "KafkaBackend", "MongoBackend"]
