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
        self._threads: dict[str, threading.Thread] = {}
        self._running = True
        logger.info("RedisBackplane connected to %s", self._url)

    def publish(self, channel: str, message: str) -> None:
        self._redis.publish(channel, message)

    def subscribe(self, channel: str, callback) -> None:
        self._pubsub.subscribe(**{channel: lambda raw: callback(raw["data"].decode() if isinstance(raw["data"], bytes) else raw["data"])})
        thread = self._pubsub.run_in_thread(sleep_time=0.01, daemon=True)
        self._threads[channel] = thread
        logger.info("RedisBackplane subscribed to channel '%s'", channel)

    def unsubscribe(self, channel: str) -> None:
        self._pubsub.unsubscribe(channel)
        thread = self._threads.pop(channel, None)
        if thread:
            thread.stop()
        logger.info("RedisBackplane unsubscribed from channel '%s'", channel)

    def close(self) -> None:
        self._running = False
        for thread in self._threads.values():
            thread.stop()
        self._threads.clear()
        self._pubsub.close()
        self._redis.close()
        logger.info("RedisBackplane closed")


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
        raise NotImplementedError(
            "NATS backplane is on the roadmap but not yet implemented."
        )
    elif backend == "":
        return None
    else:
        raise ValueError(f"Unknown TINA4_WS_BACKPLANE value: '{backend}'")
