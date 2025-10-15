#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import asyncio
import base64
import json
import os
import re
import mimetypes
from urllib.parse import unquote_plus
from urllib.parse import urlparse, parse_qsl
import tina4_python
from tina4_python import Constant
from tina4_python.Constant import HTTP_REDIRECT, HTTP_OK, HTTP_SERVER_ERROR
from tina4_python.Session import Session
from tina4_python.Router import Router
from tina4_python.Debug import Debug
from tina4_python.Template import Template


def is_int(v):
    try:
        int(v)
    except ValueError:
        return False
    return True


class Webserver:
    async def get_content_length(self):
        # get the content length
        if "content-length" in self.lowercase_headers:
            return int(self.lowercase_headers["content-length"])

        return 0

    async def get_content_body(self, content_length):
        # get lines of content where at the end of the request
        content = self.content_raw

        if "content-type" in self.lowercase_headers:
            if self.lowercase_headers["content-type"] == "application/x-www-form-urlencoded":
                body = {}
                content_data = content.decode("utf-8").split("&")
                for data in content_data:
                    data = data.split("=", 1)
                    body[data[0]] = unquote_plus(data[1])
                return body, {}
            elif self.lowercase_headers["content-type"] == "application/json":
                # print("CONTENT", content, self.request)
                try:
                    return json.loads(content), {}
                except Exception:
                    return content.decode("utf-8"), {}

            elif self.lowercase_headers["content-type"] == "text/plain":
                return content.decode("utf-8"), {}
            else:
                content_data = self.lowercase_headers["content-type"].split("; ")

                if content_data[0] == "multipart/form-data":
                    boundary = content_data[1].split("=")[1] + "\r\n"
                    content = b"\r\n" + content
                    data_array = content.split(str.encode(boundary))
                    body = {}
                    files = {}
                    for data in data_array:
                        data = data.split(b"\r\n\r\n")
                        data_names = data[0].decode("utf-8").split("; ")

                        if data_names[0] == "Content-Disposition: form-data":
                            key_name = data_names[1].split("=")[1][1:-1]

                            if len(data_names) == 2:
                                data_value = data[1].split(b"\r\n")[0]
                                body[key_name] = unquote_plus(data_value.decode("utf-8"))
                            else:
                                data_value = data[1].split(b"\r\n--")[0]
                                file_data = data_names[2].split("\r\n")
                                file_name = "Unknown"
                                content_type = "Unknown"
                                meta_data = {}
                                for file_info in file_data:
                                    file_info1 = file_info.split("=")
                                    if len(file_info1) > 1:
                                        meta_data[file_info1[0]] = file_info1[1].strip()
                                    file_info2 = file_info.split(":")
                                    if len(file_info2) > 1:
                                        meta_data[file_info2[0]] = file_info2[1].strip()

                                if "filename" in meta_data:
                                    file_name = meta_data["filename"][1:-1]
                                if "Content-Type" in meta_data:
                                    content_type = meta_data["Content-Type"]

                                if key_name in body:
                                    body[key_name] = [body[key_name]]
                                    body[key_name].append({"file_name": file_name, "content_type": content_type,"content": base64.encodebytes(data_value).decode("utf-8").replace(
                                        "\n", "")})
                                else:
                                    body[key_name] = {"file_name": file_name, "content_type": content_type,"content": base64.encodebytes(data_value).decode("utf-8").replace(
                                        "\n", "")}

                                if key_name in files:
                                    files[key_name] = [files[key_name]]
                                    files[key_name].append({"file_name": file_name, "content_type": content_type,"content": base64.encodebytes(data_value).decode("utf-8").replace(
                                        "\n", "")})
                                else:
                                    files[key_name] = {"file_name": file_name, "content_type": content_type,"content": base64.encodebytes(data_value).decode("utf-8").replace(
                                        "\n", "")}

                    return body, files

        return {"data": base64.encodebytes(content).decode("utf-8").replace("\n", "")}, {}

    async def send_basic_headers(self, headers):
        self.send_header("Access-Control-Allow-Origin", "*", headers)
        self.send_header("Access-Control-Allow-Headers",
                         "Origin, X-Requested-With, Content-Type, Accept, Authorization", headers)
        self.send_header("Access-Control-Allow-Credentials", "True", headers)
        # self.send_header("Content-Length", str(len(response.content)), headers)
        self.send_header("Connection", "Keep-Alive", headers)
        self.send_header("Keep-Alive", "timeout=5, max=30", headers)

    async def get_response(self, method, transport, asgi_response=False):
        """
        Get response
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

            if asgi_response:
                return None, headers
            else:
                return headers

        params = dict(parse_qsl(urlparse(self.path).query, keep_blank_values=True))

        new_params = {}
        new_params.update(params)

        for key, value in params.items():
            regex = r"(\w+)"
            matches = re.finditer(regex, key)

            var_names = []
            for matchNum, match in enumerate(matches, start=0):
                if is_int(match.group()):
                    var_names.append(int(match.group()))
                else:
                    var_names.append(match.group())

            if len(var_names) > 1:
                start_var = new_params
                counter = 0
                while counter < len(var_names):
                    var_name = var_names[counter]
                    if not is_int(var_name):
                        if isinstance(start_var, dict) and var_name in start_var:
                            start_var = start_var[var_name]
                        else:
                            if counter + 1 < len(var_names) and is_int(var_names[counter + 1]):
                                if var_name not in start_var:
                                    start_var[var_name] = []
                                start_var = start_var[var_name]
                            else:
                                if counter - 1 > 0 and is_int(var_names[counter - 1]):
                                    index = int(var_names[counter - 1])
                                    new_value = {var_name: value}
                                    if index in range(len(start_var)):
                                        start_var[index].update(new_value)
                                    else:
                                        while len(start_var) < index:
                                            start_var.append({})
                                        start_var.append(new_value)
                                    start_var = start_var[index]
                                else:
                                    if isinstance(start_var, dict):
                                        if counter + 1 == len(var_names):
                                            start_var[var_name] = value
                                        else:
                                            start_var[var_name] = {}
                                        start_var = start_var[var_name]

                    counter += 1

        params.update(new_params)

        content_length = await self.get_content_length()
        if method != Constant.TINA4_GET:
            body, files = await self.get_content_body(content_length)
        else:
            body = None
            files = None

        request = {"params": params, "body": body, "files": files, "raw_data": self.request, "url": self.path, "session": self.session,
                   "headers": self.lowercase_headers, "raw_request": self.request_raw, "raw_content": self.content_raw,
                   "transport": transport, "asgi_response": asgi_response}

        tina4_python.tina4_current_request = request

        response = await self.router_handler.resolve(method, self.path, request, self.lowercase_headers, self.session)

        if HTTP_REDIRECT != response.http_code:
            self.send_header("Content-Type", response.content_type, headers)
            await self.send_basic_headers(headers)

            if os.getenv("TINA4_SESSION", "PY_SESS") in self.cookies:
                self.send_header("Set-Cookie",
                                 os.getenv("TINA4_SESSION", "PY_SESS") + '=' + self.cookies[
                                     os.getenv("TINA4_SESSION", "PY_SESS")], headers)

        # add the custom headers from the response
        for response_header in response.headers:
            self.send_header(response_header, response.headers[response_header], headers)

        if asgi_response:
            return response, headers

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
            response_code] + "\r\n"
        for header in response_headers:
            headers += header + "\r\n"
        headers += "\r\n"

        return headers.encode()

    async def run_server(self):
        self.server = await asyncio.start_server(self.handle_client, self.host_name, self.port)
        await self.server.serve_forever()

    async def get_data(self, reader):
        try:
            raw_data = await reader.readuntil(b"\r\n\r\n")
        except Exception:
            raw_data = await reader.read(128)

        protocol = raw_data.decode("utf-8").split("\r\n", 1)[0]
        header_array = raw_data.decode("utf-8").split("\r\n\r\n")[0]
        header_array = header_array.split("\r\n")
        headers = {}
        for header in header_array:
            split = header.split(":", 1)
            if len(split) == 2:
                headers[split[0]] = split[1].strip()

        lowercase_headers = {k.lower(): v for k, v in headers.items()}
        content = ""
        content_data = b''
        if "content-length" in lowercase_headers:
            content_length = int(lowercase_headers["content-length"])
            count = 0
            read_size = 64
            content_data = b''
            while len(content_data) < content_length:
                read = await reader.read(read_size)
                count += len(read)
                content_data += read
                raw_data += read
                # print('COUNT', count, len(read))
                if len(read) < read_size and len(content_data) == content_length:
                    break
            try:
                content = content_data.decode("utf-8")
            except Exception:  # probably binary or multipart form?
                content = content_data

        return protocol, headers, lowercase_headers, content, raw_data, content_data

    async def handle_client(self, reader, writer):
        try:
            # Get the client request
            protocol, headers_list, lowercase_headers, request, request_raw, content_raw = await self.get_data(reader)
            # Strange blank request ?
            if protocol == '':
                return
            # Decode the request
            self.request_raw = request_raw
            self.content_raw = content_raw
            self.request = request
            self.headers = headers_list
            self.lowercase_headers = lowercase_headers

            protocol = protocol.split(" ")
            # print(protocol, headers_list)
            self.method = protocol[0]
            self.path = protocol[1]


            method_list = [Constant.TINA4_GET, Constant.TINA4_DELETE, Constant.TINA4_PUT, Constant.TINA4_ANY,
                           Constant.TINA4_POST, Constant.TINA4_PATCH, Constant.TINA4_OPTIONS]

            contains_method = [ele for ele in method_list if (ele in self.method)]

            request_handled = False
            # return static content asap
            if self.method == "GET" and "sec-websocket-key" not in self.lowercase_headers:
                # split URL and extract query string
                url = Router.clean_url(self.path)
                url_parts = url.split('?')
                url = url_parts[0]

                # Serve statics
                static_file = tina4_python.root_path + os.sep + "src" + os.sep + "public" + url.replace("/", os.sep)
                Debug.info("Attempting to serve static file: " + static_file)
                if os.path.isfile(static_file):
                    mime_type = mimetypes.guess_type(url)[0]
                    with open(static_file, 'rb') as file:
                        headers = []
                        self.send_header("Content-Type", mime_type, headers)
                        await self.send_basic_headers(headers)
                        content = file.read()
                        headers = await self.get_headers(headers, self.response_protocol, HTTP_OK)
                        writer.write(headers + content)
                        await writer.drain()
                        if writer is not None:
                            writer.close()
                        request_handled = True

            if not request_handled:
                # parse cookies
                cookie_list = {}
                content = ""
                if "cookie" in self.lowercase_headers:
                    cookie_list_temp = self.lowercase_headers["cookie"].split(";")
                    for cookie_value in cookie_list_temp:
                        cookie = cookie_value.split("=", 1)
                        cookie_list[cookie[0].strip()] = cookie[1].strip()

                self.cookies = cookie_list

                # initialize the session
                self.session = Session(os.getenv("TINA4_SESSION", "PY_SESS"),
                                       os.getenv("TINA4_SESSION_FOLDER", tina4_python.root_path + os.sep + "sessions"),
                                       os.getenv("TINA4_SESSION_HANDLER", "SessionFileHandler")
                                       )

                if os.getenv("TINA4_SESSION", "PY_SESS") in self.cookies:
                    self.session.load(self.cookies[os.getenv("TINA4_SESSION", "PY_SESS")])
                else:
                    self.cookies[os.getenv("TINA4_SESSION", "PY_SESS")] = self.session.start()

                if "sec-websocket-key" not in self.lowercase_headers:
                    try:
                        if self.method != "" and contains_method:
                            content = await (self.get_response(self.method, writer))
                        if content != "":
                            writer.write(content)
                            await writer.drain()
                        writer.close()
                    except BrokenPipeError as e:
                        Debug.warning("Socket connection broken: " + str(e))
                        # socket got terminated
                        pass
                else:
                    # for sockets
                    await (self.get_response(self.method, writer))


        except Exception as e:
            error_string = tina4_python.global_exception_handler(e)
            headers = []
            await self.send_basic_headers(headers)
            headers = await self.get_headers(headers, self.response_protocol, HTTP_SERVER_ERROR)
            url = Router.clean_url(self.path)

            content_type = "text/html"
            if "content-type" in self.lowercase_headers:
                content_type = self.lowercase_headers["content-type"].lower()

            if content_type == "application/json":
                html = json.dumps({"error": "500 - Internal Server Error",
                                   "data": {"server": {"url": url}, "error_message": error_string}})
            else:
                html = Template.render_twig_template("errors/500.twig",
                                                     {"server": {"url": url}, "error_message": error_string})

            writer.write(headers + html.encode())
            await writer.drain()
            writer.close()

    def __init__(self, host_name, port):
        self.content_raw = None
        self.session = Session
        self.cookies = {}
        self.method = None
        self.response_protocol = "HTTP/1.1"
        self.headers = None
        self.lowercase_headers = None
        self.request = None
        self.request_raw = None
        self.path = None
        self.server_socket = None
        self.host_name = host_name
        self.port = port
        self.router_handler = None
        self.running = False
        self.server = None

    async def serve_forever(self):
        await self.run_server()

    def server_close(self):
        self.running = False
        self.server_socket.close()
