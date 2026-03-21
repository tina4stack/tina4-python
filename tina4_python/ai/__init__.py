# Tina4 AI — Detect AI coding assistants and scaffold context files.
"""
Detect which AI coding tools are available and install framework-aware
context so that any AI assistant understands how to build with Tina4.

    from tina4_python.ai import detect_ai, install_ai_context

    tools = detect_ai()          # ["claude-code", "cursor"]
    install_ai_context()         # Scaffold context for all detected tools
"""
import os
import json
import shutil
from pathlib import Path


# AI tool detection signatures: (name, detection_function)
_AI_TOOLS = {
    "claude-code": {
        "description": "Claude Code (Anthropic CLI)",
        "detect": lambda root: (root / ".claude").is_dir() or (root / "CLAUDE.md").exists(),
        "config_dir": ".claude",
        "context_file": "CLAUDE.md",
    },
    "cursor": {
        "description": "Cursor IDE",
        "detect": lambda root: (root / ".cursor").is_dir() or (root / ".cursorules").exists(),
        "config_dir": ".cursor",
        "context_file": ".cursorules",
    },
    "copilot": {
        "description": "GitHub Copilot",
        "detect": lambda root: (
            (root / ".github" / "copilot-instructions.md").exists()
            or (root / ".github").is_dir()
        ),
        "config_dir": ".github",
        "context_file": ".github/copilot-instructions.md",
    },
    "windsurf": {
        "description": "Windsurf (Codeium)",
        "detect": lambda root: (root / ".windsurfrules").exists(),
        "config_dir": None,
        "context_file": ".windsurfrules",
    },
    "aider": {
        "description": "Aider",
        "detect": lambda root: (root / ".aider.conf.yml").exists() or (root / "CONVENTIONS.md").exists(),
        "config_dir": None,
        "context_file": "CONVENTIONS.md",
    },
    "cline": {
        "description": "Cline (VS Code)",
        "detect": lambda root: (root / ".clinerules").exists(),
        "config_dir": None,
        "context_file": ".clinerules",
    },
    "codex": {
        "description": "OpenAI Codex CLI",
        "detect": lambda root: (root / "AGENTS.md").exists() or (root / "codex.md").exists(),
        "config_dir": None,
        "context_file": "AGENTS.md",
    },
}


def detect_ai(root: str = ".") -> list[dict]:
    """Detect which AI coding tools are present in the project.

    Returns a list of dicts with tool info:
        [{"name": "claude-code", "description": "Claude Code (Anthropic CLI)", "installed": True}]
    """
    root = Path(root).resolve()
    detected = []
    for name, tool in _AI_TOOLS.items():
        detected.append({
            "name": name,
            "description": tool["description"],
            "installed": tool["detect"](root),
        })
    return detected


def detect_ai_names(root: str = ".") -> list[str]:
    """Return just the names of detected AI tools."""
    return [t["name"] for t in detect_ai(root) if t["installed"]]


def generate_context(include_skills: bool = True) -> str:
    """Generate a universal Tina4 context document for any AI assistant.

    This produces a Markdown document describing the framework, its features,
    conventions, and how to build with it. It's designed to be understood by
    any LLM-based coding assistant.
    """
    skills_section = ""
    if include_skills:
        skills_section = """

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
"""

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
frontend/         — Frontend framework source (builds to public/)
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
| Background Queue | queue | `from tina4_python.queue import Queue, Producer, Consumer` |
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
{skills_section}
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


def install_context(root: str = ".", tools: list[str] = None, force: bool = False) -> list[str]:
    """Install Tina4 context files for detected (or specified) AI tools.

    Args:
        root: Project root directory
        tools: Specific tools to install for (None = auto-detect all)
        force: Overwrite existing context files

    Returns:
        List of files created/updated
    """
    root = Path(root).resolve()
    created = []

    if tools is None:
        # Auto-detect, but also include common ones that should always be present
        tools = detect_ai_names(str(root))

    context = generate_context(include_skills=True)

    for tool_name in tools:
        tool = _AI_TOOLS.get(tool_name)
        if not tool:
            continue

        files = _install_for_tool(root, tool_name, tool, context, force)
        created.extend(files)

    return created


def install_all(root: str = ".", force: bool = False) -> list[str]:
    """Install Tina4 context for ALL known AI tools (not just detected ones).

    This is called by `tina4python init --ai` to pre-install context for every
    supported AI assistant.
    """
    root = Path(root).resolve()
    created = []
    context = generate_context(include_skills=True)

    for tool_name, tool in _AI_TOOLS.items():
        files = _install_for_tool(root, tool_name, tool, context, force)
        created.extend(files)

    return created


def _install_for_tool(root: Path, name: str, tool: dict, context: str, force: bool) -> list[str]:
    """Install context files for a specific AI tool."""
    created = []
    context_path = root / tool["context_file"]

    # Create config directory if needed
    if tool.get("config_dir"):
        (root / tool["config_dir"]).mkdir(parents=True, exist_ok=True)

    # For tools that need a subdirectory (e.g., .github/)
    context_path.parent.mkdir(parents=True, exist_ok=True)

    if not context_path.exists() or force:
        # Adapt context format for each tool
        adapted = _adapt_context(name, context)
        context_path.write_text(adapted, encoding="utf-8")
        created.append(str(context_path.relative_to(root)))

    # Install Claude Code skills if it's Claude
    if name == "claude-code":
        skills = _install_claude_skills(root, force)
        created.extend(skills)

    return created


def _adapt_context(tool_name: str, context: str) -> str:
    """Adapt the universal context document for a specific tool's format."""
    if tool_name == "cursor":
        # Cursor uses .cursorules — plain text rules format
        return context

    if tool_name == "windsurf":
        # Windsurf uses .windsurfrules — similar to cursor
        return context

    if tool_name == "cline":
        # Cline uses .clinerules
        return context

    if tool_name == "codex":
        # OpenAI Codex CLI uses AGENTS.md
        return context

    if tool_name == "aider":
        # Aider uses CONVENTIONS.md
        return context

    # Default: return as-is (Claude CLAUDE.md, Copilot instructions.md)
    return context


def _install_claude_skills(root: Path, force: bool) -> list[str]:
    """Copy Claude Code skill files from the framework's templates."""
    created = []
    commands_dir = root / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    # Source skills from the framework package
    pkg_dir = Path(__file__).parent.parent
    # Skills might be in the project's .claude/commands or in templates
    source_dirs = [
        pkg_dir / "templates" / "ai" / "claude-commands",
    ]

    for source_dir in source_dirs:
        if source_dir.is_dir():
            for skill_file in source_dir.glob("*.md"):
                target = commands_dir / skill_file.name
                if not target.exists() or force:
                    target.write_text(skill_file.read_text(encoding="utf-8"), encoding="utf-8")
                    created.append(str(target.relative_to(root)))

    # Copy .skill files from the framework's skills/ directory to project root
    # These are self-contained ZIP archives that Claude Code can install
    framework_root = pkg_dir.parent
    skills_source = framework_root / "skills"
    if skills_source.is_dir():
        for skill_file in skills_source.glob("*.skill"):
            target = root / skill_file.name
            if not target.exists() or force:
                shutil.copy2(skill_file, target)
                created.append(str(target.relative_to(root)))

    # Copy skill directories from the framework's .claude/skills/ to the project
    framework_skills_dir = framework_root / ".claude" / "skills"
    if framework_skills_dir.is_dir():
        target_skills_dir = root / ".claude" / "skills"
        target_skills_dir.mkdir(parents=True, exist_ok=True)
        for skill_dir in framework_skills_dir.iterdir():
            if skill_dir.is_dir():
                target_dir = target_skills_dir / skill_dir.name
                if not target_dir.exists() or force:
                    if target_dir.exists():
                        shutil.rmtree(target_dir)
                    shutil.copytree(skill_dir, target_dir)
                    created.append(str(target_dir.relative_to(root)))

    return created


def status_report(root: str = ".") -> str:
    """Generate a human-readable report of AI tool detection."""
    tools = detect_ai(root)
    installed = [t for t in tools if t["installed"]]
    missing = [t for t in tools if not t["installed"]]

    lines = ["\nTina4 AI Context Status\n"]

    if installed:
        lines.append("Detected AI tools:")
        for t in installed:
            lines.append(f"  ✓ {t['description']} ({t['name']})")
    else:
        lines.append("No AI coding tools detected.")

    if missing:
        lines.append("\nNot detected (install context with `tina4python ai --all`):")
        for t in missing:
            lines.append(f"  · {t['description']} ({t['name']})")

    lines.append("")
    return "\n".join(lines)


__all__ = [
    "detect_ai", "detect_ai_names", "generate_context",
    "install_context", "install_all", "status_report",
]
