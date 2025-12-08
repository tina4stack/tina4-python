import os
import time
import pytest
from tina4_python.Queue import Queue, Config, Message, Producer, Consumer

@pytest.fixture
def litequeue_config():
    config = Config()
    config.queue_type = "litequeue"
    config.litequeue_database_name = "test_queue.db"
    config.prefix = "test"
    return config

@pytest.fixture
def lite_queue(litequeue_config):
    q = Queue(config=litequeue_config, topic="test-topic")
    yield q
    if os.path.exists(litequeue_config.litequeue_database_name):
        os.remove(litequeue_config.litequeue_database_name)

def test_init_litequeue(lite_queue):
    assert lite_queue.producer is not None
    assert lite_queue.consumer is not None
    assert lite_queue.get_prefix() == "test_"

def test_produce_litequeue(lite_queue):
    response = lite_queue.produce("hello world", user_id="user123")
    assert isinstance(response, Message)
    assert response.data == "hello world"
    assert response.user_id == "user123"
    assert response.status == 0  # Initial status
    assert len(response.message_id) == 36  # UUID length

def test_produce_with_callback(lite_queue):
    delivered = None
    def delivery_cb(producer, err, msg):
        nonlocal delivered
        delivered = (err, msg)
    response = lite_queue.produce("callback test", user_id="user456", delivery_callback=delivery_cb)
    assert delivered[0] is None  # No error
    assert isinstance(delivered[1], Message)
    assert delivered[1].data == "callback test"

def test_consume_litequeue(lite_queue):
    # Produce a message first
    lite_queue.produce("consume me", user_id="user789")

    consumed = None
    def consumer_cb(consumer, err, msg):
        nonlocal consumed
        consumed = (err, msg)

    lite_queue.consume(acknowledge=True, consumer_callback=consumer_cb)
    assert consumed[0] is None
    assert isinstance(consumed[1], Message)
    assert consumed[1].data == "consume me"
    assert consumed[1].status == 2  # Acknowledged status

def test_consume_no_ack(lite_queue):
    lite_queue.produce("no ack test", user_id="user000")

    consumed = None
    def consumer_cb(consumer, err, msg):
        nonlocal consumed
        consumed = msg

    lite_queue.consume(acknowledge=False, consumer_callback=consumer_cb)
    assert consumed.status == 1  # Not acknowledged

def test_producer_wrapper(litequeue_config):
    q = Queue(config=litequeue_config, topic="producer-test")
    producer = Producer(q)
    response = producer.produce("wrapped produce", user_id="wrapped_user")
    assert isinstance(response, Message)
    assert response.data == "wrapped produce"

def test_consumer_wrapper(litequeue_config):
    q = Queue(config=litequeue_config, topic="consumer-test")
    q.produce("to consume", user_id="consume_user")

    collected = []
    def consumer_cb(consumer, err, msg):
        collected.append(msg)

    consumer = Consumer(q, consumer_callback=consumer_cb, acknowledge=True)

    # Run for a few iterations to simulate consumption
    consumer.run(sleep=1, iterations=1)

    assert len(collected) == 1
    assert collected[0].data == "to consume"

def test_error_handling(lite_queue):
    # Simulate invalid produce (e.g., bad value)
    with pytest.raises(Exception):
        lite_queue.produce(None)  # Assuming JSON dumps fails on None

    # Consume on empty queue (should not raise, just do nothing)
    lite_queue.consume()

