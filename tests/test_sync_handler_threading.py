"""A SYNC HANDLER MUST WORK, AND MUST NOT BLOCK THE EVENT LOOP.

Two defects, both measured before this file existed.

1. A PLAIN ``def`` HANDLER CRASHED. ``_invoke_handler`` awaited the handler
   unconditionally, so a sync one raised

       TypeError: object Response can't be used in 'await' expression

   which names neither the handler nor the rule it broke. Flask, Django and
   FastAPI all accept a sync view, so a plain ``def`` is the first thing a
   Python developer writes.

2. A BLOCKING HANDLER FROZE EVERY OTHER REQUEST. asyncio runs one loop, so a
   handler that blocks it stops the whole server for its duration. Measured on
   3.13.94 with ``time.sleep(10)`` in a route: a trivial route took 9.004s
   instead of milliseconds. PHP had the identical property and fixed it by
   forking per request; Python has threads, so it does not need to fork.

The fix is the one Starlette and FastAPI already use: run a ``def`` handler in
a thread and leave an ``async def`` handler on the loop. That makes the sync
path both WORK and stay off the loop, which closes both defects with one
change.

WHAT THIS DELIBERATELY DOES NOT CLAIM: an ``async def`` handler that blocks
still blocks. Nothing can rescue that inside one event loop, and the last test
here pins it so the limit is documented rather than discovered.

NO MOCKS: the real dispatcher, real handlers, a real clock, real threads.
"""
import asyncio
import threading
import time

import pytest

from tina4_python.core.request import Request
from tina4_python.core.response import Response
from tina4_python.core.server import _invoke_handler


def _request(path="/x"):
    request = Request()
    request.method = "GET"
    request.path = path
    return request


def _route(handler):
    return {"handler": handler}


# ── 1. a sync handler must be accepted at all ────────────────────────────────

def test_a_plain_def_handler_is_accepted():
    """The first thing a Python developer writes must not raise."""

    def handler(request, response):
        return response("sync ok")

    result = asyncio.run(_invoke_handler(_request(), Response(), _route(handler), {}))
    assert isinstance(result, Response), (
        "a plain def handler must be dispatched, not rejected. It used to raise "
        "TypeError: object Response can't be used in 'await' expression"
    )


def test_an_async_handler_still_works():
    """The control, asserting the handler's OWN result reached the caller.

    Asserting only ``isinstance(result, Response)`` was not enough, and a
    mutation proved it: route an async handler to a thread and
    ``asyncio.to_thread`` hands back a coroutine, ``_invoke_handler`` sees a
    non-Response and returns the response it was PASSED, which is still a
    Response. The test passed while the handler's return value was silently
    thrown away. Checking the content closes that hole.
    """

    async def handler(request, response):
        return response("async-marker")

    result = asyncio.run(_invoke_handler(_request(), Response(), _route(handler), {}))
    assert isinstance(result, Response)
    assert b"async-marker" in result.content, (
        "the async handler's response never reached the caller - it was awaited "
        "somewhere that discarded it, or never awaited at all"
    )


def test_a_sync_handler_result_also_reaches_the_caller():
    """The same check for the sync path, so neither side can regress silently."""

    def handler(request, response):
        return response("sync-marker")

    result = asyncio.run(_invoke_handler(_request(), Response(), _route(handler), {}))
    assert b"sync-marker" in result.content


# ── 2. a sync handler must not be ON the loop ────────────────────────────────

def test_a_sync_handler_runs_off_the_event_loop():
    """Proved by thread identity, not by timing.

    A timing assertion can pass on a fast machine for the wrong reason. The
    thread id cannot: if the handler reports the loop's own thread, it ran on
    the loop, full stop.
    """
    seen = {}

    def handler(request, response):
        seen["handler_thread"] = threading.get_ident()
        return response("ok")

    async def drive():
        seen["loop_thread"] = threading.get_ident()
        return await _invoke_handler(_request(), Response(), _route(handler), {})

    asyncio.run(drive())

    assert seen["handler_thread"] != seen["loop_thread"], (
        "the sync handler ran on the event loop thread, so anything blocking "
        "inside it freezes every other request"
    )


def test_a_blocking_sync_handler_does_not_stall_the_loop():
    """The defect, stated as elapsed time on the thing that must stay responsive.

    While the slow handler sleeps, the loop must keep running other work. The
    assertion is on the LOOP's progress, not on the slow handler, because the
    slow handler is allowed to be slow.
    """
    ticks = []

    def slow(request, response):
        time.sleep(1.0)
        return response("slow")

    async def ticker():
        # If the loop is free, this records many ticks during the 1s sleep.
        for _ in range(40):
            ticks.append(time.monotonic())
            await asyncio.sleep(0.02)

    async def drive():
        task = asyncio.ensure_future(ticker())
        await _invoke_handler(_request(), Response(), _route(slow), {})
        task.cancel()

    asyncio.run(drive())

    assert len(ticks) > 10, (
        f"the loop only ticked {len(ticks)} times while a sync handler slept 1s. "
        "It was blocked, so every other in-flight request was blocked with it."
    )


# ── 3. the limit, pinned honestly ────────────────────────────────────────────

def test_an_async_handler_that_blocks_still_blocks():
    """Not a bug to fix later. A statement of what asyncio is.

    An ``async def`` handler runs ON the loop by definition, so a blocking call
    inside one stops everything. Threading the sync path cannot help here, and
    pretending otherwise would be worse than saying it plainly. The fix for
    this case is to make the handler ``def``, or to await something.
    """
    ticks = []

    async def slow(request, response):
        time.sleep(0.5)          # blocking, inside a coroutine
        return response("slow")

    async def ticker():
        for _ in range(40):
            ticks.append(time.monotonic())
            await asyncio.sleep(0.01)

    async def drive():
        task = asyncio.ensure_future(ticker())
        await asyncio.sleep(0)   # let the ticker start
        await _invoke_handler(_request(), Response(), _route(slow), {})
        task.cancel()

    asyncio.run(drive())

    assert len(ticks) < 20, (
        f"the loop ticked {len(ticks)} times during a blocking async handler. "
        "If that is now possible the documented limit has changed and this "
        "test, and the docs that repeat it, need rewriting."
    )
