#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E403,F401,E402
"""
Tina4 Python – Lightweight full-stack framework.

Features:
- Decorator-based routing (@get, @post, etc.)
- Built-in Twig templating
- Zero-config ORM + migrations
- Auto Swagger UI (/docs or /swagger)
- One-liner CRUD scaffolding
- WebSocket support
- Live SASS compilation
- Hot-reload with jurigged (optional)

Just `pip install tina4-python` and run your project – everything just works.
"""
import asyncio
import os
if os.getenv("TINA4_DEBUG_LEVEL", "") == "":
    os.environ["TINA4_DEBUG_LEVEL"] = "DEBUG"

import shutil
import importlib
import sys
import threading
import re
import traceback
import sass
import gettext
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler, FileSystemEvent
from tina4_python.Router import get
from tina4_python import Messages, Constant
from tina4_python.Swagger import Swagger
from tina4_python.Env import load_env
from tina4_python.Webserver import Webserver
from tina4_python.Router import Router
from tina4_python.Localization import localize
from tina4_python.Auth import Auth
from tina4_python.Debug import Debug
from tina4_python.Debug import setup_logging
from tina4_python.ShellColors import ShellColors
from tina4_python.Session import Session
from tina4_python.HtmlElement import add_html_helpers
from tina4_python import ShellColors
from tina4_python.Constant import TINA4_LOG_INFO, TINA4_LOG_ALL

# Make HTML helper functions available globally (html(), div(), etc.)
add_html_helpers(globals())

_ = gettext.gettext

# Server startup messages
MSG_ASSUMING_ROOT_PATH = _('Assuming root path: {root_path}, library path: {library_path}')
MSG_LOAD_ALL_THINGS = _('Load all things')
MSG_SERVER_STARTED = _('Server started http://{host_name}:{port}')
MSG_SERVER_STOPPED = _('Server stopped.')
MSG_STARTING_WEBSERVER = _('Starting webserver on {port}')
MSG_ENTRY_POINT_NAME = _('Entry point name ... {name}')

# Load correct .env file based on environment
if os.getenv('environment') is not None:
    environment = ".env." + os.getenv('environment')
else:
    environment = ".env"

load_env(environment)

debug_level = os.getenv("TINA4_DEBUG_LEVEL", TINA4_LOG_ALL).strip()

if not debug_level or debug_level in ("", "NONE", "NULL"):
    debug_level = TINA4_LOG_INFO
    os.environ["TINA4_DEBUG_LEVEL"] = TINA4_LOG_INFO

setup_logging()
Debug.info("Environment is", environment)

try:
    TINA4_BANNER = ShellColors.bright_magenta + """
    ████████╗██╗███╗   ██╗ █████╗ ██╗  ██╗
    ╚══██╔══╝██║████╗  ██║██╔══██╗██║  ██║
       ██║   ██║██╔██╗ ██║███████║███████║
       ██║   ██║██║╚██╗██║██╔══██║╚════██║
       ██║   ██║██║ ╚████║██║  ██║     ██║
       ╚═╝   ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝     ╚═╝
    """ + ShellColors.end


    print(TINA4_BANNER)
except Exception as e:
    print(ShellColors.bright_magenta +"TINA4"+ShellColors.end)

print(ShellColors.cyan + "INFO: Setting debug mode:", debug_level, ShellColors.end)

# Optional live-coding hot reload
if importlib.util.find_spec("jurigged"):
    import jurigged

# Core paths
library_path = os.path.dirname(os.path.realpath(__file__))
root_path = os.path.realpath(os.getcwd())
sys.path.append(root_path)

# Ensure logs folder exists
if not os.path.exists(root_path + os.sep + "logs"):
    os.makedirs(root_path + os.sep + "logs")

localize()

Debug.debug(Messages.MSG_ASSUMING_ROOT_PATH.format(root_path=root_path, library_path=library_path))

# Global runtime containers
tina4_routes = {}  # Registry of all registered routes
tina4_current_request = {}  # Current request context (used in helpers)
tina4_api_key = None  # Optional global API key
tina4_auth = Auth(root_path)


def global_exception_handler(exception):
    """Global uncaught exception handler.

    Shows full traceback when debug mode is enabled.

    Args:
        exception (Exception): The exception that was raised

    Returns:
        str: User-facing error message
    """
    error = str(exception)
    tb_str = ''.join(traceback.format_exception(None, exception, exception.__traceback__))
    error_string = "Exception Error: " + error + "\n" + tb_str + "\nYou are seeing this error because Tina4 is in debug mode"
    Debug.error(error_string)
    if debug_level == "ALL" or debug_level is None or debug_level == "DEBUG":
        pass
    else:
        error_string = "An exception happened"
    return error_string


def start_in_thread(target, exception_hook=None):
    """Run a function in a background daemon thread.

    Used for watchers (SASS, etc.).

    Args:
        target (callable): Function to execute
        exception_hook (callable, optional): Custom excepthook for the thread
    """
    if exception_hook is not None:
        threading.excepthook = exception_hook
    thread = threading.Thread(target=target)
    thread.start()


# Test JWT token on startup (debug only)
token = tina4_auth.get_token({"name": "Tina4"})
Debug.debug("TEST TOKEN", token)
Debug.debug("VALID TOKEN", tina4_auth.valid(token + "a"))
Debug.debug("VALID TOKEN", tina4_auth.valid(token))
Debug.debug("PAYLOAD", tina4_auth.get_payload(token))

if "API_KEY" in os.environ:
    tina4_api_key = os.environ["API_KEY"]

# Dev-mode path fix
if root_path.count("tina4_python") > 0:
    root_path = root_path.split("tina4_python")[0][:-1]

# Create default project structure on first run
if not os.path.exists(root_path + os.sep + "src"):
    os.makedirs(root_path + os.sep + "src" + os.sep + "routes")
    os.makedirs(root_path + os.sep + "src" + os.sep + "scss")
    os.makedirs(root_path + os.sep + "src" + os.sep + "orm")
    os.makedirs(root_path + os.sep + "src" + os.sep + "app")

    with open(root_path + os.sep + "src" + os.sep + "__init__.py", 'w') as init_file:
        init_file.write('# Start your project here\n')

    if not os.path.isfile(root_path + os.sep + "app.py") and not os.path.isdir(root_path + os.sep + "tina4_python"):
        with open(root_path + os.sep + "app.py", 'w') as app_file:
            app_file.write('# Starting point for tina4_python, you shouldn\'t need to change anything here\n')
            app_file.write('from tina4_python import *\n')

if not os.path.exists(root_path + os.sep + "src" + os.sep + "app"):
    os.makedirs(root_path + os.sep + "src" + os.sep + "app")

# Copy default templates & public assets
if not os.path.exists(root_path + os.sep + "src" + os.sep + "templates"):
    source_dir = library_path + os.sep + "templates"
    destination_dir = root_path + os.sep + "src" + os.sep + "templates"
    shutil.copytree(source_dir, destination_dir)

if not os.path.exists(root_path + os.sep + "src" + os.sep + "public"):
    source_dir = library_path + os.sep + "public"
    destination_dir = root_path + os.sep + "src" + os.sep + "public"
    shutil.copytree(source_dir, destination_dir)

# Declare built ins so we don't always have to import stuff
import builtins
from .Router import get, post, put, patch, delete, middleware, cached, noauth, secured, wsdl
from .Testing import tests, assert_equal, assert_raises
from .Debug import Debug
from .Database import Database
from .ORM import ORM
from .Api import Api
from .Template import template
from .Swagger import description, secure, summary, example, example_response, tags, params, describe
from .FieldTypes import IntegerField, StringField, JSONBField, TextField, BlobField, NumericField, DateTimeField
from .Constant import TEXT_HTML, TEXT_PLAIN, TEXT_CSS, TINA4_POST, TINA4_DELETE, TINA4_ANY, TINA4_PUT, TINA4_PATCH, TINA4_OPTIONS, TINA4_LOG_ALL, TINA4_LOG_WARNING, TINA4_LOG_ERROR, TINA4_LOG_DEBUG, TINA4_GET, TINA4_LOG_INFO, HTTP_OK, HTTP_SERVER_ERROR, HTTP_FORBIDDEN, HTTP_NO_CONTENT, HTTP_PARTIAL_CONTENT, HTTP_CREATED, HTTP_UNAUTHORIZED, HTTP_ACCEPTED, HTTP_REDIRECT, HTTP_REDIRECT_MOVED, HTTP_REDIRECT_OTHER, HTTP_BAD_REQUEST, HTTP_NOT_FOUND, LOOKUP_HTTP_CODE, APPLICATION_JSON, APPLICATION_XML

# Make them globally available in every Tina4 project — zero imports
for deco in (get, post, put, patch, delete, middleware, cached, noauth, secured, wsdl, tests, assert_equal, assert_raises,
             IntegerField, StringField, JSONBField, TextField, BlobField, NumericField, DateTimeField,
             description, secure, summary, example, example_response, tags, params, describe, template):
    if deco.__name__ not in builtins.__dict__:
        builtins.__dict__[deco.__name__] = deco

builtins.Debug = Debug
builtins.Api = Api
builtins.Database = Database
builtins.ORM = ORM

# Auto-import everything from src folders
if os.path.exists(root_path + os.sep + "src"):
    try:
        exec("from src import *")
        Debug.info("Initializing src folder")
    except ImportError as e:
        Debug.error("Cannot import src folder", str(e))
else:
    Debug.warning("Missing src folder")


def compile_scss():
    """Auto-compile ALL .scss files → single compressed default.css (no default.scss needed)"""
    scss_dir = Path(root_path) / "src" / "scss"
    css_dir = Path(root_path) / "src" / "public" / "css"
    output_file = css_dir / "default.css"

    if not scss_dir.exists():
        Debug.info("No src/scss folder — skipping SCSS compile")
        return

    # Find all .scss files (ignore _partials.scss unless imported)
    scss_files = list(scss_dir.rglob("*.scss"))
    if not scss_files:
        Debug.info("No .scss files found — skipping")
        return

    css_dir.mkdir(parents=True, exist_ok=True)

    try:
        Debug.debug(f"Found {len(scss_files)} SCSS files — compiling to default.css")

        # Build one big string with all content + @import for partials
        all_scss = ""
        partials = []

        for file in scss_files:
            if file.name.startswith("_"):
                partials.append(file.name)
            else:
                # Main files: add @import for partials + content
                content = file.read_text(encoding="utf-8")
                all_scss += f"/* === {file.name} === */\n{content}\n\n"

        # Auto-import all partials at the top
        for partial in sorted(partials):
            all_scss = f"@import \"{partial}\";\n" + all_scss

        # Compile the whole thing
        compiled = sass.compile(
            string=all_scss,
            output_style='compressed',
            include_paths=[str(scss_dir)]
        )

        output_file.write_text(compiled, encoding="utf-8")
        Debug.debug(f"Compiled {len(scss_files)} files → {output_file} ({len(compiled)} bytes)")

    except Exception as e:
        Debug.error("SCSS auto-compile failed:", str(e))

# Run it on startup
compile_scss()


class SassCompiler(PatternMatchingEventHandler):
    """Live SASS watcher – recompiles on any .scss/.sass change."""

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            compile_scss()


if os.path.exists(root_path + os.sep + "src" + os.sep + "scss"):
    observer = Observer()
    event_handler = SassCompiler(patterns=["*.sass", "*.scss"])
    observer.schedule(event_handler, path=root_path + os.sep + "src" + os.sep + "scss", recursive=True)
    observer.start()
else:
    Debug.warning("Missing scss folder")


def file_get_contents(file_path):
    """Read file content as string (used by Twig & Swagger)."""
    return Path(file_path).read_text()


# Swagger UI routes
@get(os.getenv("SWAGGER_ROUTE", "/swagger") + "/swagger.json")
async def get_swagger_json(request, response):
    """Return OpenAPI 3.0 JSON specification."""
    json = Swagger.get_json(request)
    return response(json)


@get(os.getenv("SWAGGER_ROUTE", "/swagger"))
async def get_swagger(request, response):
    """Serve interactive Swagger UI page."""
    html = file_get_contents(
        root_path + os.sep + "src" + os.sep + "public" + os.sep + "swagger" + os.sep + "index.html")

    html = html.replace("{SWAGGER_ROUTE}", os.getenv("SWAGGER_ROUTE", "/swagger"))
    return response(html)


async def app(scope, receive, send):
    """ASGI entry point – compatible with Hypercorn (default), Uvicorn, Granian, etc."""
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

            cookie_list = {}
            if "cookie" in webserver.lowercase_headers:
                cookie_list_temp = webserver.lowercase_headers["cookie"].split(";")
                for cookie_value in cookie_list_temp:
                    cookie = cookie_value.split("=", 1)
                    cookie_list[cookie[0].strip()] = cookie[1].strip()

            webserver.cookies = cookie_list

            webserver.session = Session(os.getenv("TINA4_SESSION", "PY_SESS"),
                                        os.getenv("TINA4_SESSION_FOLDER", root_path + os.sep + "sessions"),
                                        os.getenv("TINA4_SESSION_HANDLER", "SessionFileHandler")
                                        )

            if os.getenv("TINA4_SESSION", "PY_SESS") in webserver.cookies:
                webserver.session.load(webserver.cookies[os.getenv("TINA4_SESSION", "PY_SESS")])
            else:
                webserver.cookies[os.getenv("TINA4_SESSION", "PY_SESS")] = webserver.session.start()

            tina4_response, tina4_headers = await webserver.get_response(webserver.method, scope=scope, reader=receive, writer=send,  asgi_response=True)

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
            else:
                if message["type"] == "websocket" and tina4_response.http_code != 200:
                    await send({
                        'type': 'websocket.close',
                    })


def run_web_server(hostname="localhost", port=7145, debug: bool = False):
    """
    Start the Tina4 web server with automatic route discovery.

    Features:
        • Automatically imports all Python files in ./src/ (recursive)
        • Triggers @get, @post, etc. decorators with zero manual imports
        • Hot-reload support via Hypercorn when debug=True
        • Fully backward compatible with existing projects

    Example:
        run_web_server("0.0.0.0", 8000, debug=True)
    """
    import sys
    import importlib
    from pathlib import Path

    # ------------------------------------------------------------------
    # 1. Auto-discover and load all route modules from src/
    # ------------------------------------------------------------------
    def _autoload_routes(root_dir: str = "src"):
        """
        Automatically imports all Python modules under src/
        Ignores:
          - src/public
          - src/templates
          - src/scss
          - any file/folder starting with _
        """
        root_path = Path(root_dir).resolve()
        if not root_path.is_dir():
            Debug.info(f"No '{root_dir}' directory found — skipping autoload.")
            return

        # Folders to completely ignore (and anything inside them)
        ignored_folders = {"public", "templates", "scss"}

        for py_file in root_path.rglob("*.py"):
            # Skip files/folders starting with underscore
            if any(part.startswith("_") for part in py_file.parts):
                continue

            # Skip entire ignored folders (public, templates, scss)
            if any(ignored in py_file.parts for ignored in ignored_folders):
                continue

            try:
                # Build dotted module name: src/api/users.py → src.api.users
                rel_parts = py_file.relative_to(Path.cwd()).with_suffix("").parts
                module_name = ".".join(rel_parts)

                if module_name in sys.modules:
                    if debug:  # debug is global in tina4_python
                        importlib.reload(sys.modules[module_name])
                        Debug.info(f"Hot-reloaded: {module_name}")
                else:
                    importlib.import_module(module_name)
                    Debug.info(f"Autoloaded: {module_name}")

            except Exception as e:
                Debug.error(f"Failed to autoload {py_file}: {e}")

    # Run autoloader (only once per process, but safe to call again)
    _autoload_routes("src")

    # ------------------------------------------------------------------
    # 2. Start the actual web server (unchanged logic)
    # ------------------------------------------------------------------
    Debug.info(Messages.MSG_STARTING_WEBSERVER.format(port=port))
    webserver(hostname, port, debug=debug)  # Pass debug flag down


def webserver(host_name, port, debug: bool = False):
    """Choose and start the appropriate ASGI server."""
    if os.getenv('TINA4_DEFAULT_WEBSERVER', 'FALSE').upper() == 'TRUE':
        Debug.info("Using default webserver")
        web_server = Webserver(host_name, int(port))
        web_server.router_handler = Router()

        try:
            asyncio.run(web_server.serve_forever())
        except KeyboardInterrupt:
            pass
        web_server.server_close()
    else:
        # Runs a hypercorn server
        Debug.debug("Using hypercorn webserver")
        try:
            from hypercorn.config import Config
            from hypercorn.asyncio import serve
            config = Config()
            config.bind = [host_name + ":" + str(port)]
            if debug:
                config.use_reloader = True  # Enables hot-reload like uvicorn --reload
                config.log_level = "debug"
                Debug.info("Hypercorn running in debug mode with auto-reload")
            asyncio.run(serve(app, config))
        except Exception as e:
            Debug.error("Not running Hypercorn webserver", str(e))

    Debug.info(Messages.MSG_SERVER_STOPPED)

# Live coding hot-reload (jurigged)
if importlib.util.find_spec("jurigged"):
    Debug.debug("Jurigged enabled")
    jurigged.watch(["./src/app", "./src/orm", "./src/routes", "./src/templates"])

# ──────────────────────────────────────────────────────────────
# Smart Auto-Start: Only start server if user didn't define control functions
# ──────────────────────────────────────────────────────────────
_CONTROL_FUNCTIONS = {
    "main", "run", "start", "cli", "console", "app",
    "migrate", "migrations", "seed", "seeds", "test", "tests"
}


def _has_control_methods():
    """Scan the actual main file content for 'def main(', 'def migrate(', etc."""
    main_module = sys.modules.get('__main__')
    if not main_module or not hasattr(main_module, '__file__'):
        return True  # REPL / Jupyter

    file_path = main_module.__file__
    Debug.debug(f"Checking {file_path} for control functions")

    if "pytest" in file_path:
        return True

    if "tina4-python" in file_path:
        return True

    if "tina4" in file_path or "uvicorn" in file_path in file_path or "hypercorn" in file_path:
        return True

    if not file_path or not file_path.endswith('.py'):
        return False
    try:
        content = Path(file_path).read_text(encoding="utf-8")
    except Exception as e:
        return False  # Can't read file → assume no control function

    # Regex: looks for "def" + name + "(" anywhere in the file
    pattern = re.compile(r"^\s*def\s+(" + "|".join(re.escape(name) for name in _CONTROL_FUNCTIONS) + r")\s*\(",
                         re.MULTILINE)

    return bool(pattern.search(content))


def _auto_start_server():
    """This runs once at the very end – after user's code is fully loaded"""
    should_we_start = not _has_control_methods()
    Debug.debug("Tina4 - Can we start the webservice ?", should_we_start)
    if not should_we_start:
        control_funcs = [name for name in _CONTROL_FUNCTIONS if name in sys.modules['__main__'].__dict__]
        if control_funcs:
            Debug.debug(
                f"Auto-start disabled — detected control function(s) or other common ASGI webserver: {', '.join(control_funcs)}"
            )
        return

    # Parse optional host:port from command-line
    hostname = "localhost"
    port = 7145

    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        if arg.lower() == "stop":
            Debug.info("Auto-start blocked via 'stop' argument", Constant.TINA4_LOG_INFO)
            return
        if ":" in arg:
            h, _, p = arg.partition(":")
            hostname = h or hostname
            if p.isdigit():
                port = int(p)
        elif arg.isdigit():
            port = int(arg)
    try:
        run_web_server(hostname, port)
    except Exception as e:
        Debug.error(f"Failed to auto-start server: {e}")


_auto_start_server()

