#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""HTTP response builder for Tina4 route handlers.

The ``Response`` class is passed as the ``response`` callback in every
route handler. Calling it constructs a properly formatted HTTP response
with the correct status code, content type, and headers.

Supported response body types:
    - ``str`` — returned as-is (HTML or plain text)
    - ``dict`` / ``list`` — JSON-serialised automatically
    - ``DatabaseResult`` — converted via ``to_paginate()``
    - ``ORM`` instances — converted via ``to_dict()``
    - Twig template strings — rendered through the template engine
    - File paths — served as binary downloads with correct MIME type

The module also provides ``add_header()`` for setting custom response
headers from anywhere in a route handler via a coroutine-safe context
variable.

Example::

    @get("/hello")
    async def hello(request, response):
        return response({"message": "Hello!"}, 200, "application/json")
"""

__all__ = ["Response"]

import os
import json
import inspect
import contextvars
from datetime import datetime, date
from types import ModuleType
from tina4_python import Constant
from tina4_python import DatabaseResult
from tina4_python.ORM import ORM
from tina4_python.Template import Template

# Per-coroutine header accumulation for add_header() calls before Response creation
_pending_headers = contextvars.ContextVar('_pending_headers', default=None)


class Response:

    @staticmethod
    def convert_special_types(obj):
        if isinstance(obj, dict):
            return {k: Response.convert_special_types(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [Response.convert_special_types(i) for i in obj]
        elif isinstance(obj, (date, datetime)):
            return obj.isoformat()
        else:
            return obj

    @staticmethod
    def reset_context():
        """Reset per-request response state. Called by Router before each request."""
        _pending_headers.set({})

    def __init__(self, content_in=None, http_code_in=None, content_type_in=None,
                 headers_in=None):
        content_type = content_type_in if content_type_in is not None else Constant.TEXT_HTML

        if http_code_in is None:
            http_code_in = Constant.HTTP_OK

        if (not isinstance(content_in, bool) and not isinstance(content_in, object)
                and not isinstance(content_in, bytes)
                and not isinstance(content_in, str)
                and not isinstance(content_in, list) and inspect.isclass(type(content_in))):
            content_in = dict(content_in)

        if isinstance(content_in, ORM):
            content_type = Constant.APPLICATION_JSON
            content_in = content_in.to_json()

        # check if database result
        if type(content_in) is DatabaseResult.DatabaseResult:
            content_type = Constant.APPLICATION_JSON
            content_in = content_in.to_json()

        # convert the dictionary or list into JSON
        if not isinstance(content_in, bool) and type(content_in) is dict or type(content_in) is list:
            content_in = json.dumps(Response.convert_special_types(content_in))
            content_type = Constant.APPLICATION_JSON

        if isinstance(content_in, bool):
            if content_in:
                content_in = "True"
            else:
                content_in = "False"

        if isinstance(content_in, ModuleType):
            from tina4_python import Messages
            content_in = json.dumps({"error": Messages.MSG_CANNOT_DECODE.format(type=str(type(content_in)))})
            content_type = Constant.APPLICATION_JSON

        # Merge any headers added via add_header() before this Response was created
        pending = _pending_headers.get()
        merged_headers = {}
        if pending:
            merged_headers.update(pending)
        if headers_in is not None:
            merged_headers.update(headers_in)

        self.headers = merged_headers
        self.content = content_in if content_in is not None else ""
        self.http_code = http_code_in
        self.content_type = content_type

    @staticmethod
    def redirect(redirect_url, http_code_in=Constant.HTTP_REDIRECT):
        """
        Redirects a request to redirect_url
        :param http_code_in:
        :param redirect_url:
        :return:
        """
        # Strip CR/LF to prevent HTTP response splitting (header injection)
        safe_url = redirect_url.replace("\r", "").replace("\n", "")
        headers = {"Location": safe_url}
        from tina4_python import Messages
        return Response(Messages.MSG_REDIRECTING, http_code_in, Constant.TEXT_HTML, headers)

    @staticmethod
    def render(template_name, data=None):
        return Response(Template.render(template_name, data=data), Constant.HTTP_OK, Constant.TEXT_HTML)

    @staticmethod
    def file(file_path: str, root_path: str = "src/public"):
        """
        Serve a static file from the file system.

        Args:
            file_path (str): The requested file path (e.g., "images/logo.png", "css/style.css")
            root_path (str): Base directory to serve files from (defaults to src/public)

        Returns:
            Response: A properly configured Response object with file content and correct MIME type
        """
        # Resolve full path and prevent directory traversal
        full_path = os.path.abspath(os.path.join(root_path, file_path.lstrip("/")))

        # Security: ensure the requested file is inside the root_path
        from tina4_python import Messages
        if not full_path.startswith(os.path.abspath(root_path)):
            return Response(Messages.MSG_FORBIDDEN, Constant.HTTP_FORBIDDEN, Constant.TEXT_PLAIN)

        # Check if file exists
        if not os.path.isfile(full_path):
            return Response(Messages.MSG_FILE_NOT_FOUND, Constant.HTTP_NOT_FOUND, Constant.TEXT_PLAIN)

        # Determine MIME type
        extension = os.path.splitext(file_path)[1].lower()
        mime_map = {
            ".html": Constant.TEXT_HTML,
            ".css":  Constant.TEXT_CSS,
            ".js":   Constant.TEXT_JAVASCRIPT,
            ".json": Constant.APPLICATION_JSON,
            ".png":  "image/png",
            ".jpg":  "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif":  "image/gif",
            ".svg":  "image/svg+xml",
            ".ico":  "image/x-icon",
            ".woff": "font/woff",
            ".woff2":"font/woff2",
            ".ttf":  "font/ttf",
            ".pdf":  "application/pdf",
            ".txt":  Constant.TEXT_PLAIN,
        }
        content_type = mime_map.get(extension, "application/octet-stream")

        # Read file content (binary for non-text, text for text)
        try:
            if content_type.startswith("text/") or content_type in ["application/json", "image/svg+xml"]:
                with open(full_path, "r", encoding="utf-8") as f:
                    content = f.read()
            else:
                with open(full_path, "rb") as f:
                    content = f.read()
        except Exception as e:
            return Response(Messages.MSG_FILE_READ_ERROR.format(error=str(e)), Constant.HTTP_BAD_REQUEST, Constant.TEXT_PLAIN)

        return Response(content, Constant.HTTP_OK, content_type)

    @staticmethod
    def add_header(key, value):
        """
        Adds a header for the response (concurrency-safe via contextvars).
        CR/LF characters are stripped from both key and value to prevent
        HTTP response splitting.
        :param key:
        :param value:
        :return:
        """
        # Sanitise to prevent header injection
        safe_key = str(key).replace("\r", "").replace("\n", "")
        safe_value = str(value).replace("\r", "").replace("\n", "")
        h = _pending_headers.get()
        if h is None:
            h = {}
            _pending_headers.set(h)
        h[safe_key] = safe_value

    @staticmethod
    def wsdl(wsdl_instance):
        """
        Sets the response for a WSDL/SOAP handler.

        This method handles WSDL and SOAP responses by calling the handle method of the provided
        WSDL instance, setting the content type to 'text/xml', and updating the response content
        and status code accordingly.

        Args:
            wsdl_instance: Instance of a WSDL subclass (e.g., CIS(request)).

        Returns:
            Self (the Response object) with updated content, headers, and status.
        """
        xml_content = wsdl_instance.handle()

        return Response(xml_content, Constant.HTTP_OK, Constant.APPLICATION_XML)
