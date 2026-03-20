# Tina4 Server — ASGI server with graceful shutdown and health check.
"""
Zero-dependency ASGI application + built-in dev server.

    from tina4_python.core import run
    run()  # Starts on localhost:7145
"""
import os
import sys
import signal
import asyncio
import importlib
import uuid
from pathlib import Path

from tina4_python.core.request import Request
from tina4_python.core.response import Response
from tina4_python.core.router import Router
from tina4_python.core.middleware import CorsMiddleware, RateLimiter
from tina4_python.debug import Log, set_request_id
from tina4_python import __version__

# Middleware singletons — created once on import
_cors = CorsMiddleware()
_rate_limiter = RateLimiter()


# Track startup time
_start_time: float = 0


def _auto_discover(root_dir: str = "src"):
    """Auto-import all .py files in src/ to trigger route decorators."""
    root = Path(root_dir).resolve()
    if not root.is_dir():
        return

    skip = {"public", "templates", "scss", "locales", "icons"}

    for py_file in sorted(root.rglob("*.py")):
        if any(part.startswith("_") for part in py_file.parts):
            continue
        if any(s in py_file.parts for s in skip):
            continue

        try:
            rel = py_file.relative_to(Path.cwd()).with_suffix("")
            module_name = ".".join(rel.parts)
            if module_name not in sys.modules:
                importlib.import_module(module_name)
                Log.debug(f"Loaded: {module_name}")
        except Exception as e:
            Log.error(f"Failed to load {py_file}: {e}")


def _ensure_folders():
    """Create project folders if missing (auto-repair)."""
    folders = [
        "src/routes", "src/orm", "src/migrations", "src/seeds",
        "src/templates", "src/templates/errors",
        "public", "public/js", "public/css", "public/icons",
        "src/locales", "data", "data/.broken", "logs", "secrets", "tests",
    ]
    for folder in folders:
        Path(folder).mkdir(parents=True, exist_ok=True)


async def _health_handler(request: Request, response: Response) -> Response:
    """Built-in /health endpoint."""
    import time
    broken_dir = Path("data/.broken")
    broken_files = list(broken_dir.glob("*.broken")) if broken_dir.exists() else []

    health = {
        "status": "error" if broken_files else "ok",
        "uptime_seconds": int(time.time() - _start_time),
        "version": __version__,
        "framework": "tina4py",
        "errors": len(broken_files),
    }

    if broken_files:
        # Read latest .broken file
        latest = sorted(broken_files, key=lambda f: f.stat().st_mtime)[-1]
        try:
            import json
            health["latest_error"] = json.loads(latest.read_text())
        except Exception:
            health["latest_error"] = {"file": latest.name}

    code = 503 if broken_files else 200
    return response.status(code).json(health)


# Register health check
Router.add("GET", "/health", _health_handler)


def _render_error_page(status_code: int, path: str, request_id: str, error_message: str = "") -> str | None:
    """Render a styled error page using Frond engine.

    Search order for templates:
    1. src/templates/errors/{code}.twig  (user override)
    2. tina4_python/templates/errors/{code}.twig  (framework default)

    Returns rendered HTML string, or None if no template found.
    """
    from tina4_python.frond.engine import Frond

    template_name = f"errors/{status_code}.twig"
    data = {
        "path": path,
        "request_id": request_id,
        "error_message": error_message,
        "status_code": status_code,
    }

    # 1. Try user override
    user_dir = Path("src/templates")
    if (user_dir / template_name).exists():
        try:
            engine = Frond(str(user_dir))
            return engine.render(template_name, data)
        except Exception:
            pass

    # 2. Try framework default
    framework_dir = Path(__file__).resolve().parent.parent / "templates"
    if (framework_dir / template_name).exists():
        try:
            engine = Frond(str(framework_dir))
            return engine.render(template_name, data)
        except Exception:
            pass

    return None


def _has_index_template() -> bool:
    """Check if the user has an index template in src/templates/."""
    template_dir = Path("src/templates")
    for name in ("index.html", "index.twig", "index.php", "index.erb"):
        if (template_dir / name).is_file():
            return True
    return False


def _render_landing_page() -> str:
    """Render the built-in Tina4 welcome page shown when no / route exists."""
    routes = Router.all()
    route_rows = ""
    for r in routes:
        flags = []
        if r.get("cached"):
            flags.append('<span style="background:#e3f2fd;color:#1565c0;padding:1px 6px;border-radius:3px;font-size:11px">CACHE</span>')
        if r.get("auth"):
            flags.append('<span style="background:#fce4ec;color:#c62828;padding:1px 6px;border-radius:3px;font-size:11px">AUTH</span>')
        flag_str = " ".join(flags)
        path = r.get("path", "")
        method = r.get("method", "")
        route_rows += f'<tr><td><code>{method}</code></td><td><a href="{path}">{path}</a></td><td>{flag_str}</td></tr>'

    is_dev = os.environ.get("TINA4_DEBUG_LEVEL", "").upper() in ("DEBUG", "ALL")
    mode = '<span style="color:#4caf50">Development</span>' if is_dev else '<span style="color:#ff9800">Production</span>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Tina4 Python v{__version__}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; color: #333; }}
        .hero {{ background: linear-gradient(135deg, #1565c0, #1976d2); color: white; padding: 60px 20px; text-align: center; }}
        .hero h1 {{ font-size: 2.5em; margin-bottom: 10px; }}
        .hero p {{ font-size: 1.2em; opacity: 0.9; }}
        .container {{ max-width: 800px; margin: 0 auto; padding: 30px 20px; }}
        .card {{ background: white; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); padding: 24px; margin-bottom: 20px; }}
        .card h2 {{ color: #1565c0; margin-bottom: 12px; font-size: 1.3em; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid #eee; }}
        th {{ color: #666; font-size: 0.85em; text-transform: uppercase; }}
        code {{ background: #e3f2fd; padding: 2px 8px; border-radius: 4px; font-size: 0.9em; color: #1565c0; }}
        a {{ color: #1565c0; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .get-started {{ background: #e3f2fd; border-left: 4px solid #1565c0; padding: 16px; border-radius: 0 8px 8px 0; }}
        .get-started code {{ display: block; margin-top: 8px; background: #333; color: #4caf50; padding: 8px 12px; border-radius: 4px; }}
    </style>
</head>
<body>
    <div class="hero">
        <h1>Tina4 Python</h1>
        <p>This is not a 4ramework &mdash; v{__version__} &mdash; {mode}</p>
    </div>
    <div class="container">
        <div class="card">
            <h2>Registered Routes</h2>
            <table>
                <thead><tr><th>Method</th><th>Path</th><th>Flags</th></tr></thead>
                <tbody>{route_rows}</tbody>
            </table>
        </div>
        <div class="card get-started">
            <h2>Get Started</h2>
            <p>Create your first route file:</p>
            <code>src/routes/hello.py</code>
            <p style="margin-top: 12px">Example route:</p>
            <code>@get("/hello")<br>async def hello(request, response):<br>&nbsp;&nbsp;&nbsp;&nbsp;return response({{"hello": "world"}})</code>
        </div>
        <div class="card">
            <h2>Quick Links</h2>
            <p><a href="/health">/health</a> &mdash; Health check endpoint</p>
            <p style="margin-top: 8px"><a href="/swagger">/swagger</a> &mdash; API documentation</p>
            <p style="margin-top: 8px"><a href="https://tina4.com" target="_blank">tina4.com</a> &mdash; Full documentation</p>
        </div>
    </div>
</body>
</html>"""


async def app(scope: dict, receive, send):
    """ASGI entry point — compatible with uvicorn, hypercorn, granian."""
    if scope["type"] == "lifespan":
        msg = await receive()
        if msg["type"] == "lifespan.startup":
            import time
            global _start_time
            _start_time = time.time()
            await send({"type": "lifespan.startup.complete"})
        elif msg["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
        return

    if scope["type"] != "http":
        return

    # Read full body
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break

    # Build request
    request = Request.from_scope(scope, body)
    request_id = request.headers.get("x-request-id", str(uuid.uuid4())[:8])
    set_request_id(request_id)

    response = Response()
    response.header("x-request-id", request_id)

    # CORS preflight — respond immediately
    if _cors.is_preflight(request):
        _cors.apply(request, response)
        response.status(204)
        await send({"type": "http.response.start", "status": 204, "headers": response.build_headers("")})
        await send({"type": "http.response.body", "body": b""})
        return

    # Rate limiting
    rate_enabled = os.environ.get("TINA4_RATE_LIMIT", "")
    if rate_enabled:
        allowed, info = _rate_limiter.check(request.ip)
        _rate_limiter.apply_headers(response, info)
        if not allowed:
            _cors.apply(request, response)
            response.status(429).json({
                "error": "Too Many Requests",
                "retry_after": info["reset"],
                "status": 429,
            })
            response.header("retry-after", str(info["reset"]))
            await send({"type": "http.response.start", "status": 429, "headers": response.build_headers("")})
            await send({"type": "http.response.body", "body": response.content})
            return

    import time as _time
    _req_start = _time.perf_counter()

    # Dev admin dashboard and API
    _is_dev = os.environ.get("TINA4_DEBUG_LEVEL", "").upper() in ("DEBUG", "ALL") or \
              os.environ.get("TINA4_DEBUG", "").lower() == "true"

    if _is_dev and request.path.startswith("/__dev"):
        from tina4_python.dev_admin import get_api_handlers, render_dashboard
        if request.path == "/__dev/" or request.path == "/__dev":
            response.html(render_dashboard())
        else:
            handlers = get_api_handlers()
            handler_info = handlers.get(request.path)
            if handler_info and request.method == handler_info[0]:
                try:
                    # Dev admin handlers use response(data) callable style
                    def _resp(data, code=200):
                        if isinstance(data, str):
                            response.status(code).html(data)
                        else:
                            response.status(code).json(data)
                        return data
                    _resp.render = response.render
                    result = await handler_info[1](request, _resp)
                except Exception as e:
                    response.status(500).json({"error": str(e)})
            else:
                response.status(404).json({"error": "Not found"})

        # Send dev admin response (skip overlay injection)
        _cors.apply(request, response)
        headers = response.build_headers("")
        await send({"type": "http.response.start", "status": response.status_code, "headers": headers})
        await send({"type": "http.response.body", "body": response.content})
        return

    # Match route
    route, params = Router.match(request.method, request.path)

    if route:
        request._route_params = params
        try:
            result = await route["handler"](request, response)
            if isinstance(result, Response):
                response = result
        except Exception as e:
            Log.error(f"Route error: {e}", path=request.path)
            _write_broken(request, e)
            # Also track in BrokenTracker for admin UI
            if _is_dev:
                try:
                    import traceback as _tb
                    from tina4_python.dev_admin import BrokenTracker
                    BrokenTracker.record(type(e).__name__, str(e), _tb.format_exc(),
                                        {"method": request.method, "path": request.path})
                except Exception:
                    pass
            import traceback
            tb = traceback.format_exc()
            html = _render_error_page(500, request.path, request_id, tb)
            if html:
                response.status(500).html(html)
            else:
                response.status(500).json({
                    "error": "Internal Server Error",
                    "request_id": request_id,
                    "status": 500,
                })
    else:
        # Try serving static file
        static = _try_static(request.path)
        if static:
            response = static
        elif request.path == "/" and not _has_index_template():
            # No "/" route registered and no index template — show default landing page
            response.html(_render_landing_page())
        else:
            html = _render_error_page(404, request.path, request_id)
            if html:
                response.status(404).html(html)
            else:
                response.status(404).json({
                    "error": "Not Found",
                    "path": request.path,
                    "status": 404,
                })

    # Apply CORS headers to all responses
    _cors.apply(request, response)

    # Dev mode: inject overlay button into HTML responses
    if _is_dev and response.content_type and "text/html" in response.content_type:
        if not request.path.startswith("/__dev"):
            try:
                from tina4_python.dev_admin import render_overlay_script
                overlay = render_overlay_script().encode()
                content = response.content
                # Inject before </body> if present, else append
                if b"</body>" in content:
                    content = content.replace(b"</body>", overlay + b"\n</body>", 1)
                else:
                    content = content + overlay
                response.content = content
            except Exception:
                pass

    # Dev mode: capture request in inspector
    if _is_dev:
        try:
            from tina4_python.dev_admin import RequestInspector
            duration = (_time.perf_counter() - _req_start) * 1000
            RequestInspector.capture(
                request.method, request.path, response.status_code, duration,
                body_size=len(response.content) if response.content else 0,
                ip=request.ip,
            )
        except Exception:
            pass

    # ETag check — 304 Not Modified
    if_none_match = request.headers.get("if-none-match", "")

    # Build and send response
    accept_encoding = request.headers.get("accept-encoding", "")
    headers = response.build_headers(accept_encoding)

    # Check ETag after building (since build_headers computes it)
    etag = ""
    for name, value in headers:
        if name == b"etag":
            etag = value.decode()
            break
    if if_none_match and if_none_match == etag:
        await send({"type": "http.response.start", "status": 304, "headers": []})
        await send({"type": "http.response.body", "body": b""})
        return

    await send({"type": "http.response.start", "status": response.status_code, "headers": headers})
    await send({"type": "http.response.body", "body": response.content})


def _try_static(path: str) -> Response | None:
    """Serve static files. Searches multiple directories.

    Search order (first match wins):
    1. TINA4_PUBLIC_DIR env var (if set)
    2. public/           (simple, IDE-friendly)
    3. src/public/       (nested convention)
    4. tina4_python/public/  (framework built-in assets)
    """
    clean = path.lstrip("/")
    custom = os.environ.get("TINA4_PUBLIC_DIR")
    candidates = []
    if custom:
        candidates.append(Path(custom) / clean)
    candidates.append(Path("public") / clean)
    candidates.append(Path("src/public") / clean)
    # Framework built-in assets (tina4.js, tina4.min.css, tina4-dev-admin.js, etc.)
    candidates.append(Path(__file__).resolve().parent.parent / "public" / clean)

    for file_path in candidates:
        if file_path.is_file():
            resp = Response()
            resp.file(str(file_path))
            return resp
    return None


def _write_broken(request: Request, error: Exception):
    """Write a .broken file for the health check."""
    import json
    import traceback
    from datetime import datetime, timezone

    broken_dir = Path("data/.broken")
    broken_dir.mkdir(parents=True, exist_ok=True)

    error_type = type(error).__name__
    ts = datetime.now(timezone.utc)
    filename = f"{ts.strftime('%Y-%m-%dT%H%M%S')}_{error_type}.broken"

    # Deduplicate — update existing if same error type + location
    tb_lines = traceback.format_exception(type(error), error, error.__traceback__)
    location = tb_lines[-2].strip() if len(tb_lines) >= 2 else "unknown"

    for existing in broken_dir.glob("*.broken"):
        if error_type in existing.name:
            try:
                data = json.loads(existing.read_text())
                data["last_seen"] = ts.isoformat()
                data["occurrence_count"] = data.get("occurrence_count", 1) + 1
                existing.write_text(json.dumps(data, indent=2))
                return
            except Exception:
                pass

    data = {
        "timestamp": ts.isoformat(),
        "request_id": request.headers.get("x-request-id", ""),
        "error_type": error_type,
        "message": str(error),
        "location": location,
        "stack_trace": "".join(tb_lines),
        "request": {
            "method": request.method,
            "path": request.path,
            "ip": request.ip,
        },
        "first_seen": ts.isoformat(),
        "last_seen": ts.isoformat(),
        "occurrence_count": 1,
        "resolved": False,
    }

    (broken_dir / filename).write_text(json.dumps(data, indent=2))


def run(host: str = "localhost", port: int = 7145):
    """Start the Tina4 dev server.

    Discovers routes from src/, starts ASGI server, handles shutdown.
    """
    import time
    global _start_time
    _start_time = time.time()

    # Init logger
    is_production = os.environ.get("TINA4_ENV", "development") == "production"
    log_level = os.environ.get("TINA4_LOG_LEVEL", "debug" if not is_production else "info")
    Log.init(level=log_level, production=is_production)

    # Banner
    print(f"\n  Tina4 Python v{__version__}")
    print(f"  {'─' * 30}")

    # Ensure folders
    _ensure_folders()

    # Load .env
    from tina4_python.dotenv import load_env
    load_env()

    # Auto-discover routes
    _auto_discover("src")
    route_count = len(Router.all())
    Log.info(f"Discovered {route_count} routes")

    # Parse CLI args
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        if ":" in arg:
            h, _, p = arg.partition(":")
            host = h or host
            port = int(p) if p.isdigit() else port
        elif arg.isdigit():
            port = int(arg)

    display = "localhost" if host in ("0.0.0.0", "::") else host
    Log.info(f"Server started http://{display}:{port}")

    # Graceful shutdown
    shutdown = asyncio.Event()

    def _signal_handler(*_):
        Log.info("Shutting down gracefully...")
        shutdown.set()

    # Run ASGI server
    async def _serve():
        from asyncio import start_server

        async def _handle_connection(reader, writer):
            """Minimal HTTP/1.1 → ASGI bridge for dev server."""
            try:
                raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30)
            except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError):
                writer.close()
                return

            lines = raw.decode(errors="replace").split("\r\n")
            if not lines:
                writer.close()
                return

            # Parse request line
            parts = lines[0].split(" ", 2)
            if len(parts) < 2:
                writer.close()
                return

            method = parts[0]
            raw_path = parts[1]
            path, _, qs = raw_path.partition("?")

            # Parse headers
            headers = []
            content_length = 0
            for line in lines[1:]:
                if ":" in line:
                    name, _, value = line.partition(":")
                    name = name.strip().lower()
                    value = value.strip()
                    headers.append([name.encode(), value.encode()])
                    if name == "content-length":
                        content_length = int(value)

            # Read body
            body = b""
            if content_length > 0:
                body = await asyncio.wait_for(
                    reader.readexactly(content_length), timeout=30
                )

            # Build ASGI scope
            addr = writer.get_extra_info("peername") or ("127.0.0.1", 0)
            scope = {
                "type": "http",
                "method": method,
                "path": path,
                "query_string": qs.encode(),
                "headers": headers,
                "server": (host, port),
                "client": addr,
            }

            # Capture response
            resp_started = False
            resp_status = 200
            resp_headers = []
            resp_body = b""

            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}

            async def send(msg):
                nonlocal resp_started, resp_status, resp_headers, resp_body
                if msg["type"] == "http.response.start":
                    resp_started = True
                    resp_status = msg["status"]
                    resp_headers = msg.get("headers", [])
                elif msg["type"] == "http.response.body":
                    resp_body = msg.get("body", b"")

            await app(scope, receive, send)

            # Write HTTP/1.1 response
            status_line = f"HTTP/1.1 {resp_status} OK\r\n"
            writer.write(status_line.encode())
            for name, value in resp_headers:
                writer.write(name + b": " + value + b"\r\n")
            writer.write(b"\r\n")
            writer.write(resp_body)
            await writer.drain()
            writer.close()

        server = await start_server(_handle_connection, host, port)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                pass  # Windows

        await shutdown.wait()
        server.close()
        await server.wait_closed()
        Log.info("Server stopped.")

    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        pass
