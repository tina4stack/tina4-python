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
from typing import Dict, Any

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
    data: str
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

    def consume(self, acknowledge=True, consumer_callback=None):
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
            elif self.config.queue_type == "mongo-queue-service":
                msg = self.consumer.next(channel=prefix + self.topic)
                if msg:
                    data = msg.payload
                    status = 2 if acknowledge else 1
                    if acknowledge:
                        msg.complete()
                    response = Message(data["message_id"], data["msg"], data["user_id"], status, msg.queued_at, "0")
            elif self.config.queue_type == "rabbitmq":
                method, _, body = self.producer.basic_get(queue=prefix + self.topic, auto_ack=acknowledge)
                if method:
                    data = json.loads(body)
                    status = 2 if acknowledge else 1
                    response = Message(data["message_id"], data["msg"], data["user_id"], status, data["in_time"], method.delivery_tag)
            elif self.config.queue_type == "kafka":
                msg = self.consumer.poll(1.0)
                if msg and not msg.error():
                    data = json.loads(msg.value().decode('utf-8'))
                    status = 2 if acknowledge else 1
                    response = Message(data["message_id"], data["msg"], data["user_id"], status, data["in_time"], msg.offset())
                else:
                    return
            if consumer_callback:
                consumer_callback(self.consumer, None, response)
            if self.callback:
                self.callback(response)
        except Exception as e:
            Debug.error(f"Error consuming {self.topic}: {e}")

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
            config = self.config.mongo_queue_config or {"host": "localhost", "port": 27017, "timeout": 300, "max_attempts": 5}
            client_args = {"host": config["host"], "port": config["port"]}
            if "username" in config and "password" in config:
                client_args.update(username=config["username"], password=config["password"])
            client = pymongo.MongoClient(**client_args).queue
            queue = mongo_queue.queue.Queue(client[self.get_prefix() + self.topic],
                                            consumer_id=self.topic, timeout=config["timeout"], max_attempts=config["max_attempts"])
            self.producer = self.consumer = queue
        except Exception as e:
            Debug.error("Failed to init mongo-queue-service", e)

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
    def __init__(self, queues, consumer_callback=None, acknowledge=True):
        self.queues = [queues] if not isinstance(queues, list) else queues
        self.consumer_callback = consumer_callback
        self.acknowledge = acknowledge

    def run(self, sleep=1, iterations=None):
        counter = 0
        Debug.debug("Consuming", [q.topic for q in self.queues])
        while True:
            for queue in self.queues:
                queue.consume(self.acknowledge, self.consumer_callback)
            counter += 1
            if iterations and counter >= iterations:
                break
            time.sleep(sleep)