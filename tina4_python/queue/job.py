class Job:
    """A single queue job."""

    def __init__(self, queue, job_id, topic: str, data: dict,
                 priority: int = 0, attempts: int = 0):
        self.queue = queue
        self.id = job_id
        self.topic = topic
        self.payload = data
        self.priority = priority
        self.attempts = attempts

    @property
    def data(self):
        """Alias for payload — deprecated, use .payload instead."""
        return self.payload

    def complete(self):
        """Mark job as completed."""
        self.queue._backend.complete(self)

    def fail(self, error: str = ""):
        """Mark job as failed. Will be retried if attempts < max_retries."""
        self.queue._backend.fail(self, error)

    def reject(self, reason: str = ""):
        """Reject a job with a reason. Alias for fail()."""
        self.fail(reason)

    def retry(self, delay_seconds: int = 0):
        """Re-queue this job with optional delay."""
        self.queue._backend.retry(self, delay_seconds)

    def to_array(self) -> list:
        """Return job fields as a flat list of values."""
        return [self.id, self.topic, self.payload, self.priority, self.attempts]

    def to_hash(self) -> dict:
        """Return job as a dict."""
        return {
            "id": self.id,
            "topic": self.topic,
            "payload": self.payload,
            "priority": self.priority,
            "attempts": self.attempts,
        }

    def to_json(self) -> str:
        """Return job as a JSON string."""
        import json
        return json.dumps(self.to_hash())
