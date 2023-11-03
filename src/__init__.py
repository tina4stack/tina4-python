#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
from tina4_python import Constant
from tina4_python.Debug import Debug
from tina4_python.Router import get
from tina4_python.Router import post
from tina4_python.Router import response
import asyncio

# Define your routes here




# This is a simple example of a GET request
# This will be available at http://localhost:port/example

@get("/example")
async def example(**params):
    # Add your code here

    message = "This is an example of a GET request"
    return response(message)


# This is an example of parameterized routing
# This will be available at http://localhost:port/example
@get("/names/{name}/{surname}")
async def example(**params):

    message = f"Hello {params['name']} {params['surname']}"
    return response(f"<h1>{message}<h1>")
