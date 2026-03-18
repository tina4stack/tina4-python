import json
from tina4_python.Router import post, noauth
from tina4_python.Queue import Queue, Producer
from src.orm.Job import Job


queue = Queue(topic="jobs")
producer = Producer(queue)


@noauth()
@post("/api/jobs/fetch-weather")
async def enqueue_weather(request, response):
    city = request.body.get("city", "London")
    job = Job({"job_type": "fetch_weather", "payload": json.dumps({"city": city}), "status": "pending"})
    job.save()
    producer.produce({"job_id": job.id})
    return response({"job_id": job.id, "status": "queued"}, 201)


@noauth()
@post("/api/jobs/send-notification")
async def enqueue_notification(request, response):
    to = request.body.get("to", "user@example.com")
    job = Job({"job_type": "send_notification", "payload": json.dumps({"to": to}), "status": "pending"})
    job.save()
    producer.produce({"job_id": job.id})
    return response({"job_id": job.id, "status": "queued"}, 201)


@noauth()
@post("/api/jobs/generate-report")
async def enqueue_report(request, response):
    job = Job({"job_type": "generate_report", "payload": "{}", "status": "pending"})
    job.save()
    producer.produce({"job_id": job.id})
    return response({"job_id": job.id, "status": "queued"}, 201)
