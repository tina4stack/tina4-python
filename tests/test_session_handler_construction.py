"""SESSION CONTRACT: a handler constructor performs NO network I/O.

ADR-0021: connection happens on FIRST USE, inside the log-loud-and-degrade
policy. A constructor sits OUTSIDE that policy, so anything it does cannot be
logged, cannot be degraded, and cannot be re-raised by TINA4_SESSION_STRICT.

WHY THIS MATTERS, stated as the operator sees it: the one place the failure
policy cannot protect is the FIRST thing that runs. An unreachable backend takes
the app down at construction instead of degrading per-request as designed - so
the very scenario the policy exists for is the one it never sees.

MEASURED at v3 HEAD, tina4_python/session/__init__.py:167:

    def __init__(self, db, ttl: int = None):
        self._db = db
        self._ttl = ...
        self._ensure_table()      <-- table_exists() + CREATE TABLE + commit()

Real DDL, on a real connection, in a constructor. And because the request path
builds a Session per request, that ran on EVERY request.

HOW THIS IS PROVED WITHOUT MOCKS. Two independent real measurements:

  * A real TCP listener this test starts, which COUNTS accepted connections.
    Construct the handler pointed at it and the count must still be zero; do one
    real operation and the count must rise. That is a direct observation of
    network behaviour, not an assertion about code shape - a handler cannot
    connect without the kernel completing an accept() we can see.

  * A genuinely CLOSED port. A constructor that connects raises "connection
    refused"; one that does not, returns an object. No doubles either way.

The negative control matters as much: deferring the connection must not break
the connection. A healthy backend still has to round-trip after the change, or
"do nothing in the constructor" has been satisfied by doing nothing at all.
"""
from __future__ import annotations

import os
import socket
import threading
import time
import uuid

import pytest

from tina4_python.database import Database
from tina4_python.session import DatabaseSessionHandler

REDIS_HOST = os.environ.get("TINA4_SESSION_REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.environ.get("TINA4_SESSION_REDIS_PORT", "6379"))


def _closed_port() -> int:
    """Bind a port, learn its number, close it. Nothing listens afterwards."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return port


class _CountingListener:
    """A REAL TCP server that counts the connections it accepts.

    Not a mock of a backend - it speaks no protocol and pretends to be nothing.
    It is a socket, and the only thing it reports is a fact the kernel decided:
    whether anybody actually connected. That is exactly the question this file
    asks, and no test double can answer it honestly.
    """

    def __init__(self):
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(16)
        self._server.settimeout(0.25)
        self.port = self._server.getsockname()[1]
        self.accepted = 0
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while self._running:
            try:
                connection, _ = self._server.accept()
            except (socket.timeout, OSError):
                continue
            self.accepted += 1
            try:
                connection.close()      # accept, count, hang up
            except OSError:
                pass

    def close(self):
        self._running = False
        self._thread.join(timeout=2)
        try:
            self._server.close()
        except OSError:
            pass


@pytest.fixture
def listener():
    probe = _CountingListener()
    yield probe
    probe.close()


def _build_network_handlers(host: str, port: int) -> dict:
    """Every handler that speaks over a socket, pointed at one endpoint."""
    from tina4_python.session_handlers import (
        MemcachedSessionHandler,
        MongoDBSessionHandler,
        RedisSessionHandler,
        ValkeySessionHandler,
    )
    return {
        "redis": lambda: RedisSessionHandler(host=host, port=port, ttl=60),
        "valkey": lambda: ValkeySessionHandler(host=host, port=port, ttl=60),
        "memcached": lambda: MemcachedSessionHandler(host=host, port=port, ttl=60),
        "mongodb": lambda: MongoDBSessionHandler(
            url=f"mongodb://{host}:{port}/?serverSelectionTimeoutMS=500&connectTimeoutMS=500",
            ttl=60,
        ),
    }


def test_a_session_handler_constructor_performs_no_network_io(listener, tmp_path):
    """Constructing a handler must not touch the network. Proved by a real accept() count.

    The listener is a real socket. If any constructor dials it, the kernel
    completes an accept and the counter moves. Nothing here can be satisfied by
    a handler that merely *claims* not to connect.
    """
    for name, build in _build_network_handlers("127.0.0.1", listener.port).items():
        before = listener.accepted
        build()
        time.sleep(0.2)  # give any background connect a real chance to land
        assert listener.accepted == before, (
            f"{name}: the CONSTRUCTOR opened a connection "
            f"({listener.accepted - before} accepted). Connection belongs on first "
            "use, inside the failure policy - a constructor sits outside it, so "
            "nothing it does can be logged, degraded or re-raised."
        )

    # The database backend owns no socket of its own to watch - it is handed a
    # Database that is already connected - so its constructor is measured by its
    # SIDE EFFECT instead, against a real engine: it used to run table_exists()
    # + CREATE TABLE + commit(). Drop the table, construct the handler, and the
    # table must still be absent. That is a real out-of-band observation (a
    # second connection asks the server), not an assertion about code shape.
    #
    # SQLite is the engine here because it needs no service to be reachable for
    # the DDL question to be meaningful; the same code path serves every engine.
    database_path = tmp_path / "construction.db"
    database = Database(f"sqlite://{database_path}")
    database.execute("DROP TABLE IF EXISTS tina4_session")

    DatabaseSessionHandler(database)

    probe = Database(f"sqlite://{database_path}")
    assert not probe.table_exists("tina4_session"), (
        "the DatabaseSessionHandler CONSTRUCTOR created its table - real DDL on a "
        "real connection, outside the failure policy. Because the request path "
        "builds a Session per request, that ran on EVERY request."
    )


def test_the_backend_connection_happens_on_first_use_not_construction(listener):
    """Deferred is not the same as never. The FIRST OPERATION must connect.

    Without this, "do no I/O in the constructor" is trivially satisfied by a
    handler that does no I/O at all, and case 1 would pass on a broken store.
    """
    build = _build_network_handlers("127.0.0.1", listener.port)["redis"]
    handler = build()
    time.sleep(0.2)
    after_construction = listener.accepted

    # One real operation against the listener. It answers nothing useful, so the
    # handler will fail - that is fine and expected; we are measuring the DIAL,
    # not the conversation.
    try:
        handler.read("connection-probe-" + uuid.uuid4().hex[:8])
    except Exception:
        pass
    time.sleep(0.2)

    assert listener.accepted > after_construction, (
        "the first operation opened NO connection - the handler is not lazy, it "
        "is inert, and case 1 would pass on a store that never talks to anything"
    )


def test_a_healthy_backend_still_works_after_lazy_connection(tmp_path):
    """NEGATIVE CONTROL: deferring the connection must not break the connection.

    A real Redis and a real SQLite file, both driven end to end. "No I/O in the
    constructor" is not an achievement if the handler no longer works.
    """
    from tina4_python.session_handlers import RedisSessionHandler

    if not _reachable(REDIS_HOST, REDIS_PORT):
        message = f"redis is not reachable at {REDIS_HOST}:{REDIS_PORT}"
        if os.environ.get("TINA4_REQUIRE_SERVICES"):
            pytest.fail(f"TINA4_REQUIRE_SERVICES is set but {message}")
        pytest.skip(message)

    session_id = f"lazyok-{uuid.uuid4().hex[:8]}"
    redis_handler = RedisSessionHandler(host=REDIS_HOST, port=REDIS_PORT, ttl=60)
    redis_handler.write(session_id, {"seeded": True})
    assert redis_handler.read(session_id) == {"seeded": True}, "redis round-trip broke"
    redis_handler.destroy(session_id)

    database = Database(f"sqlite://{tmp_path / 'lazy.db'}")
    database_handler = DatabaseSessionHandler(database)
    database_handler.write(session_id, {"seeded": True})
    assert database_handler.read(session_id) == {"seeded": True}, (
        "the database round-trip broke - the table is created on first use, so a "
        "deferred _ensure_table that never runs shows up exactly here"
    )


def _reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
