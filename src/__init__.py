#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
from tina4_python import Constant
from tina4_python.Router import get
from tina4_python.Router import post
from tina4_python.Router import response
import asyncio



@get("/andre|/test")
async def get_main_page(request):
    print("Params", request["params"])
    await asyncio.sleep(10)
    return response('<h1>Hello 111</h1>', Constant.HTTP_OK, Constant.TEXT_HTML)


@get("/hello/{one}")
async def main_page_2(one, request):
    print("Params", request["params"], one)
    return response('<h1>Hello</h1>' + one, Constant.HTTP_OK, Constant.TEXT_HTML)


@post("/api/generate")
async def post_me(request):
    #print("Params", request)
    return response(request["body"])
