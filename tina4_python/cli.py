#!/usr/bin/env python3
"""
Tina4 CLI Tool – Quick commands for starting projects and running servers.

Usage: tina4 [COMMAND] [ARGS...]

Commands:
  init PROJECT_NAME     Scaffold a new Tina4 project
  start [PORT]          Run the development server (default: 7145)
  migrate               Run pending migrations
  help                  Show this help
"""
import re
import sys
import argparse
from pathlib import Path

# Import your core Tina4 functions (adjust paths as needed)


try:
    from tina4_python import run_web_server
    from tina4_python.Router import get
    from tina4_python.Migration import migrate
    from tina4_python.Debug import Debug
except ImportError as e:
    print("Error: tina4_python not installed. Run: pip install tina4-python")
    sys.exit(1)


from pathlib import Path

def create_project(project_name: str):
    """Scaffold a new Tina4 project directory."""
    project_dir = Path(project_name)

    if project_dir.exists():
        print(f"Warning: Directory '{project_name}' already exists.")

    project_dir.mkdir(exist_ok=True)


    main_py_path = project_dir / "main.py"
    if main_py_path.exists():
        print(f"Removing existing 'main.py' in '{project_name}'...")
        main_py_path.unlink()  # deletes the file


    # Create minimal app.py (renamed from index.py for clarity)
    index_content = '''from tina4_python import run_web_server
from tina4_python.Router import get

@get("/")
async def get_hello_world(request, response):
    return response("Hello World from {project_name}!")

def app():
    run_web_server()

if __name__ == "__main__":
    app()
'''.format(project_name=project_name.title())

    with open(project_dir / "app.py", "w") as f:
        f.write(index_content)

    # Create requirements.txt
    reqs_content = "tina4-python\n"
    with open(project_dir / "requirements.txt", "w") as f:
        f.write(reqs_content)

    print(f"✅ Project '{project_name}' created!\n"
          f"Run this next:\n"
          f"   cd {project_name} && python app.py")


def run_server(port: int = 8000):
    """Run the Tina4 dev server."""
    # Your existing run_web_server handles the rest
    print(f"🚀 Starting Tina4 server on http://localhost:{port}")
    run_web_server(port=port)  # Assuming it accepts a port arg; adjust if needed

# ----------------------------------------------------------------------
# Create SQL migration with auto-increment
# ----------------------------------------------------------------------
def create_sql_migration(description: str):
    """
    Creates a new SQL migration file:
    000001_create_users_table.sql
    """
    migrations_dir = Path("migrations")
    migrations_dir.mkdir(exist_ok=True)

    if not description or description.strip() == "":
        print("Error: Migration description cannot be empty")
        print("Example: tina4 migrate:create create users table")
        sys.exit(1)

    # Normalize description: lowercase, replace spaces/special chars with underscore
    clean_desc = re.sub(r'[^a-z0-9]+', '_', description.strip().lower()).strip("_")

    # Find highest existing number
    existing = [f for f in migrations_dir.iterdir() if f.is_file() and f.name[0].isdigit() and f.suffix == ".sql"]
    numbers = []
    for f in existing:
        match = re.match(r"(\d+)", f.name)
        if match:
            numbers.append(int(match.group(1)))

    next_num = (max(numbers) + 1) if numbers else 1
    filename = f"{next_num:06d}_{clean_desc}.sql"
    filepath = migrations_dir / filename

    template = f"""-- Migration: {description.strip()}
-- Created: {filepath.name}
"""

    filepath.write_text(template)
    print(f"Migration created: {filepath}")

# ----------------------------------------------------------------------
# Migration helpers (official Tina4 way)
# ----------------------------------------------------------------------
def run_migrations():
    """
    Scans common entry-point files and executes them one by one
    until a global `dba` variable is successfully created.
    """
    candidates = [
        "app.py",
        "main.py",
        "src/__init__.py",
        "initialize.py",
        "project.py",
    ]

    dba = None
    loaded_file = None

    for candidate in candidates:
        file_path = Path(candidate)
        if not file_path.exists():
            continue

        print(f"Trying to load dba from: {candidate}")

        # Dynamic import
        import importlib.util
        module_name = file_path.stem if file_path.parent == Path(".") else "src"
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if not spec or not spec.loader:
            continue

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"  → Failed to execute {candidate}: {e}")
            continue

        if hasattr(module, "dba") and getattr(module, "dba") is not None:
            dba = getattr(module, "dba")
            loaded_file = candidate
            print(f"  → Found dba in {candidate}")
            break
        else:
            print(f"  → No dba found in {candidate}")

    # Final check
    if not dba:
        print("\nCould not find a 'dba' instance in any of the following files:")
        for c in candidates:
            if Path(c).exists():
                print(f"  - {c} (exists but no dba)")
            else:
                print(f"  - {c} (not found)")
        print("\nMake sure you have something like:")
        print("    from tina4_python.Database import Database")
        print("    dba = Database(...)")
        print("in one of your main files.")
        sys.exit(1)

    print(f"Using database: {getattr(dba, 'connection_params', 'Unknown')}")
    print("Running migrations...\n")
    try:
        migrate(dba)
        print("All migrations completed successfully!")
    except Exception as e:
        print(f"Migration error: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description="Tina4 Python CLI – This is not a framework.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Subcommand: start
    start_parser = subparsers.add_parser("init", help="Create a new project")
    start_parser.add_argument("project_name", help="Name of the project directory")

    # Subcommand: run
    run_parser = subparsers.add_parser("start", help="Run the dev server")
    run_parser.add_argument("port", nargs="?", type=int, default=7145, help="Port to run on (default: 7145)")

    # migrate
    run_migrate = subparsers.add_parser("migrate", help="Run pending migrations")

    # migrate:create
    run_create = subparsers.add_parser("migrate:create", help="Create a new migration file")
    run_create.add_argument("description", nargs="+", help="Description, e.g. create users table")

    args = parser.parse_args()

    if args.command == "init":
        create_project(args.project_name)
    elif args.command == "start":
        run_server(args.port)
    elif args.command == "migrate":
        run_migrations()
    elif args.command == "migrate:create":
        description = " ".join(args.description)
        create_sql_migration(description)
    else:
        # Default: run server if no command
        parser.print_help()


if __name__ == "__main__":
    main()
