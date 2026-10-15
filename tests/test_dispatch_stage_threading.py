# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""THE DISPATCH PIPELINE STAGES MUST NOT BLOCK THE EVENT LOOP EITHER.

ADR-0074 (test_sync_handler_threading.py) threaded the ROUTE HANDLER so a
blocking `def` route no longer freezes the loop. But only the handler was
offloaded: every dispatch STAGE still runs on the loop (server.py, the
`for stage in _*_STAGES` runners). Two of those stages do blocking network I/O
whose cost the handler fix never touched:

  * session LOAD  (_autostart_session -> Session.start(sid) -> handler.read)
  * session SAVE  (_stage_session_save -> session.save() -> handler.write)

With a network session backend (Redis/Valkey/memcached/MongoDB) each is a
blocking `socket.recv`/`sendall` round-trip ON the loop, so even a perfectly
async route serialises every request through its session I/O.

These tests PROVE it the way ADR-0074 did — a real request through the REAL
`server.handle` dispatch, a real clock, real threads, and a real file-backed
session handler with a deliberate latency standing in for a slow backend (the
same instrument as ADR-0074's `time.sleep` route; it is a REAL handler doing
REAL file I/O plus a measured delay, not a mock of a backend's protocol).

They are RED on today's code (stages on the loop) and GREEN once the blocking
stages are offloaded with `asyncio.to_thread`, exactly as the handler was.
"""
import asyncio
import threading
import time

import pytest

import tina4_python.core.server as server
from tina4_python.core.request import Request
from tina4_python.core.middleware import Middleware
from tina4_python.core.router import Router, get as route_get
from tina4_python import session as session_mod
from tina4_python.session import Session, FileSessionHandler, session_cookie_name

DELAY = 0.3          # the latency each session read/write stands in for
N = 4                # concurrent requests for the serialization proof


class SlowFileSessionHandler(FileSessionHandler):
    """A REAL file-backed session handler with a deliberate per-op latency.

    read()/write() persist to a real file (the parent's behaviour) and then
    sleep DELAY to represent a slow network backend's round-trip. The sleep is
    a real blocking call - the instrument, not a mock - so a stage that runs it
    on the loop genuinely blocks the loop for DELAY, which is the thing measured.
    """

    def read(self, session_id):
        time.sleep(DELAY)
        return super().read(session_id)

    def write(self, session_id, data, ttl=0):
        time.sleep(DELAY)
        return super().write(session_id, data, ttl)


@pytest.fixture(autouse=True)
def _app(monkeypatch, tmp_path):
    Router.clear()
    Middleware.reset()
    # Inject the REAL slow file handler into the dispatch's own Session() calls.
    slow = SlowFileSessionHandler(str(tmp_path))
    monkeypatch.setattr(Session, "_resolve_handler", staticmethod(lambda: slow))

    @route_get("/sess")
    async def _probe(request, response):           # async route: the handler is NOT the blocker
        request.session.set("touched", "1")        # make the save stage persist (blocking write)
        return response("ok")

    yield
    Router.clear()
    Middleware.reset()


def _request():
    # A cookie makes autostart do a blocking READ; the route's write makes the
    # save stage do a blocking WRITE. Both land in the dispatch, on the loop.
    cookie = f"{session_cookie_name()}=abc123".encode()
    scope = {
        "type": "http", "method": "GET", "path": "/sess", "query_string": b"",
        "scheme": "http", "headers": [(b"cookie", cookie)], "client": ("127.0.0.1", 1),
    }
    return server.handle(Request.from_scope(scope, b""))


def test_session_io_does_not_stall_the_event_loop():
    """While one request's session read+write run, the loop must keep ticking.

    RED today: the session stages run on the loop, so the ticker is frozen for
    ~2*DELAY and records almost nothing. GREEN once they are offloaded.
    """
    ticks = []

    async def ticker():
        for _ in range(200):
            ticks.append(time.monotonic())
            await asyncio.sleep(0.01)

    async def drive():
        t = asyncio.ensure_future(ticker())
        await asyncio.sleep(0)          # let the ticker start
        await _request()
        t.cancel()

    asyncio.run(drive())

    assert len(ticks) > 20, (
        f"the loop ticked only {len(ticks)} times while one request did its "
        f"session read+write (~{2 * DELAY:.1f}s). The session stages ran ON the "
        "loop, so every other in-flight request was frozen with it."
    )


def test_concurrent_requests_do_not_serialize_on_session_io():
    """N concurrent requests must overlap their session I/O, not queue on it.

    Serial (today): N * 2 * DELAY. Concurrent (after offloading): ~2 * DELAY.
    The assertion sits well below the serial time so it is RED now, GREEN after,
    and the ratio it prints is the performance improvement.
    """
    async def drive():
        start = time.monotonic()
        await asyncio.gather(*(_request() for _ in range(N)))
        return time.monotonic() - start

    elapsed = asyncio.run(drive())
    serial = N * 2 * DELAY
    assert elapsed < serial * 0.6, (
        f"{N} concurrent requests took {elapsed:.2f}s; serial would be ~{serial:.2f}s "
        f"and fully concurrent ~{2 * DELAY:.2f}s. They serialised on session I/O "
        "running on the event loop."
    )
