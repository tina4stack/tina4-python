import os
import time
import pytest
from tina4_python.Queue import Queue, Config, Message, Producer, Consumer


# Helper to clean up SQLite files completely
def cleanup_db(db_name):
    for suffix in ["", "-wal", "-shm", "-journal"]:
        file_path = f"{db_name}{suffix}"
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except PermissionError:
                time.sleep(0.1)
                try:
                    os.remove(file_path)
                except:
                    pass  # best effort


@pytest.fixture(scope="function")
def litequeue_config():
    # Unique DB name per test run to avoid locks
    db_name = f"test_queue_{int(time.time() * 1000)}.db"
    config = Config()
    config.queue_type = "litequeue"
    config.litequeue_database_name = db_name
    config.prefix = "test"
    yield config
    cleanup_db(config.litequeue_database_name)


@pytest.fixture(scope="function")
def lite_queue(litequeue_config):
    q = Queue(config=litequeue_config, topic="test-topic")
    yield q
    cleanup_db(litequeue_config.litequeue_database_name)


def test_init_litequeue(lite_queue):
    assert lite_queue.producer is not None
    assert lite_queue.consumer is not None
    assert lite_queue.get_prefix() == "test_"


def test_produce_litequeue(lite_queue):
    response = lite_queue.produce("hello world", user_id="user123")
    assert isinstance(response, Message)
    assert response.data == "hello world"
    assert response.user_id == "user123"
    assert response.status == 0
    assert len(response.message_id) == 36


def test_produce_with_callback(lite_queue):
    delivered = [None]

    def delivery_cb(producer, err, msg):
        delivered[0] = (err, msg)

    response = lite_queue.produce("callback test", user_id="user456", delivery_callback=delivery_cb)
    assert delivered[0][0] is None
    assert isinstance(delivered[0][1], Message)
    assert delivered[0][1].data == "callback test"


def test_consume_litequeue(lite_queue):
    lite_queue.produce("consume me", user_id="user789")

    # Use generator directly — no callback needed
    messages = list(lite_queue.consume(acknowledge=True))
    assert len(messages) == 1
    msg = messages[0]
    assert isinstance(msg, Message)
    assert msg.data == "consume me"
    assert msg.status == 2  # Acknowledged


def test_consume_no_ack(lite_queue):
    lite_queue.produce("no ack test", user_id="user000")

    messages = list(lite_queue.consume(acknowledge=False))
    assert len(messages) == 1
    msg = messages[0]
    assert msg.status == 1  # Not acknowledged


def test_producer_wrapper(litequeue_config):
    q = Queue(config=litequeue_config, topic="producer-test")
    producer = Producer(q)
    response = producer.produce("wrapped produce", user_id="wrapped_user")
    assert isinstance(response, Message)
    assert response.data == "wrapped produce"


def test_consumer_wrapper(litequeue_config):
    q = Queue(config=litequeue_config, topic="consumer-test")
    q.produce("to consume", user_id="consume_user")

    consumer = Consumer(q, acknowledge=True)

    collected = []
    # Poll a few times to get the message
    for msg in consumer.messages():
        collected.append(msg)
        if len(collected) >= 1:
            break

    assert len(collected) >= 1
    assert any(m.data == "to consume" for m in collected)


def test_batch_mode():
    callback_calls = []

    def my_callback(msg: Message):
        callback_calls.append(msg.data)

    # Create queue with batch_size=5 and callback
    queue = Queue(topic="batch-test", batch_size=5, callback=my_callback)

    # Produce 12 messages
    for i in range(12):
        queue.produce(f"Message {i + 1}", user_id="tester")
        time.sleep(0.1)

    # Consume in batch mode
    batches = []
    total_messages = 0

    consumer = Consumer([queue], acknowledge=True)

    for item in consumer.messages():
        assert isinstance(item, list)
        assert all(isinstance(m, Message) for m in item)
        batch_size = len(item)
        batches.append(batch_size)
        total_messages += batch_size

        # Extract data for easier checking
        batch_data = [msg.data for msg in item]

        expected_data = [f"Message {total_messages - batch_size + j + 1}" for j in range(batch_size)]
        print("BATCH DATA", batch_data, expected_data)
        assert batch_data == expected_data

        if total_messages >= 12:
            break

    # Verify we got the expected batch sizes: 5 + 5 + 2
    assert batches == [5, 5, 2]
    assert total_messages == 12
    assert len(callback_calls) == 12  # Callback called once per message
    assert sorted(callback_calls) == sorted([f"Message {i + 1}" for i in range(12)])


def test_error_handling(lite_queue):
    with pytest.raises(Exception):
        lite_queue.produce(None)

    # Consume on empty queue — should yield nothing, no error
    messages = list(lite_queue.consume())
    assert len(messages) == 0
