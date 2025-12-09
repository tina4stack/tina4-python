#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
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
    variables = {}

    @staticmethod
    def _parse_route_segment(segment):
        """
        Parse route segment like {id}, {username:str}, {price:float}, {file:path}
        Returns (param_name, converter) where converter is 'str', 'int', 'float', 'path'
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
        """Normalize URL: strip query, domain, collapse slashes, trim whitespace"""
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
        """Legacy helper - extracts variables with type conversion"""
        variables = {}
        url_path = Router.clean_url(url).rstrip('/')
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
        """
        Robust URL matching with full support for:
        - Fixed segments
        - {param}, {param:int}, {param:float}, {param:path} (greedy)
        - Trailing slashes (both URL and route)
        - Leading/trailing whitespace and multiple slashes
        - Root path "/" and empty URLs
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
        """
        Returns True if the request should be blocked due to missing auth
        """
        # Route explicitly marked as secure (via @secure() or legacy)
        explicitly_secured = bool(
            route.get("secure") or
            (isinstance(route.get("swagger"), dict) and route["swagger"].get("secure"))
        )

        # Write methods always need auth unless explicitly public
        is_write_method = method not in [Constant.TINA4_GET, Constant.TINA4_OPTIONS]

        return explicitly_secured or (is_write_method and not validated)

    # Renders the URL and returns the content
    @staticmethod
    async def get_result(url, method, request, headers, session):
        from tina4_python import Request
        from tina4_python import Response

        Response.headers = {}
        Response.content = ""
        Response.http_code = Constant.HTTP_NOT_FOUND
        Response.content_type = Constant.TEXT_HTML
        result = Response

        Debug.debug("Root Path " + tina4_python.root_path + " " + url, method)
        tina4_python.tina4_current_request["url"] = url
        tina4_python.tina4_current_request["headers"] = headers

        validated = False
        # we can add other methods later but right now we validate posts
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
                return Response.Response(file.read(), Constant.HTTP_OK, mime_type)

        old_stdout = None
        buffer = io.StringIO()
        for route in tina4_python.tina4_routes.values():
            if "methods" not in route or method not in route["methods"]:
                continue

            Debug.debug(method, "Matching route ", route['routes'], " to ", url)
            if Router.match(url, route['routes']):

                if not "noauth" in route and not validated:
                    if Router.requires_auth(route, method, validated):
                        return Response.Response("Forbidden - Access denied", Constant.HTTP_FORBIDDEN,
                                                 Constant.TEXT_HTML)

                router_response = route["callback"]

                # Add the inline variables & construct a Request variable
                request["params"].update(Router.variables)

                Request.request = request  # Add the request object
                Request.headers = headers  # Add the headers
                Request.params = request["params"]
                Request.body = request["body"] if "body" in request else None
                Request.files = request["files"] if "files" in request else None
                Request.session = session
                Request.raw_data = request["raw_data"] if "raw_data" in request else None
                Request.raw_request = request["raw_request"] if "raw_request" in request else None
                Request.raw_content = request["raw_content"] if "raw_content" in request else None
                Request.url = url
                Request.asgi_scope = request["asgi_scope"] if "asgi_scope" in request else None
                Request.asgi_reader = request["asgi_reader"] if "asgi_reader" in request else None
                Request.asgi_writer = request["asgi_writer"] if "asgi_writer" in request else None
                Request.asgi_response = request["asgi_response"] if "asgi_response" in request else None

                tina4_python.tina4_current_request = Request

                old_stdout = sys.stdout  # Memorize the default stdout stream
                sys.stdout = buffer = io.StringIO()
                error_set = (Constant.HTTP_REDIRECT, Constant.HTTP_REDIRECT_MOVED, Constant.HTTP_REDIRECT_OTHER,
                             Constant.HTTP_FORBIDDEN, Constant.HTTP_BAD_REQUEST, Constant.HTTP_UNAUTHORIZED,
                             Constant.HTTP_SERVER_ERROR)

                if "middleware" in route:
                    middleware_runner = MiddleWare(route["middleware"]["class"])

                    if "methods" in route["middleware"] and route["middleware"]["methods"] is not None and len(
                            route["middleware"]["methods"]) > 0:
                        for method in route["middleware"]["methods"]:
                            Request, result = middleware_runner.call_direct_method(Request, result, method)
                            if result.http_code in error_set:
                                return Response.Response(result.content, result.http_code, result.content_type)
                    else:
                        Request, result = await middleware_runner.call_before_methods(Request, result)
                        if result.http_code in error_set:
                            return Response.Response(result.content, result.http_code, result.content_type)
                        Request, result = await middleware_runner.call_any_methods(Request, result)
                        if result.http_code in error_set:
                            return Response.Response(result.content, result.http_code, result.content_type)

                try:
                    sig = inspect.signature(router_response)
                    kwargs = {}

                    for param_name, param in sig.parameters.items():
                        if param_name in Router.variables:
                            value = Router.variables[param_name]
                            if param.annotation != inspect.Parameter.empty and callable(param.annotation):
                                try:
                                    value = param.annotation(value)
                                except ValueError:
                                    raise ValueError(
                                        f"Invalid type for path param '{param_name}': expected {param.annotation.__name__}, got '{Router.variables[param_name]}'")
                            kwargs[param_name] = value
                        elif param_name == 'request':
                            kwargs[param_name] = Request
                        elif param_name == 'response':
                            kwargs[param_name] = Response.Response
                        elif param.default == inspect.Parameter.empty:
                            raise TypeError(f"Missing required parameter: {param_name}")

                    result = await router_response(**kwargs)
                except Exception as e:
                    error_string = tina4_python.global_exception_handler(e)
                    if Constant.TINA4_LOG_DEBUG in os.getenv(
                            "TINA4_DEBUG_LEVEL") or Constant.TINA4_LOG_ALL in os.getenv("TINA4_DEBUG_LEVEL"):
                        html = Template.render_twig_template("errors/500.twig",
                                                             {"server": {"url": url}, "error_message": error_string})
                        return Response.Response(html, Constant.HTTP_SERVER_ERROR, Constant.TEXT_HTML)
                    else:
                        return Response.Response(error_string, Constant.HTTP_SERVER_ERROR, Constant.TEXT_HTML)

                # we have found a result ... make sure we reflect this if the user didn't actually put the correct http response code in
                if result is not None:
                    if result.http_code == Constant.HTTP_NOT_FOUND:
                        result.http_code = Constant.HTTP_OK

                if "middleware" in route:
                    middleware_runner = MiddleWare(route["middleware"]["class"])

                    if "methods" in route["middleware"] and route["middleware"]["methods"] is not None and len(
                            route["middleware"]["methods"]) > 0:
                        for method in route["middleware"]["methods"]:
                            Request, result = middleware_runner.call_direct_method(Request, result, method)
                            if result.http_code in error_set:
                                return Response.Response(result.content, result.http_code, result.content_type)
                    else:
                        Request, result = await middleware_runner.call_any_methods(Request, result)
                        if result.http_code in error_set:
                            return Response.Response(result.content, result.http_code, result.content_type)

                        Request, result = await middleware_runner.call_after_methods(Request, result)
                        if result.http_code in error_set:
                            return Response.Response(result.content, result.http_code, result.content_type)

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

                break

        if result is None and old_stdout is not None:
            result = Response

            result.headers["FreshToken"] = tina4_python.tina4_auth.get_token({"path": url})
            sys.stdout = old_stdout
            if buffer.getvalue() != "":
                try:
                    return Response.Response(json.loads(buffer.getvalue()), Constant.HTTP_OK, Constant.APPLICATION_JSON,
                                             result.headers)
                except Exception:
                    return Response.Response(buffer.getvalue(), Constant.HTTP_OK, Constant.TEXT_HTML, result.headers)
            else:
                result = Response
                result.http_code = Constant.HTTP_NOT_FOUND

        # If no route is matched, serve 404
        if result.http_code == Constant.HTTP_NOT_FOUND:
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

                    result.headers["FreshToken"] = tina4_python.tina4_auth.get_token({"path": url})
                    result.headers["Cache-Control"] = "max-age=-1, public"
                    result.headers["Pragma"] = "no-cache"
                    content = Template.render_twig_template(twig_file, {"request": tina4_python.tina4_current_request})
                    if content != "":
                        return Response.Response(content, Constant.HTTP_OK, Constant.TEXT_HTML, result.headers)

        if result.http_code == Constant.HTTP_NOT_FOUND:
            content = Template.render_twig_template(
                "errors/404.twig", {"server": {"url": url}})
            return Response.Response(content, Constant.HTTP_NOT_FOUND, Constant.TEXT_HTML)

        result.headers["FreshToken"] = tina4_python.tina4_auth.get_token({"path": url})
        return result

    @staticmethod
    async def resolve(method, url, request, headers, session):
        url = Router.clean_url(url)
        Debug.debug(method, "Resolving URL: " + url)
        return await Router.get_result(url, method, request, headers, session)

    # cleans the url of double slashes
    @staticmethod
    def clean_url(url):
        return url.replace('//', '/')

    # adds a route to the router
    @staticmethod
    def add(method, route, callback):
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
    """
    Get router
    :param path:
    :return:
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
    """
    Post router
    :param path:
    :return:
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
    """
    Put router
    :param path:
    :return:
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
    """
    Patch router
    :param path:
    :return:
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
    """
    Delete router
    :param path:
    :return:
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
    """
    Sets whether the route is cached or not
    :param is_cached:
    :param max_age:
    :return:
    """

    def actual_cached(callback):
        if callback not in tina4_python.tina4_routes:
            tina4_python.tina4_routes[callback] = {"routes": [], "methods": []}
        tina4_python.tina4_routes[callback]["cache"] = {"cached": is_cached, "max_age": max_age}
        return callback

    return actual_cached


def middleware(middleware, specific_methods=None):
    """
    Sets middleware for the route and methods that need to be called
    :param middleware:
    :param specific_methods:
    :return:
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
    """
    Makes a route secure - secured vs secure with swagger
    :return:
    """

    def actual_secure(callback):
        if callback not in tina4_python.tina4_routes:
            tina4_python.tina4_routes[callback] = {"routes": [], "methods": []}
        tina4_python.tina4_routes[callback]["secure"] = True
        return callback

    return actual_secure


def noauth():
    """
    Defines a route with no auth
    :return:
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