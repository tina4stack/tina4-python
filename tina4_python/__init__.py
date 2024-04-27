#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E403,F401,E402
import asyncio
import gettext
import os
import shutil
import importlib
import sys
import sass
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from tina4_python import Messages, Constant
from tina4_python.Env import load_env
from tina4_python.Webserver import Webserver
from tina4_python.Router import Router
from tina4_python.Localization import localize
from tina4_python.Auth import Auth
from tina4_python.Debug import Debug
from tina4_python.ShellColors import ShellColors

_ = gettext.gettext

# Server startup messages
MSG_ASSUMING_ROOT_PATH = _('Assuming root path: {root_path}, library path: {library_path}')
MSG_LOAD_ALL_THINGS = _('Load all things')
MSG_SERVER_STARTED = _('Server started http://{host_name}:{port}')
MSG_SERVER_STOPPED = _('Server stopped.')
MSG_STARTING_WEBSERVER = _('Starting webserver on {port}')
MSG_ENTRY_POINT_NAME = _('Entry point name ... {name}')

if os.getenv('environment') is not None:
    environment = ".env." + os.getenv('environment')
else:
    environment = ".env"

load_env(environment)
print(ShellColors.bright_yellow + "Setting debug mode", os.getenv("TINA4_DEBUG_LEVEL"), ShellColors.end)
localize()

if importlib.util.find_spec("jurigged"):
    import jurigged

# Define the variable to be used for global routes
library_path = os.path.dirname(os.path.realpath(__file__))
root_path = os.path.realpath(os.getcwd())
Debug(Messages.MSG_ASSUMING_ROOT_PATH.format(root_path=root_path, library_path=library_path),
      Constant.TINA4_LOG_INFO)

tina4_routes = []
tina4_current_request = {}
tina4_secret = None
tina4_auth = Auth(root_path)

token = tina4_auth.get_token({"name": "Tina4"})
Debug("TEST TOKEN", token, Constant.TINA4_LOG_DEBUG)
Debug("VALID TOKEN", tina4_auth.valid(token + "a"), Constant.TINA4_LOG_DEBUG)
Debug("VALID TOKEN", tina4_auth.valid(token), Constant.TINA4_LOG_DEBUG)
Debug("PAYLOAD", tina4_auth.get_payload(token), Constant.TINA4_LOG_DEBUG)

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

# please keep in place otherwise autoloading of files does not work nicely, if you want this to work
# add __init__.py files in your folders
# ignore F403
from src import *
from src.routes import *
from src.app import *


# compile sass
def compile_scss():
    try:
        if os.path.exists(root_path + os.sep + "src" + os.sep + "scss"):
            Debug("Compiling scss", Constant.TINA4_LOG_DEBUG)
            sass.compile(dirname=(root_path + os.sep + 'src' + os.sep + 'scss',
                                  root_path + os.sep + 'src' + os.sep + 'public' + os.sep + 'css'),
                         output_style='compressed')
    except sass.CompileError as E:
        Debug('Error compiling SASS ', E, Constant.TINA4_LOG_ERROR)


compile_scss()


class SassCompiler(FileSystemEventHandler):
    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            compile_scss()


observer = Observer()
event_handler = SassCompiler()
observer.schedule(event_handler, path=root_path + os.sep + "src" + os.sep + "scss", recursive=True)
observer.start()


# end compile sass


def webserver(host_name, port):
    web_server = Webserver(host_name, int(port))  # HTTPServer((host_name, int(port)), Webserver)
    web_server.router_handler = Router()
    # Fix the display to make it clickable
    if host_name == "0.0.0.0":
        host_name = "localhost"
    Debug(Messages.MSG_SERVER_STARTED.format(host_name=host_name, port=port), Constant.TINA4_LOG_INFO)
    try:
        asyncio.run(web_server.serve_forever())
    except KeyboardInterrupt:
        pass
    web_server.server_close()
    Debug(Messages.MSG_SERVER_STOPPED, Constant.TINA4_LOG_INFO)


def run_web_server(in_hostname="localhost", in_port=7145):
    Debug(Messages.MSG_STARTING_WEBSERVER.format(port=in_port), Constant.TINA4_LOG_INFO)
    webserver(in_hostname, in_port)


if importlib.util.find_spec("jurigged"):
    Debug("Jurigged enabled", Constant.TINA4_LOG_INFO)
    jurigged.watch("./")

# Start up a webserver based on params passed on the command line
HOSTNAME = "localhost"
PORT = 7145
if len(sys.argv) > 1:
    PORT = sys.argv[1]
    if ":" in PORT:
        SERVER_CONFIG = PORT.split(":")
        HOSTNAME = SERVER_CONFIG[0]
        PORT = SERVER_CONFIG[1]

if PORT != "stop" and PORT != "manual":
    try:
        PORT = int(PORT)
        run_web_server(HOSTNAME, PORT)
    except Exception:
        Debug("Not running webserver", Constant.TINA4_LOG_WARNING)
else:
    Debug("Webserver is set to manual start, please call " + ShellColors.bright_red +
          "run_web_server(<HOSTNAME>, <PORT>)" + ShellColors.end + " in your code",
          Constant.TINA4_LOG_WARNING)
