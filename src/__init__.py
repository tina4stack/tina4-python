#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
import sys
from codecs import replace_errors
from idlelib.rpc import response_queue


from src.app.MiddleWare import MiddleWare
from tina4_python import Migration, tina4_auth
from tina4_python.Migration import migrate
from tina4_python.Template import Template
from tina4_python.Debug import Debug
from tina4_python.Router import get, cached
from tina4_python.Router import post, middleware
from tina4_python.Database import Database
from tina4_python.Swagger import description, secure, summary, example, tags, params

dba = Database("sqlite3:test.db", "username", "password")
migrate(dba)

@get("/some/page")
async def some_page(request, response):
    global dba
    result = dba.fetch("select id, name from test_record where id = 2")

    html = Template.render_twig_template("index.twig", data={"persons": result.to_array()})
    return response(html)

@post("/some/page")
async def some_page_post(request, response):
    print(request.params)
    print(request.body)

    token = tina4_auth.get_payload(request.params["formToken"])
    print(token)


@get("/hello/{name}")
@description("Some description")
@params(["limit=10", "offset=0"])
@summary("Some summary")
@tags(["hello", "cars"])
async def greet(**params):  #(request, response)
    Debug("Hello", params['request'], file_name="test.log")
    name = params['request'].params['name']
    sys.stdout.flush()
    return params['response'](f"Hello, {name}  !")  # return response()


@post("/hello/{name}")
@description("Some description")
@summary("Some summary")
@example({"id": 1, "name": "Test"})
@tags("OK")
@secure()
async def greet_again(**params):  #(request, response)
    print(params['request'])
    return params['response'](params['request'].body)  # return response()


@post("/upload/files")
async def upload_file(request, response):
    return response(request.body)


@get("/system/roles")
async def system_roles(request, response):
    print("roles")


@middleware(MiddleWare, ["before_and_after"])
@get("/system/roles/data")
async def system_roles(request, response):
    print("roles ggg")

    return response("OK")


@get("/system/roles/{id}")
async def system_roles(request, response):
    print("roles id")


@middleware(MiddleWare)
@get("/test/redirect")
async def redirect(request, response):
    return response.redirect("/hello/world")


@cached(False)
@get("/")
async def index_html(request, response):
    return response(Template.render_twig_template("index.twig"))


@get("/test/vars")
async def run_test_vars(request, response):
    print("<pre>")
    print("vars")
    print(request.params)
