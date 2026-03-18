import json
import asyncio

# In-memory store of active WebSocket connections: {username: connection}
connections = {}


def add_connection(username, conn):
    connections[username] = conn


def remove_connection(username):
    connections.pop(username, None)


async def broadcast(message_data, exclude=None):
    """Send a JSON message to all connected clients except the excluded one."""
    payload = json.dumps(message_data)
    disconnected = []
    for username, conn in connections.items():
        if username == exclude:
            continue
        try:
            await asyncio.to_thread(conn.send, payload)
        except Exception:
            disconnected.append(username)
    for username in disconnected:
        remove_connection(username)
