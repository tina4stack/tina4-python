#!/usr/bin/python3
#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
from  tina4_python import run_web_server

import sys

print("Running the service", sys.argv)
default_port = 8080
if len(sys.argv) > 2:
    default_port = int(sys.argv[2])
run_web_server("127.0.0.1", default_port)
