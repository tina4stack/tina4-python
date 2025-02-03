import json
import random
import threading
import asyncer
from tina4_python import get
from tina4_python.Websocket import Websocket
from tina4_python.Queue import Config, Queue, Consumer, Producer

config = Config()
config.litequeue_database_name = "test_queue.db"


@get("/queue/add")
async def get_add_to_queue(request, response):
    queue = Queue(config, topic="some-queue")
    producer = Producer(queue)

    # produce some data

    producer.produce({"event": "create_log", "log_info": "This is an example of a producer creating a log event"})
    return response("Ok")


@get("/websocket")
async def get_websocket(request, response):
    ws = await Websocket(request).connection()
    try:

        def queue_message(queue, err, message):
            # We have set acknowledge to false on our consumer so we have to manually acknowledge the message
            if message is not None and message.status == 1:
                queue.done(message.message_id)
                asyncer.runnify(ws.send)(json.dumps(message.data))

            print("RESULT", err, message)

        def start_queue():
            queue = Queue(config, topic="some-queue")
            # Run a consumer with one-second sleep cycles with manual acknowledgement
            consumer = Consumer(queue, queue_message, acknowledge=False)

            consumer.run()

        thread = threading.Thread(target=start_queue)
        thread.start()

        while True:

            data = await ws.receive() + " Reply"
            if random.randint(1, 4) == 2:
                await ws.send("Hello")
            if data != "":
                await ws.send(data)

    except Exception as e:
        pass

    return response("")
