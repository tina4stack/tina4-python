"""queue_contract.json :: every-method-exists-on-every-backend

RULE: every public Queue method RESOLVES and runs on every configured backend.
No method may be a fatal error, a NoMethodError/AttributeError, or an undefined
method on any backend the framework offers.

This is not the same rule as invariant 6. Invariant 6 says an operation a
backend cannot perform must RAISE naming itself. Invariant 1 says the method
must EXIST to do the raising. A named refusal satisfies both; a
"Call to undefined method" fatal satisfies neither.

MEASURED 2026-08-03 across all four frameworks and every backend:
  python  clear() on mongodb -> AttributeError: 'NoneType' has no attribute
          'delete_many'. The only one of that adapter's six _collection users
          that forgot to connect first.
  php     failed(), deadLetters(), retry(), retryFailed() were a FATAL
          "Call to undefined method" on rabbitmq AND kafka. The QueueBackend
          interface never declared them, so only Lite and Mongo happened to
          have them while Queue called them on everything.
  ruby    size() raised NoMethodError on kafka - the method simply did not
          exist, though Python and PHP both answer 0.
  node    rabbitmq and kafka throw at CONSTRUCTION. This is ADR-0022 decision
          8 and is CORRECT, not a violation: a backend that cannot keep the
          at-least-once promise is refused rather than documented. It is a
          holding position recorded in that ADR.

NO MOCKS. Every assertion drives a live MongoDB over TCP. If it is unreachable
the module skips, unless TINA4_REQUIRE_SERVICES is set - then a missing service
is a FAILURE.

The three case names here are shared VERBATIM with the PHP, Ruby and Node
suites, because scripts/audit-contract-fixtures.py resolves ONE fixture case
against EVERY framework's file.
"""
import os
import socket
import uuid

import pytest

HOST = os.environ.get("TINA4_TEST_MONGO_HOST", "127.0.0.1")
PORT = int(os.environ.get("TINA4_TEST_MONGO_PORT", "27017"))

# Every public Queue method that takes no live job to exercise.
METHODS = {
    "size": lambda q: q.size(),
    "pop_batch": lambda q: q.pop_batch(1),
    "pop_by_id": lambda q: q.pop_by_id("nope"),
    "failed": lambda q: q.failed(),
    "dead_letters": lambda q: q.dead_letters(),
    "retry": lambda q: q.retry(),
    "retry_failed": lambda q: q.retry_failed(),
    "purge": lambda q: q.purge("completed"),
    "clear": lambda q: q.clear(),
}


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


def _queue(monkeypatch, backend):
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", backend)
    monkeypatch.setenv("TINA4_QUEUE_URL", f"mongodb://{HOST}:{PORT}" if backend == "mongodb" else "")

    from tina4_python.queue import Queue

    return Queue(topic=f"surf_{uuid.uuid4().hex[:10]}")


@pytest.mark.parametrize("backend", ["file", "mongodb"])
def test_every_public_queue_method_resolves_on_every_backend(monkeypatch, backend):
    """A method must never be ABSENT. AttributeError/NoMethodError means the
    call site cannot even reach a refusal - the upgrade path is severed rather
    than degraded, which is the exact scenario ADR-0024 exists to prevent.

    Each method is exercised TWICE, because the two modes catch different bugs:

    - FRESH queue per method. This is the mode that catches a method which
      never initialises what it uses. Python's clear() reached the connector's
      _collection without connecting first, so it was AttributeError on a
      brand-new Queue. On a SHARED queue an earlier size() had already
      connected, which hid it completely.
    - SHARED queue across methods. This catches state a previous call left
      behind. PHP's broker backends stored FALSE in the socket after a failed
      connect, so every later call died in fwrite().
    """
    unresolved = []

    # Mode 1: a brand-new queue for every method.
    for name, call in METHODS.items():
        queue = _queue(monkeypatch, backend)
        try:
            call(queue)
        except AttributeError as exc:            # the violation: no such method
            unresolved.append(f"fresh {name}: {exc}")
        except NotImplementedError:              # a NAMED refusal is allowed
            pass
        except Exception:                        # noqa: BLE001 - any other runtime
            pass                                 # error is not this invariant

    # Mode 2: one queue, every method in sequence.
    queue = _queue(monkeypatch, backend)
    for name, call in METHODS.items():
        try:
            call(queue)
        except AttributeError as exc:
            unresolved.append(f"shared {name}: {exc}")
        except NotImplementedError:
            pass
        except Exception:                        # noqa: BLE001
            pass

    assert unresolved == [], f"{backend}: methods that do not resolve: {unresolved}"


@pytest.mark.parametrize("backend", ["rabbitmq", "kafka"])
def test_a_backend_that_cannot_answer_a_question_refuses_by_name_instead_of_lying(
    monkeypatch, backend
):
    """The broker keeps no queryable registry of failed jobs. Returning an
    empty list would claim nothing has failed, which is a different answer to
    the question asked - so it must refuse, naming itself."""
    queue = _queue(monkeypatch, backend)

    # These three resolve on every backend. On a broker they may either answer
    # or refuse BY NAME - what they may never do is fail to exist.
    for name in ("failed", "dead_letters", "retry_failed"):
        assert hasattr(queue, name), f"{backend}: Queue.{name} must exist"

    # push(priority) is the operation these brokers genuinely cannot do; the
    # refusal must name the backend AND the operation.
    with pytest.raises(NotImplementedError) as excinfo:
        queue.push({"m": "x"}, 9, 0)
    message = str(excinfo.value)
    assert backend in message, "the refusal must name the backend"
    assert "priority" in message.lower(), "the refusal must name the operation"


@pytest.mark.parametrize("backend", ["file", "mongodb"])
def test_a_supported_method_returns_a_real_answer_rather_than_a_refusal(
    monkeypatch, backend
):
    """NEGATIVE: without this, 'make every method raise a named refusal' would
    satisfy both cases above while breaking the whole queue. A backend that CAN
    answer must actually answer."""
    queue = _queue(monkeypatch, backend)

    assert isinstance(queue.size(), int), "size must return a real count"
    assert isinstance(queue.failed(), list), "failed must return a real list"
    assert isinstance(queue.dead_letters(), list), "dead_letters must return a real list"
    assert isinstance(queue.clear(), int), "clear must return a real count"
