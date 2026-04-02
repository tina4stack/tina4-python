# Tina4 Server — ASGI server with graceful shutdown and health check.
"""
Zero-dependency ASGI application + built-in dev server.

    from tina4_python.core import run
    run()  # Starts on localhost:7146
"""
import os
import sys
import signal
import asyncio
import contextvars
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


# ContextVar to signal that the current request is being served on the AI dev port
_ai_port_ctx: contextvars.ContextVar[bool] = contextvars.ContextVar("_ai_port_ctx", default=False)

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
    from tina4_python.core.response import get_frond, get_framework_frond

    template_name = f"errors/{status_code}.twig"
    data = {
        "path": path,
        "request_id": request_id,
        "error_message": error_message,
        "status_code": status_code,
    }

    # 1. Try user override (singleton engine with custom filters/globals)
    try:
        return get_frond().render(template_name, data)
    except (FileNotFoundError, Exception):
        pass

    # 2. Try framework default (singleton, filters/globals synced)
    fw_engine = get_framework_frond()
    if fw_engine is not None:
        try:
            return fw_engine.render(template_name, data)
        except Exception:
            pass

    return None


_template_cache: dict[str, str] | None = None


def _resolve_template(path: str) -> str | None:
    """Resolve a URL path to a template file in src/templates/.
    Dev mode: checks filesystem every time for live changes.
    Production: uses a cached lookup built once at startup.
    """
    clean_path = path.strip("/") or "index"
    is_dev = os.environ.get("TINA4_DEBUG", "false").lower() in ("true", "1", "yes")

    if is_dev:
        template_dir = Path("src/templates")
        for ext in (".twig", ".html"):
            candidate = clean_path + ext
            if (template_dir / candidate).is_file():
                return candidate
        return None

    global _template_cache
    if _template_cache is None:
        _build_template_cache()
    return _template_cache.get(clean_path)


def _build_template_cache() -> None:
    """Scan src/templates/ once and build url_path -> template_file lookup."""
    global _template_cache
    _template_cache = {}
    template_dir = Path("src/templates")
    if not template_dir.is_dir():
        return
    for f in template_dir.rglob("*"):
        if not f.is_file() or f.suffix not in (".twig", ".html"):
            continue
        rel = str(f.relative_to(template_dir)).replace("\\", "/")
        url_path = rel.rsplit(".", 1)[0]
        if url_path not in _template_cache:
            _template_cache[url_path] = rel


def _is_gallery_deployed(name: str) -> bool:
    """Check if a gallery item's files exist in the project's src/ folder."""
    import json
    gallery_dir = Path(__file__).resolve().parent.parent / "gallery" / name
    meta_file = gallery_dir / "meta.json"
    if not meta_file.exists():
        return False
    src_dir = gallery_dir / "src"
    if not src_dir.exists():
        return False
    project_src = Path.cwd() / "src"
    for f in src_dir.rglob("*"):
        if f.is_file():
            rel = f.relative_to(src_dir)
            if not (project_src / rel).exists():
                return False
    return True


def _gallery_btn(name: str, try_url: str) -> str:
    """Render a Try It or View button depending on deployment state."""
    if _is_gallery_deployed(name):
        return f'<button class="try-btn" style="background:#22c55e;" onclick="window.location.href=\'{try_url}\'" data-deployed="1">View &#8599;</button>'
    return f'<button class="try-btn" onclick="deployGallery(\'{name}\',\'{try_url}\')">Try It</button>'


def _render_landing_page() -> str:
    """Render the built-in Tina4 welcome page shown when no / route exists."""
    port = os.environ.get("PORT", "7146")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tina4Python</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;display:flex;flex-direction:column;align-items:center;position:relative}}
.bg-watermark{{position:fixed;bottom:-5%;right:-5%;width:45%;opacity:0.04;pointer-events:none;z-index:0}}
.hero{{text-align:center;z-index:1;padding:3rem 2rem 2rem}}
.logo{{width:120px;height:120px;margin-bottom:1.5rem}}
h1{{font-size:3rem;font-weight:700;margin-bottom:0.25rem;letter-spacing:-1px}}
.tagline{{color:#64748b;font-size:1.1rem;margin-bottom:2rem}}
.actions{{display:flex;gap:0.75rem;justify-content:center;flex-wrap:wrap;margin-bottom:2.5rem}}
.btn{{padding:0.6rem 1.5rem;border-radius:0.5rem;font-size:0.9rem;font-weight:600;cursor:pointer;text-decoration:none;transition:all 0.15s;border:1px solid #334155;color:#94a3b8;background:transparent;min-width:140px;text-align:center;display:inline-block}}
.btn:hover{{border-color:#64748b;color:#e2e8f0}}
.btn-primary{{background:#3572A5;color:#fff;border-color:#3572A5}}
.btn-primary:hover{{opacity:0.9;transform:translateY(-1px)}}
.status{{display:flex;gap:2rem;justify-content:center;align-items:center;color:#64748b;font-size:0.85rem;margin-bottom:1.5rem}}
.status .dot{{width:8px;height:8px;border-radius:50%;background:#22c55e;display:inline-block;margin-right:0.4rem}}
.footer{{color:#334155;font-size:0.8rem;letter-spacing:0.5px}}
.section{{z-index:1;width:100%;max-width:800px;padding:0 2rem;margin-bottom:2.5rem}}
.card{{background:#1e293b;border-radius:0.75rem;padding:2rem;border:1px solid #334155}}
.card h2{{font-size:1.4rem;font-weight:600;margin-bottom:1.25rem;color:#e2e8f0}}
.code-block{{background:#0f172a;border-radius:0.5rem;padding:1.25rem;overflow-x:auto;font-family:'SF Mono',SFMono-Regular,Consolas,'Liberation Mono',Menlo,monospace;font-size:0.85rem;line-height:1.6;color:#4ade80;border:1px solid #1e293b}}
.gallery{{z-index:1;width:100%;max-width:800px;padding:0 2rem;margin-bottom:3rem}}
.gallery h2{{font-size:1.4rem;font-weight:600;margin-bottom:1.25rem;color:#e2e8f0;text-align:center}}
.gallery-grid{{display:flex;gap:1rem;flex-wrap:wrap}}
.gallery-card{{flex:1 1 220px;background:#1e293b;border:1px solid #334155;border-radius:0.75rem;padding:1.5rem;position:relative;overflow:hidden}}
.gallery-card .accent{{position:absolute;top:0;left:0;right:0;height:3px}}
.gallery-card .accent-blue{{background:#3572A5}}
.gallery-card .accent-green{{background:#22c55e}}
.gallery-card .accent-purple{{background:#a78bfa}}
.gallery-card .icon{{font-size:1.5rem;margin-bottom:0.75rem}}
.gallery-card h3{{font-size:1rem;font-weight:600;margin-bottom:0.5rem;color:#e2e8f0}}
.gallery-card p{{font-size:0.85rem;color:#94a3b8;line-height:1.5}}
.gallery-card .try-btn{{display:inline-block;margin-top:0.75rem;padding:0.3rem 0.8rem;background:#3572A5;color:#fff;border:none;border-radius:0.375rem;font-size:0.75rem;font-weight:600;cursor:pointer;transition:opacity 0.15s}}
.gallery-card .try-btn:hover{{opacity:0.85}}
@keyframes wiggle{{0%{{transform:rotate(0deg)}}15%{{transform:rotate(14deg)}}30%{{transform:rotate(-10deg)}}45%{{transform:rotate(8deg)}}60%{{transform:rotate(-4deg)}}75%{{transform:rotate(2deg)}}100%{{transform:rotate(0deg)}}}}
.star-wiggle{{display:inline-block;transform-origin:center}}
</style>
</head>
<body>
<img src="/images/tina4-logo-icon.webp" class="bg-watermark" alt="">
<div class="hero">
    <img src="/images/tina4-logo-icon.webp" class="logo" alt="Tina4">
    <h1>Tina4Python</h1>
    <p class="tagline">This Is Now A 4Framework</p>
    <div class="actions">
        <a href="https://tina4.com/python" class="btn" target="_blank">Website</a>
        <a href="/__dev" class="btn">Dev Admin</a>
        <a href="#gallery" class="btn">Gallery</a>
        <a href="https://github.com/tina4stack/tina4-python" class="btn" target="_blank">GitHub</a>
        <a href="https://github.com/tina4stack/tina4-python/stargazers" class="btn" target="_blank"><span class="star-wiggle">&#9734;</span> Star</a>
    </div>
    <div class="status">
        <span><span class="dot"></span>Server running</span>
        <span>Port {port}</span>
        <span>v{__version__}</span>
    </div>
    <p class="footer">Zero dependencies &middot; Convention over configuration</p>
</div>
<div class="section">
    <div class="card">
        <h2>Getting Started</h2>
        <pre class="code-block"><code><span style="color:#64748b"># app.py</span>
<span style="color:#c084fc">from</span> tina4_python.core <span style="color:#c084fc">import</span> run
<span style="color:#c084fc">from</span> tina4_python.core.router <span style="color:#c084fc">import</span> get

<span style="color:#fbbf24">@get</span>(<span style="color:#4ade80">"/hello"</span>)
<span style="color:#c084fc">async def</span> <span style="color:#38bdf8">hello</span>(request, response):
    <span style="color:#c084fc">return</span> response({{"message": <span style="color:#4ade80">"Hello World!"</span>}})

run()  <span style="color:#64748b"># starts on port 7146</span></code></pre>
    </div>
</div>
<div class="gallery">
    <h2 id="gallery">What You Can Build</h2>
    <p style="color:#64748b;font-size:0.85rem;text-align:center;margin-bottom:1.25rem;">Click <strong style="color:#94a3b8;">Try It</strong> to deploy working example code into your <code style="color:#4ade80;">src/</code> folder</p>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem;">
        <div class="gallery-card">
            <div class="accent accent-blue"></div>
            <div class="icon">&#128640;</div>
            <h3>REST API</h3>
            <p>Define routes with one decorator</p>
            <pre style="background:#0f172a;color:#4ade80;padding:0.75rem;border-radius:0.375rem;font-size:0.75rem;overflow-x:auto;margin-top:0.5rem;font-family:'SF Mono',SFMono-Regular,Consolas,monospace;">@get("/api/users")
async def users(req, res):
    return res({{"users": []}})</pre>
            {_gallery_btn('rest-api', '/api/gallery/hello')}
        </div>
        <div class="gallery-card">
            <div class="accent accent-green"></div>
            <div class="icon">&#128451;</div>
            <h3>ORM</h3>
            <p>Active record models, zero config</p>
            <pre style="background:#0f172a;color:#4ade80;padding:0.75rem;border-radius:0.375rem;font-size:0.75rem;overflow-x:auto;margin-top:0.5rem;font-family:'SF Mono',SFMono-Regular,Consolas,monospace;">class User(ORM):
    id = IntegerField(primary_key=True)
    name = StringField()</pre>
            {_gallery_btn('orm', '/api/gallery/products')}
        </div>
        <div class="gallery-card">
            <div class="accent accent-purple"></div>
            <div class="icon">&#128274;</div>
            <h3>Auth</h3>
            <p>JWT tokens built-in</p>
            <pre style="background:#0f172a;color:#4ade80;padding:0.75rem;border-radius:0.375rem;font-size:0.75rem;overflow-x:auto;margin-top:0.5rem;font-family:'SF Mono',SFMono-Regular,Consolas,monospace;">token = Auth.get_token({{"user_id": 1}})
valid = Auth.valid_token(token)</pre>
            {_gallery_btn('auth', '/gallery/auth')}
        </div>
        <div class="gallery-card">
            <div class="accent accent-blue"></div>
            <div class="icon">&#9889;</div>
            <h3>Queue</h3>
            <p>Background jobs, no Redis needed</p>
            <pre style="background:#0f172a;color:#4ade80;padding:0.75rem;border-radius:0.375rem;font-size:0.75rem;overflow-x:auto;margin-top:0.5rem;font-family:'SF Mono',SFMono-Regular,Consolas,monospace;">queue = Queue(topic="emails")
queue.produce("emails", {{"to": "a@b.com"}})</pre>
            {_gallery_btn('queue', '/api/gallery/queue/status')}
        </div>
        <div class="gallery-card">
            <div class="accent accent-green"></div>
            <div class="icon">&#128196;</div>
            <h3>Templates</h3>
            <p>Twig templates with auto-reload</p>
            <pre style="background:#0f172a;color:#4ade80;padding:0.75rem;border-radius:0.375rem;font-size:0.75rem;overflow-x:auto;margin-top:0.5rem;font-family:'SF Mono',SFMono-Regular,Consolas,monospace;">@template("dashboard.twig")
@get("/dashboard")
async def dash(req, res):
    return {{"title": "Home"}}</pre>
            {_gallery_btn('templates', '/gallery/page')}
        </div>
        <div class="gallery-card">
            <div class="accent accent-purple"></div>
            <div class="icon">&#128225;</div>
            <h3>Database</h3>
            <p>Multi-engine, one API</p>
            <pre style="background:#0f172a;color:#4ade80;padding:0.75rem;border-radius:0.375rem;font-size:0.75rem;overflow-x:auto;margin-top:0.5rem;font-family:'SF Mono',SFMono-Regular,Consolas,monospace;">db = Database("sqlite:///app.db")
result = db.fetch("SELECT * FROM users")
for row in result: print(row["name"])</pre>
            {_gallery_btn('database', '/api/gallery/db/tables')}
        </div>
        <div class="gallery-card">
            <div class="accent accent-blue"></div>
            <div class="icon">&#128680;</div>
            <h3>Error Overlay</h3>
            <p>Rich debug page with source code</p>
            <pre style="background:#0f172a;color:#4ade80;padding:0.75rem;border-radius:0.375rem;font-size:0.75rem;overflow-x:auto;margin-top:0.5rem;font-family:'SF Mono',SFMono-Regular,Consolas,monospace;">user = {{"name": "Alice"}}
role = user["role"]  # KeyError!</pre>
            {_gallery_btn('error-overlay', '/api/gallery/crash')}
        </div>
    </div>
</div>
<script>
function deployGallery(name, tryUrl) {{
    var btn = event.target;
    if (btn.dataset.deployed) {{
        window.open(tryUrl, '_blank');
        return;
    }}
    if (!confirm('This will add example code to your src/ folder. Continue?')) return;
    btn.textContent = 'Deploying...';
    btn.disabled = true;
    fetch('/__dev/api/gallery/deploy', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{name: name}})
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(d) {{
        if (d.error) {{
            btn.textContent = 'Try It';
            btn.disabled = false;
            alert('Deploy failed: ' + d.error);
        }} else {{
            btn.textContent = 'View \u2197';
            btn.style.background = '#22c55e';
            btn.disabled = false;
            btn.dataset.deployed = '1';
            // Wait for the newly deployed route to become reachable before navigating
            var attempts = 0;
            var maxAttempts = 5;
            function pollRoute() {{
                fetch(tryUrl, {{method: 'HEAD'}}).then(function() {{
                    window.location.href = tryUrl;
                }}).catch(function() {{
                    attempts++;
                    if (attempts < maxAttempts) {{
                        setTimeout(pollRoute, 500);
                    }} else {{
                        window.location.href = tryUrl;
                    }}
                }});
            }}
            setTimeout(pollRoute, 500);
        }}
    }})
    .catch(function(e) {{
        btn.textContent = 'Try It';
        btn.disabled = false;
        alert('Deploy failed: ' + e.message);
    }});
}}
(function(){{
    var star=document.querySelector('.star-wiggle');
    if(!star)return;
    function doWiggle(){{
        star.style.animation='wiggle 1.2s ease-in-out';
        star.addEventListener('animationend',function onEnd(){{
            star.removeEventListener('animationend',onEnd);
            star.style.animation='none';
            var delay=3000+Math.random()*15000;
            setTimeout(doWiggle,delay);
        }});
    }}
    setTimeout(doWiggle,3000);
}})();
</script>
</body>
</html>"""


# ── WebSocket support ──────────────────────────────────────────
from tina4_python.websocket import WebSocketConnection, WebSocketManager

_ws_manager = WebSocketManager()


async def _handle_asgi_websocket(scope: dict, receive, send):
    """Handle ASGI WebSocket connections, dispatching to registered routes."""
    path = scope.get("path", "/")

    route, params = Router.match_ws(path)
    if route is None:
        # No matching WebSocket route — reject
        await send({"type": "websocket.close", "code": 4004})
        return

    # Accept the connection
    msg = await receive()
    if msg["type"] != "websocket.connect":
        return
    await send({"type": "websocket.accept"})

    handler = route["handler"]

    # Create a lightweight connection wrapper for ASGI WebSocket
    conn = _AsgiWebSocketConnection(scope, receive, send, path, params, _ws_manager)
    _ws_manager.add(conn)

    # Fire "open" event
    try:
        await handler(conn, "open", None)
    except Exception as e:
        Log.error(f"WebSocket open handler error: {e}")

    # Message loop
    try:
        while True:
            msg = await receive()
            if msg["type"] == "websocket.receive":
                data = msg.get("text") or (msg.get("bytes", b"").decode("utf-8", errors="replace") if msg.get("bytes") else "")
                try:
                    await handler(conn, "message", data)
                except Exception as e:
                    Log.error(f"WebSocket message handler error: {e}")
            elif msg["type"] == "websocket.disconnect":
                break
    except Exception:
        pass
    finally:
        # Fire "close" event
        try:
            await handler(conn, "close", None)
        except Exception as e:
            Log.error(f"WebSocket close handler error: {e}")
        _ws_manager.remove(conn)


class _AsgiWebSocketConnection:
    """WebSocket connection wrapper for ASGI servers (uvicorn, etc.)."""

    def __init__(self, scope, receive, send, path, params, manager):
        self.id = str(uuid.uuid4())[:8]
        self.path = path
        self.params = params
        self.headers = {
            k.decode(): v.decode()
            for k, v in scope.get("headers", [])
        }
        self._scope = scope
        self._receive = receive
        self._send = send
        self._manager = manager
        self._closed = False

        client = scope.get("client", ("unknown", 0))
        self.ip = client[0] if client else "unknown"
        import time
        self.connected_at = time.time()

    @property
    def closed(self) -> bool:
        return self._closed

    async def send(self, message: str | bytes):
        """Send a text or binary message."""
        if self._closed:
            return
        try:
            if isinstance(message, bytes):
                await self._send({"type": "websocket.send", "bytes": message})
            else:
                await self._send({"type": "websocket.send", "text": str(message)})
        except Exception:
            self._closed = True

    async def send_json(self, data):
        """Send data as JSON."""
        import json
        await self.send(json.dumps(data))

    async def broadcast(self, message: str | bytes, exclude_self: bool = False):
        """Broadcast to all connections on the same path."""
        await self._manager.broadcast(self.path, message,
                                      exclude=self.id if exclude_self else None)

    async def broadcast_to(self, path: str, message: str | bytes):
        """Broadcast to all connections on a different path."""
        await self._manager.broadcast(path, message)

    async def close(self, code: int = 1000, reason: str = ""):
        """Close the WebSocket connection."""
        if self._closed:
            return
        self._closed = True
        try:
            await self._send({"type": "websocket.close", "code": code})
        except Exception:
            pass


async def _handle_dev_websocket(reader, writer, headers, path):
    """Handle WebSocket upgrade in the built-in dev server, dispatching to registered routes."""
    route, params = Router.match_ws(path)
    if route is None:
        writer.write(b"HTTP/1.1 404 Not Found\r\n\r\n")
        await writer.drain()
        writer.close()
        return

    from tina4_python.websocket import compute_accept_key

    ws_key = headers.get("sec-websocket-key")
    if not ws_key:
        writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        await writer.drain()
        writer.close()
        return

    # Send upgrade response
    accept = compute_accept_key(ws_key)
    response_data = (
        f"HTTP/1.1 101 Switching Protocols\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
    )
    writer.write(response_data.encode())
    await writer.drain()

    ws = WebSocketConnection(reader, writer, path, headers, params)
    _ws_manager.add(ws)

    handler = route["handler"]

    # Fire "open" event
    try:
        await handler(ws, "open", None)
    except Exception as e:
        Log.error(f"WebSocket open handler error: {e}")

    # Wire up message/close callbacks and run the frame loop
    async def on_message(message):
        try:
            await handler(ws, "message", message)
        except Exception as e:
            Log.error(f"WebSocket message handler error: {e}")

    ws._on_message = on_message

    original_on_close = ws._on_close

    async def on_close():
        try:
            await handler(ws, "close", None)
        except Exception as e:
            Log.error(f"WebSocket close handler error: {e}")
        _ws_manager.remove(ws)
        if original_on_close:
            result = original_on_close()
            if asyncio.iscoroutine(result):
                await result

    ws._on_close = on_close

    # Enter the frame loop
    await ws._run()

    # Ensure cleanup if _run exits without triggering on_close
    if not ws._closed:
        ws._closed = True
        try:
            await handler(ws, "close", None)
        except Exception:
            pass
        _ws_manager.remove(ws)
        try:
            ws.writer.close()
        except Exception:
            pass



def _init_session(request: Request) -> None:
    """Auto-start session from cookie. Modifies request.session in place."""
    if request.session is not None:
        return
    try:
        from tina4_python.session import Session
        cookie_header = request.headers.get("cookie", "")
        sid_match = None
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("tina4_session="):
                sid_match = part.split("=", 1)[1]
                break
        sess = Session()
        sess.start(sid_match)
        request.session = sess
        # Probabilistic garbage collection (1% of requests)
        import random
        if random.randint(1, 100) == 1:
            sess.gc()
    except Exception:
        pass  # Session module not available — session stays None


def _handle_rate_limit(request: Request, response: Response) -> Response | None:
    """Check rate limit. Returns an error Response if blocked, else None."""
    rate_enabled = os.environ.get("TINA4_RATE_LIMIT", "")
    if not rate_enabled:
        return None
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
        return response
    return None


async def _handle_dev_admin(request: Request, response: Response) -> Response:
    """Serve the /__dev dashboard and API routes."""
    from tina4_python.dev_admin import get_api_handlers, render_dashboard
    if request.path in ("/__dev/", "/__dev"):
        response.html(render_dashboard())
    else:
        handlers = get_api_handlers()
        handler_info = handlers.get(request.path)
        if handler_info and request.method == handler_info[0]:
            try:
                def _resp(data, code=200):
                    if isinstance(data, str):
                        response.status(code).html(data)
                    else:
                        response.status(code).json(data)
                    return data
                _resp.render = response.render
                import inspect
                _tsig = inspect.signature(handler_info[1])
                _tpcount = len(_tsig.parameters)
                _tparams = list(_tsig.parameters.values())
                if _tpcount == 0:
                    await handler_info[1]()
                elif _tpcount == 1:
                    _tann = _tparams[0].annotation
                    if _tann is Request or (isinstance(_tann, str) and _tann in ("Request", "request")):
                        await handler_info[1](request)
                    else:
                        await handler_info[1](_resp)
                else:
                    await handler_info[1](request, _resp)
            except Exception as e:
                response.status(500).json({"error": str(e)})
        else:
            response.status(404).json({"error": "Not found"})
    _cors.apply(request, response)
    return response


def _handle_swagger(request: Request, response: Response) -> Response | None:
    """Serve /swagger UI and /swagger/openapi.json. Returns Response or None."""
    if request.path in ("/swagger", "/swagger/"):
        swagger_html = (
            '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
            '<title>API Documentation</title>'
            '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">'
            '</head><body><div id="swagger-ui"></div>'
            '<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>'
            '<script>SwaggerUIBundle({ url: "/swagger/openapi.json", dom_id: "#swagger-ui" });</script>'
            '</body></html>'
        )
        response.html(swagger_html)
        _cors.apply(request, response)
        return response
    if request.path == "/swagger/openapi.json":
        from tina4_python.swagger import Swagger as _SwaggerGen
        _swagger = _SwaggerGen()
        _spec = _swagger.generate(Router.get_routes())
        response.json(_spec)
        _cors.apply(request, response)
        return response
    return None


def _check_auth(request: Request, response: Response, route: dict) -> bool:
    """Validate auth on a route. Returns True if handler should be skipped."""
    if not route.get("auth_required"):
        return False
    _auth_header = request.headers.get("authorization", "")
    _api_key = os.environ.get("TINA4_API_KEY", os.environ.get("API_KEY", ""))
    _auth_ok = False
    if _auth_header and _auth_header.startswith("Bearer "):
        _token = _auth_header[7:]
        if _api_key and _token == _api_key:
            _auth_ok = True
        else:
            try:
                from tina4_python.auth import Auth
                if Auth.valid_token_static(_token):
                    _auth_ok = True
            except Exception:
                pass
    if not _auth_ok:
        response.status(401).json({
            "error": "Unauthorized",
            "message": "Valid authorization token required",
            "status": 401,
        })
        return True
    return False


def _run_before_middleware(request: Request, response: Response, route: dict) -> tuple[Request, Response, bool]:
    """Run before_* middleware methods. Returns (request, response, skip_handler)."""
    skip = False
    for _mw_cls in route.get("middleware", []):
        _mw_inst = _mw_cls() if isinstance(_mw_cls, type) else _mw_cls
        for _attr_name in dir(_mw_inst):
            if _attr_name.startswith("before_"):
                _mw_method = getattr(_mw_inst, _attr_name)
                if callable(_mw_method):
                    _mw_result = _mw_method(request, response)
                    if _mw_result is not None:
                        request, response = _mw_result
                        if response.status_code >= 400:
                            skip = True
                            break
        if skip:
            break
    return request, response, skip


def _run_after_middleware(request: Request, response: Response, route: dict) -> tuple[Request, Response]:
    """Run after_* middleware methods."""
    for _mw_cls in route.get("middleware", []):
        _mw_inst = _mw_cls() if isinstance(_mw_cls, type) else _mw_cls
        for _attr_name in dir(_mw_inst):
            if _attr_name.startswith("after_"):
                _mw_method = getattr(_mw_inst, _attr_name)
                if callable(_mw_method):
                    _mw_result = _mw_method(request, response)
                    if _mw_result is not None:
                        request, response = _mw_result
    return request, response


async def _invoke_handler(request: Request, response: Response, route: dict, params: dict) -> Response:
    """Call the route handler with the correct arguments."""
    import inspect
    _sig = inspect.signature(route["handler"])
    _params = list(_sig.parameters.values())
    _pcount = len(_params)

    _args = []
    _remaining = []
    for p in _params:
        if p.name in params:
            _args.append(params[p.name])
        else:
            _remaining.append(p)

    if len(_remaining) == 1:
        _ann = _remaining[0].annotation
        if _ann is Request or (isinstance(_ann, str) and _ann in ("Request", "request")):
            _args.append(request)
        else:
            _args.append(response)
    elif len(_remaining) >= 2:
        _args.append(request)
        _args.append(response)

    if _pcount == 0:
        result = await route["handler"]()
    else:
        result = await route["handler"](*_args)
    if isinstance(result, Response):
        response = result
    return response


def _handle_route_error(
    error: Exception, request: Request, response: Response,
    request_id: str, is_dev: bool,
) -> Response:
    """Format an error response for a failed route handler."""
    Log.error(f"Route error: {error}", path=request.path)
    _write_broken(request, error)
    if is_dev:
        try:
            import traceback as _tb
            from tina4_python.dev_admin import BrokenTracker
            BrokenTracker.record(
                type(error).__name__, str(error), _tb.format_exc(),
                {"method": request.method, "path": request.path},
            )
        except Exception:
            pass
        from tina4_python.debug.error_overlay import render_error_overlay
        overlay_html = render_error_overlay(error, request)
        response.status(500).html(overlay_html)
    else:
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
    return response


def _handle_no_route(request: Request, response: Response, request_id: str) -> Response:
    """Serve static files, templates, landing page, or 404."""
    static = _try_static(request.path)
    if static:
        return static
    tpl_file = _resolve_template(request.path)
    if tpl_file:
        from tina4_python.core.response import get_frond
        html = get_frond().render(tpl_file, {})
        response.html(html)
    elif request.path == "/":
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
    return response


def _finalize_response(
    request: Request, response: Response, route: dict | None,
    request_id: str, is_dev: bool, req_start: float,
) -> Response:
    """Apply CORS, dev toolbar, request inspector, and session cookie."""
    _cors.apply(request, response)

    # Dev toolbar injection
    if is_dev and response.content_type and "text/html" in response.content_type:
        if not request.path.startswith("/__dev"):
            try:
                from tina4_python.dev_admin import render_dev_toolbar
                matched_pattern = route["path"] if route else "-"
                toolbar = render_dev_toolbar(
                    request.method, request.path, matched_pattern,
                    request_id, len(Router.get_routes()),
                ).encode()
                content_body = response.content
                if b"</body>" in content_body:
                    content_body = content_body.replace(b"</body>", toolbar + b"\n</body>", 1)
                else:
                    content_body = content_body + toolbar
                response.content = content_body
            except Exception:
                pass

    # Request inspector
    if is_dev:
        try:
            import time as _time
            from tina4_python.dev_admin import RequestInspector
            duration = (_time.perf_counter() - req_start) * 1000
            RequestInspector.capture(
                request.method, request.path, response.status_code, duration,
                body_size=len(response.content) if response.content else 0,
                ip=request.ip,
            )
        except Exception:
            pass

    # Session save + cookie
    if request.session is not None:
        try:
            request.session.save()
            sid = request.session.session_id if hasattr(request.session, 'session_id') else getattr(request.session, 'id', None)
            if sid:
                ttl = int(os.environ.get("TINA4_SESSION_TTL", "3600"))
                samesite = os.environ.get("TINA4_SESSION_SAMESITE", "Lax")
                response.header("set-cookie", f"tina4_session={sid}; Path=/; HttpOnly; SameSite={samesite}; Max-Age={ttl}")
            import random
            if random.randint(1, 100) == 1:
                request.session.gc()
        except Exception:
            pass

    return response


async def handle(request: Request) -> Response:
    """Dispatch a pre-built Request through the Tina4 router and return a Response.

    Handles session setup, CORS, rate limiting, routing, auth, middleware,
    dev toolbar injection, and session saving. The caller is responsible
    for sending the response over the wire. Useful for testing and embedding.
    """
    import time as _time

    request_id = request.headers.get("x-request-id", str(uuid.uuid4())[:8])
    set_request_id(request_id)
    _init_session(request)

    response = Response()
    response.header("x-request-id", request_id)

    # CORS preflight
    if _cors.is_preflight(request):
        _cors.apply(request, response)
        response.status(204)
        return response

    # Rate limiting
    rate_response = _handle_rate_limit(request, response)
    if rate_response is not None:
        return rate_response

    _req_start = _time.perf_counter()
    from tina4_python.dotenv import is_truthy
    _is_dev = is_truthy(os.environ.get("TINA4_DEBUG", ""))

    # Dev admin
    if _is_dev and request.path.startswith("/__dev"):
        return await _handle_dev_admin(request, response)

    # Swagger
    if _is_dev and request.method == "GET":
        swagger_resp = _handle_swagger(request, response)
        if swagger_resp is not None:
            return swagger_resp

    # Route matching and dispatch
    route, params = Router.match(request.method, request.path)

    if route:
        request._route_params = params
        request.merge_route_params()
        try:
            skip = _check_auth(request, response, route)
            if not skip:
                request, response, skip = _run_before_middleware(request, response, route)
            if not skip:
                response = await _invoke_handler(request, response, route, params)
            request, response = _run_after_middleware(request, response, route)
        except Exception as e:
            response = _handle_route_error(e, request, response, request_id, _is_dev)
    else:
        response = _handle_no_route(request, response, request_id)

    return _finalize_response(request, response, route, request_id, _is_dev, _req_start)


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

    if scope["type"] == "websocket":
        await _handle_asgi_websocket(scope, receive, send)
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

    # Build request and dispatch
    request = Request.from_scope(scope, body)
    response = await handle(request)

    # ETag check — 304 Not Modified
    if_none_match = request.headers.get("if-none-match", "")
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
    # Framework built-in assets (tina4.min.js, frond.min.js, tina4.min.css, tina4-dev-admin.min.js, etc.)
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


def _find_production_server():
    """Check for production ASGI servers, return (name, start_func) or None.

    Priority order: uvicorn > hypercorn > granian.
    Returns None if no production server is installed.
    """
    try:
        import uvicorn
        def _start_uvicorn(host, port, asgi_app):
            uvicorn.run(asgi_app, host=host, port=port, log_level="info")
        return "uvicorn", _start_uvicorn
    except ImportError:
        pass
    try:
        import hypercorn.asyncio
        import hypercorn.config
        def _start_hypercorn(host, port, asgi_app):
            import asyncio
            cfg = hypercorn.config.Config()
            cfg.bind = [f"{host}:{port}"]
            asyncio.run(hypercorn.asyncio.serve(asgi_app, cfg))
        return "hypercorn", _start_hypercorn
    except ImportError:
        pass
    try:
        import granian
        def _start_granian(host, port, asgi_app):
            from granian import Granian
            g = Granian("tina4_python.core.server:app", address=host, port=port, interface="asgi")
            g.serve()
        return "granian", _start_granian
    except ImportError:
        pass
    return None


def _kill_port(port: int) -> None:
    """Kill whatever process is listening on *port*.

    Uses lsof on macOS/Linux and netstat + taskkill on Windows.
    Raises RuntimeError if the port cannot be freed.
    """
    import subprocess
    import time

    print(f"  Port {port} in use — killing existing process...")

    if sys.platform == "win32":
        # Find PID via netstat
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True, timeout=5
            )
            pid = None
            for line in result.stdout.splitlines():
                if f":{port}" in line and ("LISTENING" in line or "ESTABLISHED" in line):
                    parts = line.split()
                    if parts:
                        pid = parts[-1]
                        break
            if pid and pid.isdigit():
                subprocess.run(["taskkill", "/PID", pid, "/F"], timeout=5)
        except Exception as e:
            raise RuntimeError(f"Could not free port {port}: {e}") from e
    else:
        # macOS / Linux — use lsof
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, timeout=5
            )
            pids = result.stdout.strip().splitlines()
            if not pids:
                return  # Nothing found — port may have freed itself
            for pid_str in pids:
                pid_str = pid_str.strip()
                if pid_str.isdigit():
                    os.kill(int(pid_str), signal.SIGTERM)
        except FileNotFoundError:
            # lsof not available — try fuser
            try:
                result = subprocess.run(
                    ["fuser", f"{port}/tcp"],
                    capture_output=True, text=True, timeout=5
                )
                for pid_str in result.stdout.split():
                    if pid_str.isdigit():
                        os.kill(int(pid_str), signal.SIGTERM)
            except Exception as e:
                raise RuntimeError(f"Could not free port {port}: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Could not free port {port}: {e}") from e

    # Give the OS a moment to reclaim the port
    time.sleep(0.5)
    print(f"  Port {port} freed")


def _find_available_port(start: int, max_tries: int = 10) -> int:
    """Check if *start* is available; if not, kill the process on it and return *start*.

    The auto-increment behaviour is intentionally removed — the server always
    claims the requested port.  If killing fails a RuntimeError is raised.
    """
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", start))
        s.close()
        return start
    except OSError:
        _kill_port(start)
        return start


def _open_browser(url: str):
    """Open *url* in the default browser after a short delay."""
    import webbrowser
    import threading
    threading.Timer(2.0, webbrowser.open, args=[url]).start()


def resolve_config(cli_host: str | None = None, cli_port: int | None = None) -> tuple[str, int]:
    """Resolve host/port with priority: CLI flag > ENV var > default.

    Args:
        cli_host: Host from CLI flag (--host or positional), or None.
        cli_port: Port from CLI flag (--port or positional), or None.

    Returns:
        (host, port) tuple with resolved values.
    """
    default_host = "0.0.0.0"
    default_port = 7146

    # Host: CLI flag > HOST env > default
    if cli_host is not None:
        host = cli_host
    else:
        host = os.environ.get("HOST", default_host)

    # Port: CLI flag > PORT env > default
    if cli_port is not None:
        port = cli_port
    else:
        env_port = os.environ.get("PORT")
        port = int(env_port) if env_port and env_port.isdigit() else default_port

    return host, port


def _print_banner(host: str, port: int, server_name: str = "asyncio", ai_port: int | None = None):
    """Print the Tina4 Slant ASCII banner to stdout (not through the logger)."""
    from tina4_python.dotenv import is_truthy

    is_debug = is_truthy(os.environ.get("TINA4_DEBUG", ""))
    log_level = os.environ.get("TINA4_LOG_LEVEL", "error").upper()
    display = "localhost" if host in ("0.0.0.0", "::") else host

    # Blue color for Python, only when stdout is a TTY
    color = "\033[34m" if sys.stdout.isatty() else ""
    reset = "\033[0m" if sys.stdout.isatty() else ""

    ai_port_line = f"\n  Test Port: http://{display}:{ai_port} (stable — no hot-reload)" if ai_port else ""

    banner = f"""{color}
  ______ _             __ __
 /_  __/(_)___  ____ _/ // /
  / /  / / __ \\/ __ `/ // /_
 / /  / / / / / /_/ /__  __/
/_/  /_/_/ /_/\\__,_/  /_/
{reset}
  Tina4 Python v{__version__} — This Is Now A 4Framework

  Server:    http://{display}:{port} ({server_name})
  Swagger:   http://localhost:{port}/swagger
  Dashboard: http://localhost:{port}/__dev
  Debug:     {"ON" if is_debug else "OFF"} (Log level: {log_level}){ai_port_line}
"""
    print(banner)


def run(host: str | None = None, port: int | None = None, no_browser: bool = False, no_reload: bool = False):
    """Start the Tina4 dev server.

    Discovers routes from src/, starts ASGI server, handles shutdown.

    Args:
        host: Bind address. Falls back to HOST env var, then 0.0.0.0.
        port: Bind port. Falls back to PORT env var, then 7146.
        no_browser: If True, do not open browser on startup.
        no_reload: If True, disable the file watcher / live-reload.
    """
    import time
    global _start_time
    _start_time = time.time()

    if no_reload:
        os.environ["TINA4_NO_RELOAD"] = "true"

    # Ensure CWD is on sys.path so auto-discovered modules can be imported
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    # Load .env first so env vars are available for logger init
    from tina4_python.dotenv import load_env
    load_env()

    # Init logger
    is_production = os.environ.get("TINA4_ENV", "development") == "production"
    log_level = os.environ.get("TINA4_LOG_LEVEL", "error" if not is_production else "error")
    Log.init(level=log_level, production=is_production)

    # Ensure folders
    _ensure_folders()

    # Auto-discover routes
    _auto_discover("src")
    route_count = len(Router.get_routes())
    Log.info(f"Discovered {route_count} routes")

    # Resolve host/port (CLI arg > ENV > default)
    host, port = resolve_config(cli_host=host, cli_port=port)

    # Claim the requested port — kill whatever is on it if needed
    port = _find_available_port(port)

    # Detect production server (unless TINA4_DEBUG is true)
    from tina4_python.dotenv import is_truthy
    is_debug = is_truthy(os.environ.get("TINA4_DEBUG", ""))

    # Start DevReload file watcher in debug mode
    if is_debug:
        no_reload = os.environ.get("TINA4_NO_RELOAD", "").lower() in ("true", "1", "yes")
        if not no_reload:
            try:
                from tina4_python.dev_reload import start as _start_dev_reload
                _start_dev_reload(["src", "public"])
            except Exception as e:
                Log.error(f"DevReload: failed to start: {e}")

    prod = None
    if not is_debug:
        prod = _find_production_server()

    server_name = prod[0] if prod else "asyncio"

    # Determine AI dev port (port+1) when debug is on and not suppressed
    _no_ai_port = os.environ.get("TINA4_NO_AI_PORT", "").lower() in ("true", "1", "yes")
    _ai_port = (port + 1000) if (is_debug and not _no_ai_port) else None

    # Banner — printed directly to stdout, not through the logger
    _print_banner(host, port, server_name, ai_port=_ai_port)

    display = "localhost" if host in ("0.0.0.0", "::") else host
    Log.info(f"Server started http://{display}:{port} ({server_name})")
    if _ai_port:
        Log.info(f"Test port: http://{display}:{_ai_port} (stable — no hot-reload)")

    # Open browser after a short delay (unless --no-browser)
    _skip_browser = no_browser or os.environ.get("TINA4_NO_BROWSER", "").lower() in ("true", "1", "yes")
    if not _skip_browser:
        _open_browser(f"http://{display}:{port}")

    # Use production server if available
    if prod:
        name, starter = prod
        Log.info(f"Production server: {name}")
        try:
            starter(host, port, app)
        except KeyboardInterrupt:
            pass
        return

    # Fall back to built-in asyncio dev server
    Log.info("Development server: asyncio")

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

            # Check for WebSocket upgrade before reading body
            _header_dict = {k.decode(): v.decode() for k, v in headers}
            if _header_dict.get("upgrade", "").lower() == "websocket":
                if hasattr(writer, "_tina4_ai_port") and path == "/__dev_reload":
                    writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                    await writer.drain()
                    writer.close()
                    return
                await _handle_dev_websocket(reader, writer, _header_dict, path)
                return

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

        # Test port (port + 1000) — stable, no live-reload WebSocket
        ai_server = None
        if _ai_port:
            try:
                async def _handle_ai_connection(reader, writer):
                    _ai_port_ctx.set(True)
                    writer._tina4_ai_port = True
                    await _handle_connection(reader, writer)

                ai_server = await start_server(_handle_ai_connection, host, _ai_port)
            except OSError:
                Log.warning(f"AI port {_ai_port} in use — skipping")

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                pass  # Windows

        await shutdown.wait()
        if ai_server:
            ai_server.close()
            await ai_server.wait_closed()
        server.close()
        await server.wait_closed()
        Log.info("Server stopped.")

    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        pass
