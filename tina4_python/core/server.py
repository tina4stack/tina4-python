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
import threading
import time
import uuid
from email.utils import formatdate, parsedate_to_datetime
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
# Seeded at import so `uptime` is a small, sane number even if the health
# handler is reached before run() re-stamps it. A 0 default meant "seconds since
# 1970" (uptime of 1.7e9) rather than "just started".
_start_time: float = time.time()

# ── Background tasks registry ────────────────────────────────────────────
_background_tasks: list["BackgroundTask"] = []
# The registry is read from the event loop and written from user code (which may
# be on another thread), and stop() is a search-then-delete — not atomic under
# the GIL. One lock guards every mutation.
_background_lock = threading.Lock()


class BackgroundTask:
    """Handle for one registered background task.

    Returned by :func:`background`. Call :meth:`stop` to end the task AND remove
    it from the registry — a stopped task is never left behind, so
    :func:`background_task_count` always reports what is actually running.

    Mirrors Node's ``background()`` handle (``handle.stop()``) and Ruby's
    ``Tina4::Background.stop_task(task)``.
    """

    __slots__ = ("callback", "interval", "stopped", "_runner")

    def __init__(self, callback, interval: float):
        self.callback = callback
        self.interval = float(interval)
        self.stopped = False
        # The asyncio.Task ticking this callback, once the server loop has
        # started it. None while the task is registered but not yet running.
        self._runner = None

    def stop(self) -> bool:
        """Stop this task and deregister it.

        Works whether or not the server is running: before start it simply
        leaves the registry, and once ticking it also cancels its runner.

        Idempotent — a second call is a safe no-op.

        Returns:
            True if this call removed the task, False if it was already gone.
        """
        removed = False
        with _background_lock:
            # Identity, not equality: only THIS handle goes, never a sibling
            # that happens to hold the same callback and interval.
            for index, registered in enumerate(_background_tasks):
                if registered is self:
                    del _background_tasks[index]
                    removed = True
                    break

        self.stopped = True
        runner, self._runner = self._runner, None
        if runner is not None and not runner.done():
            runner.cancel()
        return removed


def background(callback, interval: float = 1.0) -> BackgroundTask:
    """Register a background task that runs periodically in the server event loop.

    Matches PHP's $app->background(fn, interval) pattern.

    Args:
        callback: Function to call (sync or async, no arguments).
        interval: Seconds between invocations (default: 1.0).

    Returns:
        A BackgroundTask handle — call ``.stop()`` to end and deregister it.
    """
    task = BackgroundTask(callback, interval)
    with _background_lock:
        _background_tasks.append(task)
    return task


def background_task_count() -> int:
    """Number of REGISTERED background tasks (stopped ones are already gone)."""
    with _background_lock:
        return len(_background_tasks)


def stop_all_background_tasks() -> int:
    """Stop and deregister every background task. Returns how many were stopped.

    Each task deregisters itself, so there is no blanket ``clear()``: clearing
    would also drop a task registered while this was running, leaving it ticking
    but invisible in the registry.
    """
    with _background_lock:
        snapshot = list(_background_tasks)
    return sum(1 for task in snapshot if task.stop())


# ── Graceful shutdown ────────────────────────────────────────────────────
# 30 seconds matches Kubernetes' default terminationGracePeriodSeconds and
# gunicorn's graceful_timeout, so the drain finishes before the orchestrator
# escalates to SIGKILL. Same env var and same default in all four frameworks.
DEFAULT_SHUTDOWN_TIMEOUT = 30.0


def _resolve_shutdown_timeout() -> float:
    """Seconds to spend draining in-flight work on shutdown.

    Read from TINA4_SHUTDOWN_TIMEOUT. A value that is not a positive number
    warns and falls back to the default — NEVER a silent 0, which would look
    like a graceful drain while actually cutting every in-flight request.
    """
    raw = os.environ.get("TINA4_SHUTDOWN_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_SHUTDOWN_TIMEOUT
    try:
        seconds = float(raw)
    except ValueError:
        seconds = 0.0
    if seconds <= 0:
        Log.warning(
            f"TINA4_SHUTDOWN_TIMEOUT={raw!r} is not a positive number of seconds — "
            f"draining for the {DEFAULT_SHUTDOWN_TIMEOUT:g}s default instead"
        )
        return DEFAULT_SHUTDOWN_TIMEOUT
    return seconds


def _shutdown_timeout_whole_seconds() -> int:
    """TINA4_SHUTDOWN_TIMEOUT for a server whose own option is int-typed.

    uvicorn's ``timeout_graceful_shutdown`` is an int. Rounding a positive
    sub-second timeout down to 0 would mean "no grace at all" — the silent zero
    this feature exists to prevent — so the floor is 1 second.
    """
    return max(1, round(_resolve_shutdown_timeout()))


def _close_bound_databases() -> int:
    """Close every ORM-bound database connection. Returns how many were closed.

    Shutdown must hand the connections back rather than let the OS reap them —
    a pooled server that never closes leaves the DB counting phantom clients
    until its own idle timeout. Mirrors Ruby's ``Tina4::Shutdown``. A close
    failure is logged and never fatal: the process is going away regardless.
    """
    from tina4_python.orm import model as orm_model

    unique = []
    for db in [orm_model._database, *orm_model._databases.values()]:
        # Identity, not equality — a Database has no __eq__ and two handles to
        # the same file are still two connections to close.
        if db is not None and not any(db is seen for seen in unique):
            unique.append(db)

    closed = 0
    for db in unique:
        try:
            db.close()
            closed += 1
        except Exception as exc:  # noqa: BLE001 — shutdown must not fail here
            Log.error(f"Error closing database on shutdown: {exc}")
    if closed:
        Log.info(f"Database connections closed ({closed})")
    return closed


def _start_background_tasks(executor, shutdown) -> list:
    """Start an asyncio runner for every registered task. Called once by _serve.

    Each runner is bound to its handle so ``BackgroundTask.stop()`` can cancel a
    task that is already ticking, not merely deregister one that never started.
    """
    with _background_lock:
        # Never iterate the live list — a concurrent stop() mutates it.
        snapshot = list(_background_tasks)

    runners = []
    for task in snapshot:
        if task.stopped:
            continue  # stopped between registration and server start
        runner = asyncio.create_task(
            background_tick_loop(task.callback, task.interval, executor, shutdown)
        )
        task._runner = runner
        # A stop() that landed while the runner was being created must still win,
        # or the task would tick on with nothing holding a reference to cancel it.
        if task.stopped:
            runner.cancel()
            continue
        runners.append(runner)
    return runners


async def background_tick_loop(callback, interval: float, executor, shutdown):
    """Run one registered background task on its interval until shutdown.

    A task NEVER overlaps itself: each run is awaited to completion before the
    interval sleep and the next tick. That is the only sound reading of an
    interval scheduler, and it is what makes the one-worker-per-task pool sizing
    in `_serve` safe.

    Args:
        callback: The registered callable (sync or async, no arguments).
        interval: Seconds to sleep between runs.
        executor: ThreadPoolExecutor used for sync callbacks.
        shutdown: asyncio.Event that ends the loop when set.
    """
    timeout = max(interval * 2, 5.0)
    loop = asyncio.get_running_loop()
    while not shutdown.is_set():
        try:
            if asyncio.iscoroutinefunction(callback):
                # A coroutine IS cancellable, so the timeout really interrupts it.
                await asyncio.wait_for(callback(), timeout=timeout)
            else:
                # Run sync callback in a thread pool — never blocks the event loop.
                #
                # A callable already running in a ThreadPoolExecutor CANNOT be
                # cancelled: Future.cancel() returns False once it has started and
                # there is no way to interrupt the thread. So this must NOT use
                # wait_for() — that abandons the wrapper future while the thread
                # keeps running, and the next tick then starts a SECOND copy
                # alongside the first (silent double-execution of a slow sweep,
                # with every later tick piling on another). Wait for the run to
                # finish and only WARN about the overrun.
                fut = loop.run_in_executor(executor, callback)
                done, _pending = await asyncio.wait({fut}, timeout=timeout)
                if not done:
                    Log.warning(
                        f"Background task is still running after {timeout:.1f}s. "
                        f"The next run is deferred until it finishes (a running sync "
                        f"task cannot be interrupted). Use non-blocking calls "
                        f"(e.g. queue.pop() instead of queue.consume())."
                    )
                await fut  # never overlap; re-raises the callback's error
        except asyncio.TimeoutError:
            Log.warning(
                f"Background task exceeded {timeout:.1f}s timeout and was interrupted. "
                f"Use non-blocking calls (e.g. queue.pop() instead of queue.consume())."
            )
        except Exception as e:
            Log.error(f"Background task error: {e}")
        await asyncio.sleep(interval)


# module_name → source-file mtime at the last (re)import. Drives the
# changed-file detection in ``_auto_discover``: a file whose mtime is newer
# than the recorded value is re-executed in place, so editing an existing
# route hot-reloads on /__dev/api/reload without a server restart. Files we
# have never imported are absent from the map.
_discovered_mtimes: dict[str, float] = {}


def _auto_discover(root_dir: str = "src"):
    """Auto-import all .py files in ``root_dir`` to trigger route decorators.

    Idempotent and re-runnable so re-discovery on /__dev/api/reload is cheap:

    * **New** module (not in ``sys.modules``) → import it, record its mtime.
    * **Changed** module (in ``sys.modules`` and its source mtime is newer than
      the recorded value) → re-execute it (``del sys.modules`` + re-import) so
      edits to an existing route take effect. The Router replaces same-(method,
      path) registrations, so the re-imported handler wins instead of being
      shadowed by the stale one.
    * **Unchanged** module → skipped (keeps the re-runnable property cheap).

    Only modules discovered under ``root_dir`` are ever re-imported — framework
    (``tina4_python.*``) and third-party modules are never deleted/re-imported,
    which would be catastrophic for shared singletons and class identity.

    Import failures are recorded to ``data/.broken/`` so /health surfaces them
    instead of swallowing them into a console line nobody reads.
    """
    root = Path(root_dir).resolve()
    if not root.is_dir():
        return

    # Drop importlib's cached directory listings before importing anything.
    #
    # importlib caches the contents of each directory it has scanned and only
    # re-reads one when it believes the directory changed. A file created shortly
    # after that cache was warmed is therefore INVISIBLE to import_module, which
    # raises ModuleNotFoundError for a file that plainly exists on disk. The
    # failure is swallowed by the except below (recorded to data/.broken/), so the
    # visible symptom is simply a route that never registers.
    #
    # That is exactly "drop a new route file and hit reload": the first
    # _auto_discover warms the cache for src/routes, the user adds a file, and the
    # re-discover cannot see it -- so the route stays missing until a full
    # restart, which is the very gotcha this function exists to remove.
    #
    # MEASURED through this function on the lab host (Python 3.12.3, ext4), 300
    # iterations of write-file -> discover -> write-sibling -> discover:
    #   without this call: 150/300 iterations failed to register the new route
    #   with    this call:   0/300
    # It is not a rare race. It also explains the intermittent failure of
    # tests/test_auto_discover.py::test_auto_discover_picks_up_new_files_on_reload,
    # whose captured log showed "Failed to load .../second.py: No module named
    # 'src.routes.second'".
    #
    # Cost is one cache clear per discover (not per file), so the re-runnable and
    # cheap properties of this function are unaffected.
    importlib.invalidate_caches()

    # The package prefix every discovered module shares (e.g. "src"). The
    # del+reimport path is gated on this so we can never evict a framework or
    # third-party module from sys.modules even if a name somehow collides.
    try:
        root_pkg = root.relative_to(Path.cwd()).parts[0]
    except (ValueError, IndexError):
        root_pkg = root.name

    # Folders to skip — non-Python sub-trees inside src/.
    skip = {"public", "templates", "scss", "locales", "icons"}
    # Routes folder is special-cased so the user gets a clear warning when
    # it exists but contains zero discoverable Python files.
    routes_dir = root / "routes"
    found_route_files = 0

    for py_file in sorted(root.rglob("*.py")):
        # Only filter on parts INSIDE src/, not the absolute path. Previously
        # `py_file.parts` included every ancestor, so a project living under
        # something like /Users/me/_archive/myapp would silently skip every
        # file. Compute the relative parts first and filter on those.
        try:
            rel_to_root = py_file.relative_to(root)
        except ValueError:
            continue

        rel_parts = rel_to_root.parts
        if any(part.startswith("_") for part in rel_parts):
            continue
        if any(s in rel_parts for s in skip):
            continue

        if routes_dir in py_file.parents:
            found_route_files += 1

        try:
            rel = py_file.relative_to(Path.cwd()).with_suffix("")
            module_name = ".".join(rel.parts)
            try:
                current_mtime = py_file.stat().st_mtime
            except OSError:
                current_mtime = 0.0

            if module_name not in sys.modules:
                # New module — import and remember its mtime.
                importlib.import_module(module_name)
                _discovered_mtimes[module_name] = current_mtime
                Log.debug(f"Loaded: {module_name}")
            elif module_name not in _discovered_mtimes:
                # Already in sys.modules but NEVER recorded by discovery — it was
                # imported TRANSITIVELY (e.g. `from src.x import y` pulled it in
                # before the walk reached its file). Record its current mtime as
                # the baseline WITHOUT re-importing. Re-importing here would
                # del+re-add a fresh module object, while the earlier importer
                # keeps the STALE one — module-level singletons would silently
                # diverge (issue #53). We only ever reload a module WE loaded.
                _discovered_mtimes[module_name] = current_mtime
            elif current_mtime > _discovered_mtimes[module_name]:
                # Changed since WE loaded it — re-execute so edits to an existing
                # route take effect in-process. Scope guard: only ever evict a
                # module that lives under our discovery package. Deleting a
                # tina4_python.* / third-party module would break shared
                # singletons and class identity — never do that here.
                if module_name == root_pkg or module_name.startswith(root_pkg + "."):
                    # Purge this module's OLD routes first. Re-importing only
                    # OVERWRITES an identical (method, path), so a renamed or
                    # deleted endpoint would otherwise keep serving its stale
                    # handler until a full restart. The decorators below
                    # re-register whatever the file declares NOW.
                    from tina4_python.core.router import Router
                    dropped = Router.remove_routes_for_module(module_name)
                    del sys.modules[module_name]
                    importlib.import_module(module_name)
                    _discovered_mtimes[module_name] = current_mtime
                    Log.info(
                        f"Reloaded changed module: {module_name}"
                        + (f" (dropped {dropped} stale route(s))" if dropped else "")
                    )
                else:
                    # Out-of-scope module changed — record mtime so we don't
                    # keep re-evaluating it, but do not re-import it.
                    _discovered_mtimes[module_name] = current_mtime
            # Unchanged module → skip (keeps re-discovery cheap/idempotent).
        except Exception as e:
            Log.error(f"Failed to load {py_file}: {e}")
            _record_broken_import(py_file, e)

    # User-friendly hint: routes folder has Python files but the router is
    # still empty. They almost certainly forgot the @get/@post decorator.
    if found_route_files > 0:
        try:
            from tina4_python.core.router import Router
            if not Router.get_routes():
                Log.warning(
                    f"Auto-discover found {found_route_files} .py file(s) in "
                    f"{routes_dir} but no routes registered. Did you forget "
                    f"@get / @post / @put / @delete on your handler?"
                )
        except Exception:
            pass


def _record_broken_import(py_file: Path, error: Exception) -> None:
    """Write a .broken sentinel so /health and the dev dashboard surface
    auto-discover failures instead of burying them in the console."""
    try:
        broken_dir = Path("data/.broken")
        broken_dir.mkdir(parents=True, exist_ok=True)
        import json
        slug = str(py_file).replace("/", "_").replace("\\", "_")
        (broken_dir / f"discover_{slug}.broken").write_text(json.dumps({
            "type": "auto_discover_failure",
            "file": str(py_file),
            "error": f"{type(error).__name__}: {error}",
        }))
    except Exception:
        # If even the .broken write fails we already logged the original error.
        pass


def _ensure_folders():
    """Create project folders if missing (auto-repair).

    Note: ``migrations/`` lives at the project root (matches the CLI's
    ``migrations`` default and the documented project structure), never
    under ``src/``. Don't add ``src/migrations`` here — it creates an
    empty directory that the migration runner ignores and confuses users.
    """
    folders = [
        "src/routes", "src/orm", "src/seeds",
        "src/templates", "src/templates/errors",
        "src/public", "src/public/js", "src/public/css", "src/public/icons",
        "src/locales",
        "migrations",
        "data", "data/.broken", "logs", "secrets", "tests",
    ]
    for folder in folders:
        Path(folder).mkdir(parents=True, exist_ok=True)

    _clear_stale_broken_sentinels()


def _clear_stale_broken_sentinels() -> None:
    """Drop ``.broken`` sentinels left by a PREVIOUS run.

    A sentinel records an error that happened in a process that no longer
    exists, so reporting it on this process's health is simply wrong -- and
    because nothing ever removed them the set grew without bound and a single
    historical error was reported forever, across restarts. The health body
    describes THIS run.
    """
    broken_dir = Path("data/.broken")
    if not broken_dir.is_dir():
        return
    for sentinel in broken_dir.glob("*.broken"):
        try:
            sentinel.unlink()
        except OSError as error:  # pragma: no cover - unreadable dir is not fatal
            Log.warning(f"health: could not clear stale sentinel {sentinel.name}: {error}")


def _auto_wire_i18n():
    """Auto-register t() as a Frond global if locale files exist.

    Convention: if src/locales/ contains .json files, create an I18n
    instance and register its .t() method as the Frond global ``t``.
    Reads TINA4_LOCALE and TINA4_LOCALE_DIR from the environment.
    """
    locale_dir = Path(os.environ.get("TINA4_LOCALE_DIR", "src/locales"))
    if not locale_dir.is_dir():
        return
    json_files = list(locale_dir.glob("*.json"))
    if not json_files:
        return

    try:
        from tina4_python.i18n import I18n
        from tina4_python.frond import Frond

        i18n = I18n(
            locale_dir=str(locale_dir),
            default_locale=os.environ.get("TINA4_LOCALE", "en"),
        )

        # Only register if t() hasn't been explicitly set by the user
        if "t" not in Frond._class_globals:
            Frond._class_globals["t"] = i18n.t
            Log.info(f"i18n: auto-registered t() with {len(json_files)} locale(s)")
    except Exception as e:
        Log.error(f"i18n: auto-wire failed: {e}")


async def _health_handler(request: Request, response: Response) -> Response:
    """Built-in health endpoint. This is a LIVENESS probe.

    Liveness answers exactly one question: can this process serve at all? The
    answer is carried by the fact that it responded, so this handler reports 200
    whenever it runs. A failing liveness probe tells an orchestrator to RESTART
    the container, so the only thing it may react to is a condition a restart
    actually fixes.

    It therefore does NOT fail on a recorded route error. It used to: any
    unhandled exception in any route writes ``data/.broken/*.broken`` from the
    request path, and this handler returned 503 while such a file existed.
    Nothing cleared them, so one ordinary 500 flipped health to 503 for good and
    the file survived a restart -- a CrashLoopBackOff from a single bad request,
    reacting to something a restart cannot repair (a route file that fails to
    import fails again on the next boot). Route errors are still reported below
    as diagnostics for the dev dashboard; they no longer set the status code.

    Dependency health (database, cache, queue) belongs on a READINESS endpoint,
    which withdraws traffic WITHOUT a restart. See ADR-0016.

    The body is exactly four keys, identical in all four frameworks. It used to
    also carry ``errors`` and ``latest_error`` read from ``data/.broken``. Once
    those stopped driving the status code they were pure diagnostics, and
    diagnostics do not belong on a probe endpoint that should stay minimal and
    fast. The ``.broken`` writer and the dev dashboard that reads it are both
    unchanged; only this body dropped the keys.
    """
    import time

    return response.status(200).json({
        "status": "ok",
        "version": __version__,
        "uptime": round(time.time() - _start_time, 2),
        "framework": "tina4-python",
    })


# Register health check.
# TINA4_HEALTH_PATH overrides the URL path. We also keep /health registered
# under the env path; if the env path differs we register both so existing
# probes don't break. Default "/__health" matches PHP/Ruby/Node parity.
_HEALTH_PATH = os.environ.get("TINA4_HEALTH_PATH", "/__health")
Router.add("GET", _HEALTH_PATH, _health_handler)
if _HEALTH_PATH != "/health":
    Router.add("GET", "/health", _health_handler)

# Frond live blocks: re-render a registered {% live %} fragment on demand.
# Always on (production too) - the poll/sse client fetches this; auth re-applies
# through the normal middleware chain on every refresh.
from tina4_python.frond import live_endpoint as _live_endpoint
Router.add("GET", "/__frond/live/{name}", _live_endpoint)


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


# Auto-routing scans this single subdirectory of src/templates/. Only files
# in src/templates/pages/ become URLs — everything else (partials, layouts,
# base.twig, errors, components, macros) is never URL-exposed and remains
# renderable only via {% include %} / {% extends %} / response.render().
#
# Convention adapted from Next.js' pages/ directory and Nuxt's pages/ folder.
# Explicit, secure by default, no skip lists to maintain.
_TEMPLATE_PAGES_DIR = "pages"


def _is_dev_mode() -> bool:
    """True when ``TINA4_DEBUG`` is one of the truthy values (true|1|yes).

    Centralised so every dev-mode gate (landing page, dev toolbar, error
    overlay, dev admin) reads the same flag the same way.
    """
    return os.environ.get("TINA4_DEBUG", "false").strip().lower() in ("true", "1", "yes")


# RFC 7231 / RFC 9110 status reason phrases. We use this to write a correct
# HTTP status line in the dev server's HTTP/1.1 → ASGI bridge — previously
# the bridge wrote "HTTP/1.1 404 OK" regardless of code, which is malformed.
_HTTP_REASON_PHRASES: dict[int, str] = {
    100: "Continue", 101: "Switching Protocols",
    200: "OK", 201: "Created", 202: "Accepted", 204: "No Content",
    206: "Partial Content",
    301: "Moved Permanently", 302: "Found", 303: "See Other",
    304: "Not Modified", 307: "Temporary Redirect", 308: "Permanent Redirect",
    400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
    404: "Not Found", 405: "Method Not Allowed", 406: "Not Acceptable",
    409: "Conflict", 410: "Gone", 413: "Content Too Large",
    415: "Unsupported Media Type", 422: "Unprocessable Content",
    429: "Too Many Requests",
    500: "Internal Server Error", 501: "Not Implemented",
    502: "Bad Gateway", 503: "Service Unavailable", 504: "Gateway Timeout",
}


def _http_reason(status: int) -> str:
    """Return the canonical HTTP reason phrase for ``status``.

    Falls back to a sensible label when an exotic status is used. Never
    returns an empty string — the HTTP/1.1 status line requires a phrase.
    """
    return _HTTP_REASON_PHRASES.get(int(status), "OK" if 200 <= status < 300 else "Error")


def _template_auto_routing_enabled() -> bool:
    """Honour TINA4_TEMPLATE_ROUTING=off|false|0|no as an explicit kill switch.

    Default: enabled. Drop a file in src/templates/pages/ and it serves at
    the matching URL — the zero-config Tina4 convention. Operators who want
    explicit-only routing can set TINA4_TEMPLATE_ROUTING=off and every URL
    must be registered via @get / @post (or be a static file).
    """
    val = os.environ.get("TINA4_TEMPLATE_ROUTING", "on").strip().lower()
    return val not in ("off", "false", "0", "no", "disabled")


def _resolve_template(path: str) -> str | None:
    """Resolve a URL path to a template file in src/templates/pages/.

    Only files inside ``src/templates/pages/`` auto-route from a URL.
    Anything in ``src/templates/`` outside ``pages/`` (partials, layouts,
    base.twig, errors, components) is never served standalone.

    Dev mode: checks filesystem every time for live changes.
    Production: uses a cached lookup built once at startup.

    The whole feature can be turned off with ``TINA4_TEMPLATE_ROUTING=off``.
    """
    if not _template_auto_routing_enabled():
        return None

    clean_path = path.strip("/") or "index"
    is_dev = os.environ.get("TINA4_DEBUG", "false").lower() in ("true", "1", "yes")

    if is_dev:
        # Skip underscore-prefixed files even within pages/ — they're private
        # by Hugo/Jekyll convention (helpers, fragments) and shouldn't auto-serve.
        if any(seg.startswith("_") for seg in clean_path.split("/")):
            return None
        pages_dir = Path("src/templates") / _TEMPLATE_PAGES_DIR
        for ext in (".twig", ".html"):
            candidate_rel = f"{_TEMPLATE_PAGES_DIR}/{clean_path}{ext}"
            if (pages_dir / (clean_path + ext)).is_file():
                return candidate_rel
        return None

    global _template_cache
    if _template_cache is None:
        _build_template_cache()
    return _template_cache.get(clean_path)


def _build_template_cache() -> None:
    """Scan src/templates/pages/ once and build url_path -> template_file lookup.
    Only files under ``pages/`` are eligible — partials, layouts, base.twig,
    errors etc remain renderable via explicit response.render() but never
    auto-serve from a URL.
    """
    global _template_cache
    _template_cache = {}
    pages_dir = Path("src/templates") / _TEMPLATE_PAGES_DIR
    if not pages_dir.is_dir():
        return
    for f in pages_dir.rglob("*"):
        if not f.is_file() or f.suffix not in (".twig", ".html"):
            continue
        # Skip private files even within pages/ (e.g. pages/_helper.twig)
        rel_inside_pages = f.relative_to(pages_dir)
        if any(p.startswith("_") for p in rel_inside_pages.parts):
            continue
        rel = str(f.relative_to(Path("src/templates"))).replace("\\", "/")
        url_path = str(rel_inside_pages).replace("\\", "/").rsplit(".", 1)[0]
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
        return f'<button class="try-btn" style="background:#22c55e;" onclick="window.open(\'{try_url}\',\'_blank\')" data-deployed="1">View &#8599;</button>'
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
    <p class="tagline">The Intelligent Native Application 4ramework</p>
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
            // Wait for the newly deployed route to become reachable, then
            // open it in a new tab so the dev-admin / gallery home stays
            // open (fixes tina4-book#115).
            var attempts = 0;
            var maxAttempts = 5;
            function pollRoute() {{
                fetch(tryUrl, {{method: 'HEAD'}}).then(function() {{
                    window.open(tryUrl, '_blank');
                }}).catch(function() {{
                    attempts++;
                    if (attempts < maxAttempts) {{
                        setTimeout(pollRoute, 500);
                    }} else {{
                        window.open(tryUrl, '_blank');
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
from tina4_python.websocket import CLOSE_GOING_AWAY, WebSocketConnection, WebSocketManager

_ws_manager = WebSocketManager()


async def _dev_reload_ws(connection, event, data):
    """WebSocket handler for the dev-reload channel (/__dev_reload).

    Connections are kept open and held by ``_ws_manager`` on the
    ``/__dev_reload`` path so ``POST /__dev/api/reload`` can broadcast an
    instant reload to every browser. The framework never pushes anything from
    the client side — incoming frames are ignored; the open socket is the
    whole point. This restores the documented WebSocket-primary DevReload
    design (the dashboard SPA and the injected dev-toolbar both connect here).
    """
    return


_dev_reload_ws_registered = [False]


def _register_dev_reload_ws() -> None:
    """Register the /__dev_reload WebSocket route once (debug mode only)."""
    if _dev_reload_ws_registered[0]:
        return
    Router.websocket("/__dev_reload", _dev_reload_ws)
    _dev_reload_ws_registered[0] = True


async def _handle_asgi_websocket(scope: dict, receive, send):
    """Handle ASGI WebSocket connections, dispatching to registered routes."""
    path = scope.get("path", "/")

    route, params = Router.match_ws(path)
    if route is None:
        # No matching WebSocket route — reject
        await send({"type": "websocket.close", "code": 4004})
        return

    # Origin allow-list (opt-in via TINA4_WS_ALLOWED_ORIGINS). Unset = allow all
    # so existing deployments are unaffected. Shared with the standalone server
    # via websocket.origin_allowed().
    from tina4_python.websocket import origin_allowed, ws_authorized
    _ws_headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    if not origin_allowed(_ws_headers):
        # 1008 = policy violation (per ASGI/RFC 6455 close codes)
        await send({"type": "websocket.close", "code": 1008})
        return

    # Per-route auth: a @secured() WS route requires a valid JWT on the upgrade
    # (Authorization header, "bearer" subprotocol, or ?token=). Public by default.
    _ws_subproto = _ws_headers.get("sec-websocket-protocol", "")
    _ws_payload, _ws_ok = ws_authorized(
        route, _ws_headers, scope.get("query_string", b"").decode(), _ws_subproto)
    if not _ws_ok:
        await send({"type": "websocket.close", "code": 1008})
        return

    # Accept the connection (echo the bearer subprotocol if the client offered it)
    msg = await receive()
    if msg["type"] != "websocket.connect":
        return
    _accept = {"type": "websocket.accept"}
    if any(p.strip().lower() == "bearer" for p in _ws_subproto.split(",")):
        _accept["subprotocol"] = "bearer"
    await send(_accept)

    handler = route["handler"]

    # Create a lightweight connection wrapper for ASGI WebSocket
    conn = _AsgiWebSocketConnection(scope, receive, send, path, params, _ws_manager)
    conn.auth = _ws_payload
    _ws_manager.add(conn)

    # Fire "open" event — this may set conn._on_message / conn._on_close
    # via WebSocketServer's decorator-style handler
    try:
        await handler(conn, "open", None)
    except Exception as e:
        Log.error(f"WebSocket open handler error: {e}")

    # Message loop — prefer decorator-style handlers if set during open
    try:
        while True:
            msg = await receive()
            if msg["type"] == "websocket.receive":
                data = msg.get("text") or (msg.get("bytes", b"").decode("utf-8", errors="replace") if msg.get("bytes") else "")
                try:
                    if conn._on_message:
                        result = conn._on_message(data)
                        if asyncio.iscoroutine(result):
                            await result
                    else:
                        await handler(conn, "message", data)
                except Exception as e:
                    Log.error(f"WebSocket message handler error: {e}")
            elif msg["type"] == "websocket.disconnect":
                break
    except Exception:
        pass
    finally:
        # Fire "close" event — prefer decorator-style if set
        try:
            if conn._on_close:
                result = conn._on_close()
                if asyncio.iscoroutine(result):
                    await result
            else:
                await handler(conn, "close", None)
        except Exception as e:
            Log.error(f"WebSocket close handler error: {e}")
        # Clean up rooms
        for room_name in list(conn._rooms):
            _ws_manager._leave_room(conn.id, room_name)
        conn._rooms.clear()
        _ws_manager.remove(conn)


class _AsgiWebSocketConnection:
    """WebSocket connection wrapper for ASGI servers (uvicorn, etc.).

    Supports both Router's (conn, event, data) style and WebSocketServer's
    decorator style (@conn.on_message / @conn.on_close).
    """

    def __init__(self, scope, receive, send, path, params, manager):
        self.id = str(uuid.uuid4())[:8]
        self.path = path
        self.params = params
        self.auth = None   # verified JWT payload on a @secured WS route, else None
        self.headers = {
            k.decode(): v.decode()
            for k, v in scope.get("headers", [])
        }
        self._scope = scope
        self._receive = receive
        self._send = send
        self._manager = manager
        self._closed = False
        self._on_message = None
        self._on_close = None
        self._on_error = None
        self._rooms: set = set()

        client = scope.get("client", ("unknown", 0))
        self.ip = client[0] if client else "unknown"
        import time
        self.connected_at = time.time()

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def rooms(self) -> set:
        """Return the set of room names this connection has joined."""
        return self._rooms

    def on_message(self, handler):
        """Register a message handler (decorator style)."""
        self._on_message = handler

    def on_close(self, handler):
        """Register a close handler (decorator style)."""
        self._on_close = handler

    def on_error(self, handler):
        """Register an error handler (decorator style)."""
        self._on_error = handler

    def join_room(self, room_name: str) -> None:
        """Join a named room."""
        self._rooms.add(room_name)
        if self._manager:
            self._manager._join_room(self.id, room_name)

    def leave_room(self, room_name: str) -> None:
        """Leave a named room."""
        self._rooms.discard(room_name)
        if self._manager:
            self._manager._leave_room(self.id, room_name)

    async def broadcast_to_room(self, room_name: str, message: str | bytes,
                                 exclude_self: bool = False) -> None:
        """Broadcast a message to all connections in a room."""
        if self._manager:
            exclude = self.id if exclude_self else None
            await self._manager.broadcast_to_room(room_name, message, exclude=exclude)

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


async def _handle_dev_websocket(reader, writer, headers, path, query_string: str = ""):
    """Handle WebSocket upgrade in the built-in dev server, dispatching to registered routes."""
    route, params = Router.match_ws(path)
    if route is None:
        writer.write(b"HTTP/1.1 404 Not Found\r\n\r\n")
        await writer.drain()
        writer.close()
        return

    from tina4_python.websocket import compute_accept_key, origin_allowed, ws_authorized

    ws_key = headers.get("sec-websocket-key")
    if not ws_key:
        writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        await writer.drain()
        writer.close()
        return

    # Origin allow-list (opt-in via TINA4_WS_ALLOWED_ORIGINS). Unset = allow all.
    if not origin_allowed(headers):
        writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
        await writer.drain()
        writer.close()
        return

    # Per-route auth: a @secured() WS route needs a valid JWT on the upgrade
    # (Authorization header, "bearer" subprotocol, or ?token=). Public by default.
    # (This mirrors the ASGI path — the built-in server used to skip it, which
    # both left secured WS routes unauthenticated AND left conn.auth unset.)
    _ws_subproto = headers.get("sec-websocket-protocol", "")
    _ws_payload, _ws_ok = ws_authorized(route, headers, query_string, _ws_subproto)
    if not _ws_ok:
        writer.write(b"HTTP/1.1 401 Unauthorized\r\n\r\n")
        await writer.drain()
        writer.close()
        return

    # Send upgrade response. Echo the `bearer` subprotocol when the client
    # offered it (a browser sends the JWT as `Sec-WebSocket-Protocol: bearer,
    # <jwt>` since it can't set an Authorization header); a browser fails the
    # handshake if the server doesn't select one of the offered subprotocols.
    accept = compute_accept_key(ws_key)
    _proto_header = ""
    if any(p.strip().lower() == "bearer" for p in _ws_subproto.split(",")):
        _proto_header = "Sec-WebSocket-Protocol: bearer\r\n"
    response_data = (
        f"HTTP/1.1 101 Switching Protocols\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        f"{_proto_header}\r\n"
    )
    writer.write(response_data.encode())
    await writer.drain()

    ws = WebSocketConnection(reader, writer, path, headers, params)
    ws.auth = _ws_payload
    _ws_manager.add(ws)

    handler = route["handler"]

    # Fire "open" event — this may set ws._on_message / ws._on_close
    # via WebSocketServer's decorator-style handler
    try:
        await handler(ws, "open", None)
    except Exception as e:
        Log.error(f"WebSocket open handler error: {e}")

    # If the open handler set decorator-style callbacks, use those directly.
    # Otherwise fall back to calling handler(ws, "message/close", data).
    decorator_on_message = ws._on_message
    decorator_on_close = ws._on_close

    if not decorator_on_message:
        async def on_message(message):
            try:
                await handler(ws, "message", message)
            except Exception as e:
                Log.error(f"WebSocket message handler error: {e}")
        ws._on_message = on_message

    if not decorator_on_close:
        original_on_close = ws._on_close

        async def on_close():
            try:
                await handler(ws, "close", None)
            except Exception as e:
                Log.error(f"WebSocket close handler error: {e}")
            _ws_manager.remove(ws)

        ws._on_close = on_close
    else:
        # Wrap the decorator close handler to also clean up the manager
        _user_on_close = decorator_on_close

        async def on_close_with_cleanup():
            try:
                result = _user_on_close()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                Log.error(f"WebSocket close handler error: {e}")
            _ws_manager.remove(ws)

        ws._on_close = on_close_with_cleanup

    # Enter the frame loop
    await ws._run()

    # Ensure cleanup if _run exits without triggering on_close
    if not ws._closed:
        ws._closed = True
        try:
            if decorator_on_close:
                result = decorator_on_close()
                if asyncio.iscoroutine(result):
                    await result
            else:
                await handler(ws, "close", None)
        except Exception:
            pass
        _ws_manager.remove(ws)
        try:
            ws.writer.close()
        except Exception:
            pass



def _init_session(request: Request) -> None:
    """Auto-start session from cookie. Modifies request.session in place.

    Session creation is skipped for WebSocket upgrade requests — they don't send
    cookies and would create orphaned session files that are never cleaned up.
    A session is only created when:
      - A session cookie is already present (resume existing session), OR
      - The request is a normal HTTP request (not a WebSocket upgrade)

    The incoming cookie is read by the SAME configured name the write side emits
    (``TINA4_SESSION_NAME``, default ``tina4_session``) via
    ``session.session_cookie_name()`` — otherwise a renamed cookie would be
    written but never read back and the session would silently never resume.
    """
    if request.session is not None:
        return

    # Skip session creation for WebSocket upgrade requests.
    # WebSocket clients don't send cookies so sess.start(None) would create a
    # new orphaned file every connection that is never cleaned up.
    upgrade = request.headers.get("upgrade", "").lower()
    if upgrade == "websocket":
        return

    try:
        from tina4_python.session import Session, session_cookie_name
        cookie_header = request.headers.get("cookie", "")
        sid_match = None
        cookie_prefix = session_cookie_name() + "="
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith(cookie_prefix):
                sid_match = part.split("=", 1)[1]
                break

        # Only create a new session for HTTP requests that don't already have one.
        # This prevents a new empty session file being written on every anonymous request.
        if sid_match is None:
            # Lazy session: attach a Session object but don't persist until the route
            # explicitly writes to it. The session file is only created on first save().
            sess = Session()
            sess.start(None)
            sess._is_new = True  # flag for _finalize_response to skip saving if unused
        else:
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
    from tina4_python.dev_admin import get_api_handlers
    if request.path in ("/__dev/", "/__dev", "/__dev/v2", "/__dev/v2/"):
        # Unified SPA dev admin. The bundle derives its WS URL from
        # `location.host` directly, so no environment shim is needed —
        # the framework serves /__dev_reload on its own port and the
        # SPA reaches it as `ws://<page-host>/__dev_reload`.
        response.html("""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Tina4 Dev Admin</title></head>
<body><div id="app" data-framework="python" data-color="#3b82f6"></div>
<script src="/js/tina4-dev-admin.min.js"></script></body></html>""")
        # Never cache the dev admin shell — otherwise old HTML can
        # keep loading stale widget references / outdated bundle URLs
        # after we ship UX changes, leaving the user staring at
        # phantoms that no longer exist server-side.
        response.header("cache-control", "no-store, must-revalidate")
        response.header("pragma", "no-cache")
    else:
        handlers = get_api_handlers()
        handler_info = handlers.get(request.path)
        if not handler_info:
            # Fallback: longest-prefix wildcard match. Routes registered
            # with a trailing "/*" (e.g. "/__dev/api/threads/*") catch
            # everything under that namespace — used for parameterised
            # resources like /threads/{id} that don't fit exact-match.
            best_prefix = ""
            for key, info in handlers.items():
                if key.endswith("/*"):
                    prefix = key[:-1]  # keep the trailing slash
                    if request.path.startswith(prefix) and len(prefix) > len(best_prefix):
                        best_prefix = prefix
                        handler_info = info
        # Allow "*" as a method wildcard for handlers that switch on
        # request.method themselves (REST resources with GET+POST+PATCH
        # on the same path).
        method_ok = (
            handler_info is not None
            and (handler_info[0] == "*" or request.method == handler_info[0])
        )
        if method_ok:
            try:
                def _resp(data, code=200, content_type=None):
                    # content_type overrides the auto-detected MIME —
                    # lets handlers stream binary with an explicit
                    # Content-Type (e.g. /__dev/api/file/raw).
                    if content_type is not None:
                        response.status(code)
                        response.content_type = content_type
                        response.content = data if isinstance(data, (bytes, bytearray)) else str(data).encode("utf-8")
                    elif isinstance(data, (bytes, bytearray)):
                        response.status(code)
                        response.content_type = "application/octet-stream"
                        response.content = data
                    elif isinstance(data, str):
                        response.status(code).html(data)
                    else:
                        response.status(code).json(data)
                    return data
                _resp.render = response.render
                # Expose .stream() so handlers can return an SSE/chunked
                # response — used by the dev_admin supervisor proxy to
                # forward the agent server's text/event-stream live
                # (instead of buffering the whole multi-agent run).
                _resp.stream = response.stream
                # Expose .header() so handlers can set custom headers
                # (e.g. Cache-Control on the feedback widget bundle).
                _resp.header = response.header
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
    """Serve /swagger UI and /swagger/openapi.json. Returns Response or None.

    Self-gated on swagger.is_enabled() (TINA4_SWAGGER_ENABLED, else TINA4_DEBUG)
    so the documented production on/off switch is actually honoured — before
    v3.13.40 the dispatch gated only on TINA4_DEBUG and this env var was dead.
    """
    from tina4_python.swagger import is_enabled as _swagger_enabled
    if not _swagger_enabled():
        return None
    if request.path in ("/swagger", "/swagger/"):
        # The UI assets load from a CDN by default (keeps the framework
        # zero-dependency — no vendored ~1.4MB swagger-ui-dist). Air-gapped
        # deployments point TINA4_SWAGGER_UI_CDN at a self-hosted mirror.
        _cdn = os.environ.get(
            "TINA4_SWAGGER_UI_CDN", "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5"
        ).rstrip("/")
        swagger_html = (
            '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
            '<title>API Documentation</title>'
            f'<link rel="stylesheet" href="{_cdn}/swagger-ui.css">'
            '</head><body><div id="swagger-ui"></div>'
            f'<script src="{_cdn}/swagger-ui-bundle.js"></script>'
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
    _auth_ok = False
    if _auth_header and _auth_header.startswith("Bearer "):
        _token = _auth_header[7:]
        try:
            from tina4_python.auth import Auth
            # The API-key bypass goes through validate_api_key, which compares
            # with hmac.compare_digest. A plain `==` on a secret returns as soon
            # as two bytes differ, so response timing leaks the key prefix and
            # the key can be recovered a character at a time.
            if Auth.validate_api_key(_token):
                _auth_ok = True
            elif Auth.valid_token_static(_token):
                _auth_ok = True
        except Exception:
            pass
    # Fall back to formToken in request body (frond.js sends token here)
    if not _auth_ok:
        _body = getattr(request, "body", None) or {}
        _form_token = _body.get("formToken", "") if isinstance(_body, dict) else ""
        if _form_token:
            try:
                from tina4_python.auth import Auth
                if Auth.valid_token_static(_form_token):
                    _auth_ok = True
                    # Return a FreshToken header so frond.js can use
                    # the Authorization header on subsequent requests
                    from tina4_python.auth import refresh_token as _refresh
                    _fresh = _refresh(_form_token)
                    if _fresh:
                        response.add_header("FreshToken", _fresh)
            except Exception:
                pass
    # Fall back to session token (for @secured() GET routes after login)
    if not _auth_ok:
        _session = getattr(request, "session", None)
        if _session:
            _session_token = _session.get("token") if _session else ""
            if _session_token:
                try:
                    from tina4_python.auth import Auth
                    if Auth.valid_token_static(_session_token):
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


def _is_function_middleware(mw) -> bool:
    """A function-style middleware is a non-class callable that takes 3+ args.

    Class-based middleware uses ``before_*`` / ``after_*`` method-name
    dispatch. Function-based middleware uses Express/FastAPI-style
    ``async def mw(request, response, next_handler)`` with a continuation
    callable that invokes the next layer (or the route handler).
    Documented in chapter 10 for 8+ examples; before tina4-book#141
    PY-10-01 the framework silently ignored the function bodies.
    """
    import inspect
    if isinstance(mw, type):
        return False  # Class — class-based before_*/after_* dispatch
    if not callable(mw):
        return False
    try:
        sig = inspect.signature(mw)
        # The third (or later) parameter is the next_handler continuation.
        return len(sig.parameters) >= 3
    except (TypeError, ValueError):
        return False


def _middleware_method_names(mw_inst, prefix: str) -> list:
    """Prefixed method names on a middleware instance in DEFINITION order.

    Delegates to ``Middleware._discover_methods`` so the dispatch path and
    the ``Middleware`` orchestrator share ONE ordering rule: cross-class =
    registration order (the caller loops ``route["middleware"]`` in order),
    within-class = source-definition order (never ``dir()`` alphabetical).
    """
    from tina4_python.core.middleware import Middleware
    return Middleware._discover_methods(mw_inst, prefix)


def _effective_middleware(route: dict, include_globals: bool = True) -> list:
    """Resolve the middleware that actually runs for a route.

    Global middleware (registered via ``Middleware.use`` / ``Router.use``) runs
    on EVERY route, BEFORE the route's own middleware, in registration order.
    The list is deduped (by class) so a class that is both global and attached
    to the route runs once. This is the fix for issue #55 — globals were
    registered into ``Middleware._global_middleware`` but the dispatcher only
    ever iterated ``route["middleware"]``, so global middleware never ran.
    Mirrors the PHP/Ruby/Node dispatchers, which already fold globals in.
    """
    from tina4_python.core.middleware import Middleware
    resolved = []
    seen = set()
    # POST-match globals only: anything flagged ``pre_match`` already ran in
    # handle() before the route was looked up, and must not run twice.
    #
    # ``include_globals=False`` selects the route's OWN middleware only. The
    # dispatcher needs both halves separately because the auth gate sits
    # between them, and the pre-match pass passes its own list here - without
    # the switch that pass would prepend the post-match globals and run them a
    # second time.
    _globals = list(Middleware.post_match_middleware()) if include_globals else []
    for mw in _globals + list(route.get("middleware", [])):
        key = mw if isinstance(mw, type) else type(mw)
        if key not in seen:
            seen.add(key)
            resolved.append(mw)
    return resolved


def _run_before_middleware(request: Request, response: Response, route: dict, include_globals: bool = True) -> tuple[Request, Response, bool]:
    """Run class-based before_* middleware methods. Returns (request, response, skip_handler).

    Function-style ``async def mw(req, resp, next_handler)`` middleware is
    skipped here — it's handled by ``_invoke_handler_with_middleware``
    which wraps the route handler with each function's continuation.

    Ordering (v3.13.38): middleware classes run in REGISTRATION order (the
    order of ``route["middleware"]``); within a class, ``before_*`` methods
    run in DEFINITION order, not ``dir()`` alphabetical order.

    Return-value contract: exactly the table in
    ``Middleware.apply_hook_result`` — a Response object short-circuits and
    BECOMES the response at any status, a ``(request, response)`` pair rebinds
    and continues, ``False`` short-circuits (403 if the response is still
    default), ``None`` continues. One implementation, shared with the
    ``Middleware`` orchestrator, so the two public entry points cannot drift.

    Also retained: a LEGACY COMPAT path where a response status >= 400
    short-circuits even when the hook returned ``None``. It stays because real
    middleware takes that shape, but it is NOT the main mechanism — a status
    test cannot express a 3xx redirect.

    Resilience (M2): each method call is wrapped — a method that THROWS is
    logged and converted to a clean 500, and the handler is skipped.
    """
    from tina4_python.core.middleware import Middleware
    skip = False
    for _mw_cls in _effective_middleware(route, include_globals):
        if _is_function_middleware(_mw_cls):
            continue  # Handled by the continuation wrapper instead
        _mw_inst = _mw_cls() if isinstance(_mw_cls, type) else _mw_cls
        for _attr_name in _middleware_method_names(_mw_inst, "before_"):
            _mw_method = getattr(_mw_inst, _attr_name)
            try:
                _mw_result = _mw_method(request, response)
            except Exception as _err:
                response = Middleware.middleware_500(response, _mw_inst, _attr_name, _err)
                skip = True
                break
            request, response, skip = Middleware.apply_hook_result(_mw_result, request, response)
            if skip:
                break
            # Legacy compat path — see the docstring.
            if response.status_code >= 400:
                skip = True
                break
        if skip:
            break
    return request, response, skip


def _run_after_middleware(request: Request, response: Response, route: dict, include_globals: bool = True) -> tuple[Request, Response]:
    """Run class-based after_* middleware methods.

    Function-style middleware that wraps the handler (with next_handler)
    handles its own "after" code on the return path — no separate pass
    needed for it here.

    Ordering (v3.13.38): same rule as before_* — registration order across
    classes, definition order within a class.

    4xx short-circuit rule (M2): after_* ALWAYS run, even when a before_*
    short-circuited with status >= 400 (the handler was skipped). This lets
    after-middleware add headers / logging on error responses too. All four
    frameworks follow this same rule. There is deliberately no >= 400 legacy
    path here — that would stop the after chain on every error response.

    Return-value contract: the same ``Middleware.apply_hook_result`` table as
    the before pass. An after hook that returns a Response object or ``False``
    short-circuits the remaining after hooks.

    Resilience (M2): each after_* call is wrapped — a method that THROWS is
    logged and converted to a clean 500; remaining after_* still run.
    """
    from tina4_python.core.middleware import Middleware
    for _mw_cls in _effective_middleware(route, include_globals):
        if _is_function_middleware(_mw_cls):
            continue
        _mw_inst = _mw_cls() if isinstance(_mw_cls, type) else _mw_cls
        for _attr_name in _middleware_method_names(_mw_inst, "after_"):
            _mw_method = getattr(_mw_inst, _attr_name)
            try:
                _mw_result = _mw_method(request, response)
            except Exception as _err:
                response = Middleware.middleware_500(response, _mw_inst, _attr_name, _err)
                continue
            request, response, _short_circuit = Middleware.apply_hook_result(
                _mw_result, request, response
            )
            if _short_circuit:
                return request, response
    return request, response


def _make_mw_continuation(mw, inner_next):
    """Build a `next_handler` continuation for a function-style middleware.

    Captures `mw` and the next layer (`inner_next`) in a closure. When
    invoked, calls `mw(req, resp, next_handler=inner_next)`. The
    middleware is responsible for awaiting `inner_next(req, resp)` if it
    wants the chain to continue — otherwise it short-circuits.
    """
    async def wrapper(req, resp):
        return await mw(req, resp, inner_next)
    return wrapper


async def _invoke_handler_with_middleware(request: Request, response: Response, route: dict, params: dict) -> Response:
    """Invoke the route handler, wrapping with any function-style middleware.

    Function-style middleware (``async def mw(req, resp, next_handler)``)
    forms a Russian-doll continuation chain — the first declared
    middleware is the outermost layer; it calls ``next_handler`` to
    descend, and the route handler is the innermost. Class-based
    middleware is dispatched separately by ``_run_before_middleware`` /
    ``_run_after_middleware`` and does not go through this wrapper.
    """
    fn_middlewares = [
        mw for mw in route.get("middleware", [])
        if _is_function_middleware(mw)
    ]

    if not fn_middlewares:
        return await _invoke_handler(request, response, route, params)

    # Build the chain from the inside out: innermost wraps the handler
    # first, then each outer layer wraps that. The result is a callable
    # `next_handler` that, when invoked, runs the whole chain.
    async def call_route_handler(req, resp):
        return await _invoke_handler(req, resp, route, params)

    next_handler = call_route_handler
    for mw in reversed(fn_middlewares):
        next_handler = _make_mw_continuation(mw, next_handler)

    result = await next_handler(request, response)
    if isinstance(result, Response):
        return result
    return response


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
    """Format an error response for a failed route handler.

    Two contracts (v3.13.7):

    1. Fire ``tina4.request.error`` before rendering, so observers
       (centralised logging, APM, Sentry) see the failure even though
       the framework caught it. Payload is a single dict ``{exception,
       request}`` — the canonical shape mirrored by PHP/Ruby/Node.
       Listener exceptions are swallowed so a broken listener can't
       break the 500 page.

    2. In non-debug mode, never put the stack trace in the response
       body (CWE-209). The trace is still available via ``Log.error``
       above and the dev-admin ``BrokenTracker`` in dev mode. The
       framework's own 500.twig now guards the trace block with
       ``{% if error_message %}``.
    """
    Log.error(f"Route error: {error}", path=request.path)
    _write_broken(request, error)

    try:
        from tina4_python.core.events import emit as _emit
        _emit("tina4.request.error", {"exception": error, "request": request})
    except Exception as listener_err:
        try:
            Log.warning(
                f"Listener for tina4.request.error raised: "
                f"{type(listener_err).__name__}: {listener_err}"
            )
        except Exception:
            pass

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
        # Production: NO traceback in the body. The trace is logged via
        # Log.error above; clients only see the generic page + request_id.
        html = _render_error_page(500, request.path, request_id, "")
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
    """Serve static files, templates, landing page, or 404.

    Lookup order at any URL with no registered route:
      1. Static file (public/, src/public/, framework public/, with /
         resolving to index.html so SPAs Just Work)
      2. Auto-routed template from src/templates/pages/ (gated by
         TINA4_TEMPLATE_ROUTING)
      3. Framework landing page — only at "/", and only in dev
         (``TINA4_DEBUG=true``). Production never shows it, so the
         framework version, dev-admin link, and gallery never leak
         to real users.
      4. 404
    """
    static = _try_static(request.path)
    if static:
        return static
    tpl_file = _resolve_template(request.path)
    if tpl_file:
        from tina4_python.core.response import get_frond
        html = get_frond().render(tpl_file, {})
        response.html(html)
    elif request.path == "/" and _is_dev_mode():
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


def _request_logging_enabled(is_dev: bool) -> bool:
    """Whether to emit a per-request log line (v3.13.14).

    ``TINA4_LOG_REQUESTS`` is the explicit control (true/false). When unset,
    request logging follows dev mode: on under ``TINA4_DEBUG``, off in
    production (so prod doesn't pay the per-request logging cost unless the
    operator opts in). Same contract across all four frameworks.
    """
    from tina4_python.dotenv import is_truthy
    val = os.environ.get("TINA4_LOG_REQUESTS")
    if val is not None and val != "":
        return is_truthy(val)
    return is_dev


# ── The dispatch pipeline ────────────────────────────────────────────
#
# ``handle`` was one 190-line function at cyclomatic complexity 27 against a
# ceiling of 10, on the path of every request. Its concerns are named and
# ordered as DATA below, so the pipeline can be read, tested and compared
# across the four frameworks without reading an implementation.
#
# Two groups, because the function genuinely has two:
#
#   _PRE_MATCH_STAGES   run in order until one RETURNS a Response. That
#                       response is sent AS IS - it does NOT go through the
#                       HEAD strip or ``_finalize_response``. That is existing
#                       behaviour, not a new shortcut: every one of these
#                       branches used a bare ``return`` today.
#   then                match -> dispatch -> HEAD strip -> finalize.
#
# Ordering is BEHAVIOUR, not taste: the CORS preflight answers before rate
# limiting (a browser preflight must not be throttled into a CORS error), dev
# routes beat the router, and the pre-match middleware runs before matching so
# its headers outlive a 401 (ADR-0012).
#
# Same shape as tina4-ruby/lib/tina4/dispatch_pipeline.rb and
# tina4-nodejs/packages/core/src/dispatchPipeline.ts.
class DispatchContext:
    """Per-request state shared between stages.

    Exists so a stage can be called with nothing but a context - the
    alternative is stages reading each other's locals, which is the coupling
    the extraction removes. ``request`` and ``response`` are REBOUND by
    middleware, so they live here rather than being passed by value.
    """

    __slots__ = ("request", "response", "request_id", "is_dev", "req_start", "route")

    def __init__(self, request: Request, response: Response, request_id: str):
        self.request = request
        self.response = response
        self.request_id = request_id
        self.is_dev = False
        self.req_start = 0.0
        self.route = None


async def _stage_cors_preflight(ctx: DispatchContext) -> Response | None:
    """Answer a CORS preflight.

    The response also carries the resource's REAL method set as ``Allow``
    (RFC 9110 s9.3.7): a preflight IS an OPTIONS response, so it answers the
    same question a bare OPTIONS does, on top of the CORS policy headers.

    This is CONFORMANCE, not a deviation. The frameworks' own OPTIONS handlers
    already do it - Django's ``View.options()`` sets Allow from
    ``_allowed_methods()``, Express's router auto-answers OPTIONS with Allow.
    The add-on CORS libraries (cors npm, django-cors-headers, rack-cors,
    stack-cors, ASP.NET CORS) omit it, but that is a LAYERING artifact: each
    sits ahead of the framework, so short-circuiting the preflight also skips
    the framework's OPTIONS handler and the header it would have produced.
    Tina4 owns both paths in one dispatcher. See ADR-0013.

    ``Allow`` and ``Access-Control-Allow-Methods`` are NOT interchangeable:
    Allow is what the resource supports, ACAM is what the CORS policy permits
    cross-origin. A policy allowing DELETE on a GET-only route still 405s. An
    unknown path yields "" - the same shape the bare-OPTIONS branch uses - so a
    client can tell "nothing here" from "not told".
    """
    if not _cors.is_preflight(ctx.request):
        return None

    _cors.apply(ctx.request, ctx.response)
    ctx.response.header("Allow", ", ".join(Router.methods_allowed_for_path(ctx.request.path)))
    ctx.response.status(204)
    return ctx.response


async def _stage_rate_limit(ctx: DispatchContext) -> Response | None:
    """Reject the request when it is over the configured rate limit."""
    return _handle_rate_limit(ctx.request, ctx.response)


async def _stage_start_timer(ctx: DispatchContext) -> None:
    """Start the request clock and resolve dev mode, for the stages that need them.

    Deliberately AFTER the preflight and rate-limit stages: neither of those
    reaches ``_finalize_response``, so neither is timed today.
    """
    import time as _time
    from tina4_python.dotenv import is_truthy

    ctx.req_start = _time.perf_counter()
    ctx.is_dev = is_truthy(os.environ.get("TINA4_DEBUG", ""))
    return None


async def _stage_trailing_slash_redirect(ctx: DispatchContext) -> Response | None:
    """301 ``/foo/`` to ``/foo`` when TINA4_TRAILING_SLASH_REDIRECT is on.

    The root ``/`` is skipped so the homepage still works. Cross-framework
    parity v3.12.4.
    """
    from tina4_python.dotenv import is_truthy

    if not is_truthy(os.environ.get("TINA4_TRAILING_SLASH_REDIRECT", "")):
        return None
    if len(ctx.request.path) <= 1 or not ctx.request.path.endswith("/"):
        return None

    canonical = ctx.request.path.rstrip("/") or "/"
    return ctx.response.status(301).header("location", canonical)


async def _stage_dev_admin(ctx: DispatchContext) -> Response | None:
    """Dev admin, service-health probes and the feedback widget's routes.

    Also catches /ai/api/chat (the SPA's ollama proxy) and the bare
    /ai /vision /embed /image /rag probes that drive the "SERVICES" dots in the
    dev-admin UI. The /__feedback/* routes live OUTSIDE /__dev because the
    widget is for whitelisted END USERS of the shipped app - they should not
    see any /__dev URL in their network tab.
    """
    if not ctx.is_dev:
        return None

    path = ctx.request.path
    if not (path.startswith("/__dev") or path.startswith("/__feedback")
            or path in _DEV_EXTRA_PATHS):
        return None

    return await _handle_dev_admin(ctx.request, ctx.response)


async def _stage_swagger(ctx: DispatchContext) -> Response | None:
    """Swagger UI and the OpenAPI document.

    ``_handle_swagger`` self-gates on ``swagger.is_enabled()``
    (TINA4_SWAGGER_ENABLED, else TINA4_DEBUG), so it is called on any GET: that
    honours an explicit prod-enable AND an explicit dev-disable, both of which
    the old ``_is_dev``-only gate silently ignored.
    """
    if ctx.request.method != "GET":
        return None
    return _handle_swagger(ctx.request, ctx.response)


async def _stage_reset_request_caches(ctx: DispatchContext) -> None:
    """Clear the request-scoped query cache.

    Identical SELECTs are deduped within this request but never served across
    requests (zero cross-request staleness). No-op when TINA4_DB_CACHE=true
    (persistent mode) or when caching is disabled.
    """
    try:
        from tina4_python.database.connection import Database as _Db
        _Db.reset_request_caches()
    except Exception:
        pass
    return None


async def _stage_global_middleware_pre(ctx: DispatchContext) -> Response | None:
    """PRE-MATCH global middleware.

    Runs before a route is even looked up, so CORS and anything else that must
    survive a short-circuit can set headers that outlive a 401/403. Opt in with
    ``pre_match = True``.
    """
    from tina4_python.core.middleware import Middleware as _Mw

    pre = _Mw.pre_match_middleware()
    if not pre:
        return None

    pre_route = {"middleware": pre, "handler": None}
    ctx.request, ctx.response, skip = _run_before_middleware(
        ctx.request, ctx.response, pre_route, include_globals=False
    )
    if not skip:
        return None

    _run_after_middleware(ctx.request, ctx.response, pre_route, include_globals=False)
    return ctx.response


#: Stages that run before route matching, in order. The first to return a
#: Response answers the request AS IS - no HEAD strip, no finalize.
_PRE_MATCH_STAGES = (
    _stage_cors_preflight,
    _stage_rate_limit,
    _stage_start_timer,
    _stage_trailing_slash_redirect,
    _stage_dev_admin,
    _stage_swagger,
    _stage_reset_request_caches,
    _stage_global_middleware_pre,
)

#: Dev-admin paths that live outside /__dev.
_DEV_EXTRA_PATHS = {"/ai/api/chat", "/ai", "/vision", "/embed", "/image", "/rag"}



def _Mw_pre() -> list:
    """The pre-match global middleware, for the after pass.

    A tiny indirection so the dispatch stage does not import Middleware at
    module scope - the rest of this file resolves it lazily too, to keep the
    import graph acyclic.
    """
    from tina4_python.core.middleware import Middleware

    return Middleware.pre_match_middleware()


async def _stage_dispatch_route(ctx: DispatchContext) -> None:
    """Match a route and run it, or fall through to 405 / 404.

    Order inside a matched route, and it is BEHAVIOUR (ADR-0012):
    POST-MATCH globals -> auth gate -> the route's OWN middleware -> handler.

    The globals run BEFORE the gate so a rate limiter can throttle a
    brute-force login and an access log records the 401 - neither is possible
    if they only run on authenticated requests. That is what every mainstream
    framework does: Django ships CsrfViewMiddleware ahead of
    AuthenticationMiddleware and enforces auth in a view decorator after all
    MIDDLEWARE, Laravel runs the `web` group before the `auth` route
    middleware, ASP.NET puts UseAuthorization last before the endpoint.

    The route's OWN middleware stays AFTER the gate, so middleware attached to
    a secured route never processes an unauthenticated request.
    """
    route, params = Router.match(ctx.request.method, ctx.request.path)
    ctx.route = route

    if not route:
        # Nothing claimed the path. The fallback chain is NOT called from here -
        # it is _FALLBACK_STAGES, walked by handle(). Ordering lives in the
        # lists, never in a call from one stage to another.
        return None

    ctx.request._route_params = params
    ctx.request.merge_route_params()
    # Expose the matched handler so before_* middleware (e.g. CsrfMiddleware)
    # can read handler metadata such as _noauth.
    ctx.request._handler = route.get("handler")

    try:
        ctx.request, ctx.response, skip = _run_before_middleware(
            ctx.request, ctx.response, {"middleware": [], "handler": route.get("handler")}
        )
        if not skip:
            skip = _check_auth(ctx.request, ctx.response, route)
        if not skip:
            ctx.request, ctx.response, skip = _run_before_middleware(
                ctx.request, ctx.response, route, include_globals=False
            )
        if not skip:
            ctx.response = await _invoke_handler_with_middleware(
                ctx.request, ctx.response, route, params
            )
        # The AFTER pass runs over EVERY global middleware - both phases - plus
        # the route's own, not just the post-match group.
        #
        # The response phase must cover everything the request phase entered.
        # Running only the post-match group meant a ``pre_match`` middleware's
        # after_* NEVER ran on a successful request: measured 0 runs in 5
        # requests. An acquire/release pair leaked one slot per request,
        # unbounded; a timer started in before_* was never stopped; an access
        # log saw the request and never the response - the very hole ADR-0012
        # moved the globals ahead of the auth gate to close.
        #
        # Worse, it inverted: the pre-match after_* DID run when the pre-match
        # pass short-circuited, so it fired on the error path and not the happy
        # one.
        #
        # Django unwinds its single MIDDLEWARE list in reverse, Laravel runs the
        # response/terminate phase for global, group AND route middleware, Rails
        # runs every declared after_action. Ruby and PHP already did this.
        # Splitting the BEFORE pass by dependency (ADR-0012) says nothing about
        # the after pass: an after hook adds headers or logging and needs no
        # route metadata either way.
        #
        # No double-run: when the pre-match pass short-circuits, handle()
        # returns before ever reaching this.
        _after_route = {
            "middleware": list(_Mw_pre()) + list(route.get("middleware", [])),
            "handler": route.get("handler"),
        }
        ctx.request, ctx.response = _run_after_middleware(ctx.request, ctx.response, _after_route)
    except Exception as e:
        ctx.response = _handle_route_error(
            e, ctx.request, ctx.response, ctx.request_id, ctx.is_dev
        )
    return None


def _stage_method_not_allowed(ctx: DispatchContext) -> bool:
    """RFC 9110 conformance, before falling through to 404 / static / template.

    Checks whether the PATH is known to the router under any OTHER method:
      - OPTIONS -> 204 No Content with Allow listing the methods (s9.3.7)
      - any other method (PUT on a GET-only route, TRACE, CONNECT) -> 405 with
        the Allow header (s15.5.6 + s10.2.1)

    Returns True when it answered, so ``_stage_not_found`` is skipped.
    """
    allowed = Router.methods_allowed_for_path(ctx.request.path)
    if not allowed:
        return False

    allow_header = ", ".join(allowed)
    ctx.response.header("Allow", allow_header)
    if ctx.request.method.upper() == "OPTIONS":
        ctx.response.status(204)
        return True

    ctx.response.status(405).json({
        "error": "Method Not Allowed",
        "path": ctx.request.path,
        "method": ctx.request.method,
        "allow": allowed,
        "status": 405,
    })
    return True


def _stage_not_found(ctx: DispatchContext) -> bool:
    """Nothing claimed the path: static, template, then 404.

    Terminal - it always answers, so it is last in ``_FALLBACK_STAGES``.
    """
    ctx.response = _handle_no_route(ctx.request, ctx.response, ctx.request_id)
    return True


def _stage_apply_cors(ctx: DispatchContext) -> None:
    """Apply the CORS policy headers to the finished response."""
    _cors.apply(ctx.request, ctx.response)
    return None


def _stage_dev_toolbar_inject(ctx: DispatchContext) -> None:
    """Inject the dev toolbar into an HTML response, in dev mode only.

    Best-effort: a toolbar that fails to render must never break the response
    it was decorating, so the whole thing is guarded.
    """
    if not ctx.is_dev or not ctx.response.content_type:
        return None
    if "text/html" not in ctx.response.content_type:
        return None
    if ctx.request.path.startswith("/__dev"):
        return None

    try:
        from tina4_python.dev_admin import render_dev_toolbar
        toolbar = render_dev_toolbar(
            ctx.request.method, ctx.request.path,
            ctx.route["path"] if ctx.route else "-",
            ctx.request_id, len(Router.get_routes()),
        ).encode()
        body = ctx.response.content
        ctx.response.content = (
            body.replace(b"</body>", toolbar + b"\n</body>", 1)
            if b"</body>" in body else body + toolbar
        )
    except Exception:
        pass
    return None


def _stage_dev_inspector_capture(ctx: DispatchContext) -> None:
    """Record the request for the /__dev dashboard, in dev mode only.

    Runs AFTER the toolbar injection so ``body_size`` reports what actually
    went on the wire, not the pre-injection body.
    """
    if not ctx.is_dev:
        return None
    try:
        import time as _time
        from tina4_python.dev_admin import RequestInspector
        RequestInspector.capture(
            ctx.request.method, ctx.request.path, ctx.response.status_code,
            (_time.perf_counter() - ctx.req_start) * 1000,
            body_size=len(ctx.response.content) if ctx.response.content else 0,
            ip=ctx.request.ip,
        )
    except Exception:
        pass
    return None


def _stage_request_log(ctx: DispatchContext) -> None:
    """Emit the per-request log line (v3.13.14).

    The dev dashboard's RequestInspector above only feeds the /__dev UI - it
    never reached stdout, so ``tina4 serve`` printed the startup banner then
    went silent even as requests flowed. This lands on stdout (docker logs /
    k8s) like every other log. On by default in dev; opt in in production via
    TINA4_LOG_REQUESTS, to avoid the per-request overhead.
    """
    if not _request_logging_enabled(ctx.is_dev):
        return None
    try:
        import time as _time
        elapsed_ms = round((_time.perf_counter() - ctx.req_start) * 1000, 3)
        Log.info(
            f"{ctx.request.method} {ctx.request.path} -> "
            f"{ctx.response.status_code} ({elapsed_ms}ms)"
        )
    except Exception:
        pass
    return None


def _stage_session_save(ctx: DispatchContext) -> None:
    """Persist the session and set its cookie.

    A brand-new session the route never wrote to is NOT saved - that is what
    stops empty orphaned session files accumulating on disk.
    """
    if ctx.request.session is None:
        return None
    session = ctx.request.session
    try:
        if not (getattr(session, "_is_new", False) and not session.all()):
            session.save()
            sid = getattr(session, "session_id", None) or getattr(session, "id", None)
            if sid:
                # Route through the single cookie-builder so every
                # TINA4_SESSION_* knob (Secure/HttpOnly/SameSite) and the
                # proxy-aware Secure detection actually take effect. Do NOT
                # hand-write a second Set-Cookie here - that bypass is what made
                # TINA4_SESSION_SECURE a silent no-op (#95).
                ctx.response.header(
                    "set-cookie", session.cookie_header(request=ctx.request)
                )
        # Probabilistic GC (~1% of requests). INSIDE the try and AFTER the save,
        # exactly as before: a session that failed to save does not then get
        # garbage collected. It runs for a new-and-empty session too, which is
        # why it sits outside the save branch rather than in it.
        import random
        if random.randint(1, 100) == 1:
            session.gc()
    except Exception:
        pass
    return None


def _stage_head_strip(ctx: DispatchContext) -> None:
    """RFC 9110 s9.3.2: a HEAD response MUST NOT include content.

    Strips the body unconditionally - even for an explicit ``Router.head()``
    handler that accidentally returned one - and records what Content-Length
    the GET would have sent, because cache validators, link checkers and
    monitoring probes size their estimates from it.

    Python strips LATE, at the single return point; Node wraps write/end EARLY
    because it streams and has no single exit. ADR-0011 keeps the OUTCOME
    shared and the mechanism idiomatic per runtime.
    """
    if ctx.request.method.upper() != "HEAD":
        return None

    body = ctx.response.content if ctx.response.content is not None else b""
    if isinstance(body, str):
        body = body.encode("utf-8")
    if body:
        ctx.response.header("Content-Length", str(len(body)))
        ctx.response.content = b""
    return None


#: Match a route and run it. ``_stage_dispatch_route`` leaves ``ctx.route``
#: None when nothing claimed the path, and the fallback chain below answers.
_POST_MATCH_STAGES = (
    _stage_dispatch_route,
)

#: Walked ONLY when no route matched, in order, until one answers True.
#: ADR-0010 (routes beat files) is why this runs AFTER matching: a file dropped
#: into src/public/ by a build step must never shadow a reviewed route.
_FALLBACK_STAGES = (
    _stage_method_not_allowed,
    _stage_not_found,
)

#: Run over the finished Response on the way out, in order.
#:
#: Order is BEHAVIOUR: the inspector runs AFTER the toolbar injection so its
#: body_size reports what went on the wire, and ``_stage_head_strip`` is LAST
#: because the toolbar injection would otherwise put 8.5KB of markup back into
#: an already-stripped HEAD response - the body removed and then restored. A
#: run without TINA4_DEBUG could not see that. Stripping last also makes
#: Content-Length report the body AFTER injection, which is exactly what the
#: equivalent GET would send (RFC 9110 s9.3.2).
_RESPONSE_STAGES = (
    _stage_apply_cors,
    _stage_dev_toolbar_inject,
    _stage_dev_inspector_capture,
    _stage_request_log,
    _stage_session_save,
    _stage_head_strip,
)


async def handle(request: Request) -> Response:
    """Dispatch a pre-built Request through the Tina4 router and return a Response.

    Handles session setup, CORS, rate limiting, routing, auth, middleware,
    dev toolbar injection, and session saving. The caller is responsible
    for sending the response over the wire. Useful for testing and embedding.

    Every branch this used to hold now lives in a named stage. The only control
    flow left here is "walk a list, stop when a stage answers" - four times,
    over ``_PRE_MATCH_STAGES``, ``_POST_MATCH_STAGES``, ``_FALLBACK_STAGES``
    and ``_RESPONSE_STAGES``.
    """
    request_id = request.headers.get("x-request-id", str(uuid.uuid4())[:8])
    set_request_id(request_id)
    _init_session(request)

    response = Response()
    response.header("x-request-id", request_id)

    ctx = DispatchContext(request, response, request_id)

    for stage in _PRE_MATCH_STAGES:
        answered = await stage(ctx)
        if answered is not None:
            # Sent AS IS: these branches bypass the HEAD strip and finalize,
            # exactly as they did when each was a bare `return`.
            return answered

    for stage in _POST_MATCH_STAGES:
        await stage(ctx)

    if ctx.route is None:
        for stage in _FALLBACK_STAGES:
            if stage(ctx):
                break

    for stage in _RESPONSE_STAGES:
        stage(ctx)

    return ctx.response

async def app(scope: dict, receive, send):
    """ASGI entry point — compatible with uvicorn, hypercorn, granian."""
    if scope["type"] == "lifespan":
        # ASGI lifespan is ONE call carrying BOTH events, so this has to loop.
        # It used to return after the first message, which made the shutdown
        # branch below unreachable: the app coroutine had already finished by
        # the time the server sent lifespan.shutdown.
        while True:
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                import time
                global _start_time
                _start_time = time.time()
                await send({"type": "lifespan.startup.complete"})
            elif msg["type"] == "lifespan.shutdown":
                # The only shutdown hook that fires on the production path.
                # uvicorn restores the default signal handlers and RE-RAISES the
                # signal as its run() returns, so the process dies inside the
                # starter and nothing after it ever executes — a `finally` there
                # is unreachable. uvicorn drains requests and closes sockets
                # itself; the ORM-bound connections are the part only Tina4
                # knows about, so this is where they get closed.
                _close_bound_databases()
                await send({"type": "lifespan.shutdown.complete"})
                return
            else:
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

    # Streaming responses bypass ETag/compression — send immediately
    _streaming = getattr(response, "_is_streaming", False)
    if _streaming:
        # Streaming response — send headers then stream chunks
        stream_headers = [
            (b"content-type", response.content_type.encode()),
        ]
        for name, value in response._headers:
            stream_headers.append((name.lower().encode(), value.encode()))
        for cookie_str in response._cookies:
            stream_headers.append((b"set-cookie", cookie_str.encode()))
        await send({"type": "http.response.start", "status": response.status_code, "headers": stream_headers})

        import asyncio
        source = response._stream_source
        try:
            if hasattr(source, "__aiter__"):
                # Async generator
                async for chunk in source:
                    if isinstance(chunk, str):
                        chunk = chunk.encode()
                    await send({"type": "http.response.body", "body": chunk, "more_body": True})
            elif hasattr(source, "__iter__"):
                # Sync iterable
                for chunk in source:
                    if isinstance(chunk, str):
                        chunk = chunk.encode()
                    await send({"type": "http.response.body", "body": chunk, "more_body": True})
                    await asyncio.sleep(0)  # yield control
        except asyncio.CancelledError:
            # Client disconnected mid-stream. Close the source if it supports it
            # (best-effort) then re-raise — cancellation must never be swallowed.
            aclose = getattr(source, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception:
                    pass
            raise
        except Exception as exc:
            # The generator itself raised mid-stream. Log and stop cleanly —
            # fall through to the final empty-body send rather than crashing
            # the worker.
            Log.error(f"SSE/stream source error: {exc}")

        await send({"type": "http.response.body", "body": b"", "more_body": False})
        return

    # Customer feedback widget injection — adds <script src="/__feedback/widget.js">
    # to HTML responses for whitelisted users. No-op if the feature is
    # off (TINA4_FEEDBACK_WHITELIST empty) or the user isn't whitelisted
    # or the body isn't HTML. Done BEFORE ETag/header build so the
    # injected bytes are included in the ETag hash + Content-Length.
    try:
        if (
            response.content
            and isinstance(response.content, (bytes, bytearray))
            and "text/html" in (response.content_type or "").lower()
        ):
            from tina4_python.dev_admin import inject_feedback_widget
            response.content = inject_feedback_widget(request, bytes(response.content))
    except Exception:
        pass  # Injection is best-effort — never break the response.

    # ETag check — 304 Not Modified
    if_none_match = request.headers.get("if-none-match", "")
    accept_encoding = request.headers.get("accept-encoding", "")
    headers = response.build_headers(accept_encoding)

    etag = ""
    for name, value in headers:
        if name == b"etag":
            etag = value.decode()
            break
    if if_none_match and if_none_match == etag:
        await send({"type": "http.response.start", "status": 304, "headers": []})
        await send({"type": "http.response.body", "body": b""})
        return

    # If-Modified-Since -> 304, for responses carrying a Last-Modified (static
    # assets). If-None-Match takes precedence (RFC 9110 13.1.3), so this only
    # runs when the client sent no ETag validator.
    if not if_none_match:
        if_modified_since = request.headers.get("if-modified-since", "")
        last_modified = ""
        for name, value in headers:
            if name == b"last-modified":
                last_modified = value.decode()
                break
        if if_modified_since and last_modified:
            try:
                if parsedate_to_datetime(last_modified) <= parsedate_to_datetime(if_modified_since):
                    await send({"type": "http.response.start", "status": 304, "headers": []})
                    await send({"type": "http.response.body", "body": b""})
                    return
            except (TypeError, ValueError):
                pass  # Unparseable date -> serve the body (never 304 on garbage).

    await send({"type": "http.response.start", "status": response.status_code, "headers": headers})
    await send({"type": "http.response.body", "body": response.content})


def _try_static(path: str) -> Response | None:
    """Serve static files. Searches multiple directories.

    Search order (first match wins):
    1. TINA4_PUBLIC_DIR env var (if set)
    2. public/           (simple, IDE-friendly)
    3. src/public/       (nested convention)
    4. tina4_python/public/  (framework built-in assets)

    Index resolution: when ``path`` is ``/`` or ends with ``/``, the lookup
    appends ``index.html`` so a Vite/SPA build with ``src/public/index.html``
    serves at the matching URL — no custom ``@get("/")`` route needed.
    """
    clean = path.lstrip("/")

    # The framework ships the Swagger UI as STATIC assets under
    # tina4_python/public/swagger/. Static serving is independent of the gated
    # /swagger routes, so without this check the UI stays reachable in production
    # via '/swagger/', '/swagger/index.html' or '/swagger/oauth2-redirect.html'
    # even when swagger is disabled -- silently bypassing TINA4_SWAGGER_ENABLED /
    # TINA4_DEBUG. (A bare '/swagger' already 404s because index resolution below
    # only fires for '' or a trailing slash, which is why this leak hid.)
    # Checked BEFORE index resolution so the trailing-slash form is caught too.
    if clean == "swagger" or clean.startswith("swagger/"):
        from tina4_python.swagger import is_enabled as _swagger_enabled
        if not _swagger_enabled():
            return None

    # Index resolution: '/' or '/foo/' -> append 'index.html' so SPA builds
    # in src/public/ Just Work without a custom root route.
    if clean == "" or clean.endswith("/"):
        clean = clean + "index.html"
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
            # Static assets may be cached but must be revalidated on every use,
            # so a redeployed file reaches the browser on the next load without a
            # manual hard refresh. The response already carries an ETag
            # (build_headers) and the pipeline answers If-None-Match with a 304,
            # so revalidation is a cheap round-trip, not a re-download. A
            # Last-Modified is added too (pipeline honours If-Modified-Since ->
            # 304) so the validators match the other frameworks.
            resp.header("cache-control", "no-cache, must-revalidate")
            resp.header(
                "last-modified",
                formatdate(file_path.stat().st_mtime, usegmt=True),
            )
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
            uvicorn.run(asgi_app, host=host, port=port, log_level="info",
                        timeout_graceful_shutdown=_shutdown_timeout_whole_seconds())
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
            cfg.graceful_timeout = _resolve_shutdown_timeout()
            asyncio.run(hypercorn.asyncio.serve(asgi_app, cfg))
        return "hypercorn", _start_hypercorn
    except ImportError:
        pass
    try:
        import granian
        def _start_granian(host, port, asgi_app):
            from granian import Granian
            Log.warning(
                "granian has no request-drain deadline, so TINA4_SHUTDOWN_TIMEOUT "
                "is NOT honoured on this path (workers_kill_timeout is when to kill "
                "a worker, not how long to drain)"
            )
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

    # Host: CLI flag > TINA4_HOST env > HOST env > default.
    # TINA4_HOST takes precedence over the legacy plain HOST so a stray
    # OS-level HOST (common on shared CI runners) can't silently override
    # the framework's bind address. See cross-framework v3.12.4 plan.
    if cli_host is not None:
        host = cli_host
    else:
        host = os.environ.get("TINA4_HOST") or os.environ.get("HOST", default_host)

    # Port: CLI flag > PORT env > default
    if cli_port is not None:
        port = cli_port
    else:
        env_port = os.environ.get("PORT")
        port = int(env_port) if env_port and env_port.isdigit() else default_port

    return host, port


def banner_surface_lines(
    port: int, *, swagger_enabled: bool, dev_admin_enabled: bool
) -> tuple[str, str]:
    """Build the startup banner's optional surface lines (issue #99).

    Only advertise a surface that is actually REACHABLE. In production, or with
    ``TINA4_DEBUG`` off, ``/swagger`` and ``/__dev`` return 404 -- printing them
    anyway both misleads an operator into believing a dev surface is exposed and
    sends a developer to a dead link.

    Kept as a pure function of (port, two booleans) so the contract is unit
    testable without booting a server and grepping stdout. Parity: PHP
    ``App::bannerSurfaceLines``, Ruby ``Tina4.banner_surface_lines``, Node
    ``bannerSurfaceLines``.

    :return: ``(swagger_line, dashboard_line)`` -- each either empty, or a
             newline followed by the banner row, ready to interpolate.
    """
    swagger_line = (
        f"\n  Swagger:   http://localhost:{port}/swagger" if swagger_enabled else ""
    )
    dashboard_line = (
        f"\n  Dashboard: http://localhost:{port}/__dev" if dev_admin_enabled else ""
    )
    return swagger_line, dashboard_line


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

    # Only advertise a surface that is actually reachable (issue #99).
    from tina4_python.swagger import is_enabled as _swagger_enabled
    swagger_line, dashboard_line = banner_surface_lines(
        port, swagger_enabled=_swagger_enabled(), dev_admin_enabled=is_debug
    )

    banner = f"""{color}
  ______ _             __ __
 /_  __/(_)___  ____ _/ // /
  / /  / / __ \\/ __ `/ // /_
 / /  / / / / / /_/ /__  __/
/_/  /_/_/ /_/\\__,_/  /_/
{reset}
  Tina4 Python v{__version__} — The Intelligent Native Application 4ramework

  Server:    http://{display}:{port} ({server_name}){swagger_line}{dashboard_line}
  Debug:     {"ON" if is_debug else "OFF"} (Log level: {log_level}){ai_port_line}
"""
    print(banner)


# Legacy env var names that v3.12 has retired. If any of these are set in
# the environment we refuse to boot — silently ignoring them would cause
# auth/db/mail to fall back to defaults with no warning. Each maps to its
# new TINA4_-prefixed canonical name (or DROPPED for deleted features).
_LEGACY_ENV_VARS: dict[str, str] = {
    "DATABASE_URL":           "TINA4_DATABASE_URL",
    "DATABASE_USERNAME":      "TINA4_DATABASE_USERNAME",
    "DATABASE_PASSWORD":      "TINA4_DATABASE_PASSWORD",
    "DB_URL":                 "TINA4_DATABASE_URL",
    "SECRET":                 "TINA4_SECRET",
    "API_KEY":                "TINA4_API_KEY",
    "JWT_ALGORITHM":          "TINA4_JWT_ALGORITHM",
    "SMTP_HOST":              "TINA4_MAIL_HOST",
    "SMTP_PORT":              "TINA4_MAIL_PORT",
    "SMTP_USERNAME":          "TINA4_MAIL_USERNAME",
    "SMTP_PASSWORD":          "TINA4_MAIL_PASSWORD",
    "SMTP_FROM":              "TINA4_MAIL_FROM",
    "SMTP_FROM_NAME":         "TINA4_MAIL_FROM_NAME",
    "IMAP_HOST":              "TINA4_MAIL_IMAP_HOST",
    "IMAP_PORT":              "TINA4_MAIL_IMAP_PORT",
    "IMAP_USER":              "TINA4_MAIL_IMAP_USERNAME",
    "IMAP_PASS":              "TINA4_MAIL_IMAP_PASSWORD",
    "HOST_NAME":              "TINA4_HOST_NAME",
    "SWAGGER_TITLE":          "TINA4_SWAGGER_TITLE",
    "SWAGGER_DESCRIPTION":    "TINA4_SWAGGER_DESCRIPTION",
    "SWAGGER_VERSION":        "TINA4_SWAGGER_VERSION",
    "ORM_PLURAL_TABLE_NAMES": "TINA4_ORM_PLURAL_TABLE_NAMES",
}


def _check_legacy_env_vars() -> None:
    """Refuse to boot if pre-3.12 un-prefixed env vars are still set.

    Tina4 v3.12 hard-renamed every framework-specific env var to use the
    ``TINA4_`` prefix. Booting silently with a legacy ``DATABASE_URL`` or
    ``SECRET`` would let auth, DB, or mail fall back to insecure defaults
    while the user thought their config was being read. Better to die
    loudly with a list of names to fix.

    Bypass with ``TINA4_ALLOW_LEGACY_ENV=true`` in CI / migration scripts
    that genuinely need both names set during a transition window.
    """
    if os.environ.get("TINA4_ALLOW_LEGACY_ENV", "").lower() in ("true", "1", "yes"):
        return
    found = sorted(name for name in _LEGACY_ENV_VARS if name in os.environ)
    if not found:
        return
    msg = ["", "─" * 72,
           "Tina4 v3.12 requires TINA4_ prefix on all framework env vars.",
           "Your environment still has these legacy names:",
           ""]
    for old in found:
        new = _LEGACY_ENV_VARS[old]
        msg.append(f"    {old:<28}  →  {new}")
    msg.extend(["",
                "Note: these may come from a .env file loaded by dotenv, not just",
                "the runtime environment — check your image / build context (a .env",
                "baked into a Docker image is loaded at startup) as well as k8s/CI env.",
                "",
                "FIX: run `tina4 env --migrate` to rewrite your .env automatically",
                "(it renames every legacy name to its TINA4_ form in place).",
                "Or rename manually. See https://tina4.com/release/3.12.0",
                "Set TINA4_ALLOW_LEGACY_ENV=true to bypass during migration.",
                "─" * 72, ""])
    print("\n".join(msg), file=sys.stderr)
    sys.exit(2)


def _auto_migrate_on_startup(migration_folder: str = "migrations") -> None:
    """Apply pending DB migrations on startup — NON-BREAKING.

    When a ``migrations/`` folder exists (with at least one ``.sql`` file) and
    ``TINA4_AUTO_MIGRATE`` is not disabled, pending migrations are applied during
    boot so the schema is current with no manual ``tina4 migrate`` step. A
    failure here is logged LOUD and the service STILL starts — a bad migration
    must never take the backend down. (The explicit ``tina4 migrate`` CLI stays
    fail-fast so CI still gets a non-zero exit.)

    Disable with ``TINA4_AUTO_MIGRATE=false`` — e.g. multi-instance production
    that migrates as a separate deploy step (concurrent first-apply can race).
    """
    from pathlib import Path
    from tina4_python.dotenv import is_truthy

    folder = Path(migration_folder)
    if not folder.is_dir() or not any(folder.glob("*.sql")):
        return  # no migrations → nothing to do (silent)
    if not is_truthy(os.environ.get("TINA4_AUTO_MIGRATE", "true")):
        Log.debug("TINA4_AUTO_MIGRATE is off — skipping startup migrations")
        return

    try:
        from tina4_python.database import Database
        db = Database()  # resolves TINA4_DATABASE_URL (framework default if unset)
    except Exception as exc:
        Log.debug(f"Startup migrations skipped (no database configured): {exc}")
        return

    try:
        from tina4_python.migration import migrate
        applied = migrate(db)
        if applied:
            Log.info(f"Applied {len(applied)} pending migration(s) on startup")
    except Exception as exc:
        Log.error(
            f"Startup auto-migration failed: {exc} — the service is starting "
            "anyway. Run `tina4 migrate` to retry."
        )
    finally:
        try:
            db.close()  # transient migration connection — don't leak it at boot
        except Exception:
            pass


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

    # Refuse to boot with v3.11 / v2 era un-prefixed env vars set.
    _check_legacy_env_vars()

    # ── Require tina4 CLI ─────────────────────────────────────────
    # The framework must be launched via `tina4 serve`, not `python app.py`.
    # The tina4 CLI passes --managed when spawning the server process.
    # Users can bypass this by adding TINA4_OVERRIDE_CLIENT=true to .env
    is_managed = "--managed" in sys.argv
    if not is_managed and os.environ.get("TINA4_OVERRIDE_CLIENT") != "true":
        # Load .env early so TINA4_OVERRIDE_CLIENT can be read.
        # ONE call: load_env() with no argument treats the cwd as the ROOT and
        # applies real-env > .env.local > .env itself. It used to be two calls
        # here and two more below, and a caller who got the order or the
        # override flag wrong let a stray gitignored .env.local clobber an
        # explicitly-set real env var. The rule now lives in one place.
        from tina4_python.dotenv import load_env
        load_env(override=False)
        if os.environ.get("TINA4_OVERRIDE_CLIENT") != "true":
            print()
            print("=" * 60)
            print()
            print("  Tina4 must be started with the tina4 CLI:")
            print()
            print("    tina4 serve              (development)")
            print("    tina4 serve --production (production)")
            print()
            print("  Install: cargo install tina4")
            print("  Docs:    https://tina4.com")
            print()
            print("  To run directly, add to .env:")
            print("    TINA4_OVERRIDE_CLIENT=true")
            print()
            print("=" * 60)
            print()
            sys.exit(1)

    if no_reload:
        os.environ["TINA4_NO_RELOAD"] = "true"

    # Ensure CWD is on sys.path so auto-discovered modules can be imported
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    # Load env so vars are available for logger init. ONE call - load_env()
    # applies real-env > .env.local > .env itself (see the note above). A
    # previously-generated dev secret in .env.local is still picked up when no
    # real value is set, and TINA4_ENV_FILE still names the .env while
    # .env.local beside it keeps applying.
    from tina4_python.dotenv import load_env
    load_env(override=False)

    # Fail-safe dev secret: if TINA4_SECRET is blank AND we are in dev (not CI,
    # not prod), mint a per-machine random secret, persist it to .env.local
    # (gitignored), and set it in the process env for this run. In CI/prod this
    # emits an actionable warning instead. Runs after env load, before auth is
    # used. Never crashes boot — file-write failures fall back to in-memory.
    from tina4_python.auth import ensure_dev_secret
    ensure_dev_secret()

    # Init logger
    is_production = os.environ.get("TINA4_ENV", "development") == "production"
    # v3.13.14: default level is INFO (was ERROR). ERROR-by-default meant a
    # deployed app that logged at info/debug appeared silent — operators
    # "weren't getting logs". INFO shows request/startup/warn/error without
    # debug noise, and matches PHP/Ruby/Node defaults. Override per-deploy
    # with TINA4_LOG_LEVEL.
    log_level = os.environ.get("TINA4_LOG_LEVEL", "info")
    Log.configure(level=log_level, production=is_production)

    # Install a top-level exception hook so uncaught exceptions bubbling
    # out of anything (a route handler, a background task, the event
    # loop itself on startup) land in logs/error.log. Without this,
    # an uncaught exception surfaces only via Python's default stderr
    # writer and never touches Log — the same gap PHP had before its
    # set_exception_handler fix. Chains to the previous hook so any
    # debugger / IDE hook already in place still fires.
    import sys as _sys
    import traceback as _traceback
    _prior_excepthook = _sys.excepthook

    def _tina4_excepthook(exc_type, exc_value, exc_tb):
        # KeyboardInterrupt is a user-initiated Ctrl+C, not an error —
        # defer to the prior hook (which prints a clean traceback).
        if issubclass(exc_type, KeyboardInterrupt):
            _prior_excepthook(exc_type, exc_value, exc_tb)
            return
        try:
            trace_text = "".join(_traceback.format_exception(exc_type, exc_value, exc_tb))
            Log.error(
                f"Uncaught {exc_type.__name__}: {exc_value}",
                trace=trace_text,
            )
        except Exception:
            # If logging itself fails (disk full, permissions, logger
            # not initialised yet), fall through to the prior hook so
            # the user still sees something in stderr.
            pass
        _prior_excepthook(exc_type, exc_value, exc_tb)

    _sys.excepthook = _tina4_excepthook

    # Ensure folders
    _ensure_folders()

    # Auto-wire i18n → Frond global t() if locale files exist
    _auto_wire_i18n()

    # Auto-discover routes
    _auto_discover("src")
    route_count = len(Router.get_routes())
    Log.info(f"Discovered {route_count} routes")

    # Apply pending DB migrations on startup (non-breaking — see helper).
    _auto_migrate_on_startup()

    # Resolve host/port (CLI arg > ENV > default)
    host, port = resolve_config(cli_host=host, cli_port=port)

    # Claim the requested port — kill whatever is on it if needed
    port = _find_available_port(port)

    # Detect production server (unless TINA4_DEBUG is true)
    from tina4_python.dotenv import is_truthy
    is_debug = is_truthy(os.environ.get("TINA4_DEBUG", ""))

    # File watching is handled by the Rust CLI (tina4 serve). The framework
    # only needs to receive POST /__dev/api/reload, re-import the changed
    # module in-process, and push an instant reload over the /__dev_reload
    # WebSocket. The mtime counter at /__dev/api/mtime is the polling
    # fallback for when that socket is down. No internal watcher.
    if is_debug:
        _register_dev_reload_ws()

    # TINA4_DEFAULT_WEBSERVER=TRUE pins Tina4's own built-in webserver, so an
    # operator (or CI) can exercise it deterministically without also turning on
    # debug mode and everything that comes with it. Unset/FALSE is unchanged:
    # a production ASGI server is used when one is installed.
    use_builtin_webserver = is_truthy(os.environ.get("TINA4_DEFAULT_WEBSERVER", ""))

    prod = None
    if not is_debug and not use_builtin_webserver:
        prod = _find_production_server()

    server_name = prod[0] if prod else "asyncio"

    # Determine AI dev port (port+1) when debug is on and not suppressed
    _no_ai_port = os.environ.get("TINA4_NO_AI_PORT", "").lower() in ("true", "1", "yes")
    _ai_port = (port + 1000) if (is_debug and not _no_ai_port) else None

    # Banner — printed directly to stdout, not through the logger.
    # TINA4_SUPPRESS=true silences the startup banner (useful in CI / Docker
    # logs where the ASCII art is just noise). Cross-framework parity v3.12.4.
    from tina4_python.dotenv import is_truthy as _is_truthy
    if not _is_truthy(os.environ.get("TINA4_SUPPRESS", "")):
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
        # Databases are closed from the ASGI lifespan.shutdown handler in app(),
        # NOT here: uvicorn re-raises the signal as it returns, so the process
        # dies inside starter() and any cleanup after this call is unreachable.
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
                await _handle_dev_websocket(reader, writer, _header_dict, path, qs)
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

            _headers_sent = False

            async def send(msg):
                nonlocal resp_started, resp_status, resp_headers, resp_body, _headers_sent
                if msg["type"] == "http.response.start":
                    resp_started = True
                    resp_status = msg["status"]
                    resp_headers = msg.get("headers", [])
                elif msg["type"] == "http.response.body":
                    chunk = msg.get("body", b"")
                    more = msg.get("more_body", False)

                    if more or _headers_sent:
                        # Streaming mode — flush headers on first chunk, then write each chunk immediately
                        if not _headers_sent:
                            _headers_sent = True
                            writer.write(f"HTTP/1.1 {resp_status} {_http_reason(resp_status)}\r\n".encode())
                            for name, value in resp_headers:
                                writer.write(name + b": " + value + b"\r\n")
                            writer.write(b"\r\n")
                            await writer.drain()

                        if chunk:
                            writer.write(chunk)
                            await writer.drain()

                        if not more:
                            writer.close()
                    else:
                        # Buffered mode — accumulate body
                        resp_body = chunk

            await app(scope, receive, send)

            # Write HTTP/1.1 response (only if headers weren't already sent by streaming)
            if not _headers_sent:
                status_line = f"HTTP/1.1 {resp_status} {_http_reason(resp_status)}\r\n"
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

        # Start registered background tasks as asyncio tasks.
        # Sync callbacks run in a thread pool so they CANNOT block the event loop.
        # max_workers is one per registered task — sound only because a task never
        # overlaps itself (see background_tick_loop), so tasks cannot starve each
        # other of workers.
        import concurrent.futures
        _executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(background_task_count(), 2),
            thread_name_prefix="tina4_bg",
        )
        bg_tasks = _start_background_tasks(_executor, shutdown)

        await shutdown.wait()

        # 1. Stop accepting FIRST. A connection that arrives after the signal
        #    must get a clean CONNECTION REFUSED — not a 503, not a TCP reset.
        live_servers = [s for s in (ai_server, server) if s is not None]
        for live_server in live_servers:
            live_server.close()

        # 2. Stop background work.
        for t in bg_tasks:
            t.cancel()

        # 3. Drain what is already in flight, BOUNDED. wait_closed() on its own
        #    waits forever, so one wedged handler (or one idle WebSocket) used to
        #    hold the process open past any orchestrator's grace period.
        timeout_seconds = _resolve_shutdown_timeout()
        try:
            async with asyncio.timeout(timeout_seconds):
                # A live WebSocket never drains by itself — tell it we are going
                # away (RFC 6455 close code 1001) so the client reconnects
                # elsewhere instead of seeing the socket vanish. A dead peer
                # must not turn a clean exit 0 into a crash on the way out.
                try:
                    await _ws_manager.disconnect_all(
                        code=CLOSE_GOING_AWAY, reason="server shutting down")
                except Exception as exc:  # noqa: BLE001 — never fail the exit
                    Log.error(f"Error closing WebSocket connections on shutdown: {exc}")
                for live_server in live_servers:
                    await live_server.wait_closed()
        except TimeoutError:
            Log.warning(
                f"TINA4_SHUTDOWN_TIMEOUT={timeout_seconds:g}s reached with work still "
                f"in flight — forcing the remaining connections closed"
            )
            for live_server in live_servers:
                # Python 3.13+. On 3.12 the tasks are cancelled by asyncio.run's
                # own teardown instead, which still gets us out.
                abort_clients = getattr(live_server, "abort_clients", None)
                if abort_clients is not None:
                    abort_clients()

        # 4. Release the resources the OS would otherwise reap for us.
        _close_bound_databases()
        _executor.shutdown(wait=False, cancel_futures=True)
        Log.info("Server stopped.")

    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        pass


# ── Module-level server reference for start()/stop() ────────────────────
_server_handle: dict | None = None


def start(host: str | None = None, port: int | None = None, no_browser: bool = True, no_reload: bool = False):
    """Start the Tina4 HTTP server.

    Thin wrapper around run() for cross-framework parity with PHP and Ruby.
    """
    run(host=host, port=port, no_browser=no_browser, no_reload=no_reload)


def stop():
    """Stop the running Tina4 server gracefully.

    Sends SIGTERM to the current process which triggers the asyncio
    shutdown event inside run(). Safe to call from signal handlers or
    separate threads.
    """
    os.kill(os.getpid(), signal.SIGTERM)
