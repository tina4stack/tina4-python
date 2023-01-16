#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
from tina4_python.Constant import LOOKUP_HTTP_CODE
from tina4_python.Debug import Debug
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qsl
import socket
import asyncio


class Webserver:
    async def get_response(self, method):
        params = dict(parse_qsl(urlparse(self.path).query, keep_blank_values=True))
        request = {"params": params, "raw": self.request}
        response = await self.router_handler.resolve(method, self.path, request, self.headers)
        print("Response", response)
        headers = []
        self.send_header("Content-type", response["content_type"], headers)
        headers = await self.get_headers(headers, self.response_protocol, response["http_code"])
        if type(response["content"]) == str:
            return headers + response["content"].encode()
        else:
            return headers + response["content"]

    @staticmethod
    def send_header(header, value, headers):
        print("Header", header, value)
        headers.append(header + ": " + value)

    @staticmethod
    async def get_headers(response_headers, response_protocol, response_code):
        headers = response_protocol + " " + str(response_code) + " " + LOOKUP_HTTP_CODE[
            response_code] + "\n"
        for header in response_headers:
            headers += header + "\n\n"
        print("Headers", headers)
        return headers.encode()

    async def run_server(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host_name, self.port))
        self.server_socket.listen(8)
        self.server_socket.setblocking(False)
        self.running = True

        loop = asyncio.get_event_loop()
        while True:
            client, _ = await loop.sock_accept(self.server_socket)
            loop.create_task(self.handle_client(client))

    async def handle_client(self, client):
        loop = asyncio.get_event_loop()
        request = None

        # Get the client request
        request = (await loop.sock_recv(client, 1024)).decode('utf8')
        # Decode the request

        self.request = request.strip()
        self.path = request.split(" ")[1].strip("\r")
        self.method = request.split(" ")[0].strip("\r")

        self.headers = request.split("\n")
        response = await self.get_response(self.method)
        await loop.sock_sendall(client, response)
        client.close()

    def __init__(self, host_name, port):
        self.method = None
        self.response_protocol = "HTTP/1.1"
        self.headers = None
        self.response_headers = []
        self.request = None
        self.path = None
        self.server_socket = None
        self.host_name = host_name
        self.port = port
        self.router_handler = None
        self.running = False

    def serve_forever(self):
        asyncio.run(self.run_server())

    def server_close(self):
        self.running = False
        self.server_socket.close()
