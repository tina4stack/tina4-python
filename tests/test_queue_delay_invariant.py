"""queue_contract.json :: delay-is-honoured-on-every-backend

MEASURED 2026-08-03: push(delay_seconds) was silently DROPPED on every
non-file backend, in ALL FOUR frameworks. A scheduled job fired immediately in
production and on time in development — the worst shape of divergence, because
the environment you test in is the one that behaves correctly.

The fix splits by what each broker can actually do:
  mongodb   implemented — a delayed job is stamped available_at in the future,
            and dequeue already filtered on available_at <= now.
  rabbitmq  RAISES — no per-message delay in core (the delayed-message-exchange
            plugin is not a standard broker, and TTL + dead-letter head-of-line
            blocks).
  kafka     RAISES — no per-message delay at all; a partition is read in offset
            order.

Per queue invariant 6, a backend that genuinely cannot perform an operation
raises naming the backend AND the operation. It may never silently no-op.

NO MOCKS. Every assertion drives a live MongoDB over TCP. If it is unreachable
the module skips, unless TINA4_REQUIRE_SERVICES is set — then a missing service
is a FAILURE, because a suite that silently skips its only real verification is
not verification.

The four case names here are shared VERBATIM with the PHP, Ruby and Node
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

# Long enough that a dropped delay is unambiguous, short enough to keep the
# suite quick. A dropped delay shows up instantly, so this is not a race.
DELAY = 3


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

    return lambda: Queue(topic=f"delay_{uuid.uuid4().hex[:12]}")


def test_an_undelayed_job_is_visible_immediately(mongo_queue):
    """NEGATIVE: without this pair, 'never return anything' passes the two
    delay tests below. It also proves the queue itself works, so a failure
    there is really about the delay and not about a broken backend."""
    queue = mongo_queue()
    queue.push({"m": "undelayed"}, 0, 0)
    time.sleep(1)

    assert queue.pop() is not None, "an undelayed job must be available at once"


def test_a_delayed_job_is_not_visible_before_its_delay_elapses(mongo_queue):
    """The measured defect: this job used to come straight back."""
    queue = mongo_queue()
    queue.push({"m": "delayed"}, 0, DELAY)
    time.sleep(1)

    assert queue.pop() is None, "a delayed job must not be claimable before its delay"


def test_a_delayed_job_becomes_visible_once_its_delay_elapses(mongo_queue):
    """NEGATIVE of the negative: 'hide it forever' would satisfy the test above
    while losing the job outright. The delay must expire."""
    queue = mongo_queue()
    queue.push({"m": "delayed"}, 0, DELAY)
    time.sleep(DELAY + 2)

    assert queue.pop() is not None, "a delayed job must be claimable after its delay"


@pytest.mark.parametrize("backend", ["rabbitmq", "kafka"])
def test_a_backend_that_cannot_delay_refuses_instead_of_dropping_the_delay(
    monkeypatch, backend
):
    """These two brokers have no per-message delay. Silently discarding it is
    the failure mode invariant 6 exists to forbid, so they raise naming both
    the backend and the operation — and never touch the network to do it."""
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", backend)

    from tina4_python.queue import Queue

    queue = Queue(topic=f"delay_{uuid.uuid4().hex[:12]}")

    with pytest.raises(NotImplementedError) as excinfo:
        queue.push({"m": "delayed"}, 0, DELAY)

    message = str(excinfo.value)
    assert backend in message, "the error must name the backend"
    assert "delay" in message.lower(), "the error must name the operation"
