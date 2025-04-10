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
import threading
import traceback
import sass
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from tina4_python.Router import get
from tina4_python import Messages, Constant
from tina4_python.Swagger import Swagger
from tina4_python.Env import load_env
from tina4_python.Webserver import Webserver
from tina4_python.Router import Router
from tina4_python.Localization import localize
from tina4_python.Auth import Auth
from tina4_python.Debug import Debug
from tina4_python.ShellColors import ShellColors
from tina4_python.Session import Session

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

if importlib.util.find_spec("jurigged"):
    import jurigged

# Define the variable to be used for global routes
library_path = os.path.dirname(os.path.realpath(__file__))
root_path = os.path.realpath(os.getcwd())
sys.path.append(root_path)

if not os.path.exists(root_path + os.sep + "logs"):
    os.makedirs(root_path + os.sep + "logs")

localize()

Debug(Messages.MSG_ASSUMING_ROOT_PATH.format(root_path=root_path, library_path=library_path),
      Constant.TINA4_LOG_INFO)

tina4_routes = {}
tina4_current_request = {}
tina4_api_key = None
tina4_auth = Auth(root_path)


# Set up the global exception handler
def global_exception_handler(exception):
    debug_level = Constant.TINA4_LOG_DEBUG
    error = str(exception)
    tb_str = ''.join(traceback.format_exception(None, exception, exception.__traceback__))
    error_string = "Exception Error: " + error + "\n" + tb_str + "\nYou are seeing this error because Tina4 is in debug mode"
    Debug.error(error_string)
    if (os.getenv("TINA4_DEBUG_LEVEL", [Constant.TINA4_LOG_ALL]) == "[TINA4_LOG_ALL]"
            or debug_level in os.getenv("TINA4_DEBUG_LEVEL", [Constant.TINA4_LOG_ALL])):
        pass
    else:
        error_string = ""
    return error_string

def start_in_thread(target):
    """
    Starts a method in a thread
    :param target:
    :return:
    """
    thread = threading.Thread(target=target)
    thread.start()

token = tina4_auth.get_token({"name": "Tina4"})
Debug("TEST TOKEN", token, Constant.TINA4_LOG_DEBUG)
Debug("VALID TOKEN", tina4_auth.valid(token + "a"), Constant.TINA4_LOG_DEBUG)
Debug("VALID TOKEN", tina4_auth.valid(token), Constant.TINA4_LOG_DEBUG)
Debug("PAYLOAD", tina4_auth.get_payload(token), Constant.TINA4_LOG_DEBUG)

if "API_KEY" in os.environ:
    tina4_api_key = os.environ["API_KEY"]

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

if not os.path.exists(root_path + os.sep + "src" + os.sep + "app"):
    os.makedirs(root_path + os.sep + "src" + os.sep + "app")

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
if os.path.exists(root_path + os.sep + "src"):
    try:
        exec("from src import *")
    except ImportError as e:
        Debug("Cannot import src folder", str(e), Constant.TINA4_LOG_ERROR)
else:
    Debug("Missing src folder", Constant.TINA4_LOG_WARNING)

if os.path.exists(root_path + os.sep + "src" + os.sep + "routes"):
    try:
        exec("from src.routes import *")
    except ImportError as e:
        Debug("Cannot import src.routes folder", str(e), Constant.TINA4_LOG_ERROR)
else:
    Debug("Missing src/routes folder", Constant.TINA4_LOG_WARNING)

if os.path.exists(root_path + os.sep + "src" + os.sep + "app"):
    try:
        exec("from src.app import *")
    except ImportError as e:
        Debug("Cannot import src.app folder", str(e), Constant.TINA4_LOG_ERROR)
else:
    Debug("Missing src/app folder", Constant.TINA4_LOG_WARNING)


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


if os.path.exists(root_path + os.sep + "src" + os.sep + "scss"):
    observer = Observer()
    event_handler = SassCompiler()
    observer.schedule(event_handler, path=root_path + os.sep + "src" + os.sep + "scss", recursive=True)
    observer.start()
else:
    Debug("Missing scss folder", Constant.TINA4_LOG_WARNING)


# end compile sass


def file_get_contents(file_path):
    return Path(file_path).read_text()


# Add swagger routes
@get(os.getenv("SWAGGER_ROUTE", "/swagger") + "/swagger.json")
async def get_swagger_json(request, response):
    json = Swagger.get_json(request)
    return response(json)


@get(os.getenv("SWAGGER_ROUTE", "/swagger"))
async def get_swagger(request, response):
    html = file_get_contents(
        root_path + os.sep + "src" + os.sep + "public" + os.sep + "swagger" + os.sep + "index.html")

    html = html.replace("{SWAGGER_ROUTE}", os.getenv("SWAGGER_ROUTE", "/swagger"))
    return response(html)


async def app(scope, receive, send):
    """
    Runs normal hypercorn, uvicorn, granian
    :param scope:
    :param receive:
    :param send:
    :return:
    """
    body = b""
    while True and scope['type'] == 'http' or scope['type'] == 'websocket':
        if scope['type'] != 'websocket':
            message = await receive()
        else:
            message = {'type': 'websocket'}

        if "body" in message:
            body += message["body"]
        if message['type'] == 'lifespan.startup':
            await send({'type': 'lifespan.startup.complete'})
            return
        elif message['type'] == 'lifespan.shutdown':
            await send({'type': 'lifespan.shutdown.complete'})
            return
        elif message["type"] == "http.disconnect" or message["type"] == "websocket.disconnect":
            return
        elif not message.get("more_body"):
            webserver = Webserver(scope["server"][0], scope["server"][1])
            parsed_headers = {}
            parsed_headers_lowercase = {}
            for header in scope["headers"]:
                parsed_headers[header[0].decode()] = header[1].decode()
                parsed_headers_lowercase[header[0].decode().lower()] = header[1].decode()

            if "content-length" not in parsed_headers_lowercase and "accept" in parsed_headers_lowercase:
                parsed_headers_lowercase["content-type"] = parsed_headers_lowercase["accept"].split(",")[0]
                parsed_headers["Content-Type"] = parsed_headers_lowercase["content-type"]

            if "content-length" not in parsed_headers_lowercase:
                parsed_headers_lowercase["content-length"] = 0
                parsed_headers_lowercase["Content-Length"] = parsed_headers_lowercase["content-length"]

            webserver.headers = parsed_headers
            webserver.lowercase_headers = parsed_headers_lowercase

            webserver.path = scope["path"] + "?" + scope["query_string"].decode()

            if "method" in scope:
                webserver.method = scope["method"]
            else:
                webserver.method = "GET"

            if message["type"] == "http.request":
                webserver.content_raw = body
            else:
                webserver.content_raw = b""
            webserver.content_length = parsed_headers_lowercase["content-length"]
            webserver.router_handler = Router()
            webserver.session = Session

            cookie_list = {}
            if "cookie" in webserver.lowercase_headers:
                cookie_list_temp = webserver.lowercase_headers["cookie"].split(";")
                for cookie_value in cookie_list_temp:
                    cookie = cookie_value.split("=", 1)
                    cookie_list[cookie[0].strip()] = cookie[1].strip()

            webserver.cookies = cookie_list

            # initialize the session
            webserver.session = Session(os.getenv("TINA4_SESSION", "PY_SESS"),
                                        os.getenv("TINA4_SESSION_FOLDER", root_path + os.sep + "sessions"),
                                        os.getenv("TINA4_SESSION_HANDLER", "SessionFileHandler")
                                        )

            if os.getenv("TINA4_SESSION", "PY_SESS") in webserver.cookies:
                webserver.session.load(webserver.cookies[os.getenv("TINA4_SESSION", "PY_SESS")])
            else:
                webserver.cookies[os.getenv("TINA4_SESSION", "PY_SESS")] = webserver.session.start()

            tina4_response, tina4_headers = await webserver.get_response(webserver.method, (scope, receive, send), True)

            if message["type"] != "websocket":
                response_headers = []
                for header in tina4_headers:
                    header = header.split(":")
                    response_headers.append([header[0].strip().encode(), header[1].strip().encode()])

                await send({
                    'type': 'http.response.start',
                    'status': tina4_response.http_code,
                    'headers': response_headers,
                })

                if isinstance(tina4_response.content, str):
                    await send({
                        'type': 'http.response.body',
                        'body': tina4_response.content.encode(),
                    })
                else:
                    await send({
                        'type': 'http.response.body',
                        'body': tina4_response.content,
                    })


def run_web_server(in_hostname="localhost", in_port=7145):
    Debug(Messages.MSG_STARTING_WEBSERVER.format(port=in_port), Constant.TINA4_LOG_INFO)
    webserver(in_hostname, in_port)


def webserver(host_name, port):
    """
    Runs the correct webserver
    :param host_name:
    :param port:
    :return:
    """
    if os.getenv("TINA4_BUILT_IN_WEBSERVER", "False").upper() == "TRUE":
        # runs the built-in webserver (websockets) don't work on windows
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
    else:
        # Runs a hyper corn server
        try:
            from hypercorn.config import Config
            from hypercorn.asyncio import serve
            config = Config()
            config.bind = [host_name + ":" + str(port)]
            asyncio.run(serve(app, config))
        except Exception as e:
            Debug("Not running Hypercorn webserver", str(e), Constant.TINA4_LOG_WARNING)

    Debug(Messages.MSG_SERVER_STOPPED, Constant.TINA4_LOG_INFO)


if os.getenv('TINA4_DEFAULT_WEBSERVER', 'True').upper() == 'TRUE':
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
        except Exception as e:
            Debug("Not running webserver", str(e), Constant.TINA4_LOG_WARNING)
    else:
        Debug("Webserver is set to manual start, please call " + ShellColors.bright_red +
              "run_web_server(<HOSTNAME>, <PORT>)" + ShellColors.end + " in your code",
              Constant.TINA4_LOG_WARNING)
