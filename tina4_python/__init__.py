#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
__version__ = '0.1.0'

from http.server import HTTPServer
from tina4_python.Webserver import Webserver
from tina4_python.Router import Router
import sys
import jurigged


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


def main(in_port=7145):
    print("Starting webserver on", in_port)
    initialize()
    webserver(in_port)

jurigged.watch("./src")

if __name__ == '__main__':
    # Start up a webserver based on params passed on the command line
    PORT = 7145
    if len(sys.argv) > 1 and sys.argv[1]:
        PORT = sys.argv[1]
    main(PORT)