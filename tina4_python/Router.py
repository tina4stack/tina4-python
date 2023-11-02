import mimetypes
import re
import os
import json
import urllib.parse
import tina4_python
from pathlib import Path
from jinja2 import Environment, select_autoescape, FileSystemLoader, TemplateNotFound
from tina4_python import Constant
from tina4_python.Debug import Debug


class Router:
    variables = None

    @staticmethod
    def match(url, route_path):
        matching = False
        variables = {}

        url_segments = url.strip('/').split('/')
        route_segments = route_path.strip('/').split('/')

        if len(url_segments) == len(route_segments):
            matching = True
            for i, segment in enumerate(route_segments):
                if '{' in segment:  # parameter part of the url
                    param_name = re.search(r'{(.*?)}', segment).group(1)
                    variables[param_name] = url_segments[i]
                elif segment != url_segments[i]:  # non parameter part
                    matching = False
                    break

        Router.variables = variables
        Debug("Variables: " + str(variables))
        Debug("Matching: " + str(matching))
        return matching

    @staticmethod
    async def render(url, method, request, headers):
        Debug("Root Path " + tina4_python.root_path + " " + url)

        # serve statics
        static_file = tina4_python.root_path + os.sep + "src" + os.sep + "public" + url.replace("/", os.sep)
        Debug("Attempting to serve static file: " + static_file)
        if os.path.isfile(static_file):
            mime_type = mimetypes.guess_type(url)[0]
            with open(static_file, 'rb') as file:
                return {"content": file.read(), "http_code": Constant.HTTP_OK, "content_type": mime_type}

        # serve templates
        twig = Router.init_twig(tina4_python.root_path + os.sep + "src" + os.sep + "templates")
        if url == "/":
            twig_file = "index"
        else:
            twig_file = url
        try:
            if twig.get_template(twig_file + ".twig"):
                template = twig.get_template(twig_file + ".twig")
                return {"content": template.render(), "http_code": Constant.HTTP_OK, "content_type": Constant.TEXT_HTML}
        except TemplateNotFound:
            Debug("Could not render " + twig_file)

        # serve routes
        result = response('', Constant.HTTP_NOT_FOUND, Constant.TEXT_HTML)

        for route in tina4_python.tina4_routes:
            if route["method"] != method:
                continue
            Debug("Matching route " + route['route'] + " to " + url)
            if Router.match(url, route['route']):
                router_response = route["callback"]

                params = Router.variables
                params['request'] = request  # Add the request object

                result = await router_response(**params)
                break

        return {"content": result.content, "http_code": result.http_code, "content_type": result.content_type}

    @staticmethod
    async def resolve(method, url, request, headers):
        url = Router.clean_url(url)

        Debug("Rendering URL: " + url)
        html_response = await Router.render(url, method, request, headers)
        return dict(http_code=html_response["http_code"], content_type=html_response["content_type"],
                    content=html_response["content"])

    @staticmethod
    def clean_url(url):
        url_parts = url.split('?')
        return url_parts[0].replace('//', '/')

    @staticmethod
    def add(method, route, callback):
        Debug("Adding a route: " + route)
        tina4_python.tina4_routes.append({"route": route, "callback": callback, "method": method})
        if '{' in route:  # store the parameters if the route contains parameters
            route_variables = re.findall(r'{(.*?)}', route)
            tina4_python.tina4_routes[-1]["params"] = route_variables

    @staticmethod
    def init_twig(path):
        if hasattr(Router, "twig"):
            Debug("Twig found on " + path)
            return Router.twig
        Debug("Initializing Twig on " + path)
        twig_path = Path(path)
        Router.twig = Environment(loader=FileSystemLoader(Path(twig_path)))
        return Router.twig


class response:
    """
    Response object for router
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
