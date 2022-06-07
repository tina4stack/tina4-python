#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
__version__ = '0.1.0'

from http.server import HTTPServer
from tina4_python.Webserver import Webserver
from tina4_python.Router import Router


def initialize():
    print("Load all things")


def webserver(port):
    host_name = "localhost"
    web_server = HTTPServer((host_name, int(port)), Webserver)
    web_server.router_handler = Router()
    print("Server started http://%s:%s" % (host_name, port))

    try:
        web_server.serve_forever()
    except KeyboardInterrupt:
        pass

    web_server.server_close()
    print("Server stopped.")
