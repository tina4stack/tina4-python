# Tina4 CLI — Command-line interface for project management.
"""
CLI commands for development workflow.

    tina4python init              # Scaffold a new project
    tina4python serve             # Start dev server
    tina4python migrate           # Run pending migrations
    tina4python migrate:create    # Create a migration file
    tina4python migrate:rollback  # Rollback last batch
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
        "seed": _seed,
        "routes": _routes,
        "test": _test,
        "build": _build,
        "ai": _ai,
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
  seed                  Run database seeders
  routes                List all registered routes
  test                  Run test suite
  build                 Build distributable package
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
            "TINA4_DEBUG_LEVEL=DEBUG\n"
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
    os.environ.setdefault("TINA4_DEBUG_LEVEL", "DEBUG")

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
    rolled = rollback(db, "migrations")
    if rolled:
        for f in rolled:
            print(f"  Rolled back: {f}")
        print(f"\n{len(rolled)} migration(s) rolled back.")
    else:
        print("Nothing to rollback.")
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
    routes = Router.all()
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
    """Detect AI coding tools and install Tina4 context."""
    from tina4_python.ai import detect_ai, install_context, install_all, status_report

    root = "."

    if "--all" in args:
        # Install context for ALL known AI tools
        created = install_all(root, force="--force" in args)
        if created:
            print("Installed Tina4 context for all AI tools:")
            for f in created:
                print(f"  + {f}")
        else:
            print("All AI context files already exist. Use --force to overwrite.")
    elif "--status" in args or not args:
        # Show detection status
        print(status_report(root))

        # Auto-install for detected tools
        detected = [t for t in detect_ai(root) if t["installed"]]
        if detected:
            created = install_context(root)
            if created:
                print("Installed Tina4 context:")
                for f in created:
                    print(f"  + {f}")
            else:
                print("Context files already exist. Use --force to overwrite.")
    else:
        # Install for specific tool(s)
        created = install_context(root, tools=args, force="--force" in args)
        if created:
            for f in created:
                print(f"  + {f}")
        else:
            print("Nothing to install.")


def _load_env():
    """Load .env file if it exists."""
    env_path = Path(".env")
    if env_path.exists():
        from tina4_python.dotenv import load_dotenv
        load_dotenv(str(env_path))


__all__ = ["main"]
