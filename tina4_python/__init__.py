#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
__version__ = '0.1.0'

from tina4_python.Env import load_env
from tina4_python.Webserver import Webserver
from tina4_python.Router import Router, response, get
import importlib
import sys
import os
import shutil

if importlib.util.find_spec("jurigged"):
    import jurigged

# define the variable to be used for global routes
tina4_routes = []

library_path = os.path.dirname(os.path.realpath(__file__))

root_path = os.path.realpath(os.getcwd())
print("Assuming root path:", root_path, "library path:", library_path)

# hack for local development
if root_path.count("tina4_python") > 0:
    root_path = root_path.split("tina4_python")[0][:-1]

# Make the beginning files for the tina4stack
if not os.path.exists(root_path + os.sep + "src"):
    source_dir = library_path + os.sep + "public"
    destination_dir = root_path + os.sep + "src" + os.sep + "public"
    shutil.copytree(source_dir, destination_dir)
    os.makedirs(root_path + os.sep + "src" + os.sep + "templates")
    with open(root_path + os.sep + "src" + os.sep + "__init__.py", 'w') as init_file:
        init_file.write('# Start your project here')
        init_file.write('\n')
    if not os.path.isfile(root_path + os.sep + "app.py") and not os.path.isdir(root_path + os.sep + "tina4_python"):
        with open(root_path + os.sep + "app.py", 'w') as app_file:
            app_file.write('# Starting point for tina4_python, you shouldn''t need to change anything here')
            app_file.write('\n')
            app_file.write('from tina4_python import *')
            app_file.write('\n')

from src import *


def initialize():
    print("Load all things")


def webserver(port):
    host_name = "localhost"
    web_server = Webserver(host_name, int(port)) #HTTPServer((host_name, int(port)), Webserver)
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
    load_env()
    initialize()
    webserver(in_port)


if importlib.util.find_spec("jurigged"):
    jurigged.watch("./src")

print("Entry point name ...", __name__)
if __name__ == '__main__' or __name__ == 'tina4_python':
    # Start up a webserver based on params passed on the command line
    PORT = 7145
    if len(sys.argv) > 1 and sys.argv[1]:
        PORT = sys.argv[1]
    main(PORT)
