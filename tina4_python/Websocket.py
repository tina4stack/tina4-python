#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import asyncio
import base64
import hashlib
from tina4_python.Debug import Debug

class ASGIConnection:
    def __init__(self, receive, send):
        self.receive_func = receive
        self.send_func = send

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            msg = await self.receive()
            if msg is None:
                raise StopAsyncIteration
            return msg
        except Exception:
            raise StopAsyncIteration

    async def receive(self):
        msg = await self.receive_func()
        if msg['type'] == 'websocket.disconnect':
            raise ConnectionError("Connection closed")
        return msg.get('text') or msg.get('bytes')

    async def send(self, message):
        if isinstance(message, str):
            await self.send_func({'type': 'websocket.send', 'text': message})
        else:
            await self.send_func({'type': 'websocket.send', 'bytes': message})

    async def close(self):
        try:
            await self.send_func({'type': 'websocket.close'})
        except Exception as e:
            Debug.error("Error closing WebSocket connection:", str(e))

class Connection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            msg = await self.receive()
            if msg is None:
                raise StopAsyncIteration
            return msg
        except Exception:
            raise StopAsyncIteration

    async def receive(self):
        try:
            header = await self.reader.read(2)
            if len(header) < 2:
                raise ConnectionError("Connection closed")
            first = header[0]
            fin = (first & 0x80) >> 7
            opcode = first & 0x0F
            second = header[1]
            mask = (second & 0x80) >> 7
            payload_len = second & 0x7F
            if payload_len == 126:
                ext = await self.reader.read(2)
                payload_len = int.from_bytes(ext, 'big')
            elif payload_len == 127:
                ext = await self.reader.read(8)
                payload_len = int.from_bytes(ext, 'big')
            masking_key = None
            if mask:
                masking_key = await self.reader.read(4)
            payload = b''
            if payload_len > 0:
                payload = await self.reader.readexactly(payload_len)
            if mask and masking_key:
                payload = bytes(b ^ masking_key[i % 4] for i, b in enumerate(payload))
            if opcode == 1:
                return payload.decode('utf-8')
            elif opcode == 2:
                return payload
            elif opcode == 8:
                raise ConnectionError("Connection closed by client")
            elif opcode == 9:
                await self._send_frame(payload, opcode=10)
                return await self.receive()
            else:
                # Ignore unknown opcode, recurse
                return await self.receive()
        except Exception as e:
            Debug.error("Error receiving WebSocket message:", str(e))
            raise

    async def send(self, message):
        if isinstance(message, str):
            await self._send_frame(message.encode('utf-8'), opcode=1)
        else:
            await self._send_frame(message, opcode=2)

    async def _send_frame(self, payload: bytes, opcode: int = 1):
        length = len(payload)
        header = bytes([0x80 | opcode])
        if length <= 125:
            header += bytes([length])
        elif length <= 65535:
            header += bytes([126])
            header += length.to_bytes(2, 'big')
        else:
            header += bytes([127])
            header += length.to_bytes(8, 'big')
        self.writer.write(header + payload)
        await self.writer.drain()

    async def close(self):
        try:
            await self._send_frame(b'', opcode=8)
            self.writer.close()
            await self.writer.wait_closed()
        except Exception as e:
            Debug.error("Error closing WebSocket connection:", str(e))

class Websocket:
    """
    Websocket class which implements manual handshake and frame handling
    """
    def __init__(self, request):
        self.request = request

    async def connection(self):
        """
        Performs handshake and returns a websocket connection
        :return:
        """
        try:
            if self.request.get("asgi_response"):
                await self.request["send"]({
                    'type': 'websocket.accept'
                })
                return ASGIConnection(self.request["receive"], self.request["send"])
            else:
                headers = self.request["headers"]
                if "sec-websocket-key" not in headers:
                    raise ValueError("Not a WebSocket upgrade request")
                key = headers["sec-websocket-key"]
                magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                accept = base64.b64encode(hashlib.sha1((key + magic).encode()).digest()).decode()
                writer = self.request["transport"]
                writer.write(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n".encode())
                await writer.drain()
                return Connection(self.request["reader"], writer)
        except Exception as e:
            Debug.error("Could not establish a WebSocket connection:", str(e))
            return None