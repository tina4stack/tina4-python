# Tina4 AI — Install AI coding assistant context files.
"""
Simple menu-driven installer for AI tool context files.
The user picks which tools they use, we install the appropriate files.

    from tina4_python.ai import show_menu, install_selected
"""
import os
import shutil
import subprocess
from pathlib import Path


# Ordered list of supported AI tools
AI_TOOLS = [
    {"name": "claude-code", "description": "Claude Code", "context_file": "CLAUDE.md", "config_dir": ".claude"},
    {"name": "cursor", "description": "Cursor", "context_file": ".cursorules", "config_dir": ".cursor"},
    {"name": "copilot", "description": "GitHub Copilot", "context_file": ".github/copilot-instructions.md", "config_dir": ".github"},
    {"name": "windsurf", "description": "Windsurf", "context_file": ".windsurfrules", "config_dir": None},
    {"name": "aider", "description": "Aider", "context_file": "CONVENTIONS.md", "config_dir": None},
    {"name": "cline", "description": "Cline", "context_file": ".clinerules", "config_dir": None},
    {"name": "codex", "description": "OpenAI Codex", "context_file": "AGENTS.md", "config_dir": None},
]


def is_installed(root: str, tool: dict) -> bool:
    """Check if a tool's context file already exists."""
    return (Path(root).resolve() / tool["context_file"]).exists()


def show_menu(root: str = ".") -> str:
    """Print the numbered menu and return user input."""
    root = str(Path(root).resolve())
    green = "\033[32m"
    reset = "\033[0m"

    print("\n  Tina4 AI Context Installer\n")
    for i, tool in enumerate(AI_TOOLS, 1):
        installed = is_installed(root, tool)
        marker = f"  {green}[installed]{reset}" if installed else ""
        print(f"  {i}. {tool['description']:<20s} {tool['context_file']}{marker}")

    # tina4-ai tools option
    tina4_ai_installed = shutil.which("mdview") is not None
    marker = f"  {green}[installed]{reset}" if tina4_ai_installed else ""
    print(f"  8. Install tina4-ai tools  (requires Python){marker}")
    print()
    return input("  Select (comma-separated, or 'all'): ").strip()


def install_selected(root: str, selection: str) -> list[str]:
    """Install context files for the selected tools.

    selection: comma-separated numbers like "1,2,3" or "all"
    Returns list of created/updated file paths.
    """
    root_path = Path(root).resolve()
    created = []

    if selection.lower() == "all":
        indices = list(range(len(AI_TOOLS)))
        install_tina4_ai = True
    else:
        parts = [s.strip() for s in selection.split(",") if s.strip()]
        indices = []
        install_tina4_ai = False
        for p in parts:
            try:
                n = int(p)
                if n == 8:
                    install_tina4_ai = True
                elif 1 <= n <= len(AI_TOOLS):
                    indices.append(n - 1)
            except ValueError:
                pass

    for idx in indices:
        tool = AI_TOOLS[idx]
        context = generate_context(tool["name"])
        files = _install_for_tool(root_path, tool, context)
        created.extend(files)

    if install_tina4_ai:
        _install_tina4_ai()

    return created


def install_all(root: str = ".") -> list[str]:
    """Install context for all AI tools (non-interactive)."""
    return install_selected(root, "all")


def _install_for_tool(root: Path, tool: dict, context: str) -> list[str]:
    """Install context file for a single tool."""
    created = []
    context_path = root / tool["context_file"]

    # Create directories
    if tool.get("config_dir"):
        (root / tool["config_dir"]).mkdir(parents=True, exist_ok=True)
    context_path.parent.mkdir(parents=True, exist_ok=True)

    # Always overwrite — user chose to install
    context_path.write_text(context, encoding="utf-8")
    action = "Updated" if context_path.exists() else "Installed"
    rel = str(context_path.relative_to(root))
    created.append(rel)
    print(f"  \033[32m✓\033[0m {action} {rel}")

    # Claude-specific extras
    if tool["name"] == "claude-code":
        skills = _install_claude_skills(root)
        created.extend(skills)

    return created


def _install_tina4_ai():
    """Install tina4-ai package (provides mdview for markdown viewing)."""
    print("  Installing tina4-ai tools...")
    for cmd in ["pip3", "pip"]:
        if shutil.which(cmd):
            try:
                result = subprocess.run(
                    [cmd, "install", "--upgrade", "tina4-ai"],
                    capture_output=True, text=True, timeout=60,
                )
                if result.returncode == 0:
                    print("  \033[32m✓\033[0m Installed tina4-ai (mdview)")
                    return
                else:
                    print(f"  \033[33m!\033[0m {cmd} failed: {result.stderr.strip()[:100]}")
            except (subprocess.TimeoutExpired, OSError):
                continue
    print("  \033[33m!\033[0m Python/pip not available — skip tina4-ai")


def _install_claude_skills(root: Path) -> list[str]:
    """Copy Claude Code skill files from the framework's templates."""
    created = []
    commands_dir = root / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    pkg_dir = Path(__file__).parent.parent
    source_dirs = [pkg_dir / "templates" / "ai" / "claude-commands"]

    for source_dir in source_dirs:
        if source_dir.is_dir():
            for skill_file in source_dir.glob("*.md"):
                target = commands_dir / skill_file.name
                target.write_text(skill_file.read_text(encoding="utf-8"), encoding="utf-8")
                rel = str(target.relative_to(root))
                created.append(rel)

    # Copy skill directories from framework .claude/skills/
    framework_root = pkg_dir.parent
    framework_skills_dir = framework_root / ".claude" / "skills"
    if framework_skills_dir.is_dir():
        target_skills_dir = root / ".claude" / "skills"
        target_skills_dir.mkdir(parents=True, exist_ok=True)
        for skill_dir in framework_skills_dir.iterdir():
            if skill_dir.is_dir():
                target_dir = target_skills_dir / skill_dir.name
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                shutil.copytree(skill_dir, target_dir)
                rel = str(target_dir.relative_to(root))
                created.append(rel)
                print(f"  \033[32m✓\033[0m Updated {rel}")

    return created


def generate_context(tool_name: str = "claude-code") -> str:
    """Generate tool-specific Tina4 context. Each tool gets content suited to its format."""
    from tina4_python import __version__
    v = __version__

    # Shared building blocks
    _route_example = '''from tina4_python.core.router import get, post, noauth, secured

@get("/api/users")
async def list_users(request, response):
    return response({{"users": []}})

@post("/api/users")
@noauth()
async def create_user(request, response):
    return response({{"created": request.body["name"]}}, 201)'''

    _orm_example = '''from tina4_python.orm import ORM, IntegerField, StringField

class User(ORM):
    table_name = "users"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField(required=True)
    email = StringField()'''

    _conventions = """1. Routes return response() — always response(data) not response.json()
2. GET routes are public, POST/PUT/PATCH/DELETE require auth by default
3. Use @noauth() to make write routes public, @secured() to protect GET routes
4. Decorator order: @noauth/@secured then @description/@tags then @get/@post (route innermost)
5. Every template extends base.twig
6. All schema changes via migrations — never create tables in route code
7. Use built-in features — never install packages for things Tina4 already provides"""

    _features_compact = (
        "Router, ORM, Database (SQLite/PostgreSQL/MySQL/MSSQL/Firebird), "
        "Frond templates (Twig-compatible), JWT auth, Sessions (File/Redis/Valkey/MongoDB/DB), "
        "GraphQL + GraphiQL, WebSocket + Redis backplane, WSDL/SOAP, Queue (File/RabbitMQ/Kafka/MongoDB), "
        "HTTP client, Messenger (SMTP/IMAP), FakeData/Seeder, Migrations, SCSS compiler, "
        "Swagger/OpenAPI, i18n, Events, Container/DI, HtmlElement, Inline testing, "
        "Error overlay, Dev dashboard, Rate limiter, Response cache, Logging, MCP server"
    )

    _project_structure = """src/routes/    — Route handlers (auto-discovered)
src/orm/       — ORM models
src/templates/ — Twig templates
src/app/       — Service classes
src/scss/      — SCSS (auto-compiled)
src/public/    — Static assets
src/seeds/     — Database seeders
migrations/    — SQL migration files
tests/         — pytest tests"""

    # ── Cursor: compact key patterns ──
    if tool_name == "cursor":
        return f"""# tina4-python — Cursor Rules

Tina4 Python v{v}. 54 built-in features, zero dependencies. Python 3.12+.

## Key Patterns

```python
{_route_example}
```

```python
{_orm_example}
```

## Critical Rules

{_conventions}

## Built-in Features

{_features_compact}

## Docs

https://tina4.com
"""

    # ── Copilot: short instructions ──
    if tool_name == "copilot":
        return f"""# tina4-python Copilot Instructions

Tina4 Python v{v}. 54 features, zero dependencies.

## Route Pattern

```python
{_route_example}
```

## Critical Rules

{_conventions}

## Built-in (use these, don't install alternatives)

{_features_compact}
"""

    # ── Windsurf: same format as Cursor ──
    if tool_name == "windsurf":
        return f"""# tina4-python — Windsurf Rules

Tina4 Python v{v}. 54 built-in features, zero dependencies. Python 3.12+.

## Key Patterns

```python
{_route_example}
```

```python
{_orm_example}
```

## Conventions

{_conventions}

## Built-in Features

{_features_compact}

## Project Structure

```
{_project_structure}
```

## Docs

https://tina4.com
"""

    # ── Aider (CONVENTIONS.md): concise conventions ──
    if tool_name == "aider":
        return f"""# Tina4 Python — Conventions

v{v} — 54 built-in features, zero dependencies.

## Rules

{_conventions}

## Route Pattern

```python
{_route_example}
```

## ORM Pattern

```python
{_orm_example}
```

## Structure

```
{_project_structure}
```

## Built-in Features

{_features_compact}
"""

    # ── Cline: same as Cursor ──
    if tool_name == "cline":
        return f"""# tina4-python — Cline Rules

Tina4 Python v{v}. 54 built-in features, zero dependencies. Python 3.12+.

## Key Patterns

```python
{_route_example}
```

```python
{_orm_example}
```

## Conventions

{_conventions}

## Built-in Features

{_features_compact}
"""

    # ── Codex (AGENTS.md): task-oriented ──
    if tool_name == "codex":
        return f"""# Tina4 Python — Agent Instructions

v{v}. 54 built-in features, zero dependencies. Python 3.12+.

## Framework

This project uses Tina4 Python. All features are built in — do not install external packages for routing, ORM, auth, templates, GraphQL, WebSocket, email, queues, or any other feature listed below.

## Conventions

{_conventions}

## Route Pattern

```python
{_route_example}
```

## ORM Pattern

```python
{_orm_example}
```

## Available Features

{_features_compact}

## Project Structure

```
{_project_structure}
```

## CLI

```bash
tina4python serve       # Dev server on port 7145
tina4python migrate     # Run migrations
tina4python test        # Run tests
tina4python routes      # List routes
```
"""

    # ── Claude Code (CLAUDE.md): full developer guide — defer to existing CLAUDE.md ──
    # For claude-code, read the existing CLAUDE.md from the framework repo
    # as it's the most detailed and maintained file
    if tool_name == "claude-code":
        framework_claude = Path(__file__).parent.parent.parent / "CLAUDE.md"
        if framework_claude.exists():
            return framework_claude.read_text(encoding="utf-8")

    # Fallback: universal context
    return f"""# Tina4 Python — AI Context

Tina4 Python v{v}. 54 built-in features, zero dependencies.

## Conventions

{_conventions}

## Route Pattern

```python
{_route_example}
```

## ORM Pattern

```python
{_orm_example}
```

## Built-in Features

{_features_compact}

## Project Structure

```
{_project_structure}
```

## Docs

https://tina4.com
"""


__all__ = ["AI_TOOLS", "is_installed", "show_menu", "install_selected", "install_all", "generate_context"]
