#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
import mimetypes
import re
import os
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
        url += "/"
        route_path += "/"

        matching = True
        variables = []

        match_regex = r"/([a-zA-Z0-9\%\ \!\-\.\_\ }\{]*)"

        url_matches_regex = re.finditer(match_regex, url, re.MULTILINE)
        route_matches_regex = re.finditer(match_regex, route_path, re.MULTILINE)

        url_matches = []
        route_matches = []
        for matchNum, match in enumerate(route_matches_regex, start=1):
            url_matches.append(match)
        for matchNum, match in enumerate(url_matches_regex, start=1):
            route_matches.append(match)

        if url != route_path and len(url_matches) == len(route_matches) and len(url_matches) == 2:
            return False

        if len(route_matches) == len(url_matches):
            for i, match_route in enumerate(route_matches):
                print("Comparing", str(url_matches[i].group()), match_route.group())
                if match_route.group() != "" and str(url_matches[i].group()).find('{') != -1:
                    variables.append(urllib.parse.unquote(match_route.group().strip("/")))
                elif route_matches[i].group() != "":
                    print("Matching",match_route.group(), url_matches[i].group())
                    if match_route.group() != url_matches[i].group():
                        matching = False
                        break
                elif route_matches[i].group() == "" and i > 1:
                    matching = False
                    break

        else:
            matching = False

        Router.variables = variables
        print("matching", url_matches, route_matches, variables, matching)
        return matching

    @staticmethod
    async def render(url, method, request, headers):
        Debug("Root Path " + tina4_python.root_path + " " + url)

        # serve statics
        static_file = tina4_python.root_path + os.sep + "src" + os.sep + "public" + url.replace("/", os.sep)
        print("Looking for", static_file)
        if os.path.isfile(static_file):
            mime_type = mimetypes.guess_type(url)[0]
            print("Guessed ", mime_type)
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
            Debug("matching route " + route['route'] + " to " + url)
            if Router.match(url, route['route']):
                router_response = route["callback"]

                params = Router.variables
                params.append(request)

                result = await router_response(*params)
                break

        return {"content": result.content, "http_code": result.http_code, "content_type": result.content_type}

    @staticmethod
    async def resolve(method, url, request, headers):
        """
        Resolve the route and return a html answer
        :param method:
        :param url:
        :param request
        :param headers:
        """
        # render templates or routes ???

        url = Router.clean_url(url)

        Debug("Rendering " + url)
        html_response = await Router.render(url, method, request, headers)
        return dict(http_code=html_response["http_code"], content_type=html_response["content_type"],
                    content=html_response["content"])

    @staticmethod
    def clean_url(url):
        url_parts = url.split('?')
        return url_parts[0].replace('//', '/')

    @staticmethod
    def add(method, route, callback):
        Debug("Adding a route " + route, debug_level=Constant.DEBUG_DEBUG)
        tina4_python.tina4_routes.append({"route": route, "callback": callback, "method": method})

    @staticmethod
    def init_twig(path):
        if hasattr(Router, "twig"):
            Debug("Twig found on " + path)
            return Router.twig
        Debug("Initializing twig on " + path)
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
