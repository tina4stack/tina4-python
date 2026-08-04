"""Queue.close() — the connection an app opens must be one it can hand back.

MEASURED 2026-08-04: ``close()`` was ABSENT on the top-level ``Queue`` class in
ALL FOUR frameworks. The backends below it were in four different states —

    php     close() on the QueueBackend INTERFACE, implemented by all four
            backends, and reachable from nothing.
    ruby    close on rabbitmq/mongo/kafka, missing on lite, so a caller that
            wrote `queue.backend.close if respond_to?` silently skipped it.
    nodejs  nowhere on any backend class.
    python  nowhere at all on the queue/ adapters (the low-level connectors in
            queue_backends/ had one, unreachable from Queue).

— so an application holding a broker- or Mongo-backed queue had NO WAY to
release the connection. Build a Queue per request and you leak one client per
request, invisibly, until the broker refuses new connections. That is exactly
the leak ADR-0025 corollary 4 (client-lifecycle-is-bounded) fixed in DocStore,
where 20 get_collection() calls left ~39 server connections open.

The three cases are positive AND negative on purpose:

  1. closing releases the connection      — the POSITIVE rule. A close() that
                                            exists but delegates nowhere fails
                                            here and nowhere else.
  2. closing twice is safe                — NEGATIVE. Shutdown paths run twice
                                            (an explicit close plus an atexit /
                                            finally); a close that raises the
                                            second time turns a clean shutdown
                                            into a crash.
  3. closing the file backend is no error — NEGATIVE. The file backend has no
                                            connection, and close() must be a
                                            no-op there rather than an
                                            AttributeError. Without this, the
                                            zero-config default breaks the
                                            moment anyone calls close().

NO MOCKS. Every handle inspected here belongs to a REAL connector holding a
REAL socket to a REAL MongoDB / RabbitMQ / Kafka over TCP; the file cases use a
real temp directory. There is no double, stub or monkeypatched collaborator
anywhere in this file — the only monkeypatch is on os.environ, which is
configuration, not a collaborator. A service that is unreachable skips, unless
TINA4_REQUIRE_SERVICES is set — then it is a FAILURE, because a suite that
silently skips its only real verification is not verification.

The three case names are shared VERBATIM with the PHP, Ruby and Node suites, so
one fixture case in scripts/audit-contract-fixtures.py resolves against EVERY
framework's file.
"""
import os
import socket
import uuid

import pytest

MONGO_HOST = os.environ.get("TINA4_TEST_MONGO_HOST", "127.0.0.1")
MONGO_PORT = int(os.environ.get("TINA4_TEST_MONGO_PORT", "27017"))
RABBIT_HOST = os.environ.get("TINA4_TEST_RABBITMQ_HOST", "127.0.0.1")
RABBIT_PORT = int(os.environ.get("TINA4_TEST_RABBITMQ_PORT", "5672"))
KAFKA_HOST = os.environ.get("TINA4_TEST_KAFKA_HOST", "127.0.0.1")
KAFKA_PORT = int(os.environ.get("TINA4_TEST_KAFKA_PORT", "9092"))

# Backends that hold a real connection, and the service each one needs.
SERVICES = {
    "mongodb": ("MongoDB", MONGO_HOST, MONGO_PORT),
    "rabbitmq": ("RabbitMQ", RABBIT_HOST, RABBIT_PORT),
    "kafka": ("Kafka", KAFKA_HOST, KAFKA_PORT),
}
CONNECTED_BACKENDS = ["mongodb", "rabbitmq", "kafka"]
ALL_BACKENDS = ["file"] + CONNECTED_BACKENDS

# Every field a queue connector uses to hold a LIVE connection. The imported
# module handles (_pymongo / _pika / _confluent) are deliberately NOT here:
# they are modules, not connections, and close() must not drop them.
HANDLE_FIELDS = (
    "_client", "_db", "_collection",   # mongodb
    "_connection", "_channel",         # rabbitmq (pika)
    "_producer", "_consumer",          # kafka (confluent)
    "_socket",                         # rabbitmq / kafka (raw wire protocol)
)


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def _require(name: str, host: str, port: int) -> None:
    """Skip, or FAIL under TINA4_REQUIRE_SERVICES. A silent skip is not proof."""
    if _reachable(host, port):
        return
    if os.environ.get("TINA4_REQUIRE_SERVICES"):
        pytest.fail(
            f"TINA4_REQUIRE_SERVICES is set but {name} is not reachable at {host}:{port}"
        )
    pytest.skip(f"{name} not reachable at {host}:{port}")


def _live_handles(queue) -> list:
    """Names of the connection handles the queue's backend is holding RIGHT NOW.

    Reads the REAL connector object's REAL state — no double is involved. The
    file backend has no connector underneath it and therefore no handles, which
    is the whole reason close() must be a no-op there.
    """
    connector = getattr(queue._backend, "_backend", None)
    if connector is None:
        return []
    return [field for field in HANDLE_FIELDS if getattr(connector, field, None) is not None]


@pytest.fixture
def make_queue(monkeypatch, tmp_path):
    """Build a real Queue on a topic no other test shares.

    A FRESH queue per call, deliberately: reusing one instance across backends
    is how a connection opened by an earlier call makes a later assertion pass
    for the wrong reason.
    """
    monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path))
    monkeypatch.setenv("TINA4_MONGO_URI", f"mongodb://{MONGO_HOST}:{MONGO_PORT}")
    monkeypatch.setenv("TINA4_QUEUE_MONGO_URI", f"mongodb://{MONGO_HOST}:{MONGO_PORT}")
    monkeypatch.setenv("TINA4_RABBITMQ_HOST", RABBIT_HOST)
    monkeypatch.setenv("TINA4_RABBITMQ_PORT", str(RABBIT_PORT))
    monkeypatch.setenv("TINA4_KAFKA_BROKERS", f"{KAFKA_HOST}:{KAFKA_PORT}")
    # TINA4_QUEUE_BACKEND would override the explicit backend= argument, and a
    # stray TINA4_QUEUE_URL would re-point every broker at someone else's host.
    monkeypatch.delenv("TINA4_QUEUE_BACKEND", raising=False)
    monkeypatch.delenv("TINA4_QUEUE_URL", raising=False)

    from tina4_python.queue import Queue

    built = []

    def _build(backend: str):
        queue = Queue(
            topic=f"qclose_{uuid.uuid4().hex[:12]}",
            backend=backend,
            max_retries=2,
        )
        built.append(queue)
        return queue

    yield _build

    # Reap what we spawn: a connection left open by a FAILING case must not be
    # inherited by the next one. Idempotent, which is case 2's whole point.
    for queue in built:
        try:
            queue.close()
        except Exception:  # noqa: BLE001 - teardown must never mask the failure
            pass


@pytest.mark.parametrize("backend", CONNECTED_BACKENDS)
def test_closing_a_queue_releases_the_backend_connection(make_queue, backend):
    """POSITIVE: close() reaches the backend and the live handle is given back.

    The push is not decoration — every connected backend connects LAZILY, so
    without a real operation first there would be no connection to release and
    this case would pass against a close() that does nothing at all.
    """
    _require(*SERVICES[backend])

    queue = make_queue(backend)
    queue.push({"m": "connect"})

    held = _live_handles(queue)
    assert held, (
        f"{backend}: expected a live connection handle after a real push, found none "
        f"— the test cannot prove a release that never had anything to release"
    )

    queue.close()

    still_open = _live_handles(queue)
    assert still_open == [], (
        f"{backend}: close() left {still_open} still held — the connection was "
        f"never released, which is the leak this exists to stop"
    )


@pytest.mark.parametrize("backend", ALL_BACKENDS)
def test_closing_a_queue_twice_is_safe(make_queue, backend):
    """NEGATIVE: a second close() must be a no-op, never an exception.

    Shutdown paths run twice in real apps (an explicit close plus an atexit or
    finally). A close that raises on the second call turns a clean shutdown into
    a crash, and a `finally: queue.close()` into a masked original error.
    """
    if backend != "file":
        _require(*SERVICES[backend])

    queue = make_queue(backend)
    queue.push({"m": "connect"})

    try:
        queue.close()
        queue.close()
    except Exception as exc:  # noqa: BLE001 - the raise IS the failure
        pytest.fail(f"{backend}: closing twice raised {type(exc).__name__}: {exc}")

    still_open = _live_handles(queue)
    assert still_open == [], f"{backend}: {still_open} still held after two closes"


def test_closing_a_file_backed_queue_is_not_an_error(make_queue):
    """NEGATIVE: the zero-config default has no connection, and must not care.

    The file backend is what every app gets before it configures anything. If
    close() were only defined on the connected backends, adding a shutdown path
    would break the default with an AttributeError — so this pins that the
    no-op is real, and that it does not disturb the queue's contents.
    """
    queue = make_queue("file")
    queue.push({"m": "on disk"})

    before = queue.size("pending")
    assert before == 1, f"file: expected the pushed job to be pending, got {before}"

    try:
        queue.close()
    except Exception as exc:  # noqa: BLE001 - the raise IS the failure
        pytest.fail(f"file: close() raised {type(exc).__name__}: {exc}")

    assert _live_handles(queue) == [], "file: the file backend must hold no connection"
    assert queue.size("pending") == before, (
        "file: close() must not disturb the queue's contents — it has nothing to close"
    )
