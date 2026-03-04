#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""Developer experience: live-reload and error overlay for Tina4.

This module provides zero-config browser auto-refresh and a rich error
overlay for development mode. It is activated only when
``TINA4_DEBUG_LEVEL`` is set to ``ALL`` or ``DEBUG``.

Features:
    - Unified file watcher for ``.py``, ``.twig``, ``.html``, ``.scss``,
      ``.sass``, ``.js``, and ``.css`` files under ``src/``.
    - WebSocket-based live-reload via ``/__dev_reload`` endpoint.
    - CSS-only reload for SCSS changes (no full page refresh).
    - Automatic SCSS compilation on ``.scss`` / ``.sass`` changes.
    - Debounced notifications (100 ms) to avoid rapid-fire reloads.
    - Rich error overlay with syntax-highlighted Python tracebacks.

The live-reload uses the ``ReconnectingWebSocket`` library already
bundled in ``public/js/reconnecting-websocket.js``.
"""

__all__ = [
    "DevFileWatcher",
    "livereload_websocket_handler",
    "inject_dev_scripts",
    "start_watcher",
]

import asyncio
import json
import os
import threading
import time
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler, FileSystemEvent

from tina4_python.Debug import Debug

# Global set of asyncio.Queue objects — one per connected browser tab
_clients: set = set()
_clients_lock = threading.Lock()

# Reference to the asyncio event loop (set when the first WebSocket connects)
_event_loop = None

# Debounce timer
_debounce_timer = None
_debounce_lock = threading.Lock()


def _notify_clients(change_type: str):
    """Send a change notification to all connected browser clients.

    Called from a watchdog thread, so we must use ``call_soon_threadsafe``
    to schedule the ``put_nowait`` on the asyncio event loop.

    Args:
        change_type: Either ``"reload"`` (full page) or ``"css-reload"``
            (stylesheet-only refresh).
    """
    msg = json.dumps({"type": change_type})
    with _clients_lock:
        loop = _event_loop
        for queue in list(_clients):
            try:
                if loop is not None and loop.is_running():
                    loop.call_soon_threadsafe(queue.put_nowait, msg)
                else:
                    queue.put_nowait(msg)
            except Exception:
                pass


def _debounced_notify(change_type: str, delay: float = 0.1):
    """Debounce rapid file changes into a single notification.

    Multiple changes within *delay* seconds are collapsed into one
    notification, preventing rapid-fire browser reloads when editors
    write multiple files at once (e.g. auto-save, format-on-save).

    Args:
        change_type: ``"reload"`` or ``"css-reload"``.
        delay: Debounce window in seconds (default 100 ms).
    """
    global _debounce_timer
    with _debounce_lock:
        if _debounce_timer is not None:
            _debounce_timer.cancel()
        _debounce_timer = threading.Timer(delay, _notify_clients, args=[change_type])
        _debounce_timer.daemon = True
        _debounce_timer.start()


class DevFileWatcher(PatternMatchingEventHandler):
    """Watchdog handler that triggers live-reload on file changes.

    Watches ``src/`` for relevant file types and dispatches change
    notifications to connected browsers via WebSocket.  SCSS changes
    also trigger recompilation before notifying.
    """

    def __init__(self, compile_scss_fn=None):
        super().__init__(
            patterns=["*.py", "*.twig", "*.html", "*.scss", "*.sass", "*.js", "*.css"],
            ignore_directories=True,
            case_sensitive=False,
        )
        self._compile_scss = compile_scss_fn

    def on_modified(self, event: FileSystemEvent):
        self._handle(event)

    def on_created(self, event: FileSystemEvent):
        self._handle(event)

    def _handle(self, event: FileSystemEvent):
        path = event.src_path
        filename = os.path.basename(path)

        # Ignore editor temp files
        if filename.startswith(".") or filename.endswith("~") or filename.endswith(".swp"):
            return

        ext = os.path.splitext(path)[1].lower()
        Debug.debug(f"[DevReload] File changed: {path}")

        if ext in (".scss", ".sass"):
            if self._compile_scss:
                try:
                    self._compile_scss()
                except Exception as e:
                    Debug.error(f"[DevReload] SCSS compile error: {e}")
            _debounced_notify("css-reload")
        else:
            _debounced_notify("reload")


async def livereload_websocket_handler(scope, receive, send):
    """Raw ASGI WebSocket handler for the ``/__dev_reload`` endpoint.

    Accepts a WebSocket connection, registers a message queue, and
    forwards file-change notifications from the watcher to the browser.
    The handler runs until the client disconnects.

    Args:
        scope: ASGI connection scope dict.
        receive: ASGI receive callable.
        send: ASGI send callable.
    """
    global _event_loop

    # Accept the WebSocket handshake
    await send({"type": "websocket.accept"})

    # Capture the running event loop so watchdog threads can schedule on it
    _event_loop = asyncio.get_running_loop()

    queue = asyncio.Queue()
    with _clients_lock:
        _clients.add(queue)

    try:
        while True:
            # Wait for either a file change notification or a client message
            receive_task = asyncio.ensure_future(receive())
            queue_task = asyncio.ensure_future(queue.get())

            done, pending = await asyncio.wait(
                {receive_task, queue_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()

            for task in done:
                if task is receive_task:
                    result = task.result()
                    if result.get("type") == "websocket.disconnect":
                        return
                elif task is queue_task:
                    msg = task.result()
                    try:
                        await send({
                            "type": "websocket.send",
                            "text": msg,
                        })
                    except Exception:
                        return
    except asyncio.CancelledError:
        pass  # Server shutting down — exit cleanly
    except Exception:
        pass
    finally:
        with _clients_lock:
            _clients.discard(queue)


def get_livereload_script():
    """Return the inline ``<script>`` tag for live-reload.

    Uses the bundled ``ReconnectingWebSocket`` to maintain a persistent
    connection to ``/__dev_reload``.  On ``"reload"`` messages the page
    reloads; on ``"css-reload"`` messages only stylesheets are refreshed.

    Returns:
        str: An HTML ``<script>`` block ready to inject before ``</body>``.
    """
    return """
<script>
(function() {
    // Determine WebSocket URL from current page location
    var proto = (location.protocol === 'https:') ? 'wss://' : 'ws://';
    var wsUrl = proto + location.host + '/__dev_reload';
    var ws;

    // Try ReconnectingWebSocket first, fall back to native WebSocket
    if (typeof ReconnectingWebSocket !== 'undefined') {
        ws = new ReconnectingWebSocket(wsUrl);
    } else {
        ws = new WebSocket(wsUrl);
    }

    // Toast notification element
    var toast = document.createElement('div');
    toast.id = 'tina4-dev-toast';
    toast.style.cssText = 'position:fixed;bottom:16px;right:16px;padding:8px 16px;background:#1a1a2e;color:#e94560;font-family:monospace;font-size:13px;border-radius:6px;z-index:999999;opacity:0;transition:opacity 0.3s;pointer-events:none;border:1px solid #e94560;';
    document.body.appendChild(toast);

    function showToast(msg) {
        toast.textContent = msg;
        toast.style.opacity = '1';
        setTimeout(function() { toast.style.opacity = '0'; }, 1500);
    }

    ws.onmessage = function(event) {
        try {
            var data = JSON.parse(event.data);
            if (data.type === 'css-reload') {
                showToast('\\u2728 CSS reloaded');
                // Cache-bust all stylesheets
                var links = document.querySelectorAll('link[rel="stylesheet"]');
                links.forEach(function(link) {
                    var href = link.href.split('?')[0];
                    link.href = href + '?_t=' + Date.now();
                });
            } else if (data.type === 'reload') {
                showToast('\\u27f3 Reloading...');
                setTimeout(function() { location.reload(); }, 100);
            }
        } catch(e) {}
    };

    ws.onopen = function() {
        showToast('\\u26a1 DevReload connected');
    };

    ws.onclose = function() {
        // ReconnectingWebSocket handles reconnection automatically
    };
})();
</script>
"""


def get_error_overlay_assets():
    """Return inline CSS and JS for the rich error overlay.

    The overlay styles the 500 error page with a dark theme, syntax-
    highlighted traceback, dismiss-on-Escape functionality, and
    prominent file/line display.  The raw error text is preserved
    in a hidden ``<div>`` for AI tool consumption.

    Returns:
        str: Combined ``<style>`` and ``<script>`` HTML blocks.
    """
    return """
<style>
#tina4-error-overlay {
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(10, 10, 20, 0.95);
    z-index: 99999;
    display: flex; align-items: center; justify-content: center;
    font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
    padding: 20px;
    overflow: auto;
}
#tina4-error-panel {
    background: #1a1a2e; border: 1px solid #e94560;
    border-radius: 12px; width: 100%; max-width: 900px;
    max-height: 90vh; overflow: auto;
    box-shadow: 0 25px 80px rgba(233, 69, 96, 0.3);
}
.tina4-error-header {
    display: flex; align-items: center; gap: 12px;
    padding: 16px 20px; border-bottom: 1px solid #2a2a4a;
    position: sticky; top: 0; background: #1a1a2e; z-index: 1;
    border-radius: 12px 12px 0 0;
}
.tina4-error-badge {
    background: #e94560; color: #fff; padding: 4px 10px;
    border-radius: 4px; font-weight: bold; font-size: 14px;
    flex-shrink: 0;
}
.tina4-error-header h2 {
    margin: 0; color: #e94560; font-size: 16px; font-weight: 600;
    flex: 1;
}
.tina4-error-url {
    color: #888; font-size: 13px; flex-shrink: 0;
}
.tina4-error-close {
    background: none; border: 1px solid #444; color: #888;
    width: 32px; height: 32px; border-radius: 6px; cursor: pointer;
    font-size: 18px; display: flex; align-items: center; justify-content: center;
    transition: all 0.2s; flex-shrink: 0;
}
.tina4-error-close:hover { border-color: #e94560; color: #e94560; }
.tina4-error-trace {
    margin: 0; padding: 20px; font-size: 13px; line-height: 1.6;
    color: #ccc; white-space: pre-wrap; word-break: break-word;
    overflow-x: auto;
}
/* Syntax highlighting for Python tracebacks */
.tina4-tb-file { color: #6ec6ff; }
.tina4-tb-lineno { color: #ffd93d; }
.tina4-tb-func { color: #c084fc; }
.tina4-tb-error { color: #e94560; font-weight: bold; }
.tina4-tb-code { color: #a8d8a8; }
.tina4-error-hint {
    padding: 12px 20px; border-top: 1px solid #2a2a4a;
    color: #666; font-size: 12px; text-align: center;
}
</style>
<script>
(function() {
    // Find error text from any source: dedicated div, or any <pre> on the page
    var errorData = document.getElementById('tina4-error-data');
    var existingPre = document.querySelector('pre');
    var errorText = '';
    if (errorData) {
        errorText = errorData.textContent;
    } else if (existingPre) {
        errorText = existingPre.textContent;
    }
    if (!errorText) return;

    // Build the overlay dynamically
    var overlay = document.createElement('div');
    overlay.id = 'tina4-error-overlay';

    var panel = document.createElement('div');
    panel.id = 'tina4-error-panel';

    // Header
    var header = document.createElement('div');
    header.className = 'tina4-error-header';
    header.innerHTML = '<span class="tina4-error-badge">500</span>'
        + '<h2>Runtime Error</h2>'
        + '<span class="tina4-error-url">' + location.pathname + '</span>'
        + '<button class="tina4-error-close" title="Dismiss (Esc)">&times;</button>';
    panel.appendChild(header);

    // Traceback
    var trace = document.createElement('pre');
    trace.className = 'tina4-error-trace';
    trace.textContent = errorText;

    // Syntax highlight the traceback
    var html = trace.innerHTML;
    html = html.replace(
        /File &quot;([^&]+)&quot;, line (\\d+), in (\\S+)/g,
        'File "<span class="tina4-tb-file">$1</span>", line <span class="tina4-tb-lineno">$2</span>, in <span class="tina4-tb-func">$3</span>'
    );
    html = html.replace(
        /^(\\w+(?:Error|Exception|Warning)[^\\n]*)/gm,
        '<span class="tina4-tb-error">$1</span>'
    );
    trace.innerHTML = html;
    panel.appendChild(trace);

    // Hint
    var hint = document.createElement('div');
    hint.className = 'tina4-error-hint';
    hint.innerHTML = 'Press <kbd>Esc</kbd> to dismiss &middot; Fix the error and save to auto-reload';
    panel.appendChild(hint);

    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    // Dismiss handlers
    function dismiss() { overlay.style.display = 'none'; }
    header.querySelector('.tina4-error-close').addEventListener('click', dismiss);
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') dismiss();
    });
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) dismiss();
    });
})();
</script>
"""


def inject_dev_scripts(html_content):
    """Inject live-reload and overlay scripts into an HTML response.

    Inserts the live-reload ``<script>`` tag just before the closing
    ``</body>`` tag.  If no ``</body>`` is found, appends to the end.

    Args:
        html_content: The rendered HTML string.

    Returns:
        str: The HTML with dev scripts injected.
    """
    scripts = get_livereload_script()
    closing = "</body>"
    lower = html_content.lower()
    idx = lower.rfind(closing)
    if idx != -1:
        return html_content[:idx] + scripts + html_content[idx:]
    return html_content + scripts


def start_watcher(root_path, compile_scss_fn=None):
    """Start the unified file watcher for development mode.

    Creates a ``DevFileWatcher`` that monitors the ``src/`` directory
    for changes to Python, template, SCSS, and static files.

    Args:
        root_path: The project root directory.
        compile_scss_fn: Optional callable to compile SCSS files.
            If provided, called on ``.scss`` / ``.sass`` changes.

    Returns:
        Observer: The running watchdog Observer instance.
    """
    src_path = os.path.join(root_path, "src")
    if not os.path.exists(src_path):
        Debug.warning("[DevReload] No src/ directory found — watcher not started")
        return None

    observer = Observer()
    handler = DevFileWatcher(compile_scss_fn=compile_scss_fn)
    observer.schedule(handler, path=src_path, recursive=True)
    observer.daemon = True
    observer.start()
    Debug.info("[DevReload] Watching src/ for changes (live-reload enabled)")
    return observer
