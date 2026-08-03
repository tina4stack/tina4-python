"""queue_contract.json :: priority-and-availability-are-honoured

MEASURED 2026-08-03: `push(priority=...)` was honoured ONLY on the file backend
in Python, and on NO backend but file in PHP, Ruby and Node. An urgent job
queued behind a backlog waited for all of it, in production, while development
on the file backend prioritised correctly.

The fix splits by what each backend can actually do:
  file      already correct - highest priority first, ties oldest-first.
  mongodb   implemented - priority is stored top-level and the dequeue sorts
            on it. Python already did this; PHP, Ruby and Node did not.
  rabbitmq  RAISES - a RabbitMQ queue is FIFO. Native priority needs the queue
            DECLARED with x-max-priority, and an existing queue cannot be
            redeclared with one (PRECONDITION_FAILED), so switching it on would
            break every queue already in service.
  kafka     RAISES - no priority concept at all; a partition is read in offset
            order.

Per queue invariant 6, a backend that genuinely cannot perform an operation
raises naming the backend AND the operation. It may never silently no-op.

The AVAILABILITY half of this invariant (a not-yet-available job is not
delivered) is proved by the delay-is-honoured-on-every-backend cases and is not
duplicated here.

NO MOCKS. Every assertion drives a live MongoDB over TCP. If it is unreachable
the module skips, unless TINA4_REQUIRE_SERVICES is set - then a missing service
is a FAILURE, because a suite that silently skips its only real verification is
not verification.

The three case names here are shared VERBATIM with the PHP, Ruby and Node
suites, because scripts/audit-contract-fixtures.py resolves ONE fixture case
against EVERY framework's file.
"""
import os
import socket
import time
import uuid

import pytest

HOST = os.environ.get("TINA4_TEST_MONGO_HOST", "127.0.0.1")
PORT = int(os.environ.get("TINA4_TEST_MONGO_PORT", "27017"))


def _reachable() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=2):
            return True
    except OSError:
        return False


if not _reachable():
    if os.environ.get("TINA4_REQUIRE_SERVICES"):
        raise RuntimeError(
            f"TINA4_REQUIRE_SERVICES is set but MongoDB is not reachable at {HOST}:{PORT}"
        )
    pytest.skip(f"MongoDB not reachable at {HOST}:{PORT}", allow_module_level=True)


@pytest.fixture
def mongo_queue(monkeypatch):
    """A real Mongo-backed Queue on a topic no other test shares."""
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", "mongodb")
    monkeypatch.setenv("TINA4_QUEUE_URL", f"mongodb://{HOST}:{PORT}")

    from tina4_python.queue import Queue

    return lambda: Queue(topic=f"prio_{uuid.uuid4().hex[:12]}")


def _payload(job):
    return (job.data or {}).get("m")


def test_a_higher_priority_job_is_delivered_before_an_older_lower_priority_one(mongo_queue):
    """The measured defect. LOW is pushed FIRST, so FIFO order and priority
    order disagree - the only arrangement that can tell them apart."""
    queue = mongo_queue()
    queue.push({"m": "low"}, 0, 0)
    time.sleep(0.5)                      # distinct created_at, so FIFO is unambiguous
    queue.push({"m": "high"}, 9, 0)
    time.sleep(1)

    first = queue.pop()
    assert first is not None, "the queue returned nothing - priority is unmeasurable"
    assert _payload(first) == "high", "the higher-priority job must be delivered first"


def test_equal_priority_jobs_are_delivered_oldest_first(mongo_queue):
    """NEGATIVE: pins the TIE-BREAK. Without it, 'always deliver the newest job'
    passes the case above while breaking FIFO for everything else. It also
    proves both jobs come back at all, so this doubles as the control."""
    queue = mongo_queue()
    queue.push({"m": "first"}, 5, 0)
    time.sleep(0.5)
    queue.push({"m": "second"}, 5, 0)
    time.sleep(1)

    first = queue.pop()
    second = queue.pop()
    assert first is not None and second is not None, "both jobs must come back"
    assert _payload(first) == "first", "equal priority must fall back to oldest-first"
    assert _payload(second) == "second"


@pytest.mark.parametrize("backend", ["rabbitmq", "kafka"])
def test_a_backend_that_cannot_prioritise_refuses_instead_of_dropping_the_priority(
    monkeypatch, backend
):
    """Neither broker can order by priority. Silently discarding it is the
    failure mode invariant 6 exists to forbid, so they raise naming both the
    backend and the operation - and never touch the network to do it."""
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", backend)

    from tina4_python.queue import Queue

    queue = Queue(topic=f"prio_{uuid.uuid4().hex[:12]}")

    with pytest.raises(NotImplementedError) as excinfo:
        queue.push({"m": "high"}, 9, 0)

    message = str(excinfo.value)
    assert backend in message, "the error must name the backend"
    assert "priority" in message.lower(), "the error must name the operation"
