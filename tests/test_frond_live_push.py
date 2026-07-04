"""Frond push_live() - re-render a live fragment and broadcast it over WebSocket.

Real Frond render + real WebSocketManager + real WebSocketConnection + real
RFC-6455 frame encoding. The only redirection is the socket transport: frame
bytes land in an in-memory buffer instead of a kernel socket (I/O redirection,
the same pattern the repo's own websocket tests use) - no collaborator is mocked.
"""
import asyncio

from tina4_python.frond import Frond, push_live
from tina4_python.websocket import WebSocketConnection


class _CaptureWriter:
    """A writer whose bytes land in a buffer instead of a socket."""
    def __init__(self):
        self.sent = bytearray()

    def write(self, data):
        self.sent.extend(data)

    def get_extra_info(self, key, default=None):
        return ("127.0.0.1", 0) if key == "peername" else default

    def is_closing(self):
        return False

    async def drain(self):
        pass

    def close(self):
        pass


async def test_push_live_returns_rendered_html():
    Frond.clear_registry()
    Frond().render_string('{% live "score" ws "/ws/score" %}<b>{{ n }}</b>{% endlive %}', {"n": 0})
    html = await push_live("score", {"n": 5})
    assert "<b>5</b>" in html


async def test_push_live_unknown_name_returns_none():
    Frond.clear_registry()
    assert await push_live("ghost", {}) is None


async def test_push_live_broadcasts_fragment_over_declared_ws_path():
    Frond.clear_registry()
    Frond().render_string(
        '{% live "chat" ws "/ws/chat" %}{% for m in msgs %}<p>{{ m }}</p>{% endfor %}{% endlive %}',
        {"msgs": []})

    from tina4_python.core.server import _ws_manager
    writer = _CaptureWriter()
    conn = WebSocketConnection(asyncio.StreamReader(), writer, "/ws/chat")
    _ws_manager.add(conn)
    try:
        html = await push_live("chat", {"msgs": ["hello world"]})
        assert "<p>hello world</p>" in html
        raw = bytes(writer.sent)
        assert raw, "expected a WebSocket frame to be written to the connection"
        assert b"hello world" in raw           # the re-rendered fragment reached the socket
        assert b'"type": "live"' in raw or b'"type":"live"' in raw   # envelope
        assert b'"name": "chat"' in raw or b'"name":"chat"' in raw
    finally:
        _ws_manager.remove(conn)


async def test_push_live_does_not_reach_other_paths():
    Frond.clear_registry()
    Frond().render_string('{% live "chat" ws "/ws/chat" %}<i>{{ x }}</i>{% endlive %}', {"x": 0})

    from tina4_python.core.server import _ws_manager
    other = _CaptureWriter()
    other_conn = WebSocketConnection(asyncio.StreamReader(), other, "/ws/other")
    _ws_manager.add(other_conn)
    try:
        await push_live("chat", {"x": 9})
        assert bytes(other.sent) == b"", "a connection on a different path must not receive the push"
    finally:
        _ws_manager.remove(other_conn)
