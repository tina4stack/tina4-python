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

Three further commands — doctor, setup, deploy — are owned by the `tina4` client
and reached by DELEGATION (see DELEGATED / _delegate_to_client below), so
`tina4python doctor` behaves exactly like `tina4 doctor` without cloning the
client's implementation into four languages.
"""
import os
import re
import shutil
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# ── Field type mapping ────────────────────────────────────────────────
FIELD_TYPE_MAP = {
    "string":   {"orm": "StringField",   "sql": "VARCHAR(255)", "default": "''"},
    "str":      {"orm": "StringField",   "sql": "VARCHAR(255)", "default": "''"},
    "int":      {"orm": "IntegerField",  "sql": "INTEGER", "default": "0"},
    "integer":  {"orm": "IntegerField",  "sql": "INTEGER", "default": "0"},
    "float":    {"orm": "NumericField",  "sql": "REAL",    "default": "0"},
    "numeric":  {"orm": "NumericField",  "sql": "REAL",    "default": "0"},
    "decimal":  {"orm": "NumericField",  "sql": "REAL",    "default": "0"},
    "bool":     {"orm": "BooleanField",  "sql": "INTEGER", "default": "0"},
    "boolean":  {"orm": "BooleanField",  "sql": "INTEGER", "default": "0"},
    "text":     {"orm": "TextField",     "sql": "TEXT",    "default": "''"},
    "datetime": {"orm": "DateTimeField", "sql": "TIMESTAMP", "default": "NULL"},
    "blob":     {"orm": "BlobField",     "sql": "BLOB",    "default": "NULL"},
}


# ── Helpers ───────────────────────────────────────────────────────────

def _to_snake(name: str) -> str:
    """CamelCase → snake_case: ProductCategory → product_category."""
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


# Table names that collide with SQL reserved words. `CREATE TABLE order (...)`
# is a syntax error on every engine, and the ORM interpolates table names into
# SQL unquoted (and hands the raw name to driver insert/update/delete), so the
# safe fix is to never GENERATE one. The plural form is not reserved and reads
# naturally as a table name.
SQL_RESERVED_TABLE_NAMES = {
    "order", "group", "user", "table", "select", "from", "where", "index",
    "key", "values", "column", "constraint", "check", "default", "primary",
    "foreign", "references", "unique", "join", "union", "having", "limit",
    "offset", "desc", "asc", "case", "when", "then", "else", "end", "and",
    "or", "not", "null", "insert", "update", "delete", "create", "drop",
    "alter", "grant", "revoke", "commit", "rollback", "view", "trigger",
    "procedure", "function", "database", "schema", "session", "set", "into",
    "as", "on", "by", "inner", "outer", "left", "right", "full", "natural",
    "using", "with", "distinct", "between", "exists", "like", "in", "is",
    "all", "any", "cross", "add", "row", "rows", "range", "current", "to",
}


def _pluralize_table(name: str) -> str:
    """Simple English plural, used to escape a reserved table name."""
    if name.endswith("y") and not name.endswith(("ay", "ey", "iy", "oy", "uy")):
        return name[:-1] + "ies"
    if name.endswith(("s", "x", "z", "ch", "sh")):
        return name + "es"
    return name + "s"


def _to_table(name: str) -> str:
    """Class name → singular table name: Product → product.

    A name colliding with a SQL reserved word is pluralised instead
    (Order → orders). Every generator routes through here, so the model's
    ``table_name``, the migration DDL, the routes and the tests all agree.
    """
    table = _to_snake(name)
    if table in SQL_RESERVED_TABLE_NAMES:
        return _pluralize_table(table)
    return table


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


# Called without --fields, the generators fall back to a single `name` string
# column. That default MUST be materialised here, in one place, and then flow
# into the model, the migration, the template and the test alike. It used to
# live only inside the model template, so `generate model X` / `generate crud X`
# wrote a model declaring `name` while the migration - built from the parsed
# field list, which was empty - created only id + created_at. The first write
# then failed with "table x has no column named name".
DEFAULT_FIELDS: list[tuple[str, str]] = [("name", "string")]


def _fields_or_default(fields_str: str) -> list[tuple[str, str]]:
    """Parsed --fields, or the default single `name` column when none given."""
    return _parse_fields(fields_str) or list(DEFAULT_FIELDS)


def _parse_flags(args: list[str]) -> tuple[dict, list[str]]:
    """Parse --key value and --flag from args. Returns (flags, positional)."""
    # Boolean-only flags that never take a value argument
    boolean_flags = {"no-browser", "no-reload", "no-kill", "production", "managed", "all", "clear",
                     "json", "public", "no-migration", "once", "dry-run", "quote", "fix", "no-install"}

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


# The port-takeover safety logic (identity check, PID safety filter, container
# guard, dev gate, opt-out) lives in ONE shared module so the CLI path here and
# the runtime bind-failure fallback in core/server.py cannot diverge
# (TAKEOVER-DEC-02). `selectable_pids` and `_in_container` are re-exported so
# their existing callers/tests keep resolving `tina4_python.cli.selectable_pids`.
from tina4_python.core.port_takeover import (  # noqa: E402
    selectable_pids,
    in_container as _in_container,
    take_over_port,
    is_dev,
    no_takeover_opted_out,
)


def _kill_process_on_port(port: int) -> bool:
    """Reclaim *port* from a stale Tina4 dev server, only when it is safe.

    Routes through the shared identity-checked takeover (TAKEOVER-DEC-01/02):
    a holder is signalled ONLY when a Tina4 dev server recorded its PID in the
    per-port PID file. A foreign holder is left running and a clear message is
    printed; takeover is also skipped in a container, outside dev mode, and when
    opted out (`TINA4_NO_TAKEOVER` / `tina4 serve --no-kill`).

    Returns True only when a Tina4 holder was actually signalled.
    """
    result = take_over_port(port, dev=is_dev(), no_takeover=no_takeover_opted_out())
    if result.reclaimed:
        print(f"  ⚠ {result.message}")
        return True
    if result.refused and result.message:
        print(f"  {result.message}")
    return False


# ── Delegation to the `tina4` client ─────────────────────────────────
#
# `doctor`, `setup` and `deploy` are owned by the Rust `tina4` client, not by any
# framework. `doctor` probes ALL FOUR runtimes plus package managers, ports and
# global AI-skills currency; `setup` installs language runtimes (Homebrew /
# Chocolatey, with UAC elevation on Windows) and scaffolds a project from
# nothing; `deploy` writes deployment boilerplate baked into the client binary.
# Cloning any of them into four languages would duplicate hundreds of lines per
# language for zero new capability — and four copies would immediately drift.
#
# So the framework CLI DELEGATES: it resolves `tina4` on PATH, runs it with the
# same argv, and exits with the client's exit code. All four frameworks reach the
# SAME implementation, which is a stronger parity guarantee than four ports.
#
# Delegation is ALLOW-LISTED, never blind. The client forwards ITS unknown
# commands to the framework CLI, so a framework that forwarded its unknowns back
# would ping-pong an unknown command between two processes forever. The closed
# DELEGATED set contains only commands the client dispatches natively, so no
# loop is possible by construction, and a real typo still gets "Unknown command".

CLIENT_BINARY = "tina4"

# Internal process marker (same class as the client's own TINA4_SETUP_ELEVATED):
# set on the child so a client that resolves back to a framework CLI is caught
# instead of spawning forever. NOT user configuration — deliberately absent from
# the CLI's known_vars().
DELEGATION_GUARD_ENV = "TINA4_CLI_DELEGATED"

# Exit codes. 127 is the conventional "command not found" and covers both ways
# the client can be unreachable (absent from PATH, or the loop guard tripping).
EXIT_CLIENT_UNAVAILABLE = 127
EXIT_UNKNOWN_COMMAND = 1

CLIENT_INSTALL_HINT = (
    "  Install it:  curl -fsSL https://tina4.com/install.sh | sh\n"
    "  Windows:     irm https://tina4.com/install.ps1 | iex"
)


def _find_client() -> str | None:
    """Absolute path of the `tina4` client on PATH, or None if it isn't there."""
    return shutil.which(CLIENT_BINARY)


def _delegate_to_client(command: str, args: list) -> int:
    """Run `tina4 <command> <args...>`, returning the client's exit code.

    Returns EXIT_CLIENT_UNAVAILABLE (127) with an actionable message when the
    client is not on PATH, or when the re-entry guard shows the resolved `tina4`
    came back to a framework CLI (a delegation loop).
    """
    if os.environ.get(DELEGATION_GUARD_ENV) == command:
        print(
            f"  Refusing to delegate '{command}' again — the 'tina4' on your PATH\n"
            f"  resolved back to a framework CLI instead of the tina4 client.\n\n"
            f"  Check which 'tina4' comes first on your PATH and put the client first.",
            file=sys.stderr,
        )
        return EXIT_CLIENT_UNAVAILABLE

    client = _find_client()
    if client is None:
        print(
            f"  '{command}' is provided by the tina4 client, which is not on your PATH.\n\n"
            f"{CLIENT_INSTALL_HINT}\n\n"
            f"  Then run:    {CLIENT_BINARY} {command}",
            file=sys.stderr,
        )
        return EXIT_CLIENT_UNAVAILABLE

    # stdio is inherited, so the client's interactive prompts (setup) and colour
    # output work exactly as if it had been invoked directly.
    env = dict(os.environ)
    env[DELEGATION_GUARD_ENV] = command
    return subprocess.run([client, command, *args], env=env).returncode


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
    elif command in DELEGATED:
        sys.exit(_delegate_to_client(command, cmd_args))
    else:
        # A genuinely unknown command is an ERROR: exit non-zero so a typo in a
        # script or CI step fails loudly instead of reporting success.
        print(f"Unknown command: {command}")
        _help([])
        sys.exit(EXIT_UNKNOWN_COMMAND)


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

    Generated from the COMMANDS, DELEGATED and GENERATORS registries — the SAME
    single source of truth that drives dispatch (`main`) and the
    `commands --json` manifest — so the help text can never drift from what the
    CLI actually does.
    """
    command_rows = [
        (f"{name} {spec.get('usage', '')}".rstrip(), spec["summary"])
        for name, spec in COMMANDS.items()
    ]
    delegated_rows = [
        (f"{name} {spec.get('usage', '')}".rstrip(), spec["summary"])
        for name, spec in DELEGATED.items()
    ]
    generator_rows = [
        (f"generate {name} {spec.get('usage', '')}".rstrip(), spec["summary"])
        for name, spec in GENERATORS.items()
    ]
    # Align summaries in a column; a left cell longer than the cap overflows
    # cleanly (2-space gap) rather than pushing every other summary out.
    pad = min(46, max(len(left) for left, _ in command_rows + delegated_rows + generator_rows))

    def row(left, summary):
        gap = pad if len(left) <= pad else len(left)
        return f"  {left:<{gap}}  {summary}"

    lines = ["", "Tina4 Python — CLI", "", "Usage: tina4python <command> [options]", "", "Commands:"]
    lines += [row(left, summary) for left, summary in command_rows]
    lines += ["", f"Delegated to the {CLIENT_BINARY} client (same behaviour in every framework):"]
    lines += [row(left, summary) for left, summary in delegated_rows]
    lines += [f"  (these run the {CLIENT_BINARY} client — install: "
              f"curl -fsSL https://tina4.com/install.sh | sh)"]
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
    from tina4_python.orm import bind_database
    from tina4_python.debug import Log
    from tina4_python.api import Api
    from tina4_python.core.events import on, emit

    # Try to connect database from TINA4_DATABASE_URL. Honour the SEPARATE
    # credential env vars (TINA4_DATABASE_USERNAME/PASSWORD) — the documented
    # Tina4 convention keeps credentials out of the URL, so building the handle
    # from the URL alone left `db` unauthenticated and it failed on every
    # credentialed engine (PostgreSQL/MySQL/Firebird/MSSQL). Bind it globally
    # too, so the `db` handle and the ORM models share ONE connected instance
    # (mirrors ORM._get_db()'s own lazy auto-bind).
    db = None
    db_url = os.environ.get("TINA4_DATABASE_URL")
    if db_url:
        try:
            username = os.environ.get("TINA4_DATABASE_USERNAME", "")
            password = os.environ.get("TINA4_DATABASE_PASSWORD", "")
            db = Database(db_url, username, password)
            bind_database(db)
            # Redacted, always. This printed the raw TINA4_DATABASE_URL - so
            # `tina4 console` put the production password on the terminal, into
            # scrollback, and into any transcript or screen share of it.
            from tina4_python.database.database_url import redact_url
            print(f"  Database: {redact_url(db_url)}")
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

    # Create pyproject.toml — a Tina4 project is a uv project. The Dockerfiles
    # already COPY pyproject.toml + uv.lock and `uv sync`, so a fresh project
    # MUST ship a manifest. This is also what makes `deps/install` (uv add) and
    # `uv run pytest` work out of the box. pytest ships in the dev group so the
    # scaffolded tests are runnable from the first commit (tests-first).
    pyproject = target / "pyproject.toml"
    if not pyproject.exists():
        project_name = target.resolve().name.replace(" ", "-").lower() or "tina4-app"
        pyproject.write_text(
            '[project]\n'
            f'name = "{project_name}"\n'
            'version = "0.1.0"\n'
            'description = "A Tina4 application"\n'
            'requires-python = ">=3.11"\n'
            'dependencies = [\n'
            '    "tina4-python",\n'
            ']\n\n'
            '[dependency-groups]\n'
            'dev = [\n'
            '    "pytest",\n'
            ']\n\n'
            '[tool.uv]\n'
            'package = false\n',
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
            'ENV TINA4_OVERRIDE_CLIENT=true\nENV TINA4_DEBUG=false\n'
            'EXPOSE 7146\nCMD ["tina4python", "serve", "--production"]\n',
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
    print("  Then: open the dev admin at /__dev, paste your Tina4 MCP key,")
    print("        and describe what to build. See https://tina4.com/build-with-ai")


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

    # --no-kill opts out of port takeover for the whole process, so the CLI path
    # here AND the runtime bind-failure fallback both honour it (TAKEOVER-DEC-03).
    if "no-kill" in flags:
        os.environ["TINA4_NO_TAKEOVER"] = "true"

    # Reclaim the port from a stale Tina4 dev server only (identity-checked).
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
    """Create a new migration file.

    Thin delegation to `_emit_resolution("migration", ...)` — the same code
    path `tina4python generate migration <desc>` takes — so both CLI surfaces
    emit the SAME ADR-0063 `generate_v1_1` envelope, the SAME `tina4:edit`
    markers in the file, and the SAME next-steps block. The only intentional
    difference is that `migrate:create` never co-emits a test file (a private
    `_no_test` marker on the flags dict suppresses the test-emit path in
    `_gen_migration` and drops `test_paths[]` in the resolution), preserving
    the "just a migration, no test" contract of `migrate:create`. Neither
    surface is deprecated; both stay first-class producers of the envelope.

    The Python API `create_migration()` in `tina4_python.migration.runner` is
    unchanged and still callable directly.
    """
    if not args:
        print("Usage: tina4python migrate:create <description>")
        sys.exit(1)
    # Split flags vs positional so `--json` / `--dry-run` flow through the
    # envelope emitter (bare word args form the description).
    flags, positional = _parse_flags(list(args))
    if not positional:
        print("Usage: tina4python migrate:create <description>")
        sys.exit(1)
    desc = " ".join(positional)
    # Private marker read by _gen_migration + _resolve_generation to suppress
    # the co-emitted test — see the `migrate:create` contract above.
    flags["_no_test"] = True
    _emit_resolution("migration", desc, flags)


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
            print(f"  [batch {m['batch']}] {m['migration_name']}  ({m['executed_at']})")
    else:
        print("\nNo completed migrations.")

    if pending:
        print("\nPending migrations:")
        for m in pending:
            print(f"  {m['migration_name']}  ({m['description']})")
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
    from tina4_python.core import discover_routes
    routes = discover_routes("src/routes")
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


def _run_inline_tests(root: Path) -> bool:
    """Discover ``@tests``-decorated functions under ``src/`` and run them.

    Returns True if any inline test FAILED or ERRORED (so the caller can exit
    non-zero), False if everything passed or there were no inline tests.

    Only files whose text contains ``@tests`` are imported — a source file
    without an inline test is never executed, so ``tina4 test`` cannot run a
    scanned file's arbitrary side effect. This is the ``@tests`` decorator
    surface wired to a real exit code (INLINE-DEC-01).
    """
    import importlib.util

    from tina4_python.Testing import reset, run_all

    src = root / "src"
    if not src.is_dir():
        return False

    reset()
    discovered = 0
    for path in sorted(src.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "@tests" not in text:
            continue
        discovered += 1
        module_name = "tina4_inline_" + re.sub(r"\W", "_", str(path.relative_to(root)))
        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            continue
        try:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001 — report and keep going
            print(f"  ! could not import {path.relative_to(root)}: {exc}")

    if discovered == 0:
        return False

    results = run_all()
    return (results["failed"] + results["errors"]) > 0


def _test(args):
    """Run the inline ``@tests`` suite AND the pytest suite; exit non-zero if either fails.

    The inline stage discovers ``@tests``-decorated functions under ``src/`` and
    runs them with a real exit code (INLINE-DEC-01) — the batteries-included flow
    the docs advertise. The pytest stage still runs the ``tests/`` suite when that
    directory exists (preserving the python#96 exit-code contract), so a project
    that keeps its tests in ``tests/`` is unaffected.
    """
    inline_failed = _run_inline_tests(Path.cwd())

    pytest_code = 0
    if Path("tests").is_dir():
        pytest_code = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/"] + args
        ).returncode

    sys.exit(1 if (inline_failed or pytest_code) else 0)


def _resolve_ruff(root: Path):
    """Locate a runnable ruff and return its command prefix (a list), or None.
    Checks PATH first, then the project's own virtualenv (where ``uv add --dev
    ruff`` puts it) on POSIX and Windows layouts."""
    on_path = shutil.which("ruff")
    if on_path:
        return [on_path]
    for candidate in (root / ".venv" / "bin" / "ruff", root / ".venv" / "Scripts" / "ruff.exe"):
        if candidate.is_file():
            return [str(candidate)]
    return None


def _lint(args):
    """Lint the project's source. The framework ships NO linter (so a Tina4 app
    stays zero-dependency); ``tina4 lint`` uses the project's own ``ruff`` and
    INSTALLS it as a DEV dependency on demand when it is absent. Layers:

    * **ruff present** (on PATH or in the project ``.venv``): run it. ``--fix``
      runs ``ruff check --fix`` (safe autofixes). ruff reports syntax too, so it
      is the whole pass when present.
    * **ruff absent:** silently ``uv add --dev ruff`` -- running ``tina4 lint`` is
      the consent to add it -- then run it. It lands in the DEV group only, never
      the app's runtime dependencies. ``--no-install`` skips this.
    * **Baseline (zero dependency):** the built-in ``compile()`` syntax parse --
      no execution, no ``.pyc``, no dependency. Used with ``--no-install`` or when
      the install cannot run (no ``uv`` on PATH, offline).

    Contract (identical across all four frameworks): exit 0 = clean, non-zero =
    findings; the summary names the tool that ran. Scope is the user's app
    (``src/`` + ``app.py``), mirroring how ``tina4 test`` runs the project's own
    tests -- not the framework's code.

        tina4 lint               # ruff (installed dev-only on demand), else baseline
        tina4 lint --fix         # ruff --fix
        tina4 lint --no-install  # ruff if already present, else the syntax baseline
    """
    flags, _ = _parse_flags(list(args))
    fix = bool(flags.get("fix"))
    no_install = bool(flags.get("no-install"))
    root = Path.cwd()

    py_files = []
    src = root / "src"
    if src.is_dir():
        py_files.extend(sorted(src.rglob("*.py")))
    if (root / "app.py").is_file():
        py_files.append(root / "app.py")
    if not py_files:
        print("  lint: nothing to lint (no src/ or app.py).")
        sys.exit(0)

    ruff = _resolve_ruff(root)

    # Silent on-demand install: running `tina4 lint` is the consent to add ruff
    # as a DEV dependency of the project. --no-install opts out (CI / offline) and
    # falls through to the zero-dependency baseline. Needs `uv` on PATH.
    if not ruff and not no_install and shutil.which("uv"):
        print("  · ruff not found -- adding it as a dev dependency (uv add --dev ruff)...")
        rc = subprocess.run(["uv", "add", "--dev", "ruff"]).returncode
        if rc == 0:
            ruff = _resolve_ruff(root)
        else:
            print("  · could not install ruff -- using the zero-dependency syntax baseline.")

    if ruff:
        cmd = ruff + ["check"] + (["--fix"] if fix else []) + [str(p) for p in py_files]
        code = subprocess.run(cmd).returncode
        label = "ruff --fix" if fix else "ruff"
        if code != 0:
            print(f"  ✗ lint failed -- {len(py_files)} file(s) [{label}]")
            sys.exit(1)
        print(f"  ✓ lint clean -- {len(py_files)} file(s) [{label}]")
        sys.exit(0)

    # Zero-dependency baseline: built-in compile() syntax parse. No execution,
    # no bytecode written, no dependency added.
    if fix:
        print("  · syntax baseline has no autofix (--no-install, or ruff unavailable).")
    syntax_errors = 0
    for pf in py_files:
        try:
            compile(pf.read_text(encoding="utf-8", errors="ignore"), str(pf), "exec")
        except SyntaxError as exc:
            print(f"  ✗ {pf.relative_to(root)}:{exc.lineno}: {exc.msg}")
            syntax_errors += 1
        except OSError as exc:
            print(f"  ✗ {pf.relative_to(root)}: cannot read ({exc})")
            syntax_errors += 1
    if syntax_errors:
        print(f"  ✗ lint failed -- {syntax_errors} syntax error(s) in {len(py_files)} file(s) [compile]")
        sys.exit(1)
    print(f"  ✓ lint clean -- {len(py_files)} file(s) [compile, syntax only]")
    sys.exit(0)


def _build(args):
    """Build the deployable Docker image for this Tina4 app.

    A Tina4 app deploys as a container — ``tina4python init`` and ``tina4 deploy
    docker`` both scaffold a Dockerfile — so ``build`` produces THAT artifact:
    the image. It shells out to the ``docker`` CLI (no new Python dependency)
    and fails loud with guidance when there is no Dockerfile or docker is not on
    PATH, instead of silently packaging the framework as a Python library (the
    old ``python -m build`` fallback shipped the lib, not the app).

        tina4python build                    # docker build -t <dir>:latest .
        tina4python build --tag myapp:1.2     # explicit image tag
        tina4python build --file docker/uv/Dockerfile
    """
    import shutil

    flags, _ = _parse_flags(args)

    tag = flags.get("tag")
    if not tag or tag is True:
        # Default tag: <project-folder>:latest, lower-cased (docker repo names
        # must be lowercase). Fall back to a sane name for an unnamed cwd.
        tag = f"{(Path.cwd().name.lower() or 'tina4app')}:latest"

    dockerfile = Path(flags.get("file") or "Dockerfile")
    if not dockerfile.is_file():
        print(f"  ✗ No {dockerfile} found.")
        print("  A Tina4 app deploys as a container. Scaffold a Dockerfile first:")
        print("      tina4 deploy docker        (or: tina4python init)")
        sys.exit(1)

    docker = shutil.which("docker")
    if not docker:
        print("  ✗ docker was not found on PATH.")
        print("  Install Docker to build the deployable image, or build manually:")
        print(f"      docker build -t {tag} -f {dockerfile} .")
        sys.exit(1)

    print(f"  Building image {tag} from {dockerfile} ...")
    result = subprocess.run([docker, "build", "-t", tag, "-f", str(dockerfile), "."])
    if result.returncode != 0:
        print(f"  ✗ docker build failed (exit {result.returncode})")
        sys.exit(result.returncode)
    print(f"  ✓ Built image {tag}")
    print(f"  Run: docker run -p 7146:7146 {tag}")


def _ai(args):
    """Install AI coding assistant context files."""
    from tina4_python.ai import show_menu, install_selected, install_context

    if args and args[0].lower() == "all":
        install_context(".")
    else:
        selection = show_menu(".")
        if selection:
            install_selected(".", selection)


# ── Generate resolution envelope (ADR-0062, agent-experience contract) ─────
#
# Every `generate model/route/migration/middleware` call ALSO exposes the
# mapping the framework decided to build — the class name, the (maybe
# pluralized) table name, every file it will write, and every transformation
# it applied. An agent (or a human) sees WHAT was chosen without having to
# reverse-engineer it from the generated files. Emitted as a JSON envelope
# on `--json`, as a human block on stderr for bare invocations, and skipping
# every write on `--dry-run` (composable with `--json`).
#
# The envelope shape is the SAME across all four language backends and is
# advertised as `resolution_contract` on the `commands --json` manifest so a
# caller can programmatically discover the schema version.

# The four generators wired for the envelope. Others (crud, service, queue,
# validator, seeder, websocket, listener, auth, test, form, view) keep their
# existing behaviour — this is the minimum surface the plan calls out.
_RESOLUTION_TARGETS = {"model", "route", "migration", "middleware", "queue"}

# Envelope schema version. Bump when the SHAPE changes; adding an optional
# key on the resolution object is not a break.
#
# 1.1 (ADR-0063 Wave 1, 3.13.120): additive keys `edit_hints[]` and `next[]`
# on `resolution`, plus `test_paths[]` (already emitted since v1) is now
# surfaced in the human stderr block too. Every existing generator template
# bakes `tina4:edit` markers at first-edit spots so a caller sees exactly
# where to point a follow-up patch. Old envelope keys are preserved; a v1
# consumer sees the v1 shape intact and simply ignores the new keys.
_RESOLUTION_ENVELOPE_VERSION = "1.1"
_RESOLUTION_ENVELOPE_NAME = "generate_v1_1"

# Marker syntax the generator templates bake in at first-edit spots — accepts
# a Python (`#`), SQL (`--`), or Twig (`{#`) comment prefix, followed by a
# short actionable label. The label ends at end-of-line or a closing Twig `#}`.
# NEVER matches inside a string literal — the compiler regex is a plain textual
# scan of freshly-written source, but no template contains a matching literal.
_EDIT_MARKER_RE = re.compile(
    r"(?:#|--|\{#)\s*tina4:edit\s+([^\n#]+?)\s*(?:#\})?\s*$"
)


def _input_fields(flags: dict):
    """Normalise `--fields` back into the envelope's `input.fields` field.

    A missing / bare / boolean `--fields` maps to null so an agent can rely on
    the shape; a real "name:string,price:float" value is preserved as-is (the
    raw text the caller actually supplied).
    """
    value = flags.get("fields")
    if not isinstance(value, str) or not value:
        return None
    return value


def _scan_edit_hints(root: Path, rel_paths: list[str]) -> list[dict]:
    """Grep freshly-written files for `tina4:edit` markers (envelope v1.1).

    Reads each `rel_paths` entry under `root`, walks its lines, and returns
    `[{file, line, label}]` — one entry per marker, in file+line order.

    A missing file is silently skipped: the caller wires this into the
    envelope path where `actions_taken` is the source of truth for what
    landed. The scan is text-only — no imports, no parsing — so an edited
    template that fails to run still yields honest hints.
    """
    hints: list[dict] = []
    for rel in rel_paths:
        f = root / rel
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            match = _EDIT_MARKER_RE.search(line)
            if match:
                hints.append({
                    "file": rel,
                    "line": lineno,
                    "label": match.group(1).strip(),
                })
    return hints


def _hint_paths_from_resolution(target: str, resolution: dict) -> list[str]:
    """The set of paths the caller should scan for `tina4:edit` markers.

    Every path the generator ACTUALLY writes is worth scanning — the model
    file, the matching migration + down, the middleware file, the co-emitted
    test — because a marker in any of them names a first-edit spot the
    developer will hit. Order is stable: primary file, then migration + down,
    then any test paths declared in the envelope. The hints themselves land
    in file+line order regardless.
    """
    paths: list[str] = []
    primary = resolution.get("file_path")
    if primary:
        paths.append(primary)

    # Model + migration composite: the migration is written by _gen_migration
    # under the model's own generator, so its markers deserve to surface too.
    if target == "model" and resolution.get("migration_path"):
        migration = resolution["migration_path"]
        paths.append(migration)
        if migration.endswith(".sql"):
            paths.append(migration[:-len(".sql")] + ".down.sql")

    # A bare migration also writes its own .down.sql.
    if target == "migration" and primary and primary.endswith(".sql"):
        paths.append(primary[:-len(".sql")] + ".down.sql")

    # Co-emitted tests carry their own markers (see the test template).
    for test_path in resolution.get("test_paths", []):
        if test_path not in paths:
            paths.append(test_path)
    return paths


def _next_steps_for(target: str, name: str, resolution: dict, flags: dict) -> list[str]:
    """Curated actionable next-steps a caller should see after generation.

    Kept short and concrete: what to edit, what to run, how to try it. The
    entries are per-target because a generic "next steps" list dilutes into
    noise — a route's next step is `curl`, a middleware's next step is
    `@middleware(...)` on a real route.

    Placeholders are resolved from the same shape the envelope already
    reports (class_name, table_name, routes), so a caller can trust the
    strings match what actually landed on disk.
    """
    if target == "model":
        table = resolution.get("table_name") or _to_table(name)
        return [
            f"Edit src/orm/{name}.py to add fields beyond the default `name`",
            "Apply the migration:      tina4 migrate",
            f"Scaffold CRUD around it:  tina4 generate crud {name} --skip-model",
            f"Try it:                   tina4 serve  ->  curl http://localhost:7146/api/{table}",
        ]

    if target == "route":
        route_path = name.lstrip("/")
        first_url = (resolution.get("routes") or [f"/api/{route_path}"])[0]
        return [
            f"Edit src/routes/{route_path}.py to customise the handlers",
            "Start the server:  tina4 serve",
            f"Try it:            curl http://localhost:7146{first_url}",
        ]

    if target == "migration":
        return [
            "Apply it:              tina4 migrate",
            "Roll back last batch:  tina4 migrate --rollback",
            "Inspect the pending:   tina4 migrate --status",
        ]

    if target == "middleware":
        snake = _to_snake(name)
        return [
            f"Register it on a route with @middleware({name}) in src/routes/",
            f"Run the co-emitted test:  .venv/bin/python -m pytest tests/test_{snake}.py",
        ]

    if target == "queue":
        topic = name.lstrip("/")
        slug = _to_snake(re.sub(r"[^0-9a-zA-Z]+", "_", topic)).strip("_") or "topic"
        return [
            f"Edit src/services/{slug}_consumer.py: implement handle_{slug}(data) to process ONE job",
            f"Produce a job:  from src.services.{slug}_consumer import publish_{slug}; publish_{slug}({{...}})",
            f"The consumer is discovered by ServiceRunner (src/services); tina4 serve runs it",
            f"Run the co-emitted test:  .venv/bin/python -m pytest tests/test_{slug}.py",
        ]

    return []


def _resolve_generation(target: str, name: str, flags: dict,
                        timestamp: str | None = None) -> dict:
    """Compute the resolution mapping for a generate call. Pure — no writes.

    Called BEFORE the generator runs, so the same envelope drives both --json
    (emit + write) and --dry-run (emit + skip) without a second walk of the
    tree. Timestamps for migration filenames are locked at the call site and
    threaded through the underlying generator via the private `_timestamp`
    flag, so the envelope path always equals the on-disk filename.
    """
    ts = timestamp or datetime.now().strftime("%Y%m%d%H%M%S")

    if target == "model":
        raw_table = _to_snake(name)
        table = _to_table(name)
        transformations = []
        if raw_table in SQL_RESERVED_TABLE_NAMES and raw_table != table:
            transformations.append({
                "kind": "reserved_word_pluralize",
                "from": raw_table,
                "to": table,
                "reason": f"SQL reserved word '{raw_table}' would break CREATE TABLE",
                "override": (
                    f"--table {raw_table} --quote (requires quoted-identifier "
                    "mode, not yet implemented)"
                ),
            })
        migration_filename = f"{ts}_create_{table}.sql"
        return {
            "class_name": name,
            "table_name": table,
            "file_path": f"src/orm/{name}.py",
            "migration_path": f"migrations/{migration_filename}",
            "transformations": transformations,
            "routes": [],
            "test_paths": [f"tests/test_{table}_model.py"],
        }

    if target == "route":
        route_path = name.lstrip("/")
        return {
            "class_name": None,
            "table_name": None,
            "file_path": f"src/routes/{route_path}.py",
            "migration_path": None,
            "transformations": [],
            "routes": [
                f"/api/{route_path}",
                f"/api/{route_path}/{{id:int}}",
            ],
            "test_paths": [f"tests/test_{route_path}.py"],
        }

    if target == "migration":
        table = name.removeprefix("create_").removeprefix("add_").removeprefix("drop_")
        table = _to_snake(table)
        filename = f"{ts}_{name}.sql"
        is_create = name.startswith("create_")
        # Private `_no_test` marker (set by `migrate:create`, which is a
        # single-file operation): drop `test_paths[]` so the envelope
        # matches the on-disk effect. `_gen_migration` reads the same flag.
        want_test = is_create and not flags.get("_no_test")
        return {
            "class_name": None,
            "table_name": table,
            "file_path": f"migrations/{filename}",
            "migration_path": f"migrations/{filename}",
            "transformations": [],
            "routes": [],
            "test_paths": [f"tests/test_{table}_migration.py"] if want_test else [],
        }

    if target == "middleware":
        snake = _to_snake(name)
        return {
            "class_name": name,
            "table_name": None,
            "file_path": f"src/middleware/{snake}.py",
            "migration_path": None,
            "transformations": [],
            "routes": [],
            "test_paths": [f"tests/test_{snake}.py"],
        }

    if target == "queue":
        # Slug computed EXACTLY as _gen_queue does, so the envelope's paths
        # equal the on-disk filenames byte-for-byte.
        topic = name.lstrip("/")
        slug = _to_snake(re.sub(r"[^0-9a-zA-Z]+", "_", topic)).strip("_") or "topic"
        return {
            "class_name": None,
            "table_name": None,
            "file_path": f"src/services/{slug}_consumer.py",
            "migration_path": None,
            "transformations": [],
            "routes": [],
            "test_paths": [f"tests/test_{slug}.py"],
        }

    return {}  # never reached; guarded by _RESOLUTION_TARGETS


def _actions_from_resolution(target: str, resolution: dict) -> list[str]:
    """Flat "wrote X" list mirroring what the generators actually write.

    The generators print `  ✓ Created <path>` per file; this reconstructs the
    same list from the resolution so the envelope's `actions_taken` matches
    the on-disk effect without having to shadow the generator's own I/O.
    """
    actions: list[str] = []
    file_path = resolution.get("file_path")
    if file_path:
        actions.append(f"wrote {file_path}")

    # Migration + its matching .down.sql — _gen_migration writes both.
    if target == "model" and resolution.get("migration_path"):
        migration = resolution["migration_path"]
        actions.append(f"wrote {migration}")
        actions.append(f"wrote {migration[:-len('.sql')]}.down.sql")
    if target == "migration" and file_path and file_path.endswith(".sql"):
        actions.append(f"wrote {file_path[:-len('.sql')]}.down.sql")

    for test_path in resolution.get("test_paths", []):
        actions.append(f"wrote {test_path}")

    return actions


def _format_resolution_block(name: str, target: str, resolution: dict,
                             dry_run: bool = False,
                             edit_hints: list[dict] | None = None,
                             next_steps: list[str] | None = None) -> str:
    """Render the human-readable resolution block for stderr on bare calls.

    Same shape as the plan / ADR-0062 example. A generator with no route/table
    footprint (middleware, route without a matching table) simply omits the
    lines that don't apply — the block is honest about what was chosen.

    ADR-0063 (envelope v1.1) also surfaces `test_paths[]` (was in the envelope
    since v1, never printed), plus `edit_hints[]` under "Edit these lines:"
    and `next_steps[]` under "Next:". Each section omits when empty so the
    block never grows a header without content beneath it.
    """
    suffix = "  (dry-run — nothing written)" if dry_run else ""
    lines = [f"Generated {target} {name}{suffix}"]

    class_name = resolution.get("class_name")
    file_path = resolution.get("file_path")
    if class_name and file_path:
        lines.append(f"  class      {class_name}  (in {file_path})")
    elif file_path:
        lines.append(f"  file       {file_path}")

    pluralize = next(
        (t for t in resolution.get("transformations", [])
         if t.get("kind") == "reserved_word_pluralize"),
        None,
    )
    if resolution.get("table_name"):
        note = ""
        if pluralize:
            note = f"  (auto-pluralized: '{pluralize['from']}' is a SQL reserved word)"
        lines.append(f"  table      {resolution['table_name']}{note}")

    if resolution.get("routes"):
        lines.append(f"  routes     {', '.join(resolution['routes'])}")
    if target != "migration" and resolution.get("migration_path"):
        lines.append(f"  migration  {resolution['migration_path']}")

    # ADR-0063: surface test_paths[] in the human block too (it has been in the
    # envelope since v1 but only the JSON path printed it). Skipped when empty
    # so a migration without a test file doesn't grow an empty "tests" row.
    test_paths = resolution.get("test_paths") or []
    if test_paths:
        lines.append(f"  tests      {', '.join(test_paths)}")

    if pluralize:
        lines.append("")
        lines.append(f"  To keep the raw name '{pluralize['from']}' as the table:")
        lines.append(
            f"    tina4 generate {target} {name} "
            f"--table {pluralize['from']} --quote  "
            "(opt-in, ADR-0062 forthcoming)"
        )

    # ADR-0063 additive sections. Each renders only when there is content, so
    # a target with no markers or no next-steps stays as tight as before.
    if edit_hints:
        lines.append("")
        lines.append("Edit these lines:")
        # Left-pad the file:line column so labels align — makes scanning easier
        # when there are three or four hints of different path lengths.
        addrs = [f"{h['file']}:{h['line']}" for h in edit_hints]
        width = max(len(a) for a in addrs)
        for addr, hint in zip(addrs, edit_hints):
            lines.append(f"  {addr:<{width}}  {hint['label']}")

    if next_steps:
        lines.append("")
        lines.append("Next:")
        for i, step in enumerate(next_steps, start=1):
            lines.append(f"  {i}. {step}")

    return "\n".join(lines) + "\n"


def _emit_resolution(target: str, name: str, flags: dict) -> None:
    """Handle the --json / --dry-run / bare paths for the 4 wired generators.

    Contract shared by every language (ADR-0062, extended by ADR-0063):
    - --json           → envelope on stdout; nothing else on stdout.
    - --dry-run        → skip every write; envelope with dry_run=true.
    - --json + --dry-run → both compose (envelope with actions_taken=[]).
    - bare             → normal write, then human resolution block on stderr.

    Envelope v1.1 (ADR-0063) additively surfaces `resolution.edit_hints[]`
    (one per `tina4:edit` marker found in freshly-written files) and
    `resolution.next[]` (curated actionable next-steps per verb). The
    hints are scanned from disk on the write paths; on --dry-run the
    generator runs in a throw-away tmpdir so the same scan gives the
    caller a real preview without touching the working tree.
    """
    import contextlib
    import io
    import json as _json
    import tempfile

    dry_run = bool(flags.get("dry-run"))
    want_json = bool(flags.get("json"))

    # Lock the timestamp so the envelope's migration_path and the on-disk
    # filename agree byte-for-byte (threaded through via `_timestamp` flag).
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    resolution = _resolve_generation(target, name, flags, timestamp=timestamp)

    handler = GENERATORS[target]["handler"]
    generator_flags = dict(flags)
    generator_flags["_timestamp"] = timestamp
    # `_gen_*` handlers read the primary flags; `--dry-run` / `--json` are
    # envelope-only concerns, they must not leak into the underlying writer.
    generator_flags.pop("dry-run", None)
    generator_flags.pop("json", None)

    actions_taken: list[str] = []
    edit_hints: list[dict] = []

    hint_paths = _hint_paths_from_resolution(target, resolution)

    if dry_run:
        # Render into a throw-away tree so the scan sees the SAME bytes the
        # writer would drop on disk. The envelope's paths still point at the
        # real project paths (unchanged by the tmpdir chdir) — the caller
        # can trust `edit_hints[].file` and `resolution.file_path` share a
        # coordinate space.
        with tempfile.TemporaryDirectory() as tmp:
            original_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                # Suppress the generator's own "Created X" lines — this is a
                # dry-run, and its "creations" happen in a tmpdir the caller
                # will never see. `--json` also swallows stdout on the real
                # write path; this keeps the two paths symmetrical.
                with contextlib.redirect_stdout(io.StringIO()):
                    handler(name, generator_flags)
                edit_hints = _scan_edit_hints(Path(tmp), hint_paths)
            finally:
                os.chdir(original_cwd)
    else:
        # Real write. When --json we swallow the generator's stdout so the
        # JSON envelope is the SOLE thing on stdout; otherwise we let its
        # "Created X" lines through as before.
        stdout_sink = io.StringIO() if want_json else sys.stdout
        with contextlib.redirect_stdout(stdout_sink):
            handler(name, generator_flags)

        actions_taken = _actions_from_resolution(target, resolution)
        edit_hints = _scan_edit_hints(Path.cwd(), hint_paths)

    # ADR-0063 additive envelope keys — computed once and reused by the JSON
    # and human paths so what the caller sees on stderr matches the envelope
    # byte-for-byte.
    next_steps = _next_steps_for(target, name, resolution, flags)
    resolution["edit_hints"] = edit_hints
    resolution["next"] = next_steps

    envelope = {
        "command": "generate",
        "target": target,
        "input": {"name": name, "fields": _input_fields(flags)},
        "resolution": resolution,
        "actions_taken": actions_taken,
        "dry_run": dry_run,
    }

    if want_json:
        print(_json.dumps(envelope, indent=2))
    else:
        # Human resolution block always lands on STDERR (per plan): stdout
        # keeps whatever the generator printed on the bare path, and the
        # block never contends with a caller parsing stdout.
        sys.stderr.write(_format_resolution_block(
            name, target, resolution,
            dry_run=dry_run,
            edit_hints=edit_hints,
            next_steps=next_steps,
        ))


# ── Generate (rich scaffolding) ───────────────────────────────────────

def _generate(args):
    """Generate scaffolding.

    CRUD-shaped generators (crud/form/view/migration/model/test/auth/validator/
    seeder) emit working code — the boilerplate IS the feature. Logic-shaped
    generators (route/service/queue/websocket/listener) scaffold the WIRING
    (real imports + registration + signature + error skeleton) and drop a
    single ``# your code here`` placeholder (``raise NotImplementedError``) where
    the custom logic goes, so an unfilled scaffold fails loud.

    Every code-producing generator also co-emits a REAL, green, no-mock test
    next to the code (via ``_write_test``): CRUD-shaped tests exercise the
    working scaffold against a real dependency (SQLite / TestClient / Queue);
    logic-shaped tests assert the real wiring + lock in that the placeholder
    fails loud. ``test`` (it IS the test generator) and ``form``/``view``
    (template-only, no logic to run) are the only exemptions.
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

    # ADR-0062: the four wired generators expose a JSON envelope and a
    # stderr resolution block on every call, so an agent can see WHAT the
    # framework decided to build with its input. --json emits the envelope;
    # --dry-run computes it without writing; bare calls print the human
    # block to stderr AFTER the normal writes complete.
    if what in _RESOLUTION_TARGETS:
        _emit_resolution(what, name, flags)
        return

    # Dispatch from the module-level GENERATORS registry (single source of truth
    # for the generate subcommands; also feeds `_help` and the manifest).
    gen_spec = GENERATORS.get(what)
    if gen_spec:
        gen_spec["handler"](name, flags)
    else:
        print(f"Unknown generator: {what}")
        print(f"  Available: {_all}")
        sys.exit(1)


def _gen_model(name: str, flags: dict, *, emit_test: bool = True):
    """Generate ORM model + matching migration (+ a real co-emitted test).

    tina4python generate model Product
    tina4python generate model Product --fields "name:string,price:float,in_stock:bool"

    ``emit_test`` (default True) co-emits tests/test_<table>_model.py — a real
    SQLite roundtrip test. Composite generators (crud/auth) pass emit_test=False
    and emit their own broader test instead.
    """
    fields = _fields_or_default(flags.get("fields", ""))
    table = _to_table(name)

    # Determine which ORM field types we need to import
    used_types = {"IntegerField"}  # always need for id
    for _, ftype in fields:
        info = FIELD_TYPE_MAP.get(ftype, FIELD_TYPE_MAP["string"])
        used_types.add(info["orm"])
    used_types.add("DateTimeField")  # for created_at

    imports = ", ".join(sorted(used_types))

    # Build field lines. Bracketed by two `tina4:edit` markers (ADR-0063) so
    # a first-time user sees WHERE to add columns and relationships — the
    # `id` and `created_at` lines are framework-managed, the block between
    # is theirs to grow.
    field_lines = [
        "    id = IntegerField(primary_key=True, auto_increment=True)",
        "    # tina4:edit  add fields here",
    ]
    for fname, ftype in fields:
        info = FIELD_TYPE_MAP.get(ftype, FIELD_TYPE_MAP["string"])
        field_lines.append(f"    {fname} = {info['orm']}()")
    field_lines.append("    # tina4:edit  add relationships here (e.g. author = ForeignKeyField(to=Author))")
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

    # Generate matching migration (unless --no-migration). The model's own test
    # (below) proves the schema through the real ORM, so the migration sub-call
    # does not also co-emit a migration test (emit_test=False).
    if "no-migration" not in flags:
        _gen_migration(f"create_{table}", flags, fields_override=fields,
                       table_override=table, emit_test=False)

    # Co-emit a real SQLite roundtrip test next to the model.
    if emit_test:
        _emit_model_test(name, table, fields)


def _gen_route(name: str, flags: dict, *, emit_test: bool = True):
    """Generate CRUD route file — SECURE BY DEFAULT (+ a real co-emitted test).

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
    page = int(request.query.get("page", 1))
    per_page = int(request.query.get("per_page", 20))
    offset = (page - 1) * per_page
    records, total = {model}.where("1=1", limit=per_page, offset=offset, with_count=True)
    # tina4:edit  customise the list projection (filters, ordering, fields)
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
    if item is False:
        return response({{"error": "Could not create {singular}"}}, 400)
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
    if item.save() is False:
        return response({{"error": "Could not update {singular}"}}, 400)
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

    # Co-emit a real test. A --model route is working code → the secure-gate
    # behavioural test (reads public, writes gated); a no-model route's handlers
    # are loud stubs → the Router-registration + live-stub test.
    if emit_test:
        if model:
            _gen_test(route_path, {"model": model, "secure_writes": True, "public": public})
        else:
            _emit_route_stub_test(route_path)


def _gen_crud(name: str, flags: dict):
    """Generate full CRUD stack: model + migration + routes + template + test.

    tina4python generate crud Product --fields "name:string,price:float"
    """
    fields = _fields_or_default(flags.get("fields", ""))
    table = _to_table(name)
    route_name = table + "s"  # routes are plural

    print(f"\n  Generating CRUD for {name}...\n")

    # 1. Model + migration (emit_test=False — crud emits its own broader test
    #    at step 6, so the sub-generators stay quiet to avoid double-emission).
    _gen_model(name, flags, emit_test=False)

    # 2. Routes with model — secure-by-default; thread --public through so
    #    `generate crud X --public` opens the writes (mirrors AutoCrud public=).
    is_public = bool(flags.get("public"))
    route_flags = {"model": name, "public": is_public}
    _gen_route(route_name, route_flags, emit_test=False)

    # 3. Template
    template_dir = Path("src/templates/pages")
    template_dir.mkdir(parents=True, exist_ok=True)
    template_path = template_dir / f"{route_name}.twig"
    if not template_path.exists():
        # Build column headers from fields
        cols = [f for f, _ in fields]
        th = "\n                ".join(f"<th>{c.replace('_', ' ').title()}</th>" for c in cols)
        td = "\n                ".join(f"<td>{{{{ item.{c} }}}}</td>" for c in cols)

        template_path.write_text(
            '{% extends "base.twig" %}\n'
            f'{{% block title %}}{name}s{{% endblock %}}\n'
            '{% block content %}\n'
            '<div class="container mt-4">\n'
            f'    <h1>{name}s</h1>\n'
            '    {# tina4:edit  restrict fields exposed to the API here #}\n'
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
                   fields_override: list = None, table_override: str = None,
                   emit_test: bool = True):
    """Generate a timestamped migration file with UP/DOWN sections.

    tina4python generate migration create_product
    tina4python generate migration add_category_to_product

    ``emit_test`` (default True) co-emits a real test that applies the UP then
    DOWN SQL against real SQLite and asserts the table appears then disappears —
    but only for CREATE migrations (a placeholder ALTER has no real SQL to
    assert yet). The model generator passes emit_test=False (its ORM test
    already proves the schema).
    """
    flags = flags or {}
    now = datetime.now()
    # ADR-0062: the resolution envelope pre-computes the migration path from a
    # snapshotted timestamp; if it was supplied via the private `_timestamp`
    # flag, honour it so envelope and disk agree byte-for-byte.
    timestamp = flags.get("_timestamp") or now.strftime("%Y%m%d%H%M%S")
    # Private `_no_test` marker (set by `migrate:create`, which is a
    # single-file operation): suppress the co-emitted test regardless of the
    # keyword default. `_resolve_generation` reads the same marker so the
    # envelope's `test_paths[]` and the on-disk effect stay in agreement.
    if flags.get("_no_test"):
        emit_test = False
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
        col_lines.append("    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

        # ADR-0063: `tina4:edit` marker between the last column and the closing
        # paren, placed OUTSIDE the comma-joined column list so the SQL stays
        # valid. Points a first-time user at where to add columns beyond the
        # framework-managed id + created_at.
        up_sql = (
            f"CREATE TABLE IF NOT EXISTS {table} (\n"
            + ",\n".join(col_lines)
            + "\n    -- tina4:edit  add columns beyond id + created_at\n);"
        )
        down_sql = f"DROP TABLE IF EXISTS {table};"
    else:
        up_sql = (f"-- tina4:edit  write the UP migration SQL\n"
                  f"-- Example: ALTER TABLE {table} ADD COLUMN new_col TEXT DEFAULT '';")
        down_sql = (f"-- tina4:edit  write the DOWN rollback SQL\n"
                    f"-- Example: ALTER TABLE {table} DROP COLUMN new_col;")

    content = (
        f"-- Migration: {name}\n"
        f"-- Created: {now.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"{up_sql}\n"
    )
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ Created {path}")

    # Also create .down.sql for the migration runner
    down_filename = f"{timestamp}_{name}.down.sql"
    down_path = target / down_filename
    down_path.write_text(
        f"-- Rollback: {name}\n"
        f"-- Created: {now.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"{down_sql}\n",
        encoding="utf-8",
    )
    print(f"  ✓ Created {down_path}")

    # Co-emit a real apply-up/down test — only for CREATE migrations, whose UP
    # SQL is real DDL to assert against (a placeholder ALTER has nothing yet).
    if emit_test and is_create:
        _emit_migration_test(name, table, filename, down_filename)


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
        # tina4:edit  guard the request here (auth check, rate limit, headers)
        Log.info(f"{name}: {{request.method}} {{request.url}}")
        return request, response

    @staticmethod
    def after_{snake}(request, response):
        """Runs after the route handler."""
        # tina4:edit  inject headers or audit the response here
        return request, response
'''
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ Created {path}")

    # Co-emit a real dispatch test (drives the scaffold through the real
    # server middleware dispatch).
    _emit_middleware_test(name, snake)


def _gen_test(name: str, flags: dict = None):
    """Generate a pytest test file.

    tina4python generate test products
    tina4python generate test products --model Product
    """
    flags = flags or {}
    model = flags.get("model", "")
    snake = _to_snake(name)
    singular = snake.rstrip("s") if snake.endswith("s") else snake

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
        _write_test(snake, content)
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
        # tina4:edit  add assertions here (real DB, real request — no mocks)
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
        # tina4:edit  add assertions here (real DB, real request — no mocks)
        assert True
'''

    _write_test(snake, content)


# ── Co-emitted tests — every code-producing generator ships a real, green,
#    no-mock test next to its code (owner req 2026-07-10, Phase 4). ────────
#
# One shared writer (_write_test) + one focused content builder per generator.
# The builders are NOT copy-paste boilerplate — each exercises a different real
# subsystem (real SQLite / TestClient / Router / ServiceRunner / Queue / event
# bus), grounded on the same real-collaborator patterns the acceptance matrix
# in tests/test_cli_generate.py already proves. CRUD-shaped scaffolds (working
# code) get behavioural tests; logic-shaped scaffolds (loud NotImplementedError
# stubs) get wiring tests + a lock-in that the placeholder fails loud.

def _write_test(test_name: str, content: str) -> None:
    """Write a co-emitted test to tests/test_<name>.py — the SINGLE place a
    generated test is written (path + overwrite refusal + the same ✓/✗ line
    every generator prints). Generalized from _gen_test so the generators share
    one rule instead of 12 copy-pasted write blocks."""
    target = Path("tests")
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"test_{test_name}.py"
    if path.exists():
        print(f"  ✗ File already exists: {path}")
        return
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ Created {path}")


def _pascal(name: str) -> str:
    """snake/kebab/dotted → PascalCase: user_created → UserCreated."""
    return "".join(part.capitalize() for part in re.split(r"[^0-9a-zA-Z]+", name) if part)


def _sample_literal(field_type: str) -> str:
    """A source-text Python literal that is a valid value for a scaffolded
    field type (used to build a real create() payload in the model test)."""
    return {
        "int": "1", "integer": "1",
        "float": "1.5", "numeric": "1.5", "decimal": "1.5",
        "bool": "True", "boolean": "True",
        "datetime": '"2020-01-01 00:00:00"',
        "blob": 'b"x"',
    }.get((field_type or "string").lower(), '"sample"')


def _emit_model_test(model: str, table: str, fields: list) -> None:
    """model → real SQLite roundtrip (create / read back / missing → None)."""
    # Reuse the single DEFAULT_FIELDS constant rather than re-stating the literal,
    # so the co-emitted test can never describe a shape the model does not have.
    fields = fields or list(DEFAULT_FIELDS)
    payload = ", ".join(f'"{fname}": {_sample_literal(ftype)}' for fname, ftype in fields)
    # Assert a STRING field round-trips (type-safe); else just the id round-trips
    # (avoids datetime/bool/float equality pitfalls on the read-back).
    string_field = next(
        (fname for fname, ftype in fields
         if (ftype or "string").lower() in ("string", "str", "text")), None)
    value_assert = f'        assert fetched.{string_field} == "sample"\n' if string_field else ""
    content = (
        '"""Real ORM roundtrip test for __MODEL__ — no mocks, real SQLite.\n'
        "\n"
        "Generated with src/orm/__MODEL__.py by `tina4python generate model\n"
        "__MODEL__`. The model scaffold is working code, so this passes on\n"
        "generation: it binds a real on-disk SQLite database, creates the table,\n"
        "saves a row and reads it back.\n"
        '"""\n'
        "from tina4_python.database import Database\n"
        "from tina4_python.orm.model import bind_database\n"
        "from src.orm.__MODEL__ import __MODEL__\n"
        "\n"
        "\n"
        "class Test__MODEL__Model:\n"
        '    """__MODEL__ persists to and reads back from real SQLite."""\n'
        "\n"
        "    def setup_method(self, _method):\n"
        '        bind_database(Database("sqlite:///test___TABLE___model.db"))\n'
        "        __MODEL__.create_table()\n"
        "\n"
        "    def test_create_and_read_back(self):\n"
        "        row = __MODEL__.create({__PAYLOAD__})\n"
        '        assert row and row.id, "create() should persist and return the row"\n'
        "        fetched = __MODEL__.find_by_id(row.id)\n"
        "        assert fetched is not None\n"
        "        assert fetched.id == row.id\n"
        "__VALUE_ASSERT__"
        "\n"
        "    def test_find_missing_returns_none(self):\n"
        "        assert __MODEL__.find_by_id(999999) is None\n"
    )
    content = (
        content.replace("__PAYLOAD__", payload)
        .replace("__VALUE_ASSERT__", value_assert)
        .replace("__MODEL__", model)
        .replace("__TABLE__", table)
    )
    _write_test(f"{table}_model", content)


def _emit_route_stub_test(route: str) -> None:
    """route (no --model) → real Router registration + the handler is a live
    loud stub. (route --model reuses the secure-gate _gen_test instead.)"""
    content = (
        '"""Routing test for __ROUTE__ — no mocks, real Router.\n'
        "\n"
        "Generated with src/routes/__ROUTE__.py by `tina4python generate route\n"
        "__ROUTE__` (no --model). The handlers are AI-FILL stubs that raise until\n"
        "you implement them, so this tests what IS live on generation: all five\n"
        "routes register on the REAL Router, and the list handler fails loud until\n"
        "filled. Fill a handler, then assert its real response here.\n"
        '"""\n'
        "import asyncio\n"
        "\n"
        "import pytest\n"
        "\n"
        "from tina4_python.core.request import Request\n"
        "from tina4_python.core.response import Response\n"
        "from tina4_python.core.router import Router\n"
        "import src.routes.__ROUTE__ as route_module  # importing registers the routes\n"
        "\n"
        "\n"
        "class Test__CLASS__Routing:\n"
        "    def test_all_five_routes_registered(self):\n"
        '        paths = {(r["method"], r["path"]) for r in Router.get_routes()}\n'
        '        assert ("GET", "/api/__ROUTE__") in paths\n'
        '        assert ("GET", "/api/__ROUTE__/{id:int}") in paths\n'
        '        assert ("POST", "/api/__ROUTE__") in paths\n'
        '        assert ("PUT", "/api/__ROUTE__/{id:int}") in paths\n'
        '        assert ("DELETE", "/api/__ROUTE__/{id:int}") in paths\n'
        "\n"
        "    def test_list_handler_is_a_live_stub(self):\n"
        '        """The scaffolded handler raises until filled (fails loud, good DX)."""\n'
        "        request = Request.from_scope(\n"
        '            {"type": "http", "method": "GET", "path": "/api/__ROUTE__",\n'
        '             "query_string": b"", "headers": [], "client": ("127.0.0.1", 0)}, b"")\n'
        "        with pytest.raises(NotImplementedError):\n"
        "            asyncio.run(route_module.list___ROUTE__(request, Response()))\n"
    )
    content = content.replace("__CLASS__", _pascal(route)).replace("__ROUTE__", route)
    _write_test(route, content)


def _emit_middleware_test(name: str, snake: str) -> None:
    """middleware → a request routed THROUGH the real server dispatch."""
    content = (
        '"""Real dispatch test for the __NAME__ middleware — no mocks.\n'
        "\n"
        "Generated with src/middleware/__SNAKE__.py by `tina4python generate\n"
        "middleware __NAME__`. Drives the middleware through the REAL server\n"
        "dispatch (_run_before_middleware / _run_after_middleware) with a real\n"
        "Request + Response — the same code path the live server runs.\n"
        '"""\n'
        "from tina4_python.core.request import Request\n"
        "from tina4_python.core.response import Response\n"
        "from tina4_python.core.server import _run_before_middleware, _run_after_middleware\n"
        "from src.middleware.__SNAKE__ import __NAME__\n"
        "\n"
        "\n"
        "def _request():\n"
        "    return Request.from_scope(\n"
        '        {"type": "http", "method": "GET", "path": "/", "query_string": b"",\n'
        '         "headers": [], "client": ("127.0.0.1", 0)}, b"")\n'
        "\n"
        "\n"
        "class Test__NAME__Middleware:\n"
        "    def test_before_passes_request_through(self):\n"
        '        route = {"middleware": [__NAME__]}\n'
        "        request, response, skip = _run_before_middleware(_request(), Response(), route)\n"
        "        assert skip is False            # the scaffold does not block the handler\n"
        "        assert response.status_code < 400\n"
        "\n"
        "    def test_after_runs_and_returns_the_pair(self):\n"
        '        route = {"middleware": [__NAME__]}\n'
        "        request, response = _run_after_middleware(_request(), Response(), route)\n"
        "        assert request is not None and response is not None\n"
    )
    content = content.replace("__NAME__", name).replace("__SNAKE__", snake)
    _write_test(snake, content)


def _emit_service_test(name: str, snake: str) -> None:
    """service → registrable / discoverable on a REAL ServiceRunner + loud stub."""
    content = (
        '"""Real ServiceRunner test for the __NAME__ service — no mocks.\n'
        "\n"
        "Generated with src/services/__SNAKE__.py by `tina4python generate service\n"
        "__NAME__`. Registers the scaffold on a REAL ServiceRunner and confirms the\n"
        "descriptor; the task body is an AI-FILL stub that raises until filled.\n"
        '"""\n'
        "import pytest\n"
        "\n"
        "from tina4_python.service import ServiceRunner\n"
        "from src.services.__SNAKE__ import __SNAKE___task, register, service\n"
        "\n"
        "\n"
        "class Test__CLASS__Service:\n"
        "    def test_registers_on_a_real_runner(self):\n"
        "        runner = ServiceRunner()\n"
        "        register(runner)\n"
        '        assert any(s["name"] == service["name"] for s in runner.list())\n'
        "\n"
        "    def test_descriptor_shape(self):\n"
        '        assert service["name"] and callable(service["handler"])\n'
        "\n"
        "    def test_task_is_a_live_stub(self):\n"
        '        """The scaffolded task raises until filled (fails loud, good DX)."""\n'
        "        with pytest.raises(NotImplementedError):\n"
        "            __SNAKE___task(None)\n"
    )
    content = (content.replace("__CLASS__", _pascal(snake))
               .replace("__NAME__", name).replace("__SNAKE__", snake))
    _write_test(snake, content)


def _emit_queue_test(topic: str, slug: str) -> None:
    """queue → push a REAL job onto the real file-backed Queue + daemon wiring."""
    content = (
        '"""Real file-backed Queue test for the __TOPIC__ worker — no mocks.\n'
        "\n"
        "Generated with src/services/__SLUG___consumer.py by `tina4python generate\n"
        "queue __TOPIC__`. Pushes a REAL job onto the real file-backed Queue and\n"
        "asserts it is enqueued, and that the consumer is wired as a daemon\n"
        "service. handle___SLUG__ is an AI-FILL stub that raises until you fill it\n"
        "— then assert the processed side effect here.\n"
        '"""\n'
        "import pytest\n"
        "\n"
        "from tina4_python.queue import Queue\n"
        "from src.services.__SLUG___consumer import (\n"
        "    publish___SLUG__, handle___SLUG__, consume___SLUG__, service,\n"
        ")\n"
        "\n"
        "\n"
        "class Test__CLASS__Queue:\n"
        "    def test_publish_enqueues_a_real_job(self):\n"
        '        before = Queue(topic="__TOPIC__").size()\n'
        '        job_id = publish___SLUG__({"hello": "world"})\n'
        "        assert job_id\n"
        '        assert Queue(topic="__TOPIC__").size() >= before + 1\n'
        "\n"
        "    def test_consumer_is_a_daemon_service(self):\n"
        '        assert service["daemon"] is True\n'
        '        assert service["handler"] is consume___SLUG__\n'
        "\n"
        "    def test_handle_is_a_live_stub(self):\n"
        '        """The scaffolded per-job handler raises until filled (fails loud)."""\n'
        "        with pytest.raises(NotImplementedError):\n"
        "            handle___SLUG__({})\n"
    )
    content = (content.replace("__CLASS__", _pascal(slug))
               .replace("__TOPIC__", topic).replace("__SLUG__", slug))
    _write_test(slug, content)


def _emit_validator_test(name: str, snake: str) -> None:
    """validator → run the scaffold against valid + invalid real input."""
    content = (
        '"""Real validation test for validate___SNAKE__ — no mocks.\n'
        "\n"
        "Generated with src/validators/__SNAKE__.py by `tina4python generate\n"
        "validator __NAME__`. The scaffold ships a starter rule (required \"name\"),\n"
        "so this passes on generation — adjust the rules for your payload and\n"
        "update these cases with them.\n"
        '"""\n'
        "from src.validators.__SNAKE__ import validate___SNAKE__\n"
        "\n"
        "\n"
        "class Test__CLASS__Validator:\n"
        "    def test_valid_input_passes(self):\n"
        '        assert validate___SNAKE__({"name": "Ada"}).is_valid()\n'
        "\n"
        "    def test_invalid_input_fails(self):\n"
        "        result = validate___SNAKE__({})\n"
        "        assert not result.is_valid()\n"
        "        assert result.errors()\n"
    )
    content = (content.replace("__CLASS__", _pascal(snake))
               .replace("__NAME__", name).replace("__SNAKE__", snake))
    _write_test(snake, content)


def _emit_seeder_test(model: str, table: str) -> None:
    """seeder → run the scaffold against real SQLite, assert rows created."""
    content = (
        '"""Real seeding test for the __MODEL__ seeder — no mocks, real SQLite.\n'
        "\n"
        "Generated with src/seeds/__TABLE___seeder.py by `tina4python generate\n"
        "seeder __MODEL__`. Binds a real SQLite DB, creates the table, runs the\n"
        "scaffolded seeder (auto-fills every field via FakeData) and asserts rows\n"
        "were created.\n"
        '"""\n'
        "from tina4_python.database import Database\n"
        "from tina4_python.orm.model import bind_database\n"
        "from tina4_python.seeder import FakeData\n"
        "from src.orm.__MODEL__ import __MODEL__\n"
        "from src.seeds.__TABLE___seeder import field_overrides, run\n"
        "\n"
        "\n"
        "class Test__MODEL__Seeder:\n"
        "    def setup_method(self, _method):\n"
        '        bind_database(Database("sqlite:///test___TABLE___seeder.db"))\n'
        "        __MODEL__.create_table()\n"
        "\n"
        "    def test_field_overrides_is_a_dict(self):\n"
        "        assert isinstance(field_overrides(FakeData()), dict)\n"
        "\n"
        "    def test_run_creates_rows(self):\n"
        "        run(None)\n"
        "        assert len(__MODEL__.all(limit=1000)) >= 1\n"
    )
    content = content.replace("__MODEL__", model).replace("__TABLE__", table)
    _write_test(f"{table}_seeder", content)


def _emit_websocket_test(ws_path: str, base: str, handler: str) -> None:
    """websocket → real Router registration + drive the real async handler
    (the socket-free "close" event) directly (no mock socket)."""
    content = (
        '"""Real handler test for the __WSPATH__ WebSocket route — no mocks.\n'
        "\n"
        "Generated with src/routes/ws___BASE__.py by `tina4python generate\n"
        "websocket ...`. Confirms the handler registers on the REAL Router and\n"
        'drives the real async handler for the "close" event (no socket needed).\n'
        'The "message" branch is an AI-FILL stub that raises until you fill it; a\n'
        "full RFC6455 loopback is out of scope for a unit test, so assert its\n"
        "broadcast/response against a live server once implemented.\n"
        '"""\n'
        "import asyncio\n"
        "\n"
        "import pytest\n"
        "\n"
        "from tina4_python.core.router import Router\n"
        "from src.routes.ws___BASE__ import __HANDLER__\n"
        "\n"
        "\n"
        "class Test__CLASS__WebSocket:\n"
        "    def test_handler_registered_on_router(self):\n"
        '        assert any(r["path"] == "__WSPATH__" for r in Router.get_web_socket_routes())\n'
        "\n"
        "    def test_close_event_is_handled(self):\n"
        '        """The "close" branch returns cleanly without a connection."""\n'
        '        assert asyncio.run(__HANDLER__(None, "close", None)) is None\n'
        "\n"
        "    def test_message_branch_is_a_live_stub(self):\n"
        "        with pytest.raises(NotImplementedError):\n"
        '            asyncio.run(__HANDLER__(None, "message", "hi"))\n'
    )
    content = (content.replace("__CLASS__", _pascal(base))
               .replace("__WSPATH__", ws_path)
               .replace("__HANDLER__", handler)
               .replace("__BASE__", base))
    _write_test(f"ws_{base}", content)


def _emit_listener_test(event: str, slug: str) -> None:
    """listener → emit the REAL event on the real bus, assert the listener ran."""
    content = (
        "\"\"\"Real event-bus test for the '__EVENT__' listener — no mocks.\n"
        "\n"
        "Generated with src/listeners/__SLUG__.py by `tina4python generate listener\n"
        "__EVENT__`. Confirms the listener binds on the REAL event bus and that\n"
        "emitting the event reaches it. The reaction body is an AI-FILL stub that\n"
        "raises until filled, so a strict emit re-raises here (proving it ran).\n"
        "\"\"\"\n"
        "import pytest\n"
        "\n"
        "from tina4_python.core.events import emit, events, listeners\n"
        "import src.listeners.__SLUG__  # noqa: F401 — importing binds the listener\n"
        "\n"
        "\n"
        "class Test__CLASS__Listener:\n"
        "    def test_listener_is_registered(self):\n"
        '        assert "__EVENT__" in events()\n'
        '        assert len(listeners("__EVENT__")) >= 1\n'
        "\n"
        "    def test_emit_reaches_the_listener(self):\n"
        '        """strict=True re-raises the stub error, proving the listener ran."""\n'
        "        with pytest.raises(NotImplementedError):\n"
        '            emit("__EVENT__", {"id": 1}, strict=True)\n'
    )
    content = (content.replace("__CLASS__", _pascal(slug))
               .replace("__EVENT__", event).replace("__SLUG__", slug))
    _write_test(slug, content)


def _emit_auth_test() -> None:
    """auth → real register / login / me end-to-end via the real TestClient."""
    content = (
        '"""Real auth test — register / login / me via the real TestClient.\n'
        "\n"
        "Generated with the auth scaffold by `tina4python generate auth`. No mocks:\n"
        "real Router, real Auth (PBKDF2 + JWT), real SQLite. register + login are\n"
        "public (@noauth); the token from login authenticates /api/auth/me.\n"
        '"""\n'
        "import os\n"
        "\n"
        'os.environ.setdefault("TINA4_SECRET", "test-secret")\n'
        'os.environ.pop("TINA4_API_KEY", None)\n'
        "\n"
        "from tina4_python.database import Database\n"
        "from tina4_python.orm.model import bind_database\n"
        "from tina4_python.test_client import TestClient\n"
        "from src.orm.User import User\n"
        "import src.routes.auth  # noqa: F401 — importing registers the auth routes\n"
        "\n"
        "\n"
        "class TestAuth:\n"
        '    """register → login → me, end to end against real SQLite."""\n'
        "\n"
        "    def setup_method(self, _method):\n"
        '        bind_database(Database("sqlite:///test_auth.db"))\n'
        "        User.create_table()\n"
        "        for existing in User.all(limit=1000):   # start from an empty table\n"
        "            existing.delete()\n"
        "\n"
        "    def test_register_then_login_then_me(self):\n"
        "        client = TestClient()\n"
        '        registered = client.post("/api/auth/register",\n'
        '                                 json={"email": "a@b.c", "password": "secret12"})\n'
        "        assert registered.status == 201\n"
        "\n"
        '        duplicate = client.post("/api/auth/register",\n'
        '                                json={"email": "a@b.c", "password": "secret12"})\n'
        "        assert duplicate.status == 409\n"
        "\n"
        '        login = client.post("/api/auth/login",\n'
        '                            json={"email": "a@b.c", "password": "secret12"})\n'
        "        assert login.status == 200\n"
        '        token = login.json()["token"]\n'
        "        assert token\n"
        "\n"
        '        profile = client.get("/api/auth/me",\n'
        '                             headers={"Authorization": f"Bearer {token}"})\n'
        "        assert profile.status == 200\n"
        '        assert profile.json()["email"] == "a@b.c"\n'
        "\n"
        "    def test_login_wrong_password_is_401(self):\n"
        "        client = TestClient()\n"
        '        client.post("/api/auth/register",\n'
        '                    json={"email": "x@y.z", "password": "secret12"})\n'
        '        bad = client.post("/api/auth/login",\n'
        '                          json={"email": "x@y.z", "password": "WRONG"})\n'
        "        assert bad.status == 401\n"
        "\n"
        "    def test_me_without_token_is_401(self):\n"
        '        assert TestClient().get("/api/auth/me").status == 401\n'
    )
    _write_test("auth", content)


def _emit_migration_test(migration_name: str, table: str,
                         up_file: str, down_file: str) -> None:
    """migration (create_*) → apply UP then DOWN against real SQLite, assert
    the table appears then disappears. Only for CREATE migrations — a
    placeholder ALTER migration has no real SQL to assert yet."""
    content = (
        '"""Real migration test for __UP_FILE__ — no mocks, real SQLite.\n'
        "\n"
        "Generated with the migration by `tina4python generate migration\n"
        "__MIG_NAME__`. Applies the UP migration against a fresh real SQLite\n"
        "database and asserts the table exists, then applies DOWN and asserts it\n"
        "is gone — the raw SQL the migration runner executes.\n"
        '"""\n'
        "import sqlite3\n"
        "from pathlib import Path\n"
        "\n"
        'MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"\n'
        "\n"
        "\n"
        "def _table_exists(cursor, table):\n"
        "    cursor.execute(\n"
        "        \"SELECT name FROM sqlite_master WHERE type='table' AND name=?\", (table,))\n"
        "    return cursor.fetchone() is not None\n"
        "\n"
        "\n"
        "class Test__CLASS__Migration:\n"
        "    def test_up_creates_and_down_drops(self):\n"
        '        connection = sqlite3.connect(":memory:")\n'
        "        cursor = connection.cursor()\n"
        "\n"
        '        cursor.executescript((MIGRATIONS / "__UP_FILE__").read_text())\n'
        '        assert _table_exists(cursor, "__TABLE__")\n'
        "\n"
        '        cursor.executescript((MIGRATIONS / "__DOWN_FILE__").read_text())\n'
        '        assert not _table_exists(cursor, "__TABLE__")\n'
        "\n"
        "        connection.close()\n"
    )
    content = (content.replace("__CLASS__", _pascal(table))
               .replace("__MIG_NAME__", migration_name)
               .replace("__UP_FILE__", up_file)
               .replace("__DOWN_FILE__", down_file)
               .replace("__TABLE__", table))
    _write_test(f"{table}_migration", content)


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
        "    # tina4:edit  main service loop here\n"
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

    # Co-emit a real ServiceRunner registration/discovery test.
    _emit_service_test(name, snake)


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
        "    # tina4:edit  handle the job payload here\n"
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
        "# consume___SLUG__ manages its own loop. The `topic` + per-job `handle`\n"
        '# keys let `tina4python queue work __TOPIC__` drive this consumer directly\n'
        "# (own the poll loop / bounded --once drain) without wiring a ServiceRunner.\n"
        "service = {\n"
        '    "name": "__TOPIC__-consumer",\n'
        '    "topic": "__TOPIC__",\n'
        "    \"handler\": consume___SLUG__,\n"
        "    \"handle\": handle___SLUG__,\n"
        '    "daemon": True,\n'
        "}\n"
    )
    content = (
        template.replace("__BODY__", body)
        .replace("__TOPIC__", topic)
        .replace("__SLUG__", slug)
    )
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ Created {path}")

    # Co-emit a real file-backed Queue test (push a real job + daemon wiring).
    _emit_queue_test(topic, slug)


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

    # Ships a working starter rule (not a loud stub): a rules-less validator
    # validates nothing, so there would be no negative case to co-emit a real
    # valid/invalid test against. `required("name")` mirrors the model
    # generator's default `name` field — edit it for your real payload.
    body = (
        _extend(
            f"add / adjust the rules for your {name} payload",
            'e.g. validator.email("email").min_length("name", 2).integer("age") · '
            'ground: tina4_context("validate request body with Validator", "python")',
        )
        + '    validator.required("name")\n'
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
        "    # tina4:edit  add validation rules here\n"
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

    # Co-emit a real valid + invalid test against the starter rule.
    _emit_validator_test(name, snake)


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

    # Ships working out of the box (not a loud stub): seed_orm auto-fills every
    # field by type/name, so a zero-override seeder already seeds real rows.
    # Return overrides only for fields that need a specific shape.
    body = (
        _extend(
            f"override {name} fields that need a specific shape (optional)",
            'e.g. return {"email": lambda fake: fake.email(), "status": "active"} · '
            'ground: tina4_context("seed ORM model with FakeData", "python")',
        )
        + "    return {}\n"
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
        "    # tina4:edit  add seed data here\n"
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

    # Co-emit a real seeding test (runs the seeder against real SQLite).
    _emit_seeder_test(name, table)


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
        "    # tina4:edit  handle inbound messages here\n"
        "__BODY__"
    )
    content = (
        template.replace("__BODY__", body)
        .replace("__WSPATH__", ws_path)
        .replace("__HANDLER__", handler)
    )
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ Created {path}")

    # Co-emit a real handler test (Router registration + drives the handler).
    _emit_websocket_test(ws_path, base, handler)


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
        "    # tina4:edit  react to the event here\n"
        "__BODY__"
    )
    content = (
        template.replace("__BODY__", body)
        .replace("__EVENT__", event)
        .replace("__SLUG__", slug)
    )
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ Created {path}")

    # Co-emit a real event-bus test (emit the real event, assert it ran).
    _emit_listener_test(event, slug)


# ── Utilities ─────────────────────────────────────────────────────────

def _gen_form(name: str, flags: dict = None):
    """Generate a form template matching a model's fields.

    tina4python generate form Product
    tina4python generate form Product --fields "name:string,price:float"
    """
    flags = flags or {}
    fields = _fields_or_default(flags.get("fields", ""))
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
    for fname, ftype in fields:
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
        '        {# tina4:edit  customise the form fields here #}\n'
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
    fields = _fields_or_default(flags.get("fields", ""))
    table = _to_table(name)
    route_name = table + "s"

    target = Path("src/templates/pages")
    target.mkdir(parents=True, exist_ok=True)

    cols = [f for f, _ in fields]

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
            '    {# tina4:edit  customise the list columns or add filters here #}\n'
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
            '    {# tina4:edit  arrange the detail fields here #}\n'
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

    # 1. User model + migration (emit_test=False — auth emits its own broader
    #    register/login/me test at step 5).
    _gen_model("User", {"fields": "email:string,password:string,role:string"},
               emit_test=False)

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
            '        # tina4:edit  add roles/permissions here\n'
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
            '    auth_header = request.headers.get("authorization", "")\n'
            '    token = auth_header[7:] if auth_header.startswith("Bearer ") else ""\n'
            '    payload = Auth.valid_token_static(token) if token else None\n'
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

    # 5. Auth test — real register/login/me end-to-end (real Router, real Auth
    #    JWT + PBKDF2, real SQLite). Replaces the old placeholder stub test.
    _emit_auth_test()

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


# ── Queue worker + management ─────────────────────────────────────────
#
# The top-level `queue` command wires straight to the real
# tina4_python.queue.Queue (file backend by default; RabbitMQ/Kafka/MongoDB via
# TINA4_QUEUE_BACKEND). `stats`, `retry` and `clear` operate on the queue
# without booting the app or a database; `work` runs the app's consumer for a
# topic. Distinct from `generate queue`, which SCAFFOLDS a consumer file.

def _resolve_queue_handler(services_dir: str, topic: str):
    """Return the per-job handler that a consumer module declares for ``topic``.

    A consumer module (e.g. the one `generate queue <topic>` scaffolds) exposes
    a module-level ``service`` dict; when its ``topic`` matches, ``queue work``
    drives the consumer through that dict's per-job ``handle`` callable — so the
    worker owns the poll loop (honouring ``--poll`` and the bounded ``--once``
    drain) instead of the consumer's own endless loop. Returns the callable, or
    ``None`` when no consumer in ``services_dir`` targets this topic.
    """
    import importlib.util

    svc_path = Path(services_dir)
    if not svc_path.is_dir():
        return None
    for py_file in sorted(svc_path.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"tina4_qwork_{py_file.stem}", str(py_file)
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception:  # noqa: BLE001 — a broken sibling must not sink the worker
            continue
        config = getattr(mod, "service", None)
        if isinstance(config, dict) and config.get("topic") == topic \
                and callable(config.get("handle")):
            return config["handle"]
    return None


def _queue_work(args):
    """Run a consumer loop that pops and processes jobs on a topic.

        tina4python queue work [topic] [--once] [--poll N] [--services DIR]

    Long-running by default (polls every ``--poll`` seconds, 1.0 default; Ctrl-C
    to stop). ``--once`` does a single-pass drain — it processes every currently
    available job then exits (poll interval 0). The per-job handler is resolved
    from the app's consumer for this topic (see _resolve_queue_handler); with no
    handler it drains and acks with a warning rather than inventing behaviour.
    """
    _load_env()
    flags, positional = _parse_flags(args)
    topic = positional[0] if positional else "default"
    once = bool(flags.get("once"))

    poll_raw = str(flags.get("poll", "")).strip()
    try:
        poll = float(poll_raw) if poll_raw and poll_raw != "True" else (1.0 if not once else 0.0)
    except ValueError:
        poll = 1.0
    if once:
        poll = 0.0  # single-pass: consume() returns as soon as the topic is empty

    services_dir = flags.get("services") or os.environ.get("TINA4_SERVICE_DIR", "src/services")
    if services_dir is True:
        services_dir = "src/services"

    handler = _resolve_queue_handler(services_dir, topic)
    from tina4_python.queue import Queue
    queue = Queue(topic=topic)

    if handler is None:
        print(f"  ⚠ No consumer handler found for topic '{topic}' in {services_dir}.")
        print(f"    Scaffold one with: tina4python generate queue {topic}")
        print("    Draining (consume + ack) without processing.")

    mode = "single-pass drain" if once else f"polling every {poll:g}s (Ctrl-C to stop)"
    print(f"  Queue worker on '{topic}' — {mode}...")

    processed = 0
    failed = 0
    try:
        for job in queue.consume(topic, poll_interval=poll):
            try:
                if handler is not None:
                    handler(job.data)
                job.complete()
                processed += 1
            except Exception as exc:  # noqa: BLE001 — a bad job nacks, worker lives
                job.fail(str(exc))
                failed += 1
    except KeyboardInterrupt:
        print("\n  Interrupted — stopping worker.")

    print(f"  Processed {processed} job(s), {failed} failed on '{topic}'.")


def _queue_stats(args):
    """Print pending / in-flight / failed / dead-letter / completed counts.

        tina4python queue stats [topic] [--json]
    """
    import json as _json

    _load_env()
    flags, positional = _parse_flags(args)
    topic = positional[0] if positional else "default"

    from tina4_python.queue import Queue
    queue = Queue(topic=topic)
    stats = {
        "topic": topic,
        "pending": queue.size("pending"),      # waiting to run
        "reserved": queue.size("reserved"),     # popped, not yet acked (in-flight)
        "failed": len(queue.failed()),          # failed once, still retrying
        "dead": queue.size("dead"),             # exhausted retries (dead-letter)
        "completed": queue.size("completed"),   # terminal-completed (0 on the file backend)
    }

    if "json" in flags:
        print(_json.dumps(stats, indent=2))
        return

    print(f"\n  Queue '{topic}'")
    print(f"    pending    {stats['pending']}")
    print(f"    reserved   {stats['reserved']}    (in-flight)")
    print(f"    failed     {stats['failed']}    (retrying)")
    print(f"    dead       {stats['dead']}    (dead-letter)")
    print(f"    completed  {stats['completed']}")
    print()


def _queue_retry(args):
    """Re-queue failed and dead-letter jobs so they run again.

        tina4python queue retry [topic]

    Revives every dead-letter job (manual override, regardless of attempt count)
    and re-queues any failed-but-still-eligible jobs.
    """
    _load_env()
    flags, positional = _parse_flags(args)
    topic = positional[0] if positional else "default"

    from tina4_python.queue import Queue
    queue = Queue(topic=topic)

    # max_retries=0 => every job in the dead-letter store, whatever its attempt
    # count (matches what `stats`/`size("dead")` reports), not only attempts>=N.
    dead = queue.dead_letters(max_retries=0)
    revived = sum(1 for job in dead if queue.retry(job.id))
    # Any failed-but-retryable jobs still under the limit (no-op on the file
    # backend once the above moved them out, meaningful for other backends).
    requeued = queue.retry_failed()

    total = revived + requeued
    print(f"  Re-queued {total} job(s) on '{topic}' "
          f"({revived} dead-letter, {requeued} failed).")


def _queue_clear(args):
    """Purge jobs of a given status (default: completed).

        tina4python queue clear [status] [topic]

    status is one of pending / reserved / completed / failed / dead. The default
    'completed' clears finished jobs; pass e.g. `queue clear pending` or
    `queue clear dead orders` to purge another status / topic.
    """
    _load_env()
    flags, positional = _parse_flags(args)
    status = positional[0] if positional else "completed"
    topic = positional[1] if len(positional) > 1 else "default"

    from tina4_python.queue import Queue
    queue = Queue(topic=topic)
    removed = queue.purge(status)
    print(f"  Cleared {removed} '{status}' job(s) from '{topic}'.")


# Sub-dispatch table for the `queue` command — the single source for its
# subcommands (drives _queue dispatch AND the manifest's queue.subcommands).
_QUEUE_SUBCOMMANDS = {
    "work":  _queue_work,
    "stats": _queue_stats,
    "retry": _queue_retry,
    "clear": _queue_clear,
}


def _queue(args):
    """Top-level queue command: run workers and manage jobs.

        tina4python queue work  [topic] [--once] [--poll N] [--services DIR]
        tina4python queue stats [topic] [--json]
        tina4python queue retry [topic]
        tina4python queue clear [status] [topic]
    """
    args = args or []
    if not args:
        print("Usage: tina4python queue <work|stats|retry|clear> [options]")
        print(f"  Subcommands: {', '.join(_QUEUE_SUBCOMMANDS)}")
        sys.exit(1)
    sub = args[0].lower()
    handler = _QUEUE_SUBCOMMANDS.get(sub)
    if handler is None:
        print(f"Unknown queue subcommand: {sub}")
        print(f"  Available: {', '.join(_QUEUE_SUBCOMMANDS)}")
        sys.exit(1)
    handler(args[1:])


# ── Self-describing command surface ───────────────────────────────────

def _commands_manifest() -> dict:
    """Build the machine-readable manifest of the CLI's command surface.

    Pure data: reads the module-level COMMANDS and DELEGATED registries and the
    framework version — no bootstrap, no database, no migrations, no app imports.
    This is exactly what `commands --json` serializes and what the tina4 Rust
    client consumes to discover which commands this framework supports.

    Commands the framework hands to the `tina4` client carry `"delegated": true`,
    so the manifest describes the WHOLE surface the CLI accepts while still
    saying who implements each one. The client needs no change for this: its help
    renderer already drops manifest names that clash with its own natives.

    Shape::

        {"framework": "python", "version": "<x.y.z>",
         "commands": [{"name", "summary", "args"?, "subcommands"?, "delegated"?}, ...]}
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
    for command_name, spec in DELEGATED.items():
        entry = {"name": command_name, "summary": spec["summary"], "delegated": True}
        if spec.get("args"):
            entry["args"] = list(spec["args"])
        commands.append(entry)
    return {
        "framework": "python",
        "version": __version__,
        "commands": commands,
        # ADR-0062 / ADR-0063: agents discover the generate resolution envelope
        # shape programmatically. A version bump here is a break; adding an
        # optional envelope key is not. 1.1 (envelope generate_v1_1) added
        # `edit_hints[]` and `next[]` on the resolution — every v1 key
        # preserved, so a v1 consumer keeps working unchanged.
        "resolution_contract": {
            "version": _RESOLUTION_ENVELOPE_VERSION,
            "envelope": _RESOLUTION_ENVELOPE_NAME,
        },
    }


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
        marker = f" ({CLIENT_BINARY} client)" if command.get("delegated") else ""
        print(f"  {command['name']:<{width}}  {command['summary']}{marker}")
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
    "queue":            {"handler": _queue,            "usage": "<work|stats|retry|clear> [topic]", "subcommands": list(_QUEUE_SUBCOMMANDS), "summary": "Run queue workers and manage jobs"},
    "build":            {"handler": _build,            "usage": "[--tag NAME] [--file PATH]", "summary": "Build the deployable Docker image"},
    "lint":             {"handler": _lint,             "usage": "[--fix] [--no-install]", "summary": "Lint src/ + app.py (installs ruff dev-only on demand; zero-dep syntax baseline with --no-install)"},
    "ai":               {"handler": _ai,               "usage": "[--all]", "summary": "Install AI coding assistant context"},
    "generate":         {"handler": _generate,         "usage": "<what> <name> [options]", "subcommands": list(GENERATORS), "summary": "Generate scaffolding (see Generators below)"},
    "console":          {"handler": _console,          "summary": "Start interactive REPL with framework loaded"},
    "commands":         {"handler": _commands,         "usage": "[--json]", "summary": "List available commands (add --json for machine form)"},
    "help":             {"handler": _help,             "summary": "Show this help"},
}

# Commands the `tina4` client OWNS and this CLI reaches by delegation — see the
# "Delegation to the `tina4` client" section above for why these are not ported.
# There are no handlers here: `main()` runs `tina4 <name> <args...>` and exits
# with its code. Keep this set closed and identical in all four frameworks — it
# must contain ONLY commands the client dispatches natively, or delegation could
# bounce back and loop. Summaries are the client's own wording, verbatim.
DELEGATED = {
    "doctor": {"summary": "Check installed languages and tools"},
    "setup":  {"summary": "Guided, menu-driven setup: install everything + scaffold a ready-to-run project"},
    "deploy": {"usage": "<docker|systemd|nginx|cpanel> [--force]", "args": ["target"],
               "summary": "Generate deployment scaffolding (Dockerfile, systemd unit, nginx block, cPanel)"},
}


__all__ = ["main"]
