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

    def __init__(self, body=None, params=None, headers=None, request=None, raw=None):
        self.body = body if body is not None else None
        self.params = params if params is not None else {}
        self.headers = headers if headers is not None else {}
        self.request = request if request is not None else {}
        self.cookies = {}
        self.cookies = {}
        self.session = None
        self.files = {}
        self.raw = raw if raw is not None else None
