# Tina4 AI — Detect and install AI coding assistant context files.
"""
Detect which AI tools are present in a project and install Tina4-aware
context files so any assistant understands the framework.

    from tina4_python.ai import detect_ai, install_context, status_report

    tools = detect_ai(".")          # → [{"name": "claude-code", "installed": True, ...}, ...]
    install_context(".")             # install for all known tools
    install_context(".", tools=["claude-code", "cursor"])
    print(status_report("."))        # human-readable summary
"""
import os
import shutil
import subprocess
from pathlib import Path

from .client import (
    Ai,
    AiConfigError,
    AiError,
    AiHTTPError,
    AiParseError,
    AiTimeoutError,
    ChatResponse,
)


# Ordered list of supported AI tools
AI_TOOLS = [
    {"name": "claude-code", "description": "Claude Code", "context_file": "CLAUDE.md", "config_dir": ".claude"},
    {"name": "cursor", "description": "Cursor", "context_file": ".cursorules", "config_dir": ".cursor"},
    {"name": "copilot", "description": "GitHub Copilot", "context_file": ".github/copilot-instructions.md", "config_dir": ".github"},
    {"name": "windsurf", "description": "Windsurf", "context_file": ".windsurfrules", "config_dir": None},
    {"name": "aider", "description": "Aider", "context_file": "CONVENTIONS.md", "config_dir": None},
    {"name": "cline", "description": "Cline", "context_file": ".clinerules", "config_dir": None},
    {"name": "codex", "description": "OpenAI Codex", "context_file": "AGENTS.md", "config_dir": None},
    # Google Antigravity is intentionally NOT listed as a separate tool.
    # Per Antigravity docs (v1.20.3+, March 2026), it reads AGENTS.md
    # from the repo root — the same cross-tool standard Codex pioneered
    # and Cursor / Claude Code already adopt. The Codex entry above
    # already writes our Tina4 skill block there, so Antigravity picks
    # up the same content with zero extra installer work. If you also
    # want Antigravity-specific tuning, write to .agents/rules/tina4.md
    # by hand — see https://antigravity.google/docs/rules-workflows.
]


# ── Skill files (the SKILL.md system) ───────────────────────────────────────
# `tina4 ai` installs the actual skills — not just a CLAUDE.md pointer to them —
# into BOTH the project (.claude/skills, so they travel with the repo) and the
# user's global ~/.claude/skills (so they're available in every project). A
# Python project needs the python developer skill plus the two shared skills;
# all three are served from the tina4-python release tag.
_DEV_SKILL = "tina4-developer-python"
_SKILL_REPO = "tina4-python"
_SKILLS = {
    _DEV_SKILL: ["auth-and-services.md", "data-and-orm.md", "deployment.md",
                 "routes-and-api.md", "templates-and-frontend.md", "realtime.md"],
    "tina4-js": ["html-and-components.md", "signals-and-reactivity.md",
                 "persistence.md", "rtc.md"],
    "tina4-maintainer": ["cli-and-deployment.md", "frond-and-frontend.md",
                         "routing-and-orm.md", "subsystems.md"],
}


def _skills_ref() -> str:
    """Release tag to pull skills from — the installed framework version,
    overridable with TINA4_SKILLS_REF (e.g. to test a branch)."""
    ref = os.environ.get("TINA4_SKILLS_REF")
    if ref:
        return ref
    try:
        from tina4_python import __version__
        return __version__
    except Exception:
        return "main"


def _fetch_bytes(url: str, attempts: int = 5) -> "bytes | None":
    # raw.githubusercontent.com returns an intermittent 503 under load (a freshly
    # cut tag is "cold" until GitHub warms its CDN), so a single failed fetch out of
    # the ~30 an install makes should not abort it. Retry a transient status
    # (429 / 5xx) and connection errors; a permanent 404 is never retried.
    import time
    import urllib.error
    import urllib.request
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return None
        except (urllib.error.URLError, OSError):
            if attempt < attempts - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return None
    return None


def install_skills(root: str = ".", targets: "list[Path] | None" = None) -> list[str]:
    """Install the Tina4 SKILL.md skills into the project AND global
    ~/.claude/skills, fetched from the release tag matching this framework
    version. Returns the skills fully installed. Network-dependent."""
    ref = _skills_ref()
    base = f"https://raw.githubusercontent.com/tina4stack/{_SKILL_REPO}/{ref}/.claude/skills"
    if targets is None:
        targets = [Path(root).resolve() / ".claude" / "skills",
                   Path.home() / ".claude" / "skills"]
    installed = []
    for skill, refs in _SKILLS.items():
        skill_ok = True
        for dest in targets:
            skill_dir = dest / skill
            (skill_dir / "references").mkdir(parents=True, exist_ok=True)
            data = _fetch_bytes(f"{base}/{skill}/SKILL.md")
            if data is None:
                skill_ok = False
                continue
            (skill_dir / "SKILL.md").write_bytes(data)
            for r in refs:
                rd = _fetch_bytes(f"{base}/{skill}/references/{r}")
                if rd is not None:
                    (skill_dir / "references" / r).write_bytes(rd)
        if skill_ok:
            installed.append(skill)
    return installed


def is_installed(root: str, tool: dict) -> bool:
    """Check if a tool's context file already exists."""
    return (Path(root).resolve() / tool["context_file"]).exists()


# ── Detection API (docs-friendly names) ────────────────────────────────────


def detect_ai(root: str = ".") -> list[dict]:
    """Detect which AI coding tools are installed in ``root``.

    Returns a list of tool dicts, one per known AI tool, with an
    ``installed`` boolean added. The list mirrors ``AI_TOOLS`` order.

        from tina4_python.ai import detect_ai
        tools = detect_ai(".")
        installed = [t for t in tools if t["installed"]]
    """
    return [{**t, "installed": is_installed(root, t)} for t in AI_TOOLS]


def detect_ai_names(root: str = ".") -> list[str]:
    """Return only the names of detected (installed) AI tools.

        names = detect_ai_names(".")   # → ["claude-code", "cursor"]
    """
    return [t["name"] for t in AI_TOOLS if is_installed(root, t)]


def status_report(root: str = ".") -> str:
    """Human-readable summary of AI-tool installation state in ``root``.

    Returns a multi-line string suitable for printing — lists each tool
    along with installed/not-installed and the path of the context file.
    """
    root = str(Path(root).resolve())
    lines = [f"AI tool status — {root}", ""]
    for tool in AI_TOOLS:
        marker = "✓ installed" if is_installed(root, tool) else "  not present"
        lines.append(f"  {marker}  {tool['description']:<24s} → {tool['context_file']}")
    installed_count = sum(1 for t in AI_TOOLS if is_installed(root, t))
    lines.append("")
    lines.append(f"  {installed_count}/{len(AI_TOOLS)} tools have Tina4 context.")
    return "\n".join(lines)


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

    # tina4-ai tools option — rendered AFTER the tool list, always the last number
    tina4_ai_num = len(AI_TOOLS) + 1
    tina4_ai_installed = shutil.which("mdview") is not None
    marker = f"  {green}[installed]{reset}" if tina4_ai_installed else ""
    print(f"  {tina4_ai_num}. Install tina4-ai tools  (requires Python){marker}")
    print()
    return input("  Select (comma-separated, or 'all'): ").strip()


def install_selected(root: str, selection: str) -> list[str]:
    """Install context files for the selected tools.

    selection: comma-separated numbers like "1,2,3" or "all"
    Returns list of created/updated file paths.
    """
    root_path = Path(root).resolve()
    created = []
    tina4_ai_num = len(AI_TOOLS) + 1  # keep menu numbering aligned with show_menu

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
                if n == tina4_ai_num:
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


def install_context(root: str = ".", tools: "list[str] | None" = None) -> list[str]:
    """Install Tina4 context files for AI tools (non-interactive).

    Args:
        root: Project root directory.
        tools: Optional list of tool names. When omitted, installs for all
               known AI tools.

    Returns a list of relative paths to the files that were created.

        install_context(".")                          # all tools
        install_context(".", tools=["claude-code"])   # just one
    """
    if tools is None:
        selection = "all"
    else:
        # Translate names → indices for install_selected's CSV input
        index_map = {t["name"]: str(i + 1) for i, t in enumerate(AI_TOOLS)}
        try:
            selection = ",".join(index_map[name] for name in tools)
        except KeyError as e:
            known = ", ".join(t["name"] for t in AI_TOOLS)
            raise ValueError(f"Unknown AI tool: {e!s}. Known: {known}") from e
    return install_selected(root, selection)


# ── v3.13.9: non-destructive context-file writer ───────────────────────────
#
# Pre-v3.13.9 the installer wrote a full developer guide to CLAUDE.md
# (and the other context files) on every run, clobbering whatever the
# user had put there. Now it writes only a marker-bracketed Tina4 skill
# block — pointing the assistant at .claude/skills/tina4-*/SKILL.md —
# and leaves the rest of the file alone.


def _markers_for(context_file: str) -> "tuple[str, str]":
    """Return ``(start_marker, end_marker)`` for a context file.

    Markdown files get HTML comment markers (invisible when rendered).
    Rule files (.cursorules, .windsurfrules, .clinerules) use ``#``
    line comments which most rule loaders treat as comments.
    """
    if context_file.lower().endswith(".md"):
        return ("<!-- tina4-skills:start -->", "<!-- tina4-skills:end -->")
    return ("# tina4-skills:start", "# tina4-skills:end")


def _skill_block(context_file: str) -> str:
    """Return the marker-bracketed Tina4 skill registration block."""
    start, end = _markers_for(context_file)
    if context_file.lower().endswith(".md"):
        body = (
            "## Tina4 Skills\n\n"
            "When working on this Tina4 project, these skills give the "
            "assistant project-aware behaviour:\n\n"
            f"- **{_DEV_SKILL}** — Read `.claude/skills/{_DEV_SKILL}/SKILL.md` before building features.\n"
            "- **tina4-js** — Read `.claude/skills/tina4-js/SKILL.md` for frontend work.\n"
            "- **tina4-maintainer** — Read `.claude/skills/tina4-maintainer/SKILL.md` for framework-level changes.\n\n"
            "If Tina4 behaves differently from what these skills describe, that is a bug in the skill. "
            "Tell the developer, then report it at https://tina4.com/report-a-skill "
            "(or open an issue on the matching tina4stack/* GitHub repo).\n\n"
            "See https://tina4.com for full docs."
        )
    else:
        body = (
            "Tina4 Skills — read these files before working on this project:\n"
            f"  .claude/skills/{_DEV_SKILL}/SKILL.md   (feature development)\n"
            "  .claude/skills/tina4-js/SKILL.md          (frontend / tina4-js)\n"
            "  .claude/skills/tina4-maintainer/SKILL.md  (framework-level changes)\n"
            "Found a skill that disagrees with how Tina4 actually behaves? Tell the developer,\n"
            "then report it at https://tina4.com/report-a-skill\n"
            "Docs: https://tina4.com"
        )
    return f"{start}\n{body}\n{end}"


def _has_markers(existing: str, start: str, end: str) -> bool:
    """True iff both start and end markers appear in order."""
    s_idx = existing.find(start)
    if s_idx == -1:
        return False
    return existing.find(end, s_idx + len(start)) != -1


def _replace_marker_block(existing: str, block: str, start: str, end: str) -> str:
    """Replace the bracketed block in ``existing`` with ``block``."""
    s_idx = existing.find(start)
    if s_idx == -1:
        return existing.rstrip() + "\n\n" + block + "\n"
    e_idx = existing.find(end, s_idx + len(start))
    if e_idx == -1:
        return existing.rstrip() + "\n\n" + block + "\n"
    before = existing[:s_idx].rstrip()
    after = existing[e_idx + len(end):].lstrip("\n")
    glue_before = "\n\n" if before else ""
    glue_after = "\n" + after if after else "\n"
    return f"{before}{glue_before}{block}{glue_after}"


# Headers the pre-v3.13.9 installer wrote at the top of CLAUDE.md.
# Detecting these lets us migrate cleanly off the old clobber install.
_OLD_FRAMEWORK_HEADERS = (
    "# Tina4 Python",
    "# Tina4 PHP",
    "# Tina4 Ruby",
    "# CLAUDE.md — AI Developer Guide for tina4-nodejs",
    "# CLAUDE.md - AI Developer Guide for tina4-nodejs",
)


def _looks_like_old_framework_install(existing: str) -> bool:
    """True if the file starts with a header the pre-v3.13.9 installer
    wrote. Used to migrate one-time off the old clobber-style install."""
    head = existing.lstrip()[:400]
    return any(head.startswith(m) for m in _OLD_FRAMEWORK_HEADERS)


def _write_or_merge(context_path: "Path", context_file: str, framework_guide: str) -> str:
    """Write the context file non-destructively. Returns a human-readable
    action verb for the caller's log line.

    Four branches:
      1. Doesn't exist  → write framework guide + skill block
      2. Has markers    → refresh just the skill block (idempotent)
      3. Old header     → migrate: replace old dump with new guide + block
      4. User content   → append the skill block, preserve everything else
    """
    block = _skill_block(context_file)
    start, end = _markers_for(context_file)

    if not context_path.exists():
        context_path.write_text(
            framework_guide.rstrip() + "\n\n" + block + "\n",
            encoding="utf-8",
        )
        return "Installed"

    existing = context_path.read_text(encoding="utf-8")
    if _has_markers(existing, start, end):
        new_content = _replace_marker_block(existing, block, start, end)
        context_path.write_text(new_content, encoding="utf-8")
        return "Refreshed skill block in"

    if _looks_like_old_framework_install(existing):
        head = existing.lstrip()
        preamble = existing[: len(existing) - len(head)]
        new_content = (
            (preamble.rstrip() + "\n\n" if preamble.strip() else "")
            + framework_guide.rstrip()
            + "\n\n"
            + block
            + "\n"
        )
        context_path.write_text(new_content, encoding="utf-8")
        return "Migrated (replaced old framework dump in)"

    new_content = existing.rstrip() + "\n\n" + block + "\n"
    context_path.write_text(new_content, encoding="utf-8")
    return "Appended skill block to"


def _install_for_tool(root: Path, tool: dict, context: str) -> list[str]:
    """Install context file for a single tool."""
    created = []
    context_path = root / tool["context_file"]

    # Create directories
    if tool.get("config_dir"):
        (root / tool["config_dir"]).mkdir(parents=True, exist_ok=True)
    context_path.parent.mkdir(parents=True, exist_ok=True)

    # v3.13.9: non-destructive write — see _write_or_merge below.
    action = _write_or_merge(context_path, tool["context_file"], context)
    rel = str(context_path.relative_to(root))
    created.append(rel)
    try:
        print(f"  \033[32m\u2713\033[0m {action} {rel}")
    except UnicodeEncodeError:
        print(f"  [OK] {action} {rel}")

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

    # Install the SKILL.md skills into the project AND the user's global
    # ~/.claude/skills, fetched from the release tag matching this framework
    # version. (The previous code copied from framework_root/.claude/skills,
    # which exists only in a dev/editable checkout — NOT in an installed pip
    # package, where .claude/skills sits outside the tina4_python package and
    # is never shipped. So installed users got no skills at all.)
    for skill in install_skills(str(root)):
        created.append(f".claude/skills/{skill}/")
        try:
            print(f"  \033[32m✓\033[0m Installed .claude/skills/{skill}  (project + global)")
        except UnicodeEncodeError:
            print(f"  [OK] Installed .claude/skills/{skill} (project + global)")

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
