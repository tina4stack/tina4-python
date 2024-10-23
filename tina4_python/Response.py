#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import json
import inspect
from types import ModuleType
from tina4_python import Constant
from tina4_python import DatabaseResult
from tina4_python.Debug import Debug

headers = {}
content = ""
http_code = Constant.HTTP_OK
content_type = Constant.TEXT_HTML


class Response:
    def __init__(self, content_in=None, http_code_in=None, content_type_in=None,
                 headers_in=None):
        global headers
        global content
        global http_code
        global content_type

        if (not isinstance(content_in, bool) and not isinstance(content_in, object)
                and not isinstance(content_in, bytes)
                and not isinstance(content_in, str)
                and not isinstance(content_in, list) and inspect.isclass(type(content_in))):
            content_in = dict(content_in)

        # check if database result
        if type(content_in) is DatabaseResult.DatabaseResult:
            content_type = Constant.APPLICATION_JSON
            content_in = content_in.to_json()

        # convert the dictionary or list into JSON
        if not isinstance(content_in, bool) and type(content_in) is dict or type(content_in) is list:
            content_in = json.dumps(content_in)
            content_type = Constant.APPLICATION_JSON

        if isinstance(content_in, bool):
            if content_in:
                content_in = "True"
            else:
                content_in = "False"

        if isinstance(content_in, ModuleType):
            content_in = json.dumps({"error": "Cannot decode object of type " + str(type(content_in))})
            content_type = Constant.APPLICATION_JSON

        if content is not None and isinstance(content_in, str):
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
    def redirect(redirect_url):
        """
        Redirects a request to redirect_url
        :param redirect_url:
        :return:
        """
        global headers
        global content
        global http_code
        global content_type
        headers = {}
        http_code = Constant.HTTP_REDIRECT
        headers["Location"] = redirect_url
        content = ""
        content_type = Constant.TEXT_HTML
        return Response("", http_code, content_type, headers)

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
