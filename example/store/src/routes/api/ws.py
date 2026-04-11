import json
from tina4_python.websocket import WebSocketServer

ws = WebSocketServer()


@ws.route("/ws/orders")
async def order_tracking(conn):
    """WebSocket handler for real-time order tracking."""
    await conn.send_json({"type": "connected", "message": "Order tracking ready"})

    @conn.on_message
    async def on_message(message):
        try:
            data = json.loads(message)
            if data.get("action") == "track":
                order_id = data.get("order_id")
                room = f"order_{order_id}"
                conn.join_room(room)
                await conn.send_json({
                    "type": "tracking",
                    "order_id": order_id,
                    "message": "Tracking started",
                })
        except json.JSONDecodeError:
            await conn.send_json({"type": "error", "message": "Invalid JSON"})

    @conn.on_close
    async def on_close():
        pass
