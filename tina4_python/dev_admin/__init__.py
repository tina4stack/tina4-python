# Tina4 Dev Admin — Built-in development dashboard, zero dependencies.
"""
Auto-registered admin panel for development mode (TINA4_DEBUG_LEVEL=DEBUG).
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


def get_api_handlers() -> dict:
    """Return dev admin API handler functions keyed by path.

    These are registered as routes when the server starts in dev mode.
    Returns dict of {path: (method, handler)} tuples.
    """
    return {
        "/__dev/api/status": ("GET", _api_status),
        "/__dev/api/routes": ("GET", _api_routes),
        "/__dev/api/queue": ("GET", _api_queue),
        "/__dev/api/queue/retry": ("POST", _api_queue_retry),
        "/__dev/api/queue/purge": ("POST", _api_queue_purge),
        "/__dev/api/queue/replay": ("POST", _api_queue_replay),
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
    }


async def _api_status(request, response):
    """System status overview."""
    import sys
    from tina4_python.messenger import DevMailbox

    mailbox = DevMailbox()
    status = {
        "python_version": sys.version,
        "framework": "tina4-python v3",
        "debug_level": os.environ.get("TINA4_DEBUG_LEVEL", ""),
        "database": os.environ.get("DATABASE_URL", "not configured"),
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
        routes = Router.all()
        result = []
        for r in routes:
            result.append({
                "method": r.get("method", "GET"),
                "path": r.get("path", ""),
                "auth_required": r.get("auth_required", False),
                "handler": r["handler"].__name__ if r.get("handler") else "?",
                "module": r["handler"].__module__ if r.get("handler") else "?",
            })
        return response({"routes": result, "count": len(result)})
    except Exception as e:
        return response({"routes": [], "count": 0, "error": str(e)})


async def _api_queue(request, response):
    """Queue status and jobs."""
    try:
        from tina4_python.database import Database
        db_url = os.environ.get("DATABASE_URL", "sqlite:///data/app.db")
        db = Database(db_url)

        if not db.table_exists("tina4_queue"):
            db.close()
            return response({"jobs": [], "stats": {"pending": 0, "completed": 0, "failed": 0, "reserved": 0}})

        status_filter = request.params.get("status", None) if hasattr(request, "params") else None
        topic = request.params.get("topic", None) if hasattr(request, "params") else None
        limit = int(request.params.get("limit", "50")) if hasattr(request, "params") else 50

        # Stats
        stats = {}
        for s in ["pending", "completed", "failed", "reserved"]:
            row = db.fetch_one(
                "SELECT COUNT(*) as cnt FROM tina4_queue WHERE status = ?", [s]
            )
            stats[s] = row["cnt"] if row else 0

        # Jobs
        sql = "SELECT * FROM tina4_queue"
        params = []
        conditions = []
        if status_filter:
            conditions.append("status = ?")
            params.append(status_filter)
        if topic:
            conditions.append("topic = ?")
            params.append(topic)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY id DESC"

        result = db.fetch(sql, params, limit=limit)
        jobs = []
        for row in result.records:
            job = dict(row)
            # Parse data JSON
            if isinstance(job.get("data"), str):
                try:
                    job["data"] = json.loads(job["data"])
                except (json.JSONDecodeError, TypeError):
                    pass
            jobs.append(job)

        db.close()
        return response({"jobs": jobs, "stats": stats})
    except Exception as e:
        return response({"jobs": [], "stats": {}, "error": str(e)})


async def _api_queue_retry(request, response):
    """Retry failed queue jobs."""
    try:
        from tina4_python.database import Database
        from tina4_python.queue import Queue
        db_url = os.environ.get("DATABASE_URL", "sqlite:///data/app.db")
        db = Database(db_url)
        topic = request.body.get("topic", "default") if hasattr(request, "body") and request.body else "default"
        queue = Queue(db, topic=topic)
        retried = queue.retry_failed()
        db.close()
        MessageLog.log("queue", f"Retried {retried} failed jobs", {"topic": topic})
        return response({"retried": retried})
    except Exception as e:
        return response({"error": str(e)}, 500)


async def _api_queue_purge(request, response):
    """Purge completed queue jobs."""
    try:
        from tina4_python.database import Database
        from tina4_python.queue import Queue
        db_url = os.environ.get("DATABASE_URL", "sqlite:///data/app.db")
        db = Database(db_url)
        topic = request.body.get("topic", "default") if hasattr(request, "body") and request.body else "default"
        status = request.body.get("status", "completed") if hasattr(request, "body") and request.body else "completed"
        queue = Queue(db, topic=topic)
        queue.purge(status=status)
        db.close()
        MessageLog.log("queue", f"Purged {status} jobs", {"topic": topic})
        return response({"purged": True})
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
                gql = GraphQL()
                result = gql.execute(query, variables=body.get("variables", {}))
                MessageLog.log("query", f"GraphQL: {query[:80]}", level="info")
                return response(result)
            except Exception as e:
                return response({"error": str(e)}, 400)

        # SQL query
        from tina4_python.database import Database
        db_url = os.environ.get("DATABASE_URL", "sqlite:///data/app.db")
        db = Database(db_url)

        upper = query.upper().lstrip()
        is_read = upper.startswith("SELECT") or upper.startswith("PRAGMA") or upper.startswith("SHOW") or upper.startswith("DESCRIBE")

        if is_read:
            result = db.fetch(query, limit=100)
            data = result.records
            MessageLog.log("query", f"SQL: {query[:80]}", {"rows": result.count}, level="info")
            db.close()
            return response({"rows": data, "count": result.count})
        else:
            result = db.execute(query)
            db.commit()
            affected = result.affected_rows if hasattr(result, "affected_rows") else 0
            MessageLog.log("query", f"SQL: {query[:80]}", {"affected": affected}, level="warn")
            db.close()
            return response({"affected": affected, "success": True})

    except Exception as e:
        return response({"error": str(e)}, 400)


async def _api_tables(request, response):
    """List all database tables."""
    try:
        from tina4_python.database import Database
        db_url = os.environ.get("DATABASE_URL", "sqlite:///data/app.db")
        db = Database(db_url)
        tables = db.get_database_tables()
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
        columns = db.get_table_info(table)
        sample = db.fetch(f"SELECT * FROM {table}", limit=20)
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
        queue = Queue(db, topic=topic)
        new_id = queue.push(data)
        db.close()
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
        from tina4_python.seeder import Fake

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
        columns = db.get_table_info(table)
        if not columns:
            db.close()
            return response({"error": f"Table '{table}' not found or has no columns"}, 404)

        fake = Fake(seed=42)
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
        "debug_level": os.environ.get("TINA4_DEBUG_LEVEL", ""),
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
            tables = db.get_database_tables()
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
                   "[print(f\"{r['method']:7} {r['path']}\") for r in Router.all()]"],
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
        return "Use Queue(topic='name') + Producer to enqueue, Consumer to process. Supports litequeue, RabbitMQ, Kafka, MongoDB backends."
    elif "template" in msg or "twig" in msg:
        return "Templates use Jinja2/Twig syntax in src/templates/. Always extend base.twig. Use {% block %} for content, {% include %} for partials."
    elif "auth" in msg or "jwt" in msg:
        return "Set SECRET in .env. POST/PUT/DELETE require Bearer token by default. Use @noauth() to make public, @secured() to protect GET routes."
    elif "test" in msg:
        return "Write tests in tests/ using pytest. Run with 'tina4 test' or 'pytest tests/ -v'."
    elif "migrate" in msg or "migration" in msg:
        return "Create: 'tina4 migrate:create \"description\"'. Run: 'tina4 migrate'. Files go in migrations/ folder."
    elif "seed" in msg:
        return "Create seed files in src/seeds/. Use Fake() for data generation, seed_table() for bulk insert. Run with 'tina4 seed'."
    else:
        return "I'm Tina4! Ask me about routes, ORM, database, queues, templates, auth, tests, migrations, or seeding. Set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env for AI-powered answers."


# Module startup time for uptime tracking
_start_time = time.time()


def render_dashboard() -> str:
    """Render the dev admin dashboard HTML.

    Cross-language dashboard — same HTML/JS works across Python, PHP, Ruby, Node.js.
    Uses CSS variables from tina4css conventions. Entirely self-contained.
    """
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tina4 Dev Admin</title>
<style>
:root {
    --bg: #0f172a; --surface: #1e293b; --border: #334155;
    --text: #e2e8f0; --muted: #94a3b8; --primary: #3b82f6;
    --success: #22c55e; --danger: #ef4444; --warn: #f59e0b;
    --info: #06b6d4; --radius: 0.5rem;
    --mono: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    --font: system-ui, -apple-system, sans-serif;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: var(--font); background: var(--bg); color: var(--text); font-size: 0.875rem; }
.dev-header {
    background: var(--surface); border-bottom: 1px solid var(--border);
    padding: 0.75rem 1.5rem; display: flex; align-items: center; gap: 1rem;
}
.dev-header h1 { font-size: 1rem; font-weight: 600; }
.dev-header .badge {
    background: var(--primary); color: #fff; padding: 0.15rem 0.5rem;
    border-radius: 1rem; font-size: 0.7rem; font-weight: 600;
}
.dev-tabs {
    display: flex; gap: 0; background: var(--surface);
    border-bottom: 1px solid var(--border); overflow-x: auto;
}
.dev-tab {
    padding: 0.6rem 1rem; cursor: pointer; font-size: 0.8rem;
    border-bottom: 2px solid transparent; color: var(--muted);
    transition: all 0.15s; background: none; border-top: none;
    border-left: none; border-right: none; white-space: nowrap;
}
.dev-tab:hover { color: var(--text); }
.dev-tab.active { color: var(--primary); border-bottom-color: var(--primary); }
.dev-tab .count {
    background: var(--border); color: var(--muted); padding: 0.1rem 0.4rem;
    border-radius: 0.75rem; font-size: 0.65rem; margin-left: 0.25rem;
}
.dev-content { padding: 1rem; max-width: 1400px; }
.dev-panel {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); overflow: hidden;
}
.dev-panel-header {
    padding: 0.75rem 1rem; border-bottom: 1px solid var(--border);
    display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem;
}
.dev-panel-header h2 { font-size: 0.9rem; font-weight: 600; }
table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
th { text-align: left; padding: 0.5rem 0.75rem; color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); }
td { padding: 0.4rem 0.75rem; border-bottom: 1px solid var(--border); }
tr:hover { background: rgba(59, 130, 246, 0.05); }
.method { font-family: var(--mono); font-size: 0.7rem; font-weight: 700; }
.method-get { color: var(--success); }
.method-post { color: var(--primary); }
.method-put { color: var(--warn); }
.method-delete { color: var(--danger); }
.path { font-family: var(--mono); font-size: 0.75rem; }
.badge-pill {
    display: inline-block; padding: 0.1rem 0.5rem; border-radius: 1rem;
    font-size: 0.65rem; font-weight: 600; text-transform: uppercase;
}
.bg-pending { background: rgba(245,158,11,0.15); color: var(--warn); }
.bg-completed, .bg-success { background: rgba(34,197,94,0.15); color: var(--success); }
.bg-failed, .bg-danger { background: rgba(239,68,68,0.15); color: var(--danger); }
.bg-reserved, .bg-primary { background: rgba(59,130,246,0.15); color: var(--primary); }
.bg-info { background: rgba(6,182,212,0.15); color: var(--info); }
.btn {
    padding: 0.3rem 0.65rem; border: 1px solid var(--border); border-radius: var(--radius);
    background: var(--surface); color: var(--text); cursor: pointer; font-size: 0.75rem;
    transition: all 0.15s;
}
.btn:hover { border-color: var(--primary); color: var(--primary); }
.btn-primary { background: var(--primary); color: #fff; border-color: var(--primary); }
.btn-primary:hover { background: #2563eb; }
.btn-danger { border-color: var(--danger); color: var(--danger); }
.btn-danger:hover { background: rgba(239,68,68,0.1); }
.btn-success { border-color: var(--success); color: var(--success); }
.btn-sm { padding: 0.2rem 0.5rem; font-size: 0.7rem; }
.empty { padding: 2rem; text-align: center; color: var(--muted); }
.input {
    background: var(--bg); color: var(--text); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 0.35rem 0.5rem; font-size: 0.8rem;
    font-family: var(--font);
}
.input:focus { outline: none; border-color: var(--primary); }
.input-mono { font-family: var(--mono); }
select.input { padding: 0.3rem; }
textarea.input { resize: vertical; font-family: var(--mono); }
.flex { display: flex; }
.gap-sm { gap: 0.5rem; }
.gap-md { gap: 1rem; }
.items-center { align-items: center; }
.justify-between { justify-content: space-between; }
.flex-1 { flex: 1; }
.p-sm { padding: 0.5rem; }
.p-md { padding: 1rem; }
.mb-sm { margin-bottom: 0.5rem; }
.text-sm { font-size: 0.75rem; }
.text-muted { color: var(--muted); }
.text-mono { font-family: var(--mono); }
.mail-item { padding: 0.6rem 0.75rem; border-bottom: 1px solid var(--border); cursor: pointer; }
.mail-item:hover { background: rgba(59,130,246,0.05); }
.mail-item.unread { border-left: 3px solid var(--primary); }
.msg-entry { padding: 0.4rem 0.75rem; border-bottom: 1px solid var(--border); font-size: 0.75rem; }
.msg-entry .cat {
    font-family: var(--mono); font-size: 0.65rem; padding: 0.1rem 0.35rem;
    border-radius: 0.25rem; background: rgba(59,130,246,0.15); color: var(--primary);
}
.msg-entry .time { color: var(--muted); font-size: 0.7rem; font-family: var(--mono); }
.level-error { color: var(--danger); }
.level-warn { color: var(--warn); }
.toolbar { display: flex; gap: 0.5rem; padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); flex-wrap: wrap; align-items: center; }
.hidden { display: none; }
/* Chat panel */
.chat-container { display: flex; flex-direction: column; height: 500px; }
.chat-messages { flex: 1; overflow-y: auto; padding: 0.75rem; }
.chat-msg { margin-bottom: 0.75rem; padding: 0.5rem 0.75rem; border-radius: var(--radius); font-size: 0.8rem; max-width: 85%; }
.chat-user { background: var(--primary); color: #fff; margin-left: auto; }
.chat-bot { background: var(--bg); border: 1px solid var(--border); }
.chat-input-row { display: flex; gap: 0.5rem; padding: 0.75rem; border-top: 1px solid var(--border); }
.chat-input-row input { flex: 1; }
/* System cards */
.sys-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0.75rem; padding: 1rem; }
.sys-card { background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius); padding: 0.75rem; }
.sys-card .label { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.sys-card .value { font-size: 1.25rem; font-weight: 600; margin-top: 0.25rem; }
/* Request table */
.status-ok { color: var(--success); }
.status-err { color: var(--danger); }
.status-warn { color: var(--warn); }
</style>
</head>
<body>

<div class="dev-header">
    <img src="https://tina4.com/logo.svg" style="width:1.5rem;height:1.5rem;cursor:pointer;opacity:0.7;transition:opacity 0.15s" title="Back to app" onclick="exitDevAdmin()" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.7'" alt="Tina4">
    <h1>Tina4 Dev Admin</h1>
    <span class="badge">DEV</span>
    <span style="margin-left:auto; font-size:0.75rem; color:var(--muted)" id="timestamp"></span>
</div>

<div class="dev-tabs">
    <button class="dev-tab active" onclick="showTab('routes', event)">Routes <span class="count" id="routes-count">0</span></button>
    <button class="dev-tab" onclick="showTab('queue', event)">Queue <span class="count" id="queue-count">0</span></button>
    <button class="dev-tab" onclick="showTab('mailbox', event)">Mailbox <span class="count" id="mailbox-count">0</span></button>
    <button class="dev-tab" onclick="showTab('messages', event)">Messages <span class="count" id="messages-count">0</span></button>
    <button class="dev-tab" onclick="showTab('database', event)">Database <span class="count" id="db-count">0</span></button>
    <button class="dev-tab" onclick="showTab('requests', event)">Requests <span class="count" id="req-count">0</span></button>
    <button class="dev-tab" onclick="showTab('errors', event)">Errors <span class="count" id="err-count">0</span></button>
    <button class="dev-tab" onclick="showTab('websockets', event)">WS <span class="count" id="ws-count">0</span></button>
    <button class="dev-tab" onclick="showTab('system', event)">System</button>
    <button class="dev-tab" onclick="showTab('tools', event)">Tools</button>
    <button class="dev-tab" onclick="showTab('chat', event)">Tina4</button>
</div>

<div class="dev-content">

<!-- Routes Panel -->
<div id="panel-routes" class="dev-panel">
    <div class="dev-panel-header">
        <h2>Registered Routes</h2>
        <button class="btn btn-sm" onclick="loadRoutes()">Refresh</button>
    </div>
    <table>
        <thead><tr><th>Method</th><th>Path</th><th>Auth</th><th>Handler</th></tr></thead>
        <tbody id="routes-body"></tbody>
    </table>
</div>

<!-- Queue Panel -->
<div id="panel-queue" class="dev-panel hidden">
    <div class="dev-panel-header">
        <h2>Queue Jobs</h2>
        <div class="flex gap-sm">
            <button class="btn btn-sm" onclick="loadQueue()">Refresh</button>
            <button class="btn btn-sm" onclick="retryQueue()">Retry Failed</button>
            <button class="btn btn-sm btn-danger" onclick="purgeQueue()">Purge Done</button>
        </div>
    </div>
    <div class="toolbar">
        <button class="btn btn-sm filter-btn active" onclick="filterQueue('', event)">All</button>
        <button class="btn btn-sm filter-btn" onclick="filterQueue('pending', event)">Pending <span id="q-pending">0</span></button>
        <button class="btn btn-sm filter-btn" onclick="filterQueue('completed', event)">Done <span id="q-completed">0</span></button>
        <button class="btn btn-sm filter-btn" onclick="filterQueue('failed', event)">Failed <span id="q-failed">0</span></button>
        <button class="btn btn-sm filter-btn" onclick="filterQueue('reserved', event)">Active <span id="q-reserved">0</span></button>
    </div>
    <table>
        <thead><tr><th>ID</th><th>Topic</th><th>Status</th><th>Attempts</th><th>Created</th><th>Data</th><th></th></tr></thead>
        <tbody id="queue-body"></tbody>
    </table>
    <div id="queue-empty" class="empty hidden">No queue jobs</div>
</div>

<!-- Mailbox Panel -->
<div id="panel-mailbox" class="dev-panel hidden">
    <div class="dev-panel-header">
        <h2>Dev Mailbox</h2>
        <div class="flex gap-sm">
            <button class="btn btn-sm" onclick="loadMailbox()">Refresh</button>
            <button class="btn btn-sm btn-primary" onclick="seedMailbox()">Seed 5</button>
            <button class="btn btn-sm btn-danger" onclick="clearMailbox()">Clear</button>
        </div>
    </div>
    <div class="toolbar">
        <button class="btn btn-sm filter-btn active" onclick="filterMailbox('', event)">All</button>
        <button class="btn btn-sm filter-btn" onclick="filterMailbox('inbox', event)">Inbox</button>
        <button class="btn btn-sm filter-btn" onclick="filterMailbox('outbox', event)">Outbox</button>
    </div>
    <div id="mailbox-list"></div>
    <div id="mail-detail" class="hidden p-md"></div>
</div>

<!-- Messages Panel -->
<div id="panel-messages" class="dev-panel hidden">
    <div class="dev-panel-header">
        <h2>Message Log</h2>
        <div class="flex gap-sm items-center">
            <input type="text" id="msg-search" class="input" placeholder="Search messages..." onkeydown="if(event.key==='Enter')searchMessages()">
            <button class="btn btn-sm" onclick="searchMessages()">Search</button>
            <button class="btn btn-sm" onclick="loadMessages()">All</button>
            <button class="btn btn-sm btn-danger" onclick="clearMessages()">Clear</button>
        </div>
    </div>
    <div id="messages-list"></div>
    <div id="messages-empty" class="empty">No messages logged</div>
</div>

<!-- Database Panel -->
<div id="panel-database" class="dev-panel hidden">
    <div class="dev-panel-header">
        <h2>Database</h2>
        <button class="btn btn-sm" onclick="loadTables()">Refresh</button>
    </div>
    <div class="flex gap-md p-md">
        <div class="flex-1">
            <div class="flex gap-sm items-center mb-sm">
                <select id="query-type" class="input">
                    <option value="sql">SQL</option>
                    <option value="graphql">GraphQL</option>
                </select>
                <button class="btn btn-sm btn-primary" onclick="runQuery()">Run</button>
                <span class="text-sm text-muted">Ctrl+Enter</span>
            </div>
            <textarea id="query-input" rows="4" placeholder="SELECT * FROM users LIMIT 20" class="input input-mono" style="width:100%"></textarea>
            <div id="query-error" class="hidden" style="color:var(--danger);font-size:0.75rem;margin-top:0.25rem"></div>
        </div>
        <div style="width:180px">
            <div class="text-sm text-muted" style="font-weight:600;margin-bottom:0.5rem">Tables</div>
            <div id="table-list" class="text-sm"></div>
            <div style="margin-top:0.75rem;border-top:1px solid var(--border);padding-top:0.75rem">
                <div class="text-sm text-muted" style="font-weight:600;margin-bottom:0.5rem">Seed Data</div>
                <select id="seed-table" class="input" style="width:100%;margin-bottom:0.25rem"><option value="">Pick table...</option></select>
                <div class="flex gap-sm items-center">
                    <input type="number" id="seed-count" class="input" value="10" min="1" max="1000" style="width:60px">
                    <button class="btn btn-sm btn-success" onclick="seedTable()">Seed</button>
                </div>
            </div>
        </div>
    </div>
    <div id="query-results" style="overflow-x:auto"></div>
</div>

<!-- Requests Panel -->
<div id="panel-requests" class="dev-panel hidden">
    <div class="dev-panel-header">
        <h2>Request Inspector</h2>
        <div class="flex gap-sm">
            <button class="btn btn-sm" onclick="loadRequests()">Refresh</button>
            <button class="btn btn-sm btn-danger" onclick="clearRequests()">Clear</button>
        </div>
    </div>
    <div id="req-stats" class="toolbar text-sm text-muted"></div>
    <table>
        <thead><tr><th>Time</th><th>Method</th><th>Path</th><th>Status</th><th>Duration</th><th>Size</th></tr></thead>
        <tbody id="req-body"></tbody>
    </table>
    <div id="req-empty" class="empty hidden">No requests captured</div>
</div>

<!-- Errors Panel -->
<div id="panel-errors" class="dev-panel hidden">
    <div class="dev-panel-header">
        <h2>Error Tracker</h2>
        <div class="flex gap-sm">
            <button class="btn btn-sm" onclick="loadErrors()">Refresh</button>
            <button class="btn btn-sm btn-danger" onclick="clearResolvedErrors()">Clear Resolved</button>
        </div>
    </div>
    <div id="errors-list"></div>
    <div id="errors-empty" class="empty">No errors tracked</div>
</div>

<!-- WebSocket Panel -->
<div id="panel-websockets" class="dev-panel hidden">
    <div class="dev-panel-header">
        <h2>WebSocket Connections</h2>
        <button class="btn btn-sm" onclick="loadWebSockets()">Refresh</button>
    </div>
    <table>
        <thead><tr><th>ID</th><th>Path</th><th>IP</th><th>Connected</th><th>Status</th><th></th></tr></thead>
        <tbody id="ws-body"></tbody>
    </table>
    <div id="ws-empty" class="empty">No active connections</div>
</div>

<!-- System Panel -->
<div id="panel-system" class="dev-panel hidden">
    <div class="dev-panel-header">
        <h2>System Overview</h2>
        <button class="btn btn-sm" onclick="loadSystem()">Refresh</button>
    </div>
    <div id="sys-cards" class="sys-grid"></div>
</div>

<!-- Tools Panel -->
<div id="panel-tools" class="dev-panel hidden">
    <div class="dev-panel-header">
        <h2>Developer Tools</h2>
    </div>
    <div class="sys-grid">
        <div class="sys-card" style="cursor:pointer" onclick="runTool('carbon')">
            <div class="label">Carbon Benchmark</div>
            <div style="font-size:0.8rem;margin-top:0.25rem">Run Carbonah benchmarks to measure carbon footprint of framework operations</div>
        </div>
        <div class="sys-card" style="cursor:pointer" onclick="runTool('test')">
            <div class="label">Run Tests</div>
            <div style="font-size:0.8rem;margin-top:0.25rem">Execute the full pytest test suite</div>
        </div>
        <div class="sys-card" style="cursor:pointer" onclick="runTool('routes')">
            <div class="label">List Routes</div>
            <div style="font-size:0.8rem;margin-top:0.25rem">Show all registered routes with auth status</div>
        </div>
        <div class="sys-card" style="cursor:pointer" onclick="runTool('migrate')">
            <div class="label">Run Migrations</div>
            <div style="font-size:0.8rem;margin-top:0.25rem">Apply pending database migrations</div>
        </div>
        <div class="sys-card" style="cursor:pointer" onclick="runTool('seed')">
            <div class="label">Run Seeders</div>
            <div style="font-size:0.8rem;margin-top:0.25rem">Execute seed scripts from src/seeds/</div>
        </div>
        <div class="sys-card" style="cursor:pointer" onclick="runTool('ai')">
            <div class="label">AI Detection</div>
            <div style="font-size:0.8rem;margin-top:0.25rem">Detect AI tools and install framework context</div>
        </div>
    </div>
    <div id="tool-output" class="hidden" style="margin:1rem">
        <div class="dev-panel-header">
            <h2 id="tool-title">Output</h2>
            <button class="btn btn-sm" onclick="document.getElementById('tool-output').classList.add('hidden')">Close</button>
        </div>
        <pre id="tool-result" style="padding:1rem;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);font-size:0.75rem;font-family:var(--mono);max-height:400px;overflow:auto;white-space:pre-wrap"></pre>
    </div>
</div>

<!-- Chat Panel (Tina4) -->
<div id="panel-chat" class="dev-panel hidden">
    <div class="dev-panel-header">
        <h2>Tina4</h2>
        <div class="flex gap-sm items-center">
            <select id="ai-provider" class="input" style="width:120px">
                <option value="anthropic">Claude</option>
                <option value="openai">OpenAI</option>
            </select>
            <input type="password" id="ai-key" class="input" placeholder="Paste API key..." style="width:250px">
            <button class="btn btn-sm btn-primary" onclick="setAiKey()">Set Key</button>
            <span class="text-sm text-muted" id="ai-status">No key set</span>
        </div>
    </div>
    <div class="chat-container">
        <div class="chat-messages" id="chat-messages">
            <div class="chat-msg chat-bot">Hi! I'm Tina4. Ask me about routes, ORM, database, queues, templates, auth, or any Tina4 feature.</div>
        </div>
        <div class="chat-input-row">
            <input type="text" id="chat-input" class="input" placeholder="Ask Tina4..." onkeydown="if(event.key==='Enter')sendChat()">
            <button class="btn btn-primary" onclick="sendChat()">Send</button>
        </div>
    </div>
</div>

</div>

<script src="/js/tina4-dev-admin.js"></script>
<script>
// Self-diagnostic — detect if the external JS failed to load
(function() {
    if (typeof showTab !== 'function') {
        var banner = document.createElement('div');
        banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#ef4444;color:#fff;padding:0.75rem 1rem;font-family:system-ui;font-size:0.85rem;text-align:center';
        banner.innerHTML = '<strong>Dev Admin Error:</strong> tina4-dev-admin.js failed to load. Check that /js/tina4-dev-admin.js is accessible.';
        document.body.insertBefore(banner, document.body.firstChild);
    }
})();
</script>
</body>
</html>"""


def render_overlay_script() -> str:
    """Return a JS snippet that injects a floating dev admin button.

    Inject this into page responses in dev mode to provide quick access
    to the admin dashboard.
    """
    return """<script>
(function(){
    if (document.getElementById('tina4-dev-btn')) return;
    var btn = document.createElement('div');
    btn.id = 'tina4-dev-btn';
    btn.innerHTML = '<img src="https://tina4.com/logo.svg" style="width:1.5rem;height:1.5rem" alt="T4">';
    btn.title = 'Tina4 Dev Admin';
    btn.style.cssText = 'position:fixed;bottom:1rem;right:1rem;width:2.5rem;height:2.5rem;background:#3b82f6;color:#fff;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;font-weight:700;font-size:0.8rem;font-family:system-ui;z-index:99999;box-shadow:0 2px 8px rgba(0,0,0,0.3);transition:transform 0.15s,opacity 0.15s;opacity:0.5';
    btn.onmouseover = function(){ this.style.transform='scale(1.1)'; this.style.opacity='1'; };
    btn.onmouseout = function(){ this.style.transform='scale(1)'; this.style.opacity='0.5'; };
    btn.onclick = function(){ window.open('/__dev/', '_blank'); };
    document.body.appendChild(btn);
})();
</script>"""


__all__ = ["MessageLog", "RequestInspector", "BrokenTracker",
           "get_api_handlers", "render_dashboard", "render_overlay_script"]
