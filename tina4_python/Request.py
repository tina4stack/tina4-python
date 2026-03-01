#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501


class Request:
    """Per-request object holding all request data. Instantiated fresh for each incoming request."""

    def __init__(self):
        self.request = None
        self.body = None
        self.params = {}
        self.headers = {}
        self.cookies = {}
        self.url = None
        self.session = None
        self.files = {}
        self.raw_request = None
        self.raw_data = None
        self.raw_content = None
        self.asgi_scope = None
        self.asgi_reader = None
        self.asgi_writer = None
        self.asgi_response = None
