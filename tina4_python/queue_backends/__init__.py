# Tina4 Queue Backends — pluggable message queue backends, zero core dependencies.
"""
Optional queue backends for RabbitMQ and Kafka.
Each backend implements the same interface: enqueue, dequeue, acknowledge,
reject, size, clear, dead_letter.

All external packages are optional imports with clear error messages.

    from tina4_python.queue_backends import RabbitMQBackend, KafkaBackend

    backend = RabbitMQBackend(host="localhost")
    backend.enqueue("emails", {"to": "alice@test.com"})
    msg = backend.dequeue("emails")
    backend.acknowledge("emails", msg["id"])
"""

from tina4_python.queue_backends.rabbitmq_backend import RabbitMQBackend
from tina4_python.queue_backends.kafka_backend import KafkaBackend

__all__ = ["RabbitMQBackend", "KafkaBackend"]
