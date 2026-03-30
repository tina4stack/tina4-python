# Tina4 DevReload — File-change detection via mtime polling.
"""
Watches source files for changes and triggers route re-discovery.
Active only when TINA4_DEBUG=true.

The browser-side polling is handled by JS injected into the dev toolbar,
which polls /__dev/api/mtime and reloads when the timestamp changes.

Uses simple mtime polling (no external dependencies).
"""
import os
import sys
import time
import importlib
import threading
from pathlib import Path

from tina4_python.debug import Log


# Watched file extensions
_WATCH_EXTENSIONS = {".py", ".twig", ".html", ".css", ".scss", ".js"}

# Directories to ignore (anywhere in the path)
_IGNORE_DIRS = {".git", "node_modules", "vendor", "__pycache__", "data", ".venv", ".mypy_cache", ".ruff_cache"}

# Module-level state
_last_mtime: float = 0.0
_last_change_file: str = ""
_lock = threading.Lock()
_running = False


def get_last_mtime() -> float:
    """Return the most recent file modification timestamp."""
    return _last_mtime


def get_last_change_file() -> str:
    """Return the path of the most recently changed file."""
    return _last_change_file


def _should_ignore(path: Path) -> bool:
    """Check if a path should be ignored based on directory names."""
    for part in path.parts:
        if part in _IGNORE_DIRS:
            return True
    return False


def _scan_mtime(directories: list[str]) -> tuple[float, str]:
    """Scan directories for the maximum file mtime.

    Returns (max_mtime, file_path) tuple.
    """
    max_mtime = 0.0
    max_file = ""

    for dir_path in directories:
        root = Path(dir_path)
        if not root.is_dir():
            continue

        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix not in _WATCH_EXTENSIONS:
                continue
            if _should_ignore(file_path):
                continue

            try:
                mtime = file_path.stat().st_mtime
                if mtime > max_mtime:
                    max_mtime = mtime
                    max_file = str(file_path)
            except OSError:
                continue

    return max_mtime, max_file


def _rediscover_routes():
    """Re-import changed Python modules in src/ to pick up new/changed routes.

    Clears the route registry and re-discovers all routes from scratch.
    This ensures removed routes are also cleaned up.
    """
    from tina4_python.core.router import Router, _routes

    # Remember route count before
    before = len(_routes)

    # Reload all src/ modules that are already in sys.modules
    root = Path("src").resolve()
    if not root.is_dir():
        return

    skip = {"public", "templates", "scss", "locales", "icons"}
    reloaded = 0

    # Clear existing routes (they'll be re-registered on reload)
    _routes.clear()

    for py_file in sorted(root.rglob("*.py")):
        if any(part.startswith("_") for part in py_file.parts):
            continue
        if any(s in py_file.parts for s in skip):
            continue

        try:
            rel = py_file.relative_to(Path.cwd()).with_suffix("")
            module_name = ".".join(rel.parts)

            if module_name in sys.modules:
                # Reload existing module
                importlib.reload(sys.modules[module_name])
                reloaded += 1
            else:
                # Import new module
                importlib.import_module(module_name)
                reloaded += 1
        except Exception as e:
            Log.error(f"DevReload: failed to reload {py_file}: {e}")

    # Re-register built-in routes (health check)
    from tina4_python.core.server import _health_handler
    Router.add("GET", "/health", _health_handler)

    after = len(_routes)
    Log.debug(f"DevReload: reloaded {reloaded} modules, {before} -> {after} routes")


def _poll_loop(directories: list[str], interval: float = 1.0):
    """Background thread that polls file mtimes and triggers re-discovery."""
    global _last_mtime, _last_change_file, _running

    # Initial scan
    with _lock:
        _last_mtime, _last_change_file = _scan_mtime(directories)

    Log.debug(f"DevReload: watching {', '.join(directories)} "
              f"(extensions: {', '.join(sorted(_WATCH_EXTENSIONS))})")

    while _running:
        time.sleep(interval)

        new_mtime, new_file = _scan_mtime(directories)

        if new_mtime > _last_mtime:
            rel_path = new_file
            try:
                rel_path = str(Path(new_file).relative_to(Path.cwd()))
            except ValueError:
                pass

            Log.info(f"DevReload: change detected in {rel_path}")

            with _lock:
                _last_mtime = new_mtime
                _last_change_file = new_file

            # Re-discover routes if a Python file changed
            if new_file.endswith(".py"):
                try:
                    _rediscover_routes()
                except Exception as e:
                    Log.error(f"DevReload: route re-discovery failed: {e}")

            # Note: SCSS compilation is handled by the Rust CLI watcher.
            # DevReload only handles route re-discovery and browser refresh.


def start(directories: list[str] | None = None, interval: float | None = None):
    """Start the DevReload file watcher in a background thread.

    Args:
        directories: List of directories to watch. Defaults to ["src", "public"].
        interval: Polling interval in seconds. Defaults to TINA4_DEV_POLL_INTERVAL/1000
                  env var (milliseconds), or 3.0 seconds if not set.
    """
    global _running

    if _running:
        return

    if directories is None:
        directories = ["src", "public"]

    if interval is None:
        env_ms = os.environ.get("TINA4_DEV_POLL_INTERVAL", "3000")
        try:
            interval = max(0.5, int(env_ms) / 1000.0)
        except ValueError:
            interval = 3.0

    _running = True

    thread = threading.Thread(
        target=_poll_loop,
        args=(directories, interval),
        daemon=True,
        name="tina4-dev-reload",
    )
    thread.start()
    Log.info(f"DevReload: file watcher started (interval={interval:.1f}s)")


def stop():
    """Stop the DevReload file watcher."""
    global _running
    _running = False
    Log.debug("DevReload: file watcher stopped")
