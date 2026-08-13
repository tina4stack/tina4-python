# Tina4 Middleware — orchestrator plus built-in middleware classes.
"""
Standardized middleware orchestrator and built-in middleware.

Middleware classes follow a simple convention:
    - Static methods named ``before_*`` run BEFORE the route handler
    - Static methods named ``after_*`` run AFTER the route handler
    - Each method receives ``(request, response)``

What a hook RETURNS decides what happens next. One table, every hook
(``before_*`` and ``after_*``), every scope (global and per-route), and both
public entry points (this orchestrator and the dispatcher in ``core.server``):

    ==========================  ==============================================
    a Response object           SHORT-CIRCUIT. That object IS the response,
                                at ANY status.
    the (request, response)     rebind both, continue
    tuple
    False                       SHORT-CIRCUIT. Send the response as set; a
                                still-default/empty response becomes a 403.
    None                        continue
    ==========================  ==============================================

Usage::

    from tina4_python.core.middleware import Middleware, CorsMiddleware

    Middleware.use(CorsMiddleware)
    request, response = Middleware.run_before([CorsMiddleware], request, response)
    request, response = Middleware.run_after([RequestLoggerMiddleware], request, response)

Zero dependencies — stdlib only.
"""
import os
import time
import logging
import threading

from tina4_python.core.rate_limiter import RateLimiter  # noqa: F401 — re-export for backward compat
from tina4_python.core.response import Response


def _render_forbidden(request, response) -> None:
    """The 403 a middleware gets when it says no without saying what to send.

    ERR-DEC-01/ERR-403-SPLIT: routed through the SAME negotiated renderer as
    404/500 (``server._render_error_page`` + ``server._json_error_body``), so
    a middleware refusal looks like every other error page -- a user
    template if the app ships one, the framework's ``403.twig`` otherwise,
    negotiated JSON for an API client. Lazy import: ``server`` imports this
    module at load time, so importing it back at module scope would be
    circular; by the time a real request reaches here both modules are
    fully loaded (the same pattern ``before_csrf`` already uses).
    """
    from tina4_python.core.server import _render_error_page, _json_error_body
    from tina4_python.debug import get_request_id

    request_id = get_request_id() or ""
    accept = ""
    headers = getattr(request, "headers", None)
    if headers is not None:
        accept = headers.get("accept", "") or ""

    if request is not None and hasattr(request, "wants_json"):
        wants_json = request.wants_json()
    else:
        from tina4_python.core.request import accept_prefers_json
        wants_json = accept_prefers_json(accept)

    if wants_json:
        response.status(403).json(_json_error_body(403, request_id))
        return

    path = getattr(request, "path", "") or ""
    html = _render_error_page(403, path, request_id)
    if html:
        response.status(403).html(html)
    else:
        response.status(403).json(_json_error_body(403, request_id))


class Middleware:
    """Standardized middleware orchestrator.

    Registers middleware classes globally and runs their ``before_*`` /
    ``after_*`` static methods. Mirrors the PHP, Ruby and Node.js
    orchestrators.

    Ordering rule (v3.13.38) — deterministic, never alphabetical:

    * Across middleware classes: REGISTRATION order — the order they were
      attached via ``Middleware.use`` / ``@middleware`` / ``Router.group``.
    * Within a single class: DEFINITION order — ``before_*`` / ``after_*``
      methods run in the order they appear in the class body (Python
      preserves this in ``__dict__``), NOT ``dir()`` alphabetical order.

    ``before_*`` always runs before the route handler, ``after_*`` after.
    """

    _global_middleware: list = []

    @classmethod
    def use(cls, middleware_class) -> None:
        """Register a middleware class to run on every request."""
        if middleware_class not in cls._global_middleware:
            cls._global_middleware.append(middleware_class)

    @classmethod
    def get_global(cls) -> list:
        """Return the list of globally registered middleware classes."""
        return list(cls._global_middleware)

    @classmethod
    def pre_match_middleware(cls) -> list:
        """Global middleware that runs BEFORE route matching.

        A middleware opts in with ``pre_match = True``. Everything else stays
        where it has always run - after matching - so this is additive and no
        existing middleware changes behaviour.

        The two groups need opposite things. CORS must run before matching so
        its headers survive a short-circuited 401/403; a browser shown a 401
        without them reports a CORS error and the real status never reaches the
        developer. CSRF must run AFTER, because it reads the matched route's
        metadata (``request._handler`` / ``_noauth``) to honour a route marked
        ``@noauth`` - PHP shipped exactly that bypass as dead code once,
        because the metadata was not assigned yet.

        NOT named ``before_match`` - hook discovery treats every ``before_*``
        attribute as a middleware hook and would call the flag itself with
        (request, response).
        """
        return [m for m in cls._global_middleware if getattr(m, "pre_match", False) is True]

    @classmethod
    def post_match_middleware(cls) -> list:
        """Global middleware that runs after matching. This is the default."""
        return [m for m in cls._global_middleware if getattr(m, "pre_match", False) is not True]

    @classmethod
    def reset(cls) -> None:
        """Clear all globally registered middleware (primarily for tests)."""
        cls._global_middleware = []

    @staticmethod
    def apply_hook_result(result, request, response):
        """Interpret what a ``before_*`` / ``after_*`` hook returned.

        THE contract, in one place, so both public entry points - this
        orchestrator and ``core.server``'s dispatcher - can never drift apart:

        * a ``Response`` object -> SHORT-CIRCUIT, and that object IS the
          response, at ANY status. This is the PRIMARY rule and the only one
          that can express a 302 redirect.
        * a ``(request, response)`` pair -> rebind both, continue.
        * ``False`` -> SHORT-CIRCUIT. Send the response as the hook left it; if
          it is still default and empty, make it a 403 - a hook that says "no"
          without saying anything else means Forbidden, not 200.
        * ``None`` (or anything else) -> continue.

        Returns ``(request, response, short_circuit)``.
        """
        if isinstance(result, Response):
            return request, result, True
        if isinstance(result, (tuple, list)) and len(result) >= 2:
            return result[0], result[1], False
        if result is False:
            if response.status_code == 200 and not response.content:
                _render_forbidden(request, response)
            return request, response, True
        return request, response, False

    @staticmethod
    def middleware_500(response, middleware, method_name: str, error: Exception):
        """Log a throwing middleware method and produce the deterministic 500.

        A middleware that raises must never crash the worker or leak an
        unhandled exception past the pipeline. We LOG it (so it is visible,
        never silent) and return a clean 500 with the canonical body shape
        ``{"error": "Internal Server Error", "status": 500}`` - identical
        output in all four frameworks. ``middleware`` may be a class or an
        instance; both entry points share this one implementation.
        """
        from tina4_python.debug import Log
        klass = middleware if isinstance(middleware, type) else type(middleware)
        Log.error(
            f"Middleware {klass.__name__}.{method_name} raised "
            f"{type(error).__name__}: {error}"
        )
        return response.status(500).json({
            "error": "Internal Server Error",
            "status": 500,
        })

    @classmethod
    def run_before(cls, middleware_classes, request, response):
        """Run every ``before_*`` static method on the given classes.

        Obeys the return-value contract in ``apply_hook_result``. A hook that
        RAISES is logged and becomes a clean 500, and short-circuits - the
        remaining hooks do not run.

        Also retained: a LEGACY COMPAT path where a response status >= 400
        short-circuits even when the hook returned ``None``. Real middleware
        takes that shape (Rails decides on response state), so it stays - but
        it is NOT the main mechanism, because a status test cannot express a
        3xx redirect. The Response-object rule above is.

        Returns ``(request, response)``.
        """
        for mw_class in middleware_classes:
            for method_name in cls._discover_methods(mw_class, "before_"):
                try:
                    result = getattr(mw_class, method_name)(request, response)
                except Exception as error:
                    return request, cls.middleware_500(response, mw_class, method_name, error)
                request, response, short_circuit = cls.apply_hook_result(result, request, response)
                if short_circuit:
                    return request, response
                # Legacy compat path — see the docstring.
                status = getattr(response, "status_code", None) or getattr(response, "status", 0)
                if isinstance(status, int) and status >= 400:
                    return request, response
        return request, response

    @classmethod
    def run_after(cls, middleware_classes, request, response):
        """Run every ``after_*`` static method on the given classes.

        Same return-value contract as ``run_before``. The one difference is how
        a THROW is handled: an after hook that raises is logged and becomes a
        clean 500, but the REMAINING after hooks still run - they add headers
        and logging that an error response needs just as much as a success.

        There is no >= 400 legacy path here: the handler has already run, and a
        4xx response must not stop the after chain.
        """
        for mw_class in middleware_classes:
            for method_name in cls._discover_methods(mw_class, "after_"):
                try:
                    result = getattr(mw_class, method_name)(request, response)
                except Exception as error:
                    response = cls.middleware_500(response, mw_class, method_name, error)
                    continue
                request, response, short_circuit = cls.apply_hook_result(result, request, response)
                if short_circuit:
                    return request, response
        return request, response

    @staticmethod
    def _discover_methods(mw_class, prefix: str) -> list:
        """Return prefixed method names in DEFINITION order (not alphabetical).

        Walks the MRO from the base classes up to the most-derived so a
        subclass's own methods run after the methods it inherits, and uses
        each class's ``__dict__`` (insertion-ordered in Python 3.7+) to
        preserve the order methods were written in the source. A subclass
        override keeps the position of its first definition.
        """
        seen = set()
        names = []
        klass = mw_class if isinstance(mw_class, type) else type(mw_class)
        for base in reversed(klass.__mro__):
            for name in base.__dict__:
                if (
                    name.startswith(prefix)
                    and name not in seen
                    and callable(getattr(mw_class, name, None))
                ):
                    seen.add(name)
                    names.append(name)
        return names


_CORS_DENY_WARNED: set = set()


def _cors_warn_once(key: str, message: str) -> None:
    """Log an actionable CORS warning at most once per distinct key per process.

    A rejected cross-origin request is otherwise invisible: the browser reports
    a generic CORS failure and the server log says nothing, so the operator has
    to read the framework source to discover which env var to set. Warning on
    EVERY rejected request would flood the log under a scripted probe, so each
    distinct key warns once.
    """
    if key in _CORS_DENY_WARNED:
        return
    _CORS_DENY_WARNED.add(key)
    try:
        from tina4_python.debug import Log
        Log.warning(message)
    except Exception:  # pragma: no cover — logging must never break a request
        logging.getLogger("tina4").warning(message)


class CorsMiddleware:
    """CORS handler — reads config from env, injects headers.

    Deny by default (ADR-0018). With ``TINA4_CORS_ORIGINS`` unset, NO
    ``Access-Control-Allow-Origin`` is emitted and the browser's own CORS check
    blocks the cross-origin request. ``*`` still works, but has to be asked for.

    Credentials and the wildcard are mutually exclusive. The Fetch Standard's
    CORS check treats ``*`` as a literal (not a wildcard) once the request's
    credentials mode is "include", so ``ACAO: *`` plus
    ``Access-Control-Allow-Credentials: true`` is rejected by every browser.
    Emitting it is a framework bug, so the wildcard wins and credentials are
    dropped with a warning rather than shipping a pair no browser accepts.

    ``Vary: Origin`` is emitted whenever the ACAO value is COMPUTED from the
    request's Origin — i.e. whenever an allow-list is configured, match or miss.
    RFC 9110 s12.5.5: a Vary field name list tells cache recipients they "MUST
    NOT use this response to satisfy a later request unless the later request
    has the same values for the listed header fields". Without it a shared cache
    can hand one origin's ACAO (or a miss's lack of one) to a different origin.
    A constant ``*`` genuinely does not vary, so it is NOT sent there — that
    would fragment a CDN's cache per-origin for a response identical to all.

    Access-Control-Allow-Methods / -Allow-Headers are static configured lists
    here; they are never derived from the request's Access-Control-Request-*
    headers, so those field names do NOT belong in Vary.
    """

    @staticmethod
    def before_cors(request, response):
        """Inject CORS headers on every request (class-based middleware convention).

        No preflight branch here on purpose: ``server._stage_cors_preflight``
        answers a preflight (204 + policy headers + ``Allow``) and returns
        before the middleware chain runs, so this hook only ever sees a real
        request. The branch that used to test ``is_preflight`` here ran the
        exact same two lines as the fall-through - it was superseded when the
        preflight moved into the dispatcher stage.
        """
        CorsMiddleware().apply(request, response)
        return request, response

    def __init__(self):
        # Default is EMPTY, not "*" — deny by default (ADR-0018).
        self.origins = os.environ.get("TINA4_CORS_ORIGINS", "")
        self.methods = os.environ.get(
            "TINA4_CORS_METHODS", "GET,POST,PUT,PATCH,DELETE,OPTIONS"
        )
        self.headers = os.environ.get(
            "TINA4_CORS_HEADERS",
            "Content-Type,Authorization,X-Request-ID"
        )
        self.max_age = os.environ.get("TINA4_CORS_MAX_AGE", "86400")
        self.credentials = os.environ.get(
            "TINA4_CORS_CREDENTIALS", "false"
        ).lower() in ("true", "1", "yes")

    @property
    def allowed_origins(self) -> list:
        """The configured origins, split and emptied of blanks."""
        return [o.strip() for o in self.origins.split(",") if o.strip()]

    def is_configured(self) -> bool:
        """True when an operator has actually declared a CORS policy."""
        return bool(self.allowed_origins)

    def allowed_origin(self, request_origin: str) -> str:
        """Return the origin to set in Access-Control-Allow-Origin ("" = none)."""
        allowed = self.allowed_origins
        if not allowed:
            return ""
        if "*" in allowed:
            return "*"
        if request_origin and request_origin in allowed:
            return request_origin
        return ""

    def apply(self, request, response):
        """Inject CORS headers into the response."""
        request_origin = request.headers.get("origin", "")
        allowed = self.allowed_origins

        if not allowed:
            if request_origin:
                _cors_warn_once(
                    "unconfigured",
                    f"CORS: refused cross-origin request from {request_origin} — no policy is "
                    f"configured. Set TINA4_CORS_ORIGINS to the origins you want to allow, e.g. "
                    f"TINA4_CORS_ORIGINS=https://app.example.com (or '*' to allow any origin)."
                )
            return response

        is_wildcard = "*" in allowed
        # An allow-list decision reads the request Origin, so the response
        # varies by it — on a MISS too, or a cache can serve the no-ACAO
        # response to an origin that should have been allowed.
        if not is_wildcard:
            self._vary_origin(response)

        origin = self.allowed_origin(request_origin)
        if not origin:
            if request_origin:
                _cors_warn_once(
                    f"denied:{request_origin}",
                    f"CORS: origin {request_origin} is not in TINA4_CORS_ORIGINS "
                    f"({self.origins}) — the browser will block this response."
                )
            return response

        response.header("access-control-allow-origin", origin)
        response.header("access-control-allow-methods", self.methods)
        response.header("access-control-allow-headers", self.headers)
        response.header("access-control-max-age", self.max_age)

        if self.credentials:
            if origin == "*":
                _cors_warn_once(
                    "wildcard-credentials",
                    "CORS: TINA4_CORS_CREDENTIALS is true but TINA4_CORS_ORIGINS is '*'. "
                    "The Fetch Standard forbids Access-Control-Allow-Origin: * with "
                    "credentials, so credentials are NOT being sent. List the exact "
                    "origins instead, e.g. TINA4_CORS_ORIGINS=https://app.example.com."
                )
            else:
                response.header("access-control-allow-credentials", "true")

        return response

    @staticmethod
    def _vary_origin(response) -> None:
        """Add Origin to Vary without clobbering an existing Vary value.

        The real Response keeps ``_headers`` as a list of pairs. Anything else
        just gets a plain header() call - a CORS header is never worth raising
        out of the middleware chain over.
        """
        headers = getattr(response, "_headers", None)
        if not isinstance(headers, list):
            response.header("vary", "Origin")
            return
        for index, (name, value) in enumerate(headers):
            if name.lower() == "vary":
                parts = [p.strip() for p in value.split(",") if p.strip()]
                if not any(p.lower() == "origin" for p in parts):
                    headers[index] = (name, ", ".join(parts + ["Origin"]))
                return
        response.header("vary", "Origin")

    def is_preflight(self, request) -> bool:
        """Check if this is an OPTIONS preflight request."""
        return (
            request.method == "OPTIONS"
            and "origin" in request.headers
            and "access-control-request-method" in request.headers
        )


class RateLimiterMiddleware:
    """Static rate limiter middleware — tracks requests per IP, returns 429 when exceeded.

    Config via env: TINA4_RATE_LIMIT (default 100), TINA4_RATE_WINDOW (default 60s).
    Delegates to the RateLimiter class for the actual sliding window logic.
    """

    _limiter = None
    _lock = threading.Lock()

    @classmethod
    def _get_limiter(cls):
        with cls._lock:
            if cls._limiter is None:
                cls._limiter = RateLimiter()
            return cls._limiter

    @staticmethod
    def before_rate_limit(request, response):
        """Middleware hook — enforces rate limiting before the route handler."""
        limiter = RateLimiterMiddleware._get_limiter()
        ip = getattr(request, "ip", None) or "unknown"
        allowed, info = limiter.check(ip)
        limiter.apply_headers(response, info)
        if not allowed:
            retry_after = max(1, int(info.get("reset", limiter.window)))
            response.header("retry-after", str(retry_after))
            if hasattr(response, "error"):
                response.error("Too Many Requests", f"Rate limit exceeded. Retry in {retry_after}s.", 429)
            else:
                setattr(response, "status_code", 429)
        return request, response

    @staticmethod
    def check(ip: str):
        """Check if an IP is within rate limits. Returns (allowed, info)."""
        limiter = RateLimiterMiddleware._get_limiter()
        return limiter.check(ip)


class SecurityHeadersMiddleware:
    """Injects security headers on every response.

    Secure-by-default (SECHDR-DEC-01): the framework registers this in the
    default middleware chain at boot via ``attach_security_headers`` (called
    unconditionally from ``server.run``/``server.start``), so a default Tina4 app
    ships the security headers with no opt-in. HSTS is HTTPS-only.

    Configurable via environment variables:
        TINA4_FRAME_OPTIONS        — X-Frame-Options (default: SAMEORIGIN)
        TINA4_HSTS                 — Strict-Transport-Security max-age value
                                     (default: "" = off; set to "31536000" to enable)
        TINA4_CSP                  — Content-Security-Policy (default: "default-src 'self'")
        TINA4_REFERRER_POLICY      — Referrer-Policy (default: strict-origin-when-cross-origin)
        TINA4_PERMISSIONS_POLICY   — Permissions-Policy (default: camera=(), microphone=(), geolocation=())
    """

    @staticmethod
    def before_security(request, response):
        """Set security headers before the route handler runs.

        Registered in the default chain (secure-by-default, SECHDR-DEC-01), so a
        default app emits these headers with no opt-in. Header names use the
        canonical Title-Case spelling shared with PHP/Ruby/Node — HTTP header
        names are case-insensitive, so this is purely so the four frameworks are
        byte-identical on the wire.
        """
        response.header(
            "X-Frame-Options",
            os.environ.get("TINA4_FRAME_OPTIONS", "SAMEORIGIN"),
        )
        response.header("X-Content-Type-Options", "nosniff")

        # HSTS is HTTPS-only (SECHDR-DEC-02). A downgrade-protection header on a
        # plain-HTTP response is inert at best and ships a bad max-age on an
        # unencrypted scheme at worst, so emit it ONLY when TINA4_HSTS is set AND
        # the client request is HTTPS. is_secure_scheme() honours
        # x-forwarded-proto then the native scheme — the same single source of
        # truth the session cookie's Secure flag uses. Defensive getattr keeps a
        # non-Request (e.g. a bare test double) from turning every response into a
        # 500 now that this runs on every request.
        hsts = os.environ.get("TINA4_HSTS", "")
        is_https = bool(getattr(request, "is_secure_scheme", lambda: False)())
        if hsts and is_https:
            response.header(
                "Strict-Transport-Security",
                f"max-age={hsts}; includeSubDomains",
            )

        response.header(
            "Content-Security-Policy",
            os.environ.get("TINA4_CSP", "default-src 'self'"),
        )
        response.header(
            "Referrer-Policy",
            os.environ.get("TINA4_REFERRER_POLICY", "strict-origin-when-cross-origin"),
        )
        response.header("X-XSS-Protection", "0")
        response.header(
            "Permissions-Policy",
            os.environ.get(
                "TINA4_PERMISSIONS_POLICY",
                "camera=(), microphone=(), geolocation=()",
            ),
        )

        return request, response


class CsrfMiddleware:
    """CSRF token validation middleware.

    Off by default. Set ``TINA4_CSRF=true`` (or ``1``/``yes``/``on``) in the
    environment and the framework auto-attaches this middleware at boot (see
    ``attach_csrf_from_env``); or register it explicitly via
    ``Router.use(CsrfMiddleware)``. Once attached, ``TINA4_CSRF=false`` (or
    ``0``/``no``) is the kill switch that disables enforcement again.

    Behaviour:
        - Skips GET, HEAD, OPTIONS requests.
        - Skips routes marked @noauth().
        - Fails CLOSED: with TINA4_SECRET unset the signing secret resolves to
          blank (there is NO built-in default), and a blank HMAC key is
          publicly reproducible — so no token can be trusted and every write is
          rejected (403). This is the SEC-01 no-default-secret guarantee.
        - Skips requests with a valid Authorization: Bearer header (API clients).
        - Checks request.body["formToken"] then request.headers["X-Form-Token"].
        - Rejects if token found in request.query["formToken"] (log warning, 403).
        - Validates token with Auth.valid_token using the resolved SECRET, and
          enforces that the token's ``type`` claim is ``"form"`` — a non-form
          JWT presented in the formToken slot is rejected.
        - If token payload has session_id, verifies it matches request.session.session_id.
        - Returns 403 with response.error("CSRF_INVALID", ...) on failure.
    """

    _logger = logging.getLogger("tina4.csrf")

    @staticmethod
    def before_csrf(request, response):
        """Validate CSRF token before the route handler runs."""
        # TINA4_CSRF=false (or 0/no) disables all CSRF checks, even when the
        # middleware is attached explicitly — this is the documented kill
        # switch ("TINA4_CSRF=false disables all checks"). When unset the
        # default is enabled (true).
        csrf_enabled = os.environ.get("TINA4_CSRF", "true").lower() not in ("false", "0", "no")
        if not csrf_enabled:
            return request, response

        # Skip safe HTTP methods
        method = getattr(request, "method", "GET").upper()
        if method in ("GET", "HEAD", "OPTIONS"):
            return request, response

        # Skip routes marked @noauth()
        handler = getattr(request, "_handler", None)
        if handler and getattr(handler, "_noauth", False):
            return request, response

        # Resolve the signing secret ONCE, fail-closed (blank when TINA4_SECRET
        # is unset — there is NO built-in default). A blank HMAC key is publicly
        # reproducible, so a token signed with it (or with the retired public
        # 'tina4-default-secret') is a forgery: reject every write rather than
        # validate against a guessable key. SEC-01, fail closed hard.
        from tina4_python.auth import Auth as _CsrfAuth, _resolve_secret
        secret = _resolve_secret()
        if not secret:
            return request, response.error(
                "CSRF_INVALID",
                "CSRF token cannot be validated: TINA4_SECRET is not set",
                403,
            )
        auth = _CsrfAuth(secret=secret)

        # Skip requests with a valid Bearer token (API clients)
        headers = getattr(request, "headers", {})
        auth_header = ""
        if isinstance(headers, dict):
            auth_header = headers.get("authorization", headers.get("Authorization", ""))
        elif hasattr(headers, "get"):
            auth_header = headers.get("authorization", "")

        if auth_header.startswith("Bearer "):
            bearer_token = auth_header[7:].strip()
            if bearer_token and auth.valid_token(bearer_token):
                return request, response

        # Reject if token is in query string (security risk — log warning).
        # Read the QUERY STRING only, never request.params: params is
        # route-only (REQ-PARAM-POLLUTION, 3.13.99), so on a parameterized
        # write route (e.g. PUT /api/orders/{id}) it is a non-empty, truthy
        # dict that would short-circuit an `or` fallback and never reach the
        # real query string — silently letting a smuggled ?formToken= past
        # this check on exactly the routes that have route params.
        query = getattr(request, "query", None) or {}
        if isinstance(query, dict) and query.get("formToken"):
            CsrfMiddleware._logger.warning(
                "CSRF token found in query string — rejected for security. "
                "Use POST body or X-Form-Token header instead."
            )
            return request, response.error(
                "CSRF_INVALID",
                "Form token must not be sent in the URL query string",
                403,
            )

        # Extract token: body first, then header
        token = None
        body = getattr(request, "body", None) or {}
        if isinstance(body, dict):
            token = body.get("formToken")

        if not token:
            if isinstance(headers, dict):
                token = headers.get("x-form-token", headers.get("X-Form-Token", ""))
            elif hasattr(headers, "get"):
                token = headers.get("x-form-token", "")

        if not token:
            return request, response.error(
                "CSRF_INVALID",
                "Invalid or missing form token",
                403,
            )

        # Validate the token signature / expiry
        if not auth.valid_token(token):
            return request, response.error(
                "CSRF_INVALID",
                "Invalid or missing form token",
                403,
            )

        payload = auth.get_payload(token) or {}

        # Enforce the form-token TYPE — a valid signature is not enough: a
        # non-form JWT (e.g. an auth/session token) must never be accepted in
        # the formToken slot.
        if payload.get("type") != "form":
            return request, response.error(
                "CSRF_INVALID",
                "Invalid or missing form token",
                403,
            )

        # Session binding — if token has session_id, verify it matches
        token_session_id = payload.get("session_id")
        if token_session_id:
            session = getattr(request, "session", None)
            current_session_id = None
            if session is not None:
                current_session_id = getattr(session, "session_id", None)
                if current_session_id is None and hasattr(session, "get"):
                    current_session_id = session.get("session_id")

            if current_session_id and token_session_id != current_session_id:
                return request, response.error(
                    "CSRF_INVALID",
                    "Invalid or missing form token",
                    403,
                )

        return request, response


def attach_csrf_from_env() -> bool:
    """Auto-attach ``CsrfMiddleware`` when ``TINA4_CSRF`` is enabled in the env.

    CSRF is OFF by default: with ``TINA4_CSRF`` unset the middleware is never
    attached, so a default app has no CSRF gate. Setting ``TINA4_CSRF`` to a
    truthy value (``true``/``1``/``yes``/``on``, case-insensitive) attaches it
    globally at boot so every state-changing route is gated — the env flag is
    the switch, no code change needed. Idempotent (``Middleware.use`` de-dupes).
    Returns True when the middleware is now attached.

    The framework calls this once during ``server.run``/``server.start``; a
    ``false``/``0``/``no`` value still lets an explicit ``Router.use`` opt-in be
    disabled at runtime by the kill switch in ``before_csrf``.
    """
    value = os.environ.get("TINA4_CSRF", "").strip().lower()
    if value in ("true", "1", "yes", "on"):
        Middleware.use(CsrfMiddleware)
        return True
    return False


def attach_security_headers() -> bool:
    """Register ``SecurityHeadersMiddleware`` in the default chain (secure-by-default).

    Unlike CSRF (opt-in via ``TINA4_CSRF``) this is UNCONDITIONAL: a default Tina4
    app ships the security headers with no opt-in — the SECHDR-DEC-01 posture that
    closes the SECHDR-OFF-BY-DEFAULT gap (the middleware existed with good defaults
    but was never registered). Idempotent (``Middleware.use`` de-dupes). The
    framework calls this once during ``server.run``/``server.start``. Returns True
    (always attached).
    """
    Middleware.use(SecurityHeadersMiddleware)
    return True


class RequestLoggerMiddleware:
    """Request logger — stamps start time before the handler and logs elapsed time after.

    Mirrors the PHP, Ruby and Node.js RequestLogger classes.

    v3.13.14: routes through the Tina4 ``Log`` class (was stdlib
    ``logging.getLogger``, whose ``info()`` is silently dropped by an
    unconfigured root logger — so these lines never reached stdout).
    The dev server also logs every request globally (see
    ``server._finalize_response``); this middleware remains for callers
    that want per-route request logging.
    """

    _start_times: dict = {}
    _lock = threading.Lock()

    @staticmethod
    def before_log(request, response):
        """Record the request start time."""
        key = id(request)
        with RequestLoggerMiddleware._lock:
            RequestLoggerMiddleware._start_times[key] = time.monotonic()
        return request, response

    @staticmethod
    def after_log(request, response):
        """Log the request method, path, status code, and elapsed time."""
        key = id(request)
        with RequestLoggerMiddleware._lock:
            start = RequestLoggerMiddleware._start_times.pop(key, None)
        elapsed_ms = round((time.monotonic() - start) * 1000, 3) if start is not None else 0.0
        method = getattr(request, "method", "?")
        path = getattr(request, "url", None) or getattr(request, "path", "/")
        status = getattr(response, "status_code", None) or getattr(response, "status", 0)
        from tina4_python.debug import Log
        Log.info(f"{method} {path} -> {status} ({elapsed_ms}ms)")
        return request, response
