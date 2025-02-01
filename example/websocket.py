import asyncio
from websockets.asyncio.server import serve

async def echo(websocket):
    async for message in websocket:
        await websocket.send(message)

async def main():
    server = await serve(echo, "localhost", 8765)
    await server.serve_forever()

asyncio.run(main())
