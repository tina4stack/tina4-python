#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
class Request:
    """
    Request object to store parameters, headers, etc.
    """

    def __init__(self, body=None, params=None, headers=None, request=None, raw_data=None, raw_request=None, raw_content=None):
        self.body = body if body is not None else None
        self.params = params if params is not None else {}
        self.headers = headers if headers is not None else {}
        self.request = request if request is not None else {}
        self.cookies = {}
        self.cookies = {}
        self.session = None
        self.files = {}
        self.raw_data = raw_data if raw_data is not None else None
        self.raw_request = raw_request if raw_request is not None else None
        self.raw_content = raw_content if raw_content is not None else None

