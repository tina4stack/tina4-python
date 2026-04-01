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
    tina4python ai                # Detect AI tools and install context
"""
import os
import sys
from pathlib import Path


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
  init [dir]            Scaffold a new project
  serve [--host H] [--port P]  Start dev server (default: 0.0.0.0:7145)
  migrate               Run pending database migrations
  migrate:create <desc> Create a new migration file
  migrate:rollback      Rollback last migration batch
  migrate:status        Show completed and pending migrations
  seed                  Run database seeders
  routes                List all registered routes
  test                  Run test suite
  build                 Build distributable package
  generate <what> <name> Generate scaffolding (model, route, migration, middleware)
  ai [--all]            Detect AI tools and install framework context
  help                  Show this help message

https://tina4.com
""")


def _init(args):
    """Scaffold a new Tina4 project."""
    target = Path(args[0]) if args else Path(".")
    target.mkdir(parents=True, exist_ok=True)

    # Create project structure
    folders = [
        "src/routes", "src/orm", "src/templates", "src/templates/errors",
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

    # Create app.py if it doesn't exist
    app_file = target / "app.py"
    if not app_file.exists():
        app_file.write_text(
            '"""Tina4 Application."""\n'
            'from tina4_python.core import run\n\n'
            'if __name__ == "__main__":\n'
            '    run()\n',
            encoding="utf-8",
        )

    # Create .env if it doesn't exist
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

    # Create root Dockerfile (uv variant) if it doesn't exist
    root_dockerfile = target / "Dockerfile"
    if not root_dockerfile.exists():
        root_dockerfile.write_text(
            'FROM python:3.13-slim AS build\n'
            'WORKDIR /app\n'
            'COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv\n'
            'COPY pyproject.toml uv.lock* ./\n'
            'RUN uv sync --frozen --no-dev\n'
            'COPY . .\n'
            '\n'
            'FROM python:3.13-slim\n'
            'WORKDIR /app\n'
            'COPY --from=build /app .\n'
            'COPY --from=build /usr/local/bin/uv /usr/local/bin/uv\n'
            'ENV PATH="/app/.venv/bin:$PATH"\n'
            'ENV HOST=0.0.0.0\n'
            'ENV PORT=7145\n'
            'EXPOSE 7145\n'
            'CMD ["python", "app.py"]\n',
            encoding="utf-8",
        )

    # Create root .dockerignore if it doesn't exist
    root_dockerignore = target / ".dockerignore"
    if not root_dockerignore.exists():
        root_dockerignore.write_text(
            ".venv\n__pycache__\n.git\n.claude\n.env\n*.log\ntests\ntmp\n",
            encoding="utf-8",
        )

    # Auto-detect AI tools and install context
    from tina4_python.ai import detect_ai_names, install_context, install_all
    detected = detect_ai_names(str(target))
    if detected:
        created = install_context(str(target))
        if created:
            print(f"\nAI context installed for: {', '.join(detected)}")
            for f in created:
                print(f"  + {f}")
    elif "--ai" in args:
        created = install_all(str(target))
        if created:
            print("\nAI context installed for all supported tools:")
            for f in created:
                print(f"  + {f}")

    print(f"\nProject scaffolded at {target.resolve()}")
    print("  Run: tina4python serve")
    print("  Run: tina4python ai        (detect & install AI tool context)")


def _serve(args):
    """Start the development server.

    Supports:
        tina4python serve                     # defaults
        tina4python serve 8080                # positional port
        tina4python serve --port 8080         # flag port
        tina4python serve --host 127.0.0.1    # flag host
        tina4python serve --host 127.0.0.1 --port 8080
    """
    os.environ.setdefault("TINA4_DEBUG", "true")
    os.environ.setdefault("TINA4_LOG_LEVEL", "ALL")

    cli_host = None
    cli_port = None

    # Parse flags and positional args
    i = 0
    while i < len(args):
        if args[i] == "--port" and i + 1 < len(args):
            cli_port = int(args[i + 1])
            i += 2
        elif args[i] == "--host" and i + 1 < len(args):
            cli_host = args[i + 1]
            i += 2
        elif args[i].isdigit() and cli_port is None:
            cli_port = int(args[i])
            i += 1
        else:
            i += 1

    from tina4_python.core import run
    run(host=cli_host, port=cli_port)


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
    """Show completed and pending migrations."""
    _load_env()
    from tina4_python.database import Database
    from tina4_python.migration import status

    db_url = os.environ.get("DATABASE_URL", "sqlite:///data/app.db")
    db = Database(db_url)
    mig_dir = args[0] if args else "migrations"
    result = status(db, mig_dir)

    completed = result["completed"]
    pending = result["pending"]

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


def _seed(args):
    """Run seeders from src/seeds/."""
    _load_env()
    seed_dir = Path("src/seeds")
    if not seed_dir.is_dir():
        print("No src/seeds/ directory found. Create seed scripts there.")
        return

    import importlib.util

    # Auto-discover and run all .py files in src/seeds/
    seed_files = sorted(seed_dir.glob("*.py"))
    if not seed_files:
        print("No seed files found in src/seeds/")
        return

    # Set up database for seeding
    from tina4_python.database import Database
    db_url = os.environ.get("DATABASE_URL", "sqlite:///data/app.db")
    db = Database(db_url)

    sys.path.insert(0, str(Path.cwd()))
    ran = 0
    for seed_file in seed_files:
        if seed_file.name.startswith("_"):
            continue
        print(f"  Seeding: {seed_file.name}")
        spec = importlib.util.spec_from_file_location(
            seed_file.stem, str(seed_file)
        )
        module = importlib.util.module_from_spec(spec)
        # Inject db into the module's namespace
        module.db = db
        spec.loader.exec_module(module)

        # If the module defines a run() function, call it
        if hasattr(module, "run"):
            module.run(db)
        ran += 1

    db.close()
    print(f"\n{ran} seeder(s) executed.")


def _routes(args):
    """List all registered routes."""
    # Import app to trigger route registration
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
    import subprocess
    cmd = [sys.executable, "-m", "pytest", "tests/"] + args
    subprocess.run(cmd)


def _build(args):
    """Build a distributable package."""
    import subprocess
    # Try PyInstaller first, then shiv, then standard build
    try:
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--onefile", "app.py",
             "--name", "tina4app", "--hidden-import", "tina4_python"],
            check=True,
        )
        print("Built: dist/tina4app")
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fallback to standard Python build
        subprocess.run(
            [sys.executable, "-m", "build"],
            check=True,
        )
        print("Built: dist/")


def _ai(args):
    """Install AI coding assistant context files."""
    from tina4_python.ai import show_menu, install_selected, install_all

    root = "."

    if args and args[0].lower() == "all":
        # Non-interactive: install everything
        install_all(root)
    else:
        # Interactive: show menu, get selection
        selection = show_menu(root)
        if selection:
            install_selected(root, selection)


def _generate(args):
    """Generate scaffolding: model, route, migration, middleware."""
    if len(args) < 2:
        print("Usage: tina4python generate <what> <name>")
        print("  Generators: model, route, migration, middleware")
        sys.exit(1)

    what = args[0].lower()
    name = args[1]

    if what == "model":
        _generate_model(name)
    elif what == "route":
        _generate_route(name)
    elif what == "migration":
        _generate_migration(name)
    elif what == "middleware":
        _generate_middleware(name)
    else:
        print(f"Unknown generator: {what}")
        print("  Available: model, route, migration, middleware")
        sys.exit(1)


def _generate_model(name):
    """Generate an ORM model file."""
    target = Path("src/orm")
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{name}.py"
    if path.exists():
        print(f"  File already exists: {path}")
        sys.exit(1)
    path.write_text(
        f"from tina4_python import ORM, IntegerField, StringField\n\n\n"
        f"class {name}(ORM):\n"
        f"    id = IntegerField(primary_key=True, auto_increment=True)\n"
        f"    name = StringField()\n"
        f"    email = StringField()\n",
        encoding="utf-8",
    )
    print(f"  Created {path}")


def _generate_route(name):
    """Generate a CRUD route file."""
    route_path = name.lstrip("/")
    target = Path("src/routes") / route_path
    target.mkdir(parents=True, exist_ok=True)
    path = Path(f"src/routes/{route_path}.py")
    if path.exists():
        print(f"  File already exists: {path}")
        sys.exit(1)
    path.write_text(
        f'from tina4_python.core.router import get, post, put, delete\n\n\n'
        f'@get("/{route_path}")\n'
        f'async def get_list(request, response):\n'
        f'    """List all."""\n'
        f'    return response({{"data": []}})\n\n\n'
        f'@get("/{route_path}/{{id}}")\n'
        f'async def get_one(request, response):\n'
        f'    """Get by id."""\n'
        f'    return response({{"data": {{}}}})\n\n\n'
        f'@post("/{route_path}")\n'
        f'async def create(request, response):\n'
        f'    """Create new."""\n'
        f'    return response({{"message": "created"}}, 201)\n\n\n'
        f'@put("/{route_path}/{{id}}")\n'
        f'async def update(request, response):\n'
        f'    """Update by id."""\n'
        f'    return response({{"message": "updated"}})\n\n\n'
        f'@delete("/{route_path}/{{id}}")\n'
        f'async def remove(request, response):\n'
        f'    """Delete by id."""\n'
        f'    return response({{"message": "deleted"}})\n',
        encoding="utf-8",
    )
    print(f"  Created {path}")


def _generate_migration(name):
    """Generate a timestamped migration file."""
    from datetime import datetime

    target = Path("migrations")
    target.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    timestamp = now.strftime("%Y%m%d%H%M%S")
    table = name.removeprefix("create_")
    if not table.endswith("s"):
        table = table + "s" if not table.endswith("y") else table[:-1] + "ies"

    filename = f"{timestamp}_{name}.sql"
    path = target / filename
    path.write_text(
        f"-- Migration: {name}\n"
        f"-- Created: {now.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"CREATE TABLE {table} (\n"
        f"    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
        f"    name TEXT NOT NULL,\n"
        f"    email TEXT NOT NULL,\n"
        f"    created_at DATETIME DEFAULT CURRENT_TIMESTAMP\n"
        f");\n",
        encoding="utf-8",
    )
    print(f"  Created {path}")


def _generate_middleware(name):
    """Generate a middleware class file."""
    target = Path("src/middleware")
    target.mkdir(parents=True, exist_ok=True)

    # Convert CamelCase to snake_case for filename
    snake = ""
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            snake += "_"
        snake += ch.lower()

    path = target / f"{snake}.py"
    if path.exists():
        print(f"  File already exists: {path}")
        sys.exit(1)
    path.write_text(
        f"from tina4_python.core.middleware import Middleware\n\n\n"
        f"class {name}(Middleware):\n"
        f'    async def process(self, request, response):\n'
        f'        auth = request.headers.get("Authorization")\n'
        f"        if not auth:\n"
        f'            return request, response({{"error": "Unauthorized"}}, 401)\n'
        f"        return request, response\n",
        encoding="utf-8",
    )
    print(f"  Created {path}")


def _load_env():
    """Load .env file if it exists."""
    env_path = Path(".env")
    if env_path.exists():
        from tina4_python.dotenv import load_env
        load_env(str(env_path))


__all__ = ["main"]
