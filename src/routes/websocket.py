import json
from collections import defaultdict
from tina4_python import get,secured
from tina4_python.Websocket import Websocket

subscribers = defaultdict(set)

@get("/ws/chat")
@secured()
async def chat_ws(request, response):
    ws = await Websocket(request).connection()
    try:
        while True:
            data = await ws.receive()
            Debug.info('WEBSOCKET', data, ws)
            # actions can be publish, subscribe, unsubscribe
            # data = {"topic": "Simone", "action": "publish", "data": {}}
            try:
                json_data = json.loads(data)
                # establish a session in subscribers so we can publish
                if json_data["action"] == "subscribe":
                    subscribers[json_data["topic"]].add(ws)
                if json_data["action"] == "unsubscribe":
                    subscribers[json_data["topic"]].discard(ws)
                    if not subscribers[json_data["topic"]]:
                        del subscribers[json_data["topic"]]
                if json_data["action"] == "publish":
                    for subscriber in list(subscribers[json_data["topic"]]):
                        try:
                            await subscriber.send(json.dumps(json_data["data"]))
                        except Exception:
                            # Remove stale/closed subscriber
                            subscribers[json_data["topic"]].discard(subscriber)
            except Exception as e:
                await ws.send(f"Echo: {data} {e}")
    finally:
        # Clean up all subscriptions for this ws on disconnect
        for topic in list(subscribers.keys()):
            subscribers[topic].discard(ws)
            if not subscribers[topic]:
                del subscribers[topic]
        if ws is not None:
            await ws.close()

    pass