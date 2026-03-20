# Tina4 Constants — HTTP status codes and content types.
"""
Standard constants for use in route handlers across all Tina4 frameworks.

    from tina4_python import HTTP_OK, HTTP_CREATED, APPLICATION_JSON

    @get("/api/users")
    async def list_users(request, response):
        return response(users, HTTP_OK)
"""

# ── HTTP Status Codes ──

HTTP_OK = 200
HTTP_CREATED = 201
HTTP_ACCEPTED = 202
HTTP_NO_CONTENT = 204

HTTP_MOVED = 301
HTTP_REDIRECT = 302
HTTP_NOT_MODIFIED = 304

HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
HTTP_METHOD_NOT_ALLOWED = 405
HTTP_CONFLICT = 409
HTTP_GONE = 410
HTTP_UNPROCESSABLE = 422
HTTP_TOO_MANY = 429

HTTP_SERVER_ERROR = 500
HTTP_BAD_GATEWAY = 502
HTTP_UNAVAILABLE = 503

# ── Content Types ──

APPLICATION_JSON = "application/json"
APPLICATION_XML = "application/xml"
APPLICATION_FORM = "application/x-www-form-urlencoded"
APPLICATION_OCTET = "application/octet-stream"

TEXT_HTML = "text/html; charset=utf-8"
TEXT_PLAIN = "text/plain; charset=utf-8"
TEXT_CSV = "text/csv"
TEXT_XML = "text/xml"
