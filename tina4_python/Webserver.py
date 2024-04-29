#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import asyncio
import json
import os
from urllib.parse import unquote
from urllib.parse import urlparse, parse_qsl
import tina4_python
from tina4_python.Debug import Debug
from tina4_python import Constant
from tina4_python.Session import Session


class Webserver:
    async def get_content_length(self):
        # get the content length
        if "Content-length" in self.headers != -1:
            return int(self.headers["Content-length"])

        if "Content-Length" in self.headers != -1:
            return int(self.headers["Content-Length"])

        return 0

    async def get_content_body(self, content_length):
        # get lines of content where at the end of the request
        content = self.request_raw[-content_length:]
        try:
            Debug("JSON", content, Constant.TINA4_LOG_DEBUG)
            content = json.loads(content)
        except Exception:
            # check for form body
            if content != "":
                body = {}
                variables = content.split("&", 1)
                for variable in variables:
                    variable = variable.split("=", 1)
                    body[variable[0]] = unquote(variable[1])
                return body

        return content

    async def get_response(self, method):
        """

        :param method: GET, POST, PATCH, DELETE, PUT
        :return:
        """
        headers = []
        if method == "OPTIONS":
            self.send_header("Access-Control-Allow-Origin", "*", headers)
            self.send_header("Access-Control-Allow-Headers",
                             "Origin, X-Requested-With, Content-Type, Accept, Authorization", headers)
            self.send_header("Access-Control-Allow-Credentials", "True", headers)

            headers = await self.get_headers(headers, self.response_protocol, Constant.HTTP_OK)
            return headers

        params = dict(parse_qsl(urlparse(self.path).query, keep_blank_values=True))

        content_length = await self.get_content_length()
        if method != Constant.TINA4_GET:
            body = await self.get_content_body(content_length)
        else:
            body = None

        request = {"params": params, "body": body, "raw": self.request, "headers": self.headers}

        tina4_python.tina4_current_request = request

        response = await self.router_handler.resolve(method, self.path, request, self.headers, self.session)

        self.send_header("Access-Control-Allow-Origin", "*", headers)
        self.send_header("Access-Control-Allow-Headers",
                         "Origin, X-Requested-With, Content-Type, Accept, Authorization", headers)
        self.send_header("Access-Control-Allow-Credentials", "True", headers)
        self.send_header("Content-Type", response.content_type, headers)
        self.send_header("Content-Length", str(len(response.content)), headers)
        self.send_header("Connection", "Keep-Alive", headers)
        self.send_header("Keep-Alive", "timeout=5, max=30", headers)

        if os.getenv("TINA4_SESSION", "PY_SESS") in self.cookies:
            self.send_header("Set-Cookie",
                             os.getenv("TINA4_SESSION", "PY_SESS") + '=' + self.cookies[
                                 os.getenv("TINA4_SESSION", "PY_SESS")], headers)

        headers = await self.get_headers(headers, self.response_protocol, response.http_code)

        if isinstance(response.content, str):
            return headers + response.content.encode()
        else:
            return headers + response.content

    @staticmethod
    def send_header(header, value, headers):
        headers.append(header + ": " + value)

    @staticmethod
    async def get_headers(response_headers, response_protocol, response_code):
        headers = response_protocol + " " + str(response_code) + " " + Constant.LOOKUP_HTTP_CODE[
            response_code] + "\n"
        for header in response_headers:
            headers += header + "\n"
        headers += "\n"

        return headers.encode()

    async def run_server(self):
        server = await asyncio.start_server(self.handle_client, self.host_name, self.port)
        async with server:
            await server.serve_forever()

    async def get_data(self, reader):
        # https://stackoverflow.com/questions/17667903/python-socket-receive-large-amount-of-data
        chunks = []
        found_length = False
        content_length = 0
        header_offset = 0
        while True:
            data = (await reader.read(2048)).decode("utf-8")
            chunks.append(data)

            if not found_length:
                i = "".join(chunks).find('Content-Length:')
                e = "".join(chunks).find('\n', i)
                if not i == -1 and not e == -1:
                    value = "".join(chunks)[i:e].replace("\r", "").split(":")
                    if len(value) > 1:
                        content_length = int(value[1].strip())
                        found_length = True

            if header_offset == 0:
                i = "".join(chunks).replace("\r", "").find("\n\n")
                if not i == -1:
                    header_offset = i

            if not found_length and (data.find('GET') != -1 or data.find('OPTIONS') != -1) and len(
                    data) < header_offset:
                content_length = len("".join(chunks))

            if len("".join(chunks)) >= content_length + header_offset or len("".join(chunks)) == header_offset or len(
                    "".join(chunks)) == 0:
                break
        return "".join(chunks)

    async def handle_client(self, reader, writer):
        # Get the client request
        request = await self.get_data(reader)

        # Decode the request
        self.request_raw = request

        self.request = request.replace("\r", "")

        self.path = request.split(" ")

        if len(self.path) > 1:
            self.path = self.request.split(" ")[1]

        self.method = self.request.split(" ")[0]

        body_parts = self.request.split("\n\n")

        self.headers = body_parts[0].split("\n")

        # parse headers into a dictionary for more efficient use
        headers_list = {}
        for header in self.headers:
            split = header.split(":", 1)
            if len(split) == 2:
                headers_list[split[0]] = split[1].strip()
        self.headers = headers_list

        # parse cookies
        cookie_list = {}
        if "Cookie" in self.headers:
            cookie_list_temp = self.headers["Cookie"].split(";")
            for cookie_value in cookie_list_temp:
                cookie = cookie_value.split("=", 1)
                cookie_list[cookie[0].strip()] = cookie[1].strip()
            self.cookies = cookie_list

        # initialize the session
        self.session = Session(os.getenv("TINA4_SESSION", "PY_SESS"),
                               os.getenv("TINA4_SESSION_FOLDER", tina4_python.root_path + os.sep + "sessions"))

        if os.getenv("TINA4_SESSION", "PY_SESS") in self.cookies:
            self.session.load(self.cookies[os.getenv("TINA4_SESSION", "PY_SESS")])
        else:
            self.cookies[os.getenv("TINA4_SESSION", "PY_SESS")] = self.session.start()

        method_list = [Constant.TINA4_GET, Constant.TINA4_DELETE, Constant.TINA4_PUT, Constant.TINA4_ANY,
                       Constant.TINA4_POST, Constant.TINA4_PATCH, Constant.TINA4_OPTIONS]

        contains_method = [ele for ele in method_list if (ele in self.method)]

        if self.method != "" and contains_method:
            content = await (self.get_response(self.method))
            writer.write(content)
            await writer.drain()

        writer.close()

    def __init__(self, host_name, port):
        self.session = Session
        self.cookies = {}
        self.method = None
        self.response_protocol = "HTTP/1.1"
        self.headers = None
        self.request = None
        self.request_raw = None
        self.path = None
        self.server_socket = None
        self.host_name = host_name
        self.port = port
        self.router_handler = None
        self.running = False

    async def serve_forever(self):
        await self.run_server()

    def server_close(self):
        self.running = False
        self.server_socket.close()
