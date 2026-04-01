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
        "/__dev/api/connections": ("GET", _api_connections),
        "/__dev/api/connections/test": ("POST", _api_connections_test),
        "/__dev/api/connections/save": ("POST", _api_connections_save),
        "/__dev/api/gallery": ("GET", _api_gallery_list),
        "/__dev/api/gallery/deploy": ("POST", _api_gallery_deploy),
        "/__dev/api/mtime": ("GET", _api_mtime),
        "/__dev/api/version-check": ("GET", _api_version_check),
        "/__dev/api/metrics": ("GET", _api_metrics),
        "/__dev/api/metrics/full": ("GET", _api_metrics_full),
        "/__dev/api/metrics/file": ("GET", _api_metrics_file),
    }


async def _api_status(request, response):
    """System status overview."""
    import sys
    from tina4_python.messenger import DevMailbox

    mailbox = DevMailbox()
    status = {
        "python_version": sys.version,
        "framework": "tina4-python v3",
        "debug": os.environ.get("TINA4_DEBUG", "false"),
        "log_level": os.environ.get("TINA4_LOG_LEVEL", "ERROR"),
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
        columns = db.get_table_info(table)
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


async def _api_mtime(request, response):
    """Return the last file modification timestamp for DevReload polling.

    The dev toolbar JS polls this endpoint and triggers a browser refresh
    when the mtime changes, indicating source files have been modified.
    """
    from tina4_python.dev_reload import get_last_mtime, get_last_change_file
    return response({
        "mtime": get_last_mtime(),
        "file": get_last_change_file(),
    })


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
    position: sticky; top: 0; z-index: 100;
}
.dev-header h1 { font-size: 1rem; font-weight: 600; }
.dev-header .badge {
    background: var(--primary); color: #fff; padding: 0.15rem 0.5rem;
    border-radius: 1rem; font-size: 0.7rem; font-weight: 600;
}
.dev-tabs {
    display: flex; gap: 0; background: var(--surface);
    border-bottom: 1px solid var(--border); overflow-x: auto;
    position: sticky; top: 2.75rem; z-index: 100;
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
.dev-content { padding: 0.25rem; }
.dev-panel {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); overflow: visible;
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
    <img src="/images/logo.svg" style="width:1.5rem;height:1.5rem;cursor:pointer;opacity:0.7;transition:opacity 0.15s" title="Back to app" onclick="exitDevAdmin()" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.7'" alt="Tina4">
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
    <button class="dev-tab" onclick="showTab('metrics', event)">Metrics</button>
    <button class="dev-tab" onclick="showTab('connections', event)">Connections</button>
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

<!-- Metrics Panel -->
<div id="panel-metrics" class="dev-panel hidden">
    <div class="dev-panel-header">
        <h2>Code Metrics</h2>
        <div>
            <button class="btn btn-sm" onclick="loadAllMetrics()">Refresh</button>
        </div>
    </div>
    <div id="metrics-bubble" style="margin:1rem;"></div>
    <div id="metrics-drilldown" style="margin:0 1rem;display:none;"></div>
    <div id="metrics-quick" class="sys-grid"></div>
    <div id="metrics-largest" style="margin-top:1rem;"></div>
    <div id="metrics-tables" style="margin-top:1rem;padding:0 1rem 1rem;overflow-x:auto;">
        <h3 style="margin:1rem 0 0.5rem;color:var(--primary);">File Analysis</h3>
        <div id="metrics-heatmap"></div>
        <h3 style="margin:1rem 0 0.5rem;color:var(--primary);">Most Complex Functions</h3>
        <div id="metrics-complex"></div>
        <h3 style="margin:1rem 0 0.5rem;color:var(--primary);">Coupling Analysis</h3>
        <div id="metrics-coupling"></div>
        <h3 style="margin:1rem 0 0.5rem;color:var(--primary);">Violations</h3>
        <div id="metrics-violations"></div>
    </div>
</div>

<!-- Connections Panel -->
<div id="panel-connections" class="dev-panel hidden">
    <div class="dev-panel-header">
        <h2>Connection Builder</h2>
    </div>
    <div class="p-md">
        <div class="flex gap-md" style="flex-wrap:wrap">
            <div style="flex:1;min-width:300px">
                <div class="mb-sm">
                    <label class="text-sm text-muted" style="display:block;margin-bottom:0.25rem">Driver</label>
                    <select id="conn-driver" class="input" style="width:100%" onchange="connDriverChanged()">
                        <option value="sqlite">SQLite</option>
                        <option value="postgresql">PostgreSQL</option>
                        <option value="mysql">MySQL</option>
                        <option value="mssql">MSSQL</option>
                        <option value="firebird">Firebird</option>
                    </select>
                </div>
                <div class="mb-sm conn-server-field">
                    <label class="text-sm text-muted" style="display:block;margin-bottom:0.25rem">Host</label>
                    <input type="text" id="conn-host" class="input" style="width:100%" value="localhost" placeholder="localhost" oninput="updateConnectionUrl()">
                </div>
                <div class="mb-sm conn-server-field">
                    <label class="text-sm text-muted" style="display:block;margin-bottom:0.25rem">Port</label>
                    <input type="number" id="conn-port" class="input" style="width:100%" placeholder="5432" oninput="updateConnectionUrl()">
                </div>
                <div class="mb-sm">
                    <label class="text-sm text-muted" style="display:block;margin-bottom:0.25rem">Database</label>
                    <input type="text" id="conn-database" class="input" style="width:100%" placeholder="mydb" oninput="updateConnectionUrl()">
                </div>
                <div class="mb-sm conn-server-field">
                    <label class="text-sm text-muted" style="display:block;margin-bottom:0.25rem">Username</label>
                    <input type="text" id="conn-username" class="input" style="width:100%" placeholder="username">
                </div>
                <div class="mb-sm conn-server-field">
                    <label class="text-sm text-muted" style="display:block;margin-bottom:0.25rem">Password</label>
                    <input type="password" id="conn-password" class="input" style="width:100%" placeholder="password">
                </div>
                <div class="mb-sm">
                    <label class="text-sm text-muted" style="display:block;margin-bottom:0.25rem">Connection URL</label>
                    <input type="text" id="conn-url" class="input input-mono" style="width:100%" readonly>
                </div>
                <div class="flex gap-sm">
                    <button class="btn btn-primary" onclick="testConnection()">Test Connection</button>
                    <button class="btn btn-success" onclick="saveConnection()">Save to .env</button>
                </div>
            </div>
            <div style="width:300px">
                <div class="dev-panel" style="margin-bottom:1rem">
                    <div class="dev-panel-header"><h2>Test Result</h2></div>
                    <div id="conn-test-result" class="p-md text-sm text-muted">No test run yet</div>
                </div>
                <div class="dev-panel">
                    <div class="dev-panel-header"><h2>Current .env Values</h2></div>
                    <div id="conn-env-values" class="p-md text-sm text-muted">Loading...</div>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
function connDriverChanged() {
    var driver = document.getElementById('conn-driver').value;
    var ports = {postgresql: 5432, mysql: 3306, mssql: 1433, firebird: 3050};
    var isSqlite = (driver === 'sqlite');
    document.getElementById('conn-port').value = ports[driver] || '';
    var fields = document.querySelectorAll('.conn-server-field');
    for (var i = 0; i < fields.length; i++) {
        fields[i].style.display = isSqlite ? 'none' : '';
    }
    updateConnectionUrl();
}
function updateConnectionUrl() {
    var driver = document.getElementById('conn-driver').value;
    var host = document.getElementById('conn-host').value || 'localhost';
    var port = document.getElementById('conn-port').value;
    var database = document.getElementById('conn-database').value;
    if (driver === 'sqlite') {
        document.getElementById('conn-url').value = 'sqlite:///' + database;
    } else {
        document.getElementById('conn-url').value = driver + '://' + host + ':' + port + '/' + database;
    }
}
function testConnection() {
    var url = document.getElementById('conn-url').value;
    var username = document.getElementById('conn-username').value;
    var password = document.getElementById('conn-password').value;
    var el = document.getElementById('conn-test-result');
    el.innerHTML = '<span class="text-muted">Testing...</span>';
    fetch('/__dev/api/connections/test', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url: url, username: username, password: password})
    }).then(function(r){return r.json()}).then(function(data) {
        if (data.success) {
            el.innerHTML = '<div style="color:var(--success);font-weight:600;margin-bottom:0.5rem">&#10004; Connected</div>' +
                '<div class="text-sm">Version: ' + (data.version || 'N/A') + '</div>' +
                '<div class="text-sm">Tables: ' + (data.tables !== undefined ? data.tables : 'N/A') + '</div>';
        } else {
            el.innerHTML = '<div style="color:var(--danger);font-weight:600;margin-bottom:0.5rem">&#10008; Failed</div>' +
                '<div class="text-sm" style="color:var(--danger)">' + (data.error || 'Unknown error') + '</div>';
        }
    }).catch(function(e) {
        el.innerHTML = '<div style="color:var(--danger)">Error: ' + e.message + '</div>';
    });
}
function saveConnection() {
    var url = document.getElementById('conn-url').value;
    var username = document.getElementById('conn-username').value;
    var password = document.getElementById('conn-password').value;
    if (!url) { alert('Please build a connection URL first'); return; }
    fetch('/__dev/api/connections/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url: url, username: username, password: password})
    }).then(function(r){return r.json()}).then(function(data) {
        if (data.success) {
            alert('Connection saved to .env');
            loadConnectionEnv();
        } else {
            alert('Save failed: ' + (data.error || 'Unknown error'));
        }
    }).catch(function(e) { alert('Error: ' + e.message); });
}
function loadConnectionEnv() {
    fetch('/__dev/api/connections').then(function(r){return r.json()}).then(function(data) {
        var el = document.getElementById('conn-env-values');
        el.innerHTML = '<div class="mb-sm"><span class="text-muted">DATABASE_URL:</span> <code>' + (data.url || '<em>not set</em>') + '</code></div>' +
            '<div class="mb-sm"><span class="text-muted">DATABASE_USERNAME:</span> <code>' + (data.username || '<em>not set</em>') + '</code></div>' +
            '<div><span class="text-muted">DATABASE_PASSWORD:</span> <code>' + (data.password || '<em>not set</em>') + '</code></div>';
    }).catch(function() {
        document.getElementById('conn-env-values').innerHTML = '<span class="text-muted">Could not load .env values</span>';
    });
}
// Load env values when connections tab is first shown
var _origShowTab = typeof showTab === 'function' ? showTab : null;
document.addEventListener('DOMContentLoaded', function() {
    var connTab = document.querySelector('[onclick*="connections"]');
    if (connTab) {
        connTab.addEventListener('click', function() { loadConnectionEnv(); }, {once: true});
    }
});
</script>

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

<script src="/js/tina4-dev-admin.min.js"></script>
<script>
// ── Metrics Panel JS ──
var _metricsFullData=null;
function miColor(mi){
    if(mi>=60) return 'rgb('+(Math.round(34+(1-((mi-60)/40))*186))+','+(Math.round(197-(1-((mi-60)/40))*50))+',0)';
    if(mi>=30) return 'rgb('+(Math.round(220+((60-mi)/30)*19))+','+(Math.round(180-((60-mi)/30)*112))+',0)';
    return 'rgb(239,'+(Math.round(68-mi*2))+',0)';
}
function renderBubbleChart(files,depGraph){
    var container=document.getElementById('metrics-bubble');
    if(!files||!files.length){{container.innerHTML='<p style="color:var(--muted);padding:1rem">No files to analyze</p>';return;}}
    depGraph=depGraph||{{}};
    var W=container.offsetWidth||900,H=Math.max(450,Math.min(650,W*0.45));
    var maxLoc=Math.max.apply(null,files.map(function(f){{return f.loc}}))||1;
    var maxCC=Math.max.apply(null,files.map(function(f){{return f.complexity||0}}))||1;
    var minR=14,maxR=Math.min(70,W/10);
    // Composite health colour: complexity + tests + dependencies
    function healthColor(f){{
        var cc=Math.min((f.complexity||0)/maxCC,1); // 0=low, 1=high
        var tested=f.has_tests?1:0;
        var deps=Math.min((f.dep_count||0)/10,1); // 0=none, 1=many
        // Score: 0=healthy(green), 1=risky(red)
        var score=cc*0.5+(1-tested)*0.3+deps*0.2;
        score=Math.max(0,Math.min(1,score));
        var r=Math.round(34+score*200);
        var g=Math.round(197-score*160);
        var b2=Math.round(94-score*50);
        return 'rgb('+r+','+g+','+b2+')';
    }}
    // Build path->index lookup
    var pathIdx={{}};
    files.forEach(function(f,i){{pathIdx[f.path]=i;}});
    // Spiral placement
    var sorted=files.slice().sort(function(a,b){{return a.loc-b.loc}});
    var cx=W/2,cy=H/2;
    var bubbles=[];
    var angle=0,spiralR=0;
    for(var i=0;i<sorted.length;i++){{
        var f=sorted[i];
        var r=minR+Math.sqrt(f.loc/maxLoc)*(maxR-minR);
        var color=healthColor(f);
        var placed=false;
        for(var attempt=0;attempt<800;attempt++){{
            var px=cx+spiralR*Math.cos(angle);
            var py=cy+spiralR*Math.sin(angle);
            var collides=false;
            for(var j=0;j<bubbles.length;j++){{
                var dx=px-bubbles[j].x,dy=py-bubbles[j].y;
                if(Math.sqrt(dx*dx+dy*dy)<r+bubbles[j].r+2){{collides=true;break;}}
            }}
            if(!collides&&px>r+2&&px<W-r-2&&py>r+25&&py<H-r-2){{
                bubbles.push({{x:px,y:py,vx:0,vy:0,r:r,color:color,f:f}});
                placed=true;break;
            }}
            angle+=0.2;spiralR+=0.04;
        }}
        if(!placed){{bubbles.push({{x:cx+(Math.random()-0.5)*W*0.3,y:cy+(Math.random()-0.5)*H*0.3,vx:0,vy:0,r:r,color:color,f:f}});}}
    }}
    // Build edge list from dependency graph
    var edges=[];
    Object.keys(depGraph).forEach(function(src){{
        var srcIdx=null;
        bubbles.forEach(function(b,i){{if(b.f.path===src)srcIdx=i;}});
        if(srcIdx===null)return;
        (depGraph[src]||[]).forEach(function(tgt){{
            var tgtIdx=null;
            bubbles.forEach(function(b,i){{if(b.f.path===tgt)tgtIdx=i;}});
            if(tgtIdx!==null&&srcIdx!==tgtIdx)edges.push([srcIdx,tgtIdx]);
        }});
    }});
    // Canvas
    var canvas=document.createElement('canvas');
    canvas.width=W;canvas.height=H;
    canvas.style.cssText='display:block;border:1px solid var(--border);border-radius:8px;cursor:pointer;background:#0f172a';
    container.innerHTML='<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.5rem"><h3 style="margin:0;color:var(--primary)">Code Landscape</h3><span style="font-size:0.7rem;color:var(--muted)">Drag bubbles | Click to drill down | Size=LOC | Colour=health | \u24c9=tested | \u24b9=deps</span></div>';
    container.appendChild(canvas);
    var ctx=canvas.getContext('2d');
    var hoveredIdx=-1,dragIdx=-1,dragOX=0,dragOY=0;
    // Physics
    function simulate(){{
        var damping=0.92,springK=0.005,repulse=800;
        // Spring forces along edges
        edges.forEach(function(e){{
            var a=bubbles[e[0]],b=bubbles[e[1]];
            var dx=b.x-a.x,dy=b.y-a.y;
            var dist=Math.sqrt(dx*dx+dy*dy)||1;
            var rest=a.r+b.r+40;
            var force=(dist-rest)*springK;
            var fx=dx/dist*force,fy=dy/dist*force;
            if(e[0]!==dragIdx){{a.vx+=fx;a.vy+=fy;}}
            if(e[1]!==dragIdx){{b.vx-=fx;b.vy-=fy;}}
        }});
        // Repulsion between all bubbles
        for(var i=0;i<bubbles.length;i++){{
            for(var j=i+1;j<bubbles.length;j++){{
                var a=bubbles[i],b=bubbles[j];
                var dx=b.x-a.x,dy=b.y-a.y;
                var dist=Math.sqrt(dx*dx+dy*dy)||1;
                var minDist=a.r+b.r+4;
                if(dist<minDist*3){{
                    var force=repulse/(dist*dist);
                    var fx=dx/dist*force,fy=dy/dist*force;
                    if(i!==dragIdx){{a.vx-=fx;a.vy-=fy;}}
                    if(j!==dragIdx){{b.vx+=fx;b.vy+=fy;}}
                }}
            }}
        }}
        // Apply velocity + damping + boundary
        bubbles.forEach(function(b,idx){{
            if(idx===dragIdx)return;
            b.vx*=damping;b.vy*=damping;
            b.x+=b.vx;b.y+=b.vy;
            b.x=Math.max(b.r+2,Math.min(W-b.r-2,b.x));
            b.y=Math.max(b.r+25,Math.min(H-b.r-2,b.y));
        }});
    }}
    // Draw
    function draw(){{
        simulate();
        ctx.clearRect(0,0,W,H);
        // Grid
        ctx.strokeStyle='rgba(255,255,255,0.03)';ctx.lineWidth=1;
        for(var gx=0;gx<W;gx+=50){{ctx.beginPath();ctx.moveTo(gx,0);ctx.lineTo(gx,H);ctx.stroke();}}
        for(var gy=0;gy<H;gy+=50){{ctx.beginPath();ctx.moveTo(0,gy);ctx.lineTo(W,gy);ctx.stroke();}}
        // Dependency arrows
        edges.forEach(function(e){{
            var a=bubbles[e[0]],b=bubbles[e[1]];
            var dx=b.x-a.x,dy=b.y-a.y;
            var dist=Math.sqrt(dx*dx+dy*dy)||1;
            var highlighted=(hoveredIdx===e[0]||hoveredIdx===e[1]);
            ctx.beginPath();
            ctx.moveTo(a.x+dx/dist*a.r,a.y+dy/dist*a.r);
            var ex=b.x-dx/dist*b.r,ey=b.y-dy/dist*b.r;
            ctx.lineTo(ex,ey);
            ctx.strokeStyle=highlighted?'rgba(139,180,250,0.6)':'rgba(255,255,255,0.1)';
            ctx.lineWidth=highlighted?2:1;ctx.stroke();
            // Arrowhead
            var aLen=highlighted?10:6;
            var aAngle=Math.atan2(dy,dx);
            ctx.beginPath();
            ctx.moveTo(ex,ey);
            ctx.lineTo(ex-aLen*Math.cos(aAngle-0.4),ey-aLen*Math.sin(aAngle-0.4));
            ctx.lineTo(ex-aLen*Math.cos(aAngle+0.4),ey-aLen*Math.sin(aAngle+0.4));
            ctx.closePath();ctx.fillStyle=ctx.strokeStyle;ctx.fill();
        }});
        // Bubbles
        bubbles.forEach(function(b,idx){{
            var isHovered=(idx===hoveredIdx);
            var drawR=isHovered?b.r+4:b.r;
            if(isHovered){{ctx.beginPath();ctx.arc(b.x,b.y,drawR+8,0,Math.PI*2);ctx.fillStyle='rgba(255,255,255,0.08)';ctx.fill();}}
            ctx.beginPath();ctx.arc(b.x,b.y,drawR,0,Math.PI*2);
            ctx.fillStyle=b.color;ctx.globalAlpha=isHovered?0.95:0.7;ctx.fill();
            ctx.globalAlpha=1;ctx.strokeStyle=b.color;ctx.lineWidth=isHovered?2.5:1.5;ctx.stroke();
            // Label
            var name=b.f.path.split('/').pop().replace('.py','');
            if(drawR>16){{
                var fs=Math.max(8,Math.min(13,drawR*0.38));
                ctx.fillStyle='#fff';ctx.font='600 '+fs+'px monospace';ctx.textAlign='center';
                ctx.fillText(name,b.x,b.y-2);
                ctx.fillStyle='rgba(255,255,255,0.65)';ctx.font=(fs-1)+'px monospace';
                ctx.fillText(b.f.loc+' LOC',b.x,b.y+fs);
                if(isHovered&&drawR>25){{
                    ctx.fillStyle='rgba(255,255,255,0.5)';ctx.font=(fs-2)+'px monospace';
                    ctx.fillText('CC:'+b.f.complexity+' MI:'+b.f.maintainability,b.x,b.y+fs*2);
                }}
            }}
            // Markers: T (tested) and D (dependencies)
            var markers='';
            if(b.f.has_tests)markers+='\u24c9';
            if(b.f.dep_count>0)markers+='\u24b9';
            if(markers&&drawR>12){{
                ctx.fillStyle='rgba(255,255,255,0.85)';ctx.font='bold '+Math.max(7,drawR*0.25)+'px sans-serif';
                ctx.textAlign='center';ctx.fillText(markers,b.x,b.y-drawR+Math.max(7,drawR*0.25)+1);
            }}
            b._drawX=b.x;b._drawY=b.y;b._drawR=drawR;
        }});
        // Summary
        var totalLoc=0,totalFiles=bubbles.length,testedCount=0;
        bubbles.forEach(function(b){{totalLoc+=b.f.loc;if(b.f.has_tests)testedCount++;}});
        var avgMI=bubbles.reduce(function(s,b){{return s+b.f.maintainability}},0)/totalFiles;
        ctx.fillStyle='rgba(255,255,255,0.35)';ctx.font='11px monospace';ctx.textAlign='right';
        ctx.fillText(totalFiles+' files | '+totalLoc.toLocaleString()+' LOC | MI:'+avgMI.toFixed(1)+' | Tested:'+testedCount+'/'+totalFiles,W-12,H-10);
        window._metricsAnimFrame=requestAnimationFrame(draw);
    }}
    draw();
    // Mouse events — hover + drag
    canvas.addEventListener('mousemove',function(e){{
        var rect=canvas.getBoundingClientRect();
        var mx=e.clientX-rect.left,my=e.clientY-rect.top;
        if(dragIdx>=0){{
            bubbles[dragIdx].x=mx-dragOX;bubbles[dragIdx].y=my-dragOY;
            bubbles[dragIdx].vx=0;bubbles[dragIdx].vy=0;return;
        }}
        hoveredIdx=-1;
        for(var i=bubbles.length-1;i>=0;i--){{
            var b=bubbles[i];
            var dx=mx-b._drawX,dy=my-b._drawY;
            if(Math.sqrt(dx*dx+dy*dy)<=b._drawR){{hoveredIdx=i;break;}}
        }}
        canvas.style.cursor=hoveredIdx>=0?'grab':'default';
    }});
    canvas.addEventListener('mousedown',function(e){{
        if(hoveredIdx>=0){{
            dragIdx=hoveredIdx;
            var rect=canvas.getBoundingClientRect();
            dragOX=e.clientX-rect.left-bubbles[dragIdx].x;
            dragOY=e.clientY-rect.top-bubbles[dragIdx].y;
            canvas.style.cursor='grabbing';
        }}
    }});
    canvas.addEventListener('mouseup',function(){{
        if(dragIdx>=0){{canvas.style.cursor='grab';dragIdx=-1;}}
    }});
    canvas.addEventListener('mouseleave',function(){{hoveredIdx=-1;dragIdx=-1;}});
    canvas.addEventListener('dblclick',function(e){{
        if(hoveredIdx<0)return;
        drillDownFile(bubbles[hoveredIdx].f.path);
    }});
}
function drillDownFile(path){
    var dd=document.getElementById('metrics-drilldown');
    dd.style.display='block';
    dd.innerHTML='<div class="dev-panel" style="margin-bottom:1rem"><div class="dev-panel-header"><h2>'+path+'</h2><button class="btn btn-sm" onclick="document.getElementById(&#39;metrics-drilldown&#39;).style.display=&#39;none&#39;">Close</button></div><div class="p-md"><p style="color:var(--muted)">Loading file analysis...</p></div></div>';
    fetch('/__dev/api/metrics/file?path='+encodeURIComponent(path)).then(function(r){return r.json()}).then(function(d){
        if(d.error){dd.querySelector('.p-md').innerHTML='<p style="color:var(--danger)">'+d.error+'</p>';return;}
        var html='<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:0.5rem;margin-bottom:1rem">';
        html+='<div class="sys-card"><div class="label">LOC</div><div class="value">'+d.loc+'</div></div>';
        html+='<div class="sys-card"><div class="label">Total Lines</div><div class="value">'+d.total_lines+'</div></div>';
        html+='<div class="sys-card"><div class="label">Classes</div><div class="value">'+d.classes+'</div></div>';
        html+='<div class="sys-card"><div class="label">Functions</div><div class="value">'+(d.functions?d.functions.length:0)+'</div></div>';
        html+='<div class="sys-card"><div class="label">Imports</div><div class="value">'+(d.imports?d.imports.length:0)+'</div></div>';
        html+='</div>';
        if(d.functions&&d.functions.length){
            html+='<h3 style="margin:0.5rem 0;color:var(--primary);font-size:0.85rem">Cyclomatic Complexity by Function</h3>';
            // Mini bar chart for complexity
            var maxCC=Math.max.apply(null,d.functions.map(function(f){return f.complexity}))||1;
            html+='<div style="display:flex;flex-direction:column;gap:4px">';
            d.functions.forEach(function(f){
                var pct=Math.max(3,f.complexity/maxCC*100);
                var color=f.complexity>20?'#ef4444':f.complexity>10?'#eab308':f.complexity>5?'#3b82f6':'#22c55e';
                html+='<div style="display:flex;align-items:center;gap:8px;font-size:0.75rem;font-family:var(--mono)">';
                html+='<span style="width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text)" title="'+f.name+'">'+f.name+'</span>';
                html+='<div style="flex:1;height:16px;background:var(--bg);border-radius:3px;overflow:hidden;position:relative">';
                html+='<div style="width:'+pct+'%;height:100%;background:'+color+';border-radius:3px;transition:width 0.3s"></div>';
                html+='</div>';
                html+='<span style="width:70px;text-align:right;color:'+color+';font-weight:600">CC:'+f.complexity+'</span>';
                html+='<span style="width:60px;text-align:right;color:var(--muted)">'+f.loc+' LOC</span>';
                html+='<span style="width:30px;text-align:right;color:var(--muted)">L'+f.line+'</span>';
                html+='</div>';
            });
            html+='</div>';
        }
        if(d.imports&&d.imports.length){
            html+='<h3 style="margin:0.75rem 0 0.25rem;color:var(--primary);font-size:0.85rem">Dependencies</h3>';
            html+='<div style="display:flex;flex-wrap:wrap;gap:4px">';
            d.imports.forEach(function(imp){
                html+='<span style="padding:2px 8px;background:var(--bg);border:1px solid var(--border);border-radius:4px;font-size:0.7rem;font-family:var(--mono)">'+imp+'</span>';
            });
            html+='</div>';
        }
        if(d.warnings&&d.warnings.length){
            html+='<h3 style="margin:0.75rem 0 0.25rem;color:#eab308;font-size:0.85rem">&#9888; Warnings</h3>';
            html+='<div style="display:flex;flex-direction:column;gap:4px">';
            d.warnings.forEach(function(w){
                html+='<div style="padding:4px 8px;background:rgba(234,179,8,0.08);border-left:3px solid #eab308;border-radius:0 4px 4px 0;font-size:0.75rem;font-family:var(--mono);color:var(--text)">';
                html+='<span style="color:#eab308;margin-right:6px">L'+w.line+'</span>'+w.message+'</div>';
            });
            html+='</div>';
        }
        dd.querySelector('.p-md').innerHTML=html;
    }).catch(function(e){
        dd.querySelector('.p-md').innerHTML='<p style="color:var(--danger)">Error: '+e.message+'</p>';
    });
    dd.scrollIntoView({behavior:'smooth',block:'start'});
}
function loadAllMetrics(){
    // Stop any running animation
    if(window._metricsAnimFrame)cancelAnimationFrame(window._metricsAnimFrame);
    // Load quick metrics
    var el=document.getElementById('metrics-quick');
    el.innerHTML='<div class="sys-card"><div class="value">Loading...</div></div>';
    fetch('/__dev/api/metrics').then(function(r){return r.json()}).then(function(d){
        if(d.error){el.innerHTML='<div class="sys-card"><div class="value" style="color:var(--danger)">'+d.error+'</div></div>';return;}
        el.innerHTML=
            '<div class="sys-card"><div class="label">Python Files</div><div class="value">'+d.file_count+'</div></div>'+
            '<div class="sys-card"><div class="label">Lines of Code</div><div class="value">'+d.total_loc.toLocaleString()+'</div></div>'+
            '<div class="sys-card"><div class="label">Comment Lines</div><div class="value">'+d.total_comment.toLocaleString()+'</div></div>'+
            '<div class="sys-card"><div class="label">Blank Lines</div><div class="value">'+d.total_blank.toLocaleString()+'</div></div>'+
            '<div class="sys-card"><div class="label">Classes</div><div class="value">'+d.classes+'</div></div>'+
            '<div class="sys-card"><div class="label">Functions</div><div class="value">'+d.functions+'</div></div>'+
            '<div class="sys-card"><div class="label">Routes</div><div class="value">'+d.route_count+'</div></div>'+
            '<div class="sys-card"><div class="label">ORM Models</div><div class="value">'+d.orm_count+'</div></div>'+
            '<div class="sys-card"><div class="label">Templates</div><div class="value">'+d.template_count+'</div></div>'+
            '<div class="sys-card"><div class="label">Migrations</div><div class="value">'+d.migration_count+'</div></div>';
    }).catch(function(e){el.innerHTML='<div class="sys-card"><div class="value" style="color:var(--danger)">Error: '+e.message+'</div></div>';});
    // Load full analysis (bubble chart + tables)
    document.getElementById('metrics-bubble').innerHTML='<p style="color:var(--muted);padding:1rem">Analyzing codebase...</p>';
    fetch('/__dev/api/metrics/full').then(function(r){return r.json()}).then(function(d){
        _metricsFullData=d;
        if(d.error){document.getElementById('metrics-bubble').innerHTML='<p style="color:var(--danger);padding:1rem">'+d.error+'</p>';return;}
        // Bubble chart
        renderBubbleChart(d.file_metrics,d.dependency_graph);
        // File analysis table
        var hm=document.getElementById('metrics-heatmap');
        var rows=d.file_metrics.map(function(f){
            var color=miColor(f.maintainability);
            var barW=Math.max(2,Math.min(100,f.maintainability));
            return '<tr style="cursor:pointer" onclick="drillDownFile(&#39;'+f.path+'&#39;)"><td><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:'+color+';margin-right:6px"></span>'+f.path+'</td><td>'+f.loc+'</td><td>'+f.complexity+'</td><td>'+f.avg_complexity+'</td><td><div style="display:flex;align-items:center;gap:6px"><div style="width:'+barW+'px;height:6px;border-radius:3px;background:'+color+'"></div><span>'+f.maintainability+'</span></div></td><td>'+f.instability+'</td></tr>';
        }).join('');
        hm.innerHTML='<table style="width:100%"><thead><tr><th>File</th><th>LOC</th><th>CC</th><th>Avg CC</th><th>MI</th><th>Instab.</th></tr></thead><tbody>'+rows+'</tbody></table>';
        // Most complex functions
        var cf=document.getElementById('metrics-complex');
        var frows=d.most_complex_functions.map(function(f){
            var color=f.complexity>20?'#ef4444':f.complexity>10?'#eab308':'#22c55e';
            return '<tr style="cursor:pointer" onclick="drillDownFile(&#39;'+f.file+'&#39;)"><td><span style="color:'+color+';font-weight:bold">'+f.complexity+'</span></td><td>'+f.name+'</td><td>'+f.file+':'+f.line+'</td><td>'+f.loc+'</td></tr>';
        }).join('');
        cf.innerHTML='<table style="width:100%"><thead><tr><th>CC</th><th>Function</th><th>File</th><th>LOC</th></tr></thead><tbody>'+frows+'</tbody></table>';
        // Coupling
        var cp=document.getElementById('metrics-coupling');
        var crows=d.file_metrics.filter(function(f){return f.coupling_afferent>0||f.coupling_efferent>0}).map(function(f){
            return '<tr style="cursor:pointer" onclick="drillDownFile(&#39;'+f.path+'&#39;)"><td>'+f.path+'</td><td>'+f.coupling_afferent+'</td><td>'+f.coupling_efferent+'</td><td>'+f.instability+'</td></tr>';
        }).join('');
        cp.innerHTML=crows?'<table style="width:100%"><thead><tr><th>File</th><th>Ca (in)</th><th>Ce (out)</th><th>Instability</th></tr></thead><tbody>'+crows+'</tbody></table>':'<p style="color:var(--muted)">No coupling data</p>';
        // Violations
        var vl=document.getElementById('metrics-violations');
        if(d.violations&&d.violations.length){
            var vrows=d.violations.map(function(v){
                var icon=v.type==='error'?'&#9888;':'&#9432;';
                var color=v.type==='error'?'#ef4444':'#eab308';
                return '<tr style="cursor:pointer" onclick="drillDownFile(&#39;'+v.file+'&#39;)"><td style="color:'+color+'">'+icon+'</td><td>'+v.message+'</td><td>'+v.file+(v.line?':'+v.line:'')+'</td></tr>';
            }).join('');
            vl.innerHTML='<table style="width:100%"><thead><tr><th></th><th>Issue</th><th>Location</th></tr></thead><tbody>'+vrows+'</tbody></table>';
        }else{
            vl.innerHTML='<p style="color:#22c55e">&#10003; No violations found</p>';
        }
    }).catch(function(e){
        document.getElementById('metrics-bubble').innerHTML='<p style="color:var(--danger);padding:1rem">Error: '+e.message+'</p>';
    });
}
// Auto-load when Metrics tab is shown
var _metricsLoaded=false;
var _origShowTab=typeof showTab==='function'?showTab:null;
if(_origShowTab){
    showTab=function(name){
        _origShowTab(name);
        if(name==='metrics'&&!_metricsLoaded){_metricsLoaded=true;loadAllMetrics();}
    };
}
// Fallback: also listen for click on the tab button
var metricsTab=document.querySelector('[onclick*="metrics"]');
if(metricsTab)metricsTab.addEventListener('click',function(){if(!_metricsLoaded){_metricsLoaded=true;loadAllMetrics();}});
</script>
<script>
// Self-diagnostic — detect if the external JS failed to load
(function() {
    if (typeof showTab !== 'function') {
        var banner = document.createElement('div');
        banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#ef4444;color:#fff;padding:0.75rem 1rem;font-family:system-ui;font-size:0.85rem;text-align:center';
        banner.innerHTML = '<strong>Dev Admin Error:</strong> tina4-dev-admin.min.js failed to load. Check that /js/tina4-dev-admin.min.js is accessible.';
        document.body.insertBefore(banner, document.body.firstChild);
    }
})();
</script>
</body>
</html>"""


def render_dev_toolbar(method: str, path: str, matched_pattern: str,
                       request_id: str, route_count: int) -> str:
    """Return an HTML toolbar injected at the bottom of HTML responses in dev mode.

    Shows: Tina4 version (blue), HTTP method (green), path, matched pattern,
    request ID (yellow), route count (blue), Python version, Dashboard link,
    and a close button.
    """
    import sys
    python_version = sys.version.split()[0]
    poll_interval_ms = int(os.environ.get("TINA4_DEV_POLL_INTERVAL", "3000"))

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
(function(){{
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
}})();
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


__all__ = ["MessageLog", "RequestInspector", "BrokenTracker",
           "get_api_handlers", "render_dashboard", "render_dev_toolbar"]
