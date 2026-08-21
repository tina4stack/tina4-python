# Tina4 Dev Admin — Built-in development dashboard, zero dependencies.
"""
Auto-registered admin panel for development mode (TINA4_DEBUG=true).
Provides API endpoints and a single-page UI at /__dev/ for:

    - Route inspector (all registered routes, methods, auth)
    - Queue viewer (pending, completed, failed jobs)
    - Dev mailbox (captured outbound emails + seeded inbox)
    - Message log (tracked debug messages)
    - System info (Python version, env, loaded modules)

Uses tina4-js (frond.js) for reactive UI — zero external dependencies.
"""
import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from tina4_python import __version__
# THE redaction primitive. A connection URL in a response body is a credential
# leak exactly like one in a log line: /__dev/api/status and the system-info
# endpoint both used to hand back TINA4_DATABASE_URL verbatim, password and all.
from tina4_python.database.database_url import redact_url


# ── Dev-admin mutation security (feature 127, DEVADMIN-DEC-01/02/03) ──────────
# The dashboard can write files, run SQL and install packages, so it must assume
# the developer ALSO browses the web. Two fail-closed gates guard every /__dev
# write, and a secret denylist guards the file-read surface.

_DEV_SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
#: The MCP surface carries its own richer loopback+token+remote gate
#: (_mcp_request_allowed → 404), so the REST loopback gate skips these prefixes
#: and lets the MCP gate govern (keeps the mcp/call refusal a 404, not a 403).
_DEV_MCP_PREFIXES = ("/__dev/api/mcp", "/__dev/mcp")
#: Private-key / credential basenames the file endpoints must never serve.
_DEV_SECRET_BASENAMES = frozenset({
    ".env", ".envrc", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
})
_DEV_SECRET_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".keystore", ".jks")


def _dev_same_origin_ok(request) -> bool:
    """Fail-closed same-origin check for a dev-admin mutation (DEVADMIN-DEC-01).

    A drive-by CSRF is a BROWSER cross-origin request, and a modern browser
    always sends ``Sec-Fetch-Site`` (and any browser sends ``Origin`` on a
    cross-origin POST), so:

    - ``Sec-Fetch-Site`` present -> trust the browser's own classification
      (``cross-site`` is refused; ``same-origin`` / ``same-site`` / ``none`` ok).
    - else ``Origin`` present -> require it to match the request Host.
    - else neither header -> not a browser cross-origin request at all (curl, a
      test client, a server-side caller); it cannot be a drive-by, so it is
      allowed here and the loopback gate still constrains the peer.
    """
    headers = getattr(request, "headers", None) or {}
    sec_fetch_site = (headers.get("sec-fetch-site") or "").strip().lower()
    if sec_fetch_site:
        return sec_fetch_site in ("same-origin", "same-site", "none")
    origin = (headers.get("origin") or "").strip()
    if origin:
        netloc = origin.split("://", 1)[1] if "://" in origin else origin
        host = (headers.get("host") or "").strip()
        return bool(host) and netloc.lower() == host.lower()
    return True


def _dev_mutation_denial(request):
    """Return ``(status, error)`` to REFUSE a dev-admin write, or ``None`` to allow.

    Two independent fail-closed gates on every /__dev mutation:
      DEVADMIN-DEC-01  same-origin (all writes, incl. mcp/call) - drive-by CSRF.
      DEVADMIN-DEC-02  loopback peer (all writes EXCEPT the MCP surface, which
                       carries its own gate) - a network-exposed debug box.
    """
    if not _dev_same_origin_ok(request):
        return (403, "dev-admin: refused (cross-origin request)")
    path = getattr(request, "path", "") or ""
    if not path.startswith(_DEV_MCP_PREFIXES):
        from tina4_python.mcp import is_loopback
        remote_ip = getattr(request, "remote_ip", "") or ""
        if not (is_loopback(remote_ip) or _mcp_token_ok(request)):
            return (403, "dev-admin: refused (non-loopback peer)")
    return None


def _is_secret_path(rel: str) -> bool:
    """True when ``rel`` names secret material the file endpoints must never
    serve (DEVADMIN-DEC-03): ``.env`` / ``.env.*`` (the ``.env.example`` template
    is allowed), anything under ``.git/`` or ``secrets/``, and private keys."""
    norm = (rel or "").replace("\\", "/").strip("/").lower()
    if not norm:
        return False
    parts = norm.split("/")
    if any(p in (".git", "secrets") for p in parts):
        return True
    base = parts[-1]
    if base == ".env.example":
        return False
    if base == ".env" or base.startswith(".env."):
        return True
    if base in _DEV_SECRET_BASENAMES:
        return True
    return base.endswith(_DEV_SECRET_SUFFIXES)


class MessageLog:
    """In-memory message log for dev mode tracking.

    Captures structured messages from anywhere in the application,
    viewable in the dev admin dashboard.
    """

    _messages: list[dict] = []
    _max_messages: int = 500

    @classmethod
    def log(cls, category: str, message: str, data: dict = None,
            level: str = "info"):
        """Log a message to the dev admin message tracker.

        Args:
            category: Category (e.g., "queue", "email", "auth", "route")
            message: Human-readable message
            data: Optional structured data
            level: "info", "warn", "error", "debug"
        """
        entry = {
            "id": f"{int(time.time() * 1000)}_{len(cls._messages)}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category": category,
            "level": level,
            "message": message,
            "data": data,
        }
        cls._messages.append(entry)

        # Trim old messages
        if len(cls._messages) > cls._max_messages:
            cls._messages = cls._messages[-cls._max_messages:]

    @classmethod
    def get(cls, category: str = None, level: str = None,
            limit: int = 100, offset: int = 0) -> list[dict]:
        """Get logged messages with optional filtering."""
        msgs = cls._messages
        if category:
            msgs = [m for m in msgs if m["category"] == category]
        if level:
            msgs = [m for m in msgs if m["level"] == level]
        # Newest first
        msgs = list(reversed(msgs))
        return msgs[offset:offset + limit]

    @classmethod
    def clear(cls, category: str = None):
        """Clear messages."""
        if category:
            cls._messages = [m for m in cls._messages if m["category"] != category]
        else:
            cls._messages = []

    @classmethod
    def count(cls) -> dict:
        """Get message counts by category."""
        counts = {}
        for m in cls._messages:
            cat = m["category"]
            counts[cat] = counts.get(cat, 0) + 1
        counts["total"] = len(cls._messages)
        return counts


class RequestInspector:
    """Captures recent HTTP requests for the dev admin inspector."""

    _requests: list[dict] = []
    _max_requests: int = 200

    @classmethod
    def capture(cls, method: str, path: str, status: int, duration_ms: float,
                headers: dict = None, body_size: int = 0, ip: str = ""):
        """Record a request."""
        entry = {
            "id": f"{int(time.time() * 1000)}_{len(cls._requests)}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": method,
            "path": path,
            "status": status,
            "duration_ms": round(duration_ms, 2),
            "headers": headers or {},
            "body_size": body_size,
            "ip": ip,
        }
        cls._requests.append(entry)
        if len(cls._requests) > cls._max_requests:
            cls._requests = cls._requests[-cls._max_requests:]

    @classmethod
    def get(cls, limit: int = 50, method: str = None, status_min: int = None) -> list[dict]:
        """Get captured requests, newest first."""
        reqs = cls._requests
        if method:
            reqs = [r for r in reqs if r["method"] == method.upper()]
        if status_min:
            reqs = [r for r in reqs if r["status"] >= status_min]
        return list(reversed(reqs))[:limit]

    @classmethod
    def clear(cls):
        cls._requests = []

    @classmethod
    def stats(cls) -> dict:
        """Request statistics."""
        if not cls._requests:
            return {"total": 0, "avg_ms": 0, "errors": 0}
        durations = [r["duration_ms"] for r in cls._requests]
        errors = sum(1 for r in cls._requests if r["status"] >= 400)
        return {
            "total": len(cls._requests),
            "avg_ms": round(sum(durations) / len(durations), 2),
            "errors": errors,
            "slowest_ms": round(max(durations), 2),
        }


class BrokenTracker:
    """Tracks production errors via .broken files."""

    _broken_dir = "data/broken"

    @classmethod
    def record(cls, error_type: str, message: str, traceback_str: str = "",
               context: dict = None):
        """Record an error."""
        Path(cls._broken_dir).mkdir(parents=True, exist_ok=True)
        # Dedup by error signature
        sig = f"{error_type}:{message[:100]}"
        import hashlib
        sig_hash = hashlib.md5(sig.encode()).hexdigest()[:12]
        filepath = Path(cls._broken_dir) / f"{sig_hash}.json"

        if filepath.exists():
            try:
                existing = json.loads(filepath.read_text(encoding="utf-8"))
                existing["count"] = existing.get("count", 1) + 1
                existing["last_seen"] = datetime.now(timezone.utc).isoformat()
                filepath.write_text(json.dumps(existing, indent=2), encoding="utf-8")
                return sig_hash
            except (json.JSONDecodeError, OSError):
                pass

        entry = {
            "id": sig_hash,
            "error_type": error_type,
            "message": message,
            "traceback": traceback_str,
            "context": context or {},
            "count": 1,
            "first_seen": datetime.now(timezone.utc).isoformat(),
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "resolved": False,
        }
        filepath.write_text(json.dumps(entry, indent=2), encoding="utf-8")
        return sig_hash

    @classmethod
    def get_all(cls) -> list[dict]:
        """Get all broken entries."""
        broken_dir = Path(cls._broken_dir)
        if not broken_dir.exists():
            return []
        entries = []
        for f in sorted(broken_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                entries.append(json.loads(f.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        return entries

    @classmethod
    def resolve(cls, error_id: str) -> bool:
        """Mark an error as resolved."""
        filepath = Path(cls._broken_dir) / f"{error_id}.json"
        if not filepath.exists():
            return False
        try:
            entry = json.loads(filepath.read_text(encoding="utf-8"))
            entry["resolved"] = True
            filepath.write_text(json.dumps(entry, indent=2), encoding="utf-8")
            return True
        except (json.JSONDecodeError, OSError):
            return False

    @classmethod
    def clear_resolved(cls):
        """Remove all resolved .broken files."""
        broken_dir = Path(cls._broken_dir)
        if not broken_dir.exists():
            return
        for f in broken_dir.glob("*.json"):
            try:
                entry = json.loads(f.read_text(encoding="utf-8"))
                if entry.get("resolved"):
                    f.unlink()
            except (json.JSONDecodeError, OSError):
                continue

    @classmethod
    def health(cls) -> dict:
        """Health check — are there unresolved errors?"""
        entries = cls.get_all()
        unresolved = [e for e in entries if not e.get("resolved")]
        return {
            "healthy": len(unresolved) == 0,
            "total": len(entries),
            "unresolved": len(unresolved),
            "resolved": len(entries) - len(unresolved),
        }

    @classmethod
    def unresolved_count(cls) -> int:
        """Count of unresolved errors."""
        entries = cls.get_all()
        return sum(1 for e in entries if not e.get("resolved"))

    @classmethod
    def clear_all(cls):
        """Remove ALL broken files."""
        broken_dir = Path(cls._broken_dir)
        if not broken_dir.exists():
            return
        for f in broken_dir.glob("*.json"):
            try:
                f.unlink()
            except OSError:
                continue

    @classmethod
    def reset(cls):
        """Reset all state (for testing). Alias for clear_all."""
        cls.clear_all()

    @classmethod
    def capture(cls, error_type: str, message: str, traceback_str: str = "",
                file: str = "", line: int = 0):
        """Capture an error (parity alias for record).

        Accepts the same 5-param signature as PHP/Ruby ErrorTracker.capture.
        The file and line params are stored in context.
        """
        context = {}
        if file:
            context["file"] = file
        if line:
            context["line"] = line
        return cls.record(error_type, message, traceback_str, context)


def register():
    """Register dev admin routes on the router.

    Parity method matching PHP DevAdmin::register() and Node DevAdmin.register().
    In Python, routes are registered via get_api_handlers() called from the server;
    this function provides an explicit entry point for the same operation.
    """
    from tina4_python.core.router import Router
    handlers = get_api_handlers()
    for path, (method, handler) in handlers.items():
        if method == "GET":
            Router.get(path, handler)
        else:
            Router.post(path, handler)
    # Auto-discovery: drop `.tina4/mcp.json` so MCP-aware AI tools
    # (Claude Code, Cursor, etc.) discover the local Live Docs +
    # MCP server without the user authoring config. Idempotent.
    write_mcp_discovery_file()


def write_mcp_discovery_file() -> None:
    """Drop `.tina4/mcp.json` and append `.tina4/` to `.gitignore`.

    Both are idempotent — running twice is a no-op when the state is
    already correct. Skipped silently outside debug mode and on
    filesystem errors (read-only project dir, etc.) — discovery is
    a convenience, not a requirement.

    See plan/v3/22-LIVE-API-RAG.md §"Auto-discovery file" for the
    JSON shape.
    """
    import json
    import os

    is_dev = os.environ.get("TINA4_DEBUG", "false").lower() in ("1", "true", "yes")
    if not is_dev:
        return
    root = os.getcwd()
    tina4_dir = os.path.join(root, ".tina4")
    mcp_file = os.path.join(tina4_dir, "mcp.json")
    port = (os.environ.get("TINA4_PORT")
            or os.environ.get("PORT")
            or "7146")
    expected = {
        "mcpServers": {
            "tina4-live-docs": {
                "type": "http",
                "url": f"http://localhost:{port}/__dev/mcp",
                "description": "Live API docs + dev tools for this Tina4 project (framework + user code)",
            }
        }
    }
    expected_json = json.dumps(expected, indent=2) + "\n"

    try:
        if os.path.isfile(mcp_file):
            with open(mcp_file, "r", encoding="utf-8") as f:
                existing = f.read()
            if existing.strip() == expected_json.strip():
                _ensure_gitignore(root)
                return
        os.makedirs(tina4_dir, exist_ok=True)
        with open(mcp_file, "w", encoding="utf-8") as f:
            f.write(expected_json)
        _ensure_gitignore(root)
    except OSError:
        # Read-only fs, permission denied, etc. Silently skip —
        # discovery is convenience.
        return


def _ensure_gitignore(root: str) -> None:
    """Append `.tina4/` to `.gitignore` if not already excluded.

    Tolerates leading slashes, trailing slashes, and existing comment
    lines so we never duplicate. Only touches `.gitignore` if `.git/`
    exists (don't pollute non-git projects).
    """
    import os

    if not os.path.isdir(os.path.join(root, ".git")):
        return
    gi_path = os.path.join(root, ".gitignore")
    existing = ""
    if os.path.isfile(gi_path):
        try:
            with open(gi_path, "r", encoding="utf-8") as f:
                existing = f.read()
        except OSError:
            return
    for raw in existing.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        normal = line.strip("/").strip()
        if normal == ".tina4":
            return  # already excluded
    suffix = "" if existing.endswith("\n") or existing == "" else "\n"
    try:
        with open(gi_path, "a", encoding="utf-8") as f:
            f.write(suffix + ".tina4/\n")
    except OSError:
        pass


def get_api_handlers() -> dict:
    """Return dev admin API handler functions keyed by path.

    These are registered as routes when the server starts in dev mode.
    Returns dict of {path: (method, handler)} tuples.
    """
    return {
        "/__dev/api/status": ("GET", _api_status),
        "/__dev/api/routes": ("GET", _api_routes),
        "/__dev/api/queue": ("GET", _api_queue),
        "/__dev/api/queue/topics": ("GET", _api_queue_topics),
        "/__dev/api/queue/retry": ("POST", _api_queue_retry),
        "/__dev/api/queue/purge": ("POST", _api_queue_purge),
        "/__dev/api/queue/replay": ("POST", _api_queue_replay_job),
        "/__dev/api/queue/dead-letters": ("GET", _api_queue_dead_letters),
        "/__dev/api/mailbox": ("GET", _api_mailbox),
        "/__dev/api/mailbox/read": ("GET", _api_mailbox_read),
        "/__dev/api/mailbox/seed": ("POST", _api_mailbox_seed),
        "/__dev/api/mailbox/clear": ("POST", _api_mailbox_clear),
        "/__dev/api/messages": ("GET", _api_messages),
        "/__dev/api/messages/search": ("GET", _api_messages_search),
        "/__dev/api/messages/clear": ("POST", _api_messages_clear),
        "/__dev/api/query": ("POST", _api_query),
        "/__dev/api/tables": ("GET", _api_tables),
        "/__dev/api/table": ("GET", _api_table_info),
        "/__dev/api/seed": ("POST", _api_seed_table),
        "/__dev/api/requests": ("GET", _api_requests),
        "/__dev/api/requests/clear": ("POST", _api_requests_clear),
        "/__dev/api/broken": ("GET", _api_broken),
        "/__dev/api/broken/resolve": ("POST", _api_broken_resolve),
        "/__dev/api/broken/clear": ("POST", _api_broken_clear),
        "/__dev/api/websockets": ("GET", _api_websockets),
        "/__dev/api/websockets/disconnect": ("POST", _api_ws_disconnect),
        "/__dev/api/system": ("GET", _api_system),
        "/__dev/api/chat": ("POST", _api_chat),
        # Thread CRUD — exact match handles GET (list) + POST (create);
        # the "/*" key is the prefix-fallback for /threads/{id}[/messages]
        # which the dev_admin dispatcher routes to _api_threads_sub.
        # "*" method = handler switches on request.method itself.
        "/__dev/api/threads":   ("*", _api_threads),
        "/__dev/api/threads/*": ("*", _api_threads_sub),
        # ── Customer feedback widget (Tier 1: intake-only) ──
        # /__feedback/widget.js — bundle served at top-level so HTML
        # pages can embed without a /__dev path (the widget is for
        # whitelisted END USERS of the app, not developers).
        # /__feedback/api/turn — one conversational turn; routes
        # whitelist + rate-limit + sender-stamping then forwards
        # to the Rust agent /feedback/intake.
        "/__feedback/widget.js": ("GET",  _api_feedback_widget_js),
        "/__feedback/api/turn":  ("POST", _api_feedback_turn),
        # Transparent pass-through proxy to the qwen ollama endpoint —
        # accepts the ollama-native `{model, messages, stream, options}`
        # body and forwards to TINA4_AI_URL unchanged. The SPA uses this
        # for FIM completion and supervisor chat. Distinct from
        # /__dev/api/chat, which is the dev-admin Q&A wrapper that
        # takes `{message: "..."}`.
        "/ai/api/chat": ("POST", _api_ai_proxy),
        # Service health probes — the SPA fires these on load to paint
        # the "SERVICES ●●●●●" row. Any 2xx response = green dot.
        "/ai":     ("GET", _api_service_ai),
        "/vision": ("GET", _api_service_vision),
        "/embed":  ("GET", _api_service_embed),
        "/image":  ("GET", _api_service_image),
        "/rag":    ("GET", _api_service_rag),
        # Thoughts — proxied to the rust agent server when it's running.
        "/__dev/api/thoughts": ("GET", _api_thoughts),
        # Supervisor orchestration — transparent proxy to the rust
        # agent server (port = framework port + 2000). When tina4
        # serve isn't running these respond 503 with a helpful hint
        # instead of failing silently.
        "/__dev/api/supervise/create":   ("POST", _api_supervise_create),
        "/__dev/api/supervise/sessions": ("GET",  _api_supervise_sessions),
        "/__dev/api/supervise/diff":     ("GET",  _api_supervise_diff),
        "/__dev/api/supervise/commit":   ("POST", _api_supervise_commit),
        "/__dev/api/supervise/cancel":   ("POST", _api_supervise_cancel),
        "/__dev/api/execute":            ("POST", _api_execute),
        "/__dev/api/tool": ("POST", _api_tool),
        "/__dev/api/connections": ("GET", _api_connections),
        "/__dev/api/connections/test": ("POST", _api_connections_test),
        "/__dev/api/connections/save": ("POST", _api_connections_save),
        "/__dev/api/gallery": ("GET", _api_gallery_list),
        "/__dev/api/gallery/deploy": ("POST", _api_gallery_deploy),
        # Dev-toolbar assets — external CSS/JS so the injected toolbar is
        # CSP-clean (no inline styles, handlers, or <script>) and works under
        # a strict `default-src 'self'` (SecurityHeadersMiddleware). #115.
        "/__dev/toolbar.css": ("GET", _api_toolbar_css),
        "/__dev/toolbar.js": ("GET", _api_toolbar_js),
        "/__dev/api/mtime": ("GET", _api_mtime),
        "/__dev/api/reload": ("POST", _api_reload),
        "/__dev/api/version-check": ("GET", _api_version_check),
        "/__dev/api/metrics/full": ("GET", _api_metrics_full),
        "/__dev/api/metrics/file": ("GET", _api_metrics_file),
        "/__dev/api/graphql/schema": ("GET", _api_graphql_schema),
        # ── Editor endpoints ──
        "/__dev/api/files": ("GET", _api_files),
        "/__dev/api/file": ("GET", _api_file_read),
        "/__dev/api/file/save": ("POST", _api_file_save),
        "/__dev/api/file/raw": ("GET", _api_file_raw),
        "/__dev/api/file/rename": ("POST", _api_file_rename),
        "/__dev/api/file/delete": ("POST", _api_file_delete),
        "/__dev/api/deps/search": ("GET", _api_deps_search),
        "/__dev/api/deps/install": ("POST", _api_deps_install),
        "/__dev/api/git/status": ("GET", _api_git_status),
        # ── MCP REST shim ──
        # Dev-admin speaks a REST flavour of MCP (plain GET/POST with
        # JSON bodies) rather than the JSON-RPC SSE protocol used by
        # Claude Desktop et al. Both surfaces share the same
        # `_default_server` tool registry, so tools registered via the
        # @mcp_tool decorator appear in both immediately.
        "/__dev/api/mcp/tools": ("GET", _api_mcp_tools),
        "/__dev/api/mcp/call": ("POST", _api_mcp_call),
        # MCP transport surface for real clients (Claude Code / Desktop).
        # Same registry as the REST shim above. /__dev/mcp is the Streamable
        # HTTP endpoint (POST message + DELETE session; "*" so one handler
        # switches on the method); /message + /sse are the legacy HTTP+SSE
        # transport, kept working for older SSE-only clients.
        "/__dev/mcp": ("*", _api_mcp_endpoint),
        "/__dev/mcp/message": ("POST", _api_mcp_message),
        "/__dev/mcp/sse": ("GET", _api_mcp_sse),
        # ── Scaffold REST shim ──
        # Wraps the tina4python CLI's `generate <kind> <name>` so the
        # + Route / + Model / + Migration / + Middleware buttons work
        # without shelling out from the browser.
        "/__dev/api/scaffold": ("GET", _api_scaffold_list),
        "/__dev/api/scaffold/run": ("POST", _api_scaffold_run),
        # ── Run-chip endpoints (project-level operations) ──
        # The dev-admin SPA's ▶ Migrate / ▶ Test / ▶ Seed chips call
        # these. Each runs the whole-project operation via the framework's
        # own machinery (matching the CLI), NOT by shelling out redundantly.
        # /seed/run is distinct from /seed above (which seeds one named
        # table); /run seeds every discovered ORM model.
        "/__dev/api/migrate": ("POST", _api_migrate),
        "/__dev/api/test": ("POST", _api_test),
        "/__dev/api/seed/run": ("POST", _api_seed_run),
        # ── Framework-grounding (mcp.tina4.com) token config ──
        # Self-contained in Python (writes/reads the project .env
        # directly) — does NOT depend on the Rust agent being up, unlike
        # the Node dev-admin which proxies these to /mcp/status + /mcp/token.
        "/__dev/api/grounding/status": ("GET", _api_grounding_status),
        "/__dev/api/grounding/token": ("POST", _api_grounding_token),
        # ── Live Docs (per plan/v3/22-LIVE-API-RAG.md) ──
        # Thin HTTP wrappers around tina4_python.docs.Docs. Both
        # framework public API and the user's src/ surface are
        # returned, tagged with `source = framework | user`. AI tools
        # (Claude Code, Cursor, dev-admin chat) hit these for ground-
        # truth introspection instead of guessing from training data.
        "/__dev/api/docs/search": ("GET", _api_docs_search),
        "/__dev/api/docs/class": ("GET", _api_docs_class),
        "/__dev/api/docs/method": ("GET", _api_docs_method),
        "/__dev/api/docs/index": ("GET", _api_docs_index),
        "/__dev/api/docs/.well-known.json": ("GET", _api_docs_well_known),
    }


async def _api_status(request, response):
    """System status overview."""
    import sys
    from tina4_python.messenger import DevMailbox

    mailbox = DevMailbox()
    db_table_count = 0
    try:
        from tina4_python.database import Database
        db = Database()
        if db and db.adapter:
            db_table_count = len(db.get_tables())
    except Exception:
        pass
    # Memory telemetry — best-effort via resource (POSIX) or psutil if present;
    # falls back to 0.0 on Windows with no psutil so the key shape stays stable.
    memory_usage_mb = 0.0
    peak_memory_mb = 0.0
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        # ru_maxrss is KB on Linux, bytes on macOS
        scale = 1024.0 if sys.platform == "darwin" else 1.0
        peak_memory_mb = round(usage.ru_maxrss * scale / 1024.0 / 1024.0, 2)
        memory_usage_mb = peak_memory_mb  # resource has no current-rss field
    except Exception:
        pass
    try:
        import psutil  # optional
        proc = psutil.Process()
        memory_usage_mb = round(proc.memory_info().rss / 1024.0 / 1024.0, 2)
    except Exception:
        pass

    status = {
        "python_version": sys.version,
        "framework": "tina4-python v3",
        "framework_version": __version__,
        "debug": os.environ.get("TINA4_DEBUG", "false"),
        "log_level": os.environ.get("TINA4_LOG_LEVEL", "ERROR"),
        "database": redact_url(os.environ.get("TINA4_DATABASE_URL", "not configured")),
        "db_tables": db_table_count,
        "mailbox": mailbox.count(),
        "messages": MessageLog.count(),
        "requests": RequestInspector.stats(),
        "health": BrokenTracker.health(),
        "memory_usage_mb": memory_usage_mb,
        "peak_memory_mb": peak_memory_mb,
        "uptime_seconds": round(time.time() - _start_time, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return response(status)


async def _api_routes(request, response):
    """List all registered routes."""
    try:
        from tina4_python.core.router import Router
        internal_prefixes = ("/__dev", "/health", "/swagger")
        routes = Router.get_routes()
        result = []
        for r in routes:
            path = r.get("path", "")
            if path.startswith(internal_prefixes):
                continue
            result.append({
                "method": r.get("method", "GET"),
                "path": path,
                "auth_required": r.get("auth_required", False),
                "handler": r["handler"].__name__ if r.get("handler") else "?",
                "module": r["handler"].__module__ if r.get("handler") else "?",
            })
        return response({"routes": result, "count": len(result)})
    except Exception as e:
        return response({"routes": [], "count": 0, "error": str(e)})


def _read_queue_dir(directory: str, status: str = None) -> list:
    """Read every ``*.queue-data`` record in ONE queue directory, oldest name
    first, skipping corrupt files exactly as ``LiteBackend.size()`` skips them —
    so the list and the count always see the same set.

    ``status`` labels the jobs, for the ``failed/`` and ``reserved/`` dirs whose
    every file is counted by ``size()`` regardless of the status string stored
    inside it. Left as None (the queue dir) each job keeps its OWN status, which
    is exactly the field ``size("pending")`` / ``size("completed")`` matches on.
    """
    jobs = []
    try:
        filenames = sorted(os.listdir(directory))
    except OSError:
        return jobs
    for filename in filenames:
        if not filename.endswith(".queue-data"):
            continue  # skips the failed/ + reserved/ subdirectories
        try:
            with open(os.path.join(directory, filename)) as fh:
                job = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue  # skip corrupt files
        job["status"] = status or job.get("status") or "pending"
        jobs.append(job)
    return jobs


async def _api_queue_topics(request, response):
    """List available queue topics by scanning the queue data directory."""
    try:
        from tina4_python.queue import queue_base_path
        queue_dir = queue_base_path()
        if os.path.isdir(queue_dir):
            topics = sorted([d for d in os.listdir(queue_dir) if os.path.isdir(os.path.join(queue_dir, d))])
        else:
            topics = ["default"]
        return response({"topics": topics})
    except Exception as e:
        return response({"topics": ["default"], "error": str(e)})


async def _api_queue(request, response):
    """Queue status and jobs — works with any backend (lite, kafka, mongo, rabbitmq)."""
    try:
        from tina4_python.queue import Queue, queue_base_path
        topic = request.query.get("topic", "default") if hasattr(request, "query") else "default"
        status_filter = request.query.get("status", None) if hasattr(request, "query") else None
        queue = Queue(topic=topic)

        # Stats
        stats = {
            "pending": queue.size("pending"),
            "completed": queue.size("completed"),
            "failed": queue.size("failed"),
            "reserved": queue.size("reserved"),
        }

        # The job list and the stats above MUST describe the same set of jobs.
        # Three defects broke that (see tests/test_dev_admin_queue_path.py):
        #
        #  1. The directory. This scanned a hardcoded cwd/data/queue/<topic>
        #     while Queue.size() reads queue_base_path() — so with
        #     TINA4_QUEUE_PATH set the panel listed one directory and counted
        #     another.
        #  2. The set. Reserved jobs were counted by stats.reserved but never
        #     listed, and a failed-but-retryable job — which lives in the
        #     PENDING directory with status "pending" — was listed twice: once
        #     by the directory scan and again by queue.failed(), which re-reads
        #     the same files.
        #  3. maxRetries. queue.dead_letters() filters on THIS queue's
        #     max_retries, which the dev admin cannot know, so it returned fewer
        #     jobs than size("failed") counts — and returns Job OBJECTS, whose
        #     item assignment raised TypeError and blanked the whole endpoint.
        #
        # Each job now appears exactly once, in the bucket its own stat counts
        # it in: the queue dir under its own status (what size(<status>) matches
        # on), reserved/ -> reserved, failed/ -> dead_letter (every file there,
        # read the same way size("failed") counts it).
        topic_dir = os.path.join(queue_base_path(), topic)
        jobs = []
        if not status_filter or status_filter in ("pending", "completed"):
            counted = (status_filter,) if status_filter else ("pending", "completed")
            jobs += [j for j in _read_queue_dir(topic_dir) if j["status"] in counted]
        if not status_filter or status_filter == "reserved":
            jobs += _read_queue_dir(os.path.join(topic_dir, "reserved"), "reserved")
        if not status_filter or status_filter in ("failed", "dead"):
            jobs += _read_queue_dir(os.path.join(topic_dir, "failed"), "dead_letter")

        return response({"jobs": jobs, "stats": stats})
    except Exception as e:
        return response({"jobs": [], "stats": {"pending": 0, "completed": 0, "failed": 0, "reserved": 0}, "error": str(e)})


async def _api_queue_retry(request, response):
    """Retry failed queue jobs."""
    try:
        from tina4_python.queue import Queue
        topic = request.body.get("topic", "default") if hasattr(request, "body") and request.body else "default"
        queue = Queue(topic=topic)
        retried = queue.retry_failed()
        MessageLog.log("queue", f"Retried {retried} failed jobs", {"topic": topic})
        return response({"retried": retried})
    except Exception as e:
        return response({"error": str(e)}, 500)


async def _api_queue_purge(request, response):
    """Purge completed queue jobs."""
    try:
        from tina4_python.queue import Queue
        topic = request.body.get("topic", "default") if hasattr(request, "body") and request.body else "default"
        status = request.body.get("status", "completed") if hasattr(request, "body") and request.body else "completed"
        queue = Queue(topic=topic)
        queue.purge(status=status)
        MessageLog.log("queue", f"Purged {status} jobs", {"topic": topic})
        return response({"purged": True})
    except Exception as e:
        return response({"error": str(e)}, 500)


async def _api_queue_dead_letters(request, response):
    """List dead letter queue jobs (exceeded max retries).

    Reads failed/ the same way ``size("failed")`` counts it, for the same two
    reasons as _api_queue: ``queue.dead_letters()`` filters on the DEV ADMIN's
    own max_retries — hiding a job an app dead-lettered at fewer attempts — and
    returns ``Job`` objects, which json.dumps(default=str) rendered as
    "<tina4_python.queue.job.Job object at 0x...>" instead of job records.
    """
    try:
        from tina4_python.queue import queue_base_path
        topic = request.query.get("topic", "default") if hasattr(request, "query") else "default"
        jobs = _read_queue_dir(os.path.join(queue_base_path(), topic, "failed"), "dead_letter")
        return response({"jobs": jobs, "count": len(jobs), "topic": topic})
    except Exception as e:
        return response({"jobs": [], "error": str(e)})


async def _api_queue_replay_job(request, response):
    """Replay a specific queue job by ID (re-queue from dead letters or failed)."""
    try:
        from tina4_python.queue import Queue
        body = request.body or {}
        topic = body.get("topic", "default")
        job_id = body.get("id")
        delay = int(body.get("delay", 0))
        queue = Queue(topic=topic)
        if job_id:
            result = queue.retry(job_id=job_id, delay_seconds=delay)
            MessageLog.log("queue", f"Replayed job {job_id}", {"topic": topic})
            return response({"replayed": result, "id": job_id})
        else:
            return response({"error": "Missing job id"}, 400)
    except Exception as e:
        return response({"error": str(e)}, 500)


async def _api_mailbox(request, response):
    """List dev mailbox messages."""
    from tina4_python.messenger import DevMailbox
    mailbox = DevMailbox()
    folder = request.query.get("folder", None) if hasattr(request, "query") else None
    limit = int(request.query.get("limit", "50")) if hasattr(request, "query") else 50
    messages = mailbox.inbox(limit=limit, folder=folder)
    return response({
        "messages": messages,
        "count": len(messages),
        "unread": mailbox.unread_count(),
        "totals": mailbox.count(),
    })


async def _api_mailbox_read(request, response):
    """Read a specific mailbox message."""
    from tina4_python.messenger import DevMailbox
    mailbox = DevMailbox()
    msg_id = request.query.get("id", "") if hasattr(request, "query") else ""
    if not msg_id:
        return response({"error": "id required"}, 400)
    msg = mailbox.read(msg_id)
    if not msg:
        return response({"error": "not found"}, 404)
    return response(msg)


async def _api_mailbox_seed(request, response):
    """Seed fake inbox messages."""
    from tina4_python.messenger import DevMailbox
    mailbox = DevMailbox()
    count = int(request.body.get("count", 5)) if hasattr(request, "body") and request.body else 5
    created = mailbox.seed(count)
    MessageLog.log("email", f"Seeded {created} fake inbox messages")
    return response({"seeded": created})


async def _api_mailbox_clear(request, response):
    """Clear dev mailbox."""
    from tina4_python.messenger import DevMailbox
    mailbox = DevMailbox()
    folder = request.body.get("folder", None) if hasattr(request, "body") and request.body else None
    mailbox.clear(folder=folder)
    MessageLog.log("email", "Cleared dev mailbox", {"folder": folder or "all"})
    return response({"cleared": True})


async def _api_messages(request, response):
    """Get tracked messages."""
    category = request.query.get("category", None) if hasattr(request, "query") else None
    level = request.query.get("level", None) if hasattr(request, "query") else None
    limit = int(request.query.get("limit", "100")) if hasattr(request, "query") else 100
    messages = MessageLog.get(category=category, level=level, limit=limit)
    return response({"messages": messages, "counts": MessageLog.count()})


async def _api_messages_clear(request, response):
    """Clear tracked messages."""
    category = request.body.get("category", None) if hasattr(request, "body") and request.body else None
    MessageLog.clear(category=category)
    return response({"cleared": True})


async def _api_query(request, response):
    """Execute SQL or GraphQL query in the dev database."""
    try:
        body = request.body if hasattr(request, "body") and request.body else {}
        query = body.get("query", "").strip()
        query_type = body.get("type", "sql")  # "sql" or "graphql"

        if not query:
            return response({"error": "query required"}, 400)

        if query_type == "graphql":
            try:
                from tina4_python.graphql import GraphQL
                from tina4_python.orm import ORM

                def _all_orm_subclasses(cls):
                    """Recursively collect all non-abstract ORM subclasses."""
                    result = []
                    for sub in cls.__subclasses__():
                        if not getattr(sub, '__abstractmethods__', None):
                            result.append(sub)
                        result.extend(_all_orm_subclasses(sub))
                    return result

                gql = GraphQL()
                for model_class in _all_orm_subclasses(ORM):
                    try:
                        gql.schema.from_orm(model_class)
                    except Exception:
                        pass

                result = gql.execute(query, variables=body.get("variables", {}))
                MessageLog.log("query", f"GraphQL: {query[:80]}", level="info")
                return response(result)
            except Exception as e:
                return response({"error": str(e)}, 400)

        # SQL query
        from tina4_python.database import Database
        db_url = os.environ.get("TINA4_DATABASE_URL", "sqlite:///data/app.db")
        db = Database(db_url)

        # Split multiple statements on semicolons
        statements = [s.strip() for s in query.split(";") if s.strip()]

        if len(statements) == 1:
            upper = statements[0].upper().lstrip()
            is_read = upper.startswith("SELECT") or upper.startswith("PRAGMA") or upper.startswith("SHOW") or upper.startswith("DESCRIBE")

            if is_read:
                limit = int(body.get("limit", 100))
                offset = int(body.get("offset", 0))
                result = db.fetch(statements[0], limit=limit, offset=offset)
                data = result.records
                MessageLog.log("query", f"SQL: {statements[0][:80]}", {"rows": result.count}, level="info")
                db.close()
                return response({"rows": data, "count": result.count, "limit": limit, "offset": offset})

        # Execute all statements (single write or multi-statement batch)
        total_affected = 0
        db.start_transaction()
        try:
            for stmt in statements:
                result = db.execute(stmt)  # raises on failure → caught + rolled back below
                if hasattr(result, "affected_rows"):
                    total_affected += result.affected_rows
            db.commit()
        except Exception as e:
            db.rollback()
            db.close()
            return response({"error": str(e)}, 400)

        MessageLog.log("query", f"SQL batch: {len(statements)} statement(s)", {"affected": total_affected}, level="warn")
        db.close()
        return response({"affected": total_affected, "success": True})

    except Exception as e:
        return response({"error": str(e)}, 400)


async def _api_tables(request, response):
    """List all database tables."""
    try:
        from tina4_python.database import Database
        db_url = os.environ.get("TINA4_DATABASE_URL", "sqlite:///data/app.db")
        db = Database(db_url)
        tables = db.get_tables()
        db.close()
        return response({"tables": tables})
    except Exception as e:
        return response({"tables": [], "error": str(e)})


async def _api_table_info(request, response):
    """Get table columns and sample data."""
    try:
        from tina4_python.database import Database
        table = request.query.get("name", "") if hasattr(request, "query") else ""
        if not table:
            return response({"error": "name required"}, 400)

        db_url = os.environ.get("TINA4_DATABASE_URL", "sqlite:///data/app.db")
        db = Database(db_url)
        columns = db.get_columns(table)
        sample = db.fetch(f"SELECT * FROM {table} LIMIT 20")
        db.close()
        return response({
            "table": table,
            "columns": columns,
            "rows": sample.records,
            "count": sample.count,
        })
    except Exception as e:
        return response({"error": str(e)}, 400)


async def _api_queue_replay(request, response):
    """Replay a specific queue job — re-enqueue with same data."""
    try:
        from tina4_python.database import Database
        from tina4_python.queue import Queue
        db_url = os.environ.get("TINA4_DATABASE_URL", "sqlite:///data/app.db")
        db = Database(db_url)
        body = request.body if hasattr(request, "body") and request.body else {}
        job_id = body.get("job_id")
        topic = body.get("topic", "default")

        if not job_id:
            return response({"error": "job_id required"}, 400)

        # Fetch original job data
        row = db.fetch_one("SELECT * FROM tina4_queue WHERE id = ?", [job_id])
        if not row:
            db.close()
            return response({"error": "Job not found"}, 404)

        data = row.get("data", "{}")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = {"raw": data}

        # Push new job with same data
        queue = Queue(topic=topic)
        new_id = queue.push(data)
        MessageLog.log("queue", f"Replayed job {job_id} as {new_id}", {"original": job_id, "new": new_id})
        return response({"replayed": True, "original_id": job_id, "new_id": new_id})
    except Exception as e:
        return response({"error": str(e)}, 500)


async def _api_messages_search(request, response):
    """Search message log by keyword."""
    keyword = request.query.get("q", "") if hasattr(request, "query") else ""
    category = request.query.get("category", None) if hasattr(request, "query") else None
    limit = int(request.query.get("limit", "100")) if hasattr(request, "query") else 100

    if not keyword:
        return response({"error": "q parameter required"}, 400)

    keyword_lower = keyword.lower()
    msgs = MessageLog._messages
    if category:
        msgs = [m for m in msgs if m["category"] == category]

    results = []
    for m in reversed(msgs):
        if keyword_lower in m["message"].lower() or (
            m.get("data") and keyword_lower in json.dumps(m["data"]).lower()
        ):
            results.append(m)
            if len(results) >= limit:
                break

    return response({"messages": results, "count": len(results), "query": keyword})


async def _api_seed_table(request, response):
    """Seed fake data into a database table from the admin UI."""
    try:
        from tina4_python.database import Database
        from tina4_python.seeder import FakeData, seed_table, auto_field_map

        body = request.body if hasattr(request, "body") and request.body else {}
        table = body.get("table", "")
        count = int(body.get("count", 10))

        if not table:
            return response({"error": "table required"}, 400)
        if count > 1000:
            count = 1000

        # Reproducibility (P3): accept an optional seed; drop the old hard-coded 42.
        seed_val = body.get("seed")
        if seed_val is not None:
            try:
                seed_val = int(seed_val)
            except (TypeError, ValueError):
                seed_val = None
        clear = bool(body.get("clear", False))
        strict = bool(body.get("strict", False))

        db_url = os.environ.get("TINA4_DATABASE_URL", "sqlite:///data/app.db")
        db = Database(db_url)

        # Get table columns to auto-generate data
        columns = db.get_columns(table)
        if not columns:
            db.close()
            return response({"error": f"Table '{table}' not found or has no columns"}, 404)

        fake = FakeData(seed=seed_val)

        # Build a field_map (column -> generator, skipping auto-increment / id
        # PKs) via the shared seeder helper, then delegate to seed_table so this
        # endpoint shares the exact same visible-but-resilient per-row error
        # handling (P1/P4b) — no unhandled row failure crashes it. The MCP
        # seed_table dev tool uses the identical helper for parity.
        field_map = auto_field_map(db, table, fake)

        try:
            summary = seed_table(db, table, count, field_map=field_map,
                                 clear=clear, strict=strict)
        finally:
            db.close()

        MessageLog.log(
            "seed",
            f"Seeded {summary.seeded} rows into '{table}' ({summary.failed} failed)",
            {"table": table, "seeded": summary.seeded, "failed": summary.failed},
        )
        return response({
            "seeded": summary.seeded,
            "failed": summary.failed,
            "errors": summary.errors,
            "table": table,
        })
    except Exception as e:
        return response({"error": str(e)}, 500)


async def _api_requests(request, response):
    """Get captured HTTP requests."""
    limit = int(request.query.get("limit", "50")) if hasattr(request, "query") else 50
    method = request.query.get("method", None) if hasattr(request, "query") else None
    status_min = request.query.get("status_min", None) if hasattr(request, "query") else None
    reqs = RequestInspector.get(limit=limit, method=method,
                                status_min=int(status_min) if status_min else None)
    return response({"requests": reqs, "stats": RequestInspector.stats()})


async def _api_requests_clear(request, response):
    """Clear captured requests."""
    RequestInspector.clear()
    return response({"cleared": True})


async def _api_broken(request, response):
    """Get tracked errors (.broken files)."""
    entries = BrokenTracker.get_all()
    health = BrokenTracker.health()
    return response({"errors": entries, "health": health})


async def _api_broken_resolve(request, response):
    """Resolve a tracked error."""
    body = request.body if hasattr(request, "body") and request.body else {}
    error_id = body.get("id", "")
    if not error_id:
        return response({"error": "id required"}, 400)
    resolved = BrokenTracker.resolve(error_id)
    if resolved:
        MessageLog.log("error", f"Resolved error {error_id}")
    return response({"resolved": resolved})


async def _api_broken_clear(request, response):
    """Clear ALL tracked errors. The SPA's "Clear All" button hits here,
    and a user clicking "Clear All" expects the panel to actually empty —
    not just hide entries they've individually marked resolved. Use
    clear_all() so the button does what it says on the tin."""
    BrokenTracker.clear_all()
    return response({"cleared": True})


async def _api_websockets(request, response):
    """Get active WebSocket connections."""
    try:
        from tina4_python.websocket import WebSocketManager
        mgr = WebSocketManager()
        connections = []
        for ws in mgr._connections.values() if hasattr(mgr, "_connections") else []:
            connections.append({
                "id": ws.id,
                "path": ws.path,
                "ip": getattr(ws, "ip", ""),
                "connected_at": getattr(ws, "connected_at", ""),
                "closed": ws.closed if hasattr(ws, "closed") else False,
            })
        return response({
            "connections": connections,
            "count": mgr.count() if hasattr(mgr, "count") else len(connections),
        })
    except Exception as e:
        return response({"connections": [], "count": 0, "error": str(e)})


async def _api_ws_disconnect(request, response):
    """Disconnect a WebSocket connection."""
    try:
        from tina4_python.websocket import WebSocketManager
        body = request.body if hasattr(request, "body") and request.body else {}
        ws_id = body.get("id", "")
        if not ws_id:
            return response({"error": "id required"}, 400)
        mgr = WebSocketManager()
        await mgr.disconnect(ws_id)
        return response({"disconnected": True})
    except Exception as e:
        return response({"error": str(e)}, 500)


async def _api_system(request, response):
    """System overview — uptime, memory, DB, versions."""
    import sys
    import platform

    info = {
        "python_version": sys.version,
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "framework": "tina4-python v3",
        "pid": os.getpid(),
        "cwd": os.getcwd(),
        "debug": os.environ.get("TINA4_DEBUG", "false"),
        "log_level": os.environ.get("TINA4_LOG_LEVEL", "ERROR"),
        "database": redact_url(os.environ.get("TINA4_DATABASE_URL", "not configured")),
    }

    # Memory info
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        info["memory_mb"] = round(usage.ru_maxrss / 1024 / 1024, 2) if sys.platform == "linux" else round(usage.ru_maxrss / 1024 / 1024, 2)
    except (ImportError, AttributeError):
        info["memory_mb"] = None

    # Uptime
    info["uptime_seconds"] = round(time.time() - _start_time, 1)

    # DB status
    try:
        from tina4_python.database import Database
        db_url = os.environ.get("TINA4_DATABASE_URL", "")
        if db_url:
            db = Database(db_url)
            tables = db.get_tables()
            info["db_tables"] = len(tables)
            info["db_connected"] = True
            db.close()
        else:
            info["db_tables"] = 0
            info["db_connected"] = False
    except Exception:
        info["db_tables"] = 0
        info["db_connected"] = False

    # Loaded modules count
    info["loaded_modules"] = len([m for m in sys.modules if m.startswith("tina4_python")])

    return response(info)


async def _api_service_ai(request, response):
    return response({"service": "ai", "url": os.environ.get("TINA4_AI_URL", "http://localhost:11437/api/chat"), "ok": True})


async def _api_service_vision(request, response):
    return response({"service": "vision", "url": os.environ.get("TINA4_VISION_URL", "http://localhost:11437/api/chat"), "ok": True})


async def _api_service_embed(request, response):
    return response({"service": "embed", "url": os.environ.get("TINA4_EMBED_URL", "http://localhost:11437/api/embeddings"), "ok": True})


async def _api_service_image(request, response):
    return response({"service": "image", "url": os.environ.get("TINA4_IMAGE_URL", "http://localhost:11437/api/generate"), "ok": True})


async def _api_service_rag(request, response):
    return response({"service": "rag", "url": os.environ.get("TINA4_RAG_URL", "http://localhost:11438"), "ok": True})


def _supervisor_base_url() -> str:
    """Return the URL of the co-located rust agent server, if any.

    Resolution order (first match wins):

      1. `TINA4_SUPERVISOR_URL` — full URL for non-localhost deployments.
      2. `TINA4_AGENT_PORT` — explicit port override.
      3. `PORT + 2000` — auto-derived. `tina4 serve` exports the
         framework's PORT into the child process AND spawns the agent
         on `port + 2000` (main.rs::handle_serve). Reading PORT here
         keeps both sides aligned automatically: Python on 7146 →
         agent on 9146, Node on 7148 → agent on 9148, etc.
      4. Hardcoded 9145 — matches `tina4 agent` standalone's default
         (main.rs::handle_agent), for users running the agent without
         going through `tina4 serve`.
    """
    explicit = os.environ.get("TINA4_SUPERVISOR_URL", "").rstrip("/")
    if explicit:
        return explicit

    agent_port_str = os.environ.get("TINA4_AGENT_PORT", "").strip()
    if agent_port_str.isdigit():
        return f"http://127.0.0.1:{int(agent_port_str)}"

    framework_port_str = os.environ.get("PORT", "").strip()
    if framework_port_str.isdigit():
        return f"http://127.0.0.1:{int(framework_port_str) + 2000}"

    return "http://127.0.0.1:9145"


async def _proxy_to_supervisor(request, response, downstream_path: str):
    """Forward a dev-admin request to the rust agent server.

    The SPA's supervisor UI calls paths like ``/__dev/api/supervise/create``;
    we strip the ``/__dev/api`` prefix and POST/GET the same body+query to
    the agent server. Returns the agent's response verbatim. When the
    agent isn't reachable (tina4 serve not running, or bare framework)
    we respond with a specific 503 so the SPA can show a useful error
    instead of silently doing nothing.
    """
    import urllib.request
    import urllib.error

    base = _supervisor_base_url()
    qs = ""
    try:
        if hasattr(request, "query") and request.query:
            from urllib.parse import urlencode
            qs = "?" + urlencode(request.query)
    except Exception:
        qs = ""
    target = f"{base}{downstream_path}{qs}"

    method = (getattr(request, "method", "GET") or "GET").upper()
    data = None
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        body = getattr(request, "body", None)
        if isinstance(body, dict):
            # SPA→agent convention fixup: `/execute` sends plan_file as
            # a bare filename but the rust agent expects a project-relative
            # path. Prepend `plan/` when no slash is present.
            pf = body.get("plan_file")
            if isinstance(pf, str) and pf and "/" not in pf:
                body = dict(body)
                body["plan_file"] = f"plan/{pf}"
            data = json.dumps(body).encode()
        elif isinstance(body, list):
            data = json.dumps(body).encode()
        elif isinstance(body, str) and body:
            data = body.encode()

    import asyncio

    req = urllib.request.Request(
        target,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    # /execute and /chat run the multi-agent loop — supervisor +
    # planner + coder, each a multi-second LLM call. Other
    # supervise/* calls are metadata-only and return fast, so a
    # generous shared timeout for the heavy ones is cheaper than
    # branching on every endpoint.
    timeout = 600 if downstream_path in ("/execute", "/chat") else 30

    # Open the upstream connection in a thread — urlopen is blocking.
    # We DON'T read the body here; that's done below either in one shot
    # (JSON path) or chunk-by-chunk (SSE path) so progress events reach
    # the SPA live instead of after the whole 30-second supervisor run.
    try:
        upstream = await asyncio.to_thread(
            urllib.request.urlopen, req, None, timeout
        )
    except urllib.error.HTTPError as e:
        err_body = e.read().decode() if e.fp else str(e)
        try:
            return response(json.loads(err_body), e.code)
        except Exception:
            return response({"error": err_body[:300]}, e.code)
    except Exception as e:
        return response({
            "error": "supervisor unavailable",
            "detail": str(e),
            "hint": "Run `tina4 serve` (starts the agent server) or set TINA4_SUPERVISOR_URL",
        }, 503)

    upstream_ct = upstream.headers.get("Content-Type", "") or ""

    # SSE / event-stream: stream chunks through as they arrive. Without
    # this the SPA sees nothing until the supervisor's entire multi-agent
    # run completes (30s+), then a wall of events at once — looks like
    # "Connection failed". urlopen.read(n) is blocking, so each read goes
    # through asyncio.to_thread to keep the event loop responsive.
    if "text/event-stream" in upstream_ct.lower():
        async def _relay():
            try:
                while True:
                    chunk = await asyncio.to_thread(upstream.read, 4096)
                    if not chunk:
                        break
                    yield chunk
            finally:
                upstream.close()
        return response.stream(_relay(), "text/event-stream")

    # JSON / other: drain the body and return as before.
    try:
        raw = await asyncio.to_thread(upstream.read)
    finally:
        upstream.close()
    try:
        return response(json.loads(raw))
    except Exception:
        return response(raw.decode("utf-8", errors="replace"))


async def _api_supervise_create(request, response):
    """Before forwarding to the rust agent, auto-flesh the current plan
    if it has zero steps. The SPA sends the user's supervisor-chat
    message as ``title``/``plan``; we use that as the fleshing prompt.
    Skipped when the plan already has steps so populated plans aren't
    polluted. Best-effort — never blocks supervise/create."""
    try:
        from tina4_python.dev_admin import plan as _plan
        current = _plan.current()
        is_empty = (
            isinstance(current.get("current"), str)
            and (current.get("progress") or {}).get("total", 0) == 0
        )
        if is_empty:
            body = getattr(request, "body", None) or {}
            if isinstance(body, dict):
                prompt = str(body.get("plan") or body.get("title") or "").strip()
                if prompt:
                    _plan.flesh(current["current"], prompt)
    except Exception:
        pass  # Fleshing is best-effort.
    return await _proxy_to_supervisor(request, response, "/supervise/create")


async def _api_supervise_sessions(request, response):
    return await _proxy_to_supervisor(request, response, "/supervise/sessions")


async def _api_supervise_diff(request, response):
    return await _proxy_to_supervisor(request, response, "/supervise/diff")


async def _api_supervise_commit(request, response):
    return await _proxy_to_supervisor(request, response, "/supervise/commit")


async def _api_supervise_cancel(request, response):
    return await _proxy_to_supervisor(request, response, "/supervise/cancel")


async def _api_execute(request, response):
    return await _proxy_to_supervisor(request, response, "/execute")


async def _api_thoughts(request, response):
    """Thoughts — proxied to the rust agent server when it's running,
    otherwise an empty list so the SPA renders gracefully."""
    base = _supervisor_base_url()
    import urllib.request
    import urllib.error
    try:
        with urllib.request.urlopen(f"{base}/thoughts", timeout=5) as r:
            raw = r.read()
        try:
            return response(json.loads(raw))
        except Exception:
            return response({"thoughts": []})
    except Exception:
        return response({"thoughts": []})


async def _api_ai_proxy(request, response):
    """Transparent pass-through to the qwen ollama chat endpoint.

    Accepts the ollama-native body (``{model, messages, stream,
    options}``) that the dev-admin SPA sends for FIM completion and
    supervisor chat, forwards it verbatim to ``TINA4_AI_URL``, and
    returns the response unchanged. Streaming is forced off upstream
    because the built-in asyncio server can't reliably chunk responses
    back to the SPA; the SPA's ``body.getReader()`` still works for
    single-shot JSON.
    """
    import urllib.request
    import urllib.error

    raw_body = request.body if hasattr(request, "body") else None
    if isinstance(raw_body, (dict, list)):
        payload = dict(raw_body) if isinstance(raw_body, dict) else raw_body
        if isinstance(payload, dict):
            payload["stream"] = False
        raw_bytes = json.dumps(payload).encode()
    elif isinstance(raw_body, str) and raw_body.strip():
        try:
            decoded = json.loads(raw_body)
            if isinstance(decoded, dict):
                decoded["stream"] = False
            raw_bytes = json.dumps(decoded).encode()
        except Exception:
            raw_bytes = raw_body.encode()
    else:
        return response({"error": "empty body"}, 400)

    ai_url = os.environ.get("TINA4_AI_URL", "http://localhost:11437/api/chat")
    try:
        req = urllib.request.Request(
            ai_url,
            data=raw_bytes,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        err_body = e.read().decode() if e.fp else str(e)
        return response({"error": f"AI backend {e.code}: {err_body[:200]}"}, 502)
    except Exception as e:
        return response({"error": f"AI backend unreachable: {e}"}, 502)

    # Forward qwen's response verbatim as JSON.
    try:
        return response(json.loads(body))
    except Exception:
        # Non-JSON body (shouldn't happen from ollama) — best-effort text.
        return response(body.decode("utf-8", errors="replace"))


# ── Customer feedback widget — server-side plumbing ─────────────────
#
# Tier 1 (intake-only): customer text never reaches a file-write code
# path. Flow:
#   1. Framework middleware injects <script src="/__feedback/widget.js">
#      into HTML responses for whitelisted users.
#   2. Widget POSTs to /__feedback/api/turn for each conversational turn.
#   3. This handler verifies whitelist + rate-limit, stamps the user
#      identity server-side (client cannot fake `sender`), then forwards
#      to the Rust agent's /feedback/intake (which runs the "intake"
#      agent — no tools, JSON-only output).
#   4. Finalised tickets land in .tina4/chat/threads.json with
#      kind:"feedback". Developer sees them in the dev admin sidebar.

_FEEDBACK_RATE_LIMIT: dict[str, list[float]] = {}
_FEEDBACK_RATE_WINDOW = 3600   # 1 hour
_FEEDBACK_RATE_MAX = 5         # submissions/turns per user per hour


def _feedback_enabled() -> bool:
    """Hard master switch.

    Both gates required for the widget to render or the API to accept
    submissions:
      - TINA4_ENABLE_FEEDBACK=true (explicit opt-in — off by default)
      - TINA4_FEEDBACK_WHITELIST=... (non-empty list of users)

    Splitting the toggle from the whitelist lets the developer leave
    the whitelist intact while pausing the feature in production for
    a release (set TINA4_ENABLE_FEEDBACK=false → widget vanishes
    everywhere; whitelist comes back online with one env flip).
    """
    return os.environ.get("TINA4_ENABLE_FEEDBACK", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _feedback_whitelist() -> list[str]:
    """Comma-separated emails / user IDs in env. Empty = no one allowed."""
    if not _feedback_enabled():
        return []  # master switch off — short-circuits everywhere
    raw = os.environ.get("TINA4_FEEDBACK_WHITELIST", "").strip()
    if not raw:
        return []
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


def _feedback_identify_user(request) -> str | None:
    """Best-effort user identity from auth headers.

    Priority:
      1. JWT/Bearer token via Auth.authenticate_request — pulls
         email/sub/user_id claim.
      2. TINA4_FEEDBACK_DEV_USER env var override (LOCAL DEV ONLY —
         lets the framework owner test the widget without a full
         auth setup in the test project).
    """
    try:
        from tina4_python.auth import Auth
        payload = Auth.authenticate_request(request.headers)
        if payload and isinstance(payload, dict):
            for key in ("email", "sub", "user_id"):
                v = payload.get(key)
                if v:
                    return str(v).strip().lower()
    except Exception:
        pass
    dev_user = os.environ.get("TINA4_FEEDBACK_DEV_USER", "").strip()
    if dev_user:
        return dev_user.lower()
    return None


def _feedback_is_whitelisted(request) -> tuple[bool, str | None]:
    """Returns (allowed, identity). Both halves must be true to act."""
    wl = _feedback_whitelist()
    if not wl:
        return False, None  # feature off entirely
    user = _feedback_identify_user(request)
    if not user:
        return False, None
    return user in wl, user


def _feedback_rate_limit_ok(user: str) -> bool:
    """5 turns/hour per user. Prunes old timestamps lazily."""
    now = time.time()
    hits = [t for t in _FEEDBACK_RATE_LIMIT.get(user, [])
            if now - t < _FEEDBACK_RATE_WINDOW]
    if len(hits) >= _FEEDBACK_RATE_MAX:
        _FEEDBACK_RATE_LIMIT[user] = hits
        return False
    hits.append(now)
    _FEEDBACK_RATE_LIMIT[user] = hits
    return True


def inject_feedback_widget(request, html: bytes) -> bytes:
    """Insert the widget <script> into HTML responses for whitelisted users.

    Called from server.py right before the body is sent. No-op if:
      - The request is for a /__dev or /__feedback path (developer
        dashboard / widget assets — never inject the customer widget
        on developer pages; the dev admin has its OWN chat trigger).
      - TINA4_ENABLE_FEEDBACK + TINA4_FEEDBACK_WHITELIST not both set
      - Requesting user isn't in the whitelist
      - Response doesn't have a closing </body> tag (fragment, JSON, etc.)
    Idempotent: a second call won't double-inject (looks for marker).
    """
    if not html:
        return html
    # The customer feedback widget is for END USERS of the shipped app —
    # injecting on developer-only paths creates a confusing "two bubbles"
    # UX where the dev chat trigger + customer feedback bubble sit on
    # top of each other. Hard exclusion at the framework layer.
    path = getattr(request, "path", "") or ""
    if path.startswith("/__dev") or path.startswith("/__feedback"):
        return html
    allowed, _user = _feedback_is_whitelisted(request)
    if not allowed:
        return html
    marker = b'data-tina4-feedback'
    if marker in html:
        return html  # already injected upstream
    snippet = b'<script src="/__feedback/widget.js" data-tina4-feedback></script>'
    lower = html.rfind(b'</body>')
    if lower < 0:
        return html
    return html[:lower] + snippet + html[lower:]


async def _api_feedback_turn(request, response):
    """Proxy a single conversational turn to the Rust agent /feedback/intake.

    Stamps `sender` server-side from the verified identity — client
    cannot inject who they are. Rate-limited per user.
    """
    allowed, user = _feedback_is_whitelisted(request)
    if not allowed:
        return response({"error": "not authorised for feedback"}, 403)
    if not _feedback_rate_limit_ok(user):
        return response({
            "error": "rate limit exceeded",
            "hint": f"max {_FEEDBACK_RATE_MAX} turns per hour",
        }, 429)

    body = getattr(request, "body", None)
    if not isinstance(body, dict):
        return response({"error": "expected JSON body"}, 400)

    forward_body = dict(body)
    forward_body["sender"] = user  # server-stamped identity

    import asyncio
    import urllib.request, urllib.error
    base = _supervisor_base_url()
    payload = json.dumps(forward_body).encode()

    def _do_request():
        req = urllib.request.Request(
            f"{base}/feedback/intake",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        return urllib.request.urlopen(req, timeout=60)

    try:
        upstream = await asyncio.to_thread(_do_request)
        raw = await asyncio.to_thread(upstream.read)
        upstream.close()
    except urllib.error.HTTPError as e:
        err = e.read().decode() if e.fp else str(e)
        try:
            return response(json.loads(err), e.code)
        except Exception:
            return response({"error": err[:300]}, e.code)
    except Exception as e:
        return response({
            "error": "agent unreachable",
            "detail": str(e),
        }, 502)

    try:
        return response(json.loads(raw))
    except Exception:
        return response(raw.decode("utf-8", errors="replace"))


async def _api_toolbar_css(request, response):
    """Serve the dev-toolbar stylesheet (CSP-clean external asset, #115).

    text/css so the injected toolbar carries no inline ``style=`` and renders
    under a strict ``default-src 'self'`` CSP. Served via the response callable's
    explicit content-type arg (never ``.html()``) so the toolbar is not injected
    into its own asset — mirrors PHP's ``/__dev/toolbar.css`` route.
    """
    return response(toolbar_css(), 200, "text/css; charset=UTF-8")


async def _api_toolbar_js(request, response):
    """Serve the dev-toolbar script (CSP-clean external asset, #115).

    application/javascript so every toolbar event is wired via
    ``addEventListener`` (no inline handlers / ``<script>``) and runs under a
    strict ``default-src 'self'`` CSP — mirrors PHP's ``/__dev/toolbar.js`` route.
    """
    return response(toolbar_js(), 200, "application/javascript; charset=UTF-8")


async def _api_feedback_widget_js(request, response):
    """Serve the widget bundle.

    Lives at tina4_python/public/__feedback/widget.js — built from the
    tina4-feedback-widget source. Until that's wired we return a tiny
    stub so the route is reachable; the real bundle ships in Task 24.

    Cache-Control: no-cache, must-revalidate so browsers re-check the
    bundle on every load. Without this an old cached bundle (e.g. one
    that pre-dates the path-block guard against rendering on /__dev/)
    can persist for days and keep painting the bubble on the dev admin
    even after the server-side script-tag injection is fixed.
    """
    from pathlib import Path
    js_path = Path(__file__).parent.parent / "public" / "__feedback" / "widget.js"
    body = js_path.read_bytes() if js_path.exists() else b"console.warn('tina4-feedback-widget bundle not built yet');"
    # Force the browser to revalidate the bundle every load — see docstring.
    if hasattr(response, "header"):
        response.header("cache-control", "no-cache, must-revalidate")
        response.header("pragma", "no-cache")
    return response(body, 200, "application/javascript")


async def _api_threads(request, response):
    """Proxy /__dev/api/threads → Rust agent /threads (GET list, POST create).

    Method-multiplexed handler — the dev_admin dispatcher registered this
    under the "*" method wildcard so one entry point serves both list and
    create. Anything other than GET/POST gets a 405.
    """
    method = (getattr(request, "method", "GET") or "GET").upper()
    if method not in ("GET", "POST"):
        return response({"error": "method not allowed"}, 405)
    return await _proxy_to_supervisor(request, response, "/threads")


async def _api_threads_sub(request, response):
    """Proxy /__dev/api/threads/{id}[/messages] → Rust agent.

    Catches everything beneath /__dev/api/threads/ via the dispatcher's
    "/*" prefix match. We strip the dev-admin prefix and forward the
    remaining path verbatim so /__dev/api/threads/abc/messages becomes
    /threads/abc/messages on the agent side.
    """
    path = getattr(request, "path", "") or ""
    suffix = path[len("/__dev/api"):]  # leaves "/threads/abc[/messages]"
    if not suffix.startswith("/threads/"):
        return response({"error": "not found"}, 404)
    return await _proxy_to_supervisor(request, response, suffix)


async def _api_chat(request, response):
    """Proxy dev-admin chat to the Rust agent server's /chat endpoint.

    The SPA (Chat.ts) POSTs `{message, settings, files?}` and expects an
    SSE stream of `event: status / message / done` chunks. The Rust agent
    runs the supervisor → planner → coder loop, calls the configured LLM
    (Anthropic / OpenAI / Tina4 Cloud — driven by `ChatSettings` from
    `.tina4/chat/settings.json` or the ANTHROPIC_API_KEY env-var
    defaults), and streams progress back.

    Earlier versions of this endpoint called qwen on the Tina4 Cloud
    directly and returned a single JSON blob, which broke the SPA's SSE
    reader and bypassed every configured model setting. If you want the
    bare qwen path it's still reachable at /ai/api/chat.

    When `tina4 agent` isn't running, _proxy_to_supervisor returns 503
    with a helpful hint so the SPA can show a real error instead of
    silently hanging.
    """
    return await _proxy_to_supervisor(request, response, "/chat")


async def _api_tool(request, response):
    """Run a developer tool and return output."""
    import subprocess
    import sys

    body = request.body if hasattr(request, "body") and request.body else {}
    tool = body.get("tool", "")

    tools = {
        "carbon": [sys.executable, "benchmarks/carbon_benchmarks.py"],
        "test": [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=short"],
        "routes": [sys.executable, "-c",
                   "from tina4_python.core.router import Router; "
                   "[print(f\"{r['method']:7} {r['path']}\") for r in Router.get_routes()]"],
        "migrate": [sys.executable, "-c",
                    "from tina4_python.cli import _migrate; _migrate([])"],
        "seed": [sys.executable, "-c",
                 "from tina4_python.cli import _seed; _seed([])"],
        "ai": [sys.executable, "-c",
               "from tina4_python.ai import status_report; print(status_report())"],
    }

    if tool not in tools:
        return response({"error": f"Unknown tool: {tool}"}, 400)

    try:
        result = subprocess.run(
            tools[tool], capture_output=True, text=True, timeout=120, cwd=os.getcwd()
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        MessageLog.log("tool", f"Ran tool: {tool}", {"exit_code": result.returncode})
        return response({"output": output.strip(), "exit_code": result.returncode})
    except subprocess.TimeoutExpired:
        return response({"output": "Tool timed out after 120 seconds", "exit_code": -1})
    except Exception as e:
        return response({"error": str(e)}, 500)


def _tina4_robot_fallback(message: str) -> str:
    """Offline Tina4 — answers common questions without an LLM."""
    msg = message.lower()
    if "route" in msg:
        return "Create routes in src/routes/ using @get, @post decorators. Routes are auto-discovered. Use @noauth() for public POST routes, @secured() for protected GET routes."
    elif "orm" in msg or "model" in msg:
        return "Define ORM models in src/orm/ — one class per file. Use IntegerField, StringField, etc. Call model.save(), model.load(), model.select(). Don't forget to create a migration for the table."
    elif "database" in msg or "db" in msg:
        return "Set TINA4_DATABASE_URL in .env. Supports sqlite, postgres, mysql, firebird, mssql, mongodb. Use db.fetch(), db.insert(), db.update(), db.delete()."
    elif "queue" in msg:
        return "Use Queue(topic='name') with queue.produce() to enqueue, queue.consume() to process. Supports litequeue, RabbitMQ, Kafka, MongoDB backends."
    elif "template" in msg or "twig" in msg:
        return "Templates use Jinja2/Twig syntax in src/templates/. Always extend base.twig. Use {% block %} for content, {% include %} for partials."
    elif "auth" in msg or "jwt" in msg:
        return "Set SECRET in .env. POST/PUT/DELETE require Bearer token by default. Use @noauth() to make public, @secured() to protect GET routes."
    elif "test" in msg:
        return "Write tests in tests/ using pytest. Run with 'tina4python test' or 'pytest tests/ -v'."
    elif "migrate" in msg or "migration" in msg:
        return "Create: 'tina4python migrate:create \"description\"'. Run: 'tina4python migrate'. Files go in migrations/ folder."
    elif "seed" in msg:
        return "Create seed files in src/seeds/. Use FakeData() for data generation, seed_table() for bulk insert. Run with 'tina4python seed'."
    else:
        return "I'm Tina4! Ask me about routes, ORM, database, queues, templates, auth, tests, migrations, or seeding. Set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env for AI-powered answers."


async def _api_connections(request, response):
    """Get current .env database config."""
    env_path = Path(".env")
    url = ""
    username = ""
    password = ""
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key == "TINA4_DATABASE_URL":
                url = val
            elif key == "TINA4_DATABASE_USERNAME":
                username = val
            elif key == "TINA4_DATABASE_PASSWORD":
                password = "***" if val else ""
    return response({"url": url, "username": username, "password": password})


async def _api_connections_test(request, response):
    """Test a database connection."""
    body = request.body if hasattr(request, "body") else {}
    url = body.get("url", "")
    username = body.get("username", "")
    password = body.get("password", "")
    if not url:
        return response({"success": False, "error": "No connection URL provided"})
    try:
        from tina4_python.database import Database
        db = Database(url, username, password)
        version = ""
        table_count = 0
        try:
            tables = db.get_tables()
            table_count = len(tables) if tables else 0
        except Exception:
            table_count = 0
        try:
            if "sqlite" in url.lower():
                row = db.fetch_one("SELECT sqlite_version() as v")
                version = f"SQLite {row['v']}" if row else "SQLite"
            elif "psycopg" in url.lower() or "postgresql" in url.lower() or "postgres" in url.lower():
                row = db.fetch_one("SELECT version() as v")
                version = row["v"].split(",")[0] if row else "PostgreSQL"
            elif "mysql" in url.lower():
                row = db.fetch_one("SELECT version() as v")
                version = f"MySQL {row['v']}" if row else "MySQL"
            elif "mssql" in url.lower() or "pymssql" in url.lower():
                row = db.fetch_one("SELECT @@VERSION as v")
                version = row["v"].split("\n")[0] if row else "MSSQL"
            elif "firebird" in url.lower():
                row = db.fetch_one(
                    "SELECT rdb$get_context('SYSTEM', 'ENGINE_VERSION') as v FROM rdb$database"
                )
                version = f"Firebird {row['v']}" if row else "Firebird"
        except Exception:
            version = "Connected"
        db.close()
        return response({"success": True, "version": version, "tables": table_count})
    except Exception as e:
        return response({"success": False, "error": str(e)})


async def _api_connections_save(request, response):
    """Save connection config to .env."""
    body = request.body if hasattr(request, "body") else {}
    url = body.get("url", "")
    username = body.get("username", "")
    password = body.get("password", "")
    if not url:
        return response({"success": False, "error": "No connection URL provided"})
    try:
        env_path = Path(".env")
        lines = []
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()
        keys_found = {"TINA4_DATABASE_URL": False, "TINA4_DATABASE_USERNAME": False, "TINA4_DATABASE_PASSWORD": False}
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                new_lines.append(line)
                continue
            key = stripped.split("=", 1)[0].strip()
            # Preserve the TINA4_ prefix when rewriting — the boot guard
            # rejects bare DATABASE_URL / DATABASE_USERNAME / DATABASE_PASSWORD
            # since v3.12, so stripping the prefix here would break the next
            # restart. Bug filed as tina4-python#45.
            if key == "TINA4_DATABASE_URL":
                new_lines.append(f"TINA4_DATABASE_URL={url}")
                keys_found["TINA4_DATABASE_URL"] = True
            elif key == "TINA4_DATABASE_USERNAME":
                new_lines.append(f"TINA4_DATABASE_USERNAME={username}")
                keys_found["TINA4_DATABASE_USERNAME"] = True
            elif key == "TINA4_DATABASE_PASSWORD":
                new_lines.append(f"TINA4_DATABASE_PASSWORD={password}")
                keys_found["TINA4_DATABASE_PASSWORD"] = True
            else:
                new_lines.append(line)
        for key, found in keys_found.items():
            if not found:
                val = {"TINA4_DATABASE_URL": url, "TINA4_DATABASE_USERNAME": username, "TINA4_DATABASE_PASSWORD": password}[key]
                new_lines.append(f"{key}={val}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return response({"success": True})
    except Exception as e:
        return response({"success": False, "error": str(e)})


async def _api_gallery_list(request, response):
    """List available gallery examples."""
    import json
    gallery_dir = Path(__file__).parent.parent / "gallery"
    items = []
    if gallery_dir.exists():
        for entry in sorted(gallery_dir.iterdir()):
            meta_file = entry / "meta.json"
            if entry.is_dir() and meta_file.exists():
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                meta["id"] = entry.name
                # List the files that would be deployed
                src_dir = entry / "src"
                if src_dir.exists():
                    meta["files"] = [
                        str(f.relative_to(src_dir))
                        for f in src_dir.rglob("*") if f.is_file()
                    ]
                items.append(meta)
    return response({"gallery": items, "count": len(items)})


async def _api_gallery_deploy(request, response):
    """Deploy a gallery example into the running project."""
    import shutil
    body = request.body if hasattr(request, "body") else {}
    name = body.get("name", "")
    if not name:
        return response({"error": "No gallery item specified"}, 400)

    gallery_src = Path(__file__).parent.parent / "gallery" / name / "src"
    if not gallery_src.exists():
        return response({"error": f"Gallery item '{name}' not found"}, 404)

    project_src = Path.cwd() / "src"
    copied = []
    for src_file in gallery_src.rglob("*"):
        if src_file.is_file():
            rel = src_file.relative_to(gallery_src)
            dest = project_src / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest)
            copied.append(str(rel))

    # Re-discover routes so new files are immediately available
    try:
        from tina4_python.core.server import _auto_discover
        _auto_discover("src")
    except Exception:
        pass  # Non-fatal — routes will load on next restart

    return response({"deployed": name, "files": copied})


# Mtime counter — incremented by POST /__dev/api/reload from Rust CLI.
# The browser polls /__dev/api/mtime and reloads when this changes.
_reload_mtime = [0]
_reload_file = [""]


async def _api_mtime(request, response):
    """Return the last reload timestamp for browser polling.

    The dev toolbar JS polls this endpoint and triggers a browser refresh
    when the mtime changes. Updated by the Rust CLI via POST /__dev/api/reload.
    """
    return response({
        "mtime": _reload_mtime[0],
        "file": _reload_file[0],
    })


async def _api_reload(request, response):
    """Trigger a browser reload — called by the Rust CLI on file changes.

    Updates the mtime counter so the polling fallback detects the change AND
    re-runs auto-discover so new files in src/routes/, src/orm/, src/app/
    register their decorators without a server restart. `_auto_discover` is
    idempotent — already-imported modules are skipped.
    """
    import time
    _reload_mtime[0] = int(time.time())
    _reload_file[0] = (request.body or {}).get("file", "")
    reload_type = (request.body or {}).get("type", "reload")
    from tina4_python.debug import Log
    Log.info(f"External reload trigger: {reload_type}" + (f" ({_reload_file[0]})" if _reload_file[0] else ""))

    # Re-discover so brand-new route/model/middleware files load on reload.
    # Imports already in sys.modules are skipped, so existing files are not
    # re-imported (use a full restart for that).
    try:
        from tina4_python.core.server import _auto_discover
        before = _route_count()
        _auto_discover("src")
        after = _route_count()
        if after > before:
            Log.info(f"Re-discovered {after - before} new route(s) on reload")
    except Exception as e:
        Log.error(f"Re-discover on reload failed: {e}")

    # Keep the code Context index LIVE on the same WebSocket-reload trigger:
    # reindex just the changed file (UPSERT) so the dev-MCP code_search reflects
    # the edit immediately. Only touches an already-built index (existing_context
    # never creates one); guarded so a context failure never breaks the reload.
    try:
        if _reload_file[0]:
            from tina4_python.context import existing_context
            _ctx = existing_context()
            if _ctx is not None:
                _ctx.reindex_file(_reload_file[0])
    except Exception as e:
        Log.error(f"Context reindex on reload failed: {e}")

    # WebSocket-primary reload: push an instant message to every browser
    # connected on /__dev_reload. The toolbar client (and the dev-admin
    # dashboard) act on this immediately — the mtime poll above is only a
    # fallback for when the socket is down. CSS changes swap stylesheets;
    # everything else triggers a full page reload. We normalise the wire
    # `type` to "css"/"reload" so both clients react (the dashboard only
    # listens for reload/change/css), but the HTTP response still echoes the
    # caller's original type. Wrapped so a broadcast failure (or zero
    # clients) never 500s the reload endpoint.
    ws_type = "css" if reload_type == "css" else "reload"
    try:
        from tina4_python.core.server import _ws_manager
        await _ws_manager.broadcast(
            json.dumps({"type": ws_type, "file": _reload_file[0], "mtime": _reload_mtime[0]}),
            path="/__dev_reload",
        )
    except Exception as e:
        Log.error(f"Dev-reload WebSocket broadcast failed: {e}")

    return response({"ok": True, "type": reload_type})


def _route_count() -> int:
    try:
        from tina4_python.core.router import Router
        return len(Router.get_routes())
    except Exception:
        return 0


async def _api_version_check(request, response):
    """Proxy version check to PyPI to avoid browser CORS errors."""
    import urllib.request
    current = __version__
    latest = current
    try:
        req = urllib.request.Request(
            "https://pypi.org/pypi/tina4-python/json",
            headers={"User-Agent": "tina4-python/" + current},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            latest = data.get("info", {}).get("version", current)
    except Exception:
        pass  # Offline or timeout — return current as latest
    return response({"current": current, "latest": latest})


async def _api_metrics_full(request, response):
    """Full analysis from the native engine (ADR-0002).

    One engine for every language, so a number here is comparable with the same
    number in PHP, Ruby or Node. There is no local fallback: a second
    implementation is what made the four frameworks' numbers incomparable, so a
    missing or stale CLI returns 503 naming the fix instead of quietly serving
    different arithmetic.
    """
    from tina4_python.dev_admin.metrics import full_analysis, MetricsEngineError

    try:
        return response(full_analysis())
    except MetricsEngineError as exc:
        return response({"error": str(exc), "engine": "tina4-cli"}, 503)


async def _api_metrics_file(request, response):
    """Per-file detail metrics."""
    from tina4_python.dev_admin.metrics import file_detail, MetricsEngineError

    path = request.query.get("path", "")
    if not path:
        return response({"error": "Missing path parameter"}, 400)
    try:
        return response(file_detail(path))
    except MetricsEngineError as exc:
        message = str(exc)
        # A bad path is the caller's mistake (404); anything else is the engine
        # being absent or stale (503). Same split as the /metrics/full contract.
        if "no such file" in message or "not a file" in message:
            return response({"error": message}, 404)
        return response({"error": message, "engine": "tina4-cli"}, 503)


async def _api_graphql_schema(request, response):
    """GraphQL schema introspection — auto-discovers ORM models and returns schema + SDL."""
    try:
        from tina4_python.graphql import GraphQL
        from tina4_python.orm.model import ORM

        gql = GraphQL()
        # Auto-discover all ORM subclasses
        for cls in ORM.__subclasses__():
            try:
                gql.schema.from_orm(cls)
            except Exception:
                pass  # Skip models that can't be introspected
        return response({
            "schema": gql.introspect(),
            "sdl": gql.schema_sdl(),
        })
    except Exception as e:
        return response({"error": str(e)}, 400)


# Module startup time for uptime tracking
_start_time = time.time()



# Legacy render_dashboard() removed — UI served from tina4-dev-admin.min.js


def render_dev_toolbar(method: str, path: str, matched_pattern: str,
                       request_id: str, route_count: int) -> str:
    """Return an HTML toolbar injected at the bottom of HTML responses in dev mode.

    Shows: Tina4 version (blue), HTTP method (green), path, matched pattern,
    request ID (yellow), route count (blue), Python version, Dashboard link,
    and a close button.

    CSP-clean (tina4stack #115): the toolbar carries NO inline ``style=``, NO
    ``onclick=``, and NO inline ``<script>`` block. Presentation lives in the
    external stylesheet served at ``/__dev/toolbar.css`` and every event is
    wired via ``addEventListener`` inside ``/__dev/toolbar.js`` — so the toolbar
    renders and works under the framework's strict ``default-src 'self'`` CSP
    (SecurityHeadersMiddleware) instead of being stripped and spewing violations.
    Faithful parity with PHP's ``DevAdmin::renderToolbar()``.

    The reloader is suppressed by emitting ``data-reload="0"`` (AI/stable port,
    or ``TINA4_NO_RELOAD``); toolbar.js early-returns unless it reads ``"1"``.
    """
    import sys
    from html import escape as _html_escape
    from tina4_python.core.server import _ai_port_ctx
    python_version = sys.version.split()[0]
    # DEVADMIN-DEC-04: the toolbar is injected into every text/html response
    # (including 404s), so the reflected request path/method MUST be HTML-escaped
    # or a crafted path reflects <script> that runs in the dev-server origin and
    # can then drive every /__dev mutation route. (PHP already escapes; parity.)
    method = _html_escape(str(method), quote=True)
    path = _html_escape(str(path), quote=True)
    matched_pattern = _html_escape(str(matched_pattern), quote=True)
    request_id = _html_escape(str(request_id), quote=True)
    no_reload = os.environ.get("TINA4_NO_RELOAD", "").lower() in ("true", "1", "yes") or _ai_port_ctx.get()
    reload = "0" if no_reload else "1"

    return f"""<link rel="stylesheet" href="/__dev/toolbar.css">
<div id="tina4-dev-toolbar" data-reload="{reload}">
    <span id="tina4-ver-btn" title="Click to check for updates">Tina4 v{__version__}</span>
    <div id="tina4-ver-modal">
      <div class="t4-modal-head">
        <strong class="t4-modal-title">Version Info</strong>
        <span id="tina4-ver-close" class="t4-x">&times;</span>
      </div>
      <div id="tina4-ver-body">
        <div>Current: <strong class="t4-ok">v{__version__}</strong></div>
        <div id="tina4-ver-latest" class="t4-dim">Checking for updates...</div>
      </div>
    </div>
    <span class="t4-green">{method}</span>
    <span>{path}</span>
    <span class="t4-arrow">&rarr; {matched_pattern}</span>
    <span class="t4-yellow">req:{request_id}</span>
    <span class="t4-blue">{route_count} routes</span>
    <span class="t4-dim">Python {python_version}</span>
    <a href="#" id="tina4-dash-link" class="t4-dash">Dashboard &#8599;</a>
    <span id="tina4-bar-close" class="t4-x t4-bar-close">&#10005;</span>
</div>
<script src="/__dev/toolbar.js"></script>"""


def toolbar_css() -> str:
    """CSS for the injected dev toolbar, served as an external stylesheet.

    Extracted so the toolbar carries no inline ``style=`` and stays CSP-clean
    under a strict ``default-src 'self'``. Parity with PHP ``toolbarCss()`` —
    Python keeps its own accent (``#3572A5``) but the same class vocabulary so
    the JS can set state via ``className`` rather than inline styles.
    """
    return """#tina4-dev-toolbar{position:fixed;bottom:0;left:0;right:0;background:#333;color:#fff;font-family:monospace;font-size:12px;padding:6px 16px;z-index:99999;display:flex;align-items:center;gap:16px}
#tina4-dev-toolbar a{text-decoration:none}
#tina4-ver-btn{color:#3572A5;font-weight:bold;cursor:pointer;text-decoration:underline dotted}
#tina4-ver-modal{display:none;position:fixed;bottom:3rem;left:1rem;background:#1e1e2e;border:1px solid #3572A5;border-radius:8px;padding:16px 20px;z-index:100000;min-width:320px;box-shadow:0 8px 32px rgba(0,0,0,.5);font-family:monospace;font-size:13px;color:#cdd6f4}
.t4-modal-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.t4-modal-title{color:#89b4fa}
#tina4-ver-body{line-height:1.8}
.t4-x{cursor:pointer;color:#888}
.t4-bar-close{margin-left:8px}
.t4-green{color:#4caf50}
.t4-dim{color:#888}
.t4-arrow{color:#666}
.t4-yellow{color:#ffeb3b}
.t4-blue{color:#90caf9}
.t4-ok{color:#a6e3a1}
.t4-warn{color:#f9e2af}
.t4-err{color:#f38ba8}
.t4-purple{color:#cba6f7}
.t4-link{color:#89b4fa}
.t4-code{background:#313244;padding:2px 6px;border-radius:3px}
.t4-note{margin-top:6px}
.t4-dash{color:#ef9a9a;margin-left:auto;cursor:pointer}
#tina4-dev-panel{position:fixed;top:3rem;left:0;right:0;bottom:2rem;z-index:99998;transition:all .2s}
#tina4-dev-panel iframe{width:100%;height:100%;border:1px solid #3572A5;border-radius:.5rem;box-shadow:0 8px 32px rgba(0,0,0,.5);background:#0f172a}
"""


def toolbar_js() -> str:
    """JS for the injected dev toolbar, served as an external script.

    Wires the version-check modal, the dashboard overlay (hydrated from
    localStorage) and the WebSocket-primary live reloader — every event via
    ``addEventListener``, no inline handlers — so the toolbar stays CSP-clean.
    The reloader only starts when the toolbar root's ``data-reload`` attribute
    is ``"1"``; on the AI/stable port (or with ``TINA4_NO_RELOAD``) the render
    emits ``"0"`` and the reloader early-returns. Parity with PHP ``toolbarJs()``.

    The mtime-poll fallback interval honours ``TINA4_DEV_POLL_INTERVAL``.
    """
    poll_interval_ms = int(os.environ.get("TINA4_DEV_POLL_INTERVAL", "3000"))
    return """(function () {
    var bar = document.getElementById('tina4-dev-toolbar');
    if (!bar) { return; }

    var modal = document.getElementById('tina4-ver-modal');
    function upToDate(el, latest) {
        el.className = 't4-ok';
        el.innerHTML = 'Latest: <strong class="t4-ok">v' + latest + '</strong> &mdash; You are up to date!';
    }
    function checkVersion() {
        if (modal.style.display === 'block') { modal.style.display = 'none'; return; }
        modal.style.display = 'block';
        var el = document.getElementById('tina4-ver-latest');
        el.className = 't4-dim';
        el.textContent = 'Checking for updates...';
        fetch('/__dev/api/version-check').then(function (r) { return r.json(); }).then(function (d) {
            var latest = d.latest, current = d.current;
            if (latest === current) { upToDate(el, latest); return; }
            var cP = current.split('.').map(Number), lP = latest.split('.').map(Number);
            var isNewer = false, i, c, l;
            for (i = 0; i < Math.max(cP.length, lP.length); i++) { c = cP[i] || 0; l = lP[i] || 0; if (l > c) { isNewer = true; break; } if (l < c) { break; } }
            var isAhead = false;
            if (!isNewer) { for (i = 0; i < Math.max(cP.length, lP.length); i++) { var c2 = cP[i] || 0, l2 = lP[i] || 0; if (c2 > l2) { isAhead = true; break; } if (c2 < l2) { break; } } }
            if (isNewer) {
                var breaking = (lP[0] !== cP[0] || lP[1] !== cP[1]);
                el.className = '';
                el.innerHTML = 'Latest: <strong class="t4-warn">v' + latest + '</strong>';
                if (breaking) {
                    el.innerHTML += '<div class="t4-err t4-note">&#9888; Major/minor version change &mdash; check the <a href="https://github.com/tina4stack/tina4-python/releases" target="_blank" class="t4-link">changelog</a> for breaking changes before upgrading.</div>';
                } else {
                    el.innerHTML += '<div class="t4-warn t4-note">Patch update available. Run: <code class="t4-code">pip install --upgrade tina4-python</code></div>';
                }
            } else if (isAhead) {
                el.className = 't4-purple';
                el.innerHTML = 'You are running <strong class="t4-purple">v' + current + '</strong> (ahead of PyPI <strong>v' + latest + '</strong> &mdash; not yet published).';
            } else {
                upToDate(el, latest);
            }
        }).catch(function () {
            el.className = 't4-err';
            el.textContent = 'Could not check for updates (offline?)';
        });
    }
    var verBtn = document.getElementById('tina4-ver-btn');
    if (verBtn) { verBtn.addEventListener('click', checkVersion); }
    var verClose = document.getElementById('tina4-ver-close');
    if (verClose) { verClose.addEventListener('click', function () { modal.style.display = 'none'; }); }
    var barClose = document.getElementById('tina4-bar-close');
    if (barClose) { barClose.addEventListener('click', function () { bar.style.display = 'none'; }); }

    var STATE_KEY = 'tina4_dev_overlay_open';
    function buildOverlay() {
        var c = document.createElement('div');
        c.id = 'tina4-dev-panel';
        var f = document.createElement('iframe');
        f.src = '/__dev';
        c.appendChild(f);
        document.body.appendChild(c);
        return c;
    }
    function toggleOverlay(e) {
        if (e) { e.preventDefault(); }
        var p = document.getElementById('tina4-dev-panel');
        if (p) {
            var hide = p.style.display !== 'none';
            p.style.display = hide ? 'none' : 'block';
            try { localStorage.setItem(STATE_KEY, hide ? '0' : '1'); } catch (_) {}
            return;
        }
        buildOverlay();
        try { localStorage.setItem(STATE_KEY, '1'); } catch (_) {}
    }
    var dash = document.getElementById('tina4-dash-link');
    if (dash) { dash.addEventListener('click', toggleOverlay); }
    try {
        if (location.pathname.indexOf('/__dev') !== 0
            && localStorage.getItem(STATE_KEY) === '1'
            && !document.getElementById('tina4-dev-panel')) {
            buildOverlay();
        }
    } catch (_) {}

    if (bar.getAttribute('data-reload') !== '1') { return; }
    var cssExts = ['.css', '.scss'], debounce = null, interval = parseInt('__POLL_INTERVAL__') || 3000;
    var ws = null, pollTimer = null, mtime = null;
    function apply(d) {
        d = d || {};
        var f = d.file || '', t = d.type || '';
        var isCss = t === 'css' || cssExts.some(function (e) { return f.endsWith(e); });
        if (isCss) {
            document.querySelectorAll('link[rel="stylesheet"]').forEach(function (l) {
                var href = l.getAttribute('href');
                if (href) { l.setAttribute('href', href.split('?')[0] + '?_t4=' + (d.mtime || Date.now())); }
            });
        } else {
            location.reload();
        }
    }
    function poll() {
        fetch('/__dev/api/mtime').then(function (r) { return r.json(); }).then(function (d) {
            if (mtime === null) { mtime = d.mtime; return; }
            if (d.mtime !== mtime) { mtime = d.mtime; if (debounce) { clearTimeout(debounce); } debounce = setTimeout(function () { apply(d); }, 500); }
        }).catch(function () {});
    }
    function startPoll() { if (pollTimer) { return; } mtime = null; pollTimer = setInterval(poll, interval); }
    function stopPoll() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }
    function connect() {
        var url = (location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + '/__dev_reload';
        try { ws = new WebSocket(url); } catch (_) { startPoll(); return; }
        ws.addEventListener('open', function () { stopPoll(); });
        ws.addEventListener('message', function (ev) {
            var d = null;
            try { d = typeof ev.data === 'string' ? JSON.parse(ev.data) : null; } catch (_) {}
            if (!d) { return; }
            if (d.type === 'reload' || d.type === 'change' || d.type === 'css') {
                if (debounce) { clearTimeout(debounce); }
                debounce = setTimeout(function () { apply(d); }, 150);
            }
        });
        ws.addEventListener('close', function () { ws = null; startPoll(); setTimeout(connect, 2000); });
        ws.addEventListener('error', function () { try { ws && ws.close(); } catch (_) {} });
    }
    connect();
})();
""".replace("__POLL_INTERVAL__", str(poll_interval_ms))


# ── Editor API endpoints ──────────────────────────────────────

async def _api_files(request, response):
    """List files in a directory with git status.

    Query params:
        path — relative directory path (default: project root)
    """
    import os, subprocess
    rel = (request.query.get("path") or "").strip("/")
    base = os.getcwd()
    target = os.path.normpath(os.path.join(base, rel))

    # Security: must stay within project root
    if not target.startswith(base):
        return response({"error": "Path outside project", "path": rel, "entries": [], "branch": ""}, 403)

    if not os.path.isdir(target):
        # Missing / invalid paths: return an empty-but-valid shape
        # instead of 404. The SPA restores previously-expanded folder
        # state from localStorage; when a session moves to a different
        # harness, folders that don't exist trigger 404s which bubble
        # as noisy red errors. Empty `entries` lets the SPA quietly skip.
        return response({"path": rel, "entries": [], "branch": "", "error": "Not a directory"})

    # Find git root (may differ from cwd)
    git_root = base
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, cwd=base, timeout=5
        )
        if out.returncode == 0:
            git_root = out.stdout.strip().replace("\\", "/")
    except Exception:
        pass

    # Prefix to prepend to entry_rel paths to match git's paths
    cwd_in_git = os.path.relpath(base, git_root).replace("\\", "/")
    if cwd_in_git == ".":
        cwd_in_git = ""
    else:
        cwd_in_git += "/"

    # Get git status for the project
    git_status = {}
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "-uall"],
            capture_output=True, text=True, cwd=base, timeout=5
        )
        for line in out.stdout.strip().split("\n"):
            if len(line) >= 4:
                status_code = line[:2].strip()
                file_path = line[3:].strip()
                git_status[file_path] = status_code
    except Exception:
        pass

    # Get current branch
    branch = ""
    try:
        out = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, cwd=base, timeout=5
        )
        branch = out.stdout.strip()
    except Exception:
        pass

    entries = []
    try:
        for name in sorted(os.listdir(target)):
            full = os.path.join(target, name)
            entry_rel = os.path.relpath(full, base).replace("\\", "/")

            # DEVADMIN-DEC-03: never surface secrets in the listing (.env, keys,
            # .git/, secrets/). The .env.example template is safe to show.
            if _is_secret_path(entry_rel):
                continue
            # Skip hidden dirs and noise
            if name.startswith(".") and name != ".env.example":
                continue
            if name in ("__pycache__", "node_modules", "vendor", ".git",
                        "venv", ".venv", "dist", "target", ".tina4"):
                continue

            is_dir = os.path.isdir(full)

            # Git path = cwd_in_git + entry_rel (what git reports)
            git_path = cwd_in_git + entry_rel

            # Git status for this entry
            status = "clean"
            if git_path in git_status:
                code = git_status[git_path]
                if code == "??":
                    status = "untracked"
                elif "M" in code:
                    status = "modified"
                elif "A" in code:
                    status = "added"
                elif "D" in code:
                    status = "deleted"
            elif is_dir:
                # Check if any child is dirty
                dir_prefix = git_path + "/"
                for gf, gc in git_status.items():
                    if gf.startswith(dir_prefix):
                        if gc == "??":
                            status = "untracked"
                        else:
                            status = "modified"
                        break

            # Check if directory has children (for arrow display)
            has_children = False
            if is_dir:
                try:
                    contents = os.listdir(full)
                    has_children = any(
                        not n.startswith(".") and n not in (
                            "__pycache__", "node_modules", "vendor",
                            ".git", "venv", ".venv", "dist", "target", ".tina4"
                        ) for n in contents
                    )
                except PermissionError:
                    pass

            entries.append({
                "name": name,
                "path": entry_rel,
                "is_dir": is_dir,
                "has_children": has_children if is_dir else None,
                "git_status": status,
                "size": os.path.getsize(full) if not is_dir else None,
            })
    except PermissionError:
        return response({"error": "Permission denied"}, 403)

    return response({
        "path": rel or ".",
        "branch": branch,
        "entries": entries,
    })


async def _api_file_read(request, response):
    """Read a file's content.

    Query params:
        path — relative file path

    IMPORTANT: error responses MUST include ``path`` (echo what was
    requested). The SPA bundle calls ``e.path.split()`` on the response
    payload unconditionally — if ``path`` is absent it throws and kills
    the click handler for every subsequent file open. Manifests as
    "folder clicks work, file clicks don't" after the SPA restores
    previously-open tabs from localStorage that no longer exist.
    """
    import os
    rel = (request.query.get("path") or "").strip("/")
    if not rel:
        return response({"error": "path required", "path": "", "content": "", "language": "text", "size": 0}, 400)

    # DEVADMIN-DEC-03: never serve secret material (.env, keys, .git/, secrets/).
    if _is_secret_path(rel):
        return response({"error": "Refused: secret file", "path": rel, "content": "", "language": "text", "size": 0}, 403)

    base = os.getcwd()
    target = os.path.normpath(os.path.join(base, rel))

    if not target.startswith(base):
        return response({"error": "Path outside project", "path": rel, "content": "", "language": "text", "size": 0}, 403)

    if not os.path.isfile(target):
        return response({"error": "File not found", "path": rel, "content": "", "language": "text", "size": 0}, 404)

    # Size guard: don't load huge files into JSON
    size = os.path.getsize(target)
    if size > 2 * 1024 * 1024:  # 2MB
        return response({"error": "File too large", "path": rel, "content": "", "language": "text", "size": size}, 413)

    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return response({"error": str(e), "path": rel, "content": "", "language": "text", "size": 0}, 500)

    # Detect language from extension
    ext = os.path.splitext(rel)[1].lower()
    # Also detect Dockerfile (no extension)
    basename = os.path.basename(rel)
    if basename.lower() in ("dockerfile", "dockerfile.dev", "dockerfile.prod"):
        return response({
            "path": rel, "content": content,
            "language": "dockerfile", "size": size,
        })

    lang_map = {
        ".py": "python", ".php": "php", ".rb": "ruby",
        ".ts": "typescript", ".js": "javascript", ".jsx": "javascript",
        ".tsx": "typescript", ".json": "json", ".html": "html",
        ".twig": "html", ".css": "css", ".scss": "css",
        ".md": "markdown", ".sql": "sql", ".yaml": "yaml",
        ".yml": "yaml", ".toml": "toml", ".xml": "html",
        ".env": "env", ".env.example": "env",
        ".sh": "shell", ".bash": "shell",
        ".bat": "shell", ".cmd": "shell", ".ps1": "shell",
        ".rs": "rust", ".go": "go", ".java": "java",
        ".txt": "text", ".csv": "text", ".log": "text",
        ".gemspec": "ruby", ".rake": "ruby",
        ".svg": "svg",
    }

    return response({
        "path": rel,
        "content": content,
        "language": lang_map.get(ext, "text"),
        "size": size,
    })


async def _api_file_raw(request, response):
    """Serve a raw file with correct content-type (for image preview etc).

    Query params:
        path — relative file path
    """
    import os, mimetypes
    rel = (request.query.get("path") or "").strip("/")
    if not rel:
        return response({"error": "path required"}, 400)

    # DEVADMIN-DEC-03: never serve secret material (.env, keys, .git/, secrets/).
    if _is_secret_path(rel):
        return response({"error": "Refused: secret file"}, 403)

    base = os.getcwd()
    target = os.path.normpath(os.path.join(base, rel))

    if not target.startswith(base):
        return response({"error": "Path outside project"}, 403)
    if not os.path.isfile(target):
        return response({"error": "File not found"}, 404)

    # Size guard
    size = os.path.getsize(target)
    if size > 10 * 1024 * 1024:
        return response({"error": "File too large"}, 413)

    content_type = mimetypes.guess_type(target)[0] or "application/octet-stream"

    try:
        with open(target, "rb") as f:
            data = f.read()
    except Exception as e:
        return response({"error": str(e)}, 500)

    # PHP-parity: stream the bytes back with the correct Content-Type,
    # not a JSON wrapper. Matches PHP's `$response->header(...)->html(...)`.
    return response(data, 200, content_type)


async def _api_file_save(request, response):
    """Save content to a file.

    Body: { "path": "...", "content": "..." }
    """
    import os
    body = request.body or {}
    rel = (body.get("path") or "").strip("/")
    content = body.get("content")

    if not rel:
        return response({"error": "path required"}, 400)
    if content is None:
        return response({"error": "content required"}, 400)

    base = os.getcwd()
    target = os.path.normpath(os.path.join(base, rel))

    if not target.startswith(base):
        return response({"error": "Path outside project"}, 403)

    # Don't allow overwriting framework internals
    if "tina4_python/" in rel or "vendor/" in rel or "node_modules/" in rel:
        return response({"error": "Cannot write to framework directories"}, 403)

    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="") as f:
            f.write(content)
    except Exception as e:
        return response({"error": str(e)}, 500)

    return response({"saved": True, "path": rel, "size": len(content)})


async def _api_file_rename(request, response):
    """Rename/move a file or directory.

    Body: { "from": "old/path", "to": "new/path" }
    """
    import os, shutil
    body = request.body or {}
    from_rel = (body.get("from") or "").strip("/")
    to_rel = (body.get("to") or "").strip("/")
    if not from_rel or not to_rel:
        return response({"error": "from and to required"}, 400)

    base = os.getcwd()
    from_abs = os.path.normpath(os.path.join(base, from_rel))
    to_abs = os.path.normpath(os.path.join(base, to_rel))

    if not from_abs.startswith(base) or not to_abs.startswith(base):
        return response({"error": "Path outside project"}, 403)
    if not os.path.exists(from_abs):
        return response({"error": "Source not found"}, 404)

    try:
        os.makedirs(os.path.dirname(to_abs), exist_ok=True)
        shutil.move(from_abs, to_abs)
    except Exception as e:
        return response({"error": str(e)}, 500)

    return response({"renamed": True, "from": from_rel, "to": to_rel})


async def _api_file_delete(request, response):
    """Delete a file or directory.

    Body: { "path": "...", "is_dir": false }
    """
    import os, shutil
    body = request.body or {}
    rel = (body.get("path") or "").strip("/")
    is_dir = body.get("is_dir", False)

    if not rel:
        return response({"error": "path required"}, 400)

    base = os.getcwd()
    target = os.path.normpath(os.path.join(base, rel))

    if not target.startswith(base):
        return response({"error": "Path outside project"}, 403)
    if not os.path.exists(target):
        return response({"error": "Not found"}, 404)

    # Safety: don't delete project root or key config
    if rel in (".", "..", "app.py", "index.php", "app.rb", "app.ts",
               "composer.json", "Gemfile", "package.json", "pyproject.toml"):
        return response({"error": "Cannot delete project root files"}, 403)

    try:
        if is_dir:
            shutil.rmtree(target)
        else:
            os.remove(target)
    except Exception as e:
        return response({"error": str(e)}, 500)

    return response({"deleted": True, "path": rel})


async def _api_deps_search(request, response):
    """Search package registries.

    Query params: q (search term), registry (pypi|npm|packagist|rubygems|crates)
    """
    import urllib.request, json
    query = request.query.get("q", "").strip()
    registry = request.query.get("registry", "pypi")
    if not query:
        return response({"packages": []})

    packages = []
    try:
        if registry == "pypi":
            url = f"https://pypi.org/pypi/{query}/json"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Tina4-DevAdmin/1.0"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    data = json.loads(r.read())
                    info = data.get("info", {})
                    packages.append({
                        "name": info.get("name", query),
                        "description": (info.get("summary") or "")[:120],
                        "version": info.get("version", ""),
                    })
            except Exception:
                # Fallback: search API
                url = f"https://pypi.org/search/?q={urllib.parse.quote(query)}&o="
                # Simple search not available via JSON — just return empty
                pass

            # Also try search via simple JSON API
            if not packages:
                search_url = f"https://pypi.org/simple/"
                # PyPI doesn't have a search JSON API, use the name directly
                pass

        elif registry == "npm":
            url = f"https://registry.npmjs.org/-/v1/search?text={urllib.parse.quote(query)}&size=10"
            req = urllib.request.Request(url, headers={"User-Agent": "Tina4-DevAdmin/1.0"})
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read())
                for obj in data.get("objects", []):
                    pkg = obj.get("package", {})
                    packages.append({
                        "name": pkg.get("name", ""),
                        "description": (pkg.get("description") or "")[:120],
                        "version": pkg.get("version", ""),
                    })

        elif registry == "packagist":
            url = f"https://packagist.org/search.json?q={urllib.parse.quote(query)}&per_page=10"
            req = urllib.request.Request(url, headers={"User-Agent": "Tina4-DevAdmin/1.0"})
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read())
                for pkg in data.get("results", []):
                    packages.append({
                        "name": pkg.get("name", ""),
                        "description": (pkg.get("description") or "")[:120],
                        "version": "",
                    })

        elif registry == "rubygems":
            url = f"https://rubygems.org/api/v1/search.json?query={urllib.parse.quote(query)}&page=1"
            req = urllib.request.Request(url, headers={"User-Agent": "Tina4-DevAdmin/1.0"})
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read())
                for pkg in data[:10]:
                    packages.append({
                        "name": pkg.get("name", ""),
                        "description": (pkg.get("info") or "")[:120],
                        "version": pkg.get("version", ""),
                    })

        elif registry == "crates":
            url = f"https://crates.io/api/v1/crates?q={urllib.parse.quote(query)}&per_page=10"
            req = urllib.request.Request(url, headers={"User-Agent": "Tina4-DevAdmin/1.0"})
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read())
                for pkg in data.get("crates", []):
                    packages.append({
                        "name": pkg.get("name", ""),
                        "description": (pkg.get("description") or "")[:120],
                        "version": pkg.get("max_version", ""),
                    })

    except Exception as e:
        return response({"packages": [], "error": str(e)})

    return response({"packages": packages})


async def _api_deps_install(request, response):
    """Install a package dependency.

    Body: { "name": "...", "version": "...", "registry": "pypi|npm|...", "file": "..." }
    """
    import subprocess
    body = request.body or {}
    name = body.get("name", "").strip()
    version = body.get("version", "").strip()
    registry = body.get("registry", "pypi")
    # A dev/test dependency (pytest, etc.) goes in the manifest's dev group, not
    # runtime deps. The install must PERSIST to the manifest — so we prefer the
    # project's dependency manager (uv/bundle) over a bare pip/gem install.
    dev = bool(body.get("dev"))

    if not name:
        return response({"error": "name required"}, 400)

    import shutil

    try:
        if registry == "pypi":
            pkg = f"{name}>={version}" if version else name
            # uv add persists to pyproject.toml AND installs into the project's
            # venv. Fall back to pip only when uv or pyproject.toml is absent.
            if shutil.which("uv") and Path("pyproject.toml").exists():
                cmd = ["uv", "add", *(["--dev"] if dev else []), pkg]
            else:
                cmd = ["pip", "install", pkg]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                return response({"error": (result.stderr or result.stdout).strip()}, 500)
            return response({"message": f"Installed {name} {version}".strip(), "output": result.stdout or result.stderr})

        elif registry == "npm":
            pkg = f"{name}@{version}" if version else name
            cmd = ["npm", "install", *(["--save-dev"] if dev else []), pkg]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                return response({"error": result.stderr.strip()}, 500)
            return response({"message": f"Installed {name}", "output": result.stdout})

        elif registry == "packagist":
            pkg = f"{name}:{version}" if version else name
            cmd = ["composer", "require", *(["--dev"] if dev else []), pkg]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                return response({"error": result.stderr.strip()}, 500)
            return response({"message": f"Installed {name}", "output": result.stdout})

        elif registry == "rubygems":
            # bundle add persists to the Gemfile. Fall back to gem install.
            if shutil.which("bundle") and Path("Gemfile").exists():
                cmd = ["bundle", "add", name]
                if version:
                    cmd += ["--version", version]
                if dev:
                    cmd += ["--group", "development"]
            else:
                cmd = ["gem", "install", name, *(["-v", version] if version else [])]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                return response({"error": result.stderr.strip()}, 500)
            return response({"message": f"Installed {name}", "output": result.stdout})

        else:
            return response({"error": f"Unsupported registry: {registry}"}, 400)

    except subprocess.TimeoutExpired:
        return response({"error": "Install timed out (60s)"}, 500)
    except FileNotFoundError as e:
        return response({"error": f"Package manager not found: {e}"}, 500)
    except Exception as e:
        return response({"error": str(e)}, 500)


async def _api_git_status(request, response):
    """Return git branch, changed files, and summary."""
    import os, subprocess
    base = os.getcwd()

    result = {"branch": "", "changes": [], "clean": True}

    try:
        out = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, cwd=base, timeout=5
        )
        result["branch"] = out.stdout.strip()
    except Exception:
        return response(result)

    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "-uall"],
            capture_output=True, text=True, cwd=base, timeout=5
        )
        for line in out.stdout.strip().split("\n"):
            if len(line) >= 4:
                code = line[:2].strip()
                path = line[3:].strip()
                status = "modified"
                if code == "??":
                    status = "untracked"
                elif "A" in code:
                    status = "added"
                elif "D" in code:
                    status = "deleted"
                result["changes"].append({"path": path, "status": status})
        result["clean"] = len(result["changes"]) == 0
    except Exception:
        pass

    return response(result)


# ─── MCP REST shim ─────────────────────────────────────────────────
#
# Exposes the framework's MCP tool registry (`_default_server`) over
# plain GET/POST JSON so the dev-admin browser panel and any other
# REST client can enumerate and invoke tools without speaking the full
# JSON-RPC 2.0 over SSE protocol.
#
# The JSON-RPC endpoint at `/__dev/mcp/{message,sse}` stays live for
# proper MCP clients (Claude Desktop et al.) — the two surfaces share
# the same registry, so tools registered via the `@mcp_tool` decorator
# show up on both immediately.

def _mcp_token_ok(request) -> bool:
    """Timing-safe check of a remote MCP caller's token against
    TINA4_MCP_TOKEN (falling back to TINA4_API_KEY). Accepts an
    `Authorization: Bearer <token>` header, `X-MCP-Token`, or `X-Api-Key`."""
    import os as _os, hmac as _hmac
    expected = _os.environ.get("TINA4_MCP_TOKEN") or _os.environ.get("TINA4_API_KEY") or ""
    if not expected:
        return False
    headers = getattr(request, "headers", None) or {}
    auth = headers.get("authorization", "") or ""
    provided = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
    if not provided:
        provided = headers.get("x-mcp-token", "") or headers.get("x-api-key", "")
    if not provided:
        return False
    return _hmac.compare_digest(str(provided), str(expected))


def _mcp_request_allowed(request) -> bool:
    """Per-request MCP authorisation gate applied by EVERY MCP surface
    (JSON-RPC, SSE, and the REST shim). Loopback callers are allowed; a
    non-loopback (remote) caller needs TINA4_MCP_REMOTE + a valid token.
    Uses the raw socket peer (request.remote_ip), never X-Forwarded-For."""
    from tina4_python.mcp import is_request_allowed
    remote_ip = getattr(request, "remote_ip", "") or ""
    return is_request_allowed(remote_ip, _mcp_token_ok(request))


async def _api_mcp_tools(request, response):
    """GET — return the MCP tool registry as a plain JSON list.

    Shape matches what dev-admin's `listMcpTools()` expects:
        {"tools": [{"name": "...", "description": "...", "schema": {...}}, ...]}
    """
    if not _mcp_request_allowed(request):
        return response({"tools": [], "error": "MCP forbidden"}, 404)
    try:
        from tina4_python.mcp import _get_default_server
        server = _get_default_server()
        tools = [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "schema": t.get("inputSchema") or {"type": "object", "properties": {}},
            }
            for t in server._tools.values()
        ]
        return response({"tools": tools})
    except Exception as exc:
        return response({"tools": [], "error": str(exc)}, 500)


async def _api_mcp_call(request, response):
    """POST — invoke an MCP tool by name.

    Request:  {"name": "tool_name", "arguments": {...}}
    Response: {"ok": true, "name": "...", "result": ...}
           or {"ok": false, "error": "..."}

    The wrapper uses the tool's handler directly rather than routing
    through `handle_message` — we already know the name and args, no
    need to round-trip through JSON-RPC framing.
    """
    # DEVADMIN-DEC-05 / MCP-02: two-layer gate, identical to every other MCP
    # surface (tools-list, the JSON-RPC endpoint, the SSE stream): a disallowed
    # caller gets 404 BEFORE any tool runs. Without this, a remote unauthenticated
    # caller on a TINA4_DEBUG=true 0.0.0.0-bound server could invoke every tool
    # (database_execute, file_write). Uses the RAW socket peer, never XFF.
    if not _mcp_request_allowed(request):
        return response({"ok": False, "error": "MCP forbidden"}, 404)
    body = request.body or {}
    if not isinstance(body, dict):
        return response({"ok": False, "error": "body must be a JSON object"}, 400)

    name = body.get("name")
    if not name or not isinstance(name, str):
        return response({"ok": False, "error": "missing 'name'"}, 400)

    args = body.get("arguments") or body.get("args") or {}
    if not isinstance(args, dict):
        return response({"ok": False, "error": "'arguments' must be an object"}, 400)

    try:
        from tina4_python.mcp import _get_default_server
        server = _get_default_server()
        tool = server._tools.get(name)
        if tool is None:
            return response({"ok": False, "error": f"unknown tool: {name}"}, 404)

        handler = tool["handler"]
        # Tools are registered as regular functions or coroutines;
        # await the result when the handler returns an awaitable.
        import inspect
        if inspect.iscoroutinefunction(handler):
            result = await handler(**args)
        else:
            result = handler(**args)

        return response({"ok": True, "name": name, "result": result})
    except TypeError as exc:
        # Bad args shape — surface the Python error cleanly rather
        # than returning a 500. Callers see "argument X missing" etc.
        return response({"ok": False, "name": name, "error": f"argument error: {exc}"}, 400)
    except Exception as exc:
        return response({"ok": False, "name": name, "error": str(exc)}, 500)


# ─── MCP transport endpoint ────────────────────────────────────────
#
# The protocol surface real MCP clients (Claude Code / Claude Desktop)
# speak. Mounted on the running dev server so each `tina4 serve`d project
# exposes its OWN endpoint, giving an AI agent live access scoped to that
# project. Shares the same `_default_server` tool registry as the REST
# shim above, so every @mcp_tool shows up on all surfaces.
#
# Two transports live here:
#   * Streamable HTTP (current) — POST /__dev/mcp with the JSON-RPC message;
#     the response comes back inline as application/json, and initialize
#     issues an Mcp-Session-Id header the client echoes on later requests.
#     GET is 405 (this server initiates no messages) and DELETE ends a
#     session.
#   * Legacy HTTP+SSE (2024-11-05) — GET /__dev/mcp/sse opens a persistent
#     stream that first names the POST endpoint, then delivers each JSON-RPC
#     response as an SSE `message` event; POST /__dev/mcp/message feeds it.
#     Kept working for older SSE-only clients.


def _mcp_session_header(request) -> str:
    """Read the Mcp-Session-Id request header (empty string when absent)."""
    headers = getattr(request, "headers", None) or {}
    return headers.get("mcp-session-id", "") or ""


def _mcp_apply(response, outcome):
    """Apply a dispatch_http/dispatch_sse_message result dict (status,
    headers, body) onto the dev-admin response."""
    import json as _json
    for name, value in outcome["headers"].items():
        response.header(name, value)
    body = outcome["body"]
    if not body:
        return response("", outcome["status"])
    return response(_json.loads(body), outcome["status"])


async def _api_mcp_endpoint(request, response):
    """The Streamable HTTP endpoint at /__dev/mcp (method wildcard).

    POST   — a JSON-RPC message; response is inline application/json.
    GET    — 405, this server pushes no unsolicited messages (use the
             legacy /sse stream if you need server-initiated framing).
    DELETE — terminate the session named by Mcp-Session-Id.
    """
    from tina4_python.mcp import _get_default_server
    if not _mcp_request_allowed(request):
        return response({"error": "MCP disabled"}, 404)
    server = _get_default_server()
    method = (getattr(request, "method", "") or "GET").upper()

    if method == "POST":
        outcome = server.dispatch_http(request.body, _mcp_session_header(request))
        return _mcp_apply(response, outcome)

    if method == "DELETE":
        server.close_session(_mcp_session_header(request))
        return response("", 204)

    # GET (and anything else): no server-initiated stream on this endpoint.
    response.header("Allow", "POST, DELETE")
    return response({"error": "method not allowed"}, 405)


async def _api_mcp_message(request, response):
    """POST /__dev/mcp/message — legacy HTTP+SSE message sink.

    Delivers the JSON-RPC response on the matching open SSE stream (202
    here); with no open stream it degrades to an inline Streamable HTTP
    response, so the path also serves a plain POST client.
    """
    from tina4_python.mcp import _get_default_server
    if not _mcp_request_allowed(request):
        return response({"error": "MCP disabled"}, 404)
    server = _get_default_server()
    params = getattr(request, "params", None) or {}
    session_id = params.get("sessionId") or _mcp_session_header(request)
    outcome = server.dispatch_sse_message(request.body, session_id)
    return _mcp_apply(response, outcome)


async def _api_mcp_sse(request, response):
    """GET /__dev/mcp/sse — legacy HTTP+SSE stream.

    Opens a persistent SSE connection: first the `endpoint` event naming the
    POST target (session-tagged), then each JSON-RPC response as it arrives.
    """
    from tina4_python.mcp import _get_default_server
    if not _mcp_request_allowed(request):
        return response({"error": "MCP disabled"}, 404)
    server = _get_default_server()
    session_id = server.open_session()
    base = getattr(request, "path", "/__dev/mcp/sse").rsplit("/sse", 1)[0]
    endpoint_url = f"{base}/message?sessionId={session_id}"
    return response.stream(server.sse_stream(session_id, endpoint_url))


# ─── Scaffold REST shim ────────────────────────────────────────────
#
# Wraps the tina4python `generate <kind> <name>` CLI commands so the
# + Route / + Model / + Migration / + Middleware buttons in dev-admin
# can call them without shelling out from the browser. The handlers
# import the generator functions directly rather than shelling out —
# avoids spawning a subprocess per click and surfaces errors as JSON.

_SCAFFOLD_KINDS = [
    {"kind": "route",      "label": "+ Route",      "needs_name": True},
    {"kind": "model",      "label": "+ Model",      "needs_name": True},
    {"kind": "migration",  "label": "+ Migration",  "needs_name": True},
    {"kind": "middleware", "label": "+ Middleware", "needs_name": True},
]


async def _api_scaffold_list(request, response):
    """GET — list the scaffold kinds this framework knows how to emit.

    Dev-admin renders one button per item. Each carries a `kind` the
    /scaffold/run endpoint expects and a human `label` for the UI.
    """
    return response({"kinds": _SCAFFOLD_KINDS})


async def _api_scaffold_run(request, response):
    """POST — invoke a generator.

    Request:  {"kind": "route", "name": "contact"}
    Response: {"ok": true, "files": ["src/routes/contact.py"]}
           or {"ok": false, "error": "..."}

    Uses tina4_python.cli's module-level generator functions rather
    than shelling out via subprocess — faster, no path/env lookup.
    """
    body = request.body or {}
    if not isinstance(body, dict):
        return response({"ok": False, "error": "body must be a JSON object"}, 400)

    kind = (body.get("kind") or "").strip().lower()
    name = (body.get("name") or "").strip()
    if not kind:
        return response({"ok": False, "error": "missing 'kind'"}, 400)
    if not name and kind != "auth":
        return response({"ok": False, "error": "missing 'name'"}, 400)

    # Guard against path traversal / shell-metacharacter injection in
    # the name — generator functions pass it into file paths.
    import re
    if not re.match(r"^[A-Za-z][A-Za-z0-9_\-]*$", name):
        return response({"ok": False, "error": "name must match [A-Za-z][A-Za-z0-9_-]*"}, 400)

    generator_map = {
        "route":      "generate_route",
        "model":      "generate_model",
        "migration":  "generate_migration",
        "middleware": "generate_middleware",
    }
    fn_name = generator_map.get(kind)
    if fn_name is None:
        return response({"ok": False, "error": f"unknown scaffold kind: {kind}"}, 400)

    try:
        from tina4_python import cli as cli_module
        fn = getattr(cli_module, fn_name, None)
        if fn is None:
            # Fall back to shelling out — keeps the endpoint useful
            # even if the generator function names drift.
            import subprocess
            cp = subprocess.run(
                ["tina4python", "generate", kind, name],
                capture_output=True, text=True, timeout=30,
            )
            if cp.returncode != 0:
                return response({"ok": False, "error": cp.stderr.strip() or cp.stdout.strip()}, 500)
            return response({"ok": True, "output": cp.stdout.strip()})

        # Invoke the generator directly. The CLI functions typically
        # print to stdout + write files; we don't capture their
        # output here — the file tree will refresh and show the new
        # files, which is what the user actually cares about.
        result = fn(name) if fn.__code__.co_argcount == 1 else fn(name, None)

        # Most generators return a path or list of paths; normalise.
        files: list[str] = []
        if isinstance(result, str):
            files = [result]
        elif isinstance(result, list):
            files = [str(p) for p in result]
        return response({"ok": True, "kind": kind, "name": name, "files": files})
    except Exception as exc:
        return response({"ok": False, "error": str(exc)}, 500)


# ─── Run-chip endpoints (migrate / test / seed-all) ────────────────
#
# Project-level operations the dev-admin SPA's ▶ Migrate / ▶ Test /
# ▶ Seed chips fire. Distinct from /scaffold/run (creates one file) and
# /seed (seeds one named table): these run the whole-project operation
# via the framework's own in-process machinery — the same code paths
# the CLI drives — rather than shelling out redundantly. Response shapes
# match the shared dev-admin SPA (and the Node dev-admin reference).


def _migration_stem(filename: str) -> str:
    """'000001_create_users.sql' → '000001_create_users' (drop the suffix)."""
    return Path(filename).stem


async def _api_migrate(request, response):
    """POST /__dev/api/migrate — apply pending migrations.

    Reuses the exact runner the CLI's ``_migrate`` and the ``_api_tool``
    'migrate' tool drive (``tina4_python.migration.Migration.migrate``),
    but in-process so we can report the split result the SPA reads:

        {applied: [...], skipped: [...], failed: [...]}

    - applied: migration ids run during this call
    - skipped: migration ids already applied before this call
    - failed:  a migration that raised — the runner stops and rolls back
               at the first failure, so at most one lands here
    """
    import re

    from tina4_python.database import Database
    from tina4_python.migration import Migration

    body = request.body if hasattr(request, "body") and request.body else {}
    mig_dir = body.get("dir", "migrations") if isinstance(body, dict) else "migrations"
    db_url = os.environ.get("TINA4_DATABASE_URL", "sqlite:///data/app.db")
    db = Database(db_url)
    try:
        mig = Migration(db, mig_dir)
        completed_before = {m["migration_name"] for m in mig.status()["completed"]}
        applied: list[str] = []
        failed: list[str] = []
        try:
            ran = mig.migrate()  # list of applied filenames
            applied = [_migration_stem(f) for f in ran]
        except Exception as e:
            # The runner rolls back + re-raises at the first failing
            # migration. Recover what actually got applied from the
            # tracking table, and pull the failed file out of the message
            # ("Migration failed: <file> — <err>").
            completed_after = {m["migration_name"] for m in mig.status()["completed"]}
            applied = sorted(completed_after - completed_before)
            msg = str(e)
            match = re.search(r"Migration failed:\s*([^\s—]+)", msg)
            failed = [_migration_stem(match.group(1))] if match else [msg]
        skipped = sorted(completed_before)
        MessageLog.log(
            "migrate", f"Applied {len(applied)} migration(s)",
            {"applied": applied, "failed": failed},
        )
        return response({"applied": applied, "skipped": skipped, "failed": failed})
    finally:
        db.close()


async def _api_test(request, response):
    """POST /__dev/api/test — run the project's pytest suite.

    Returns ``{ok, code, output}`` where ``code`` is the pytest process
    exit code and ``output`` is the combined stdout+stderr. A non-zero
    exit (failing tests) is a valid, reportable result — NOT a 500 —
    mirroring the ``_api_tool`` 'test' invocation but in the SPA's chip
    shape.
    """
    import subprocess
    import sys

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=short"],
            capture_output=True, text=True, timeout=180, cwd=os.getcwd(),
        )
        output = result.stdout or ""
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        MessageLog.log("test", f"pytest exited {result.returncode}",
                       {"code": result.returncode})
        return response({
            "ok": result.returncode == 0,
            "code": result.returncode,
            "output": output.strip(),
        })
    except subprocess.TimeoutExpired:
        return response({"ok": False, "code": -1,
                         "output": "Test suite timed out after 180 seconds"})
    except Exception as e:
        return response({"ok": False, "error": str(e)}, 500)


def _discover_orm_models() -> list:
    """Import ORM model modules from ``src/orm/`` (then ``src/models/`` as
    a fallback) and return the discovered ORM subclasses.

    Same directories the server discovers on startup; importing the
    modules ensures the classes are registered as ORM subclasses even if
    nothing has referenced them yet this process. Mirrors the import
    strategy in ``AutoCrud.discover``.
    """
    import importlib
    import importlib.util
    import inspect
    import sys

    from tina4_python.orm import ORM

    seen: set[int] = set()
    classes: list = []
    for models_dir in ("src/orm", "src/models"):
        if not os.path.isdir(models_dir):
            continue
        abs_dir = os.path.abspath(models_dir)
        parent = os.path.dirname(abs_dir)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        module_prefix = f"{os.path.basename(parent)}.{os.path.basename(abs_dir)}"
        for filename in sorted(os.listdir(models_dir)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue
            module_name = filename[:-3]
            try:
                mod = importlib.import_module(f"{module_prefix}.{module_name}")
            except Exception:
                try:
                    spec = importlib.util.spec_from_file_location(
                        module_name, os.path.join(abs_dir, filename))
                    if spec is None or spec.loader is None:
                        continue
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = mod
                    spec.loader.exec_module(mod)
                except Exception:
                    continue
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (inspect.isclass(attr) and issubclass(attr, ORM)
                        and attr is not ORM and id(attr) not in seen):
                    try:
                        has_table = bool(attr._get_table())
                    except Exception:
                        has_table = False
                    if has_table:
                        seen.add(id(attr))
                        classes.append(attr)
    return classes


async def _api_seed_run(request, response):
    """POST /__dev/api/seed/run — run the whole-project seeder.

    Distinct from ``/__dev/api/seed`` (which seeds one named table): this
    discovers every ORM model in ``src/orm/`` (``src/models/`` fallback)
    and seeds them all via the framework's FK-ordered ``seed_models()`` —
    the same real seeder the CLI uses. Returns ``{seeded, failed}``.
    """
    from tina4_python.seeder import seed_models

    body = request.body if hasattr(request, "body") and request.body else {}
    count = 10
    if isinstance(body, dict) and body.get("count") is not None:
        try:
            count = int(body.get("count"))
        except (TypeError, ValueError):
            count = 10

    try:
        classes = _discover_orm_models()
        if not classes:
            return response(
                {"seeded": 0, "failed": 0,
                 "error": "No models found in src/orm/ or src/models/"}, 400)
        summaries = seed_models(classes, count)
        seeded = 0
        failed = 0
        for summary in summaries.values():
            seeded += getattr(summary, "seeded", 0)
            failed += getattr(summary, "failed", 0)
        MessageLog.log(
            "seed", f"Seeded {seeded} rows across {len(summaries)} model(s)",
            {"seeded": seeded, "failed": failed},
        )
        return response({"seeded": seeded, "failed": failed})
    except Exception as e:
        return response({"seeded": 0, "failed": 0, "error": str(e)}, 500)


# ─── Framework-grounding (mcp.tina4.com) token config ──────────────
#
# Self-contained: reads/writes TINA4_MCP_TOKEN in the process env and
# the project .env directly. The Node dev-admin proxies these to the
# Rust agent (/mcp/status, /mcp/token); Python keeps them local so the
# token panel works with a bare `tina4 serve` — no agent required.

_MCP_DEFAULT_URL = "https://mcp.tina4.com"


def _env_file_values() -> dict:
    """Parse the project ``.env`` into a plain dict (best-effort).

    Missing file or read error → ``{}``. Strips surrounding quotes so a
    quoted value round-trips to the same string the process env would hold.
    """
    values: dict = {}
    env_path = Path(".env")
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                key, _, val = s.partition("=")
                values[key.strip()] = val.strip().strip('"').strip("'")
        except OSError:
            pass
    return values


def _resolve_env(key: str, default: str = "") -> str:
    """Resolve an env var: process environment first, then project ``.env``."""
    val = os.environ.get(key)
    if val:
        return val
    return _env_file_values().get(key, default)


def _upsert_env_var(key: str, value: str) -> None:
    """Write/upsert ``KEY=value`` into the project ``.env``.

    An empty ``value`` removes the key entirely (clear). Preserves
    comments, other keys, and a trailing newline. Mirrors the .env-write
    pattern in ``_api_connections_save``.
    """
    env_path = Path(".env")
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    out: list[str] = []
    found = False
    for line in lines:
        s = line.strip()
        if s.startswith("#") or "=" not in s:
            out.append(line)
            continue
        k = s.split("=", 1)[0].strip()
        if k == key:
            found = True
            if value:
                out.append(f"{key}={value}")
            # empty value → drop the line (clear)
        else:
            out.append(line)
    if value and not found:
        out.append(f"{key}={value}")
    content = "\n".join(out)
    if content and not content.endswith("\n"):
        content += "\n"
    env_path.write_text(content, encoding="utf-8")


def _grounding_snapshot() -> dict:
    token = _resolve_env("TINA4_MCP_TOKEN", "")
    url = _resolve_env("TINA4_MCP_URL", "") or _MCP_DEFAULT_URL
    # source: the developer's own token → "personal"; otherwise the coder runs
    # on the shared FREE-TOKEN trial the Rust agent falls back to → "free",
    # which drives the panel's "register for your own" nudge. (Disabling the
    # free rung is an agent-side concern; the panel always advertises the trial
    # when no personal token is set.)
    source = "personal" if token else "free"
    return {
        "configured": bool(token),
        "source": source,
        "last4": token[-4:] if token else "",
        "url": url,
    }


async def _api_grounding_status(request, response):
    """GET /__dev/api/grounding/status — framework-grounding token config.

    ``{configured, last4, url}``. ``configured`` = TINA4_MCP_TOKEN is set
    (process env or project .env). ``last4`` = last 4 chars of the token
    (or ""). ``url`` = TINA4_MCP_URL or the mcp.tina4.com default.
    """
    return response(_grounding_snapshot())


async def _api_grounding_token(request, response):
    """POST /__dev/api/grounding/token {token} — upsert TINA4_MCP_TOKEN.

    Writes the token into the project ``.env`` (empty token clears it) and
    updates the running process env so ``/status`` reflects the change
    immediately, before any restart re-reads ``.env``. Self-contained —
    never touches the Rust agent. Returns ``{ok, configured, last4}``.
    """
    body = request.body if hasattr(request, "body") and request.body else {}
    token = str(body.get("token") or "").strip() if isinstance(body, dict) else ""
    try:
        _upsert_env_var("TINA4_MCP_TOKEN", token)
    except OSError as e:
        return response({"ok": False, "error": str(e)}, 500)
    if token:
        os.environ["TINA4_MCP_TOKEN"] = token
    else:
        os.environ.pop("TINA4_MCP_TOKEN", None)
    MessageLog.log("grounding", "Updated TINA4_MCP_TOKEN",
                   {"configured": bool(token)})
    return response({"ok": True, "configured": bool(token),
                     "last4": token[-4:] if token else ""})


_DOCS_SINGLETON = None  # cached per-process so the framework index
                         # builds once. User portion still mtime-refreshes
                         # inside Docs.

def _docs_instance():
    """Lazy singleton for the Live Docs module — bound to the project
    cwd at first call. Subsequent calls reuse the same Docs instance,
    which keeps the framework index hot across requests while still
    refreshing the user portion when src/ files change."""
    global _DOCS_SINGLETON
    if _DOCS_SINGLETON is None:
        import os
        from tina4_python.docs import Docs
        _DOCS_SINGLETON = Docs(project_root=os.getcwd())
    return _DOCS_SINGLETON


async def _api_docs_search(request, response):
    """GET /__dev/api/docs/search?q=...&k=...&source=...&include_private=..."""
    q = (request.query.get("q") or "").strip() if hasattr(request, "query") else ""
    if not q:
        return response({"ok": False, "error": "missing required 'q' param"}, 400)
    try:
        k = int(request.query.get("k", 5))
    except (TypeError, ValueError):
        k = 5
    source = request.query.get("source", "all")
    include_private = (request.query.get("include_private", "")
                       or "").lower() in ("1", "true", "yes")
    import time
    t0 = time.perf_counter()
    hits = _docs_instance().search(q, k=k, source=source, include_private=include_private)
    took_ms = int((time.perf_counter() - t0) * 1000)
    return response({"ok": True, "query": q, "results": hits, "took_ms": took_ms})


async def _api_docs_class(request, response):
    """GET /__dev/api/docs/class?name=<fqn>"""
    name = (request.query.get("name") or "").strip()
    if not name:
        return response({"ok": False, "error": "missing required 'name' param"}, 400)
    spec = _docs_instance().class_spec(name)
    if spec is None:
        return response({"ok": False, "error": f"class not found: {name}"}, 404)
    return response({"ok": True, "class": spec})


async def _api_docs_method(request, response):
    """GET /__dev/api/docs/method?class=<fqn>&name=<method>"""
    cls = (request.query.get("class") or "").strip()
    name = (request.query.get("name") or "").strip()
    if not cls or not name:
        return response({"ok": False, "error": "both 'class' and 'name' params are required"}, 400)
    spec = _docs_instance().method_spec(cls, name)
    if spec is None:
        return response({"ok": False, "error": f"method not found: {cls}.{name}"}, 404)
    return response({"ok": True, "method": spec})


async def _api_docs_index(request, response):
    """GET /__dev/api/docs/index?source=<framework|user|all>"""
    source = request.query.get("source", "all")
    entities = _docs_instance().index()
    if source != "all":
        entities = [e for e in entities if e.get("source") == source]
    return response({"ok": True, "count": len(entities), "entities": entities})


async def _api_docs_well_known(request, response):
    """Public well-known doc — describes what the docs surface offers
    so non-MCP AI tools know what endpoints to call."""
    return response({
        "ok": True,
        "service": "tina4-live-docs",
        "version": "1",
        "endpoints": {
            "search": "/__dev/api/docs/search?q={query}&k={int}&source={framework|user|all}",
            "class":  "/__dev/api/docs/class?name={fqn}",
            "method": "/__dev/api/docs/method?class={fqn}&name={method}",
            "index":  "/__dev/api/docs/index?source={framework|user|all}",
        },
        "description": "Live API reflection for this Tina4 project — framework + user code combined.",
    })


__all__ = ["MessageLog", "RequestInspector", "BrokenTracker",
           "get_api_handlers", "render_dev_toolbar", "toolbar_css", "toolbar_js"]
