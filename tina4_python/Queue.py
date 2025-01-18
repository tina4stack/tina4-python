#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import json
import sys
import importlib
import time
from tina4_python import Debug
from dataclasses import dataclass
from typing import Dict, Any

_DKW: Dict[str, Any] = {}
if sys.version_info >= (3, 10):
    _DKW["slots"] = True


class Config(object):
    queue_type = "litequeue" # can be rabbitmq or kafka as well
    litequeue_database_name = "queue.db"
    kafka_config = None

    def __init__(self):
        pass

@dataclass(frozen=True, **_DKW)
class Message:
    message_id: str
    data: str
    user_id: str
    status: str
    time_stamp: int

class Queue(object):
    def __init__(self, config=None, topic="default-queue"):
        """
        Initializes the queue object
        :param config:
        :param topic:
        """
        if config is None:
            config = Config()
            config.queue_type = "litequeue"
            config.litequeue_database_name = "queue.db"

        Debug.info("Initializing", config.queue_type, topic)
        self.producer = None
        self.consumer = None
        self.topic = topic
        self.config = config

        if config.queue_type == "litequeue":
            self.init_litequeue()
        elif config.queue_type == "rabbitmq":
            self.init_rabbitmq()
        elif config.queue_type == "kafka":
            self.init_kafka()

    def produce(self, value, user_id=None, delivery_callback=None):
        """
        Produces a message to the queue
        :param value:
        :param user_id:
        :param delivery_callback:
        :return:
        """
        if self.config.queue_type == "litequeue":
            try:
                msg = self.producer.put(json.dumps({"msg": value, "user_id": user_id}))
                response_msg = Message(
                    msg.message_id,
                    value,
                    user_id,
                    int(msg.status),
                    msg.in_time
                )
                delivery_callback(self.producer, None, response_msg)
            except Exception as e:
                delivery_callback(self.producer, e, None)
        elif self.config.queue_type == "rabbitmq":
            pass
        elif self.config.queue_type == "kafka":
            pass

        pass

    def consume(self, acknowledge=True, consumer_callback=None):
        """
        Consumes a message from the queue
        :param acknowledge:
        :param consumer_callback:
        :return:
        """
        if self.config.queue_type == "litequeue":
            try:
                msg = self.consumer.pop()
                if msg is not None:
                    data = json.loads(msg.data)
                    response_msg = Message(
                                    msg.message_id,
                                    data["msg"],
                                    data["user_id"],
                                    msg.status,
                                    msg.in_time
                    )

                    if consumer_callback is not None:
                        consumer_callback(self.consumer, None, response_msg)

                    if acknowledge:
                        self.consumer.done(msg.message_id)
                        msg = self.consumer.get(msg.message_id)
                        data = json.loads(msg.data)
                        response_msg = Message(
                            msg.message_id,
                            data["msg"],
                            data["user_id"],
                            msg.status,
                            msg.in_time
                        )

                        if consumer_callback is not None:
                            consumer_callback(self.consumer, None, response_msg)

                else:
                    if consumer_callback is not None:
                        consumer_callback(self.consumer, None, None)
            except Exception as e:
                consumer_callback(self.consumer, e, None)
        elif self.config.queue_type == "rabbitmq":
            pass
        elif self.config.queue_type == "kafka":
            pass

        pass

    def init_litequeue(self):
        """
        Initializes lite queue
        :return:
        """
        try:
            litequeue = importlib.import_module("litequeue")
            q = litequeue.LiteQueue(self.config.litequeue_database_name, queue_name=self.topic)
            self.producer = q
            self.consumer = q
        except Exception as e:
            Debug.error("Failed to import litequeue module", e)
            sys.exit(1)
        pass

    def init_rabbitmq(self):
        pass

    def init_kafka(self):
        pass


class Producer(object):
    """
    Producer class to produce queues
    """
    def __init__(self, queue, delivery_callback=None):
        """
        Creates a producer to produce queues
        :param queue:
        :param delivery_callback:
        """
        self.queue = queue
        self.delivery_callback = delivery_callback

    def produce(self, value, user_id=None):
        """
        Produces a message to queue
        :param value:
        :param user_id:
        :return:
        """
        self.queue.produce(value, user_id, self.delivery_callback)

class Consumer(object):
    """
    Consumer class to consume queues
    """
    def __init__(self, queues, consumer_callback=None, acknowledge=True):
        """
        Creates a consumer to consume queues
        :param queue:
        :param topics:
        :param consumer_callback:
        """
        self.queues = queues
        self.consumer_callback = consumer_callback
        self.acknowledge = acknowledge

    def run(self, sleep=1, iterations=None):
        """
        Runs the consumer
        :return:
        """
        # Run until we crash

        if not isinstance(self.queues, list):
            self.queues = [self.queues]

        try:
            counter = 0
            while True:
                for queue in self.queues:
                    try:
                        queue.consume(self.acknowledge, self.consumer_callback)
                    except Exception as e:
                        if self.consumer_callback is not None:
                            self.consumer_callback (queue, e, None)
                    counter += 1
                if iterations is not None and counter >= iterations:
                    break
                time.sleep(sleep)
        except KeyboardInterrupt:
            pass
        finally:

            pass


