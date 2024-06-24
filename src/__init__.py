#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
import os

from tina4_python import Migration
from tina4_python.Template import Template
from tina4_python.Debug import Debug
from tina4_python.Router import get
from tina4_python.Router import post
from tina4_python.Database import Database
from tina4_python.Swagger import description

dba = Database("sqlite3:test.db", "username", "password")

@get("/hello/{name}")
@description("Hello world!")
async def greet(**params): #(request, response)
    name = params['request'].params['name']
    return params['response'](f"Hello, {name}!") # return response()



