#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
TINA4_LOG_INFO = "INFO"
TINA4_LOG_WARNING = "WARN"
TINA4_LOG_DEBUG = "DEBUG"
TINA4_LOG_ERROR = "ERROR"
TINA4_LOG_ALL = "ALL"

TINA4_GET = "GET"
TINA4_POST = "POST"
TINA4_ANY = "ANY"
TINA4_PATCH = "PATCH"
TINA4_PUT = "PUT"
TINA4_DELETE = "DELETE"
TINA4_OPTIONS = "OPTIONS"

HTTP_OK = 200
HTTP_CREATED = 201
HTTP_NO_CONTENT = 204
HTTP_PARTIAL_CONTENT = 206
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404

LOOKUP_HTTP_CODE = {HTTP_OK: "OK", HTTP_CREATED: "Created", HTTP_BAD_REQUEST: "Bad Request",
                    HTTP_PARTIAL_CONTENT: "Partial Content", HTTP_UNAUTHORIZED: "Unauthorized",
                    HTTP_FORBIDDEN: "Forbidden", HTTP_NOT_FOUND: "Not Found", HTTP_NO_CONTENT: "No Content"}

TEXT_HTML = "text/html"
TEXT_CSS = "text/css"
TEXT_PLAIN = "text/plain"
APPLICATION_JSON = "application/json"
APPLICATION_XML = "application/xml"
