# WebSocket

Tina4 includes a native RFC 6455 WebSocket server built on asyncio. No external libraries -- it handles the HTTP upgrade handshake, frame protocol (text, binary, ping/pong, close), masking, fragmented messages, and connection management.

## Basic Server

```python
from tina4_python.websocket import WebSocketServer

ws = WebSocketServer(host="0.0.0.0", port=7146)

@ws.route("/chat")
async def on_message(ws_conn, message):
    print(f"Received: {message}")
    await ws_conn.send(f"Echo: {message}")

# Start the server
import asyncio
asyncio.run(ws.start())
```

## Connection Lifecycle

```python
@ws.on_connect("/chat")
async def on_connect(ws_conn):
    print(f"Client {ws_conn.id} connected from {ws_conn.ip}")
    await ws_conn.send("Welcome to the chat!")

@ws.route("/chat")
async def on_message(ws_conn, message):
    # Handle incoming messages
    await ws_conn.send(f"You said: {message}")

@ws.on_disconnect("/chat")
async def on_disconnect(ws_conn):
    print(f"Client {ws_conn.id} disconnected")
```

## Broadcasting

Send messages to all connected clients on a path.

```python
@ws.route("/notifications")
async def on_notification(ws_conn, message):
    # Broadcast to all clients on /notifications
    await ws_conn.broadcast(message)

    # Broadcast but exclude the sender
    await ws_conn.broadcast(message, exclude_self=True)

    # Broadcast to a different path
    await ws_conn.broadcast_to("/admin", f"User said: {message}")
```

## WebSocket Connection API

Each connection (`WebSocketConnection`) provides:

```python
@ws.route("/chat")
async def handler(ws_conn, message):
    # Properties
    ws_conn.id            # Unique connection ID (8-char UUID)
    ws_conn.ip            # Client IP address
    ws_conn.path          # Connection path ("/chat")
    ws_conn.headers       # HTTP upgrade headers
    ws_conn.params        # Query string parameters
    ws_conn.connected_at  # Connection timestamp
    ws_conn.closed        # Boolean — is connection closed?

    # Send text
    await ws_conn.send("Hello!")

    # Send binary
    await ws_conn.send(b"\x00\x01\x02")

    # Send JSON
    await ws_conn.send_json({"type": "update", "data": {"count": 42}})

    # Ping
    await ws_conn.ping()

    # Close with code and reason
    await ws_conn.close(code=1000, reason="Done")
```

## Connection Manager

The `WebSocketManager` tracks all active connections.

```python
from tina4_python.websocket import WebSocketManager

manager = ws.manager  # Accessed from the server

# Count connections
total = manager.count()
chat_count = manager.count_by_path("/chat")

# Get connections by path
connections = manager.get_by_path("/chat")

# Broadcast to a path
await manager.broadcast("/chat", "Server announcement!")

# Broadcast to all connections
await manager.broadcast_all("Global message")

# Force disconnect
await manager.disconnect(ws_conn.id)
await manager.disconnect_all("/chat")
```

## Per-Path Routing

Different paths can have different handlers, enabling multiple WebSocket services on one server.

```python
ws = WebSocketServer(port=7146)

@ws.route("/chat")
async def chat_handler(conn, msg):
    await conn.broadcast(f"{conn.id}: {msg}")

@ws.route("/notifications")
async def notification_handler(conn, msg):
    # Process notification subscriptions
    await conn.send_json({"subscribed": True})

@ws.route("/live-data")
async def live_data_handler(conn, msg):
    # Stream real-time data
    import json
    request = json.loads(msg)
    data = fetch_live_data(request["metric"])
    await conn.send_json(data)
```

## Chat Room Example

```python
import json
from tina4_python.websocket import WebSocketServer

ws = WebSocketServer(port=7146)
usernames = {}

@ws.on_connect("/chat")
async def joined(conn):
    usernames[conn.id] = f"User-{conn.id}"
    await conn.broadcast(
        json.dumps({"type": "system", "text": f"{usernames[conn.id]} joined"}),
        exclude_self=True
    )

@ws.route("/chat")
async def chat(conn, msg):
    data = json.loads(msg)

    if data.get("type") == "set_name":
        old = usernames[conn.id]
        usernames[conn.id] = data["name"]
        await conn.broadcast(
            json.dumps({"type": "system", "text": f"{old} is now {data['name']}"}),
        )
    else:
        await conn.broadcast(
            json.dumps({"type": "message", "from": usernames[conn.id], "text": data["text"]}),
        )

@ws.on_disconnect("/chat")
async def left(conn):
    name = usernames.pop(conn.id, conn.id)
    await conn.broadcast(
        json.dumps({"type": "system", "text": f"{name} left"}),
    )
```

## Client-Side JavaScript

```javascript
const ws = new WebSocket("ws://localhost:7146/chat");

ws.onopen = () => {
    ws.send(JSON.stringify({type: "set_name", name: "Alice"}));
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log(data);
};

ws.onclose = () => {
    console.log("Disconnected");
};
```

## Configuration

```bash
# .env
TINA4_WS_MAX_FRAME_SIZE=1048576  # Max frame size in bytes (default: 1MB)
```

## Tips

- WebSocket handlers must be `async` functions.
- Use `send_json()` for structured data instead of manually calling `json.dumps()`.
- The connection manager auto-cleans disconnected clients.
- Use per-path routing to separate concerns (chat, notifications, live data).
- Run the WebSocket server on a different port from the HTTP server.
