#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501

"""
Global constants used throughout the Tina4-Python framework.

These constants provide consistent values for:
- Logging levels
- HTTP methods
- HTTP status codes and their human-readable names
- Common MIME content types

They are intentionally simple strings/integers to allow direct comparison
and use in decorators, routing, and response handling.
"""

# ----------------------------------------------------------------------
# Logging Levels
# ----------------------------------------------------------------------
# Used with Debug() to control output verbosity.
# Set TINA4_DEBUG_LEVEL environment variable to one of these values.
TINA4_LOG_INFO    = "INFO"   #: Informational messages
TINA4_LOG_WARNING = "WARN"   #: Non-critical warnings
TINA4_LOG_DEBUG   = "DEBUG"   #: Detailed diagnostic information
TINA4_LOG_ERROR   = "ERROR"   #: Critical errors
TINA4_LOG_ALL     = "ALL"   #: Show all log levels (most verbose)

# ----------------------------------------------------------------------
# HTTP Request Methods
# ----------------------------------------------------------------------
# Used by routing decorators: @get, @post, @any, etc.
TINA4_GET     = "GET"     #: HTTP GET request
TINA4_POST    = "POST"    #: HTTP POST request
TINA4_ANY     = "ANY"     #: Match any HTTP method
TINA4_PATCH   = "PATCH"   #: HTTP PATCH request (partial update)
TINA4_PUT     = "PUT"     #: HTTP PUT request (replace)
TINA4_DELETE  = "DELETE"  #: HTTP DELETE request
TINA4_OPTIONS = "OPTIONS" #: HTTP OPTIONS request (preflight)

# ----------------------------------------------------------------------
# HTTP Status Codes
# ----------------------------------------------------------------------
# Standard HTTP response status codes.
# Use with response() or manually set on Response objects.
HTTP_OK              = 200  #: Request succeeded
HTTP_CREATED         = 201  #: Resource successfully created
HTTP_ACCEPTED        = 202  #: Request accepted for processing
HTTP_NO_CONTENT      = 204  #: Success with no response body
HTTP_PARTIAL_CONTENT = 206  #: Partial content returned (range requests)
HTTP_REDIRECT_MOVED  = 301  #: Permanently moved
HTTP_REDIRECT        = 302  #: Temporary redirect (found)
HTTP_REDIRECT_OTHER  = 303  #: Temporary redirect (other)
HTTP_BAD_REQUEST     = 400  #: Client sent invalid request
HTTP_UNAUTHORIZED    = 401  #: Authentication required
HTTP_FORBIDDEN       = 403  #: Authenticated but access denied
HTTP_NOT_FOUND       = 404  #: Resource not found
HTTP_SERVER_ERROR    = 500  #: Internal server error

# ----------------------------------------------------------------------
# Human-readable HTTP status code lookup
# ----------------------------------------------------------------------
#: Mapping of status code → official reason phrase (RFC 9110)
LOOKUP_HTTP_CODE = {
    HTTP_OK:              "OK",
    HTTP_CREATED:         "Created",
    HTTP_ACCEPTED:        "Accepted",
    HTTP_NO_CONTENT:      "No Content",
    HTTP_PARTIAL_CONTENT: "Partial Content",
    HTTP_REDIRECT:        "Redirect",
    HTTP_REDIRECT_MOVED:  "Redirect Moved",
    HTTP_REDIRECT_OTHER:  "Redirect Other",
    HTTP_BAD_REQUEST:     "Bad Request",
    HTTP_UNAUTHORIZED:    "Unauthorized",
    HTTP_FORBIDDEN:       "Forbidden",
    HTTP_NOT_FOUND:       "Not Found",
    HTTP_SERVER_ERROR:    "Internal Server Error",
}

# ----------------------------------------------------------------------
# Common MIME / Content-Type values
# ----------------------------------------------------------------------
# Used in response headers or when setting Content-Type manually.
TEXT_HTML         = "text/html"          #: HTML documents and templates
TEXT_CSS          = "text/css"           #: Cascading Style Sheets
TEXT_PLAIN        = "text/plain"         #: Plain text files
TEXT_JAVASCRIPT   = "text/javascript"    #: Javascript files
APPLICATION_JSON  = "application/json"   #: JSON API responses
APPLICATION_XML   = "application/xml"    #: XML data (RSS, SOAP, etc.)

# Example usage:
#   return response(data, HTTP_OK, {"Content-Type": APPLICATION_JSON})
