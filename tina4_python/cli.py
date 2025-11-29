#!/usr/bin/env python3
"""
Tina4 CLI Tool – Quick commands for starting projects and running servers.

Usage: tina4 [COMMAND] [ARGS...]

Commands:
  start PROJECT_NAME    Scaffold a new Tina4 project
  run [PORT]            Run the development server (default: 8000)
  --help                Show this help
"""

import os
import sys
import argparse
from pathlib import Path

# Import your core Tina4 functions (adjust paths as needed)

from tina4_python import run_web_server
from tina4_python.Router import get


def create_project(project_name: str):
    """Scaffold a new Tina4 project directory."""
    project_dir = Path(project_name)
    if project_dir.exists():
        print(f"Error: Directory '{project_name}' already exists.")
        sys.exit(1)

    project_dir.mkdir()

    # Create minimal index.py (based on your Hello World example)
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

    print(f"✅ Project '{project_name}' created!\nRun this next:\ncd {project_name} && pip install -r requirements.txt && python app.py")


def run_server(port: int = 8000):
    """Run the Tina4 dev server."""
    # Your existing run_web_server handles the rest
    print(f"🚀 Starting Tina4 server on http://localhost:{port}")
    run_web_server(port=port)  # Assuming it accepts a port arg; adjust if needed


def main():
    parser = argparse.ArgumentParser(
        description="Tina4 Python CLI – This is not a framework.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Subcommand: start
    start_parser = subparsers.add_parser("start", help="Scaffold a new project")
    start_parser.add_argument("project_name", help="Name of the project directory")

    # Subcommand: run
    run_parser = subparsers.add_parser("run", help="Run the dev server")
    run_parser.add_argument("port", nargs="?", type=int, default=7145, help="Port to run on (default: 7145)")

    args = parser.parse_args()

    if args.command == "start":
        create_project(args.project_name)
    elif args.command == "run":
        run_server(args.port)
    else:
        # Default: run server if no command
        parser.print_help()


if __name__ == "__main__":
    main()