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
    flags = {}
    positional = []
    i = 0
    while i < len(args):
        if args[i].startswith("--"):
            key = args[i][2:]
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                flags[key] = args[i + 1]
                i += 2
            else:
                flags[key] = True
                i += 1
        else:
            positional.append(args[i])
            i += 1
    return flags, positional


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

    commands = {
        "init": _init,
        "serve": _serve,
        "start": _serve,
        "migrate": _migrate,
        "migrate:create": _migrate_create,
        "migrate:rollback": _migrate_rollback,
        "migrate:status": _migrate_status,
        "seed": _seed,
        "routes": _routes,
        "test": _test,
        "build": _build,
        "ai": _ai,
        "generate": _generate,
        "help": _help,
    }

    handler = commands.get(command)
    if handler:
        handler(cmd_args)
    else:
        print(f"Unknown command: {command}")
        _help([])


def _help(args=None):
    print("""
Tina4 Python — CLI

Usage: tina4python <command> [options]

Commands:
  init [dir]                    Scaffold a new project
  serve [--port P] [--no-browser]  Start dev server (default: 0.0.0.0:7146)
  migrate                      Run pending database migrations
  migrate:create <desc>         Create a new migration file
  migrate:rollback              Rollback last migration batch
  migrate:status                Show migration status
  seed                          Run database seeders
  routes                        List all registered routes
  test                          Run test suite
  build                         Build distributable package
  ai [--all]                    Install AI coding assistant context

Generators:
  generate model <Name> [--fields "name:string,price:float"]
  generate route <name> [--model Name]
  generate crud <Name> [--fields "..."]   Model + migration + routes + form + view + test
  generate migration <description>
  generate middleware <Name>
  generate test <name>
  generate form <Name> [--fields "..."]   Form template with inputs matching model fields
  generate view <Name> [--fields "..."]   List + detail templates for viewing records
  generate auth                           Login/register/logout routes + User model + templates

Field types: string, int, float, bool, text, datetime, blob
Table names: singular by default (Product → product)

https://tina4.com
""")


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

    # Create .env
    env_file = target / ".env"
    if not env_file.exists():
        env_file.write_text(
            "# Tina4 Configuration\n"
            "TINA4_DEBUG=true\n"
            "TINA4_LOG_LEVEL=ALL\n"
            "DATABASE_URL=sqlite:///data/app.db\n"
            'SECRET=change-me-in-production\n',
            encoding="utf-8",
        )

    # Create .gitignore
    gitignore = target / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(
            ".env\n__pycache__/\n*.pyc\n.venv/\ndata/\nlogs/\n"
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
    from tina4_python.ai import install_all
    if "--ai" in args:
        created = install_all(str(target))
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

    # Kill existing process on port
    port = cli_port or int(os.environ.get("PORT", os.environ.get("TINA4_PORT", "7146")))
    _kill_process_on_port(port)

    from tina4_python.core import run
    run(host=cli_host, port=cli_port, no_browser=no_browser)


# ── Migrate ───────────────────────────────────────────────────────────

def _migrate(args):
    """Run pending migrations."""
    _load_env()
    from tina4_python.database import Database
    from tina4_python.migration import migrate

    db_url = os.environ.get("DATABASE_URL", "sqlite:///data/app.db")
    db = Database(db_url)
    mig_dir = args[0] if args else "migrations"
    ran = migrate(db, mig_dir)
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
    from tina4_python.migration import rollback

    db_url = os.environ.get("DATABASE_URL", "sqlite:///data/app.db")
    db = Database(db_url)
    mig_dir = args[0] if args else "migrations"
    rolled = rollback(db, mig_dir)
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
    from tina4_python.migration import status

    db_url = os.environ.get("DATABASE_URL", "sqlite:///data/app.db")
    db = Database(db_url)
    result = status(db, args[0] if args else "migrations")
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

    db_url = os.environ.get("DATABASE_URL", "sqlite:///data/app.db")
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
    from tina4_python.ai import show_menu, install_selected, install_all

    if args and args[0].lower() == "all":
        install_all(".")
    else:
        selection = show_menu(".")
        if selection:
            install_selected(".", selection)


# ── Generate (rich scaffolding) ───────────────────────────────────────

def _generate(args):
    """Generate scaffolding: model, route, crud, migration, middleware, test, form, view, auth."""
    if not args:
        print("Usage: tina4python generate <what> <name> [options]")
        print("  Generators: model, route, crud, migration, middleware, test, form, view, auth")
        print('  Options:    --fields "name:string,price:float"  --model ModelName')
        sys.exit(1)

    what = args[0].lower()

    # Auth doesn't require a name argument
    no_name_generators = {"auth"}
    if what not in no_name_generators and len(args) < 2:
        print(f"Usage: tina4python generate {what} <name> [options]")
        sys.exit(1)

    name = args[1] if len(args) > 1 else ""
    flags, _ = _parse_flags(args[2:] if len(args) > 2 else [])

    generators = {
        "model": _gen_model,
        "route": _gen_route,
        "crud": _gen_crud,
        "migration": _gen_migration,
        "middleware": _gen_middleware,
        "test": _gen_test,
        "form": _gen_form,
        "view": _gen_view,
        "auth": _gen_auth,
    }

    gen = generators.get(what)
    if gen:
        gen(name, flags)
    else:
        print(f"Unknown generator: {what}")
        print("  Available: model, route, crud, migration, middleware, test, form, view, auth")
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
    """Generate CRUD route file.

    tina4python generate route products
    tina4python generate route products --model Product
    """
    route_path = name.lstrip("/")
    singular = route_path.rstrip("s") if route_path.endswith("s") else route_path
    model = flags.get("model", "")

    target = Path("src/routes")
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{route_path}.py"
    if path.exists():
        print(f"  ✗ File already exists: {path}")
        return

    # Import line
    imports = "from tina4_python.core.router import get, post, put, delete, noauth\n"
    imports += "from tina4_python.swagger import description, tags\n"
    if model:
        imports += f"from src.orm.{model} import {model}\n"

    # Route handlers
    if model:
        content = f'''{imports}

@noauth()
@description("List all {route_path}")
@tags(["{route_path}"])
@get("/api/{route_path}")
async def list_{route_path}(request, response):
    """List all {route_path} with pagination."""
    page = int(request.params.get("page", 1))
    per_page = int(request.params.get("per_page", 20))
    offset = (page - 1) * per_page
    results = {model}().select(limit=per_page, skip=offset)
    return response(results.to_paginate(page=page, per_page=per_page))


@noauth()
@description("Get a {singular} by ID")
@tags(["{route_path}"])
@get("/api/{route_path}/{{id:int}}")
async def get_{singular}(request, response):
    """Get a single {singular} by ID."""
    {singular} = {model}.find_by_id(request.params["id"])
    if {singular} is None:
        return response({{"error": "Not found"}}, 404)
    return response({singular}.to_dict())


@noauth()
@description("Create a new {singular}")
@tags(["{route_path}"])
@post("/api/{route_path}")
async def create_{singular}(request, response):
    """Create a new {singular}."""
    item = {model}.create(request.body)
    return response(item.to_dict(), 201)


@description("Update a {singular}")
@tags(["{route_path}"])
@put("/api/{route_path}/{{id:int}}")
async def update_{singular}(request, response):
    """Update a {singular} by ID."""
    item = {model}.find_by_id(request.params["id"])
    if item is None:
        return response({{"error": "Not found"}}, 404)
    for key, value in request.body.items():
        if hasattr(item, key) and key != "id":
            setattr(item, key, value)
    item.save()
    return response(item.to_dict())


@description("Delete a {singular}")
@tags(["{route_path}"])
@delete("/api/{route_path}/{{id:int}}")
async def delete_{singular}(request, response):
    """Delete a {singular} by ID."""
    item = {model}.find_by_id(request.params["id"])
    if item is None:
        return response({{"error": "Not found"}}, 404)
    item.delete()
    return response(None, 204)
'''
    else:
        content = f'''{imports}

@noauth()
@description("List all {route_path}")
@tags(["{route_path}"])
@get("/api/{route_path}")
async def list_{route_path}(request, response):
    """List all {route_path}."""
    return response({{"data": []}})


@noauth()
@description("Get a {singular} by ID")
@tags(["{route_path}"])
@get("/api/{route_path}/{{id:int}}")
async def get_{singular}(request, response):
    """Get a single {singular}."""
    return response({{"data": {{}}}})


@noauth()
@description("Create a new {singular}")
@tags(["{route_path}"])
@post("/api/{route_path}")
async def create_{singular}(request, response):
    """Create a new {singular}."""
    return response({{"data": request.body}}, 201)


@description("Update a {singular}")
@tags(["{route_path}"])
@put("/api/{route_path}/{{id:int}}")
async def update_{singular}(request, response):
    """Update a {singular}."""
    return response({{"data": request.body}})


@description("Delete a {singular}")
@tags(["{route_path}"])
@delete("/api/{route_path}/{{id:int}}")
async def delete_{singular}(request, response):
    """Delete a {singular}."""
    return response(None, 204)
'''

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

    # 2. Routes with model
    route_flags = {"model": name}
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

    # 6. Test
    _gen_test(route_name, {"model": name})

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


__all__ = ["main"]
