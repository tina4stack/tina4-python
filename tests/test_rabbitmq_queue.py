# test_rabbitmq_queue.py
import time
import pytest
import pika
from tina4_python.Queue import Queue, Config, Message, Producer, Consumer

RABBITMQ_HOST = "localhost"
RABBITMQ_PORT = 5672

def clear_rabbitmq_queue(queue_name):
    """Delete and recreate the queue to ensure it's empty"""
    try:
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=RABBITMQ_HOST, port=RABBITMQ_PORT)
        )
        channel = connection.channel()
        channel.queue_delete(queue=queue_name)
        connection.close()
    except:
        pass  # Ignore if queue doesn't exist

@pytest.fixture(scope="function")
def rabbitmq_config():
    config = Config()
    config.queue_type = "rabbitmq"
    config.rabbitmq_config = {
        "host": RABBITMQ_HOST,
        "port": RABBITMQ_PORT
    }
    config.prefix = ""
    yield config

@pytest.fixture(scope="function")
def rabbitmq_queue(rabbitmq_config):
    topic = f"test-topic-{int(time.time() * 1000000)}"  # Unique topic per test
    queue_name = rabbitmq_config.prefix + "_" + topic if rabbitmq_config.prefix else topic

    # Clear queue before test
    clear_rabbitmq_queue(queue_name)

    q = Queue(config=rabbitmq_config, topic=topic)
    yield q

    # Cleanup after test
    clear_rabbitmq_queue(queue_name)

def test_init_rabbitmq_queue(rabbitmq_queue):
    assert rabbitmq_queue.producer is not None
    assert rabbitmq_queue.consumer is not None
    assert rabbitmq_queue.get_prefix() == ""

def test_produce_rabbitmq_queue(rabbitmq_queue):
    response = rabbitmq_queue.produce("hello rabbit", user_id="user123")
    assert isinstance(response, Message)
    assert response.data == "hello rabbit"
    assert response.user_id == "user123"
    assert response.status == 0
    assert len(response.message_id) == 36

def test_produce_with_callback(rabbitmq_queue):
    delivered = [None]

    def delivery_cb(producer, err, msg):
        delivered[0] = (err, msg)

    response = rabbitmq_queue.produce("callback rabbit", user_id="user456", delivery_callback=delivery_cb)
    assert delivered[0][0] is None
    assert isinstance(delivered[0][1], Message)
    assert delivered[0][1].data == "callback rabbit"

def test_consume_rabbitmq_queue(rabbitmq_queue):
    rabbitmq_queue.produce("consume rabbit", user_id="user789")

    messages = list(rabbitmq_queue.consume(acknowledge=True))
    assert len(messages) == 1
    msg = messages[0]
    assert isinstance(msg, Message)
    assert msg.data == "consume rabbit"
    assert msg.status == 2  # acknowledged

def test_consume_no_ack(rabbitmq_queue):
    rabbitmq_queue.produce("no ack rabbit", user_id="user000")

    messages = list(rabbitmq_queue.consume(acknowledge=False))
    assert len(messages) == 1
    msg = messages[0]
    assert msg.status == 1  # not acknowledged

def test_producer_wrapper(rabbitmq_config):
    topic = f"producer-rabbit-test-{int(time.time() * 1000000)}"
    queue_name = rabbitmq_config.prefix + "_" + topic if rabbitmq_config.prefix else topic
    clear_rabbitmq_queue(queue_name)

    q = Queue(config=rabbitmq_config, topic=topic)
    producer = Producer(q)
    response = producer.produce("wrapped rabbit produce", user_id="wrapped_user")
    assert isinstance(response, Message)
    assert response.data == "wrapped rabbit produce"

def test_consumer_wrapper(rabbitmq_config):
    topic = f"consumer-rabbit-test-{int(time.time() * 1000000)}"
    queue_name = rabbitmq_config.prefix + "_" + topic if rabbitmq_config.prefix else topic
    clear_rabbitmq_queue(queue_name)

    q = Queue(config=rabbitmq_config, topic=topic)
    q.produce("to consume rabbit", user_id="consume_user")

    consumer = Consumer(q, acknowledge=True)

    collected = []
    for msg in consumer.messages():
        collected.append(msg)
        break  # get one

    assert len(collected) == 1
    assert collected[0].data == "to consume rabbit"

def test_error_handling(rabbitmq_config):
    topic = f"error-rabbit-test-{int(time.time() * 1000000)}"
    queue_name = rabbitmq_config.prefix + "_" + topic if rabbitmq_config.prefix else topic
    clear_rabbitmq_queue(queue_name)

    q = Queue(config=rabbitmq_config, topic=topic)

    with pytest.raises(Exception):
        q.produce(None)

    messages = list(q.consume())
    assert len(messages) == 0