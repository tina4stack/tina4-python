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

    context = generate_context()

    for idx in indices:
        tool = AI_TOOLS[idx]
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


def generate_context() -> str:
    """Generate the universal Tina4 context document for any AI assistant."""
    return f"""# Tina4 Python — AI Context

This project uses **Tina4 Python**, a lightweight, batteries-included web framework
with zero third-party dependencies for core features.

**Documentation:** https://tina4.com

## Quick Start

```bash
tina4python init .          # Scaffold project
tina4python serve           # Start dev server on port 7145
tina4python migrate         # Run database migrations
tina4python test            # Run test suite
tina4python routes          # List all registered routes
```

## Project Structure

```
src/routes/       — Route handlers (auto-discovered, one per resource)
src/orm/          — ORM models (one per file, filename = class name)
src/templates/    — Twig/Jinja2 templates (extends base.twig)
src/app/          — Shared helpers and service classes
src/scss/         — SCSS files (auto-compiled to public/css/)
src/public/       — Static assets served at /
src/locales/      — Translation JSON files
src/seeds/        — Database seeder scripts
migrations/       — SQL migration files (sequential numbered)
tests/            — pytest test files
```

## Built-in Features (No External Packages Needed)

| Feature | Module | Import |
|---------|--------|--------|
| Routing | router | `from tina4_python.core.router import get, post, put, delete` |
| ORM | orm | `from tina4_python.orm import ORM, IntegerField, StringField` |
| Database | database | `from tina4_python.database import Database` |
| Templates | template | `response.render("page.twig", data)` |
| JWT Auth | auth | `from tina4_python.auth import Auth, hash_password, check_password` |
| REST API Client | api | `from tina4_python.api import Api` |
| GraphQL | graphql | `from tina4_python.graphql import GraphQL, Schema` |
| WebSocket | websocket | `from tina4_python.websocket import WebSocketServer` |
| SOAP/WSDL | wsdl | `from tina4_python.wsdl import WSDL, wsdl_operation` |
| Email (SMTP+IMAP) | messenger | `from tina4_python.messenger import Messenger` |
| Background Queue | queue | `from tina4_python.queue import Queue` |
| SCSS Compilation | scss | Auto-compiled from src/scss/ |
| Migrations | migration | `tina4python migrate` CLI command |
| Seeder | seeder | `from tina4_python.seeder import FakeData, seed_table` |
| i18n | localization | `from tina4_python.localization import Localization` |
| Swagger/OpenAPI | swagger | Auto-generated at /swagger |
| Sessions | session | `request.session.get(key)` / `.set(key, value)` |
| Middleware | middleware | `@middleware(MyMiddleware)` decorator |
| HTML Builder | html_element | `from tina4_python.html_element import HTMLElement` |
| Form Tokens | template | `{{{{ form_token() }}}}` in Twig |

## Key Conventions

1. **Routes return `response()`** — always use `response(data)` not `response.json()`
2. **GET routes are public**, POST/PUT/PATCH/DELETE require auth by default
3. **Use `@noauth()`** to make write routes public, `@secured()` to protect GET routes
4. **Decorator order**: `@noauth/@secured` → `@description/@tags` → `@get/@post` (route decorator innermost)
5. **Every template extends `base.twig`** — no standalone HTML pages
6. **No inline styles** — use SCSS in `src/scss/` with CSS variables
7. **No hardcoded colors** — use `var(--primary)`, `var(--text)`, etc.
8. **All schema changes via migrations** — never create tables in route code
9. **Service pattern** — complex logic goes in `src/app/` service classes, routes stay thin
10. **Use built-in features** — never install packages for things Tina4 already provides

## AI Workflow — Available Skills

When using an AI coding assistant with Tina4, these skills are available:

| Skill | Description |
|-------|-------------|
| `/tina4-route` | Create a new route with proper decorators and auth |
| `/tina4-orm` | Create an ORM model with migration |
| `/tina4-crud` | Generate complete CRUD (migration, ORM, routes, template, tests) |
| `/tina4-auth` | Set up JWT authentication with login/register |
| `/tina4-api` | Create an external API integration |
| `/tina4-queue` | Set up background job processing |
| `/tina4-template` | Create a server-rendered template page |
| `/tina4-graphql` | Set up a GraphQL endpoint |
| `/tina4-websocket` | Set up WebSocket communication |
| `/tina4-wsdl` | Create a SOAP/WSDL service |
| `/tina4-messenger` | Set up email send/receive |
| `/tina4-test` | Write tests for a feature |
| `/tina4-migration` | Create a database migration |
| `/tina4-seed` | Generate fake data for development |
| `/tina4-i18n` | Set up internationalization |
| `/tina4-scss` | Set up SCSS stylesheets |
| `/tina4-frontend` | Set up a frontend framework |

## Common Patterns

### Route
```python
from tina4_python.core.router import get, post, noauth
from tina4_python.swagger import description, tags

@noauth()
@description("Create a widget")
@tags(["widgets"])
@post("/api/widgets")
async def create_widget(request, response):
    data = request.body
    return response({{"created": True}}, 201)
```

### ORM Model
```python
from tina4_python.orm import ORM, IntegerField, StringField

class Widget(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
```

### Template
```twig
{{% extends "base.twig" %}}
{{% block content %}}
<div class="container">
    <h1>{{{{ title }}}}</h1>
    {{% for item in items %}}
        <p>{{{{ item.name }}}}</p>
    {{% endfor %}}
</div>
{{% endblock %}}
```
"""


__all__ = ["AI_TOOLS", "is_installed", "show_menu", "install_selected", "install_all", "generate_context"]
