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

# Define your routes here




# This is a simple example of a GET request
# This will be available at http://localhost:8080/example

@get("/example")
async def example(request):
    # Add your code here

    message = "This is an example of a GET request"
    return response(message)
