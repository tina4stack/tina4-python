# Tina4 Request — Parsed HTTP request.
"""
Clean request object with parsed body, params, headers, and cookies.
"""
import ipaddress
import json
import os
from urllib.parse import parse_qs, unquote

# Maximum upload size in bytes (default 10 MB). Override via TINA4_MAX_UPLOAD_SIZE env var.
TINA4_MAX_UPLOAD_SIZE = int(os.environ.get("TINA4_MAX_UPLOAD_SIZE", 10_485_760))


class PayloadTooLarge(Exception):
    """Raised when request body exceeds TINA4_MAX_UPLOAD_SIZE."""
    pass


class CaseInsensitiveDict(dict):
    """Dict subclass for HTTP headers — string keys are case-insensitive.

    HTTP header field-names are case-insensitive per RFC 7230 §3.2.
    With this class, ``request.headers["Content-Type"]``,
    ``request.headers.get("content-type")``, and
    ``request.headers.get("CONTENT-TYPE")`` all return the same value.

    Keys are stored lowercase internally. Cross-framework parity:
    same behaviour now ships in tina4-php (Tina4\\Request),
    tina4-ruby (Tina4::Request), tina4-nodejs (Tina4Request) so the
    chapter 10 documented examples (``headers.get("Content-Type")``)
    finally do what they read like. tina4-book#141 PY-10-03.
    """

    def __init__(self, *args, **kwargs):
        super().__init__()
        if args or kwargs:
            self.update(dict(*args, **kwargs))

    @staticmethod
    def _norm(key):
        return key.lower() if isinstance(key, str) else key

    def __setitem__(self, key, value):
        super().__setitem__(self._norm(key), value)

    def __getitem__(self, key):
        return super().__getitem__(self._norm(key))

    def __contains__(self, key):
        return super().__contains__(self._norm(key))

    def __delitem__(self, key):
        super().__delitem__(self._norm(key))

    def get(self, key, default=None):
        return super().get(self._norm(key), default)

    def setdefault(self, key, default=None):
        return super().setdefault(self._norm(key), default)

    def pop(self, key, *args):
        return super().pop(self._norm(key), *args)

    def update(self, *args, **kwargs):
        # Route through __setitem__ so every key gets normalised.
        for k, v in dict(*args, **kwargs).items():
            self[k] = v


class Request:
    """Parsed HTTP request — everything a route handler needs."""

    __slots__ = (
        "method", "path", "url", "scheme", "query_string", "params", "query",
        "headers", "body", "raw_body", "cookies", "files", "ip", "remote_ip",
        "content_type", "session", "_route_params", "_handler",
    )

    def __init__(self):
        self.method: str = "GET"
        self.path: str = "/"
        self.url: str = "/"
        self.scheme: str = "http"       # Native connection scheme (see is_secure_scheme)
        self.query_string: str = ""
        self.params: dict = {}          # Query string + route params merged
        self.query: dict = {}           # Query string params only (separate from route params)
        self.headers: dict = CaseInsensitiveDict()  # Case-insensitive HTTP headers
        self.body: dict | str | None = None  # Parsed body
        self.raw_body: bytes = b""
        self.cookies: dict = {}
        self.files: dict = {}
        self.ip: str = ""
        self.remote_ip: str = ""        # Raw socket peer (never X-Forwarded-For) — for trust decisions
        self.content_type: str = ""
        self.session = None             # Set by session middleware
        self._route_params: dict = {}   # Dynamic route params ({id}, etc.)
        self._handler = None            # Matched route handler — set by dispatch
                                        # before middleware runs, so before_*
                                        # middleware (e.g. CsrfMiddleware) can read
                                        # handler metadata like _noauth.

    def is_secure_scheme(self) -> bool:
        """True when the client's request scheme is https.

        Proxy-aware: TLS is normally terminated at a proxy (nginx, HAProxy,
        ALB, Cloudflare, most container deploys) which then forwards plain
        HTTP, so the native ASGI scheme reads ``http`` on exactly the deploys
        that ARE encrypted. ``x-forwarded-proto`` carries the scheme the
        client actually used; the FIRST hop of a comma-separated chain
        (``"https, http"``) is the client-facing one. Falls back to the
        native connection scheme when no forwarded header is present.

        This is the single source of truth for the URL scheme AND for the
        Secure flag on the session cookie, so both agree instead of one
        concluding ``https://`` while the other drops Secure (#95; mirrors
        tina4-php ``Request::isSecureScheme()``, php#175).
        """
        forwarded = self.headers.get("x-forwarded-proto", "")
        if forwarded:
            return forwarded.split(",")[0].strip().lower() == "https"
        return (self.scheme or "").lower() == "https"

    @classmethod
    def from_scope(cls, scope: dict, body: bytes = b"") -> "Request":
        """Build a Request from an ASGI scope + body."""
        req = cls()
        req.method = scope.get("method", "GET")
        req.path = scope.get("path", "/")
        req.query_string = scope.get("query_string", b"").decode()
        req.raw_body = body

        # Parse headers (ASGI sends as list of [name, value] byte pairs)
        for name, value in scope.get("headers", []):
            req.headers[name.decode().lower()] = value.decode()

        req.content_type = req.headers.get("content-type", "")
        # Raw socket peer address — NEVER honours X-Forwarded-For, so it can
        # be trusted for loopback/remote authorisation (e.g. the MCP guard).
        _client = scope.get("client")
        req.remote_ip = _client[0] if _client else ""
        # Resolved AFTER remote_ip: the peer decides whether the forwarding
        # headers may be believed at all (TINA4_TRUSTED_PROXIES).
        req.ip = _extract_ip(scope, req.headers, req.remote_ip)

        # Native connection scheme (ASGI: "http"/"https"; TLS terminated at a
        # proxy shows "http" here — x-forwarded-proto carries the real one).
        req.scheme = scope.get("scheme") or "http"

        # Reconstruct the full absolute URL — scheme://host[:port]/path[?query].
        # is_secure_scheme() is the single source of truth for the scheme (and
        # for the session cookie's Secure flag): it honours x-forwarded-proto
        # (first hop of a comma chain wins) then the native scheme, so an app
        # behind a TLS-terminating proxy still sees https. PHP/Ruby/Node parity.
        scheme = "https" if req.is_secure_scheme() else "http"
        host = (
            req.headers.get("x-forwarded-host")
            or req.headers.get("host")
            or "localhost"
        )
        url = f"{scheme}://{host}{req.path}"
        if req.query_string:
            url = f"{url}?{req.query_string}"
        req.url = url

        # Check upload size limit
        content_length = int(req.headers.get("content-length", 0) or 0)
        if content_length > TINA4_MAX_UPLOAD_SIZE or len(body) > TINA4_MAX_UPLOAD_SIZE:
            raise PayloadTooLarge(
                f"Request body ({max(content_length, len(body))} bytes) exceeds "
                f"TINA4_MAX_UPLOAD_SIZE ({TINA4_MAX_UPLOAD_SIZE} bytes)"
            )

        # Parse query params
        if req.query_string:
            parsed = parse_qs(req.query_string, keep_blank_values=True)
            req.query = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
            req.params = dict(req.query)  # params starts as copy of query, route params merge later

        # Parse cookies
        cookie_header = req.headers.get("cookie", "")
        if cookie_header:
            for pair in cookie_header.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    k, _, v = pair.partition("=")
                    req.cookies[k.strip()] = v.strip()

        # Parse body
        req.body = _parse_body(body, req.content_type)

        # Separate files from body for multipart uploads
        if isinstance(req.body, dict) and "multipart/form-data" in req.content_type:
            files = {}
            fields = {}
            for key, value in req.body.items():
                if isinstance(value, dict) and "filename" in value:
                    # Content stays as raw bytes — no base64 encoding
                    files[key] = value
                else:
                    fields[key] = value
            req.files = files
            req.body = fields

        return req

    def merge_route_params(self):
        """Merge route params into params dict (route params take priority)."""
        if self._route_params:
            self.params.update(self._route_params)

    def param(self, key: str, default=None):
        """Get a route parameter (from URL path). Alias for params[key]."""
        return self.params.get(key, self._route_params.get(key, default))

    def header(self, name: str) -> str | None:
        """Get a specific header value by name (case-insensitive)."""
        return self.headers.get(name.lower().replace("-", "_"), self.headers.get(name.lower(), None))

    def bearer_token(self) -> str | None:
        """Extract the Bearer token from the Authorization header."""
        auth = self.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:]
        return None

    def parse_body(self) -> dict | str | None:
        """Parse the raw body based on content type. Returns the parsed result."""
        return _parse_body(self.raw_body, self.content_type)


# Parsed TINA4_TRUSTED_PROXIES, cached on the raw env string so a change is
# picked up but the parse does not run per request. (raw_value, networks)
_trusted_proxy_cache: tuple = (None, ())


def _normalise_ip(value: str) -> str:
    """Strip the decorations a peer address can arrive with.

    Handles ``[::1]`` bracket form and an IPv6 zone id (``fe80::1%eth0``).
    """
    value = value.strip()
    if value.startswith("[") and "]" in value:
        value = value[1:value.index("]")]
    if "%" in value:
        value = value.split("%", 1)[0]
    return value


def _parse_ip(value: str):
    """Parse an address, unmapping IPv4-in-IPv6. Returns None if unparseable.

    A peer arriving as ``::ffff:10.0.0.1`` must match an allow-list entry of
    ``10.0.0.0/8`` - dual-stack listeners hand out the mapped form routinely.
    """
    try:
        address = ipaddress.ip_address(_normalise_ip(value))
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def trusted_proxy_networks() -> tuple:
    """The configured trusted-proxy networks, from ``TINA4_TRUSTED_PROXIES``.

    Comma-separated exact addresses and/or CIDR ranges, IPv4 and IPv6:
    ``10.0.0.0/8, 192.168.1.5, ::1, fd00::/8``. Empty or unset means trust
    NOTHING, which is the secure default: ``X-Forwarded-For`` is then ignored
    entirely and the raw socket peer identifies the client.
    """
    global _trusted_proxy_cache
    raw = os.environ.get("TINA4_TRUSTED_PROXIES", "")
    cached_raw, cached_networks = _trusted_proxy_cache
    if raw == cached_raw:
        return cached_networks

    networks = []
    for entry in raw.split(","):
        entry = _normalise_ip(entry)
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            # Loud, and exactly once per distinct config value (the cache
            # below means this parse runs once). A silently-skipped entry
            # would leave a real proxy untrusted, which looks like the app
            # over-limiting every client - a very expensive typo to debug.
            from tina4_python.debug import Log
            Log.error(
                f"TINA4_TRUSTED_PROXIES: ignoring invalid entry '{entry}' - "
                "expected an IP address or CIDR range, e.g. 10.0.0.0/8 or 192.168.1.5"
            )
    _trusted_proxy_cache = (raw, tuple(networks))
    return _trusted_proxy_cache[1]


def is_trusted_proxy(address: str) -> bool:
    """Is this address a configured trusted proxy?"""
    networks = trusted_proxy_networks()
    if not networks or not address:
        return False
    parsed = _parse_ip(address)
    if parsed is None:
        return False
    return any(parsed in network for network in networks)


def _extract_ip(scope: dict, headers: dict, peer: str = "") -> str:
    """Resolve the client IP, honouring forwarding headers ONLY behind a trusted proxy.

    ``X-Forwarded-For`` is set by whoever sends it, so an unfiltered read lets
    any client choose its own rate-limit bucket - and, worse, choose SOMEONE
    ELSE'S. The header is therefore consulted only when the raw socket peer is
    listed in ``TINA4_TRUSTED_PROXIES``; otherwise the peer IS the client.

    When it is consulted, the RIGHTMOST entry that is not itself a trusted
    proxy wins. Taking the leftmost would be no safer than trusting the header
    outright: a client can prepend its own hop, and the proxy appends rather
    than replaces. This is the algorithm Rack uses (``Rack::Request#ip``).
    """
    if not (peer and is_trusted_proxy(peer)):
        return peer

    forwarded = headers.get("x-forwarded-for", "")
    if forwarded:
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        for hop in reversed(hops):
            if not is_trusted_proxy(hop):
                return hop
        # Every hop is itself a trusted proxy - the peer is the best we have.
        return peer

    real_ip = headers.get("x-real-ip", "").strip()
    return real_ip or peer


def _parse_body(body: bytes, content_type: str) -> dict | str | None:
    """Parse request body based on content type."""
    if not body:
        return None

    if "application/json" in content_type:
        try:
            return json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return body.decode(errors="replace")

    if "application/x-www-form-urlencoded" in content_type:
        parsed = parse_qs(body.decode(), keep_blank_values=True)
        return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}

    if "multipart/form-data" in content_type:
        return _parse_multipart(body, content_type)

    # Plain text or unknown
    try:
        return body.decode()
    except UnicodeDecodeError:
        return None


def _parse_multipart(body: bytes, content_type: str) -> dict:
    """Parse multipart/form-data body. Returns dict with fields and files.

    Uses sequential scanning instead of split() to handle binary files
    that may contain the boundary string in their content.
    """
    result = {}

    # Extract boundary
    boundary = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part[9:].strip('"')
            break

    if not boundary:
        return result

    delimiter = f"--{boundary}".encode()
    close_delimiter = f"--{boundary}--".encode()
    crlf = b"\r\n"
    double_crlf = b"\r\n\r\n"

    # Find first delimiter
    pos = body.find(delimiter)
    if pos == -1:
        return result
    pos += len(delimiter)

    while pos < len(body):
        # Skip CRLF after delimiter
        if body[pos:pos + 2] == crlf:
            pos += 2

        # Find end of headers (double CRLF)
        header_end = body.find(double_crlf, pos)
        if header_end == -1:
            break

        header_section = body[pos:header_end].decode(errors="replace")
        content_start = header_end + 4

        # Find next delimiter — scan for \r\n--boundary
        next_delim = body.find(crlf + delimiter, content_start)
        if next_delim == -1:
            break

        content = body[content_start:next_delim]

        # Check if this is the close delimiter
        after_delim = next_delim + len(crlf) + len(delimiter)
        if body[after_delim:after_delim + 2] == b"--":
            # This is the final part
            is_last = True
        else:
            is_last = False

        # Move past delimiter for next iteration
        pos = after_delim

        # Parse Content-Disposition and Content-Type
        name = None
        filename = None
        file_type = "application/octet-stream"
        for line in header_section.split("\r\n"):
            if "Content-Disposition" in line:
                for token in line.split(";"):
                    token = token.strip()
                    if token.startswith("name="):
                        name = token[5:].strip('"')
                    elif token.startswith("filename="):
                        filename = token[9:].strip('"')
            elif "Content-Type" in line:
                file_type = line.split(":", 1)[1].strip()

        if not name:
            if is_last:
                break
            continue

        if filename:
            result[name] = {
                "filename": filename,
                "type": file_type,
                "content": bytes(content),
                "size": len(content),
            }
        else:
            result[name] = content.decode(errors="replace")

        if is_last:
            break

    return result
