"""Test WebSocket server and room management — demonstrates: WebSocketServer creation,
route registration, WebSocketManager room operations.

Note: These tests exercise the server/manager logic directly without opening real sockets.
"""
import pytest
from tina4_python.websocket import WebSocketServer, WebSocketManager, WebSocketConnection


class FakeWriter:
    """Minimal writer mock for WebSocketConnection construction."""

    def get_extra_info(self, key):
        return ("127.0.0.1", 9999) if key == "peername" else None

    def write(self, data):
        pass

    async def drain(self):
        pass

    def close(self):
        pass


class TestWebSocketServerCreation:
    def test_create_server_defaults(self):
        ws = WebSocketServer()
        assert ws.host == "0.0.0.0"
        assert ws.port == 7146
        assert ws.manager is not None

    def test_create_server_custom_port(self):
        ws = WebSocketServer(host="localhost", port=9000)
        assert ws.host == "localhost"
        assert ws.port == 9000

    def test_route_registration(self):
        ws = WebSocketServer()

        @ws.route("/ws/orders")
        async def handler(conn):
            pass

        assert "/ws/orders" in ws._handlers
        assert ws._handlers["/ws/orders"]["handler"] is handler


class TestWebSocketManager:
    def _make_connection(self, path="/ws/test"):
        conn = WebSocketConnection(
            reader=None, writer=FakeWriter(), path=path,
        )
        return conn

    def test_add_and_count(self):
        mgr = WebSocketManager()
        conn = self._make_connection()
        mgr.add(conn)
        assert mgr.count() == 1

    def test_remove_connection(self):
        mgr = WebSocketManager()
        conn = self._make_connection()
        mgr.add(conn)
        mgr.remove(conn)
        assert mgr.count() == 0

    def test_get_by_path(self):
        mgr = WebSocketManager()
        c1 = self._make_connection("/ws/orders")
        c2 = self._make_connection("/ws/chat")
        mgr.add(c1)
        mgr.add(c2)
        orders = mgr.get_by_path("/ws/orders")
        assert len(orders) == 1
        assert orders[0].id == c1.id

    def test_count_by_path(self):
        mgr = WebSocketManager()
        mgr.add(self._make_connection("/ws/orders"))
        mgr.add(self._make_connection("/ws/orders"))
        mgr.add(self._make_connection("/ws/chat"))
        assert mgr.count_by_path("/ws/orders") == 2
        assert mgr.count_by_path("/ws/chat") == 1


class TestWebSocketRooms:
    def _make_managed_connection(self, mgr, path="/ws/test"):
        conn = WebSocketConnection(
            reader=None, writer=FakeWriter(), path=path,
        )
        mgr.add(conn)
        return conn

    def test_join_room(self):
        mgr = WebSocketManager()
        conn = self._make_managed_connection(mgr)
        conn.join_room("order_42")
        assert "order_42" in conn.rooms
        assert mgr.room_count("order_42") == 1

    def test_leave_room(self):
        mgr = WebSocketManager()
        conn = self._make_managed_connection(mgr)
        conn.join_room("order_42")
        conn.leave_room("order_42")
        assert "order_42" not in conn.rooms
        assert mgr.room_count("order_42") == 0

    def test_multiple_connections_in_room(self):
        mgr = WebSocketManager()
        c1 = self._make_managed_connection(mgr)
        c2 = self._make_managed_connection(mgr)
        c1.join_room("lobby")
        c2.join_room("lobby")
        assert mgr.room_count("lobby") == 2

        conns = mgr.get_room_connections("lobby")
        ids = {c.id for c in conns}
        assert c1.id in ids
        assert c2.id in ids

    def test_remove_connection_clears_rooms(self):
        mgr = WebSocketManager()
        conn = self._make_managed_connection(mgr)
        conn.join_room("room_a")
        conn.join_room("room_b")
        mgr.remove(conn)
        assert mgr.room_count("room_a") == 0
        assert mgr.room_count("room_b") == 0

    def test_room_count_empty(self):
        mgr = WebSocketManager()
        assert mgr.room_count("nonexistent") == 0
