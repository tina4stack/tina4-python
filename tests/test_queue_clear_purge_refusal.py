"""clear()/purge() on a broker backend refuse by name (ADR-0022, invariant 6).

MEASURED 2026-08-07: on the Kafka backend ``clear()`` returned 0 and ``purge()``
was a bare ``pass`` — a status-addressed operation silently no-opped, so a dev
who ran it believed the queue had been emptied when nothing happened. On the
RabbitMQ backend ``clear()``/``purge("pending")`` DRAINED the live broker queue,
destroying every pending job, because ``basic.get`` pops the head of the queue
and the adapter has no way to select messages by status.

ADR-0022: "a broker that cannot address messages by status refuses the
operation by name." ``clear()`` and ``purge(status)`` are status-addressed:
neither RabbitMQ nor Kafka can honour them (RabbitMQ has no status concept and
can only drain the whole queue; a Kafka log is read in offset order and leaves
only by retention). So both RAISE, naming the backend AND the operation, exactly
as the same two backends already do for ``push(priority)``, ``retry_failed()``
and ``failed()``.

NO MOCKS and NO BROKER. The refusal is a guard that fires BEFORE any socket is
opened — the connector connects lazily, and clear()/purge() raise before
touching ``self._backend`` at all — so constructing the real backend and calling
the real method is a complete, local, red-first test. The file backend is the
negative control: it CAN address by status, so it must still answer for real
rather than join a blanket refusal.
"""
import uuid

import pytest


@pytest.mark.parametrize("backend", ["rabbitmq", "kafka"])
def test_clear_on_a_broker_backend_refuses_by_name(monkeypatch, backend):
    """POSITIVE: clear() raises NotImplementedError naming the backend and the
    operation. Before the fix, kafka returned 0 (silent no-op) and rabbitmq
    drained the live queue (data loss)."""
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", backend)
    monkeypatch.setenv("TINA4_QUEUE_URL", "")

    from tina4_python.queue import Queue

    queue = Queue(topic=f"clr_{uuid.uuid4().hex[:10]}")

    with pytest.raises(NotImplementedError) as excinfo:
        queue.clear()

    message = str(excinfo.value)
    assert backend in message, "the refusal must name the backend"
    assert "clear" in message.lower(), "the refusal must name the operation"


@pytest.mark.parametrize("backend", ["rabbitmq", "kafka"])
def test_purge_on_a_broker_backend_refuses_by_name(monkeypatch, backend):
    """POSITIVE: purge(status) raises NotImplementedError naming the backend and
    the operation. Before the fix, kafka's purge() was a bare ``pass`` and
    rabbitmq drained the live queue on ``purge("pending")``."""
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", backend)
    monkeypatch.setenv("TINA4_QUEUE_URL", "")

    from tina4_python.queue import Queue

    queue = Queue(topic=f"prg_{uuid.uuid4().hex[:10]}")

    with pytest.raises(NotImplementedError) as excinfo:
        queue.purge("completed")

    message = str(excinfo.value)
    assert backend in message, "the refusal must name the backend"
    assert "purge" in message.lower(), "the refusal must name the operation"


def test_the_file_backend_still_clears_for_real(monkeypatch, tmp_path):
    """NEGATIVE control: a backend that CAN address by status must answer, not
    refuse. Without this, making every clear() raise would pass the two cases
    above while breaking the whole queue. The file backend returns a real int
    and never raises NotImplementedError."""
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
    monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path))

    from tina4_python.queue import Queue

    queue = Queue(topic=f"file_{uuid.uuid4().hex[:10]}")
    queue.push({"m": "keep"})

    removed = queue.clear()
    assert isinstance(removed, int), "the file backend must clear for real"


def test_the_file_backend_still_purges_for_real(monkeypatch, tmp_path):
    """NEGATIVE control: the file backend's purge(status) answers for real and
    never raises NotImplementedError — the refusal is broker-specific, not a
    blanket ban on the operation."""
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
    monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path))

    from tina4_python.queue import Queue

    queue = Queue(topic=f"file_{uuid.uuid4().hex[:10]}")

    purged = queue.purge("completed")
    assert isinstance(purged, int), "the file backend must purge for real"
