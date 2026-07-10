# Tina4 CLI — Command-line interface for project management.
"""
CLI commands for development workflow.

    tina4python init              # Scaffold a new project
    tina4python serve             # Start dev server
    tina4python migrate           # Run pending migrations
    tina4python migrate:create    # Create a migration file
    tina4python migrate:rollback  # Rollback last batch
    tina4python migrate:status    # Show completed and pending migrations
    tina4python seed              # Run seeders
    tina4python routes            # List registered routes
    tina4python test              # Run tests
    tina4python generate          # Generate scaffolding
    tina4python ai                # Detect AI tools and install context
"""
import os
import re
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# ── Field type mapping ────────────────────────────────────────────────
FIELD_TYPE_MAP = {
    "string":   {"orm": "StringField",   "sql": "TEXT",    "default": "''"},
    "str":      {"orm": "StringField",   "sql": "TEXT",    "default": "''"},
    "int":      {"orm": "IntegerField",  "sql": "INTEGER", "default": "0"},
    "integer":  {"orm": "IntegerField",  "sql": "INTEGER", "default": "0"},
    "float":    {"orm": "NumericField",  "sql": "REAL",    "default": "0"},
    "numeric":  {"orm": "NumericField",  "sql": "REAL",    "default": "0"},
    "decimal":  {"orm": "NumericField",  "sql": "REAL",    "default": "0"},
    "bool":     {"orm": "BooleanField",  "sql": "INTEGER", "default": "0"},
    "boolean":  {"orm": "BooleanField",  "sql": "INTEGER", "default": "0"},
    "text":     {"orm": "TextField",     "sql": "TEXT",    "default": "''"},
    "datetime": {"orm": "DateTimeField", "sql": "TEXT",    "default": "NULL"},
    "blob":     {"orm": "BlobField",     "sql": "BLOB",    "default": "NULL"},
}


# ── Helpers ───────────────────────────────────────────────────────────

def _to_snake(name: str) -> str:
    """CamelCase → snake_case: ProductCategory → product_category."""
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _to_table(name: str) -> str:
    """Class name → singular table name: Product → product."""
    return _to_snake(name)


def _parse_fields(fields_str: str) -> list[tuple[str, str]]:
    """Parse 'name:string,price:float' → [('name','string'), ('price','float')]."""
    if not fields_str or not fields_str.strip():
        return []
    result = []
    for part in fields_str.split(","):
        part = part.strip()
        if ":" in part:
            name, typ = part.split(":", 1)
            result.append((name.strip(), typ.strip().lower()))
        elif part:
            result.append((part.strip(), "string"))
    return result


def _parse_flags(args: list[str]) -> tuple[dict, list[str]]:
    """Parse --key value and --flag from args. Returns (flags, positional)."""
    # Boolean-only flags that never take a value argument
    boolean_flags = {"no-browser", "no-reload", "production", "managed", "all", "clear", "json",
                     "public", "no-migration"}

    flags = {}
    positional = []
    i = 0
    while i < len(args):
        if args[i].startswith("--"):
            key = args[i][2:]
            if key in boolean_flags:
                flags[key] = True
                i += 1
            elif i + 1 < len(args) and not args[i + 1].startswith("--"):
                flags[key] = args[i + 1]
                i += 2
            else:
                flags[key] = True
                i += 1
        else:
            positional.append(args[i])
            i += 1
    return flags, positional


def _ai_fill(fn: str, intent: str, use: str, raise_msg: str, *,
             given: str = "", ret: str = "", ground: str = "",
             indent: str = "    ") -> str:
    """Return the canonical AI-FILL placeholder block for a LOGIC-shaped stub.

    A tight, grounded *fill-spec* — not a vague ``# TODO`` — so a coding agent
    (or dev) completes it correctly and idiomatically. ``raise
    NotImplementedError`` makes an unfilled scaffold fail LOUD, and the greppable
    ``AI-FILL`` banner lets a human/agent jump to every gap in a file. ≤ 6
    comment lines; ``Use:`` names only REAL Tina4 symbols (verified in source).

        {indent}# ─── AI-FILL: <fn> ───────────────────────────────
        {indent}# Intent:  <what this must do>
        {indent}# Given:   <inputs + shape>
        {indent}# Use:     <named REAL Tina4 API — the idiomatic path>
        {indent}# Return:  <exact return value + status>
        {indent}# Ground:  tina4_context("<intent>", "python") · skill tina4-developer-python
        {indent}raise NotImplementedError("<feature>: <what>")   # remove when done
        {indent}# ─────────────────────────────────────────────────
    """
    bar = "─" * 60
    head = f"{indent}# ─── AI-FILL: {fn} "
    head = head + "─" * max(4, 66 - len(head))
    lines = [head, f"{indent}# Intent:  {intent}"]
    if given:
        lines.append(f"{indent}# Given:   {given}")
    lines.append(f"{indent}# Use:     {use}")
    if ret:
        lines.append(f"{indent}# Return:  {ret}")
    if ground:
        lines.append(f"{indent}# Ground:  {ground}")
    lines.append(f'{indent}raise NotImplementedError("{raise_msg}")   # remove when done')
    lines.append(f"{indent}# {bar}")
    return "\n".join(lines) + "\n"


def _extend(note: str, hint: str = "", indent: str = "    ") -> str:
    """Return the lighter EXTEND marker for CRUD-shaped WORKING code.

    Marks the natural extension point in generated code that already runs — NO
    ``NotImplementedError`` (the boilerplate IS the feature); just a greppable
    hint at where custom validation / business rules go.
    """
    head = f"{indent}# ─── EXTEND: {note} "
    head = head + "─" * max(4, 66 - len(head))
    out = head + "\n"
    if hint:
        out += f"{indent}# {hint}\n"
    return out


def _parse_every(every: str) -> int:
    """Parse a --every duration ('5m', '30s', '2h', '1d', or bare seconds) → seconds.

    Falls back to 60s on an empty/unparseable value so a scaffold always has a
    valid interval for ServiceRunner.register(interval=...).
    """
    if not every:
        return 60
    every = str(every).strip().lower()
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        if every[-1] in units:
            return max(1, int(float(every[:-1]) * units[every[-1]]))
        return max(1, int(float(every)))
    except (ValueError, IndexError):
        return 60


def _kill_process_on_port(port: int) -> bool:
    """Kill any process listening on the given port. Returns True if killed."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            for pid in pids:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
            import time
            time.sleep(0.5)
            print(f"  ⚠ Killed existing process on port {port} (PID: {', '.join(pids)})")
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return False


# ── Main entry point ─────────────────────────────────────────────────

def main():
    """CLI entry point."""
    args = sys.argv[1:]
    if not args:
        _help()
        return

    command = args[0].lower()
    cmd_args = args[1:]

    # Dispatch from the single-source-of-truth COMMANDS registry (defined at the
    # bottom of this module). The same registry drives `_help` and the
    # `commands --json` manifest, so dispatch, help, and discovery never drift.
    spec = COMMANDS.get(command)
    if spec:
        spec["handler"](cmd_args)
    else:
        print(f"Unknown command: {command}")
        _help([])


def _env_migrate(args):
    """Rewrite a .env file in place, renaming pre-3.12 names to TINA4_ form.

    Usage: tina4python env-migrate [path]   (default path: .env)

    Backs the original up to <path>.bak before rewriting. Prints a diff of
    each rename. Idempotent — running twice is a no-op on the second run.
    """
    from tina4_python.core.server import _LEGACY_ENV_VARS
    target = Path(args[0]) if args else Path(".env")
    if not target.is_file():
        print(f"  no .env at {target}")
        return
    text = target.read_text(encoding="utf-8")
    backup = target.with_suffix(target.suffix + ".bak")
    backup.write_text(text, encoding="utf-8")
    print(f"  backup written: {backup}")

    renamed = 0
    new_lines = []
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line); continue
        if "=" not in stripped:
            new_lines.append(line); continue
        key = stripped.split("=", 1)[0].strip()
        if key in _LEGACY_ENV_VARS:
            new_key = _LEGACY_ENV_VARS[key]
            new_line = line.replace(key, new_key, 1)
            print(f"  {key:<28}  →  {new_key}")
            new_lines.append(new_line)
            renamed += 1
        else:
            new_lines.append(line)

    if renamed == 0:
        print("  nothing to rename — your .env is already on the new convention")
        backup.unlink()  # don't leave a noise backup
        return

    target.write_text("".join(new_lines), encoding="utf-8")
    print(f"\n  done: {renamed} rename(s) applied to {target}")
    print(f"  original kept at {backup} (delete once you've verified)")


def _help(args=None):
    """Print the human-readable command reference.

    Generated from the COMMANDS and GENERATORS registries — the SAME single
    source of truth that drives dispatch (`main`) and the `commands --json`
    manifest — so the help text can never drift from what the CLI actually does.
    """
    command_rows = [
        (f"{name} {spec.get('usage', '')}".rstrip(), spec["summary"])
        for name, spec in COMMANDS.items()
    ]
    generator_rows = [
        (f"generate {name} {spec.get('usage', '')}".rstrip(), spec["summary"])
        for name, spec in GENERATORS.items()
    ]
    # Align summaries in a column; a left cell longer than the cap overflows
    # cleanly (2-space gap) rather than pushing every other summary out.
    pad = min(46, max(len(left) for left, _ in command_rows + generator_rows))

    def row(left, summary):
        gap = pad if len(left) <= pad else len(left)
        return f"  {left:<{gap}}  {summary}"

    lines = ["", "Tina4 Python — CLI", "", "Usage: tina4python <command> [options]", "", "Commands:"]
    lines += [row(left, summary) for left, summary in command_rows]
    lines += ["", "Generators:"]
    lines += [row(left, summary) for left, summary in generator_rows]
    lines += [
        "",
        "Scaffolding-first: logic-shaped generators emit wiring + an AI-FILL placeholder",
        "(raise NotImplementedError) where the custom logic goes; CRUD-shaped ones emit",
        "working code. Writes are secure by default — use --public to open them.",
        "",
        "Field types: string, int, float, bool, text, datetime, blob",
        "Table names: singular by default (Product → product)",
        "",
        "https://tina4.com",
        "",
    ]
    print("\n".join(lines))


# ── Console ───────────────────────────────────────────────────────────

def _console(args=None):
    """Start an interactive REPL with the framework loaded."""
    import code
    import os

    # Load environment
    from tina4_python.dotenv import load_env
    load_env()

    # Import everything the user needs
    from tina4_python import get, post, put, patch, delete, Router, Database, ORM, Auth, Queue, Frond
    from tina4_python.debug import Log
    from tina4_python.api import Api
    from tina4_python.core.events import on, emit

    # Try to connect database from TINA4_DATABASE_URL
    db = None
    db_url = os.environ.get("TINA4_DATABASE_URL")
    if db_url:
        try:
            db = Database(db_url)
            print(f"  Database: {db_url}")
        except Exception as e:
            print(f"  Database: failed ({e})")

    # Auto-discover routes
    from tina4_python.core.server import _auto_discover
    _auto_discover("src")
    route_count = len(Router.get_routes())
    print(f"  Routes: {route_count} discovered")

    banner = (
        "\n  Tina4 Python Console\n"
        "  Type Python code. Framework is loaded.\n"
        "  Available: db, Router, ORM, Database, Auth, Api, Log, Queue\n"
        "  Exit: Ctrl+D or exit()\n"
    )

    local_vars = {
        "db": db, "Database": Database, "ORM": ORM, "Router": Router,
        "Auth": Auth, "Api": Api, "Log": Log, "Queue": Queue,
        "Frond": Frond, "get": get, "post": post, "put": put,
        "patch": patch, "delete": delete, "on": on, "emit": emit,
    }

    code.interact(banner=banner, local=local_vars)


# ── Metrics ───────────────────────────────────────────────────────────

def _metrics(args):
    """Report top code-quality offenders (complexity, size, maintainability, tests).

    tina4python metrics                       # human report, scans src/ (or framework)
    tina4python metrics --top 10              # only the worst 10
    tina4python metrics --path tina4_python   # scan a specific directory
    tina4python metrics --json                # machine-readable for CI
    tina4python metrics --fail-on warn        # exit 1 if any warn/error offender
    tina4python metrics --fail-on error       # exit 1 only on error-severity
    """
    import json
    from tina4_python.dev_admin import metrics as _m

    flags, _ = _parse_flags(args)

    top = int(flags["top"]) if "top" in flags and str(flags["top"]).isdigit() else 20
    as_json = "json" in flags
    path = flags.get("path", "src")
    fail_on = flags.get("fail-on")
    if fail_on not in (None, "warn", "error"):
        print(f"  invalid --fail-on '{fail_on}' (use warn or error)")
        sys.exit(2)

    result = _m.offenders(path, top=top)
    summary = result["summary"]
    found = result["offenders"]

    if "error" in summary:
        print(f"  metrics error: {summary['error']}")
        sys.exit(2)

    # Decide exit code from the FULL offender set, not just the printed top-N.
    # full_analysis is cached, so this reuses the same analysis.
    all_offenders = _m.offenders(path, top=summary["total_offenders"] or 1)["offenders"]
    severities = {o["severity"] for o in all_offenders}
    exit_code = 0
    if fail_on == "warn" and ({"warn", "error"} & severities):
        exit_code = 1
    elif fail_on == "error" and ("error" in severities):
        exit_code = 1

    if as_json:
        print(json.dumps({"summary": summary, "offenders": found}, indent=2))
        sys.exit(exit_code)

    # ── Human report ──────────────────────────────────────────────────
    use_color = sys.stdout.isatty()

    def _c(text, code):
        return f"\033[{code}m{text}\033[0m" if use_color else text

    sev_color = {"error": "31", "warn": "33", "info": "2"}  # red / yellow / dim

    print()
    print(f"  Tina4 Metrics — {summary['scan_mode']} scan ({summary['scan_root']})")
    print(f"  files: {summary['files_analyzed']}   "
          f"functions: {summary['total_functions']}   "
          f"avg complexity: {summary['avg_complexity']}   "
          f"avg maintainability: {summary['avg_maintainability']}")
    print(f"  offenders: {summary['total_offenders']} total"
          + (f" (showing top {len(found)})" if found else ""))
    print()

    if not found:
        print("  " + _c("✓ no offenders — clean", "32"))
        print()
        sys.exit(exit_code)

    # Compute a column width for the file:line cell so the table lines up.
    locs = [f"{o['file']}:{o['line']}" for o in found]
    loc_w = max(len("FILE:LINE"), max(len(s) for s in locs))
    kind_w = max(len("KIND"), max(len(o["kind"]) for o in found))

    header = f"  {'#':>3}  {'SEVERITY':<8}  {'KIND':<{kind_w}}  {'FILE:LINE':<{loc_w}}  DETAIL"
    print(_c(header, "1"))
    print("  " + "-" * (len(header) - 2))
    for i, o in enumerate(found, 1):
        sev = o["severity"]
        sev_cell = _c(f"{sev:<8}", sev_color[sev])
        print(f"  {i:>3}  {sev_cell}  {o['kind']:<{kind_w}}  "
              f"{locs[i - 1]:<{loc_w}}  {o['detail']}")
    print()
    sys.exit(exit_code)


# ── Init ──────────────────────────────────────────────────────────────

def _init(args):
    """Scaffold a new Tina4 project."""
    target = Path(args[0]) if args else Path(".")
    target.mkdir(parents=True, exist_ok=True)

    folders = [
        "src/routes", "src/orm", "src/templates", "src/templates/errors",
        "src/app", "src/middleware", "src/seeds", "src/scss",
        "public", "public/js", "public/css", "public/icons",
        "src/locales", "migrations", "tests", "data", "logs",
        "frontend", "docker/python", "docker/uv", "docker/poetry", "docker/distroless",
    ]
    for folder in folders:
        (target / folder).mkdir(parents=True, exist_ok=True)

    # Copy framework public assets into the project so they're visible
    framework_public = Path(__file__).parent.parent / "public"
    project_public = target / "src" / "public"
    assets_to_copy = [
        "css/tina4.css",
        "css/tina4.min.css",
        "js/tina4.min.js",
        "js/frond.min.js",
        "images/tina4-logo-icon.webp",
    ]
    for asset in assets_to_copy:
        src = framework_public / asset
        dst = project_public / asset
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.exists() and not dst.exists():
            import shutil
            shutil.copy2(src, dst)

    # Copy frontend README
    frontend_readme = target / "frontend" / "README.md"
    if not frontend_readme.exists():
        template_dir = Path(__file__).parent.parent / "templates" / "frontend"
        src_readme = template_dir / "README.md"
        if src_readme.exists():
            frontend_readme.write_text(src_readme.read_text(encoding="utf-8"), encoding="utf-8")

    # Create app.py
    app_file = target / "app.py"
    if not app_file.exists():
        app_file.write_text(
            '"""Tina4 Application."""\n'
            'from tina4_python.core import run\n\n'
            'if __name__ == "__main__":\n'
            '    run()\n',
            encoding="utf-8",
        )

    # Create .env — every framework env var is TINA4_-prefixed since v3.12.
    # The boot guard refuses to start with bare DATABASE_URL / SECRET set,
    # so a fresh project MUST get the prefixed names.
    env_file = target / ".env"
    if not env_file.exists():
        env_file.write_text(
            "# Tina4 Configuration\n"
            "TINA4_DEBUG=true\n"
            "TINA4_LOG_LEVEL=ALL\n"
            "TINA4_DATABASE_URL=sqlite:///data/app.db\n"
            'TINA4_SECRET=change-me-in-production\n',
            encoding="utf-8",
        )

    # Create .gitignore
    gitignore = target / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(
            ".env\n.env.local\n__pycache__/\n*.pyc\n.venv/\ndata/\nlogs/\n"
            "sessions/\nsecrets/\n*.db\n",
            encoding="utf-8",
        )

    # Copy Dockerfiles
    docker_src = Path(__file__).parent.parent / "templates" / "docker"
    for variant in ("python", "uv", "poetry", "distroless"):
        src_file = docker_src / variant / "Dockerfile"
        dst_file = target / "docker" / variant / "Dockerfile"
        if not dst_file.exists() and src_file.exists():
            dst_file.write_text(src_file.read_text(encoding="utf-8"), encoding="utf-8")

    # Root Dockerfile
    root_dockerfile = target / "Dockerfile"
    if not root_dockerfile.exists():
        root_dockerfile.write_text(
            'FROM python:3.13-slim AS build\nWORKDIR /app\n'
            'COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv\n'
            'COPY pyproject.toml uv.lock* ./\nRUN uv sync --frozen --no-dev\nCOPY . .\n\n'
            'FROM python:3.13-slim\nWORKDIR /app\n'
            'COPY --from=build /app .\nCOPY --from=build /usr/local/bin/uv /usr/local/bin/uv\n'
            'ENV PATH="/app/.venv/bin:$PATH"\nENV HOST=0.0.0.0\nENV PORT=7146\n'
            'EXPOSE 7146\nCMD ["python", "app.py"]\n',
            encoding="utf-8",
        )

    # .dockerignore
    root_dockerignore = target / ".dockerignore"
    if not root_dockerignore.exists():
        root_dockerignore.write_text(
            ".venv\n__pycache__\n.git\n.claude\n.env\n*.log\ntests\ntmp\n",
            encoding="utf-8",
        )

    # AI context
    from tina4_python.ai import install_context
    if "--ai" in args:
        created = install_context(str(target))
        if created:
            print("\nAI context installed for all supported tools:")
            for f in created:
                print(f"  + {f}")
    else:
        print("\n  Tip: run 'tina4python ai' to install AI coding assistant context files.")

    print(f"\nProject scaffolded at {target.resolve()}")
    print("  Run: tina4python serve")
    print("  Run: tina4python ai        (detect & install AI tool context)")


# ── Serve ─────────────────────────────────────────────────────────────

def _serve(args):
    """Start the development server."""
    os.environ.setdefault("TINA4_DEBUG", "true")
    os.environ.setdefault("TINA4_LOG_LEVEL", "ALL")

    flags, positional = _parse_flags(args)

    cli_host = flags.get("host")
    cli_port = int(flags["port"]) if "port" in flags else None

    # Positional port
    if not cli_port and positional and positional[0].isdigit():
        cli_port = int(positional[0])

    # --no-browser flag or env var
    no_browser = "no-browser" in flags
    if os.environ.get("TINA4_OPEN_BROWSER", "").lower() in ("false", "0", "no"):
        no_browser = True

    # --no-reload flag
    no_reload = "no-reload" in flags

    # Kill existing process on port
    port = cli_port or int(os.environ.get("PORT", os.environ.get("TINA4_PORT", "7146")))
    _kill_process_on_port(port)

    from tina4_python.core import run
    run(host=cli_host, port=cli_port, no_browser=no_browser, no_reload=no_reload)


# ── Migrate ───────────────────────────────────────────────────────────

def _migrate(args):
    """Run pending migrations."""
    _load_env()
    from tina4_python.database import Database
    from tina4_python.migration import Migration

    db_url = os.environ.get("TINA4_DATABASE_URL", "sqlite:///data/app.db")
    db = Database(db_url)
    mig_dir = args[0] if args else "migrations"
    ran = Migration(db, mig_dir).migrate()
    if ran:
        for f in ran:
            print(f"  Migrated: {f}")
        print(f"\n{len(ran)} migration(s) executed.")
    else:
        print("Nothing to migrate.")
    db.close()


def _migrate_create(args):
    """Create a new migration file."""
    if not args:
        print("Usage: tina4python migrate:create <description>")
        sys.exit(1)
    from tina4_python.migration import create_migration
    desc = " ".join(args)
    path = create_migration(desc, "migrations")
    print(f"Created: {path}")


def _migrate_rollback(args):
    """Rollback the last migration batch."""
    _load_env()
    from tina4_python.database import Database
    from tina4_python.migration import Migration

    db_url = os.environ.get("TINA4_DATABASE_URL", "sqlite:///data/app.db")
    db = Database(db_url)
    mig_dir = args[0] if args else "migrations"
    rolled = Migration(db, mig_dir).rollback()
    if rolled:
        for f in rolled:
            print(f"  Rolled back: {f}")
        print(f"\n{len(rolled)} migration(s) rolled back.")
    else:
        print("Nothing to rollback.")
    db.close()


def _migrate_status(args):
    """Show migration status."""
    _load_env()
    from tina4_python.database import Database
    from tina4_python.migration import Migration

    db_url = os.environ.get("TINA4_DATABASE_URL", "sqlite:///data/app.db")
    db = Database(db_url)
    result = Migration(db, args[0] if args else "migrations").status()
    completed, pending = result["completed"], result["pending"]

    if completed:
        print("\nCompleted migrations:")
        for m in completed:
            print(f"  [batch {m['batch']}] {m['migration_id']}  ({m['executed_at']})")
    else:
        print("\nNo completed migrations.")

    if pending:
        print("\nPending migrations:")
        for m in pending:
            print(f"  {m['migration_id']}  ({m['description']})")
    else:
        print("\nNo pending migrations.")

    print(f"\nTotal: {len(completed)} completed, {len(pending)} pending.")
    db.close()


# ── Seed / Routes / Test / Build ──────────────────────────────────────

def _seed(args):
    """Run seeders from src/seeds/."""
    _load_env()
    seed_dir = Path("src/seeds")
    if not seed_dir.is_dir():
        print("No src/seeds/ directory found.")
        return

    import importlib.util
    from tina4_python.database import Database

    db_url = os.environ.get("TINA4_DATABASE_URL", "sqlite:///data/app.db")
    db = Database(db_url)
    sys.path.insert(0, str(Path.cwd()))

    ran = 0
    for seed_file in sorted(seed_dir.glob("*.py")):
        if seed_file.name.startswith("_"):
            continue
        print(f"  Seeding: {seed_file.name}")
        spec = importlib.util.spec_from_file_location(seed_file.stem, str(seed_file))
        module = importlib.util.module_from_spec(spec)
        module.db = db
        spec.loader.exec_module(module)
        if hasattr(module, "run"):
            module.run(db)
        ran += 1
    db.close()
    print(f"\n{ran} seeder(s) executed.")


def _routes(args):
    """List all registered routes."""
    if Path("app.py").exists():
        sys.path.insert(0, str(Path.cwd()))
        import importlib
        importlib.import_module("app")

    from tina4_python.core.router import Router
    routes = Router.get_routes()
    if not routes:
        print("No routes registered.")
        return

    print(f"\n{'Method':<8} {'Path':<40} {'Auth':<8} {'Handler'}")
    print("-" * 80)
    for r in routes:
        auth = "Yes" if r.get("auth_required") else "No"
        handler_name = r["handler"].__name__ if r.get("handler") else "?"
        print(f"{r['method']:<8} {r['path']:<40} {auth:<8} {handler_name}")
    print(f"\n{len(routes)} route(s) registered.")


def _test(args):
    """Run the test suite."""
    subprocess.run([sys.executable, "-m", "pytest", "tests/"] + args)


def _build(args):
    """Build a distributable package."""
    try:
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--onefile", "app.py",
             "--name", "tina4app", "--hidden-import", "tina4_python"],
            check=True,
        )
        print("Built: dist/tina4app")
    except (subprocess.CalledProcessError, FileNotFoundError):
        subprocess.run([sys.executable, "-m", "build"], check=True)
        print("Built: dist/")


def _ai(args):
    """Install AI coding assistant context files."""
    from tina4_python.ai import show_menu, install_selected, install_context

    if args and args[0].lower() == "all":
        install_context(".")
    else:
        selection = show_menu(".")
        if selection:
            install_selected(".", selection)


# ── Generate (rich scaffolding) ───────────────────────────────────────

def _generate(args):
    """Generate scaffolding.

    CRUD-shaped generators (crud/form/view/migration/model/test/auth) emit
    working code — the boilerplate IS the feature. Logic-shaped generators
    (route/service/queue/validator/seeder/websocket/listener) scaffold the
    WIRING (real imports + registration + signature + error skeleton) and drop a
    single ``# your code here`` placeholder (``raise NotImplementedError``) where
    the custom logic goes, so an unfilled scaffold fails loud.
    """
    _all = ", ".join(GENERATORS)  # single source: the GENERATORS registry
    if not args:
        print("Usage: tina4python generate <what> <name> [options]")
        print(f"  Generators: {_all}")
        print('  Options:    --fields "name:string,price:float"  --model ModelName')
        print('              --public                 open a route\'s writes (default: secure)')
        print('              --every 5m | --cron "..."  service schedule')
        sys.exit(1)

    what = args[0].lower()

    # Auth doesn't require a name argument
    no_name_generators = {"auth"}
    if what not in no_name_generators and len(args) < 2:
        print(f"Usage: tina4python generate {what} <name> [options]")
        sys.exit(1)

    name = args[1] if len(args) > 1 else ""
    flags, _ = _parse_flags(args[2:] if len(args) > 2 else [])

    # Dispatch from the module-level GENERATORS registry (single source of truth
    # for the generate subcommands; also feeds `_help` and the manifest).
    gen_spec = GENERATORS.get(what)
    if gen_spec:
        gen_spec["handler"](name, flags)
    else:
        print(f"Unknown generator: {what}")
        print(f"  Available: {_all}")
        sys.exit(1)


def _gen_model(name: str, flags: dict):
    """Generate ORM model + matching migration.

    tina4python generate model Product
    tina4python generate model Product --fields "name:string,price:float,in_stock:bool"
    """
    fields = _parse_fields(flags.get("fields", ""))
    table = _to_table(name)

    # Determine which ORM field types we need to import
    used_types = {"IntegerField"}  # always need for id
    for _, ftype in fields:
        info = FIELD_TYPE_MAP.get(ftype, FIELD_TYPE_MAP["string"])
        used_types.add(info["orm"])
    if not fields:
        used_types.add("StringField")
    used_types.add("DateTimeField")  # for created_at

    imports = ", ".join(sorted(used_types))

    # Build field lines
    field_lines = [f"    id = IntegerField(primary_key=True, auto_increment=True)"]
    if fields:
        for fname, ftype in fields:
            info = FIELD_TYPE_MAP.get(ftype, FIELD_TYPE_MAP["string"])
            field_lines.append(f"    {fname} = {info['orm']}()")
    else:
        field_lines.append("    name = StringField()")
    field_lines.append("    created_at = DateTimeField()")

    # Write model file
    target = Path("src/orm")
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{name}.py"
    if path.exists():
        print(f"  ✗ File already exists: {path}")
        return

    content = (
        f"from tina4_python.orm import ORM, {imports}\n\n\n"
        f"class {name}(ORM):\n"
        f'    table_name = "{table}"\n'
        f"    # plural_table = True  # uncomment for plural: {table}s\n\n"
        + "\n".join(field_lines) + "\n"
    )
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ Created {path}")

    # Generate matching migration (unless --no-migration)
    if "no-migration" not in flags:
        _gen_migration(f"create_{table}", flags, fields_override=fields, table_override=table)


def _gen_route(name: str, flags: dict):
    """Generate CRUD route file — SECURE BY DEFAULT.

    tina4python generate route products
    tina4python generate route products --model Product
    tina4python generate route products --model Product --public   # open writes

    Writes (POST/PUT/DELETE) are Bearer-token-gated by default (the router
    gates them unless ``@noauth()``). Reads (GET) are public by default, so no
    decorator is emitted for them. ``--public`` re-adds ``@noauth()`` on the
    write handlers as the explicit opt-out — mirroring AutoCrud's ``public=True``
    (tina4_python/crud/__init__.py: secure-by-default write routes).
    """
    route_path = name.lstrip("/")
    singular = route_path.rstrip("s") if route_path.endswith("s") else route_path
    model = flags.get("model", "")
    public = bool(flags.get("public"))

    target = Path("src/routes")
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{route_path}.py"
    if path.exists():
        print(f"  ✗ File already exists: {path}")
        return

    # ``@noauth()`` is only imported/emitted when the caller opts writes public.
    w = "@noauth()\n" if public else ""  # write-handler auth decorator (opt-in)
    router_imports = "get, post, put, delete, noauth" if public else "get, post, put, delete"

    imports = f"from tina4_python.core.router import {router_imports}\n"
    imports += "from tina4_python.swagger import description, tags\n"
    if model:
        imports += f"from src.orm.{model} import {model}\n"

    # Secure-by-default posture note for the WRITE handler docstrings.
    write_doc = (
        "Public (--public): no token required."
        if public else
        "Secure-by-default: requires a Bearer token (use --public to open)."
    )

    # Route handlers
    if model:
        # WORKING code (the boilerplate IS the feature) + EXTEND markers at the
        # natural extension points (no NotImplementedError).
        ext_create = _extend(
            "validate / business rules before persist",
            'e.g. reject invalid input; ground: tina4_context("validate before create", "python")',
        )
        ext_update = _extend(
            "guard which fields / who may update",
            'e.g. enforce ownership; ground: tina4_context("authorize update", "python")',
        )
        content = f'''{imports}

@description("List all {route_path}")
@tags(["{route_path}"])
@get("/api/{route_path}")
async def list_{route_path}(request, response):
    """List all {route_path} with pagination."""
    page = int(request.params.get("page", 1))
    per_page = int(request.params.get("per_page", 20))
    offset = (page - 1) * per_page
    records, total = {model}.where("1=1", limit=per_page, offset=offset, with_count=True)
    return response({{
        "records": [r.to_dict() for r in records],
        "count": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, -(-total // per_page)),
    }})


@description("Get a {singular} by ID")
@tags(["{route_path}"])
@get("/api/{route_path}/{{id:int}}")
async def get_{singular}(request, response):
    """Get a single {singular} by ID."""
    {singular} = {model}.find_by_id(request.params["id"])
    if {singular} is None:
        return response({{"error": "Not found"}}, 404)
    return response({singular}.to_dict())


{w}@description("Create a new {singular}")
@tags(["{route_path}"])
@post("/api/{route_path}")
async def create_{singular}(request, response):
    """Create a new {singular}. {write_doc}"""
{ext_create}    item = {model}.create(request.body)
    return response(item.to_dict(), 201)


{w}@description("Update a {singular}")
@tags(["{route_path}"])
@put("/api/{route_path}/{{id:int}}")
async def update_{singular}(request, response):
    """Update a {singular} by ID. {write_doc}"""
    item = {model}.find_by_id(request.params["id"])
    if item is None:
        return response({{"error": "Not found"}}, 404)
{ext_update}    for key, value in request.body.items():
        if hasattr(item, key) and key != "id":
            setattr(item, key, value)
    item.save()
    return response(item.to_dict())


{w}@description("Delete a {singular}")
@tags(["{route_path}"])
@delete("/api/{route_path}/{{id:int}}")
async def delete_{singular}(request, response):
    """Delete a {singular} by ID. {write_doc}"""
    item = {model}.find_by_id(request.params["id"])
    if item is None:
        return response({{"error": "Not found"}}, 404)
    item.delete()
    return response(None, 204)
'''
    else:
        # CUSTOM route — no model. Every handler body is a LOGIC-shaped stub:
        # AI-FILL fill-spec + raise NotImplementedError (fails loud until filled).
        m = "".join(p.capitalize() for p in singular.split("_"))  # PascalCase hint
        b_list = _ai_fill(
            f"list_{route_path}",
            f"return the {route_path} collection (add pagination if it grows)",
            f"{m}.all()  or  {m}.where(sql, params, with_count=True)  (import {m} from src.orm.{m})",
            f"list_{route_path}: query and return the records",
            ret='response({"records": [r.to_dict() for r in rows]})',
            ground=f'tina4_context("list ORM records with pagination", "python")',
        )
        b_get = _ai_fill(
            f"get_{singular}",
            f"fetch one {singular} by id",
            f'{m}.find_by_id(request.params["id"])  (import {m} from src.orm.{m})',
            f"get_{singular}: fetch by id or 404",
            given='request.params["id"] -> int',
            ret='response(item.to_dict())  or  response({"error": "Not found"}, 404)',
            ground='tina4_context("find ORM record by id", "python")',
        )
        b_create = _ai_fill(
            f"create_{singular}",
            f"validate the body and persist a new {singular}",
            f"{m}.create(request.body)  (import {m} from src.orm.{m})",
            f"create_{singular}: persist and return the new record",
            given="request.body -> dict of fields",
            ret="response(item.to_dict(), 201)",
            ground='tina4_context("create ORM record and return 201", "python")',
        )
        b_update = _ai_fill(
            f"update_{singular}",
            f"load, mutate and save an existing {singular}",
            f'{m}.find_by_id(request.params["id"])  then set fields and item.save()',
            f"update_{singular}: apply changes and return the record",
            given='request.params["id"] -> int; request.body -> changed fields',
            ret="response(item.to_dict())  or  404",
            ground='tina4_context("update ORM record", "python")',
        )
        b_delete = _ai_fill(
            f"delete_{singular}",
            f"delete a {singular} by id",
            f'{m}.find_by_id(request.params["id"])  then item.delete()',
            f"delete_{singular}: delete and return 204",
            given='request.params["id"] -> int',
            ret="response(None, 204)  or  404",
            ground='tina4_context("delete ORM record", "python")',
        )
        content = f'''{imports}

@description("List all {route_path}")
@tags(["{route_path}"])
@get("/api/{route_path}")
async def list_{route_path}(request, response):
    """List all {route_path}."""
{b_list}

@description("Get a {singular} by ID")
@tags(["{route_path}"])
@get("/api/{route_path}/{{id:int}}")
async def get_{singular}(request, response):
    """Get a single {singular}."""
{b_get}

{w}@description("Create a new {singular}")
@tags(["{route_path}"])
@post("/api/{route_path}")
async def create_{singular}(request, response):
    """Create a new {singular}. {write_doc}"""
{b_create}

{w}@description("Update a {singular}")
@tags(["{route_path}"])
@put("/api/{route_path}/{{id:int}}")
async def update_{singular}(request, response):
    """Update a {singular}. {write_doc}"""
{b_update}

{w}@description("Delete a {singular}")
@tags(["{route_path}"])
@delete("/api/{route_path}/{{id:int}}")
async def delete_{singular}(request, response):
    """Delete a {singular}. {write_doc}"""
{b_delete}'''

    path.write_text(content, encoding="utf-8")
    print(f"  ✓ Created {path}")


def _gen_crud(name: str, flags: dict):
    """Generate full CRUD stack: model + migration + routes + template + test.

    tina4python generate crud Product --fields "name:string,price:float"
    """
    fields = _parse_fields(flags.get("fields", ""))
    table = _to_table(name)
    route_name = table + "s"  # routes are plural

    print(f"\n  Generating CRUD for {name}...\n")

    # 1. Model + migration
    _gen_model(name, flags)

    # 2. Routes with model — secure-by-default; thread --public through so
    #    `generate crud X --public` opens the writes (mirrors AutoCrud public=).
    is_public = bool(flags.get("public"))
    route_flags = {"model": name, "public": is_public}
    _gen_route(route_name, route_flags)

    # 3. Template
    template_dir = Path("src/templates/pages")
    template_dir.mkdir(parents=True, exist_ok=True)
    template_path = template_dir / f"{route_name}.twig"
    if not template_path.exists():
        # Build column headers from fields
        cols = [f for f, _ in fields] if fields else ["name"]
        th = "\n                ".join(f"<th>{c.replace('_', ' ').title()}</th>" for c in cols)
        td = "\n                ".join(f"<td>{{{{ item.{c} }}}}</td>" for c in cols)

        template_path.write_text(
            '{% extends "base.twig" %}\n'
            f'{{% block title %}}{name}s{{% endblock %}}\n'
            '{% block content %}\n'
            '<div class="container mt-4">\n'
            f'    <h1>{name}s</h1>\n'
            '    <table class="table">\n'
            '        <thead>\n'
            '            <tr>\n'
            '                <th>ID</th>\n'
            f'                {th}\n'
            '                <th>Actions</th>\n'
            '            </tr>\n'
            '        </thead>\n'
            '        <tbody>\n'
            '        {% for item in items %}\n'
            '            <tr>\n'
            '                <td>{{ item.id }}</td>\n'
            f'                {td}\n'
            '                <td><a href="/api/' + route_name + '/{{ item.id }}">View</a></td>\n'
            '            </tr>\n'
            '        {% endfor %}\n'
            '        </tbody>\n'
            '    </table>\n'
            '</div>\n'
            '{% endblock %}\n',
            encoding="utf-8",
        )
        print(f"  ✓ Created {template_path}")

    # 4. Form
    _gen_form(name, flags)

    # 5. View (list + detail)
    _gen_view(name, flags)

    # 6. Test — secure-by-default gate test (behavioural, real TestClient).
    _gen_test(route_name, {"model": name, "secure_writes": True, "public": is_public})

    print(f"\n  CRUD generation complete for {name}.")
    print(f"  Run: tina4python migrate")
    print(f"  Visit: /swagger to see the API docs")


def _gen_migration(name: str, flags: dict = None, *,
                   fields_override: list = None, table_override: str = None):
    """Generate a timestamped migration file with UP/DOWN sections.

    tina4python generate migration create_product
    tina4python generate migration add_category_to_product
    """
    flags = flags or {}
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d%H%M%S")
    target = Path("migrations")
    target.mkdir(parents=True, exist_ok=True)

    # Determine table name
    if table_override:
        table = table_override
    else:
        table = name.removeprefix("create_").removeprefix("add_").removeprefix("drop_")
        table = _to_snake(table)

    # Build SQL columns from fields
    fields = fields_override or _parse_fields(flags.get("fields", ""))
    is_create = name.startswith("create_") or fields_override is not None

    filename = f"{timestamp}_{name}.sql"
    path = target / filename

    if is_create:
        col_lines = ["    id INTEGER PRIMARY KEY AUTOINCREMENT"]
        for fname, ftype in fields:
            info = FIELD_TYPE_MAP.get(ftype, FIELD_TYPE_MAP["string"])
            default = f" DEFAULT {info['default']}" if info["default"] != "NULL" else ""
            col_lines.append(f"    {fname} {info['sql']}{default}")
        col_lines.append("    created_at TEXT DEFAULT CURRENT_TIMESTAMP")

        up_sql = f"CREATE TABLE IF NOT EXISTS {table} (\n" + ",\n".join(col_lines) + "\n);"
        down_sql = f"DROP TABLE IF EXISTS {table};"
    else:
        up_sql = f"-- Write your UP migration SQL here\n-- Example: ALTER TABLE {table} ADD COLUMN new_col TEXT DEFAULT '';"
        down_sql = f"-- Write your DOWN rollback SQL here\n-- Example: ALTER TABLE {table} DROP COLUMN new_col;"

    content = (
        f"-- Migration: {name}\n"
        f"-- Created: {now.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"{up_sql}\n"
    )
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ Created {path}")

    # Also create .down.sql for the migration runner
    down_path = target / f"{timestamp}_{name}.down.sql"
    down_path.write_text(
        f"-- Rollback: {name}\n"
        f"-- Created: {now.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"{down_sql}\n",
        encoding="utf-8",
    )
    print(f"  ✓ Created {down_path}")


def _gen_middleware(name: str, flags: dict = None):
    """Generate middleware with before/after stubs.

    tina4python generate middleware AuthLog
    """
    snake = _to_snake(name)
    target = Path("src/middleware")
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{snake}.py"
    if path.exists():
        print(f"  ✗ File already exists: {path}")
        return

    content = f'''"""{name} middleware."""
from tina4_python.debug import Log


class {name}:
    """Middleware with before/after hooks.

    Usage in routes:
        from tina4_python.core.router import get, middleware
        from src.middleware.{snake} import {name}

        @middleware({name})
        @get("/api/protected")
        async def protected(request, response):
            return response({{"data": "protected"}})
    """

    @staticmethod
    def before_{snake}(request, response):
        """Runs before the route handler.

        Return (request, response) to continue, or
        return (request, response("error", 401)) to block.
        """
        Log.info(f"{name}: {{request.method}} {{request.url}}")
        return request, response

    @staticmethod
    def after_{snake}(request, response):
        """Runs after the route handler."""
        return request, response
'''
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ Created {path}")


def _gen_test(name: str, flags: dict = None):
    """Generate a pytest test file.

    tina4python generate test products
    tina4python generate test products --model Product
    """
    flags = flags or {}
    model = flags.get("model", "")
    snake = _to_snake(name)
    singular = snake.rstrip("s") if snake.endswith("s") else snake

    target = Path("tests")
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"test_{snake}.py"
    if path.exists():
        print(f"  ✗ File already exists: {path}")
        return

    # Secure-by-default CRUD test (emitted by `generate crud`): proves the gate
    # by BEHAVIOR through the real TestClient — reads public, writes gated —
    # instead of assuming an anonymous create returns 201. Grounded on
    # tests/test_test_client_auth.py (real Router, real _check_auth, real JWT).
    if model and flags.get("secure_writes"):
        singular_ = singular
        write_neg = (
            '    def test_create___SINGULAR___requires_auth(self):\n'
            '        """Secure by default: a tokenless POST is rejected with 401."""\n'
            '        assert TestClient().post("/api/__SNAKE__", json={"name": "test"}).status == 401\n'
        )
        write_pos = (
            '    def test_create___SINGULAR___with_token(self):\n'
            '        """A valid Bearer token passes the gate and creates → 201."""\n'
            '        res = TestClient().post("/api/__SNAKE__", json={"name": "test"}, headers=_auth_headers())\n'
            "        assert res.status == 201\n"
        )
        if flags.get("public"):
            # --public opened the writes: an anonymous POST must succeed (201).
            write_neg = (
                '    def test_create___SINGULAR___is_public(self):\n'
                '        """--public opened the write: an anonymous POST creates → 201."""\n'
                '        assert TestClient().post("/api/__SNAKE__", json={"name": "test"}).status == 201\n'
            )
            write_pos = ""
        gate_template = (
            '"""Tests for __NAME__ CRUD — reads public, writes __POSTURE__.\n'
            "\n"
            "Real end-to-end via TestClient: no mocks — real Router, real auth gate\n"
            "(_check_auth), real JWT. A real SQLite DB + table is bound in setup so\n"
            "the create path is exercised for real.\n"
            '"""\n'
            "import os\n"
            "\n"
            'os.environ.setdefault("TINA4_SECRET", "test-secret")\n'
            'os.environ.pop("TINA4_API_KEY", None)\n'
            "\n"
            "from tina4_python.auth import get_token\n"
            "from tina4_python.database import Database\n"
            "from tina4_python.orm.model import bind_database\n"
            "from tina4_python.test_client import TestClient\n"
            "from src.orm.__MODEL__ import __MODEL__\n"
            "import src.routes.__SNAKE__  # noqa: F401 — importing registers the routes\n"
            "\n"
            "\n"
            "def _auth_headers():\n"
            '    """A valid Bearer token for the gated write routes."""\n'
            '    return {"Authorization": f"Bearer {get_token({\'user_id\': 1})}"}\n'
            "\n"
            "\n"
            "class Test__MODEL__:\n"
            '    """__MODEL__ CRUD — reads public, writes __POSTURE__ (secure by default)."""\n'
            "\n"
            "    def setup_method(self, _method):\n"
            '        bind_database(Database("sqlite:///test___SNAKE__.db"))\n'
            "        __MODEL__.create_table()\n"
            "\n"
            "    def test_list___SNAKE___is_public(self):\n"
            '        """GET is public — no token needed."""\n'
            '        assert TestClient().get("/api/__SNAKE__").status == 200\n'
            "\n"
            "__WRITE_NEG__"
            "\n"
            "__WRITE_POS__"
        )
        content = (
            gate_template.replace("__WRITE_NEG__", write_neg)
            .replace("__WRITE_POS__", write_pos)
            .replace("__POSTURE__", "open (--public)" if flags.get("public") else "gated")
            .replace("__NAME__", name)
            .replace("__MODEL__", model)
            .replace("__SINGULAR__", singular_)
            .replace("__SNAKE__", snake)
        )
        path.write_text(content, encoding="utf-8")
        print(f"  ✓ Created {path}")
        return

    if model:
        content = f'''"""Tests for {name} CRUD operations."""
import pytest


class Test{model}:
    """Test suite for {model}."""

    def setup_method(self):
        """Set up test fixtures."""
        pass

    def teardown_method(self):
        """Clean up after tests."""
        pass

    def test_list_{snake}(self):
        """Test listing {snake}."""
        # TODO: implement
        assert True

    def test_get_{singular}(self):
        """Test getting a single {singular}."""
        # TODO: implement
        assert True

    def test_create_{singular}(self):
        """Test creating a {singular}."""
        # TODO: implement
        assert True

    def test_update_{singular}(self):
        """Test updating a {singular}."""
        # TODO: implement
        assert True

    def test_delete_{singular}(self):
        """Test deleting a {singular}."""
        # TODO: implement
        assert True
'''
    else:
        content = f'''"""Tests for {name}."""
import pytest


class Test{name.title().replace("_", "")}:
    """Test suite for {name}."""

    def setup_method(self):
        """Set up test fixtures."""
        pass

    def teardown_method(self):
        """Clean up after tests."""
        pass

    def test_example(self):
        """Example test — replace with real tests."""
        assert True
'''

    path.write_text(content, encoding="utf-8")
    print(f"  ✓ Created {path}")


# ── Scaffolding-first generators (wiring + `# your code here`) ────────
#
# Each grounds on the REAL current Tina4 API (verified against the source) and
# drops the _ai_fill() AI-FILL placeholder where the custom logic goes:
#   service   → tina4_python/service/__init__.py   ServiceRunner.register / discover
#   queue     → tina4_python/queue/__init__.py     Queue.push / Queue.consume / Job.complete
#   validator → tina4_python/validator/__init__.py Validator
#   seeder    → tina4_python/seeder/__init__.py    FakeData / seed_orm
#   websocket → tina4_python/core/router.py        @websocket (conn, event, data)
#   listener  → tina4_python/core/events.py        @on(event)

def _gen_service(name: str, flags: dict = None):
    """Generate a scheduled background service (ServiceRunner).

    tina4python generate service Cleanup --every 5m
    tina4python generate service Report --cron "0 3 * * *"
    """
    flags = flags or {}
    snake = _to_snake(name)
    cron = flags.get("cron")
    if cron and cron is not True:
        schedule_reg = f'cron="{cron}"'
        schedule_kv = f'"cron": "{cron}",'
        schedule_note = f"cron '{cron}'"
    else:
        seconds = _parse_every(flags.get("every", "") if flags.get("every") is not True else "")
        schedule_reg = f"interval={seconds}"
        schedule_kv = f'"interval": {seconds},'
        schedule_note = f"every {seconds}s"

    target = Path("src/services")
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{snake}.py"
    if path.exists():
        print(f"  ✗ File already exists: {path}")
        return

    body = _ai_fill(
        f"{snake}_task",
        "do the scheduled work for this service",
        "context.log.info(...) to log; call your ORM / app code (re-run on schedule)",
        f"service:{snake}: implement the scheduled task",
        given="context -> ServiceContext (.name, .stop_event, .log)",
        ground='tina4_context("background service scheduled task", "python")',
    )
    template = (
        '"""__NAME__ background service — runs __NOTE__ via ServiceRunner.\n'
        "\n"
        "Wire a runner once (e.g. in app.py) to actually run it — `tina4python\n"
        "serve` does NOT auto-start services:\n"
        "\n"
        "    from tina4_python.service import ServiceRunner\n"
        "    runner = ServiceRunner()\n"
        '    register(runner)              # or: runner.discover("src/services")\n'
        "    runner.start()\n"
        '"""\n'
        "from tina4_python.service import ServiceRunner\n"
        "\n"
        "\n"
        "def __SNAKE___task(context):\n"
        '    """The scheduled task body. `context` is a ServiceContext with\n'
        "    .name, .stop_event and .log; a daemon-style task would loop until\n"
        '    context.stop_event.is_set()."""\n'
        "__BODY__"
        "\n\n"
        "def register(runner: ServiceRunner) -> None:\n"
        '    """Register this service on a ServiceRunner."""\n'
        '    runner.register("__SNAKE__", __SNAKE___task, __SCHEDULE_REG__)\n'
        "\n"
        "\n"
        '# Discovered by ServiceRunner.discover("src/services"), which calls\n'
        "# register(name=, handler=, interval=/cron=) from these keys.\n"
        "service = {\n"
        '    "name": "__SNAKE__",\n'
        '    "handler": __SNAKE___task,\n'
        "    __SCHEDULE_KV__\n"
        "}\n"
    )
    content = (
        template.replace("__BODY__", body)
        .replace("__NAME__", name)
        .replace("__NOTE__", schedule_note)
        .replace("__SCHEDULE_REG__", schedule_reg)
        .replace("__SCHEDULE_KV__", schedule_kv)
        .replace("__SNAKE__", snake)
    )
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ Created {path}")


def _gen_queue(name: str, flags: dict = None):
    """Generate a queue producer + consumer worker.

    tina4python generate queue order-emails
    """
    topic = name.lstrip("/")
    slug = _to_snake(re.sub(r"[^0-9a-zA-Z]+", "_", topic)).strip("_") or "topic"

    target = Path("src/services")  # consumer runs as a daemon service (see below)
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{slug}_consumer.py"
    if path.exists():
        print(f"  ✗ File already exists: {path}")
        return

    body = _ai_fill(
        f"handle_{slug}",
        f"process ONE {topic} job payload",
        "your ORM / Messenger() code; return to ack (job.complete), raise to nack (job.fail)",
        f"queue:{topic}: process the job payload",
        given="data -> dict (the pushed Job.data)",
        ground='tina4_context("process a queue job", "python")',
    )
    template = (
        '"""__TOPIC__ queue — producer + consumer worker.\n'
        "\n"
        "Produce from anywhere:   publish___SLUG__({...})\n"
        "The consumer is a long-running worker wired as a daemon `service` so\n"
        '    ServiceRunner().discover("src/services") + runner.start()\n'
        "runs it without blocking boot (consume() is an endless generator).\n"
        '"""\n'
        "from tina4_python.queue import Queue\n"
        "\n"
        "\n"
        "def publish___SLUG__(data: dict):\n"
        '    """Enqueue a __TOPIC__ job for the worker below to process."""\n'
        '    return Queue(topic="__TOPIC__").push(data)\n'
        "\n"
        "\n"
        "def handle___SLUG__(data: dict):\n"
        '    """Process ONE __TOPIC__ job payload (`data` is Job.data — the pushed dict)."""\n'
        "__BODY__"
        "\n\n"
        "def consume___SLUG__(context=None):\n"
        '    """Long-running __TOPIC__ worker. consume() yields Jobs; ack with\n'
        "    job.complete(), nack with job.fail(). `context` is the ServiceContext\n"
        '    when run under ServiceRunner (unused here)."""\n'
        '    for job in Queue(topic="__TOPIC__").consume():\n'
        "        try:\n"
        "            handle___SLUG__(job.data)\n"
        "            job.complete()          # ack — job done, remove from the queue\n"
        "        except Exception as exc:    # noqa: BLE001\n"
        "            job.fail(str(exc))      # nack — retry / dead-letter\n"
        "\n"
        "\n"
        '# Discovered by ServiceRunner.discover("src/services"); daemon=True because\n'
        "# consume___SLUG__ manages its own loop.\n"
        'service = {"name": "__TOPIC__-consumer", "handler": consume___SLUG__, "daemon": True}\n'
    )
    content = (
        template.replace("__BODY__", body)
        .replace("__TOPIC__", topic)
        .replace("__SLUG__", slug)
    )
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ Created {path}")


def _gen_validator(name: str, flags: dict = None):
    """Generate a request-body validator.

    tina4python generate validator CreateUser
    """
    snake = _to_snake(name)
    target = Path("src/validators")
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{snake}.py"
    if path.exists():
        print(f"  ✗ File already exists: {path}")
        return

    body = _ai_fill(
        f"validate_{snake}",
        f"declare the validation rules for a {name} payload",
        'validator.required("name").email("email").min_length("name", 2).integer("age")',
        f"validator:{snake}: add the rule set",
        given="validator -> Validator(data) (chainable)",
        ret="the same validator (caller checks .is_valid() / .errors())",
        ground='tina4_context("validate request body with Validator", "python")',
    )
    template = (
        '"""__NAME__ request validator."""\n'
        "from tina4_python.validator import Validator\n"
        "\n"
        "\n"
        "def validate___SNAKE__(data: dict) -> Validator:\n"
        '    """Validate a __NAME__ payload. Returns a Validator (chainable rules).\n'
        "\n"
        "    Usage in a route::\n"
        "\n"
        "        v = validate___SNAKE__(request.body)\n"
        "        if not v.is_valid():\n"
        '            return response.error("VALIDATION_FAILED", v.errors()[0]["message"], 400)\n'
        '    """\n'
        "    validator = Validator(data)\n"
        "__BODY__"
        "    return validator\n"
    )
    content = (
        template.replace("__BODY__", body)
        .replace("__NAME__", name)
        .replace("__SNAKE__", snake)
    )
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ Created {path}")


def _gen_seeder(name: str, flags: dict = None):
    """Generate a seeder for an ORM model.

    tina4python generate seeder Product
    """
    table = _to_table(name)
    target = Path("src/seeds")
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{table}_seeder.py"
    if path.exists():
        print(f"  ✗ File already exists: {path}")
        return

    body = _ai_fill(
        "field_overrides",
        f"map {name} fields to fake-data generators (only those needing a specific shape)",
        "fake.name() / fake.email() / fake.integer(1, 99) / fake.company()  (FakeData)",
        f"seeder:{name}: return the field->generator overrides",
        given="fake -> FakeData instance",
        ret='{"email": lambda fake: fake.email(), "status": "active"}  (dict)',
        ground='tina4_context("seed ORM model with FakeData", "python")',
    )
    template = (
        '"""Seeder for __NAME__ — run with: tina4python seed"""\n'
        "from tina4_python.seeder import FakeData, seed_orm\n"
        "from src.orm.__NAME__ import __NAME__\n"
        "\n"
        "\n"
        "def field_overrides(fake: FakeData) -> dict:\n"
        '    """Map __NAME__ fields → FakeData generators (or static values).\n'
        "\n"
        "    seed_orm auto-fills every field by type/name; override the ones that\n"
        "    need a specific shape here. Each callable receives a FakeData instance:\n"
        '        return {"email": lambda fake: fake.email(), "status": "active"}\n'
        '    """\n'
        "__BODY__"
        "\n\n"
        "def run(db):\n"
        '    """Seed rows. Invoked by `tina4python seed` (passes the Database)."""\n'
        "    fake = FakeData()\n"
        "    summary = seed_orm(__NAME__, count=20, overrides=field_overrides(fake))\n"
        '    print(f"Seeded {summary.seeded} __NAME__ row(s), {summary.failed} failed")\n'
    )
    content = template.replace("__BODY__", body).replace("__NAME__", name)
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ Created {path}")


def _gen_websocket(name: str, flags: dict = None):
    """Generate a WebSocket route.

    tina4python generate websocket chat
    tina4python generate websocket /ws/rooms/{id}
    """
    raw = name.strip()
    ws_path = raw if raw.startswith("/") else "/ws/" + raw.lstrip("/")
    slug = _to_snake(re.sub(r"[^0-9a-zA-Z]+", "_", raw.strip("/"))).strip("_") or "ws"
    base = slug[3:] if slug.startswith("ws_") else slug
    base = base or "ws"
    handler = f"{base}_ws"

    target = Path("src/routes")  # @websocket auto-registers on import (src/ is discovered)
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"ws_{base}.py"
    if path.exists():
        print(f"  ✗ File already exists: {path}")
        return

    body = _ai_fill(
        handler,
        f'handle an inbound "message" frame on {ws_path}',
        "await connection.broadcast(data)  or  await connection.send_json({...})",
        f"websocket:{ws_path}: handle the inbound message",
        given="data -> str (message payload); connection -> WebSocketConnection",
        ground='tina4_context("websocket broadcast message", "python")',
    )
    template = (
        '"""__WSPATH__ WebSocket route.\n'
        "\n"
        "Auto-registered on import by @websocket (src/ is auto-discovered at boot).\n"
        "The server invokes the handler as handler(connection, event, data) for\n"
        'each event: "open" (connect), "message" (inbound frame), "close"\n'
        "(disconnect). Put @secured() above @websocket to require a JWT on the\n"
        "upgrade; connection.broadcast()/connection.send() reach the other clients.\n"
        '"""\n'
        "from tina4_python.core.router import websocket\n"
        "\n"
        "\n"
        '@websocket("__WSPATH__")\n'
        "async def __HANDLER__(connection, event, data):\n"
        '    """__WSPATH__ handler. `data` is the message payload on "message",\n'
        '    None on "open"/"close"; connection.params holds any path params."""\n'
        '    if event == "open":\n'
        '        await connection.send(\'{"type": "welcome"}\')\n'
        "        return\n"
        '    if event == "close":\n'
        "        return\n"
        '    # event == "message"\n'
        "__BODY__"
    )
    content = (
        template.replace("__BODY__", body)
        .replace("__WSPATH__", ws_path)
        .replace("__HANDLER__", handler)
    )
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ Created {path}")


def _gen_listener(name: str, flags: dict = None):
    """Generate an event listener.

    tina4python generate listener user.created
    """
    event = name.strip()
    slug = _to_snake(re.sub(r"[^0-9a-zA-Z]+", "_", event)).strip("_") or "event"

    target = Path("src/listeners")  # @on auto-registers on import (src/ is discovered)
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{slug}.py"
    if path.exists():
        print(f"  ✗ File already exists: {path}")
        return

    body = _ai_fill(
        f"on_{slug}",
        f"react to the '{event}' event",
        "your app code — Messenger().send(...), an ORM write, or emit(...) a follow-up event",
        f"listener:{event}: react to the event payload",
        given=f"data -> whatever emit('{event}', data) passed",
        ground='tina4_context("event listener reaction", "python")',
    )
    template = (
        "\"\"\"Listener for the '__EVENT__' event.\n"
        "\n"
        "Auto-registered on import by @on (src/ is auto-discovered at boot). Fires\n"
        'when something calls emit("__EVENT__", data). Listeners are isolated — a\n'
        "raise is logged and the other listeners still run (emit(..., strict=True)\n"
        "re-raises instead).\n"
        '"""\n'
        "from tina4_python.core.events import on\n"
        "\n"
        "\n"
        '@on("__EVENT__")\n'
        "def on___SLUG__(data=None):\n"
        "    \"\"\"React to '__EVENT__'. `data` is whatever emit('__EVENT__', data) passed.\"\"\"\n"
        "__BODY__"
    )
    content = (
        template.replace("__BODY__", body)
        .replace("__EVENT__", event)
        .replace("__SLUG__", slug)
    )
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ Created {path}")


# ── Utilities ─────────────────────────────────────────────────────────

def _gen_form(name: str, flags: dict = None):
    """Generate a form template matching a model's fields.

    tina4python generate form Product
    tina4python generate form Product --fields "name:string,price:float"
    """
    flags = flags or {}
    fields = _parse_fields(flags.get("fields", ""))
    table = _to_table(name)
    route_name = table + "s"

    # Input type mapping
    input_types = {
        "string": "text", "str": "text", "text": "textarea",
        "int": "number", "integer": "number",
        "float": "number", "numeric": "number", "decimal": "number",
        "bool": "checkbox", "boolean": "checkbox",
        "datetime": "datetime-local", "blob": "file",
    }

    target = Path("src/templates/forms")
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{table}.twig"
    if path.exists():
        print(f"  ✗ File already exists: {path}")
        return

    # Build form fields
    field_html = ""
    for fname, ftype in (fields or [("name", "string")]):
        itype = input_types.get(ftype, "text")
        label = fname.replace("_", " ").title()
        step = ' step="0.01"' if ftype in ("float", "numeric", "decimal") else ""

        if itype == "textarea":
            field_html += (
                f'    <div class="form-group mb-3">\n'
                f'        <label for="{fname}">{label}</label>\n'
                f'        <textarea id="{fname}" name="{fname}" class="form-control" rows="4"'
                f' placeholder="{label}">{{{{ item.{fname} }}}}</textarea>\n'
                f'    </div>\n'
            )
        elif itype == "checkbox":
            field_html += (
                f'    <div class="form-group mb-3">\n'
                f'        <label>\n'
                f'            <input type="checkbox" id="{fname}" name="{fname}" value="1"'
                f' {{% if item.{fname} %}}checked{{% endif %}}>\n'
                f'            {label}\n'
                f'        </label>\n'
                f'    </div>\n'
            )
        else:
            field_html += (
                f'    <div class="form-group mb-3">\n'
                f'        <label for="{fname}">{label}</label>\n'
                f'        <input type="{itype}" id="{fname}" name="{fname}" class="form-control"'
                f'{step} value="{{{{ item.{fname} }}}}" placeholder="{label}">\n'
                f'    </div>\n'
            )

    content = (
        '{%% extends "base.twig" %%}\n'
        '{%% block title %%}%s {%% if item.id %%}Edit{%% else %%}Create{%% endif %%}{%% endblock %%}\n'
        '{%% block content %%}\n'
        '<div class="container mt-4">\n'
        '    <h1>{%% if item.id %%}Edit %s{%% else %%}Create %s{%% endif %%}</h1>\n'
        '    <form method="post" action="/api/%s{%% if item.id %%}/{{ item.id }}{%% endif %%}">\n'
        '        {{ form_token() }}\n'
        '%s'
        '    <button type="submit" class="btn btn-primary">\n'
        '        {%% if item.id %%}Update{%% else %%}Create{%% endif %%}\n'
        '    </button>\n'
        '    <a href="/api/%s" class="btn btn-secondary">Cancel</a>\n'
        '    </form>\n'
        '</div>\n'
        '{%% endblock %%}\n'
    ) % (name, name, name, route_name, field_html, route_name)

    path.write_text(content, encoding="utf-8")
    print(f"  ✓ Created {path}")


def _gen_view(name: str, flags: dict = None):
    """Generate list + detail view templates.

    tina4python generate view Product
    tina4python generate view Product --fields "name:string,price:float"
    """
    flags = flags or {}
    fields = _parse_fields(flags.get("fields", ""))
    table = _to_table(name)
    route_name = table + "s"

    target = Path("src/templates/pages")
    target.mkdir(parents=True, exist_ok=True)

    cols = [f for f, _ in fields] if fields else ["name"]

    # List view
    list_path = target / f"{route_name}.twig"
    if not list_path.exists():
        th = "\n                ".join(f"<th>{c.replace('_', ' ').title()}</th>" for c in cols)
        td = "\n                ".join(f"<td>{{{{ item.{c} }}}}</td>" for c in cols)

        list_path.write_text(
            '{%% extends "base.twig" %%}\n'
            '{%% block title %%}%s{%% endblock %%}\n'
            '{%% block content %%}\n'
            '<div class="container mt-4">\n'
            '    <div class="d-flex justify-content-between align-items-center mb-3">\n'
            '        <h1>%s</h1>\n'
            '        <a href="/%s/create" class="btn btn-primary">Add %s</a>\n'
            '    </div>\n'
            '    <table class="table">\n'
            '        <thead>\n'
            '            <tr>\n'
            '                <th>ID</th>\n'
            '                %s\n'
            '                <th>Actions</th>\n'
            '            </tr>\n'
            '        </thead>\n'
            '        <tbody>\n'
            '        {%% for item in items %%}\n'
            '            <tr>\n'
            '                <td>{{ item.id }}</td>\n'
            '                %s\n'
            '                <td>\n'
            '                    <a href="/%s/{{ item.id }}" class="btn btn-sm btn-primary">View</a>\n'
            '                    <a href="/%s/{{ item.id }}/edit" class="btn btn-sm btn-secondary">Edit</a>\n'
            '                </td>\n'
            '            </tr>\n'
            '        {%% endfor %%}\n'
            '        </tbody>\n'
            '    </table>\n'
            '</div>\n'
            '{%% endblock %%}\n'
            % (name + "s", name + "s", route_name, name, th, td, route_name, route_name),
            encoding="utf-8",
        )
        print(f"  ✓ Created {list_path}")

    # Detail view
    detail_path = target / f"{table}.twig"
    if not detail_path.exists():
        detail_fields = "\n".join(
            f'    <div class="mb-3"><strong>{c.replace("_", " ").title()}:</strong> {{{{ item.{c} }}}}</div>'
            for c in cols
        )

        detail_path.write_text(
            '{%% extends "base.twig" %%}\n'
            '{%% block title %%}%s Detail{%% endblock %%}\n'
            '{%% block content %%}\n'
            '<div class="container mt-4">\n'
            '    <div class="d-flex justify-content-between align-items-center mb-3">\n'
            '        <h1>%s #{{ item.id }}</h1>\n'
            '        <div>\n'
            '            <a href="/%s/{{ item.id }}/edit" class="btn btn-secondary">Edit</a>\n'
            '            <a href="/%s" class="btn btn-outline-secondary">Back</a>\n'
            '        </div>\n'
            '    </div>\n'
            '%s\n'
            '</div>\n'
            '{%% endblock %%}\n'
            % (name, name, route_name, route_name, detail_fields),
            encoding="utf-8",
        )
        print(f"  ✓ Created {detail_path}")


def _gen_auth(name: str = None, flags: dict = None):
    """Generate authentication scaffolding: User model, login/register routes, templates.

    tina4python generate auth
    """
    print("\n  Generating authentication scaffolding...\n")

    # 1. User model + migration
    _gen_model("User", {"fields": "email:string,password:string,role:string"})

    # 2. Auth routes
    target = Path("src/routes")
    target.mkdir(parents=True, exist_ok=True)
    auth_path = target / "auth.py"
    if not auth_path.exists():
        auth_path.write_text(
            'from tina4_python.core.router import get, post, noauth\n'
            'from tina4_python.swagger import description, tags\n'
            'from tina4_python.auth import Auth\n'
            'from src.orm.User import User\n\n\n'
            '@noauth()\n'
            '@description("Register a new user")\n'
            '@tags(["auth"])\n'
            '@post("/api/auth/register")\n'
            'async def register(request, response):\n'
            '    """Register a new user."""\n'
            '    body = request.body\n'
            '    email = body.get("email", "")\n'
            '    password = body.get("password", "")\n\n'
            '    if not email or not password:\n'
            '        return response({"error": "Email and password required"}, 400)\n\n'
            '    # Check if user exists\n'
            '    existing = User()\n'
            '    if existing.load("email = ?", [email]):\n'
            '        return response({"error": "Email already registered"}, 409)\n\n'
            '    # Create user with hashed password\n'
            '    user = User.create({\n'
            '        "email": email,\n'
            '        "password": Auth.hash_password(password),\n'
            '        "role": "user",\n'
            '    })\n'
            '    return response({"message": "Registered", "id": user.id}, 201)\n\n\n'
            '@noauth()\n'
            '@description("Login and receive JWT token")\n'
            '@tags(["auth"])\n'
            '@post("/api/auth/login")\n'
            'async def login(request, response):\n'
            '    """Login with email and password."""\n'
            '    body = request.body\n'
            '    email = body.get("email", "")\n'
            '    password = body.get("password", "")\n\n'
            '    user = User()\n'
            '    if not user.load("email = ?", [email]):\n'
            '        return response({"error": "Invalid credentials"}, 401)\n\n'
            '    if not Auth.check_password(password, user.password):\n'
            '        return response({"error": "Invalid credentials"}, 401)\n\n'
            '    token = Auth.get_token({"user_id": user.id, "email": user.email, "role": user.role})\n'
            '    return response({"token": token})\n\n\n'
            '@description("Get current user profile")\n'
            '@tags(["auth"])\n'
            '@get("/api/auth/me")\n'
            'async def me(request, response):\n'
            '    """Get current authenticated user."""\n'
            '    payload = Auth.get_payload(request)\n'
            '    if not payload:\n'
            '        return response({"error": "Unauthorized"}, 401)\n'
            '    user = User.find_by_id(payload.get("user_id"))\n'
            '    if not user:\n'
            '        return response({"error": "User not found"}, 404)\n'
            '    return response({"id": user.id, "email": user.email, "role": user.role})\n',
            encoding="utf-8",
        )
        print(f"  ✓ Created {auth_path}")

    # 3. Login template
    forms_dir = Path("src/templates/forms")
    forms_dir.mkdir(parents=True, exist_ok=True)
    login_path = forms_dir / "login.twig"
    if not login_path.exists():
        login_path.write_text(
            '{% extends "base.twig" %}\n'
            '{% block title %}Login{% endblock %}\n'
            '{% block content %}\n'
            '<div class="container mt-4" style="max-width:400px">\n'
            '    <h1>Login</h1>\n'
            '    <form method="post" action="/api/auth/login">\n'
            '        {{ form_token() }}\n'
            '        <div class="form-group mb-3">\n'
            '            <label for="email">Email</label>\n'
            '            <input type="email" id="email" name="email" class="form-control" placeholder="Email" required>\n'
            '        </div>\n'
            '        <div class="form-group mb-3">\n'
            '            <label for="password">Password</label>\n'
            '            <input type="password" id="password" name="password" class="form-control" placeholder="Password" required>\n'
            '        </div>\n'
            '        <button type="submit" class="btn btn-primary w-100">Login</button>\n'
            '        <p class="mt-3 text-center"><a href="/register">Create an account</a></p>\n'
            '    </form>\n'
            '</div>\n'
            '{% endblock %}\n',
            encoding="utf-8",
        )
        print(f"  ✓ Created {login_path}")

    # 4. Register template
    register_path = forms_dir / "register.twig"
    if not register_path.exists():
        register_path.write_text(
            '{% extends "base.twig" %}\n'
            '{% block title %}Register{% endblock %}\n'
            '{% block content %}\n'
            '<div class="container mt-4" style="max-width:400px">\n'
            '    <h1>Register</h1>\n'
            '    <form method="post" action="/api/auth/register">\n'
            '        {{ form_token() }}\n'
            '        <div class="form-group mb-3">\n'
            '            <label for="email">Email</label>\n'
            '            <input type="email" id="email" name="email" class="form-control" placeholder="Email" required>\n'
            '        </div>\n'
            '        <div class="form-group mb-3">\n'
            '            <label for="password">Password</label>\n'
            '            <input type="password" id="password" name="password" class="form-control" placeholder="Password" minlength="8" required>\n'
            '        </div>\n'
            '        <button type="submit" class="btn btn-primary w-100">Register</button>\n'
            '        <p class="mt-3 text-center"><a href="/login">Already have an account?</a></p>\n'
            '    </form>\n'
            '</div>\n'
            '{% endblock %}\n',
            encoding="utf-8",
        )
        print(f"  ✓ Created {register_path}")

    # 5. Auth test
    _gen_test("auth", {"model": "User"})

    print("\n  Authentication scaffolding complete.")
    print("  Run: tina4python migrate")
    print("  POST /api/auth/register  — create account")
    print("  POST /api/auth/login     — get JWT token")
    print("  GET  /api/auth/me        — get profile (requires token)")


def _load_env():
    """Load .env file if it exists."""
    env_path = Path(".env")
    if env_path.exists():
        from tina4_python.dotenv import load_env
        load_env(str(env_path))


# ── Self-describing command surface ───────────────────────────────────

def _commands_manifest() -> dict:
    """Build the machine-readable manifest of the CLI's command surface.

    Pure data: reads the module-level COMMANDS registry and the framework
    version — no bootstrap, no database, no migrations, no app imports. This is
    exactly what `commands --json` serializes and what the tina4 Rust client
    consumes to discover which commands this framework supports.

    Shape::

        {"framework": "python", "version": "<x.y.z>",
         "commands": [{"name", "summary", "args"?, "subcommands"?}, ...]}
    """
    from tina4_python import __version__
    commands = []
    for command_name, spec in COMMANDS.items():
        entry = {"name": command_name, "summary": spec["summary"]}
        if spec.get("args"):
            entry["args"] = list(spec["args"])
        if spec.get("subcommands"):
            entry["subcommands"] = list(spec["subcommands"])
        commands.append(entry)
    return {"framework": "python", "version": __version__, "commands": commands}


def _commands(args=None):
    """Emit the CLI's own command surface — the self-describing manifest.

        tina4python commands           human-readable list
        tina4python commands --json    machine-readable manifest (for the tina4 CLI)

    CHEAP + side-effect-free by contract: it only prints the static COMMANDS
    registry plus the framework version. It MUST NOT bootstrap the framework,
    open a database, run migrations, or import app modules — the Rust client
    calls this on `tina4 --help`, in any directory, so it must be instant and
    safe to run anywhere.
    """
    args = args or []
    manifest = _commands_manifest()

    if "--json" in args:
        import json
        print(json.dumps(manifest, indent=2))
        return

    print(f"\nTina4 {manifest['framework']} — {manifest['version']}\n")
    width = max(len(command["name"]) for command in manifest["commands"])
    for command in manifest["commands"]:
        print(f"  {command['name']:<{width}}  {command['summary']}")
        if command.get("subcommands"):
            print(f"  {'':<{width}}    {', '.join(command['subcommands'])}")
    print()


# ── Command registries — the single source of truth ───────────────────
#
# One entry per command drives dispatch (main / _generate), the human help
# (_help), AND the machine-readable manifest (commands --json). Add a command
# in ONE place and it appears everywhere — there is no second list to sync.
#
#   GENERATORS[name] = {"handler": fn(name, flags), "usage": str, "summary": str}
#   COMMANDS[name]   = {"handler": fn(args), "summary": str,
#                       "usage"?: str,          # arg/flag hint for _help (human only)
#                       "args"?: [str],         # positional args for the manifest ("x?" = optional)
#                       "subcommands"?: [str]}  # sub-names for the manifest (generate)

GENERATORS = {
    "model":      {"handler": _gen_model,      "usage": '<Name> [--fields "name:string,price:float"]', "summary": "ORM model + matching migration"},
    "route":      {"handler": _gen_route,      "usage": "<name> [--model Name] [--public]",            "summary": "CRUD route file, secure by default (--public opens writes)"},
    "crud":       {"handler": _gen_crud,       "usage": '<Name> [--fields "..."] [--public]',          "summary": "Model + migration + routes + form + view + test"},
    "migration":  {"handler": _gen_migration,  "usage": "<description>",                               "summary": "Timestamped migration file (UP/DOWN)"},
    "middleware": {"handler": _gen_middleware, "usage": "<Name>",                                      "summary": "Middleware with before/after hooks"},
    "test":       {"handler": _gen_test,       "usage": "<name> [--model Name]",                       "summary": "pytest test file"},
    "form":       {"handler": _gen_form,       "usage": '<Name> [--fields "..."]',                     "summary": "Form template with inputs matching model fields"},
    "view":       {"handler": _gen_view,       "usage": '<Name> [--fields "..."]',                     "summary": "List + detail view templates"},
    "auth":       {"handler": _gen_auth,       "usage": "",                                            "summary": "Login/register routes + User model + templates"},
    "service":    {"handler": _gen_service,    "usage": '<Name> [--every 5m | --cron "..."]',          "summary": "Scheduled ServiceRunner task (src/services/)"},
    "queue":      {"handler": _gen_queue,      "usage": "<topic>",                                     "summary": "Producer + consumer worker (src/services/)"},
    "validator":  {"handler": _gen_validator,  "usage": "<Name>",                                      "summary": "Request-body Validator (src/validators/)"},
    "seeder":     {"handler": _gen_seeder,     "usage": "<Model>",                                     "summary": "FakeData + seed_orm seeder (src/seeds/)"},
    "websocket":  {"handler": _gen_websocket,  "usage": "<path>",                                      "summary": "@websocket handler (src/routes/)"},
    "listener":   {"handler": _gen_listener,   "usage": "<event>",                                     "summary": "@on(event) listener (src/listeners/)"},
}

COMMANDS = {
    "init":             {"handler": _init,             "usage": "[dir]",  "args": ["dir?"],        "summary": "Scaffold a new project"},
    "serve":            {"handler": _serve,            "usage": "[--port P] [--no-browser] [--no-reload]", "summary": "Start dev server (default: 0.0.0.0:7146)"},
    "start":            {"handler": _serve,            "summary": "Alias for serve"},
    "migrate":          {"handler": _migrate,          "summary": "Run pending database migrations"},
    "migrate:create":   {"handler": _migrate_create,   "usage": "<desc>", "args": ["description"], "summary": "Create a new migration file"},
    "migrate:rollback": {"handler": _migrate_rollback, "summary": "Rollback last migration batch"},
    "migrate:status":   {"handler": _migrate_status,   "summary": "Show migration status"},
    "env-migrate":      {"handler": _env_migrate,      "usage": "[path]", "args": ["path?"],       "summary": "Rewrite .env to TINA4_-prefixed names (v3.12 migration)"},
    "seed":             {"handler": _seed,             "summary": "Run database seeders"},
    "routes":           {"handler": _routes,           "summary": "List all registered routes"},
    "test":             {"handler": _test,             "summary": "Run test suite"},
    "build":            {"handler": _build,            "summary": "Build distributable package"},
    "ai":               {"handler": _ai,               "usage": "[--all]", "summary": "Install AI coding assistant context"},
    "generate":         {"handler": _generate,         "usage": "<what> <name> [options]", "subcommands": list(GENERATORS), "summary": "Generate scaffolding (see Generators below)"},
    "console":          {"handler": _console,          "summary": "Start interactive REPL with framework loaded"},
    "metrics":          {"handler": _metrics,          "usage": "[--top N] [--json] [--fail-on warn|error] [--path DIR]", "summary": "Rank top code-quality offenders"},
    "commands":         {"handler": _commands,         "usage": "[--json]", "summary": "List available commands (add --json for machine form)"},
    "help":             {"handler": _help,             "summary": "Show this help"},
}


__all__ = ["main"]
