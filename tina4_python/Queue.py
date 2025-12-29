#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
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

def uuid7(_last=None):
    if _last is None:
        _last = [0, 0, 0, 0]
    ns = time_ns()
    if ns == 0:
        return '00000000-0000-0000-0000-000000000000'
    sixteen_secs = 16_000_000_000
    t1, rest1 = divmod(ns, sixteen_secs)
    t2, rest2 = divmod(rest1 << 16, sixteen_secs)
    t3, _ = divmod(rest2 << 12, sixteen_secs)
    t3 |= 7 << 12  # UUID version
    if t1 == _last[0] and t2 == _last[1] and t3 == _last[2]:
        if _last[3] < 0x3FFF:
            _last[3] += 1
    else:
        _last[:] = (t1, t2, t3, 0)
    t4 = (2 << 14) | _last[3]  # UUID variant
    rand = os.urandom(6)
    return f"{t1:>08x}-{t2:>04x}-{t3:>04x}-{t4:>04x}-{rand.hex()}"

class Config:
    queue_type = "litequeue"  # litequeue, mongo-queue-service, rabbitmq, kafka
    litequeue_database_name = "queue.db"
    kafka_config = None
    rabbitmq_config = None
    mongo_queue_config = None
    rabbitmq_queue = "default-queue"
    prefix = ""

@dataclass(frozen=False)
class Message:
    message_id: str
    data: str|dict
    user_id: str
    status: int
    time_stamp: int
    delivery_tag: str

class Queue:
    def __init__(self, config=None, topic="default-queue", callback=None):
        if config is None:
            config = Config()
        self.config = config
        self.topic = topic
        self.callback = callback
        self.producer = None
        self.consumer = None
        init_method = f"init_{config.queue_type.replace('-', '_')}"
        getattr(self, init_method)()

    def get_prefix(self):
        return f"{self.config.prefix}_" if self.config.prefix else ""

    def produce(self, value, user_id=None, delivery_callback=None):
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

    def consume(self, acknowledge: bool = True) -> Generator[Message, None, None]:
        """
        Generator that yields messages one by one.
        Use like:
            for msg in queue.consume():
                print(msg.data)
        """
        prefix = self.get_prefix()
        try:
            if self.config.queue_type == "litequeue":
                msg = self.consumer.pop()
                if msg:
                    data = json.loads(msg.data)
                    response = Message(msg.message_id, data["msg"], data["user_id"], msg.status, msg.in_time, "0")
                    if acknowledge:
                        self.consumer.done(msg.message_id)
                        msg = self.consumer.get(msg.message_id)
                        response.status = int(msg.status)
                    yield response

            elif self.config.queue_type == "mongo-queue-service":
                msg = self.consumer.next(channel=prefix + self.topic)
                if msg:
                    data = msg.payload
                    response = Message(data["message_id"], data["msg"], data["user_id"], 2 if acknowledge else 1, msg.queued_at, "0")
                    if acknowledge:
                        msg.complete()
                    yield response

            elif self.config.queue_type == "rabbitmq":
                method, _, body = self.consumer.basic_get(queue=prefix + self.topic, auto_ack=acknowledge)
                if method:
                    data = json.loads(body)
                    response = Message(data["message_id"], data["msg"], data["user_id"], 2 if acknowledge else 1, data["in_time"], method.delivery_tag)
                    yield response

            elif self.config.queue_type == "kafka":
                msg = self.consumer.poll(0.1)  # non-blocking poll
                if msg and not msg.error():
                    data = json.loads(msg.value().decode('utf-8'))
                    response = Message(data["message_id"], data["msg"], data["user_id"], 2 if acknowledge else 1, data["in_time"], str(msg.offset()))
                    if acknowledge:
                        self.consumer.commit()
                    yield response

        except Exception as e:
            Debug.error(f"Error consuming {self.topic}: {e}")

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
            timeout = config.get("timeout", 300)
            max_attempts = config.get("max_attempts", 5)  # ← default value
            username = config.get("username")
            password = config.get("password")

            client_args = {"host": host, "port": port}
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
    def __init__(self, queue, delivery_callback=None):
        self.queue = queue
        self.delivery_callback = delivery_callback

    def produce(self, value, user_id=None, delivery_callback=None):
        return self.queue.produce(value, user_id, delivery_callback or self.delivery_callback)

class Consumer:
    def __init__(self, queues: List[Queue], acknowledge: bool = True, poll_interval: float = 1.0):
        self.queues = queues if isinstance(queues, list) else [queues]
        self.acknowledge = acknowledge
        self.poll_interval = poll_interval

    def messages(self) -> Generator[Message, None, None]:
        """Generator that yields messages from all configured queues forever"""
        Debug.debug("Consuming from queues", [q.topic for q in self.queues])
        while True:
            for queue in self.queues:
                for message in queue.consume(self.acknowledge):
                    yield message
            time.sleep(self.poll_interval)

    def run_forever(self):
        """Simple blocking runner — easy to use"""
        for message in self.messages():
            Debug.info(f"Received message: {message.message_id} -> {message.data}")
            # Do something with message here
            # Or just pass to a callback if needed

