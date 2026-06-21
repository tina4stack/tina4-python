# Built-in MCP dev tools — auto-registered when TINA4_DEBUG=true + localhost.
"""
24 built-in tools for AI-assisted development. These expose the framework's
internals to MCP clients (Claude Code, Cursor, etc.) for inspection,
querying, file editing, and management.

Security:
    - Only active when TINA4_DEBUG=true AND running on localhost
    - File operations sandboxed to project directory
    - database_execute available on localhost only
    - TINA4_MCP_REMOTE=true to enable on remote servers (opt-in)

Defensive writes:
    `file_write` and `file_patch` back up the prior content to
    `.tina4/backups/<flat-path>.<ts>.bak` before overwriting, refuse
    suspicious truncations (>200B file shrinking to <30% of its size),
    and log every attempt to `.tina4/agent.log`. The agent's "applying a
    small patch went and messed up my whole file" scenario is the
    canonical symptom this guards against.
"""
import os
import json
import re
import datetime
from pathlib import Path


def _agent_log(project_root: Path, category: str, message: str) -> None:
    """Append a structured line to `.tina4/agent.log` AND echo to stderr.

    Mirrors the Rust `agent_log` helper so a single log file captures
    every agent action regardless of which side of the stack performed
    it. Cheap — never blocks the caller on I/O failure.
    """
    try:
        log_dir = project_root / ".tina4"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "agent.log"
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{ts} [{category}] {message}\n")
    except Exception:
        pass  # logging must never fail the actual call
    import sys
    print(f"  [agent {category}] {message}", file=sys.stderr)


def _verify_python_import(project_root: Path, rel_path: str) -> str | None:
    """Try importing a freshly-written Python module to catch hallucinated
    framework APIs (NameError, ImportError, AttributeError) BEFORE the
    next request hits the broken handler.

    Returns None on success, or the captured error string on failure.
    Only checks files under src/ that end in .py (skip __init__.py
    and tests — they have their own loading patterns). Uses the
    project's .venv/bin/python3 with cwd=project_root so the import
    sees the same module layout as the running server would.

    Why this matters: the AI coder repeatedly invents framework APIs
    that don't exist (`from tina4_python.orm import db`, `model.Model`,
    `template()` without import, etc). Each broken write becomes a
    500 error the user only discovers by hitting the URL. Running
    `python3 -c "import foo"` right after write catches it inline and
    surfaces the real Python error in the file_write response — the
    LLM sees the error on its next turn and can retry with context.
    """
    if not rel_path.endswith(".py"):
        return None
    if not rel_path.startswith("src/"):
        return None
    name = Path(rel_path).name
    if name in ("__init__.py", "conftest.py") or name.startswith("test_"):
        return None
    # Convert "src/routes/foo.py" → "src.routes.foo"
    module = rel_path[:-3].replace("/", ".")
    venv_py = project_root / ".venv" / "bin" / "python3"
    if not venv_py.exists():
        return None  # no venv → can't verify reliably; skip silently
    import subprocess
    try:
        proc = subprocess.run(
            [str(venv_py), "-c", f"import {module}"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return f"verification subprocess failed: {e}"
    if proc.returncode == 0:
        return None
    # Pull the LAST meaningful traceback line — that's where the
    # actual error is (e.g. "ImportError: cannot import name 'db'").
    err = (proc.stderr or "").strip().splitlines()
    if not err:
        return f"import failed (exit {proc.returncode}, no stderr)"
    # Find the final "ErrorType: message" line.
    for line in reversed(err):
        if ":" in line and not line.startswith(" ") and not line.startswith("\t"):
            return line.strip()
    return err[-1].strip()


def _agent_backup(project_root: Path, target: Path) -> str | None:
    """Copy `target` into `.tina4/backups/` with a timestamped name.

    Returns the relative backup path on success, None on failure.
    """
    try:
        if not target.is_file():
            return None
        backup_dir = project_root / ".tina4" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        try:
            rel = target.relative_to(project_root)
        except ValueError:
            rel = Path(target.name)
        safe = str(rel).replace("/", "__").replace("\\", "__")
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        backup_path = backup_dir / f"{safe}.{ts}.bak"
        backup_path.write_bytes(target.read_bytes())
        return f".tina4/backups/{backup_path.name}"
    except Exception as e:
        _agent_log(project_root, "write.backup_failed", f"{target}: {e}")
        return None


def register_dev_tools(server):
    """Register all built-in dev tools on the given McpServer."""

    project_root = Path(os.getcwd()).resolve()

    # Paths that look like prose rather than filesystem paths. AI
    # agents occasionally pass natural language ("The plan requires
    # implementing...") as `path` to file_write and produce folders
    # with prose for names. We reject anything with whitespace,
    # backticks, or other obviously-wrong characters, plus anything
    # with an implausibly long segment.
    _SANE_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9._\-]+$")

    def _looks_like_prose(rel_path: str) -> str | None:
        """Return an error string if the path looks wrong, else None."""
        if not rel_path or not rel_path.strip():
            return "path is empty"
        if len(rel_path) > 300:
            return f"path too long ({len(rel_path)} chars); use a real filename"
        for bad in ("`", "\n", "\t", "  ", " — ", " (", " [", "?", "*", "<", ">", "|"):
            if bad in rel_path:
                return f"path contains illegal character sequence {bad!r} — looks like prose, not a filename"
        for seg in rel_path.split("/"):
            if not seg or seg in (".", ".."):
                continue
            if len(seg) > 80:
                return f"path segment too long: {seg[:60]!r}… — use a short filename"
            if not _SANE_PATH_SEGMENT.match(seg):
                return f"path segment {seg!r} contains disallowed characters — stick to [A-Za-z0-9._-]"
        return None

    def _normalize_coder_path(rel_path: str) -> str:
        """Rewrite bare top-level Tina4-conventional directories into
        their `src/<dir>/` canonical form. The framework's auto-discovery
        only scans `src/`, so a file at `templates/foo.twig` is dead
        weight — the framework never loads it. The coder agent drifts
        off the convention under "fix it" load, so we catch the slip
        here and log it.

        Mirrors normalize_coder_path() in the Rust agent — keep them
        in sync if the rules ever change.

        Returns the normalized path, or the original if no rewrite
        applied. Logs the rewrite to .tina4/agent.log so the user
        (and the supervisor on the next turn) can see what landed
        where vs what the coder asked for.
        """
        # Already canonical, or living at project root by design.
        passthrough_prefixes = ("src/", "migrations/", "plan/", "tests/",
                                "test/", ".tina4/")
        passthrough_files = {"app.py", "app.ts", "app.rb", "index.php",
                             "composer.json", "package.json", "Gemfile",
                             "pyproject.toml", "requirements.txt",
                             ".env", ".env.example"}
        if any(rel_path.startswith(p) for p in passthrough_prefixes):
            return rel_path
        if rel_path in passthrough_files:
            return rel_path
        # Bare top-level Tina4-conventional dirs → src/<dir>/
        for d in ("routes", "orm", "templates", "seeds", "controllers",
                  "models", "middleware"):
            if rel_path.startswith(f"{d}/"):
                rewritten = f"src/{rel_path}"
                _agent_log(project_root, "write.path_normalized",
                           f"{rel_path} → {rewritten}")
                return rewritten
        return rel_path

    def _safe_path(rel_path: str) -> Path:
        """Resolve a path and ensure it's within the project directory
        AND looks like a real filesystem path (not prose). Callers
        should run `_normalize_coder_path` FIRST so the prose check
        sees the final path; otherwise rel_path inside the caller's
        log lines won't match where the file actually lands."""
        err = _looks_like_prose(rel_path)
        if err:
            raise ValueError(f"Invalid path {rel_path!r}: {err}")
        resolved = (project_root / rel_path).resolve()
        root = project_root.resolve()
        # Path-COMPONENT containment (is_relative_to), not a string prefix.
        # str.startswith() would let a sibling dir like /srv/app-secrets pass
        # the guard for a project_root of /srv/app.
        if resolved != root and root not in resolved.parents:
            raise ValueError(f"Path escapes project directory: {rel_path}")
        return resolved

    def _redact_env(key: str, value: str) -> str:
        """Redact sensitive environment variable values."""
        sensitive = ("secret", "password", "token", "key", "credential", "api_key")
        if any(s in key.lower() for s in sensitive):
            return "***REDACTED***"
        return value

    # ── Database Tools ──────────────────────────────────────────

    def database_query(sql: str, params: str = "[]") -> dict:
        """Execute a read-only SQL query (SELECT/WITH) and return results.

        Enforces read-only: any non-SELECT statement, or a stacked second
        statement, is rejected. Use `database_execute` for writes.
        """
        import re as _re
        from tina4_python.orm.model import ORM
        db = ORM._get_db() if hasattr(ORM, "_get_db") else None
        if db is None:
            return {"error": "No database connection"}
        cleaned = _re.sub(r"/\*.*?\*/", " ", sql or "", flags=_re.S)
        cleaned = _re.sub(r"--[^\n]*", " ", cleaned).strip().rstrip(";").strip()
        if ";" in cleaned:
            return {"error": "database_query rejects multiple statements"}
        if not _re.match(r"(?is)^(select|with)\b", cleaned):
            return {"error": "database_query only runs read-only SELECT/WITH queries; use database_execute for writes"}
        param_list = json.loads(params) if isinstance(params, str) else params
        result = db.fetch(cleaned, param_list)
        return {"records": result.to_array(), "count": result.count}

    def database_execute(sql: str, params: str = "[]") -> dict:
        """Execute arbitrary SQL (INSERT/UPDATE/DELETE/DDL). Localhost only."""
        from tina4_python.orm.model import ORM
        db = ORM._get_db() if hasattr(ORM, "_get_db") else None
        if db is None:
            return {"error": "No database connection"}
        param_list = json.loads(params) if isinstance(params, str) else params
        try:
            result = db.execute(sql, param_list)
            db.commit()
        except Exception as e:
            # execute() raises on SQL error — return a clean MCP error payload.
            return {"error": str(e)}
        return {"success": True, "affected_rows": result.count if hasattr(result, "count") else 0}

    def database_tables() -> list:
        """List all database tables."""
        from tina4_python.orm.model import ORM
        db = ORM._get_db() if hasattr(ORM, "_get_db") else None
        if db is None:
            return {"error": "No database connection"}
        return db.get_tables()

    def database_columns(table: str) -> list:
        """Get column definitions for a table."""
        from tina4_python.orm.model import ORM
        db = ORM._get_db() if hasattr(ORM, "_get_db") else None
        if db is None:
            return {"error": "No database connection"}
        return db.get_columns(table)

    # ── Route Tools ─────────────────────────────────────────────

    def route_list() -> list:
        """List all registered routes with methods and paths."""
        from tina4_python.core.router import Router
        routes = []
        for route in Router.get_routes():
            routes.append({
                "method": route.get("method", ""),
                "path": route.get("path", ""),
                "auth_required": route.get("auth_required", False),
            })
        return routes

    def route_test(method: str, path: str, body: str = "", headers: str = "{}") -> dict:
        """Call a route and return the response (status, body, headers)."""
        from tina4_python.test_client import TestClient
        client = TestClient()
        header_dict = json.loads(headers) if isinstance(headers, str) else headers
        method = method.upper()
        if method == "GET":
            r = client.get(path, headers=header_dict)
        elif method == "POST":
            r = client.post(path, body=body, headers=header_dict)
        elif method == "PUT":
            r = client.put(path, body=body, headers=header_dict)
        elif method == "DELETE":
            r = client.delete(path, headers=header_dict)
        else:
            return {"error": f"Unsupported method: {method}"}
        return {"status": r.status, "body": r.text(), "content_type": r.content_type}

    def swagger_spec() -> dict:
        """Return the full OpenAPI 3.0.3 JSON specification."""
        from tina4_python.swagger import Swagger
        return Swagger.generate()

    # ── Template Tools ──────────────────────────────────────────

    def template_render(template: str, data: str = "{}") -> str:
        """Render a template string with the given data."""
        from tina4_python.frond import Frond
        engine = Frond("src/templates")
        ctx = json.loads(data) if isinstance(data, str) else data
        return engine.render_string(template, ctx)

    # ── File Tools ──────────────────────────────────────────────

    def file_read(path: str) -> str:
        """Read a project file. Path is relative to project root."""
        p = _safe_path(path)
        if not p.exists():
            return f"File not found: {path}"
        if not p.is_file():
            return f"Not a file: {path}"
        return p.read_text(encoding="utf-8", errors="replace")

    def file_write(path: str, content: str) -> dict:
        """Write or update a project file with FULL file content.
        Warning: overwrites entirely — use file_patch for partial edits.

        Safety mechanisms before writing:
          1. **Backup** — if the file exists, copy its prior content to
             `.tina4/backups/<flat-path>.<ts>.bak`.
          2. **Truncation guard** — refuse to overwrite a >200B file
             with content under 30% of its size (almost always an LLM
             truncation). Returns `{"error": ...}` with the original
             file untouched.
          3. **Audit log** — every attempt lands in `.tina4/agent.log`
             with old/new size + line counts.
        """
        # Coder-path normalization — rewrite bare top-level Tina4
        # directories (templates/, routes/, orm/, ...) into their src/
        # canonical form before we resolve. See _normalize_coder_path
        # for the full reasoning + rule list.
        path = _normalize_coder_path(path)
        p = _safe_path(path)
        old_bytes = p.read_bytes() if p.is_file() else b""
        old_size = len(old_bytes)
        old_lines = old_bytes.count(b"\n")
        new_bytes = content.encode()
        new_size = len(new_bytes)
        new_lines = new_bytes.count(b"\n")
        rel = str(p.relative_to(project_root)) if p.is_absolute() else path

        # Truncation guard — refuse suspicious shrinkage on non-trivial files.
        if old_size > 200 and (new_size * 100) < (old_size * 30):
            msg = (
                f"REFUSED {rel} (would shrink {old_size} → {new_size} bytes / "
                f"{old_lines} → {new_lines} lines, looks truncated)"
            )
            _agent_log(project_root, "write.refused", msg)
            return {"error": msg, "refused": True, "old_bytes": old_size, "new_bytes": new_size}

        # Backup before overwrite.
        backup_rel = _agent_backup(project_root, p) if old_size > 0 else None
        existed = old_size > 0

        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except Exception as e:
            _agent_log(project_root, "write.failed", f"{rel}: {e}")
            raise

        _record_plan_action("patched" if existed else "created", rel)
        _agent_log(project_root, "write.ok", (
            f"{rel} ({old_size}B/{old_lines}L → {new_size}B/{new_lines}L, "
            f"backup: {backup_rel or '(no prior file)'})"
        ))
        result = {"written": rel, "bytes": new_size}
        if backup_rel:
            result["backup"] = backup_rel
        # Post-write import verification — catches hallucinated
        # framework APIs (NameError / ImportError / AttributeError)
        # at write time, surfacing the error in the response so the
        # LLM sees it on its next turn and can fix the file.
        import_err = _verify_python_import(project_root, rel)
        if import_err:
            result["import_error"] = import_err
            _agent_log(project_root, "write.import_failed", f"{rel}: {import_err}")
        return result

    def file_patch(path: str, old_string: str, new_string: str, count: int = 1) -> dict:
        """Targeted edit — replace `old_string` with `new_string` in a project file.
        `old_string` must appear exactly `count` times (default 1) or the edit is
        rejected. Prefer this over file_write for small changes.

        Same defensive layer as `file_write`: backup before write + audit
        log. The truncation guard isn't needed here because the replace
        operation can't shrink the file by more than the length of
        `old_string` — it's bounded by definition.
        """
        path = _normalize_coder_path(path)
        p = _safe_path(path)
        if not p.exists() or not p.is_file():
            return {"error": f"File not found: {path}"}
        original = p.read_text(encoding="utf-8", errors="replace")
        occurrences = original.count(old_string)
        if occurrences == 0:
            return {"error": f"old_string not found in {path}"}
        if occurrences != count:
            return {
                "error": f"old_string appears {occurrences} times, expected {count}. "
                "Expand old_string to make it unique, or set count explicitly.",
            }
        updated = original.replace(old_string, new_string, count)
        rel = str(p.relative_to(project_root))

        # Backup before overwrite — same path as file_write so recovery
        # is uniform regardless of which tool touched the file.
        backup_rel = _agent_backup(project_root, p)

        try:
            p.write_text(updated, encoding="utf-8")
        except Exception as e:
            _agent_log(project_root, "patch.failed", f"{rel}: {e}")
            raise

        _record_plan_action("patched", rel)
        old_size = len(original.encode())
        new_size = len(updated.encode())
        _agent_log(project_root, "patch.ok", (
            f"{rel} (replaced {count}× old_string, {old_size}B → {new_size}B, "
            f"backup: {backup_rel or '(none)'})"
        ))
        result = {
            "patched": rel,
            "replacements": count,
            "bytes": new_size,
        }
        if backup_rel:
            result["backup"] = backup_rel
        # Same post-write verification as file_write (see comment there).
        import_err = _verify_python_import(project_root, rel)
        if import_err:
            result["import_error"] = import_err
            _agent_log(project_root, "patch.import_failed", f"{rel}: {import_err}")
        return result

    def file_list(path: str = ".") -> list:
        """List files in a directory. Path is relative to project root."""
        p = _safe_path(path)
        if not p.exists():
            return {"error": f"Directory not found: {path}"}
        if not p.is_dir():
            return {"error": f"Not a directory: {path}"}
        entries = []
        for entry in sorted(p.iterdir()):
            entries.append({
                "name": entry.name,
                "type": "dir" if entry.is_dir() else "file",
                "size": entry.stat().st_size if entry.is_file() else 0,
            })
        return entries

    def asset_upload(filename: str, content: str, encoding: str = "utf-8") -> dict:
        """Upload a file to src/public/. Content is text or base64 for binary."""
        target = _safe_path(f"src/public/{filename}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if encoding == "base64":
            import base64
            target.write_bytes(base64.b64decode(content))
        else:
            target.write_text(content, encoding="utf-8")
        return {"uploaded": str(target.relative_to(project_root)), "bytes": target.stat().st_size}

    # ── Migration Tools ─────────────────────────────────────────

    def migration_status() -> list:
        """List pending and completed migrations."""
        from tina4_python.orm.model import ORM
        from tina4_python.migration.runner import MigrationRunner
        db = ORM._database
        if db is None:
            return {"error": "No database connection"}
        runner = MigrationRunner(db)
        return runner.status() if hasattr(runner, "status") else {"info": "Migration status not available"}

    def migration_create(description: str) -> dict:
        """Create a new migration file. Refuses to create a duplicate
        for a description whose slug already exists in migrations/ —
        the AI gets an error pointing at the existing file so it can
        edit that one rather than spawning a second migration for the
        same schema change."""
        from tina4_python.migration import create_migration
        import re as _re
        slug = _re.sub(r"[^a-z0-9]+", "_", (description or "").lower()).strip("_")
        mig_dir = project_root / "migrations"
        if mig_dir.is_dir() and slug:
            # Compare against existing migration slugs (strip the
            # leading timestamp and .sql/.down.sql extension). Reuse
            # if an exact slug OR a clearly-equivalent slug exists.
            existing: list[str] = []
            for p in sorted(mig_dir.glob("*.sql")):
                name = p.name
                # Files look like "20260417175842_create_contact_messages_table.sql".
                # Strip the timestamp prefix (14 digits + underscore) and the suffix.
                after = _re.sub(r"^\d{14}_", "", name)
                after = _re.sub(r"\.(down\.)?sql$", "", after)
                existing_slug = _re.sub(r"[^a-z0-9]+", "_", after.lower()).strip("_")
                if existing_slug == slug or existing_slug == slug + "_table" or slug == existing_slug + "_table":
                    existing.append(str(p.relative_to(project_root)))
            if existing:
                return {
                    "ok": False,
                    "error": (
                        f"Migration for '{description}' already exists: {existing[0]}. "
                        "Edit it with file_patch / file_write instead of creating a duplicate."
                    ),
                    "existing": existing,
                }
        filename = create_migration(description)
        _record_plan_action("migration", filename, note=description)
        return {"created": filename}

    def _record_plan_action(action: str, path: str, note: str = "") -> None:
        """Forward a file event to the active plan's execution ledger.
        Silently no-ops when no plan is current. Never raises — a
        broken ledger must not block an otherwise-successful write."""
        try:
            from tina4_python.dev_admin import plan as _plan
            _plan.record_action(action, path, note=note)
        except Exception:
            pass

    def migration_run() -> dict:
        """Run all pending migrations."""
        from tina4_python.orm.model import ORM
        from tina4_python.migration import Migration
        db = ORM._database
        if db is None:
            return {"error": "No database connection"}
        result = Migration(db).migrate()
        return {"result": str(result)}

    # ── Queue Tools ─────────────────────────────────────────────

    def queue_status(topic: str = "default") -> dict:
        """Get queue size by status."""
        try:
            from tina4_python.queue import Queue
            q = Queue(topic=topic)
            return {
                "topic": topic,
                "pending": q.size("pending"),
                "completed": q.size("completed"),
                "failed": q.size("failed"),
            }
        except Exception as e:
            return {"error": str(e)}

    # ── Session/Cache Tools ─────────────────────────────────────

    def session_list() -> list:
        """List active sessions."""
        session_dir = Path("data/sessions")
        if not session_dir.exists():
            return []
        sessions = []
        for f in session_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                sessions.append({"id": f.stem, "data": data})
            except (json.JSONDecodeError, OSError):
                sessions.append({"id": f.stem, "error": "corrupt"})
        return sessions

    def cache_stats() -> dict:
        """Get response cache statistics."""
        try:
            from tina4_python.cache import cache_stats as _stats
            return _stats()
        except Exception as e:
            return {"error": str(e)}

    # ── ORM Tools ───────────────────────────────────────────────

    def orm_describe() -> list:
        """List all ORM models with their fields and types."""
        from tina4_python.orm.model import ORM
        models = []
        for cls in ORM.__subclasses__():
            fields = []
            for name, field in cls._fields.items():
                fields.append({
                    "name": name,
                    "type": type(field).__name__,
                    "primary_key": getattr(field, "primary_key", False),
                })
            models.append({
                "class": cls.__name__,
                "table": getattr(cls, "table_name", cls.__name__.lower()),
                "fields": fields,
            })
        return models

    # ── Debugging Tools ─────────────────────────────────────────

    def log_tail(lines: int = 50) -> list:
        """Read recent log entries."""
        log_file = Path("logs/debug.log")
        if not log_file.exists():
            return []
        all_lines = log_file.read_text(errors="replace").splitlines()
        return all_lines[-lines:]

    def error_log(limit: int = 20) -> list:
        """Recent errors/exceptions with stack traces."""
        try:
            from tina4_python.dev_admin import DevAdmin
            if hasattr(DevAdmin, "broken_tracker"):
                return DevAdmin.broken_tracker.get(limit=limit)
        except Exception:
            pass
        return []

    def env_list() -> dict:
        """List environment variables (sensitive values redacted)."""
        return {k: _redact_env(k, v) for k, v in sorted(os.environ.items())}

    # ── Data Tools ──────────────────────────────────────────────

    def seed_table(table: str, count: int = 10) -> dict:
        """Seed a table with fake data."""
        try:
            from tina4_python.seeder import seed_table as _seed
            from tina4_python.orm.model import ORM
            db = ORM._database
            if db is None:
                return {"error": "No database connection"}
            inserted = _seed(db, table, count)
            return {"table": table, "inserted": inserted}
        except Exception as e:
            return {"error": str(e)}

    # ── Current-project introspection ───────────────────────────

    def git_status() -> dict:
        """Show git working-tree state: current branch, modified/untracked
        files, last 5 commits. Returns {error} if the project isn't a git
        repo. Use when the user asks 'what changed?' or 'what am I working on?'"""
        import subprocess
        try:
            def _g(args):
                return subprocess.run(
                    ["git", *args], cwd=project_root,
                    capture_output=True, text=True, timeout=3,
                ).stdout.strip()
            # `git rev-parse` fails fast when we're not in a repo
            inside = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=project_root, capture_output=True, text=True, timeout=3,
            )
            if inside.returncode != 0:
                return {"error": "Not a git repository"}
            return {
                "branch": _g(["branch", "--show-current"]),
                "status": _g(["status", "--porcelain"]).splitlines(),
                "recent_commits": _g(["log", "--oneline", "-5"]).splitlines(),
            }
        except (OSError, subprocess.SubprocessError) as e:
            return {"error": f"git unavailable: {e}"}

    def deps_list() -> dict:
        """List the project's declared Python dependencies by reading
        pyproject.toml. Use when the user asks 'what's installed?' or
        'do I have X?' before adding a new dependency."""
        pp = _safe_path("pyproject.toml")
        if not pp.exists():
            return {"error": "No pyproject.toml at project root"}
        try:
            import tomllib
        except ImportError:  # pragma: no cover — 3.11+ always has tomllib
            return {"error": "tomllib not available"}
        try:
            data = tomllib.loads(pp.read_text(encoding="utf-8"))
        except Exception as e:
            return {"error": f"Failed to parse pyproject.toml: {e}"}
        project = data.get("project", {}) or {}
        return {
            "name": project.get("name", ""),
            "version": project.get("version", ""),
            "requires_python": project.get("requires-python", ""),
            "dependencies": project.get("dependencies", []),
            "optional_dependencies": project.get("optional-dependencies", {}),
        }

    # ── Plan management — persistent, current-plan-aware ──────
    #
    # A plan/ folder at the project root holds markdown plans, one of
    # which is "current" (filename stored in plan/.current). The
    # current plan is injected into every chat system prompt so the
    # AI keeps working on the same goal across turns.

    def plan_current() -> dict:
        """Return the active plan with steps + progress + what's next.
        If no plan is active returns {current: null}."""
        from tina4_python.dev_admin import plan as _plan
        return _plan.current()

    def plan_list() -> list:
        """All plans in plan/, with step progress + which one is current."""
        from tina4_python.dev_admin import plan as _plan
        return _plan.list_plans()

    def plan_create(title: str, goal: str = "", steps: list | None = None, make_current: bool = True) -> dict:
        """Create a new plan markdown file in plan/ and (by default) make
        it the active plan. ``steps`` is a list of short strings."""
        from tina4_python.dev_admin import plan as _plan
        return _plan.create(title, goal=goal, steps=steps or [], make_current=make_current)

    def plan_switch_to(name: str) -> dict:
        """Make a different plan the active one. ``name`` is the
        filename (with or without .md)."""
        from tina4_python.dev_admin import plan as _plan
        return _plan.set_current(name)

    def plan_complete_step(index: int) -> dict:
        """Tick step #index (0-based) on the current plan. Call this
        IMMEDIATELY after finishing a step, not at the end of the turn."""
        from tina4_python.dev_admin import plan as _plan
        return _plan.complete_step(index)

    def plan_add_step(text: str) -> dict:
        """Append a new unchecked step to the current plan — e.g. when
        you discover work that wasn't in the original breakdown."""
        from tina4_python.dev_admin import plan as _plan
        return _plan.add_step(text)

    def plan_note(text: str) -> dict:
        """Append a timestamped breadcrumb to the current plan's Notes
        section — gotchas, decisions, links to save for later."""
        from tina4_python.dev_admin import plan as _plan
        return _plan.append_note(text)

    def plan_archive(name: str = "") -> dict:
        """Move a finished plan to plan/done/. Defaults to the current
        plan. Clears the current pointer if it was this one."""
        from tina4_python.dev_admin import plan as _plan
        return _plan.archive(name)

    def plan_read(name: str) -> dict:
        """Full structured view of any plan (including archived)."""
        from tina4_python.dev_admin import plan as _plan
        return _plan.read(name)

    def plan_flesh(name: str = "", prompt: str = "") -> dict:
        """Auto-generate concrete build steps via qwen and append to an
        existing plan. Thin wrapper around ``plan.flesh`` — use when a
        plan has a title/goal but no steps yet."""
        from tina4_python.dev_admin import plan as _plan
        return _plan.flesh(name, prompt)

    # ── Project index — persistent "where is what" map ────────

    def index_rebuild() -> dict:
        """Walk the project, refresh the persistent index at
        .tina4/project_index.json. Safe to call often — incremental,
        mtime-based. Returns {added, updated, removed, total}."""
        from tina4_python.dev_admin.project_index import refresh
        return refresh()

    def index_search(query: str, limit: int = 20) -> list:
        """Find files by path, symbol, route, or summary. Ranked.
        Cheap, local — call this BEFORE grepping with file_list/file_read
        for 'where is X defined'-style questions."""
        from tina4_python.dev_admin.project_index import search
        return search(query, limit)

    def index_file(path: str) -> dict:
        """Full index entry for one file: symbols, routes, imports,
        sha256, mtime, extracted docstring. Cheaper than file_read
        when you only need the shape."""
        from tina4_python.dev_admin.project_index import file_entry
        return file_entry(path)

    def index_overview() -> dict:
        """Project shape in one call: total files, counts by language,
        number of declared routes and ORM models, 10 most-recently
        changed files. Answers 'what is this project?' instantly."""
        from tina4_python.dev_admin.project_index import overview
        return overview()

    def project_overview() -> dict:
        """One-shot snapshot of this project: name, version, deps, routes,
        ORM models, DB tables, pending migrations, recent errors. Call this
        FIRST when answering broad questions like 'what is this app?' or
        'show me the project structure' — it's ~10× cheaper than 8
        separate tool calls."""
        overview: dict = {}
        overview["system"] = system_info()
        try:
            overview["deps"] = deps_list()
        except Exception as e:
            overview["deps"] = {"error": str(e)}
        try:
            overview["routes"] = route_list()
        except Exception as e:
            overview["routes"] = {"error": str(e)}
        try:
            overview["models"] = orm_describe()
        except Exception as e:
            overview["models"] = {"error": str(e)}
        try:
            overview["tables"] = database_tables()
        except Exception as e:
            overview["tables"] = {"error": str(e)}
        try:
            overview["recent_errors"] = error_log(limit=5)
        except Exception as e:
            overview["recent_errors"] = {"error": str(e)}
        try:
            overview["git"] = git_status()
        except Exception as e:
            overview["git"] = {"error": str(e)}
        return overview

    # ── Framework docs (Tina4 knowledge base) ───────────────────
    #
    # Lets the AI look up real framework documentation on demand
    # instead of guessing from training data. Reads the markdown
    # that ships inside the installed tina4_python package, so the
    # answers match the exact framework version the project is using.

    def _framework_doc_paths() -> list:
        """Locate framework docs bundled with the installed package."""
        try:
            import tina4_python
            pkg_root = Path(tina4_python.__file__).resolve().parent
        except Exception:
            return []
        # Framework docs live at the REPO root, one level above the package
        candidates = [
            pkg_root.parent / "CLAUDE.md",
            pkg_root.parent / "AGENTS.md",
            pkg_root.parent / "CONVENTIONS.md",
            pkg_root.parent / "README.md",
            pkg_root / "CLAUDE.md",   # some installs bundle it inside
        ]
        return [p for p in candidates if p.is_file()]

    def docs_list() -> list:
        """List framework documentation files available for lookup."""
        return [
            {"name": p.name, "bytes": p.stat().st_size}
            for p in _framework_doc_paths()
        ]

    def docs_search(query: str, limit: int = 5, context_lines: int = 4) -> list:
        """Search framework docs for a query string. Returns ranked
        snippets with file + line number + surrounding context. Use this
        whenever the user asks 'how do I X in Tina4' before guessing."""
        if not query or len(query) < 2:
            return {"error": "query must be at least 2 characters"}
        needle = query.lower()
        hits = []
        for p in _framework_doc_paths():
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines):
                if needle in line.lower():
                    start = max(0, i - context_lines)
                    end = min(len(lines), i + context_lines + 1)
                    snippet = "\n".join(lines[start:end])
                    # Cheap rank: exact-case match > heading match > plain
                    score = 1
                    if query in line:
                        score += 1
                    if line.lstrip().startswith("#"):
                        score += 2
                    hits.append({
                        "file": p.name,
                        "line": i + 1,
                        "score": score,
                        "snippet": snippet,
                    })
        hits.sort(key=lambda h: -h["score"])
        return hits[:max(1, limit)]

    def docs_section(file: str, heading: str) -> dict:
        """Return a whole markdown section (from `## heading` to the next
        heading of the same or higher level). `file` is just the filename
        (e.g. 'CLAUDE.md') — use docs_list() to see what's available."""
        match = next((p for p in _framework_doc_paths() if p.name == file), None)
        if match is None:
            return {"error": f"Unknown doc file: {file}. Try docs_list() first."}
        text = match.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        heading_lc = heading.lower().strip()
        start = -1
        start_level = 0
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                # Count leading #'s
                level = len(stripped) - len(stripped.lstrip("#"))
                title = stripped[level:].strip().lower()
                if heading_lc in title:
                    start = i
                    start_level = level
                    break
        if start < 0:
            return {"error": f"Heading '{heading}' not found in {file}"}
        end = len(lines)
        for j in range(start + 1, len(lines)):
            stripped = lines[j].lstrip()
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                if level <= start_level:
                    end = j
                    break
        return {"file": file, "heading": lines[start].strip(), "body": "\n".join(lines[start:end])}

    # ── System Tools ────────────────────────────────────────────

    def system_info() -> dict:
        """Framework version, Python version, uptime, project path."""
        import sys
        import platform
        return {
            "framework": "tina4-python",
            "version": _get_version(),
            "python": sys.version,
            "platform": platform.platform(),
            "cwd": str(project_root),
            "debug": os.environ.get("TINA4_DEBUG", "false"),
        }

    def _get_version():
        try:
            from tina4_python import __version__
            return __version__
        except ImportError:
            return "unknown"

    # ── Live API RAG (per plan/v3/22-LIVE-API-RAG.md) ───────────
    # Wrappers around tina4_python.docs.Docs for AI-tool consumption.
    # See the api_* registrations below — these are distinct from
    # docs_* which searches prose markdown.

    def api_search(query: str, k: int = 5, source: str = "all", include_private: bool = False) -> list:
        from tina4_python.docs import Docs
        return Docs(project_root=str(project_root)).search(query, k=k, source=source, include_private=include_private)

    def api_class(name: str) -> dict:
        from tina4_python.docs import Docs
        spec = Docs(project_root=str(project_root)).class_spec(name)
        return spec if spec is not None else {"error": f"class not found: {name}"}

    def api_method(class_: str, name: str) -> dict:
        # `class` is a Python keyword — accept it via `class_` and let
        # the MCP layer pass either through to the wrapper.
        from tina4_python.docs import Docs
        spec = Docs(project_root=str(project_root)).method_spec(class_, name)
        return spec if spec is not None else {"error": f"method not found: {class_}.{name}"}

    # ── Register all tools ──────────────────────────────────────

    tools = [
        ("database_query", database_query, "Execute a read-only SQL query (SELECT)"),
        ("database_execute", database_execute, "Execute arbitrary SQL (INSERT/UPDATE/DELETE/DDL)"),
        ("database_tables", database_tables, "List all database tables"),
        ("database_columns", database_columns, "Get column definitions for a table"),
        ("route_list", route_list, "List all registered routes"),
        ("route_test", route_test, "Call a route and return the response"),
        ("swagger_spec", swagger_spec, "Return the OpenAPI 3.0.3 JSON spec"),
        ("template_render", template_render, "Render a template string with data"),
        ("file_read", file_read, "Read a project file"),
        ("file_write", file_write, "Write or update a project file (FULL contents — overwrites)"),
        ("file_patch", file_patch, "Targeted edit: replace old_string with new_string in a file"),
        ("file_list", file_list, "List files in a directory"),
        ("asset_upload", asset_upload, "Upload a file to src/public/"),
        ("migration_status", migration_status, "List pending and completed migrations"),
        ("migration_create", migration_create, "Create a new migration file"),
        ("migration_run", migration_run, "Run all pending migrations"),
        ("queue_status", queue_status, "Get queue size by status"),
        ("session_list", session_list, "List active sessions"),
        ("cache_stats", cache_stats, "Get response cache statistics"),
        ("orm_describe", orm_describe, "List all ORM models with fields and types"),
        ("log_tail", log_tail, "Read recent log entries"),
        ("error_log", error_log, "Recent errors and exceptions"),
        ("env_list", env_list, "List environment variables (secrets redacted)"),
        ("seed_table", seed_table, "Seed a table with fake data"),
        ("system_info", system_info, "Framework version, Python version, project info"),
        ("docs_list", docs_list, "List framework documentation files"),
        ("docs_search", docs_search, "Search Tina4 framework docs for a query string (use before guessing)"),
        ("docs_section", docs_section, "Return a full markdown section from a framework doc file"),
        ("git_status", git_status, "Show git branch, modified/untracked files, recent commits"),
        ("deps_list", deps_list, "List this project's declared Python dependencies"),
        ("project_overview", project_overview, "One-shot snapshot: deps, routes, models, tables, errors, git"),
        ("index_rebuild", index_rebuild, "Refresh the persistent project index (lazy, mtime-based)"),
        ("index_search", index_search, "Find files by path, symbol, route, or summary — use FIRST for 'where is X'"),
        ("index_file", index_file, "Full index entry for one file: symbols, routes, imports"),
        ("index_overview", index_overview, "Project shape: files by language, routes, models, recent edits"),
        ("plan_current", plan_current, "The active plan: title, steps (done/not), next step, progress"),
        ("plan_list", plan_list, "All plans in plan/ with progress and which one is active"),
        ("plan_create", plan_create, "Create a new markdown plan in plan/ and make it active"),
        ("plan_switch_to", plan_switch_to, "Make a different plan the active one"),
        ("plan_complete_step", plan_complete_step, "Tick a step as done (call the moment the step finishes)"),
        ("plan_add_step", plan_add_step, "Append a new unchecked step to the current plan"),
        ("plan_note", plan_note, "Append a timestamped note/breadcrumb to the current plan"),
        ("plan_archive", plan_archive, "Move a finished plan to plan/done/ and clear the current pointer"),
        ("plan_read", plan_read, "Full structured view of any plan by filename"),
        ("plan_flesh", plan_flesh, "Auto-generate concrete build steps via qwen and append them to an existing plan — use when a plan has a title/goal but no steps yet"),

        # ── Live API RAG (per plan/v3/22-LIVE-API-RAG.md) ──
        # Distinct from docs_* (prose markdown search). api_* tools
        # query the live framework reflection — actual class/method
        # signatures, file/line locations, source tagging (framework
        # vs user). Use api_* for "what's the signature of X?" and
        # docs_* for "explain queues conceptually".
        ("api_search", api_search, "Live API search — finds framework + user classes/methods by name/summary. Use BEFORE guessing a method exists."),
        ("api_class", api_class, "Live class reflection — returns full method list + signatures for an FQN."),
        ("api_method", api_method, "Live method reflection — returns signature, params, return type, file, line."),
    ]

    for name, handler, description in tools:
        server.register_tool(name, handler, description)
