#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""HTTP request object for Tina4 route handlers.

The ``Request`` class encapsulates all data from an incoming HTTP request
including URL, headers, body, cookies, session, query params, and uploaded
files. A fresh instance is created for each request by the web server.
"""

__all__ = ["Request"]


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
