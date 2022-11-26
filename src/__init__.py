#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
from tina4_python import Constant
from tina4_python.Router import get
from tina4_python.Router import post
from tina4_python.Router import response


@get("/test|/andre")
def main_page(request):
    return response('<h1>Hello 111</h1>', Constant.HTTP_OK, Constant.TEXT_HTML)


@get("/hello/{one}")
def main_page_2(one, request):
    return response('<h1>Hello</h1>' + one, Constant.HTTP_OK, Constant.TEXT_HTML)


@post("/test")
def post_me(request):
    return response('<h2>Testing22333222</h2>')
