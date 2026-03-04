#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""URL routing engine for the Tina4 Python web framework.

This module contains two public layers:

1. **``Router`` class** -- the core routing engine that registers routes,
   matches incoming URLs against registered patterns, resolves handlers,
   enforces authentication, runs middleware, and returns ``Response`` objects.

2. **Decorator functions** (``get``, ``post``, ``put``, ``patch``, ``delete``,
   ``cached``, ``middleware``, ``secured``, ``noauth``, ``wsdl``) -- the
   user-facing API for declaring route handlers in ``src/routes/`` files.

Route patterns support fixed segments, typed parameters (``{id}``,
``{id:int}``, ``{price:float}``), and greedy path parameters
(``{file:path}``).  Multiple paths can be bound to the same handler by
passing a pipe-delimited string (``"/a|/b"``) or a list.

Typical usage::

    from tina4_python.Router import get, post

    @get("/api/hello")
    async def hello(request, response):
        return response({"message": "Hello, world!"})

    @post("/api/items")
    async def create_item(request, response):
        return response(request.body, 201)
"""

__all__ = [
    "Router",
    "get", "post", "put", "patch", "delete", "any",
    "cached", "middleware", "secured", "noauth", "wsdl",
]

import json
import inspect
import mimetypes
import re
import os
import sys
import io
import tina4_python
from tina4_python import Constant
from tina4_python.Debug import Debug
from tina4_python.Template import Template
from tina4_python.MiddleWare import MiddleWare


class Router:
    """Core URL routing engine for Tina4.

    ``Router`` is used as a static-only utility class -- it is never
    instantiated.  All state lives in ``tina4_python.tina4_routes`` (the
    global route registry) and in the class-level ``variables`` dict that
    holds the most recently matched path parameters.

    Key responsibilities:

    * **Route registration** -- :meth:`add` stores handler callbacks, their
      HTTP methods, URL patterns, and metadata (security, caching, etc.).
    * **URL matching** -- :meth:`match` compares an incoming URL against one
      or more route patterns with full support for typed path parameters.
    * **Request resolution** -- :meth:`get_result` orchestrates the full
      request lifecycle: static file serving, route matching, auth checks,
      middleware execution, handler invocation, template fallback, and
      error handling.
    """

    variables = {}

    @staticmethod
    def _parse_route_segment(segment):
        """Parse a single route-pattern segment into a parameter name and type.

        Recognises segments of the form ``{name}``, ``{name:type}`` where
        *type* is one of ``str``, ``int``, ``float``, or ``path``.  If the
        segment does not contain a parameter placeholder the method returns
        ``(None, None)``.

        Args:
            segment: A single path segment from a route pattern, e.g.
                ``"users"``, ``"{id}"``, or ``"{price:float}"``.

        Returns:
            A ``(param_name, converter)`` tuple.  *converter* is one of
            ``'str'``, ``'int'``, ``'float'``, or ``'path'``.  Both values
            are ``None`` when the segment is a fixed (literal) segment.
        """
        match = re.match(r'^\{(\w+)(?::(\w+))?}?$', segment.strip())
        if not match:
            return None, None
        name = match.group(1)
        conv = (match.group(2) or 'str').lower()
        if conv not in ('str', 'int', 'float', 'path'):
            conv = 'str'
        return name, conv

    @staticmethod
    def clean_url(url):
        """Normalise a URL path by collapsing consecutive slashes.

        Args:
            url: The raw URL path string (e.g. ``"//api///items"``).

        Returns:
            A cleaned path with all runs of ``/`` reduced to a single
            ``/``.  Returns ``"/"`` when *url* is falsy.
        """
        if not url:
            return "/"
        return re.sub(r'/+', '/', url)

    @staticmethod
    def _normalize_url(url):
        """Full URL normalization: strip query, domain, collapse slashes, add trailing slash."""
        if not url:
            return "/"
        url = url.split('?')[0]
        url = re.sub(r'^https?://[^/]+', '', url)  # remove domain if present
        url = re.sub(r'\s+', '', url)  # remove all whitespace
        url = re.sub(r'/+', '/', url)  # collapse multiple slashes
        url = url.strip('/')
        if not url:
            return "/"
        return "/" + url + "/"

    @staticmethod
    def get_variables(url, route_path):
        """Extract path parameters from a URL given a route pattern.

        This is a legacy convenience helper.  For each parameterised
        segment in *route_path* (e.g. ``{id:int}``), the corresponding
        segment in *url* is extracted and converted to the declared type.

        Args:
            url: The actual request URL (may include a query string which
                is stripped before matching).
            route_path: The route pattern to match against (e.g.
                ``"/api/users/{id:int}"``).

        Returns:
            A dict mapping parameter names to their (type-converted)
            values.  Returns an empty dict if the URL does not conform to
            the pattern or a type conversion fails.
        """
        variables = {}
        url_path = Router._normalize_url(url).rstrip('/')
        url_segments = [s for s in url_path.strip('/').split('/') if s]
        route_segments = [s for s in route_path.strip('/').split('/') if s]

        for i, route_seg in enumerate(route_segments):
            param_name, converter = Router._parse_route_segment(route_seg)
            if param_name:
                if i >= len(url_segments):
                    return {}
                raw = url_segments[i]
                try:
                    if converter == 'int':
                        variables[param_name] = int(raw)
                    elif converter == 'float':
                        variables[param_name] = float(raw)
                    elif converter == 'path':
                        remaining = '/'.join(url_segments[i:])
                        variables[param_name] = remaining
                        break
                    else:
                        variables[param_name] = raw
                except ValueError:
                    return {}
            else:
                if i >= len(url_segments) or route_seg != url_segments[i]:
                    return {}
        return variables

    @staticmethod
    def match(url, route_path):
        """Test whether a request URL matches one or more route patterns.

        Performs robust URL matching with full support for:

        * Fixed (literal) path segments.
        * Typed parameters: ``{param}``, ``{param:int}``, ``{param:float}``.
        * Greedy path parameters: ``{param:path}`` (must be the last segment).
        * Trailing / leading slashes, whitespace, and multiple consecutive
          slashes are all normalised before comparison.

        On a successful match the extracted variables are stored in
        ``Router.variables`` so they can be consumed by the caller.

        Args:
            url: The incoming request URL (query string is stripped).
            route_path: A single route-pattern string or a list of patterns
                to try.  The first matching pattern wins.

        Returns:
            ``True`` if *url* matches any of the supplied patterns,
            ``False`` otherwise.
        """
        if isinstance(route_path, (str, list)):
            route_paths = route_path if isinstance(route_path, list) else [route_path]
        else:
            return False

        # === Normalize incoming URL ===
        url_norm = url.split('?')[0]  # remove query string
        url_norm = re.sub(r'\s+', '', url_norm)  # remove whitespace
        url_norm = re.sub(r'/+', '/', url_norm)  # collapse slashes
        url_norm = url_norm.strip('/')
        if not url_norm:
            url_norm = '/'  # root path
        else:
            url_norm = '/' + url_norm + '/'
        url_segments = [seg for seg in url_norm.strip('/').split('/') if seg]

        for route in route_paths:
            # === Normalize route ===
            route_norm = route.strip()
            route_norm = re.sub(r'\s+', '', route_norm)
            route_norm = re.sub(r'/+', '/', route_norm)
            route_norm = route_norm.strip('/')
            if not route_norm:
                route_norm = '/'
            else:
                route_norm = '/' + route_norm + '/'

            route_segments = [seg for seg in route_norm.strip('/').split('/') if seg]

            variables = {}
            match = True
            url_idx = 0

            for route_idx, route_seg in enumerate(route_segments):
                param_name, converter = Router._parse_route_segment(route_seg)

                if param_name:  # Parameter segment
                    if converter == 'path':
                        # Greedy: consume everything from here to end
                        remaining = url_segments[url_idx:]
                        value = '/'.join(remaining) if remaining else ""
                        variables[param_name] = value
                        if route_idx != len(route_segments) - 1:
                            match = False  # {path:path} must be last
                        break
                    else:
                        if url_idx >= len(url_segments):
                            match = False
                            break
                        raw_val = url_segments[url_idx]
                        try:
                            if converter == 'int':
                                variables[param_name] = int(raw_val)
                            elif converter == 'float':
                                variables[param_name] = float(raw_val)
                            else:
                                variables[param_name] = raw_val
                        except ValueError:
                            match = False
                            break
                else:  # Fixed segment
                    if url_idx >= len(url_segments) or url_segments[url_idx] != route_seg:
                        match = False
                        break

                url_idx += 1

            # Final check: all URL segments consumed unless {path:path} was used
            if match:
                has_path_param = any(Router._parse_route_segment(s)[1] == 'path' for s in route_segments)
                if has_path_param or url_idx == len(url_segments):
                    Router.variables = variables
                    return True

        Router.variables = {}
        return False

    @staticmethod
    def requires_auth(route: dict, method: str, validated: bool) -> bool:
        """Determine whether a request should be blocked for missing auth.

        A request requires authentication when:

        * The route is explicitly marked secure (via ``@secured()`` or the
          legacy swagger ``secure`` flag), **or**
        * The HTTP method is a write operation (anything other than GET /
          OPTIONS) and the request has not been validated.

        Args:
            route: The route metadata dict from ``tina4_python.tina4_routes``.
            method: The HTTP method string (e.g. ``Constant.TINA4_POST``).
            validated: Whether the request already passed token validation.

        Returns:
            ``True`` if access should be denied, ``False`` if the request
            may proceed.
        """
        # Route explicitly marked as secure (via @secure() or legacy)
        explicitly_secured = bool(
            route.get("secure") or
            (isinstance(route.get("swagger"), dict) and route["swagger"].get("secure"))
        )

        # Write methods always need auth unless explicitly public
        is_write_method = method not in [Constant.TINA4_GET, Constant.TINA4_OPTIONS]

        return explicitly_secured or (is_write_method and not validated)

    @staticmethod
    async def get_result(url, method, request, headers, session):
        """Resolve a URL to a ``Response`` by running the full request lifecycle.

        Processing order:

        1. Validate bearer / form tokens when present.
        2. Serve a static file from ``src/public/`` if one matches.
        3. Iterate registered routes and find the first match.
        4. Enforce authentication (``requires_auth``).
        5. Execute pre-route middleware, invoke the handler, execute
           post-route middleware.
        6. Fall back to Twig templates (``src/templates/``) if no route
           matched.
        7. Return a 404 response as the last resort.

        Args:
            url: The cleaned URL path (no double slashes).
            method: HTTP method constant.
            request: Raw request dict with ``params``, ``body``, ``files``,
                etc.
            headers: Dict of HTTP headers (lowercase keys).
            session: The session object for the current connection.

        Returns:
            A ``Response`` object containing the rendered content, HTTP
            status code, content type, and any extra headers.
        """
        from tina4_python.Request import Request
        from tina4_python.Response import Response

        # Reset per-request response context (clears pending headers from add_header)
        Response.reset_context()

        result = None
        route_matched = False

        Debug.debug("Root Path " + tina4_python.root_path + " " + url, method)
        tina4_python.tina4_current_request = {"url": url, "headers": headers}

        validated = False
        # we can add other methods later but right now we validate gets, posts and other risky methods
        if method in [Constant.TINA4_GET, Constant.TINA4_POST, Constant.TINA4_PUT, Constant.TINA4_PATCH,
                      Constant.TINA4_DELETE]:
            content_type = "text/html"
            if "content-type" in headers:
                content_type = headers["content-type"]

            if content_type == "application/json":
                content = {"error": "403 - Forbidden", "data": {"server": {"url": url}}}
            else:
                content = Template.render_twig_template(
                    "errors/403.twig", {"server": {"url": url}})

            # check to see if we have an auth ability
            if "authorization" in headers:
                token = headers["authorization"].replace("Bearer", "").strip()
                if tina4_python.tina4_auth.valid(token):
                    validated = True

            if request["params"] is not None and "formToken" in request["params"]:
                token = request["params"]["formToken"]
                if tina4_python.tina4_auth.valid(token):
                    validated = True

            if request["body"] is not None and "formToken" in request["body"]:
                token = request["body"]["formToken"]
                if tina4_python.tina4_auth.valid(token):
                    validated = True

            if request["body"] is not None and "formToken" in request["body"]:
                request["params"]["formToken"] = request["body"]["formToken"]
                del request["body"]["formToken"]

        # split URL and extract query string
        url_parts = url.split('?')
        url = url_parts[0]

        # Serve statics
        static_file = tina4_python.root_path + os.sep + "src" + os.sep + "public" + url.replace("/", os.sep)
        Debug.debug("Attempting to serve static file: " + static_file)
        if os.path.isfile(static_file):
            mime_type = mimetypes.guess_type(url)[0]
            with open(static_file, 'rb') as file:
                return Response(file.read(), Constant.HTTP_OK, mime_type)

        buffer = io.StringIO()
        for route in tina4_python.tina4_routes.values():
            if "methods" not in route or method not in route["methods"]:
                continue

            Debug.debug(method, "Matching route ", route['routes'], " to ", url)
            if Router.match(url, route['routes']):
                route_matched = True
                # Snapshot variables immediately to prevent race between concurrent requests
                matched_vars = dict(Router.variables)

                if not route.get("noauth", False):
                    if not validated and Router.requires_auth(route, method, validated):
                        return Response("Forbidden - Access denied", Constant.HTTP_FORBIDDEN,
                                                 Constant.TEXT_HTML)

                router_response = route["callback"]

                # Add the inline variables & construct a per-request Request object
                request["params"].update(matched_vars)

                req = Request()
                req.request = request
                req.headers = headers
                req.params = request["params"]
                req.body = request.get("body")
                req.files = request.get("files")
                req.session = session
                req.raw_data = request.get("raw_data")
                req.raw_request = request.get("raw_request")
                req.raw_content = request.get("raw_content")
                req.url = url
                req.asgi_scope = request.get("asgi_scope")
                req.asgi_reader = request.get("asgi_reader")
                req.asgi_writer = request.get("asgi_writer")
                req.asgi_response = request.get("asgi_response")

                tina4_python.tina4_current_request = req

                old_stdout = sys.stdout  # Memorize the default stdout stream
                sys.stdout = buffer = io.StringIO()
                error_set = (Constant.HTTP_REDIRECT, Constant.HTTP_REDIRECT_MOVED, Constant.HTTP_REDIRECT_OTHER,
                             Constant.HTTP_FORBIDDEN, Constant.HTTP_BAD_REQUEST, Constant.HTTP_UNAUTHORIZED,
                             Constant.HTTP_SERVER_ERROR)

                try:
                    if "middleware" in route:
                        middleware_runner = MiddleWare(route["middleware"]["class"])
                        # Pre-route middleware needs a response to pass; create a default
                        mw_response = Response("", Constant.HTTP_OK, Constant.TEXT_HTML)

                        if "methods" in route["middleware"] and route["middleware"]["methods"] is not None and len(
                                route["middleware"]["methods"]) > 0:
                            for mw_method in route["middleware"]["methods"]:
                                req, mw_response = middleware_runner.call_direct_method(req, mw_response, mw_method)
                                if mw_response.http_code in error_set:
                                    return Response(mw_response.content, mw_response.http_code, mw_response.content_type)
                        else:
                            req, mw_response = await middleware_runner.call_before_methods(req, mw_response)
                            if mw_response.http_code in error_set:
                                return Response(mw_response.content, mw_response.http_code, mw_response.content_type)
                            req, mw_response = await middleware_runner.call_any_methods(req, mw_response)
                            if mw_response.http_code in error_set:
                                return Response(mw_response.content, mw_response.http_code, mw_response.content_type)

                    try:
                        sig = inspect.signature(router_response)
                        kwargs = {}

                        for param_name, param in sig.parameters.items():
                            if param_name in matched_vars:
                                value = matched_vars[param_name]
                                if param.annotation != inspect.Parameter.empty and callable(param.annotation):
                                    try:
                                        value = param.annotation(value)
                                    except ValueError:
                                        raise ValueError(
                                            f"Invalid type for path param '{param_name}': expected {param.annotation.__name__}, got '{matched_vars[param_name]}'")
                                kwargs[param_name] = value
                            elif param_name == 'request':
                                kwargs[param_name] = req
                            elif param_name == 'response':
                                kwargs[param_name] = Response
                            elif param.default == inspect.Parameter.empty:
                                raise TypeError(f"Missing required parameter: {param_name}")

                        result = await router_response(**kwargs)
                    except Exception as e:
                        error_msg = tina4_python.global_exception_handler(e)
                        tina4_python.container_broken(error_msg)
                        if Constant.TINA4_LOG_DEBUG in os.getenv(
                                "TINA4_DEBUG_LEVEL") or Constant.TINA4_LOG_ALL in os.getenv("TINA4_DEBUG_LEVEL"):
                            html = Template.render_twig_template("errors/500.twig",
                                                                 {"server": {"url": url}, "error_message": error_msg})
                            return Response(html, Constant.HTTP_SERVER_ERROR, Constant.TEXT_HTML)
                        else:
                            return Response(error_msg, Constant.HTTP_SERVER_ERROR, Constant.TEXT_HTML)

                    # we have found a result ... make sure we reflect this if the user didn't actually put the correct http response code in
                    if result is not None:
                        if result.http_code == Constant.HTTP_NOT_FOUND:
                            result.http_code = Constant.HTTP_OK

                    if result is not None and "middleware" in route:
                        middleware_runner = MiddleWare(route["middleware"]["class"])

                        if "methods" in route["middleware"] and route["middleware"]["methods"] is not None and len(
                                route["middleware"]["methods"]) > 0:
                            for mw_method in route["middleware"]["methods"]:
                                req, result = middleware_runner.call_direct_method(req, result, mw_method)
                                if result.http_code in error_set:
                                    return Response(result.content, result.http_code, result.content_type)
                        else:
                            req, result = await middleware_runner.call_any_methods(req, result)
                            if result.http_code in error_set:
                                return Response(result.content, result.http_code, result.content_type)

                            req, result = await middleware_runner.call_after_methods(req, result)
                            if result.http_code in error_set:
                                return Response(result.content, result.http_code, result.content_type)

                    if result is not None:
                        result.headers["FreshToken"] = tina4_python.tina4_auth.get_token({"path": url})
                        if "cache" in route and route["cache"] is not None:
                            if not route["cache"]["cached"]:
                                result.headers["Cache-Control"] = "max-age=1, must-revalidate"
                                result.headers["Pragma"] = "no-cache"
                            else:
                                result.headers["Cache-Control"] = "max-age=" + str(
                                    route["cache"]["max_age"]) + ", must-revalidate"
                                result.headers["Pragma"] = "cache"
                        else:
                            result.headers["Cache-Control"] = "max-age=-1, must-revalidate"
                            result.headers["Pragma"] = "cache"
                finally:
                    sys.stdout = old_stdout

                break

        # Callback returned None but captured stdout output
        if result is None and route_matched:
            output = buffer.getvalue()
            if output:
                fresh_headers = {"FreshToken": tina4_python.tina4_auth.get_token({"path": url})}
                try:
                    return Response(json.loads(output), Constant.HTTP_OK, Constant.APPLICATION_JSON, fresh_headers)
                except Exception:
                    return Response(output, Constant.HTTP_OK, Constant.TEXT_HTML, fresh_headers)

        # If no route matched or result is still None, try twig templates then 404
        if result is None:
            # Serve twigs if the files exist
            twig_files = []
            if url == "/":
                twig_files.append("index.twig")
            else:
                twig_files.append(url + ".twig")
                twig_files.append(url + "index.twig")

            # see if we can find the twig file
            for twig_file in twig_files:
                if os.path.isfile(tina4_python.root_path + os.sep + "src" + os.sep + "templates" + os.sep + twig_file):
                    Debug.debug("Looking for twig file",
                                tina4_python.root_path + os.sep + "src" + os.sep + "templates" + os.sep + twig_file,
                                )

                    twig_headers = {
                        "FreshToken": tina4_python.tina4_auth.get_token({"path": url}),
                        "Cache-Control": "max-age=-1, public",
                        "Pragma": "no-cache"
                    }
                    content = Template.render_twig_template(twig_file, {"request": tina4_python.tina4_current_request})
                    if content != "":
                        return Response(content, Constant.HTTP_OK, Constant.TEXT_HTML, twig_headers)

        if result is None:
            content = Template.render_twig_template(
                "errors/404.twig", {"server": {"url": url}})
            return Response(content, Constant.HTTP_NOT_FOUND, Constant.TEXT_HTML)

        result.headers["FreshToken"] = tina4_python.tina4_auth.get_token({"path": url})
        return result

    @staticmethod
    async def resolve(method, url, request, headers, session):
        """Public entry point: clean the URL and delegate to :meth:`get_result`.

        Args:
            method: HTTP method constant (e.g. ``Constant.TINA4_GET``).
            url: Raw request URL (may contain double slashes).
            request: The raw request dict.
            headers: Dict of HTTP headers (lowercase keys).
            session: The session object for the current connection.

        Returns:
            A ``Response`` object ready to be sent to the client.
        """
        url = Router.clean_url(url)
        Debug.debug(method, "Resolving URL: " + url)
        return await Router.get_result(url, method, request, headers, session)

    @staticmethod
    def add(method, route, callback):
        """Register a route handler in the global route table.

        Duplicate (method, route) combinations are rejected with an error
        log.  Non-GET methods are marked secure by default so they require
        a valid bearer token unless the route is explicitly annotated with
        ``@noauth()``.

        Args:
            method: HTTP method constant (e.g. ``Constant.TINA4_GET``).
            route: URL pattern string (e.g. ``"/api/users/{id:int}"``).
            callback: The async handler function to invoke when the route
                matches.

        Returns:
            ``True`` if the route was successfully registered, ``False`` if
            a duplicate was detected.
        """
        # Normalize route (remove trailing slash for comparison)
        norm_route = route.rstrip("/").lower()

        # Check if the same method + route already exists
        for cb, data in tina4_python.tina4_routes.items():
            if "methods" in data and method in data["methods"] and \
                    any(r.rstrip("/").lower() == norm_route for r in data["routes"]):
                Debug.error(f"Route already exists: {method} {route}")
                # Optionally raise or return False
                return False

        Debug.debug("Adding a route:", route, method)

        is_secure = False
        if method != Constant.TINA4_GET:
            is_secure = True

        # Add or update the route
        if callback not in tina4_python.tina4_routes:
            tina4_python.tina4_routes[callback] = {"swagger": None, "cached": False, "noauth": False, "routes": [],
                                                   "methods": []}

        tina4_python.tina4_routes[callback]["callback"] = callback

        # see if we already have flagged the security for a GET route
        if "secure" in tina4_python.tina4_routes[callback] and method == Constant.TINA4_GET:
            is_secure = tina4_python.tina4_routes[callback]["secure"]

        if not "routes" in tina4_python.tina4_routes[callback]:
            tina4_python.tina4_routes[callback]["routes"] = []

        if route not in tina4_python.tina4_routes[callback]["routes"]:
            tina4_python.tina4_routes[callback]["routes"].append(route)

        if not "methods" in tina4_python.tina4_routes[callback]:
            tina4_python.tina4_routes[callback]["methods"] = []

        if method not in tina4_python.tina4_routes[callback]["methods"]:
            tina4_python.tina4_routes[callback]["methods"].append(method)

        tina4_python.tina4_routes[callback]["secure"] = is_secure

        if '{' in route:
            route_variables = re.findall(r'\{(\w+)(?::\w+)?}', route)
            tina4_python.tina4_routes[callback]["params"] = route_variables

        return True


def get(path: str | list):
    """Decorator that registers an async handler for HTTP GET requests.

    GET routes are public by default (no bearer token required).  Use
    ``@secured()`` to require authentication.

    Args:
        path: A URL pattern string, a pipe-delimited string of patterns
            (e.g. ``"/a|/b"``), or a list of pattern strings.

    Returns:
        A decorator that registers *callback* for the given path(s) and
        returns it unchanged.

    Example::

        @get("/api/users/{id:int}")
        async def get_user(id, request, response):
            return response({"id": id})
    """

    def actual_get(callback):
        if not isinstance(path, list):
            route_paths = path.split('|')
        else:
            route_paths = path

        for route_path in route_paths:
            Router.add(Constant.TINA4_GET, route_path, callback)
        return callback

    return actual_get


def post(path: str | list):
    """Decorator that registers an async handler for HTTP POST requests.

    POST routes require a valid bearer token by default.  Use ``@noauth()``
    to make a POST route publicly accessible.

    Args:
        path: A URL pattern string, a pipe-delimited string of patterns,
            or a list of pattern strings.

    Returns:
        A decorator that registers *callback* for the given path(s) and
        returns it unchanged.

    Example::

        @post("/api/users")
        async def create_user(request, response):
            return response(request.body, 201)
    """

    def actual_post(callback):
        if not isinstance(path, list):
            route_paths = path.split('|')
        else:
            route_paths = path
        for route_path in route_paths:
            Router.add(Constant.TINA4_POST, route_path, callback)
        return callback

    return actual_post


def put(path: str | list):
    """Decorator that registers an async handler for HTTP PUT requests.

    PUT routes require a valid bearer token by default.  Use ``@noauth()``
    to make a PUT route publicly accessible.

    Args:
        path: A URL pattern string, a pipe-delimited string of patterns,
            or a list of pattern strings.

    Returns:
        A decorator that registers *callback* for the given path(s) and
        returns it unchanged.

    Example::

        @put("/api/users/{id:int}")
        async def update_user(id, request, response):
            return response({"id": id, "updated": True})
    """

    def actual_put(callback):
        if not isinstance(path, list):
            route_paths = path.split('|')
        else:
            route_paths = path
        for route_path in route_paths:
            Router.add(Constant.TINA4_PUT, route_path, callback)
        return callback

    return actual_put


def patch(path: str | list):
    """Decorator that registers an async handler for HTTP PATCH requests.

    PATCH routes require a valid bearer token by default.  Use ``@noauth()``
    to make a PATCH route publicly accessible.

    Args:
        path: A URL pattern string, a pipe-delimited string of patterns,
            or a list of pattern strings.

    Returns:
        A decorator that registers *callback* for the given path(s) and
        returns it unchanged.

    Example::

        @patch("/api/users/{id:int}")
        async def patch_user(id, request, response):
            return response({"id": id, "patched": True})
    """

    def actual_patch(callback):
        if not isinstance(path, list):
            route_paths = path.split('|')
        else:
            route_paths = path
        for route_path in route_paths:
            Router.add(Constant.TINA4_PATCH, route_path, callback)
        return callback

    return actual_patch


def delete(path: str | list):
    """Decorator that registers an async handler for HTTP DELETE requests.

    DELETE routes require a valid bearer token by default.  Use ``@noauth()``
    to make a DELETE route publicly accessible.

    Args:
        path: A URL pattern string, a pipe-delimited string of patterns,
            or a list of pattern strings.

    Returns:
        A decorator that registers *callback* for the given path(s) and
        returns it unchanged.

    Example::

        @delete("/api/users/{id:int}")
        async def delete_user(id, request, response):
            return response({"deleted": True})
    """

    def actual_delete(callback):
        if not isinstance(path, list):
            route_paths = path.split('|')
        else:
            route_paths = path
        for route_path in route_paths:
            Router.add(Constant.TINA4_DELETE, route_path, callback)
        return callback

    return actual_delete


def cached(is_cached, max_age=60):
    """Decorator that controls HTTP cache headers for a route.

    When enabled, the ``Cache-Control`` and ``Pragma`` response headers
    are set to allow client/proxy caching for *max_age* seconds.

    Args:
        is_cached: ``True`` to enable caching, ``False`` to force
            revalidation on every request.
        max_age: Maximum cache lifetime in seconds (default ``60``).

    Returns:
        A decorator that annotates the route and returns *callback*
        unchanged.
    """

    def actual_cached(callback):
        if callback not in tina4_python.tina4_routes:
            tina4_python.tina4_routes[callback] = {"routes": [], "methods": []}
        tina4_python.tina4_routes[callback]["cache"] = {"cached": is_cached, "max_age": max_age}
        return callback

    return actual_cached


def middleware(middleware, specific_methods=None):
    """Decorator that attaches a middleware class to a route.

    The middleware class may define ``before_route``, ``after_route``, and
    arbitrary named methods.  When *specific_methods* is provided, only
    those named methods are invoked; otherwise the framework calls the
    ``before_*`` / ``after_*`` / ``any_*`` hooks automatically.

    Args:
        middleware: A middleware class (not an instance) with static
            handler methods.
        specific_methods: Optional list of method names on the middleware
            class to call explicitly.  Defaults to ``None`` (use the
            standard before/any/after lifecycle).

    Returns:
        A decorator that annotates the route and returns *callback*
        unchanged.
    """

    if specific_methods is None:
        specific_methods = []

    def actual_middleware(callback):
        if callback not in tina4_python.tina4_routes:
            tina4_python.tina4_routes[callback] = {"routes": [], "methods": []}
        tina4_python.tina4_routes[callback]["middleware"] = {"class": middleware, "methods": specific_methods}
        return callback

    return actual_middleware


def secured():
    """Decorator that marks a route as requiring authentication.

    By default only non-GET methods require a bearer token.  Apply this
    decorator to a GET route to enforce token validation on read requests
    as well.

    Returns:
        A decorator that sets the ``secure`` flag on the route and returns
        *callback* unchanged.

    Example::

        @secured()
        @get("/api/admin/stats")
        async def admin_stats(request, response):
            return response({"secret": True})
    """

    def actual_secure(callback):
        if callback not in tina4_python.tina4_routes:
            tina4_python.tina4_routes[callback] = {"routes": [], "methods": []}
        tina4_python.tina4_routes[callback]["secure"] = True
        return callback

    return actual_secure


def noauth():
    """Decorator that exempts a route from authentication checks.

    Apply this to POST/PUT/PATCH/DELETE routes that should be publicly
    accessible without a bearer token (e.g. webhooks, public form
    submissions).

    Returns:
        A decorator that sets the ``noauth`` flag on the route and returns
        *callback* unchanged.

    Example::

        @noauth()
        @post("/api/webhook")
        async def public_webhook(request, response):
            return response({"ok": True})
    """

    def actual_noauth(callback):
        if callback not in tina4_python.tina4_routes:
            tina4_python.tina4_routes[callback] = {}
        tina4_python.tina4_routes[callback]["noauth"] = True
        return callback

    return actual_noauth


def wsdl(path):
    """
    Decorator for WSDL/SOAP routes. Registers the function as a handler for both GET (for ?wsdl queries) and POST (for SOAP operations) requests on the specified path(s).

    The handler should handle both types internally, e.g., return WSDL XML on GET with ?wsdl, or process SOAP on POST.

    Example:
    @wsdl('/cis')
    async def wsdl_cis(request, response):
        return await response.wsdl(CIS(request))
    """

    def decorator(callback):
        route_paths = path.split('|')
        for route_path in route_paths:
            Router.add(Constant.TINA4_GET, route_path, callback)
            Router.add(Constant.TINA4_POST, route_path, callback)
        return callback

    return decorator