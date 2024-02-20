#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
from tina4_python.Debug import Debug
from tina4_python.Router import get
from tina4_python.Router import post
from tina4_python.Router import Response


# This is a simple example of a GET request
# This will be available at http://localhost:port/example

@get("/example")
async def example(request):
    # Add your code here
    message = "This is an example of a GET request"
    return Response(message)


# This is an example of parameterized routing
# This will be available at http://localhost:port/YOURNAME/YOURSURNAME?id=YOURID
@get("/names/{name}/{surname}")
async def example(request):
    Debug("Api GET")
    name = request.params['name']
    surname = request.params['surname']

    # check if id is present
    if "id" in request.queries:
        id = request.queries['id']
    else:
        id = "No id provided"

    message = f"Hello {name} {surname} with id {id}"
    return Response(f"{message}")


# This is an example of a POST request
# This will be available at http://localhost:port/api/generate
# You can test this using Postman
@post("/api/generate")
async def post_me(request):
    req = "NA"

    if request.body is not None:
        req = str(request.body)

    Debug(f"POST: {req}")
    return Response(f"Api POST: {req}")
