# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""THE WEBSOCKET BACKPLANE PUBLISH MUST NOT BLOCK THE EVENT LOOP.

The Redis backplane's LISTENER already runs in its own thread
(RedisBackplane.subscribe -> pubsub.run_in_thread). The PUBLISH side does not:
`WebSocketManager.broadcast*` (async, on the loop) calls `_publish`, which calls
the synchronous `redis.publish` inline. So every broadcast - a WS send, a WebRTC
signalling relay (broadcast_to_room), a chat fan-out - makes a blocking socket
round-trip ON the loop, freezing every other connection for its duration.

Proven the ADR-0074 way: a real WebSocketManager, a real clock and threads, and
a real backplane object whose `publish` carries a measured latency (the sleep is
the instrument, not a mock of Redis). No local connections, so the broadcast is
purely the publish. RED before the offload, GREEN after.
"""
import asyncio
import time

from tina4_python.websocket import WebSocketManager

DELAY = 0.3
N = 4


class SlowBackplane:
    """A real backplane whose publish blocks for DELAY (stands in for a slow
    Redis round-trip). subscribe is a no-op; the test only broadcasts."""

    def publish(self, channel, message):
        time.sleep(DELAY)

    def subscribe(self, channel, callback):
        pass

    def close(self):
        pass


def _manager():
    mgr = WebSocketManager()
    mgr._backplane_started = True       # skip the real wiring in _ensure_backplane
    mgr._backplane = SlowBackplane()
    return mgr


def test_backplane_publish_does_not_stall_the_event_loop():
    """While one broadcast's publish runs, the loop must keep ticking."""
    mgr = _manager()
    ticks = []

    async def ticker():
        for _ in range(200):
            ticks.append(time.monotonic())
            await asyncio.sleep(0.01)

    async def drive():
        t = asyncio.ensure_future(ticker())
        await asyncio.sleep(0)
        await mgr.broadcast_all("hello")
        t.cancel()

    asyncio.run(drive())

    assert len(ticks) > 15, (
        f"the loop ticked only {len(ticks)} times during one broadcast's "
        f"{DELAY}s publish. The backplane publish ran ON the loop, so every "
        "connection was frozen with it."
    )


def test_concurrent_broadcasts_do_not_serialize_on_the_publish():
    """N concurrent broadcasts must overlap their publishes, not queue on them.

    Serial (today): N * DELAY. Concurrent (after offload): ~DELAY.
    """
    mgr = _manager()

    async def drive():
        start = time.monotonic()
        await asyncio.gather(*(mgr.broadcast_all(f"m{i}") for i in range(N)))
        return time.monotonic() - start

    elapsed = asyncio.run(drive())
    serial = N * DELAY
    assert elapsed < serial * 0.6, (
        f"{N} concurrent broadcasts took {elapsed:.2f}s; serial would be ~{serial:.2f}s "
        f"and concurrent ~{DELAY:.2f}s. They serialised on the backplane publish."
    )
