"""Gallery: Queue — produce and consume background jobs."""
from tina4_python.core.router import get, post, noauth
from tina4_python.database.connection import Database
from tina4_python.queue import Queue, Producer


def _get_queue():
    """Get a queue instance backed by a local SQLite DB."""
    db = Database("sqlite:///data/gallery_queue.db")
    return Queue(db, topic="gallery-tasks")


@noauth()
@post("/api/gallery/queue/produce")
async def gallery_queue_produce(request, response):
    body = request.body or {}
    task = body.get("task", "default-task")
    data = body.get("data", {})

    queue = _get_queue()
    producer = Producer(queue)
    producer.push({"task": task, "data": data})

    return response({"queued": True, "task": task}, 201)


@get("/api/gallery/queue/status")
async def gallery_queue_status(request, response):
    queue = _get_queue()
    return response({
        "topic": "gallery-tasks",
        "size": queue.size(),
    })
