"""queue_contract.json :: operations-reach-the-configured-backend

RULE: every operation acts on the CONFIGURED backend. No method may silently
read or write the local file store, or silently no-op, when another backend is
selected.

MEASURED 2026-08-03 on mongodb, before the fix:
  python  pop_by_id() returned None on every non-file backend - a literal
          `if not isinstance(self._backend, LiteBackend): return None`, a
          silent no-op indistinguishable from "no such job".
  php     clear() and purge() called the local file store unconditionally, and
          popById() returned null on every external backend.
  ruby    clear() and pop_by_id() returned 0/nil because MongoBackend had
          neither method and Queue guarded on respond_to?.
  node    popBatch() and popById() read the LOCAL FILE STORE regardless of the
          configured backend, so they never saw a mongodb job at all.

pop_by_id was broken in ALL FOUR - unanimous, which makes it a contract nobody
had written down rather than four independent bugs.

This is the worst failure class: the call appears to succeed and operates on
the wrong data, so nothing surfaces it.

NO MOCKS. Live MongoDB over TCP; skips unless TINA4_REQUIRE_SERVICES is set,
which turns a missing service into a FAILURE.

The three case names here are shared VERBATIM with the PHP, Ruby and Node
suites.
"""
import os
import socket
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
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", "mongodb")
    monkeypatch.setenv("TINA4_QUEUE_URL", f"mongodb://{HOST}:{PORT}")
    from tina4_python.queue import Queue

    return lambda: Queue(topic=f"reach_{uuid.uuid4().hex[:12]}")


def test_clear_acts_on_the_configured_backend_not_the_local_file_store(mongo_queue):
    """If clear() hits the file store, the mongodb jobs survive and size stays 2."""
    queue = mongo_queue()
    queue.push({"m": "a"}, 0, 0)
    queue.push({"m": "b"}, 0, 0)
    assert queue.size() == 2, "the pushes must reach mongodb first, or this proves nothing"

    queue.clear()

    assert queue.size() == 0, "clear() must empty the CONFIGURED backend"


def test_pop_by_id_claims_the_job_from_the_configured_backend(mongo_queue):
    """The job is in mongodb and we ask for it by its own id. Getting nothing
    back means the call went somewhere else - or silently no-opped."""
    queue = mongo_queue()
    job_id = queue.push({"m": "byid"}, 0, 0)

    claimed = queue.pop_by_id(job_id)

    assert claimed is not None, "pop_by_id must claim the job from the configured backend"


@pytest.mark.parametrize("backend", ["rabbitmq", "kafka"])
def test_an_operation_the_backend_cannot_perform_refuses_instead_of_silently_using_the_file_store(
    monkeypatch, backend
):
    """A broker cannot address one message by id. It must say so, naming
    itself - never quietly answer from a local directory."""
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", backend)
    from tina4_python.queue import Queue

    queue = Queue(topic=f"reach_{uuid.uuid4().hex[:12]}")

    with pytest.raises(NotImplementedError) as excinfo:
        queue.pop_by_id("whatever")
    assert "pop_by_id" in str(excinfo.value), "the refusal must name the operation"
