"""
WebSocket Backplane Abstraction for Tina4 Python.

Enables broadcasting WebSocket messages across multiple server instances
using a shared pub/sub channel (e.g. Redis). Without a backplane configured,
broadcast() only reaches connections on the local process.

Configuration via environment variables:
    TINA4_WS_BACKPLANE     — Backend type: "redis", "nats", or "" (default: none)
    TINA4_WS_BACKPLANE_URL — Connection string (default: redis://localhost:6379)

Usage:
    backplane = create_backplane()
    if backplane:
        backplane.subscribe("chat", lambda msg: relay_to_local(msg))
        backplane.publish("chat", '{"user": "A", "text": "hello"}')
"""

import os
import threading
import logging

logger = logging.getLogger(__name__)


def _redacted(url: str) -> str:
    """The backplane URL as it may appear in a log: the password (redis://:pw@host,
    nats://user:pw@host) replaced by ``***`` via the framework's one redaction
    primitive. Imported lazily so the backplane does not pull in the database
    package at import time."""
    from tina4_python.database.database_url import redact_url
    return redact_url(url)


class WebSocketBackplane:
    """Base backplane interface for scaling WebSocket broadcast across instances.

    Subclasses implement publish/subscribe over a shared message bus so that
    every server instance receives every broadcast, not just the originator.
    """

    def publish(self, channel: str, message: str) -> None:
        """Publish a message to all instances listening on *channel*."""
        raise NotImplementedError

    def subscribe(self, channel: str, callback) -> None:
        """Subscribe to *channel*. *callback(message: str)* is invoked for
        each incoming message. Runs in a background thread."""
        raise NotImplementedError

    def unsubscribe(self, channel: str) -> None:
        """Stop listening on *channel*."""
        raise NotImplementedError

    def close(self) -> None:
        """Tear down connections and background threads."""
        raise NotImplementedError


class RedisBackplane(WebSocketBackplane):
    """Redis pub/sub backplane.

    Requires the ``redis`` package (``pip install redis``). The import is
    deferred so the rest of Tina4 works fine without it installed — an error
    is raised only when this class is actually instantiated.
    """

    def __init__(self, url: str | None = None):
        try:
            import redis
        except ImportError:
            raise ImportError(
                "The 'redis' package is required for RedisBackplane. "
                "Install it with: pip install redis"
            )

        self._url = url or os.environ.get(
            "TINA4_WS_BACKPLANE_URL", "redis://localhost:6379"
        )
        self._redis = redis.Redis.from_url(self._url)
        self._pubsub = self._redis.pubsub()
        # ONE listener thread for the one pub/sub connection. A thread per
        # subscribe() had several threads reading the same socket, and close()
        # closed that socket under a thread still reading it (an unhandled
        # "Bad file descriptor" in the listener, seen once the tests ran on a
        # real Redis instead of an in-memory stand-in).
        self._listener = None
        self._running = True
        logger.info("RedisBackplane connected to %s", _redacted(self._url))

    def publish(self, channel: str, message: str) -> None:
        self._redis.publish(channel, message)

    def subscribe(self, channel: str, callback) -> None:
        self._pubsub.subscribe(**{channel: lambda raw: callback(raw["data"].decode() if isinstance(raw["data"], bytes) else raw["data"])})
        if self._listener is None:
            self._listener = self._pubsub.run_in_thread(sleep_time=0.01, daemon=True)
        logger.info("RedisBackplane subscribed to channel '%s'", channel)

    def unsubscribe(self, channel: str) -> None:
        self._pubsub.unsubscribe(channel)
        logger.info("RedisBackplane unsubscribed from channel '%s'", channel)

    def close(self) -> None:
        self._running = False
        if self._listener is not None:
            # Stop AND wait: the listener must be off the socket before the
            # socket is closed.
            self._listener.stop()
            self._listener.join(timeout=5)
            self._listener = None
        self._pubsub.close()
        self._redis.close()
        logger.info("RedisBackplane closed")


class NATSBackplane(WebSocketBackplane):
    """NATS pub/sub backplane.

    Requires the ``nats-py`` package (``pip install nats-py``). The import is
    deferred so the rest of Tina4 works fine without it installed.

    NATS is async-native, so we run an asyncio event loop in a background
    thread for the subscription listener.
    """

    def __init__(self, url: str | None = None):
        try:
            import nats  # noqa: F401
        except ImportError:
            raise ImportError(
                "The 'nats-py' package is required for NATSBackplane. "
                "Install it with: pip install nats-py"
            )

        self._url = url or os.environ.get(
            "TINA4_WS_BACKPLANE_URL", "nats://localhost:4222"
        )
        self._nc = None
        self._subs: dict[str, object] = {}
        self._loop = None
        self._thread = None
        self._running = True
        self._connect()
        logger.info("NATSBackplane connected to %s", _redacted(self._url))

    def _connect(self):
        """Connect to NATS in a background event loop."""
        import asyncio
        import nats

        self._loop = asyncio.new_event_loop()

        async def _do_connect():
            self._nc = await nats.connect(self._url)

        self._loop.run_until_complete(_do_connect())

        # Run the event loop in a background thread for subscriptions
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True
        )
        self._thread.start()

    def publish(self, channel: str, message: str) -> None:
        import asyncio

        async def _pub():
            await self._nc.publish(channel, message.encode())

        asyncio.run_coroutine_threadsafe(_pub(), self._loop).result(timeout=5)

    def subscribe(self, channel: str, callback) -> None:
        import asyncio

        async def _sub():
            async def handler(msg):
                callback(msg.data.decode())

            sub = await self._nc.subscribe(channel, cb=handler)
            self._subs[channel] = sub

        asyncio.run_coroutine_threadsafe(_sub(), self._loop).result(timeout=5)
        logger.info("NATSBackplane subscribed to channel '%s'", channel)

    def unsubscribe(self, channel: str) -> None:
        import asyncio

        sub = self._subs.pop(channel, None)
        if sub:
            asyncio.run_coroutine_threadsafe(
                sub.unsubscribe(), self._loop
            ).result(timeout=5)
        logger.info("NATSBackplane unsubscribed from channel '%s'", channel)

    def close(self) -> None:
        import asyncio

        self._running = False
        if self._nc:
            asyncio.run_coroutine_threadsafe(
                self._nc.close(), self._loop
            ).result(timeout=5)
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=2)
        self._subs.clear()
        logger.info("NATSBackplane closed")


def create_backplane(url: str | None = None) -> WebSocketBackplane | None:
    """Factory that reads TINA4_WS_BACKPLANE and returns the appropriate
    backplane instance, or *None* if no backplane is configured.

    This keeps backplane usage entirely optional — callers simply check
    ``if backplane:`` before publishing.
    """
    backend = os.environ.get("TINA4_WS_BACKPLANE", "").strip().lower()

    if backend == "redis":
        return RedisBackplane(url=url)
    elif backend == "nats":
        return NATSBackplane(url=url)
    elif backend == "":
        return None
    else:
        raise ValueError(f"Unknown TINA4_WS_BACKPLANE value: '{backend}'")
