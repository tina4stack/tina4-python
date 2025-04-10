import os
from tina4_python import Debug, start_in_thread
from tina4_python.Queue import Config, Queue, Producer, Consumer
from tina4_python.Router import post, get

config = Config()
config.queue_type = "rabbitmq"
config.rabbitmq_config = {"host": os.getenv("RABBIT_MQ_HOST", "localhost"), "port": os.getenv("RABBIT_MQ_PORT", 5672)}


queue = Queue(config, topic="generate")
producer = Producer(queue)

queue_result = Queue(config, topic="result")
producer_result = Producer(queue_result)


def queue_message(queue, err, data):
    # We have set acknowledge to false on our consumer so we have to manually acknowledge the message
    if data is not None and data.status == 1:
        queue.basic_ack(data.delivery_tag)
    else:
       return

    producer_result.produce({"processed": True, "message_id": data.message_id, "message": "OK"})

    Debug.info("RESULT", err, data)



def run_consumer():
    result_queue = Queue(config, topic="generate")
    # Run a consumer with one-second sleep cycles with manual acknowledgement
    consumer = Consumer(queue, queue_message, acknowledge=False)
    consumer.run()


start_in_thread(run_consumer)


@post("/api/generate")
async def post_generate(request, response):
    # check the request.body

    message = producer.produce(request.body)

    return response({"message_id": message.message_id})


class QueueResult:
    def __init__(self, message_id, queue):
        self.message_id = message_id
        self.result = {}
        self.queue = queue

    def get_queue_result(self, result_queue, err, data):
        if data.data["message_id"] == self.message_id:
            self.result = data.data
            result_queue.basic_ack(data.delivery_tag)

    def get_result(self):
        consumer = Consumer(self.queue, self.get_queue_result, acknowledge=False)
        consumer.run(iterations=1)
        return self.result


@get("/api/generate/{message_id}")
async def get_generate(request, response):

    return response(QueueResult(request.params["message_id"], queue_result).get_result())





