import json
import asyncio
from tina4_python.Router import get, post, noauth
from tina4_python.Websocket import Websocket
from src.app.chat_manager import connections, add_connection, remove_connection, broadcast


@get("/")
async def join_page(request, response):
    return response.render("pages/join.twig", {})


@noauth()
@post("/join")
async def do_join(request, response):
    username = request.body.get("username", "").strip()
    if not username:
        return response.render("pages/join.twig", {"error": "Username is required"})
    request.session.set("username", username)
    request.session.save()
    return response.redirect("/chat")


@get("/chat")
async def chat_room(request, response):
    username = request.session.get("username")
    if not username:
        return response.redirect("/")
    return response.render("pages/room.twig", {"username": username})


@get("/ws")
async def websocket_handler(request, response):
    ws = Websocket(request)
    conn = await ws.connection()
    if conn is None:
        return response("WebSocket upgrade failed", 400)

    username = None
    try:
        # First message is the username
        raw = conn.receive()
        data = json.loads(raw)
        username = data.get("username", "anonymous")

        add_connection(username, conn)
        await broadcast({"type": "system", "text": f"{username} joined the chat"})

        while True:
            raw = conn.receive()
            data = json.loads(raw)
            await broadcast({
                "type": "message",
                "username": username,
                "text": data.get("text", ""),
            })
    except Exception:
        pass
    finally:
        if username:
            remove_connection(username)
            await broadcast({"type": "system", "text": f"{username} left the chat"})
