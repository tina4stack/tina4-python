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

_DKW: Dict[str, Any] = {}
if sys.version_info >= (3, 10):
    _DKW["slots"] = True

# Extracted from https://github.com/stevesimmons/uuid7 under MIT license

# Expose function used by uuid7() to get current time in nanoseconds
# since the Unix epoch.
time_ns = time.time_ns


def uuid7(
        _last=[0, 0, 0, 0],  # noqa
        _last_as_of=[0, 0, 0, 0],  # noqa
) -> str:
    """
    UUID v7, following the proposed extension to RFC4122 described in
    https://www.ietf.org/id/draft-peabody-dispatch-new-uuid-format-02.html.
    All representations sort chronologically, with a potential time resolution
    of 50ns (if the system clock supports this).
    Parameters
    ----------
    time_func - Set the time function, which must return integer
                nanoseconds since the Unix epoch, midnight on 1-Jan-1970.
                Defaults to time.time_ns(). This is exposed because
                time.time_ns() may have a low resolution on Windows.
    _last and _last_as_of - Used internally to trigger incrementing a
                sequence counter when consecutive calls have the same time
                values. The values [t1, t2, t3, seq] are described below.
    Returns
    -------
    A UUID object, or if as_type is specified, a string, int or
    bytes of length 16.
    Implementation notes
    --------------------
    The 128 bits in the UUID are allocated as follows:
    - 36 bits of whole seconds
    - 24 bits of fractional seconds, giving approx 50ns resolution
    - 14 bits of sequential counter, if called repeatedly in same time tick
    - 48 bits of randomness
    plus, at locations defined by RFC4122, 4 bits for the
    uuid version (0b111) and 2 bits for the uuid variant (0b10).
             0                   1                   2                   3
             0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
            +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    t1      |                 unixts (secs since epoch)                     |
            +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    t2/t3   |unixts |  frac secs (12 bits)  |  ver  |  frac secs (12 bits)  |
            +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    t4/rand |var|       seq (14 bits)       |          rand (16 bits)       |
            +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    rand    |                          rand (32 bits)                       |
            +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    Indicative timings:
    - uuid.uuid4()            2.4us
    - uuid7(as_type='str')    2.5us
    Examples
    --------
    >>> uuid7()
    '061cb26a-54b8-7a52-8000-2124e7041024'
    >>> uuid7(0)
    '00000000-0000-0000-0000-00000000000'
    """
    ns = time_ns()
    last = _last

    if ns == 0:
        # Special case for all-zero uuid. Strictly speaking not a UUIDv7.
        t1 = t2 = t3 = t4 = 0
        rand = b"\0" * 6
    else:
        # Treat the first 8 bytes of the uuid as a long (t1) and two ints
        # (t2 and t3) holding 36 bits of whole seconds and 24 bits of
        # fractional seconds.
        # This gives a nominal 60ns resolution, comparable to the
        # timestamp precision in Linux (~200ns) and Windows (100ns ticks).
        sixteen_secs = 16_000_000_000
        t1, rest1 = divmod(ns, sixteen_secs)
        t2, rest2 = divmod(rest1 << 16, sixteen_secs)
        t3, _ = divmod(rest2 << 12, sixteen_secs)
        t3 |= 7 << 12  # Put uuid version in top 4 bits, which are 0 in t3

        # The next two bytes are an int (t4) with two bits for
        # the variant 2 and a 14 bit sequence counter which increments
        # if the time is unchanged.
        if t1 == last[0] and t2 == last[1] and t3 == last[2]:
            # Stop the seq counter wrapping past 0x3FFF.
            # This won't happen in practice, but if it does,
            # uuids after the 16383rd with that same timestamp
            # will not longer be correctly ordered but
            # are still unique due to the 6 random bytes.
            if last[3] < 0x3FFF:
                last[3] += 1
        else:
            last[:] = (t1, t2, t3, 0)
        t4 = (2 << 14) | last[3]  # Put variant 0b10 in top two bits

        # Six random bytes for the lower part of the uuid
        rand = os.urandom(6)

    return f"{t1:>08x}-{t2:>04x}-{t3:>04x}-{t4:>04x}-{rand.hex()}"

class Config(object):
    queue_type = "litequeue" # can be rabbitmq or kafka as well
    litequeue_database_name = "queue.db"
    kafka_config = None
    rabbitmq_config = None
    rabbitmq_queue = "default-queue"
    prefix=""

    def __init__(self):
        pass

@dataclass(frozen=True, **_DKW)
class Message:
    message_id: str
    data: str
    user_id: str
    status: int
    time_stamp: int
    delivery_tag: str

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
            config.prefix = ""

        Debug.info("Initializing", config.queue_type, topic)
        self.producer = None
        self.consumer = None
        self.topic = topic
        self.config = config
        self.library = None

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
        if self.config.prefix != "":
            prefix = self.config.prefix+"_"
        else:
            prefix = ""

        if self.config.queue_type == "litequeue":
            try:
                msg = self.producer.put(json.dumps({"msg": value, "user_id": user_id}))
                response_msg = Message(
                    msg.message_id,
                    value,
                    user_id,
                    int(msg.status),
                    msg.in_time,
                    0
                )
                if delivery_callback is not None:
                    delivery_callback(self.producer, None, response_msg)

                return response_msg
            except Exception as e:
                if delivery_callback is not None:
                    delivery_callback(self.producer, e, None)

            return e
        elif self.config.queue_type == "rabbitmq":
            try:
                body = {
                    "message_id": uuid7(), "msg": value, "user_id": user_id, "in_time": time_ns()
                }

                self.producer.basic_publish(exchange=self.topic, routing_key='', body=json.dumps(body))
                response_msg = Message(
                    body["message_id"],
                    value,
                    user_id,
                    0,
                    body["in_time"],
                    0
                )
                if delivery_callback is not None:
                    delivery_callback(self.producer, None, response_msg)

                return response_msg
            except Exception as e:
                if delivery_callback is not None:
                    delivery_callback(self.producer, e, None)
                return e
        elif self.config.queue_type == "kafka":
            try:
                body = {
                    "message_id": uuid7(), "msg": value, "user_id": user_id, "in_time": time_ns()
                }

                response_msg = Message(
                    body["message_id"],
                    value,
                    user_id,
                    0,
                    body["in_time"],
                    0
                )

                def kafka_delivery_callback(err, kafka_msg):
                    if err:
                        delivery_callback(self.consumer, err, None)
                    else:
                        response_msg_internal = Message(
                            body["message_id"],
                            value,
                            user_id,
                            0,
                            body["in_time"],
                            kafka_msg.offset()
                        )
                        delivery_callback(self.consumer, err, response_msg_internal)


                self.producer.produce(prefix+self.topic, json.dumps(body), user_id, callback=kafka_delivery_callback)
                self.producer.poll(1000)
                self.producer.flush()

                return response_msg

            except Exception as e:
                delivery_callback(self.consumer, e, None)
                return e
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
                        msg.in_time,
                        0
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
                            msg.in_time,
                            0
                        )

                        if consumer_callback is not None:
                            consumer_callback(self.consumer, None, response_msg)

                else:
                    if consumer_callback is not None:
                        consumer_callback(self.consumer, None, None)
            except Exception as e:
                consumer_callback(self.consumer, e, None)
        elif self.config.queue_type == "rabbitmq":
            try:
                method_frame, header_frame, body = self.consumer.basic_get(queue=self.topic, auto_ack=acknowledge)

                if method_frame is not None:
                    msg_status = 1
                    if acknowledge:
                        msg_status = 2
                    data = json.loads(body)
                    response_msg = Message(
                        data["message_id"],
                        data["msg"],
                        data["user_id"],
                        msg_status,
                        data["in_time"],
                        method_frame.delivery_tag
                    )
                    if consumer_callback is not None:
                        consumer_callback(self.consumer, None, response_msg)
            except Exception as e:
                if consumer_callback is not None:
                    consumer_callback(self.consumer, e, None)
        elif self.config.queue_type == "kafka":
            try:
                msg = self.consumer.poll(1.0)
                if msg is None:
                    pass
                elif msg.error():
                    if consumer_callback is not None:
                        consumer_callback(self.consumer, msg.error(), None)
                else:
                    msg_status = 1
                    if acknowledge:
                        msg_status = 2
                    data = json.loads(msg.value().decode('utf-8'))
                    response_msg = Message(
                        data["message_id"],
                        data["msg"],
                        data["user_id"],
                        msg_status,
                        data["in_time"],
                        msg.offset()
                    )
                    if consumer_callback is not None:
                        consumer_callback(self.consumer, None, response_msg)
            except Exception as e:
                if consumer_callback is not None:
                    consumer_callback(self.consumer, e, None)

    def init_litequeue(self):
        """
        Initializes lite queue
        :return:
        """
        try:
            if self.config.prefix != "":
                prefix = self.config.prefix+"_"
            else:
                prefix = ""

            litequeue = importlib.import_module("litequeue")
            q = litequeue.LiteQueue(self.config.litequeue_database_name, queue_name=prefix+self.topic)
            self.producer = q
            self.consumer = q
        except Exception as e:
            Debug.error("Failed to import litequeue module", e)
            sys.exit(1)
        pass

    def init_rabbitmq(self):
        try:
            if self.config.prefix != "":
                prefix = "/"+self.config.prefix
            else:
                prefix = "/"

            if self.config.rabbitmq_config is None:
                self.config.rabbitmq_config = {"host": "localhost", "port": 5672}

            pika = importlib.import_module("pika")

            try:
                if "username" in self.config.rabbitmq_config:
                    credentials = pika.PlainCredentials(self.config.rabbitmq_config["username"],
                                                        self.config.rabbitmq_config["password"])
                    connection = pika.BlockingConnection(
                        pika.ConnectionParameters(host=self.config.rabbitmq_config["host"],
                                                  port=self.config.rabbitmq_config["port"],
                                                  virtual_host=prefix,
                                                  credentials=credentials
                                                  )
                    )
                else:
                    connection = pika.BlockingConnection(
                        pika.ConnectionParameters(host=self.config.rabbitmq_config["host"],
                                                  port=self.config.rabbitmq_config["port"],
                                                  virtual_host=prefix
                                                  )
                    )


            except Exception as e:
                print(e)
            channel = connection.channel()
            channel.exchange_declare(exchange=self.topic, exchange_type="topic")
            result = channel.queue_declare(self.topic, exclusive=False)
            self.config.rabbitmq_queue = result.method.queue
            channel.queue_bind(
                exchange=self.topic, queue=self.config.rabbitmq_queue, routing_key='')
            self.producer = channel
            self.consumer = channel

        except Exception as e:
            Debug.error("Failed to import rabbitmq module, try pip install pika or poetry add pika", e)
        pass

    def init_kafka(self):
        try:
            if self.config.prefix != "":
                prefix = self.config.prefix+"_"
            else:
                prefix = ""

            if self.config.kafka_config is None:
                self.config.kafka_config  = {
                    # User-specific properties that you must set
                    'bootstrap.servers': 'localhost:9092',
                    'group.id': prefix+'default-queue',
                    'auto.offset.reset': 'earliest'
                }
            kafka = importlib.import_module("confluent_kafka")

            self.consumer = kafka.Consumer(self.config.kafka_config)
            self.consumer.subscribe([prefix+self.topic])

            if 'auto.offset.reset' in self.config.kafka_config:
                del self.config.kafka_config['auto.offset.reset']
            if 'group.id' in self.config.kafka_config:
                del self.config.kafka_config['group.id']

            self.producer = kafka.Producer(self.config.kafka_config)

        except Exception as e:
            Debug.error("Failed to import kafka module, try pip install confluent-kafka or poetry add confluent-kafka", e)
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

    def produce(self, value, user_id=None, delivery_callback=None):
        """
        Produces a message to queue
        :param delivery_callback:
        :param value:
        :param user_id:
        :return:
        """
        if delivery_callback is None:
            delivery_callback = self.delivery_callback

        return self.queue.produce(value, user_id, delivery_callback)

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
            Debug("Consuming", self.queues)
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
            Debug.info("Done running consumer")
            pass


