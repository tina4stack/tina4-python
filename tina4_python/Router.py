import mimetypes
import re
import os
import json
import tina4_python
from tina4_python import Constant
from tina4_python.Debug import Debug
from tina4_python import Request
from tina4_python.Template import Template


class Router:
    variables = None

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
        Debug("Variables: " + str(variables))
        Debug("Matching: " + str(matching))
        return matching

    # Renders the URL and returns the content
    @staticmethod
    async def get_result(url, method, request, headers):
        Debug("Root Path " + tina4_python.root_path + " " + url)
        # default response
        result = response("", Constant.HTTP_NOT_FOUND, Constant.TEXT_HTML)

        # split URL and extract query string
        url_parts = url.split('?')
        url = url_parts[0]

        # parse query string into a dictionary
        query_parameters = request["queries"] if "queries" in request else {}
        Debug("Query Parameters: " + str(query_parameters))

        # Serve statics
        static_file = tina4_python.root_path + os.sep + "src" + os.sep + "public" + url.replace("/", os.sep)
        Debug("Attempting to serve static file: " + static_file)
        if os.path.isfile(static_file):
            mime_type = mimetypes.guess_type(url)[0]
            with open(static_file, 'rb') as file:
                return {"content": file.read(), "http_code": Constant.HTTP_OK, "content_type": mime_type}

        # Serve twigs if the files exist
        if url == "/":
            twig_file = "index.twig"
        else:
            twig_file = url + ".twig"
        content = Template.render_twig_template(twig_file, data=None)
        if content != "":
            return {"content": content, "http_code": Constant.HTTP_OK, "content_type": Constant.TEXT_HTML}

        for route in tina4_python.tina4_routes:
            if route["method"] != method:
                continue
            print("Matching route " + route['route'] + " to " + url)
            if Router.match(url, route['route']):
                router_response = route["callback"]

                Request.params = Router.variables
                Request.request = request  # Add the request object
                Request.headers = headers  # Add the headers
                Request.queries = query_parameters
                Request.body = request["body"] if "body" in request else None

                result = await router_response(Request)
                break

        # If no route is matched, serve 404
        if result.http_code == Constant.HTTP_NOT_FOUND:
            print(url, "Not found", request)
            content = Template.render_twig_template(
                "errors/404.twig", {"server": {"url": url}})

            return {"content": content, "http_code": Constant.HTTP_NOT_FOUND, "content_type": Constant.TEXT_HTML}

        return {"content": result.content, "http_code": result.http_code, "content_type": result.content_type}

    @staticmethod
    async def resolve(method, url, request, headers):
        url = Router.clean_url(url)

        Debug("Rendering URL: " + url)
        html_response = await Router.get_result(url, method, request, headers)
        return dict(http_code=html_response["http_code"], content_type=html_response["content_type"],
                    content=html_response["content"])

    # cleans the url of double slashes
    @staticmethod
    def clean_url(url):
        return url.replace('//', '/')

    # adds a route to the router
    @staticmethod
    def add(method, route, callback):
        Debug("Adding a route: " + route)
        tina4_python.tina4_routes.append({"route": route, "callback": callback, "method": method})
        if '{' in route:  # store the parameters if needed
            route_variables = re.findall(r'{(.*?)}', route)
            tina4_python.tina4_routes[-1]["params"] = route_variables


class response:
    """
    response object for router
    :param content
    :param http_code
    :param content_type
    """

    def __init__(self, content='', http_code=Constant.HTTP_OK, content_type=Constant.TEXT_HTML):
        if type(content) is dict or type(content) is list:
            content = json.dumps(content)
            content_type = Constant.APPLICATION_JSON
        self.content = content
        self.http_code = http_code
        self.content_type = content_type


def get(*arguments):
    def actual_get(param):
        if len(arguments) > 0:
            route_paths = arguments[0].split('|')
            for route_path in route_paths:
                Router.add(Constant.TINA4_GET, route_path, param)

    return actual_get


def post(*arguments):
    def actual_post(param):
        if len(arguments) > 0:
            route_paths = arguments[0].split('|')
            for route_path in route_paths:
                Router.add(Constant.TINA4_POST, route_path, param)

    return actual_post
