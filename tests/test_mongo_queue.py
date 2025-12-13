# test_mongo_queue.py
import time
import pytest
from pymongo import MongoClient
from tina4_python.Queue import Queue, Config, Message, Producer, Consumer

MONGO_DB_NAME = "test_queue_db"

def clear_mongo_channel(channel_name, prefix="test"):
    client = MongoClient("mongodb://localhost:27017")
    db = client[MONGO_DB_NAME]
    collection_name = f"{prefix}_{channel_name}"
    if collection_name in db.list_collection_names():
        db[collection_name].delete_many({})

@pytest.fixture(scope="function")
def mongo_config():
    config = Config()
    config.queue_type = "mongo-queue-service"
    config.mongo_queue_config = {
        "host": "localhost",
        "port": 27017,
        "timeout": 300,
        "max_attempts": 5
    }
    config.prefix = "test"
    yield config

# Each test gets its own unique topic
def unique_topic(base):
    return f"{base}_{int(time.time() * 1000000)}"

def test_init_mongo_queue(mongo_config):
    topic = unique_topic("init")
    clear_mongo_channel(topic, prefix=mongo_config.prefix)
    q = Queue(config=mongo_config, topic=topic)
    assert q.producer is not None
    assert q.consumer is not None
    assert q.get_prefix() == "test_"

def test_produce_mongo_queue(mongo_config):
    topic = unique_topic("produce")
    clear_mongo_channel(topic, prefix=mongo_config.prefix)
    q = Queue(config=mongo_config, topic=topic)
    response = q.produce("hello mongo", user_id="user123")
    assert isinstance(response, Message)
    assert response.data == "hello mongo"
    assert response.user_id == "user123"
    assert response.status == 0
    assert len(response.message_id) == 36

def test_produce_with_callback(mongo_config):
    topic = unique_topic("callback")
    clear_mongo_channel(topic, prefix=mongo_config.prefix)
    q = Queue(config=mongo_config, topic=topic)
    delivered = [None]

    def delivery_cb(producer, err, msg):
        delivered[0] = (err, msg)

    response = q.produce("callback mongo", user_id="user456", delivery_callback=delivery_cb)
    assert delivered[0][0] is None
    assert isinstance(delivered[0][1], Message)
    assert delivered[0][1].data == "callback mongo"

def test_consume_mongo_queue(mongo_config):
    topic = unique_topic("consume")
    clear_mongo_channel(topic, prefix=mongo_config.prefix)
    q = Queue(config=mongo_config, topic=topic)
    q.produce("consume mongo", user_id="user789")

    messages = list(q.consume(acknowledge=True))
    assert len(messages) == 1
    msg = messages[0]
    assert isinstance(msg, Message)
    assert msg.data == "consume mongo"
    assert msg.status == 2

def test_consume_no_ack(mongo_config):
    topic = unique_topic("noack")
    clear_mongo_channel(topic, prefix=mongo_config.prefix)
    q = Queue(config=mongo_config, topic=topic)
    q.produce("no ack mongo", user_id="user000")

    messages = list(q.consume(acknowledge=False))
    assert len(messages) == 1
    msg = messages[0]
    assert msg.status == 1

def test_producer_wrapper(mongo_config):
    topic = unique_topic("producer")
    clear_mongo_channel(topic, prefix=mongo_config.prefix)
    q = Queue(config=mongo_config, topic=topic)
    producer = Producer(q)
    response = producer.produce("wrapped mongo produce", user_id="wrapped_user")
    assert isinstance(response, Message)
    assert response.data == "wrapped mongo produce"

def test_consumer_wrapper(mongo_config):
    topic = unique_topic("consumer")
    clear_mongo_channel(topic, prefix=mongo_config.prefix)
    q = Queue(config=mongo_config, topic=topic)
    q.produce("to consume mongo", user_id="consume_user")

    consumer = Consumer(q, acknowledge=True)

    collected = []
    for msg in consumer.messages():
        collected.append(msg)
        break

    assert len(collected) == 1
    assert collected[0].data == "to consume mongo"

def test_error_handling(mongo_config):
    topic = unique_topic("error")
    clear_mongo_channel(topic, prefix=mongo_config.prefix)
    q = Queue(config=mongo_config, topic=topic)

    with pytest.raises(Exception):
        q.produce(None)

    messages = list(q.consume())
    assert len(messages) == 0