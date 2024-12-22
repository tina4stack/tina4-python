#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import json
import mimetypes
import re
import os
import sys
import io
import tina4_python
from tina4_python import Constant,Auth
from tina4_python import Response
from tina4_python import Request
from tina4_python.Debug import Debug
from tina4_python.Template import Template
from tina4_python.MiddleWare import MiddleWare


class Router:
    variables = None

    @staticmethod
    def get_variables(url, route_path):
        variables = {}
        url_segments = url.strip('/').split('/')
        route_segments = route_path.strip('/').split('/')
        for i, segment in enumerate(route_segments):
            if '{' in segment:  # parameter part
                param_name = re.search(r'{(.*?)}', segment).group(1)
                variables[param_name] = url_segments[i]
        return variables

    # Matches the URL to the route and extracts the parameters
    @staticmethod
    def match(url, route_path):
        matching = False
        variables = {}

        # splitting URL and route and putting them into lists to compare
        url_segments = url.strip('/').split('/')
        route_segments = route_path.strip('/').split('/')

        if len(url_segments) == len(route_segments):
            matching = True
            for i, segment in enumerate(route_segments):
                if '{' in segment:  # parameter part
                    param_name = re.search(r'{(.*?)}', segment).group(1)
                    variables[param_name] = url_segments[i]
                elif segment != url_segments[i]:  # non-parameter part
                    matching = False
                    break

        Router.variables = variables

        return matching

    # Renders the URL and returns the content
    @staticmethod
    async def get_result(url, method, request, headers, session):
        global Request
        global Response

        Response.headers = {}
        Response.content = ""
        Response.http_code = Constant.HTTP_NOT_FOUND
        Response.content_type = Constant.TEXT_HTML
        result = Response

        Debug("Root Path " + tina4_python.root_path + " " + url, method, Constant.TINA4_LOG_DEBUG)
        tina4_python.tina4_current_request["url"] = url
        tina4_python.tina4_current_request["headers"] = headers

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

            validated = False
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

            if not validated and method != Constant.TINA4_GET:
                return Response.Response(content, Constant.HTTP_FORBIDDEN, Constant.TEXT_HTML)
            else:
                if request["body"] is not None and "formToken" in request["body"]:
                    request["params"]["formToken"] = request["body"]["formToken"]
                    del request["body"]["formToken"]

        # split URL and extract query string
        url_parts = url.split('?')
        url = url_parts[0]

        # Serve statics
        static_file = tina4_python.root_path + os.sep + "src" + os.sep + "public" + url.replace("/", os.sep)
        Debug("Attempting to serve static file: " + static_file, Constant.TINA4_LOG_DEBUG)
        if os.path.isfile(static_file):
            mime_type = mimetypes.guess_type(url)[0]
            with open(static_file, 'rb') as file:
                return Response.Response(file.read(), Constant.HTTP_OK, mime_type)

        old_stdout = None
        buffer = io.StringIO()
        for route in tina4_python.tina4_routes.values():
            if route["method"] != method:
                continue
            Debug("Matching route " + route['route'] + " to " + url, Constant.TINA4_LOG_DEBUG)
            if Router.match(url, route['route']):
                if "swagger" in route and route["swagger"] is not None and "secure" in route["swagger"]:
                    if route["swagger"]["secure"] and not validated:
                        return Response.Response(content, Constant.HTTP_FORBIDDEN, Constant.TEXT_HTML)

                router_response = route["callback"]

                # Add the inline variables  & construct a Request variable
                request["params"].update(Router.variables)


                Request.request = request  # Add the request object
                Request.headers = headers  # Add the headers
                Request.params = request["params"]
                Request.body = request["body"] if "body" in request else None
                Request.session = session
                Request.raw_data = request["raw_data"] if "raw_data" in request else None
                Request.raw_request = request["raw_request"] if "raw_request" in request else None
                Request.raw_content = request["raw_content"] if "raw_content" in request else None
                Request.url = url

                tina4_python.tina4_current_request = Request

                old_stdout = sys.stdout  # Memorize the default stdout stream
                sys.stdout = buffer = io.StringIO()

                if "middleware" in route:
                    middleware_runner = MiddleWare(route["middleware"]["class"])

                    if "methods" in route["middleware"]:
                        for method in route["middleware"]["methods"]:
                            Request, Response = middleware_runner.call_direct_method(Request, Response, method)
                    else:
                        Request, Response = middleware_runner.call_before_methods(Request, Response)
                        Request, Response = middleware_runner.call_any_methods(Request, Response)

                result = await router_response(request=Request, response=Response.Response)

                # we have found a result ... make sure we reflect this if the user didn't actually put the correct http response code in
                if result is not None:
                    if result.http_code == Constant.HTTP_NOT_FOUND:
                        result.http_code = Constant.HTTP_OK

                if "middleware" in route:
                    middleware_runner = MiddleWare(route["middleware"]["class"])

                    if "methods" in route["middleware"]:
                        for method in route["middleware"]["methods"]:
                            Request, result = middleware_runner.call_direct_method(Request, result, method)
                    else:
                        Request, result = middleware_runner.call_after_methods(Request, result)
                        Request, result = middleware_runner.call_any_methods(Request, result)

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
                    return Response.Response(json.loads(buffer.getvalue()), Constant.HTTP_OK, Constant.APPLICATION_JSON, result.headers)
                except:
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
                    Debug("Looking for twig file",
                          tina4_python.root_path + os.sep + "src" + os.sep + "templates" + os.sep + twig_file,
                          Constant.TINA4_LOG_DEBUG)

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
        Debug(method, "Resolving URL: " + url, Constant.TINA4_LOG_DEBUG)
        return await Router.get_result(url, method, request, headers, session)

    # cleans the url of double slashes
    @staticmethod
    def clean_url(url):
        return url.replace('//', '/')

    # adds a route to the router
    @staticmethod
    def add(method, route, callback):
        Debug("Adding a route: " + route, Constant.TINA4_LOG_DEBUG)
        if not callback in tina4_python.tina4_routes:
            tina4_python.tina4_routes[callback] = {"route": route, "callback": callback, "method": method,
                                                   "swagger": None, "cached": False}
        else:
            tina4_python.tina4_routes[callback]["route"] = route
            tina4_python.tina4_routes[callback]["callback"] = callback
            tina4_python.tina4_routes[callback]["method"] = method

        if '{' in route:  # store the parameters if needed
            route_variables = re.findall(r'{(.*?)}', route)
            tina4_python.tina4_routes[callback]["params"] = route_variables



def get(path: str):
    """
    Get router
    :param arguments:
    :return:
    """

    def actual_get(callback):
        route_paths = path.split('|')
        for route_path in route_paths:
            Router.add(Constant.TINA4_GET, route_path, callback)
        return callback

    return actual_get


def post(path):
    """
    Post router
    :param path:
    :return:
    """

    def actual_post(callback):
        route_paths = path.split('|')
        for route_path in route_paths:
            Router.add(Constant.TINA4_POST, route_path, callback)
        return callback

    return actual_post


def put(path):
    """
    Put router
    :param path:
    :return:
    """

    def actual_put(callback):
        route_paths = path.split('|')
        for route_path in route_paths:
            Router.add(Constant.TINA4_PUT, route_path, callback)
        return callback

    return actual_put


def patch(path):
    """
    Patch router
    :param path:
    :return:
    """

    def actual_patch(callback):
        route_paths = path.split('|')
        for route_path in route_paths:
            Router.add(Constant.TINA4_PATCH, route_path, callback)
        return callback

    return actual_patch


def delete(path):
    """
    Delete router
    :param path:
    :return:
    """

    def actual_delete(callback):
        route_paths = path.split('|')
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
            tina4_python.tina4_routes[callback] = {}
        tina4_python.tina4_routes[callback]["cache"] = {"cached": is_cached, "max_age": max_age}
        return callback

    return actual_cached


def middleware(middleware, specific_methods=[]):
    """
    Sets middleware for the route and methods that need to be called
    :param middleware:
    :param specific_methods:
    :return:
    """

    def actual_middleware(callback):
        if callback not in tina4_python.tina4_routes:
            tina4_python.tina4_routes[callback] = {}
        tina4_python.tina4_routes[callback]["middleware"] = {"class": middleware, "methods": specific_methods}
        return callback

    return actual_middleware
