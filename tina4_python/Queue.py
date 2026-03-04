#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""Multi-backend message queue system for Tina4.

Provides a unified API for producing and consuming messages across four
queue backends:

- **litequeue** -- lightweight, file-based SQLite queue (default; zero config).
- **mongo-queue-service** -- MongoDB-backed queue via the ``mongo_queue`` package.
- **rabbitmq** -- AMQP queue via the ``pika`` library.
- **kafka** -- Apache Kafka via the ``confluent_kafka`` library.

Typical usage::

    from tina4_python.Queue import Queue, Producer, Consumer

    queue = Queue(topic="emails")
    Producer(queue).produce({"to": "alice@example.com"})

    consumer = Consumer(queue)
    for msg in consumer.messages():
        print(msg.data)

The backend is selected through the :class:`Config` class (``queue_type``
attribute).  Each backend is lazily initialised the first time a
:class:`Queue` is instantiated.
"""

__all__ = ["Queue", "Producer", "Consumer", "Message", "Config"]

import json
import sys
import os
import importlib
import time
from tina4_python import Debug
from dataclasses import dataclass
from typing import Dict, Any, Generator, List

# Extracted from https://github.com/stevesimmons/uuid7 under MIT license
time_ns = time.time_ns

def uuid7(last=None):
    if last is None:
        last = [0, 0, 0, 0]
    ns = time_ns()
    if ns == 0:
        return '00000000-0000-0000-0000-000000000000'
    sixteen_secs = 16_000_000_000
    t1, rest1 = divmod(ns, sixteen_secs)
    t2, rest2 = divmod(rest1 << 16, sixteen_secs)
    t3, _ = divmod(rest2 << 12, sixteen_secs)
    t3 |= 7 << 12  # UUID version
    if t1 == last[0] and t2 == last[1] and t3 == last[2]:
        if last[3] < 0x3FFF:
            last[3] += 1
    else:
        last[:] = (t1, t2, t3, 0)
    t4 = (2 << 14) | last[3]  # UUID variant
    rand = os.urandom(6)
    return f"{t1:>08x}-{t2:>04x}-{t3:>04x}-{t4:>04x}-{rand.hex()}"

class Config:
    """Configuration for the queue backend.

    Attributes:
        queue_type: Backend identifier. One of ``"litequeue"``,
            ``"mongo-queue-service"``, ``"rabbitmq"``, or ``"kafka"``.
        litequeue_database_name: File path for the SQLite database used by
            the litequeue backend.  Defaults to ``"queue.db"``.
        kafka_config: Optional dict of Kafka configuration passed directly
            to ``confluent_kafka.Consumer`` / ``Producer``.  When *None* a
            minimal localhost config is used.
        rabbitmq_config: Optional dict with ``host``, ``port``, and
            optionally ``username`` / ``password`` keys for the RabbitMQ
            connection.
        mongo_queue_config: Optional dict with ``host``, ``port`` (or
            ``uri``), ``timeout``, ``max_attempts``, and optional
            ``username`` / ``password`` keys for MongoDB.
        rabbitmq_queue: Name of the RabbitMQ queue.  Overwritten at runtime
            by ``init_rabbitmq`` with the server-assigned queue name.
        prefix: Optional string prepended (with a trailing underscore) to
            topic / queue names, useful for environment-based namespacing
            (e.g. ``"staging"``).
    """

    queue_type = "litequeue"  # litequeue, mongo-queue-service, rabbitmq, kafka
    litequeue_database_name = "queue.db"
    kafka_config = None
    rabbitmq_config = None
    mongo_queue_config = None
    rabbitmq_queue = "default-queue"
    prefix = ""

@dataclass(frozen=False)
class Message:
    """A single message retrieved from (or destined for) the queue.

    Attributes:
        message_id: UUID-v7 string that uniquely identifies this message.
        data: The message payload -- either the original dict/string that
            was passed to :meth:`Queue.produce`, or the deserialised form
            returned by :meth:`Queue.consume`.
        user_id: Optional identifier of the user who produced the message.
            May be *None*.
        status: Backend-specific integer status code.  Typically ``0`` for
            pending, ``1`` for in-progress, and ``2`` for acknowledged /
            completed.
        time_stamp: Nanosecond-precision Unix timestamp (from
            ``time.time_ns()``) recorded when the message was produced.
        delivery_tag: Backend-specific delivery identifier.  Used by
            RabbitMQ for explicit ack/nack; set to ``"0"`` for backends
            that do not use delivery tags.
    """

    message_id: str
    data: str|dict
    user_id: str
    status: int
    time_stamp: int
    delivery_tag: str

class Queue:
    """Unified message queue backed by one of the supported backends.

    On construction the appropriate backend is initialised automatically
    based on ``config.queue_type``.  Use :meth:`produce` to publish
    messages and :meth:`consume` to retrieve them.  For higher-level
    usage see the :class:`Producer` and :class:`Consumer` wrappers.
    """

    def __init__(self, config=None, topic="default-queue", callback=None, batch_size=1):
        """Initialise the queue and connect to the configured backend.

        Args:
            config: A :class:`Config` instance describing which backend to
                use and how to connect to it.  When *None*, a default
                ``Config`` (litequeue) is used.
            topic: The topic or queue name to produce to / consume from.
            callback: Optional callable invoked with each :class:`Message`
                as it is consumed.  Signature: ``callback(message)``.
            batch_size: Number of messages to collect per
                :meth:`consume` yield.  When greater than 1, :meth:`consume`
                yields a list of :class:`Message` objects instead of a
                single message.
        """
        if config is None:
            config = Config()
        self.config = config
        self.topic = topic
        self.callback = callback
        self.producer = None
        self.consumer = None
        self.batch_size = batch_size
        init_method = f"init_{config.queue_type.replace('-', '_')}"
        getattr(self, init_method)()

    def get_prefix(self):
        """Return the topic name prefix derived from :attr:`Config.prefix`.

        Returns:
            A string of the form ``"<prefix>_"`` when a prefix is
            configured, or an empty string otherwise.
        """
        return f"{self.config.prefix}_" if self.config.prefix else ""

    def produce(self, value, user_id=None, delivery_callback=None):
        """Publish a message to the queue.

        Args:
            value: The message payload (dict or string).  Must not be
                *None*.
            user_id: Optional identifier of the producing user, stored
                alongside the message.
            delivery_callback: Optional callable invoked after the message
                is delivered (or on error).  Signature:
                ``callback(producer, error, message)`` where *error* is
                *None* on success and *message* is a :class:`Message` (or
                *None* on failure).

        Returns:
            A :class:`Message` on success for non-Kafka backends, *None*
            for Kafka (delivery is asynchronous), or the raised
            ``Exception`` instance if an error occurred and no
            *delivery_callback* re-raises it.

        Raises:
            Exception: If *value* is *None*.
        """
        if value is None:
            raise Exception("Cannot send None value")
        prefix = self.get_prefix()
        body = {"message_id": uuid7(), "msg": value, "user_id": user_id, "in_time": time_ns()}
        msg_str = json.dumps(body)
        try:
            if self.config.queue_type == "litequeue":
                msg = self.producer.put(msg_str)
                response = Message(msg.message_id, value, user_id, int(msg.status), msg.in_time, "0")
            elif self.config.queue_type == "mongo-queue-service":
                self.producer.put(body, priority=1, channel=prefix + self.topic, job_id=body["message_id"])
                response = Message(body["message_id"], value, user_id, 0, body["in_time"], "0")
            elif self.config.queue_type == "rabbitmq":
                self.producer.basic_publish(exchange=prefix + self.topic, routing_key='', body=msg_str)
                response = Message(body["message_id"], value, user_id, 0, body["in_time"], "0")
            elif self.config.queue_type == "kafka":
                def kafka_cb(err, kafka_msg):
                    if delivery_callback:
                        delivery_callback(self.producer, err, Message(body["message_id"], value, user_id, 0, body["in_time"], kafka_msg.offset() if not err else 0))
                self.producer.produce(prefix + self.topic, msg_str, user_id, callback=kafka_cb)
                self.producer.poll(1000)
                self.producer.flush()
                return None
            if delivery_callback:
                delivery_callback(self.producer, None, response)
            return response
        except Exception as e:
            if delivery_callback:
                delivery_callback(self.producer, e, None)
            return e

    def consume(self, acknowledge: bool = True) -> Generator[Message | List[Message], None, None]:
        """
        Generator that continuously yields messages from the queue as they arrive.
        Use like:
            for msg in queue.consume():
                print(msg.data)
        If a callback was provided in __init__, it will also be called for each message.
        """
        prefix = self.get_prefix()
        is_batch = self.batch_size > 1
        count_messages = 0
        try:
            message_found = True
            batch = []
            while message_found and count_messages < self.batch_size:
                response = None
                message_found = False

                if self.config.queue_type == "litequeue":
                    msg = self.consumer.pop()
                    if msg:
                        message_found = True
                        data = json.loads(msg.data)
                        response = Message(msg.message_id, data["msg"], data["user_id"], msg.status, msg.in_time, "0")
                        if acknowledge:
                            self.consumer.done(msg.message_id)
                            updated = self.consumer.get(msg.message_id)
                            if updated:
                                response.status = int(updated.status)

                elif self.config.queue_type == "mongo-queue-service":
                    msg = self.consumer.next(channel=prefix + self.topic)
                    if msg:
                        message_found = True
                        data = msg.payload
                        response = Message(data["message_id"], data["msg"], data["user_id"], 2 if acknowledge else 1, msg.queued_at, "0")
                        if acknowledge:
                            msg.complete()

                elif self.config.queue_type == "rabbitmq":
                    method, _, body = self.consumer.basic_get(queue=prefix + self.topic, auto_ack=acknowledge)
                    if method:
                        message_found = True
                        data = json.loads(body)
                        response = Message(data["message_id"], data["msg"], data["user_id"], 2 if acknowledge else 1, data["in_time"], method.delivery_tag)

                elif self.config.queue_type == "kafka":
                    msg = self.consumer.poll(0.1)
                    if msg and not msg.error():
                        message_found = True
                        data = json.loads(msg.value().decode('utf-8'))
                        response = Message(data["message_id"], data["msg"], data["user_id"], 2 if acknowledge else 1, data["in_time"], str(msg.offset()))
                        if acknowledge:
                            self.consumer.commit()

                if message_found:
                    count_messages += 1
                    batch.append(response)
                    if self.callback:
                        try:
                            self.callback(response)
                        except Exception as e:
                            Debug.error("Failed to run queue callback", str(e))
                else:
                    # No message available right now — brief sleep to avoid busy loop
                    time.sleep(0.05)

            if len(batch) > 0:
                if not is_batch:
                    yield batch[0]
                else:
                    yield batch
        except Exception as e:
            Debug.error(f"Error consuming {self.topic}: {e}")
            raise  # Re-raise to stop consumption on fatal error

    # init methods remain unchanged
    def init_litequeue(self):
        try:
            litequeue = importlib.import_module("litequeue")
            q = litequeue.LiteQueue(self.config.litequeue_database_name, queue_name=self.get_prefix() + self.topic)
            self.producer = self.consumer = q
        except Exception as e:
            Debug.error("Failed to init litequeue", e)
            sys.exit(1)

    def init_mongo_queue_service(self):
        try:
            mongo_queue = importlib.import_module("mongo_queue")
            pymongo = importlib.import_module("pymongo")

            # Use provided config or fall back to defaults
            config = self.config.mongo_queue_config or {}
            host = config.get("host", "localhost")
            port = config.get("port", 27017)
            uri = config.get("uri", None)
            timeout = config.get("timeout", 300)
            max_attempts = config.get("max_attempts", 5)  # ← default value
            username = config.get("username")
            password = config.get("password")

            if uri is None:
                client_args = {"host": host, "port": port}
            else:
                client_args = {"host": uri}

            if username and password:
                client_args.update(username=username, password=password)

            client = pymongo.MongoClient(**client_args)
            db = client.queue  # default database name used by mongo_queue

            collection_name = self.get_prefix() + self.topic
            queue = mongo_queue.queue.Queue(
                db[collection_name],
                consumer_id=self.topic,
                timeout=timeout,
                max_attempts=max_attempts
            )
            self.producer = self.consumer = queue
            Debug.info(f"Mongo queue initialized: {collection_name}")
        except Exception as e:
            Debug.error("Failed to init mongo-queue-service", e)
            raise

    def init_rabbitmq(self):
        try:
            pika = importlib.import_module("pika")
            config = self.config.rabbitmq_config or {"host": "localhost", "port": 5672}
            params = pika.ConnectionParameters(host=config["host"], port=config["port"], virtual_host=self.get_prefix() or "/")
            if "username" in config:
                params.credentials = pika.PlainCredentials(config["username"], config["password"])
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.exchange_declare(exchange=self.topic, exchange_type="topic")
            result = channel.queue_declare(self.topic, exclusive=False)
            self.config.rabbitmq_queue = result.method.queue
            channel.queue_bind(exchange=self.topic, queue=self.config.rabbitmq_queue, routing_key='')
            self.producer = self.consumer = channel
        except Exception as e:
            Debug.error("Failed to init rabbitmq", e)

    def init_kafka(self):
        try:
            kafka = importlib.import_module("confluent_kafka")
            config = self.config.kafka_config or {'bootstrap.servers': 'localhost:9092', 'group.id': self.get_prefix() + 'default-queue', 'auto.offset.reset': 'earliest'}
            self.consumer = kafka.Consumer(config)
            self.consumer.subscribe([self.get_prefix() + self.topic])
            prod_config = config.copy()
            prod_config.pop('auto.offset.reset', None)
            prod_config.pop('group.id', None)
            self.producer = kafka.Producer(prod_config)
        except Exception as e:
            Debug.error("Failed to init kafka", e)

class Producer:
    """Convenience wrapper for producing messages on a :class:`Queue`.

    Holds a reference to a :class:`Queue` and an optional default
    delivery callback, simplifying repeated ``produce`` calls::

        producer = Producer(queue, delivery_callback=my_cb)
        producer.produce({"key": "value"})
    """

    def __init__(self, queue, delivery_callback=None):
        self.queue = queue
        self.delivery_callback = delivery_callback

    def produce(self, value, user_id=None, delivery_callback=None):
        return self.queue.produce(value, user_id, delivery_callback or self.delivery_callback)

class Consumer:
    """High-level consumer that reads messages from one or more queues.

    Wraps one or more :class:`Queue` instances and provides a continuous
    :meth:`messages` generator as well as a blocking :meth:`run_forever`
    convenience method.  Queues are polled in round-robin order.

    Args:
        queues: A single :class:`Queue` or a list of queues to consume
            from.
        acknowledge: When *True* (default), messages are acknowledged /
            marked done on the backend immediately after retrieval.
        poll_interval: Seconds to sleep when all queues are empty before
            polling again.  Defaults to ``1.0``.
    """

    def __init__(self, queues: List[Queue], acknowledge: bool = True, poll_interval: float = 1.0):
        self.queues = queues if isinstance(queues, list) else [queues]
        self.acknowledge = acknowledge
        self.poll_interval = poll_interval

    def messages(self) -> Generator[Message, None, None]:
        """Yield messages from all registered queues indefinitely.

        Iterates over every queue in round-robin fashion, yielding each
        :class:`Message` (or list of messages when ``batch_size > 1``)
        as it arrives.  When all queues are empty the generator sleeps
        for :attr:`poll_interval` seconds before trying again.

        Yields:
            A :class:`Message` when ``batch_size`` is 1, or a list of
            :class:`Message` objects when ``batch_size > 1``.
        """
        Debug.debug("Consuming from queues", [q.topic for q in self.queues])
        while True:
            emptied_count = 0
            for queue in self.queues:
                drained = False
                for message in queue.consume(self.acknowledge):
                    yield message
                    drained = True
                if not drained:
                    emptied_count += 1
            if emptied_count == len(self.queues):
                time.sleep(self.poll_interval)

    def run_forever(self):
        """Simple blocking runner — easy to use"""
        for message in self.messages():
            Debug.info(f"Received message: {message.message_id} -> {message.data}")

