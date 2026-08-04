"""queue_contract.json :: the-failure-lifecycle-is-real-everywhere

MEASURED 2026-08-04, and this invariant was OWED with no suite at all — which
is why every defect below shipped.

The rule: job.fail() reaches the backend on EVERY provider, and a job past
max_retries becomes observable through dead_letters() on EVERY provider. A
dead-letter handler written against the file backend must find the same jobs
after deploying onto Mongo or a broker.

What was actually measured before the fix:

  mongodb   failed() queried status="failed", which NOTHING ever writes — the
            retryable path re-queues as "pending" (that is what makes the next
            pop redeliver it). So it returned [] forever, and an empty list is
            indistinguishable from "nothing has failed" (ADR-0022 decision 7).
  mongodb   the dead-letter record was built WITHOUT attempts, so every Mongo
            dead letter read back as attempts=0 while file reported the real
            count. A handler logging "died after N attempts" printed 0. The
            re-queue path also dropped the error text.
  rabbitmq  failed()/retry_failed() drained the .dead_letter topic looking for
            attempts < max_retries. Only EXHAUSTED jobs are written there, so
            the predicate could never match and both silently returned []/0.
  kafka     the same.

These cases pin the WHOLE lifecycle, not just the happy path. Case 1 is the
boundary (retry, not dead-letter) and case 4 is the control: without them,
"dead-letter everything on first failure" passes case 2, and "return every job
ever seen" passes case 3.

NO MOCKS. Every assertion drives a live MongoDB over TCP, and the refusal case
drives a live RabbitMQ. If a service is unreachable the file skips, unless
TINA4_REQUIRE_SERVICES is set — then a missing service is a FAILURE, because a
suite that silently skips its only real verification is not verification.

The six case names here are shared VERBATIM with the PHP, Ruby and Node suites,
because scripts/audit-contract-fixtures.py resolves ONE fixture case against
EVERY framework's file.
"""
import os
import socket
import time
import uuid

import pytest

HOST = os.environ.get("TINA4_TEST_MONGO_HOST", "127.0.0.1")
PORT = int(os.environ.get("TINA4_TEST_MONGO_PORT", "27017"))
RABBIT_HOST = os.environ.get("TINA4_TEST_RABBITMQ_HOST", "127.0.0.1")
RABBIT_PORT = int(os.environ.get("TINA4_TEST_RABBITMQ_PORT", "5672"))

MAX_RETRIES = 2


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


if not _reachable(HOST, PORT):
    if os.environ.get("TINA4_REQUIRE_SERVICES"):
        raise RuntimeError(
            f"TINA4_REQUIRE_SERVICES is set but MongoDB is not reachable at {HOST}:{PORT}"
        )
    pytest.skip(f"MongoDB not reachable at {HOST}:{PORT}", allow_module_level=True)


@pytest.fixture
def make_queue(monkeypatch, tmp_path):
    """Build a real Queue on a topic no other test shares.

    A FRESH queue per call, deliberately. Reusing one instance across a loop is
    how the surface-invariant test once passed with its fix reverted: an earlier
    call had already connected, so the defect it was meant to catch could not
    reproduce.
    """
    monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path))
    monkeypatch.setenv("TINA4_MONGO_URI", f"mongodb://{HOST}:{PORT}")
    monkeypatch.setenv("TINA4_QUEUE_MONGO_URI", f"mongodb://{HOST}:{PORT}")

    from tina4_python.queue import Queue

    def _build(backend: str):
        return Queue(
            topic=f"faillc_{uuid.uuid4().hex[:12]}",
            backend=backend,
            max_retries=MAX_RETRIES,
        )

    return _build


# Both backends implement the full lifecycle, so both must answer identically.
# That equality IS the invariant — testing only one proves nothing about the swap.
LIFECYCLE_BACKENDS = ["file", "mongodb"]


def _drain_fail(queue, times: int, reason_prefix: str = "boom"):
    """Pop and fail a job `times` times, returning the last job popped."""
    last = None
    for attempt in range(1, times + 1):
        job = queue.pop()
        if job is None:
            break
        last = job
        job.fail(f"{reason_prefix}-{attempt}")
        time.sleep(0.3)
    return last


@pytest.mark.parametrize("backend", LIFECYCLE_BACKENDS)
def test_a_failed_job_under_max_retries_is_retried_rather_than_dead_lettered(make_queue, backend):
    """NEGATIVE/boundary: pins that failing is not the same as dying.

    Without this, 'dead-letter on the first failure' passes the past-max-retries
    case below while destroying every transient failure — the single most
    damaging way to get this wrong.
    """
    queue = make_queue(backend)
    queue.push({"m": "transient"})
    time.sleep(0.4)

    job = queue.pop()
    assert job is not None, f"{backend}: nothing to pop"
    job.fail("boom-1")
    time.sleep(0.4)

    assert queue.dead_letters() == [], (
        f"{backend}: a job with retries left must NOT be dead-lettered"
    )
    # THE defect this whole invariant was owed for: on mongodb failed() queried
    # status="failed", which the retryable path never writes, so it returned []
    # forever. Asserting only "not dead-lettered" would still pass with that bug
    # — the job has to be positively REPORTABLE as failed.
    still_failed = queue.failed()
    assert len(still_failed) == 1, (
        f"{backend}: a job that failed with retries left must be reported by "
        f"failed(), got {len(still_failed)}"
    )
    assert queue.pop() is not None, (
        f"{backend}: a job with retries left must come back for another attempt"
    )


@pytest.mark.parametrize("backend", LIFECYCLE_BACKENDS)
def test_a_job_past_max_retries_becomes_a_dead_letter(make_queue, backend):
    """The core rule: exhausting the retries makes the job observable as dead."""
    queue = make_queue(backend)
    queue.push({"m": "poison"})
    time.sleep(0.4)

    _drain_fail(queue, MAX_RETRIES)
    time.sleep(0.4)

    assert len(queue.dead_letters()) == 1, (
        f"{backend}: a job past max_retries must appear in dead_letters()"
    )
    assert queue.pop() is None, (
        f"{backend}: a dead-lettered job must NOT still be redelivered"
    )


@pytest.mark.parametrize("backend", LIFECYCLE_BACKENDS)
def test_a_dead_letter_carries_the_attempt_count_and_the_failure_reason(make_queue, backend):
    """The measured Mongo defect: attempts came back 0 and the reason was lost.

    A dead-letter handler exists to answer "what died, why, and after how many
    tries". A dead letter that cannot answer that is a row in a table.
    """
    queue = make_queue(backend)
    queue.push({"m": "poison"})
    time.sleep(0.4)

    _drain_fail(queue, MAX_RETRIES)
    time.sleep(0.4)

    dead = queue.dead_letters()
    assert len(dead) == 1, f"{backend}: expected exactly one dead letter"
    assert dead[0].attempts == MAX_RETRIES, (
        f"{backend}: dead letter reported attempts={dead[0].attempts}, "
        f"expected {MAX_RETRIES}"
    )
    assert dead[0].error == f"boom-{MAX_RETRIES}", (
        f"{backend}: dead letter lost the failure reason (got {dead[0].error!r})"
    )


@pytest.mark.parametrize("backend", LIFECYCLE_BACKENDS)
def test_a_completed_job_never_appears_in_dead_letters(make_queue, backend):
    """NEGATIVE control: 'return every job ever seen' must not pass the others."""
    queue = make_queue(backend)
    queue.push({"m": "healthy"})
    time.sleep(0.4)

    job = queue.pop()
    assert job is not None, f"{backend}: nothing to pop"
    job.complete()
    time.sleep(0.4)

    assert queue.dead_letters() == [], (
        f"{backend}: a completed job must never be reported as dead"
    )
    assert queue.failed() == [], (
        f"{backend}: a completed job must never be reported as failed"
    )


@pytest.mark.parametrize("backend", LIFECYCLE_BACKENDS)
def test_reading_dead_letters_does_not_consume_them(make_queue, backend):
    """A READ must not mutate.

    dead_letters() is what a dashboard or health check calls on a timer. On the
    brokers it is implemented by draining the dead-letter queue and re-publishing
    what it read, so an unfaithful round-trip would make a monitor destroy — or
    endlessly multiply — the backlog it reports on.
    """
    queue = make_queue(backend)
    queue.push({"m": "poison"})
    time.sleep(0.4)

    _drain_fail(queue, MAX_RETRIES)
    time.sleep(0.4)

    counts = [len(queue.dead_letters()) for _ in range(3)]
    assert counts == [1, 1, 1], (
        f"{backend}: reading dead_letters() changed the result across reads: {counts}"
    )


def test_failing_a_job_reaches_the_configured_backend_and_not_just_local_memory():
    """Proof the failure LEAVES the process.

    None of the cases above can catch this: they run on file/mongodb, where the
    backend has always had a working fail(). Only a broker exposes a failure
    that is recorded locally and never transmitted - the shape Ruby shipped,
    where job.fail() bumped an in-memory counter while the broker was never
    told, leaving the delivery unacked with no dead letter written.

    The proof is redelivery carrying the incremented count: that can only
    happen if fail() re-published through the broker.
    """
    if not _reachable(RABBIT_HOST, RABBIT_PORT):
        if os.environ.get("TINA4_REQUIRE_SERVICES"):
            raise RuntimeError(
                "TINA4_REQUIRE_SERVICES is set but RabbitMQ is not reachable at "
                f"{RABBIT_HOST}:{RABBIT_PORT}"
            )
        pytest.skip(f"RabbitMQ not reachable at {RABBIT_HOST}:{RABBIT_PORT}")

    os.environ["TINA4_RABBITMQ_HOST"] = RABBIT_HOST
    os.environ["TINA4_RABBITMQ_PORT"] = str(RABBIT_PORT)
    from tina4_python.queue import Queue

    queue = Queue(topic=f"faillc_rmq_{uuid.uuid4().hex[:8]}", backend="rabbitmq",
                  max_retries=MAX_RETRIES)
    queue.push({"m": "poison"})
    time.sleep(0.5)

    job = queue.pop()
    assert job is not None, "nothing to pop from the broker"
    job.fail("boom-1")
    time.sleep(0.5)

    redelivered = queue.pop()
    assert redelivered is not None, (
        "the failure did not reach the broker - nothing was redelivered"
    )
    assert redelivered.attempts == 1, (
        "the attempt count did not survive the round-trip through the broker "
        f"(got {redelivered.attempts})"
    )

    redelivered.fail("boom-2")
    time.sleep(0.5)
    dead = queue.dead_letters()
    assert len(dead) == 1, (
        "a broker job past max_retries must reach the dead-letter queue"
    )
    assert dead[0].attempts == MAX_RETRIES
    assert dead[0].error == f"boom-{MAX_RETRIES}"


def test_a_backend_that_cannot_enumerate_retryable_failures_refuses_by_name():
    """Invariant 6's half of this rule.

    A broker CAN report exhausted jobs (both keep their own .dead_letter topic),
    but it genuinely cannot enumerate failed-but-still-retryable ones: fail()
    re-publishes those to the MAIN topic, where they are indistinguishable from
    pending work without draining a live queue. Returning [] would claim nothing
    has failed, so it raises — naming the backend AND the operation.
    """
    if not _reachable(RABBIT_HOST, RABBIT_PORT):
        if os.environ.get("TINA4_REQUIRE_SERVICES"):
            raise RuntimeError(
                "TINA4_REQUIRE_SERVICES is set but RabbitMQ is not reachable at "
                f"{RABBIT_HOST}:{RABBIT_PORT}"
            )
        pytest.skip(f"RabbitMQ not reachable at {RABBIT_HOST}:{RABBIT_PORT}")

    os.environ["TINA4_RABBITMQ_HOST"] = RABBIT_HOST
    os.environ["TINA4_RABBITMQ_PORT"] = str(RABBIT_PORT)
    from tina4_python.queue import Queue

    queue = Queue(topic=f"faillc_rmq_{uuid.uuid4().hex[:8]}", backend="rabbitmq",
                  max_retries=MAX_RETRIES)

    with pytest.raises(NotImplementedError) as failed_exc:
        queue.failed()
    message = str(failed_exc.value)
    assert "rabbitmq" in message, "the refusal must name the BACKEND"
    assert "failed()" in message, "the refusal must name the OPERATION"

    with pytest.raises(NotImplementedError) as retry_exc:
        queue.retry_failed()
    retry_message = str(retry_exc.value)
    assert "rabbitmq" in retry_message, "the refusal must name the BACKEND"
    assert "retry_failed()" in retry_message, (
        "retry_failed() must carry its OWN refusal — letting failed()'s message "
        "escape names the wrong operation to the caller"
    )
