#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import os
import json
import inspect
from datetime import datetime, date
from types import ModuleType
from tina4_python import Constant
from tina4_python import DatabaseResult
from tina4_python.ORM import ORM
from tina4_python.Template import Template

headers = {}
content = ""
http_code = Constant.HTTP_OK
content_type = Constant.TEXT_HTML

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

    def __init__(self, content_in=None, http_code_in=None, content_type_in=None,
                 headers_in=None):
        global headers
        global content
        global http_code
        global content_type

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
            content_in = json.dumps({"error": "Cannot decode object of type " + str(type(content_in))})
            content_type = Constant.APPLICATION_JSON

        if content is not None and isinstance(content_in, str) and http_code_in == Constant.HTTP_OK:
            content_in = content + content_in

        self.headers = headers_in if headers_in is not None else headers
        self.content = content_in if content_in is not None else content
        self.http_code = http_code_in if http_code_in is not None else http_code
        self.content_type = content_type_in if content_type_in is not None else content_type
        headers = self.headers
        http_code = self.http_code
        content_type = self.content_type
        content = self.content

    @staticmethod
    def redirect(redirect_url, http_code_in=Constant.HTTP_REDIRECT):
        """
        Redirects a request to redirect_url
        :param http_code_in:
        :param redirect_url:
        :return:
        """
        global headers
        global content
        global http_code
        global content_type
        headers = {}
        http_code = http_code_in
        headers["Location"] = redirect_url
        content = "Redirecting..."
        content_type = Constant.TEXT_HTML
        return Response("Redirecting...", http_code, content_type, headers)


    @staticmethod
    def render(template_name, data=None):
        global content, content_type, http_code
        http_code = Constant.HTTP_OK
        content_type = Constant.TEXT_HTML

        return Response(Template.render(template_name, data=data), http_code, content_type)

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
        global content, content_type, http_code

        # Resolve full path and prevent directory traversal
        full_path = os.path.abspath(os.path.join(root_path, file_path.lstrip("/")))

        # Security: ensure the requested file is inside the root_path
        if not full_path.startswith(os.path.abspath(root_path)):
            http_code = Constant.HTTP_FORBIDDEN
            content_type = Constant.TEXT_PLAIN
            content = "403 - Forbidden"
            return Response(content, http_code, content_type)

        # Check if file exists
        if not os.path.isfile(full_path):
            http_code = Constant.HTTP_NOT_FOUND
            content_type = Constant.TEXT_PLAIN
            content = "404 - File Not Found"
            return Response(content, http_code, content_type)

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
            http_code = Constant.HTTP_BAD_REQUEST
            content_type = Constant.TEXT_PLAIN
            content = f"Error reading file: {str(e)}"
            return Response(content, http_code, content_type)

        http_code = Constant.HTTP_OK
        return Response(content, http_code, content_type)

    @staticmethod
    def add_header(key, value):
        """
        Adds a header for the response
        :param key:
        :param value:
        :return:
        """
        global headers
        headers[key] = value

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
