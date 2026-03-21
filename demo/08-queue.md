# Queue

Tina4 includes a database-backed job queue with zero external dependencies. No Redis or RabbitMQ needed -- it uses your connected database for storage. The queue supports priority levels, delayed jobs, retry with backoff, and dead letter tracking.

## Setup

The queue auto-creates a `tina4_queue` table on first use.

```python
from tina4_python.database.connection import Database
from tina4_python.queue import Queue, Producer, Consumer

db = Database("sqlite:///data/app.db")
queue = Queue(db, topic="emails")
```

## Pushing Jobs

```python
producer = Producer(queue)

# Simple job
producer.push({"to": "alice@example.com", "subject": "Welcome"})

# With priority (higher number = processed first)
producer.push({"to": "vip@example.com", "subject": "VIP Welcome"}, priority=10)

# Delayed job (available after 300 seconds)
producer.push({"action": "send_reminder"}, delay_seconds=300)
```

Or push directly on the queue:

```python
job_id = queue.push(
    {"to": "bob@example.com", "subject": "Hello"},
    priority=5,
    delay_seconds=60
)
print(f"Job queued with ID: {job_id}")
```

## Consuming Jobs

### Poll Once

```python
consumer = Consumer(queue)
jobs = consumer.poll()
for job in jobs:
    try:
        send_email(job.data["to"], job.data["subject"])
        job.complete()
    except Exception as e:
        job.fail(str(e))
```

### Run Forever

```python
def handle_email(job):
    send_email(job.data["to"], job.data["subject"])
    job.complete()

consumer = Consumer(queue, callback=handle_email, poll_interval=2.0)
consumer.run(max_jobs=None)  # Runs until stopped
```

### Pop One Job

```python
job = queue.pop()
if job:
    print(f"Processing job {job.id}: {job.data}")
    job.complete()
```

## Job Lifecycle

```python
job = queue.pop()

# Mark as completed
job.complete()

# Mark as failed (will be retried if under max_retries)
job.fail("Connection timeout")

# Manually retry with optional delay
job.retry(delay_seconds=60)
```

## Queue Management

```python
# Check queue size by status
pending = queue.size("pending")
failed = queue.size("failed")
completed = queue.size("completed")

# Re-queue failed jobs that haven't exceeded max retries
retried = queue.retry_failed()
print(f"Re-queued {retried} failed jobs")

# Get dead letters (exceeded max retries)
dead = queue.dead_letters()
for d in dead:
    print(f"Dead job: {d['data']} — Error: {d['error']}")

# Purge completed jobs
queue.purge("completed")
```

## Using in Route Handlers

Route handlers should respond fast. Push long-running work to a queue.

```python
from tina4_python.core.router import post
from tina4_python.queue import Queue, Producer

@post("/api/reports/generate")
async def generate_report(request, response):
    queue = Queue(db, topic="reports")
    Producer(queue).push({
        "user_id": request.body["user_id"],
        "report_type": "monthly",
    })
    return response({"status": "queued"})
```

Process the work in a separate worker script:

```python
# worker.py
from tina4_python.database.connection import Database
from tina4_python.queue import Queue, Consumer

db = Database("sqlite:///data/app.db")
queue = Queue(db, topic="reports")

def handle_report(job):
    data = job.data
    report = generate_report(data["user_id"], data["report_type"])
    save_report(report)
    job.complete()

consumer = Consumer(queue, callback=handle_report)
consumer.run()
```

## Multiple Topics

Use separate topics for different job types.

```python
email_queue = Queue(db, topic="emails")
report_queue = Queue(db, topic="reports")
notification_queue = Queue(db, topic="notifications")

# Push to specific topics
Producer(email_queue).push({"to": "alice@example.com"})
Producer(report_queue).push({"type": "monthly"})
```

## Configuration

```python
queue = Queue(
    db,
    topic="emails",
    max_retries=3,  # Jobs fail permanently after 3 attempts
)

consumer = Consumer(
    queue,
    callback=handle_job,
    poll_interval=1.0,  # Seconds between polls
)
```

## Tips

- Any operation taking more than 1 second should use a queue (emails, PDFs, file processing, slow API calls).
- Use priority for urgent jobs (higher number = processed first).
- Use `delay_seconds` for scheduled future work (reminders, follow-ups).
- Run workers as separate processes (`python worker.py`), not inside the web server.
- Monitor dead letters periodically -- they indicate systemic failures.
