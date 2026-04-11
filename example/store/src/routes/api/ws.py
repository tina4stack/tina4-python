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


@ws.route("/ws/chat")
async def live_chat(conn):
    """WebSocket handler for customer <-> admin live chat."""
    conn.join_room("chat_lobby")
    await conn.send_json({"type": "system", "message": "Connected to support chat"})

    # Notify admin users someone joined
    await conn.broadcast_to_room("chat_admin", json.dumps({
        "type": "system",
        "message": f"Customer {conn.id} joined chat",
        "client_id": conn.id,
    }), exclude_self=True)

    @conn.on_message
    async def on_message(message):
        try:
            data = json.loads(message)
            msg_type = data.get("type", "message")

            if msg_type == "join_admin":
                conn.join_room("chat_admin")
                conn.leave_room("chat_lobby")
                await conn.send_json({"type": "system", "message": "Joined as admin"})
                return

            if msg_type == "message":
                sender = data.get("sender", "Guest")
                text = data.get("text", "")
                is_admin = "chat_admin" in conn.rooms

                payload = json.dumps({
                    "type": "message",
                    "sender": sender,
                    "text": text,
                    "is_admin": is_admin,
                    "client_id": conn.id,
                })

                await conn.broadcast_to_room("chat_lobby", payload)
                await conn.broadcast_to_room("chat_admin", payload)

        except json.JSONDecodeError:
            await conn.send_json({"type": "error", "message": "Invalid JSON"})

    @conn.on_close
    async def on_close():
        await conn.broadcast_to_room("chat_admin", json.dumps({
            "type": "system",
            "message": f"Customer {conn.id} left chat",
            "client_id": conn.id,
        }))
