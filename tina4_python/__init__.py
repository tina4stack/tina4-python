#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
import gettext
import os
import shutil
import importlib
import sys
from tina4_python.Env import load_env
from tina4_python.Webserver import Webserver
from tina4_python.Router import Router
from tina4_python.Localization import localize
from tina4_python.Auth import Auth
import tina4_python.Messages

_ = gettext.gettext

# Server startup messages
MSG_ASSUMING_ROOT_PATH = _('Assuming root path: {root_path}, library path: {library_path}')
MSG_LOAD_ALL_THINGS = _('Load all things')
MSG_SERVER_STARTED = _('Server started http://{host_name}:{port}')
MSG_SERVER_STOPPED = _('Server stopped.')
MSG_STARTING_WEBSERVER = _('Starting webserver on {port}')
MSG_ENTRY_POINT_NAME = _('Entry point name ... {name}')

if os.getenv('environment') is not None:
    environment = ".env."+os.getenv('environment')
else:
    environment = ".env"

Env.load_env(environment)
localize()

if importlib.util.find_spec("jurigged"):
    import jurigged

# Define the variable to be used for global routes
library_path = os.path.dirname(os.path.realpath(__file__))
root_path = os.path.realpath(os.getcwd())
print(Messages.MSG_ASSUMING_ROOT_PATH.format(root_path=root_path, library_path=library_path))

tina4_routes = []
tina4_current_request = {}
tina4_secret = None
tina4_auth = Auth(root_path)

token = tina4_auth.get_token({"name": "Tina4"})
print("TEST TOKEN", token)
print("VALID TOKEN", tina4_auth.valid(token+"a"))
print("VALID TOKEN", tina4_auth.valid(token))
print("PAYLOAD", tina4_auth.get_payload(token))

if "TINA4_SECRET" in os.environ:
    tina4_secret = os.environ["TINA4_SECRET"]

# Hack for local development
if root_path.count("tina4_python") > 0:
    root_path = root_path.split("tina4_python")[0][:-1]

# Make the beginning files for the tina4stack
if not os.path.exists(root_path + os.sep + "src"):
    os.makedirs(root_path + os.sep + "src" + os.sep + "routes")
    os.makedirs(root_path + os.sep + "src" + os.sep + "scss")
    os.makedirs(root_path + os.sep + "src" + os.sep + "orm")
    os.makedirs(root_path + os.sep + "src" + os.sep + "app")
    with open(root_path + os.sep + "src" + os.sep + "__init__.py", 'w') as init_file:
        init_file.write('# Start your project here')
        init_file.write('\n')
    if not os.path.isfile(root_path + os.sep + "app.py") and not os.path.isdir(root_path + os.sep + "tina4_python"):
        with open(root_path + os.sep + "app.py", 'w') as app_file:
            app_file.write('# Starting point for tina4_python, you shouldn''t need to change anything here')
            app_file.write('\n')
            app_file.write('from tina4_python import *')
            app_file.write('\n')

# copy over templates if needed - required for errors
if not os.path.exists(root_path + os.sep + "src" + os.sep + "templates"):
    source_dir = library_path + os.sep + "templates"
    destination_dir = root_path + os.sep + "src" + os.sep + "templates"
    shutil.copytree(source_dir, destination_dir)

# copy over public if needed - required for static files like images and logos
if not os.path.exists(root_path + os.sep + "src" + os.sep + "public"):
    source_dir = library_path + os.sep + "public"
    destination_dir = root_path + os.sep + "src" + os.sep + "public"
    shutil.copytree(source_dir, destination_dir)

# please keep in place otherwise auto loading files does not work nicely
from src import *

def initialize():
    print(Messages.MSG_LOAD_ALL_THINGS)


def webserver(host_name, port):
    web_server = Webserver(host_name, int(port))  # HTTPServer((host_name, int(port)), Webserver)
    web_server.router_handler = Router()
    print(Messages.MSG_SERVER_STARTED.format(host_name=host_name, port=port))

    try:
        web_server.serve_forever()
    except KeyboardInterrupt:
        pass

    web_server.server_close()
    print(Messages.MSG_SERVER_STOPPED)


def main(in_hostname="localhost", in_port=7145):
    print(Messages.MSG_STARTING_WEBSERVER.format(port=in_port))
    initialize()
    webserver(in_hostname, in_port)


if importlib.util.find_spec("jurigged"):
    print("Jurigged enabled")
    jurigged.watch("./")

print(Messages.MSG_ENTRY_POINT_NAME.format(name=__name__))
if __name__ == '__main__' or __name__ == 'tina4_python':
    # Start up a webserver based on params passed on the command line
    HOSTNAME = "localhost"
    PORT = 7145
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        PORT = int(sys.argv[1])
        if len(sys.argv) > 2 and sys.argv[2].isdigit():
            PORT = int(sys.argv[2])
            if ":" in PORT:
                SERVER_CONFIG = PORT.split(":")
                HOSTNAME = SERVER_CONFIG[0]
                PORT = SERVER_CONFIG[1]

    main(HOSTNAME, PORT)
