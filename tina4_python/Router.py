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
from tina4_python import Constant
from tina4_python.Debug import Debug
from tina4_python import Request
from tina4_python.Response import Response
from tina4_python.Template import Template


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
        Debug("Root Path " + tina4_python.root_path + " " + url, method, Constant.TINA4_LOG_DEBUG)
        tina4_python.tina4_current_request["url"] = url
        tina4_python.tina4_current_request["headers"] = headers

        # we can add other methods later but right now we validate posts
        if method in [Constant.TINA4_GET, Constant.TINA4_POST, Constant.TINA4_PUT, Constant.TINA4_PATCH, Constant.TINA4_DELETE]:
            content_type = "text/html"
            if "content-type" in headers:
                content_type = headers["content-type"]

            if content_type == "application/json":
                content = {"error": "403 - Forbidden", "data": {"server": {"url": url}}};
            else:
                content = Template.render_twig_template(
                    "errors/403.twig", {"server": {"url": url}})

            current_route = None
            validated = False

            # Get all the route parameters
            for route in tina4_python.tina4_routes.values():
                if route["method"] != method:
                    continue
                Debug("Matching route " + route['route'] + " to " + url, Constant.TINA4_LOG_DEBUG)
                if Router.match(url, route['route']):
                    Debug("Route matched: " + route['route'], Constant.TINA4_LOG_DEBUG)
                    current_route = route
                    exit

            # If the route is not found
            if current_route is None:
                return Response(content, Constant.HTTP_NOT_FOUND, Constant.TEXT_HTML)

            # if we need to execute middleware
            if "middleware" in current_route:
                if current_route["middleware"] is not None:
                    middleware = current_route["middleware"]
                    Debug("Middleware found: " + middleware, Constant.TINA4_LOG_DEBUG)

                    try:
                        import importlib
                        
                        module = importlib.import_module("src.Middleware")
                        
                        # Get the Middleware class from the module
                        middleware_class = getattr(module, 'Middleware')
                        
                        # Create an instance of Middleware
                        middleware_instance = middleware_class()

                        # Get the middleware function
                        middleware_function = getattr(middleware_instance, middleware) 
                        
                        if callable(middleware_function):
                            # Execute the middleware - We can pass additional parameters in the request
                            [request, headers] = middleware_function(request, headers) 
                            Debug("Middleware executed", Constant.TINA4_LOG_DEBUG)
                        else:
                            Debug("Middleware function is not callable", Constant.TINA4_LOG_DEBUG)
                    except (AttributeError, ImportError) as e:
                        Debug(f"Error: {str(e)}", Constant.TINA4_LOG_DEBUG)

            # If the middleware has validated the user then we can carry on
            if "validated" in request:
                validated = request["validated"]
            
            # check to see if we have an auth ability
            if "authorization" in headers:
                if "Bearer" in headers["authorization"]:
                    token = headers["authorization"].replace("Bearer", "").strip()
                    if tina4_python.tina4_auth.valid(token):
                        validated = True
                    
            Debug(current_route, Constant.TINA4_LOG_DEBUG)

            # check if we can authorize with an API key in the header
            if current_route["swagger"] is not None:
                if "headerauth" in current_route["swagger"]:
                    if current_route["swagger"]["headerauth"]:
                        if "x-api-key" in headers:
                            token = headers["x-api-key"].strip()
                            if tina4_python.tina4_auth.valid(token):
                                validated = True

                # check if we can authorize with an API key in the query string
                if "queryauth" in current_route["swagger"]:
                    if current_route["swagger"]["queryauth"]:
                        if "api-key" in request["params"]:
                            token = request["params"]["api-key"]
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
                return Response(content, Constant.HTTP_FORBIDDEN, Constant.TEXT_HTML)
            else:
                if request["body"] is not None and "formToken" in request["body"]:
                    del request["body"]["formToken"]

        # default response
        result = Response("", Constant.HTTP_NOT_FOUND, Constant.TEXT_HTML)

        # split URL and extract query string
        url_parts = url.split('?')
        url = url_parts[0]

        # Serve statics
        static_file = tina4_python.root_path + os.sep + "src" + os.sep + "public" + url.replace("/", os.sep)
        Debug("Attempting to serve static file: " + static_file, Constant.TINA4_LOG_DEBUG)
        if os.path.isfile(static_file):
            mime_type = mimetypes.guess_type(url)[0]
            with open(static_file, 'rb') as file:
                return Response(file.read(), Constant.HTTP_OK, mime_type)

        # check if we have a current route
        if current_route is not None:
            if  "swagger" in current_route and current_route["swagger"] is not None and "secure" in current_route["swagger"]:
                if current_route["swagger"]["secure"] and not validated:
                    if not validated:
                        return Response(content, Constant.HTTP_FORBIDDEN, Constant.TEXT_HTML)

            router_response = current_route["callback"]

            # Add the inline variables  & construct a Request variable
            request["params"].update(Router.variables)

            Request.request = request  # Add the request object
            Request.headers = headers  # Add the headers
            Request.params = request["params"]
            Request.body = request["body"] if "body" in request else None
            Request.session = session

            tina4_python.tina4_current_request = Request
            old_stdout = sys.stdout # Memorize the default stdout stream
            sys.stdout = buffer = io.StringIO()
            result = await router_response(request=Request, response=Response)

        if result is None:
            sys.stdout = old_stdout
            try:
                return Response(json.loads(buffer.getvalue()), Constant.HTTP_OK, Constant.APPLICATION_JSON)
            except:
                return Response(buffer.getvalue(), Constant.HTTP_OK, Constant.TEXT_HTML)

        # If no route is matched, serve 404
        if result.http_code == Constant.HTTP_NOT_FOUND:
            # Serve twigs if the files exist
            if url == "/":
                twig_file = "index.twig"
            else:
                twig_file = url + ".twig"

            # see if we can find the twig file
            if os.path.isfile(tina4_python.root_path + os.sep + "src" + os.sep + "templates" + os.sep + twig_file):
                Debug("Looking for twig file",
                      tina4_python.root_path + os.sep + "src" + os.sep + "templates" + os.sep + twig_file,
                      Constant.TINA4_LOG_DEBUG)
                content = Template.render_twig_template(twig_file, {"request": tina4_python.tina4_current_request})
                if content != "":
                    return Response(content, Constant.HTTP_OK, Constant.TEXT_HTML)

        if result.http_code == Constant.HTTP_NOT_FOUND:
            content = Template.render_twig_template(
                "errors/404.twig", {"server": {"url": url}})
            return Response(content, Constant.HTTP_NOT_FOUND, Constant.TEXT_HTML)

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
    def add(method, route, callback, middleware=None):
        Debug("Adding a route: " + route, Constant.TINA4_LOG_DEBUG)
        if not callback in tina4_python.tina4_routes:
            tina4_python.tina4_routes[callback] = {"route": route, "callback": callback, "method": method, "swagger": None}
        else:
            tina4_python.tina4_routes[callback]["route"] = route
            tina4_python.tina4_routes[callback]["callback"] = callback
            tina4_python.tina4_routes[callback]["method"] = method

        if middleware is not None:
            tina4_python.tina4_routes[callback]["middleware"] = middleware
            Debug("Adding Middleware " + middleware, Constant.TINA4_LOG_DEBUG)

        if '{' in route:  # store the parameters if needed
            route_variables = re.findall(r'{(.*?)}', route)
            tina4_python.tina4_routes[callback]["params"] = route_variables



def get(path: str, middleware=None):
    """
    Get router
    :param arguments:
    :return:
    """
    def actual_get(callback):
        route_paths = path.split('|')
        for route_path in route_paths:
            Router.add(Constant.TINA4_GET, route_path, callback, middleware)
        return callback

    return actual_get


def post(path, middleware=None):
    """
    Post router
    :param path:
    :return:
    """
    def actual_post(callback):
        route_paths = path.split('|')
        for route_path in route_paths:
            Router.add(Constant.TINA4_POST, route_path, callback, middleware)
        return callback

    return actual_post

def put(path, middleware=None):
    """
    Put router
    :param path:
    :return:
    """
    def actual_put(callback):
        route_paths = path.split('|')
        for route_path in route_paths:
            Router.add(Constant.TINA4_PUT, route_path, callback, middleware)
        return callback

    return actual_put


def patch(path, middleware=None):
    """
    Patch router
    :param path:
    :return:
    """
    def actual_patch(callback):
        route_paths = path.split('|')
        for route_path in route_paths:
            Router.add(Constant.TINA4_PATCH, route_path, callback, middleware)
        return callback

    return actual_patch


def delete(path, middleware=None):
    """
    Delete router
    :param path:
    :return:
    """
    def actual_delete(callback):
        route_paths = path.split('|')
        for route_path in route_paths:
            Router.add(Constant.TINA4_DELETE, route_path, callback, middleware)
        return callback

    return actual_delete
