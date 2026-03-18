import json
import time
from tina4_python.Debug import Debug
from src.orm.Job import Job


def process_job(message):
    """Process a job from the queue. Called by the consumer."""
    data = message.data if hasattr(message, 'data') else message
    if isinstance(data, str):
        data = json.loads(data)

    job_id = data.get("job_id")
    if not job_id:
        return

    job = Job()
    if not job.load("id = ?", [job_id]):
        Debug.error(f"Job {job_id} not found")
        return

    job.status = "processing"
    job.save()

    try:
        if job.job_type == "fetch_weather":
            # Simulate an API call
            payload = json.loads(job.payload) if job.payload else {}
            city = payload.get("city", "Unknown")
            time.sleep(1)  # Simulate network delay
            job.result = json.dumps({"city": city, "temp": "22C", "condition": "Sunny"})

        elif job.job_type == "send_notification":
            payload = json.loads(job.payload) if job.payload else {}
            time.sleep(2)  # Simulate sending
            job.result = f"Notification sent to {payload.get('to', 'unknown')}"

        elif job.job_type == "generate_report":
            time.sleep(3)  # Simulate report generation
            job.result = "Report generated: 150 rows, 12 charts"

        else:
            job.result = f"Unknown job type: {job.job_type}"

        job.status = "completed"

    except Exception as e:
        job.status = "failed"
        job.result = str(e)

    job.save()
    Debug.info(f"Job {job_id} ({job.job_type}) -> {job.status}")
