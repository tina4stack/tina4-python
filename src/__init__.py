#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
import sys
from codecs import replace_errors
from idlelib.rpc import response_queue

from tina4_python import Migration
from tina4_python.Template import Template
from tina4_python.Debug import Debug
from tina4_python.Router import get, cached
from tina4_python.Router import post
from tina4_python.Database import Database
from tina4_python.Swagger import description, secure, summary, example, tags, params

dba = Database("sqlite3:test.db", "username", "password")

@get("/some/page")
async def some_page(request, response):
    global dba
    result = dba.fetch("select id, name from test_record where id = 2")
    html = Template.render_twig_template("index.twig", data={"persons": result.to_array()})
    return response(html)

@get("/hello/{name}")
@description("Some description")
@params(["limit=10", "offset=0"])
@summary("Some summary")
@tags(["hello", "cars"])

async def greet(**params): #(request, response)
    Debug("Hello", params['request'], file_name="test.log")
    name = params['request'].params['name']
    sys.stdout.flush()
    return params['response'](f"Hello, {name}  !") # return response()

@post("/hello/{name}")
@description("Some description")
@summary("Some summary")
@example({"id": 1, "name": "Test"})
@tags("OK")
@secure()
async def greet_again(**params): #(request, response)
    print(params['request'])
    return params['response'](params['request'].body) # return response()

@post("/upload/files")
async def upload_file(request, response):

    return response(request.body)


@get("/test/redirect")
async def redirect(request, response):

    return response.redirect("/hello/world")

@cached(False)
@get("/")
async def index_html(request, response):

    return response(Template.render_twig_template("index.twig"))

