#!/usr/bin/python3
#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
from tina4_python import *
from tina4_python.Debug import Debug
from tina4_python.Router import Response, get
import os


# Start your program here

@get("/env")
async def env(request):
    Debug("Api GET")
    env_variables = str(os.environ)
    Debug(str(os.environ))
    return Response(env_variables)