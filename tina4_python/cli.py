#!/usr/bin/env python3
#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
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

def create_project(project_name: str) -> None:
    """Scaffold a new Tina4 project (supports '.' for current directory) + Dockerfile."""
    project_path = Path(project_name).resolve()

    # Allow "." or "./" → scaffold in the current folder
    if project_name in (".", "./"):
        project_path = Path.cwd()
    else:
        project_path.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # app.py
    # ------------------------------------------------------------------
    app_py = project_path / "app.py"
    if app_py.exists():
        print(f"Overwriting existing 'app.py' in {project_path}")
    else:
        print(f"Creating project in {project_path}")

    app_content = '''\
from tina4_python import run_web_server
from tina4_python.Router import get

@get("/health-check")
async def index(request, response):

    return response(f"OK")

if __name__ == "__main__":
    run_web_server("0.0.0.0", 7145)
'''
    app_py.write_text(app_content, encoding="utf-8")

    # ------------------------------------------------------------------
    # requirements.txt (fallback for non-uv users)
    # ------------------------------------------------------------------
    req_file = project_path / "requirements.txt"
    if not req_file.exists():
        req_file.write_text("tina4-python\n", encoding="utf-8")

    # ------------------------------------------------------------------
    # pyproject.toml + uv.lock (optional – nice to have)
    # ------------------------------------------------------------------
    pyproject = project_path / "pyproject.toml"
    if not pyproject.exists():
        pyproject.write_text("""\
[project]
name = "tina4-project"
version = "0.1.0"
dependencies = [
    "tina4-python",
]

[build-system]
requires = ["setuptools>=45"]
build-backend = "setuptools.build_meta"
""", encoding="utf-8")

    # ------------------------------------------------------------------
    # Dockerfile (multi-stage with uv – production ready)
    # ------------------------------------------------------------------
    dockerfile_path = project_path / "Dockerfile"
    if dockerfile_path.exists():
        print("Dockerfile already exists – skipping creation")
    else:
        dockerfile_content = '''\
# === Build Stage ===
FROM python:3.13-alpine AS builder

# Install build dependencies + uv
RUN apk add --no-cache \\
    build-base \\
    libffi-dev \\
    python3-dev \\
    cargo

# Install uv (official installer)
ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Copy dependency definition
COPY pyproject.toml uv.lock* ./

# Install dependencies into system python (editable install works with uv too)
RUN uv pip install --system -e .

# Copy source code
COPY . .

# === Runtime Stage ===
FROM python:3.13-alpine

# Runtime packages only
RUN apk add --no-cache libffi libstdc++ libgcc

WORKDIR /app

# Copy installed packages + binaries
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --from=builder /app /app

EXPOSE 7145

# Swagger defaults (override with env vars in docker-compose/k8s if needed)
ENV SWAGGER_TITLE="Tina4 API"
ENV SWAGGER_VERSION="0.1.0"
ENV SWAGGER_DESCRIPTION="Auto-generated API documentation"

# Start the server on all interfaces
CMD ["python3", "app.py", "0.0.0.0:7145", "-u"]
'''
        dockerfile_path.write_text(dockerfile_content, encoding="utf-8")
        print("Dockerfile created (multi-stage + uv)")

    # ------------------------------------------------------------------
    # Final message
    # ------------------------------------------------------------------
    print("Project ready!")
    if project_path != Path.cwd():
        print(f"\nNext steps:")
        print(f"   cd {project_path.relative_to(Path.cwd())}")
        print(f"   python app.py          # local development")
        print(f"   docker build -t {project_path.name} . && docker run -p 7145:7145 {project_path.name}")
    else:
        print("\nYou are already in the project folder. Run:")
        print("   python app.py                     # development")
        print("   docker build -t myapp . && docker run -p 7145:7145 myapp")


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

    test_parser = subparsers.add_parser("test", help="Run all @tests in the project")
    test_parser.add_argument("--quiet", "-q", action="store_true", help="Only show failures")
    test_parser.add_argument("--failfast", "-x", action="store_true", help="Stop on first failure")

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
    elif args.command == "test":
        from tina4_python.Testing import run_all_tests
        run_all_tests(quiet=args.quiet, failfast=args.failfast)
    else:
        # Default: run server if no command
        parser.print_help()


if __name__ == "__main__":
    main()
