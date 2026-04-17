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
                existing = json.loads(filepath.read_text())
                existing["count"] = existing.get("count", 1) + 1
                existing["last_seen"] = datetime.now(timezone.utc).isoformat()
                filepath.write_text(json.dumps(existing, indent=2))
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
        filepath.write_text(json.dumps(entry, indent=2))
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
                entries.append(json.loads(f.read_text()))
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
            entry = json.loads(filepath.read_text())
            entry["resolved"] = True
            filepath.write_text(json.dumps(entry, indent=2))
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
                entry = json.loads(f.read_text())
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
        "/__dev/api/tool": ("POST", _api_tool),
        "/__dev/api/connections": ("GET", _api_connections),
        "/__dev/api/connections/test": ("POST", _api_connections_test),
        "/__dev/api/connections/save": ("POST", _api_connections_save),
        "/__dev/api/gallery": ("GET", _api_gallery_list),
        "/__dev/api/gallery/deploy": ("POST", _api_gallery_deploy),
        "/__dev/api/mtime": ("GET", _api_mtime),
        "/__dev/api/reload": ("POST", _api_reload),
        "/__dev/api/version-check": ("GET", _api_version_check),
        "/__dev/api/metrics": ("GET", _api_metrics),
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
    status = {
        "python_version": sys.version,
        "framework": "tina4-python v3",
        "debug": os.environ.get("TINA4_DEBUG", "false"),
        "log_level": os.environ.get("TINA4_LOG_LEVEL", "ERROR"),
        "database": os.environ.get("DATABASE_URL", "not configured"),
        "db_tables": db_table_count,
        "mailbox": mailbox.count(),
        "messages": MessageLog.count(),
        "requests": RequestInspector.stats(),
        "health": BrokenTracker.health(),
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


async def _api_queue_topics(request, response):
    """List available queue topics by scanning the queue data directory."""
    try:
        queue_dir = os.path.join(os.getcwd(), "data", "queue")
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
        from tina4_python.queue import Queue
        topic = request.params.get("topic", "default") if hasattr(request, "params") else "default"
        status_filter = request.params.get("status", None) if hasattr(request, "params") else None
        queue = Queue(topic=topic)

        # Stats
        stats = {
            "pending": queue.size("pending"),
            "completed": queue.size("completed"),
            "failed": queue.size("failed"),
            "reserved": queue.size("reserved"),
        }

        # Jobs by status — list pending by reading queue files directly
        jobs = []
        if status_filter == "pending" or not status_filter:
            queue_dir = os.path.join(os.getcwd(), "data", "queue", topic)
            if os.path.isdir(queue_dir):
                for filename in sorted(os.listdir(queue_dir)):
                    if filename.endswith(".queue-data"):
                        filepath = os.path.join(queue_dir, filename)
                        try:
                            with open(filepath, "r") as fh:
                                job = json.load(fh)
                                job["status"] = "pending"
                                jobs.append(job)
                        except Exception:
                            pass
        if status_filter == "failed" or not status_filter:
            for j in queue.failed():
                j["status"] = "failed"
                jobs.append(j)
        if status_filter == "dead" or not status_filter:
            for j in queue.dead_letters():
                j["status"] = "dead_letter"
                jobs.append(j)

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
    """List dead letter queue jobs (exceeded max retries)."""
    try:
        from tina4_python.queue import Queue
        topic = request.params.get("topic", "default") if hasattr(request, "params") else "default"
        queue = Queue(topic=topic)
        jobs = queue.dead_letters()
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
    folder = request.params.get("folder", None) if hasattr(request, "params") else None
    limit = int(request.params.get("limit", "50")) if hasattr(request, "params") else 50
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
    msg_id = request.params.get("id", "") if hasattr(request, "params") else ""
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
    category = request.params.get("category", None) if hasattr(request, "params") else None
    level = request.params.get("level", None) if hasattr(request, "params") else None
    limit = int(request.params.get("limit", "100")) if hasattr(request, "params") else 100
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
        db_url = os.environ.get("DATABASE_URL", "sqlite:///data/app.db")
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
                result = db.execute(stmt)
                if result is False:
                    raise RuntimeError(f"Statement failed: {stmt[:80]}")
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
        db_url = os.environ.get("DATABASE_URL", "sqlite:///data/app.db")
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
        table = request.params.get("name", "") if hasattr(request, "params") else ""
        if not table:
            return response({"error": "name required"}, 400)

        db_url = os.environ.get("DATABASE_URL", "sqlite:///data/app.db")
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
        db_url = os.environ.get("DATABASE_URL", "sqlite:///data/app.db")
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
    keyword = request.params.get("q", "") if hasattr(request, "params") else ""
    category = request.params.get("category", None) if hasattr(request, "params") else None
    limit = int(request.params.get("limit", "100")) if hasattr(request, "params") else 100

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
        from tina4_python.seeder import FakeData

        body = request.body if hasattr(request, "body") and request.body else {}
        table = body.get("table", "")
        count = int(body.get("count", 10))

        if not table:
            return response({"error": "table required"}, 400)
        if count > 1000:
            count = 1000

        db_url = os.environ.get("DATABASE_URL", "sqlite:///data/app.db")
        db = Database(db_url)

        # Get table columns to auto-generate data
        columns = db.get_columns(table)
        if not columns:
            db.close()
            return response({"error": f"Table '{table}' not found or has no columns"}, 404)

        fake = FakeData(seed=42)
        inserted = 0

        for _ in range(count):
            row = {}
            for col in columns:
                name = col.get("name", col.get("column_name", ""))
                col_type = col.get("type", col.get("data_type", "")).upper()
                is_pk = col.get("primary_key", col.get("pk", False))

                # Skip auto-increment PKs
                if is_pk and ("AUTO" in col_type or "SERIAL" in col_type or
                              name.lower() == "id"):
                    continue

                # Generate fake data based on column name and type
                name_lower = name.lower()
                if "email" in name_lower:
                    row[name] = fake.email()
                elif "name" in name_lower and "user" in name_lower:
                    row[name] = fake.name()
                elif "first" in name_lower and "name" in name_lower:
                    row[name] = fake.first_name()
                elif "last" in name_lower and "name" in name_lower:
                    row[name] = fake.last_name()
                elif "name" in name_lower:
                    row[name] = fake.name()
                elif "phone" in name_lower or "tel" in name_lower:
                    row[name] = fake.phone()
                elif "url" in name_lower or "link" in name_lower:
                    row[name] = fake.url()
                elif "address" in name_lower:
                    row[name] = fake.address()
                elif "date" in name_lower or "time" in name_lower or "created" in name_lower:
                    row[name] = fake.datetime_iso()
                elif "desc" in name_lower or "body" in name_lower or "content" in name_lower:
                    row[name] = fake.paragraph()
                elif "title" in name_lower or "subject" in name_lower:
                    row[name] = fake.sentence()
                elif "active" in name_lower or "enabled" in name_lower or "done" in name_lower:
                    row[name] = fake.boolean()
                elif "INT" in col_type or "SERIAL" in col_type:
                    row[name] = fake.integer(1, 10000)
                elif "REAL" in col_type or "FLOAT" in col_type or "DOUBLE" in col_type or "NUMERIC" in col_type or "DECIMAL" in col_type:
                    row[name] = fake.decimal(0, 1000)
                elif "BOOL" in col_type:
                    row[name] = fake.boolean()
                else:
                    row[name] = fake.sentence()

            if row:
                db.insert(table, row)
                inserted += 1

        db.commit()
        db.close()
        MessageLog.log("seed", f"Seeded {inserted} rows into '{table}'", {"table": table, "count": inserted})
        return response({"seeded": inserted, "table": table})
    except Exception as e:
        return response({"error": str(e)}, 500)


async def _api_requests(request, response):
    """Get captured HTTP requests."""
    limit = int(request.params.get("limit", "50")) if hasattr(request, "params") else 50
    method = request.params.get("method", None) if hasattr(request, "params") else None
    status_min = request.params.get("status_min", None) if hasattr(request, "params") else None
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
    """Clear resolved errors."""
    BrokenTracker.clear_resolved()
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
        "database": os.environ.get("DATABASE_URL", "not configured"),
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
        db_url = os.environ.get("DATABASE_URL", "")
        if db_url:
            db = Database(db_url)
            tables = db.get_tables()
            info["db_tables"] = len(tables)
            info["db_connected"] = True
            db.close()
        else:
            info["db_connected"] = False
    except Exception:
        info["db_connected"] = False

    # Loaded modules count
    info["loaded_modules"] = len([m for m in sys.modules if m.startswith("tina4_python")])

    return response(info)


async def _api_chat(request, response):
    """Tina4 — AI chat powered by LLM API."""
    body = request.body if hasattr(request, "body") and request.body else {}
    message = body.get("message", "").strip()
    provider = body.get("provider", "anthropic")

    if not message:
        return response({"error": "message required"}, 400)

    # Check for API keys — runtime key takes priority over env
    runtime_key = body.get("api_key", "")
    if runtime_key:
        if provider == "anthropic":
            os.environ["ANTHROPIC_API_KEY"] = runtime_key
        else:
            os.environ["OPENAI_API_KEY"] = runtime_key

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    if not api_key:
        # Fallback: helpful response without LLM
        return response({
            "reply": _tina4_robot_fallback(message),
            "source": "local",
        })

    try:
        import urllib.request
        import urllib.error

        if os.environ.get("ANTHROPIC_API_KEY"):
            # Claude API
            req_data = json.dumps({
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1024,
                "system": "You are Tina4, a helpful assistant embedded in the Tina4 web framework dev admin. You help developers with Tina4 Python framework questions, debugging, and code generation. Be concise and practical. When asked about Tina4 features, reference the built-in modules: Router, ORM, Database, Queue, Auth, Template (Frond), GraphQL, WebSocket, WSDL, Messenger, SCSS, Seeder, Migration, i18n, Api, Session, Swagger, DevAdmin.",
                "messages": [{"role": "user", "content": message}],
            }).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=req_data,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                    "anthropic-version": "2023-06-01",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                reply = result.get("content", [{}])[0].get("text", "No response")
                return response({"reply": reply, "source": "claude"})

        elif os.environ.get("OPENAI_API_KEY"):
            # OpenAI API
            req_data = json.dumps({
                "model": "gpt-4o-mini",
                "max_tokens": 1024,
                "messages": [
                    {"role": "system", "content": "You are Tina4, a helpful assistant embedded in the Tina4 web framework dev admin."},
                    {"role": "user", "content": message},
                ],
            }).encode()
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=req_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                reply = result["choices"][0]["message"]["content"]
                return response({"reply": reply, "source": "openai"})

    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        return response({"reply": f"API error: {e.code} — {error_body[:200]}", "source": "error"})
    except Exception as e:
        return response({"reply": f"Error: {str(e)}", "source": "error"})

    return response({"reply": _tina4_robot_fallback(message), "source": "local"})


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
        return "Set DATABASE_URL in .env. Supports sqlite, postgres, mysql, firebird, mssql, mongodb. Use db.fetch(), db.insert(), db.update(), db.delete()."
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
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key == "DATABASE_URL":
                url = val
            elif key == "DATABASE_USERNAME":
                username = val
            elif key == "DATABASE_PASSWORD":
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
        from tina4_python.Database import Database
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
            lines = env_path.read_text().splitlines()
        keys_found = {"DATABASE_URL": False, "DATABASE_USERNAME": False, "DATABASE_PASSWORD": False}
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                new_lines.append(line)
                continue
            key = stripped.split("=", 1)[0].strip()
            if key == "DATABASE_URL":
                new_lines.append(f"DATABASE_URL={url}")
                keys_found["DATABASE_URL"] = True
            elif key == "DATABASE_USERNAME":
                new_lines.append(f"DATABASE_USERNAME={username}")
                keys_found["DATABASE_USERNAME"] = True
            elif key == "DATABASE_PASSWORD":
                new_lines.append(f"DATABASE_PASSWORD={password}")
                keys_found["DATABASE_PASSWORD"] = True
            else:
                new_lines.append(line)
        for key, found in keys_found.items():
            if not found:
                val = {"DATABASE_URL": url, "DATABASE_USERNAME": username, "DATABASE_PASSWORD": password}[key]
                new_lines.append(f"{key}={val}")
        env_path.write_text("\n".join(new_lines) + "\n")
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
                meta = json.loads(meta_file.read_text())
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

    Updates the mtime counter so the polling fallback detects the change.
    """
    import time
    _reload_mtime[0] = int(time.time())
    _reload_file[0] = (request.body or {}).get("file", "")
    reload_type = (request.body or {}).get("type", "reload")
    from tina4_python.debug import Log
    Log.info(f"External reload trigger: {reload_type}" + (f" ({_reload_file[0]})" if _reload_file[0] else ""))
    return response({"ok": True, "type": reload_type})


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


async def _api_metrics(request, response):
    """Quick metrics — instant file scan."""
    from tina4_python.dev_admin.metrics import quick_metrics
    return response(quick_metrics())


async def _api_metrics_full(request, response):
    """Full analysis — AST-based, cached 60s."""
    from tina4_python.dev_admin.metrics import full_analysis
    return response(full_analysis())


async def _api_metrics_file(request, response):
    """Per-file detail metrics."""
    from tina4_python.dev_admin.metrics import file_detail
    path = request.params.get("path", "")
    if not path:
        return response({"error": "Missing path parameter"}, 400)
    return response(file_detail(path))


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
    """
    import sys
    from tina4_python.core.server import _ai_port_ctx
    python_version = sys.version.split()[0]
    poll_interval_ms = int(os.environ.get("TINA4_DEV_POLL_INTERVAL", "3000"))
    no_reload = os.environ.get("TINA4_NO_RELOAD", "").lower() in ("true", "1", "yes") or _ai_port_ctx.get()

    return f"""<div id="tina4-dev-toolbar" style="position:fixed;bottom:0;left:0;right:0;background:#333;color:#fff;font-family:monospace;font-size:12px;padding:6px 16px;z-index:99999;display:flex;align-items:center;gap:16px;">
    <span id="tina4-ver-btn" style="color:#3572A5;font-weight:bold;cursor:pointer;text-decoration:underline dotted;" onclick="tina4VersionModal()" title="Click to check for updates">Tina4 v{__version__}</span>
    <div id="tina4-ver-modal" style="display:none;position:fixed;bottom:3rem;left:1rem;background:#1e1e2e;border:1px solid #3572A5;border-radius:8px;padding:16px 20px;z-index:100000;min-width:320px;box-shadow:0 8px 32px rgba(0,0,0,0.5);font-family:monospace;font-size:13px;color:#cdd6f4;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <strong style="color:#89b4fa;">Version Info</strong>
        <span onclick="document.getElementById('tina4-ver-modal').style.display='none'" style="cursor:pointer;color:#888;">&times;</span>
      </div>
      <div id="tina4-ver-body" style="line-height:1.8;">
        <div>Current: <strong style="color:#a6e3a1;">v{__version__}</strong></div>
        <div id="tina4-ver-latest" style="color:#888;">Checking for updates...</div>
      </div>
    </div>
    <span style="color:#4caf50;">{method}</span>
    <span>{path}</span>
    <span style="color:#666;">&rarr; {matched_pattern}</span>
    <span style="color:#ffeb3b;">req:{request_id}</span>
    <span style="color:#90caf9;">{route_count} routes</span>
    <span style="color:#888;">Python {python_version}</span>
    <a href="#" onclick="(function(e){{e.preventDefault();var p=document.getElementById('tina4-dev-panel');if(p){{p.style.display=p.style.display==='none'?'block':'none';return;}}var c=document.createElement('div');c.id='tina4-dev-panel';c.style.cssText='position:fixed;top:3rem;left:0;right:0;bottom:2rem;z-index:99998;transition:all 0.2s';var f=document.createElement('iframe');f.src='/__dev';f.style.cssText='width:100%;height:100%;border:1px solid #3572A5;border-radius:0.5rem;box-shadow:0 8px 32px rgba(0,0,0,0.5);background:#0f172a';c.appendChild(f);document.body.appendChild(c);}})(event)" style="color:#ef9a9a;margin-left:auto;text-decoration:none;cursor:pointer;">Dashboard &#8599;</a>
    <span onclick="this.parentElement.style.display='none'" style="cursor:pointer;color:#888;margin-left:8px;">&#10005;</span>
</div>
<script>
{'(function(){})();' if no_reload else f"""(function(){{
    var _t4_mtime=0,_t4_css_exts=['.css','.scss'],_t4_debounce=null;
    var _t4_interval=parseInt('{poll_interval_ms}')||3000;
    function _t4_apply(d){{
        var f=d.file||'';
        var isCss=_t4_css_exts.some(function(e){{return f.endsWith(e)}});
        if(isCss){{
            var links=document.querySelectorAll('link[rel="stylesheet"]');
            links.forEach(function(l){{
                var href=l.getAttribute('href');
                if(href){{l.setAttribute('href',href.split('?')[0]+'?_t4='+d.mtime)}}
            }});
        }}else{{
            location.reload();
        }}
    }}
    function _t4_poll(){{
        fetch('/__dev/api/mtime').then(function(r){{return r.json()}}).then(function(d){{
            if(!_t4_mtime){{_t4_mtime=d.mtime;return;}}
            if(d.mtime>_t4_mtime){{
                _t4_mtime=d.mtime;
                if(_t4_debounce)clearTimeout(_t4_debounce);
                _t4_debounce=setTimeout(function(){{_t4_apply(d);}},500);
            }}
        }}).catch(function(){{}});
    }}
    setInterval(_t4_poll,_t4_interval);
}})();"""}
function tina4VersionModal(){{
    var m=document.getElementById('tina4-ver-modal');
    if(m.style.display==='block'){{m.style.display='none';return;}}
    m.style.display='block';
    var el=document.getElementById('tina4-ver-latest');
    el.innerHTML='Checking for updates...';
    el.style.color='#888';
    fetch('/__dev/api/version-check')
    .then(function(r){{return r.json()}})
    .then(function(d){{
        var latest=d.latest;
        var current=d.current;
        if(latest===current){{
            el.innerHTML='Latest: <strong style="color:#a6e3a1;">v'+latest+'</strong> &mdash; You are up to date!';
            el.style.color='#a6e3a1';
        }}else{{
            var cParts=current.split('.').map(Number);
            var lParts=latest.split('.').map(Number);
            var isNewer=false;
            for(var i=0;i<Math.max(cParts.length,lParts.length);i++){{
                var c=cParts[i]||0,l=lParts[i]||0;
                if(l>c){{isNewer=true;break;}}
                if(l<c)break;
            }}
            var isAhead=false;
            if(!isNewer){{
                for(var i=0;i<Math.max(cParts.length,lParts.length);i++){{
                    var c2=cParts[i]||0,l2=lParts[i]||0;
                    if(c2>l2){{isAhead=true;break;}}
                    if(c2<l2)break;
                }}
            }}
            if(isNewer){{
                var breaking=(lParts[0]!==cParts[0]||lParts[1]!==cParts[1]);
                el.innerHTML='Latest: <strong style="color:#f9e2af;">v'+latest+'</strong>';
                if(breaking){{
                    el.innerHTML+='<div style="color:#f38ba8;margin-top:6px;">&#9888; Major/minor version change &mdash; check the <a href="https://github.com/tina4stack/tina4-python/releases" target="_blank" style="color:#89b4fa;">changelog</a> for breaking changes before upgrading.</div>';
                }}else{{
                    el.innerHTML+='<div style="color:#f9e2af;margin-top:6px;">Patch update available. Run: <code style="background:#313244;padding:2px 6px;border-radius:3px;">pip install --upgrade tina4-python</code></div>';
                }}
            }}else if(isAhead){{
                el.innerHTML='You are running <strong style="color:#cba6f7;">v'+current+'</strong> (ahead of PyPI <strong>v'+latest+'</strong> &mdash; not yet published).';
                el.style.color='#cba6f7';
            }}else{{
                el.innerHTML='Latest: <strong style="color:#a6e3a1;">v'+latest+'</strong> &mdash; You are up to date!';
                el.style.color='#a6e3a1';
            }}
        }}
    }})
    .catch(function(){{
        el.innerHTML='Could not check for updates (offline?)';
        el.style.color='#f38ba8';
    }});
}}
</script>"""


# ── Editor API endpoints ──────────────────────────────────────

async def _api_files(request, response):
    """List files in a directory with git status.

    Query params:
        path — relative directory path (default: project root)
    """
    import os, subprocess
    rel = (request.params.get("path") or "").strip("/")
    base = os.getcwd()
    target = os.path.normpath(os.path.join(base, rel))

    # Security: must stay within project root
    if not target.startswith(base):
        return response({"error": "Path outside project"}, 403)

    if not os.path.isdir(target):
        return response({"error": "Not a directory"}, 404)

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

            # Skip hidden dirs and noise
            if name.startswith(".") and name not in (".env", ".env.example"):
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
    """
    import os
    rel = (request.params.get("path") or "").strip("/")
    if not rel:
        return response({"error": "path required"}, 400)

    base = os.getcwd()
    target = os.path.normpath(os.path.join(base, rel))

    if not target.startswith(base):
        return response({"error": "Path outside project"}, 403)

    if not os.path.isfile(target):
        return response({"error": "File not found"}, 404)

    # Size guard: don't load huge files into JSON
    size = os.path.getsize(target)
    if size > 2 * 1024 * 1024:  # 2MB
        return response({"error": "File too large", "size": size}, 413)

    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return response({"error": str(e)}, 500)

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
    rel = (request.params.get("path") or "").strip("/")
    if not rel:
        return response({"error": "path required"}, 400)

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

    from tina4_python.core.response import Response
    Response.add_header("Content-Type", content_type)
    Response.add_header("Cache-Control", "no-cache")
    # Return raw bytes — the response handler will detect binary
    import base64
    return response({
        "_raw": True,
        "data": base64.b64encode(data).decode("ascii"),
        "content_type": content_type,
        "size": size,
    })


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
    query = request.params.get("q", "").strip()
    registry = request.params.get("registry", "pypi")
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

    if not name:
        return response({"error": "name required"}, 400)

    try:
        if registry == "pypi":
            pkg = f"{name}>={version}" if version else name
            result = subprocess.run(
                ["pip", "install", pkg],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                return response({"error": result.stderr.strip()}, 500)
            return response({"message": f"Installed {name} {version}".strip(), "output": result.stdout})

        elif registry == "npm":
            pkg = f"{name}@{version}" if version else name
            result = subprocess.run(
                ["npm", "install", pkg],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                return response({"error": result.stderr.strip()}, 500)
            return response({"message": f"Installed {name}", "output": result.stdout})

        elif registry == "packagist":
            pkg = f"{name}:{version}" if version else name
            result = subprocess.run(
                ["composer", "require", pkg],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                return response({"error": result.stderr.strip()}, 500)
            return response({"message": f"Installed {name}", "output": result.stdout})

        elif registry == "rubygems":
            result = subprocess.run(
                ["gem", "install", name, "-v", version] if version else ["gem", "install", name],
                capture_output=True, text=True, timeout=60
            )
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


__all__ = ["MessageLog", "RequestInspector", "BrokenTracker",
           "get_api_handlers", "render_dev_toolbar"]
