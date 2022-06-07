#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
from tina4_python.Debug import Debug

class Router:

    @staticmethod
    def render(path, request, headers):
        # serve statics

        # serve templates

        # serve routes
        content = 'OOOH!';

        return {"content": content, "http_code": 200, "content_type": "text/html"}

    @staticmethod
    def resolve(method, path, request, headers):
        """
        Resolve the route and return back html answer
        :param method:
        :param path:
        :param request
        :param headers:
        """
        # render templates or routes ???
        Debug ("Rendering "+path)
        response = Router.render(path, request, headers);
        return dict(http_code=response["http_code"], content_type=response["content_type"], content=response["content"])
