"""Gallery: Queue — produce and consume background jobs."""
from tina4_python.Router import get, post, noauth
from tina4_python.Queue import Queue, Producer


@noauth()
@post("/api/gallery/queue/produce")
async def gallery_queue_produce(request, response):
    body = request.body or {}
    task = body.get("task", "default-task")
    data = body.get("data", {})

    queue = Queue(topic="gallery-tasks")
    producer = Producer(queue)
    producer.produce({"task": task, "data": data})

    return response({"queued": True, "task": task}, 201)


@get("/api/gallery/queue/status")
async def gallery_queue_status(request, response):
    queue = Queue(topic="gallery-tasks")
    return response({
        "topic": "gallery-tasks",
        "size": queue.size(),
    })
