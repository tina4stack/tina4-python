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


class Response:
    """
    response object for router
    :param content
    :param http_code
    :param content_type
    """

    def __init__(self, content, http_code=Constant.HTTP_OK, content_type=Constant.TEXT_HTML):
        if content is None:
            content = ""
        # try to make content into a dictionary
        elif not isinstance(content, bool) and not isinstance(content, object) and not isinstance(content, bytes) and not isinstance(content, str) and not isinstance(content, list) and inspect.isclass(type(content)):
            content = dict(content)

        #check if database result
        if type(content) is DatabaseResult.DatabaseResult:
            content_type = Constant.APPLICATION_JSON
            content = content.to_json()

        # convert the dictionary or list into JSON
        if not isinstance(content, bool) and type(content) is dict or type(content) is list:
            content = json.dumps(content)
            content_type = Constant.APPLICATION_JSON

        if isinstance(content, bool):
            if content:
                content = "True"
            else:
                content = "False"

        if isinstance(content, ModuleType):
            content = json.dumps({"error": "Cannot decode object of type "+str(type(content))})
            content_type = Constant.APPLICATION_JSON

        self.content = content
        self.http_code = http_code
        self.content_type = content_type