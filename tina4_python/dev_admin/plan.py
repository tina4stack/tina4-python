"""Project plan management — persistent, human-readable task state.

A "plan" is a markdown file under ``plan/`` at the project root with a
lightweight structure the AI (and the human) can both read and edit:

    # Add user authentication

    Goal: JWT login/registration with refresh tokens.

    ## Steps

    - [x] Create User model in src/orm/User.py
    - [x] Add auth middleware in src/app/middleware.py
    - [ ] Add /api/login route
    - [ ] Add /api/register route

    ## Notes

    Use tina4_python.auth.get_token, 60-minute tokens.

At any moment exactly one plan is "current" — recorded by the filename
stored in ``plan/.current``. That plan's contents are injected into
every chat turn's system prompt so the AI keeps working on the same
thing across conversations, and the step list gives a clear "done /
not done" snapshot.

This module is the storage + manipulation layer. MCP tools in
``tina4_python.mcp.tools`` expose it to the AI; the dev-admin UI surfaces
it to the human.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

PLAN_DIR = "plan"
CURRENT_FILE = ".current"
ARCHIVE_SUBDIR = "done"


def _project_root() -> Path:
    return Path(os.getcwd()).resolve()


def _plan_dir() -> Path:
    p = _project_root() / PLAN_DIR
    p.mkdir(exist_ok=True)
    return p


def _current_pointer() -> Path:
    return _plan_dir() / CURRENT_FILE


def _archive_dir() -> Path:
    p = _plan_dir() / ARCHIVE_SUBDIR
    p.mkdir(exist_ok=True)
    return p


def _slugify(title: str) -> str:
    """File-system-safe filename stem for a plan title."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", title.strip().lower()).strip("-")
    return slug[:80] or f"plan-{int(time.time())}"


# ── Plan file shape ──────────────────────────────────────────────────

_STEP_RE = re.compile(r"^\s*[-*]\s*\[(?P<box>[ xX])\]\s*(?P<text>.+?)\s*$")


def _parse(text: str) -> dict:
    """Parse a plan markdown file into a structured dict.

    The parser is tolerant — missing sections are fine; unknown sections
    are preserved verbatim under ``extra``. We only pick apart what we
    need to manipulate programmatically (title, goal, steps).
    """
    lines = text.splitlines()
    title = ""
    goal = ""
    steps: list = []
    notes_lines: list = []
    section = None  # None | "steps" | "notes"

    for raw in lines:
        line = raw.rstrip()
        if not title and line.startswith("# "):
            title = line[2:].strip()
            continue
        low = line.strip().lower()
        if low.startswith("goal:") and not goal:
            goal = line.split(":", 1)[1].strip()
            continue
        if low == "## steps":
            section = "steps"
            continue
        if low == "## notes":
            section = "notes"
            continue
        if line.startswith("## "):
            section = "other"
            continue
        if section == "steps":
            m = _STEP_RE.match(line)
            if m:
                steps.append({
                    "text": m.group("text").strip(),
                    "done": m.group("box").lower() == "x",
                })
        elif section == "notes" and line.strip():
            notes_lines.append(line)

    return {
        "title": title,
        "goal": goal,
        "steps": steps,
        "notes": "\n".join(notes_lines).strip(),
    }


def _render(plan: dict) -> str:
    """Serialise a parsed dict back to canonical markdown."""
    parts: list = [f"# {plan.get('title', 'Untitled plan')}", ""]
    goal = plan.get("goal")
    if goal:
        parts += [f"Goal: {goal}", ""]
    parts.append("## Steps")
    parts.append("")
    for step in plan.get("steps", []):
        box = "x" if step.get("done") else " "
        parts.append(f"- [{box}] {step.get('text', '').strip()}")
    notes = (plan.get("notes") or "").strip()
    if notes:
        parts += ["", "## Notes", "", notes]
    return "\n".join(parts) + "\n"


# ── Public API ───────────────────────────────────────────────────────


def list_plans() -> list:
    """All plan files — merged from `plan/` (user-curated) and
    `.tina4/plans/` (where the Rust supervisor's planner writes).

    Two directories exist because of a historic split: the framework
    treats `plan/` as the canonical project location, but the Rust
    agent's planner writes to `.tina4/plans/` (alongside other
    AI-state artefacts like chat history). Until those are unified
    we read both so plans created either way are discoverable. Dedup
    by filename when a plan exists in both.
    """
    from pathlib import Path
    d = _plan_dir()
    current = current_name() or ""
    # Both directories — order matters for dedup (user-curated first).
    dirs = [d]
    rust_plans = _project_root() / ".tina4" / "plans"
    if rust_plans.is_dir():
        dirs.append(rust_plans)

    seen: set[str] = set()
    out: list = []
    for plan_dir in dirs:
        for p in sorted(plan_dir.glob("*.md")):
            if p.name in seen:
                continue  # plan/ wins over .tina4/plans/ on name clash
            seen.add(p.name)
            parsed = _parse(p.read_text(encoding="utf-8", errors="replace"))
            total = len(parsed["steps"])
            done = sum(1 for s in parsed["steps"] if s["done"])
            out.append({
                "name": p.name,
                "title": parsed["title"] or p.stem,
                "steps_total": total,
                "steps_done": done,
                "is_current": p.name == current,
                # Relative path from project root — lets the SPA open
                # the right file in the editor regardless of which dir
                # the plan came from.
                "path": str(p.relative_to(_project_root())),
            })
    # Newest first by name (filenames start with unix timestamps).
    out.sort(key=lambda x: x["name"], reverse=True)
    return out


def current_name() -> str:
    """Filename of the current plan, or '' when none is set."""
    ptr = _current_pointer()
    if not ptr.exists():
        return ""
    return ptr.read_text(encoding="utf-8").strip()


def set_current(name: str) -> dict:
    """Point .current at the given plan file. Creates plan/ if needed."""
    name = name.strip()
    if not name.endswith(".md"):
        name += ".md"
    plan_path = _plan_dir() / name
    if not plan_path.exists():
        return {"ok": False, "error": f"No such plan: {name}"}
    _current_pointer().write_text(name, encoding="utf-8")
    return {"ok": True, "current": name}


def clear_current() -> dict:
    """Unset the current plan (e.g. when everything's done and nothing's queued)."""
    p = _current_pointer()
    if p.exists():
        p.unlink()
    return {"ok": True}


def current() -> dict:
    """The whole current plan: title, goal, steps (with index + done), notes,
    and a cheap 'next' pointer to the first unchecked step. Returns
    {current: null} when no plan is active — the AI treats that as
    'no specific plan, proceed normally'."""
    name = current_name()
    if not name:
        return {"current": None}
    path = _plan_dir() / name
    if not path.exists():
        # Pointer is dangling — clean up, report.
        clear_current()
        return {"current": None, "warning": f"Current pointer referenced missing file: {name}"}
    parsed = _parse(path.read_text(encoding="utf-8", errors="replace"))
    indexed_steps = [
        {"index": i, "text": s["text"], "done": s["done"]}
        for i, s in enumerate(parsed["steps"])
    ]
    next_step = next((s for s in indexed_steps if not s["done"]), None)
    return {
        "current": name,
        "title": parsed["title"],
        "goal": parsed["goal"],
        "steps": indexed_steps,
        "next_step": next_step,
        "notes": parsed["notes"],
        "progress": {
            "done": sum(1 for s in indexed_steps if s["done"]),
            "total": len(indexed_steps),
        },
        # Attach the execution summary so callers get the full picture
        # in one call — no second round-trip needed just to find out
        # which files this plan has already touched.
        "execution": summarise_execution(name),
    }


def read(name: str) -> dict:
    """Full structured view of any plan by filename."""
    if not name.endswith(".md"):
        name += ".md"
    path = _plan_dir() / name
    if not path.exists():
        return {"error": f"No such plan: {name}"}
    return _parse(path.read_text(encoding="utf-8", errors="replace")) | {"name": name}


def create(title: str, goal: str = "", steps: list | None = None, make_current: bool = True) -> dict:
    """Write a new plan file and (by default) make it the active one.
    ``steps`` is a list of strings — all start unchecked."""
    title = (title or "").strip()
    if not title:
        return {"ok": False, "error": "title is required"}
    stem = _slugify(title)
    name = f"{stem}.md"
    path = _plan_dir() / name
    if path.exists():
        return {"ok": False, "error": f"Plan already exists: {name}. Pick a different title or edit the existing one."}
    plan = {
        "title": title,
        "goal": goal.strip(),
        "steps": [{"text": s.strip(), "done": False} for s in (steps or []) if s.strip()],
        "notes": "",
    }
    path.write_text(_render(plan), encoding="utf-8")
    if make_current:
        _current_pointer().write_text(name, encoding="utf-8")
    return {"ok": True, "name": name, "title": title, "is_current": make_current}


def _load_parsed(name: str) -> tuple[Path, dict]:
    if not name.endswith(".md"):
        name += ".md"
    path = _plan_dir() / name
    if not path.exists():
        raise FileNotFoundError(f"No such plan: {name}")
    return path, _parse(path.read_text(encoding="utf-8", errors="replace"))


def complete_step(index: int, name: str = "") -> dict:
    """Tick a step (by 0-based index) on the current plan (or a named one).
    Returns the updated plan summary + what's next."""
    name = name or current_name()
    if not name:
        return {"ok": False, "error": "No current plan and no name given"}
    try:
        path, plan = _load_parsed(name)
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
    if not 0 <= index < len(plan["steps"]):
        return {"ok": False, "error": f"Step index {index} out of range (0..{len(plan['steps']) - 1})"}
    plan["steps"][index]["done"] = True
    path.write_text(_render(plan), encoding="utf-8")
    remaining = [i for i, s in enumerate(plan["steps"]) if not s["done"]]
    return {
        "ok": True,
        "completed": plan["steps"][index]["text"],
        "remaining": len(remaining),
        "next_step": plan["steps"][remaining[0]]["text"] if remaining else None,
    }


def uncomplete_step(index: int, name: str = "") -> dict:
    """Uncheck a step — useful when a change turns out to have regressed."""
    name = name or current_name()
    if not name:
        return {"ok": False, "error": "No current plan and no name given"}
    try:
        path, plan = _load_parsed(name)
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
    if not 0 <= index < len(plan["steps"]):
        return {"ok": False, "error": f"Step index {index} out of range"}
    plan["steps"][index]["done"] = False
    path.write_text(_render(plan), encoding="utf-8")
    return {"ok": True, "step": plan["steps"][index]["text"]}


def add_step(text: str, name: str = "") -> dict:
    """Append a new unchecked step."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "text is required"}
    name = name or current_name()
    if not name:
        return {"ok": False, "error": "No current plan and no name given"}
    try:
        path, plan = _load_parsed(name)
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
    plan["steps"].append({"text": text, "done": False})
    path.write_text(_render(plan), encoding="utf-8")
    return {"ok": True, "step": text, "index": len(plan["steps"]) - 1}


def append_note(text: str, name: str = "") -> dict:
    """Add a line to the plan's Notes section — great for 'here's a
    gotcha I hit' breadcrumbs the AI drops as it works."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "text is required"}
    name = name or current_name()
    if not name:
        return {"ok": False, "error": "No current plan and no name given"}
    try:
        path, plan = _load_parsed(name)
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
    existing = (plan.get("notes") or "").strip()
    stamp = time.strftime("%Y-%m-%d %H:%M")
    plan["notes"] = (existing + f"\n- [{stamp}] {text}").strip()
    path.write_text(_render(plan), encoding="utf-8")
    return {"ok": True, "appended": text}


# ── Execution ledger — "what has this plan touched so far?" ──────────
#
# Every file_write / file_patch / migration_create that lands while a
# plan is current gets recorded here. The AI reads the *summary* at the
# top of each chat turn (via `summarise_execution()`) so it doesn't
# re-create files it already made — that's the "two migrations for the
# same table" bug we saw.
#
# Stored next to the plan file as `<plan-stem>.log.json` to keep all
# plan state in one place. Not committed (plan/.gitignore covers it).


def _ledger_path(name: str = "") -> Path | None:
    name = name or current_name()
    if not name:
        return None
    if not name.endswith(".md"):
        name += ".md"
    return _plan_dir() / f"{name[:-3]}.log.json"


def record_action(action: str, path: str, note: str = "") -> None:
    """Append an entry to the current plan's ledger. Silently no-ops
    when no plan is active — tools call this unconditionally."""
    lp = _ledger_path()
    if lp is None:
        return
    entries: list = []
    if lp.exists():
        try:
            entries = json.loads(lp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            entries = []
    entries.append({
        "t": int(time.time()),
        "action": action,     # "created" | "patched" | "migration"
        "path": path,
        "note": note,
    })
    # Bound the log so it can't grow forever on long-running plans.
    if len(entries) > 500:
        entries = entries[-500:]
    try:
        lp.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    except OSError:
        pass  # ledger is best-effort


def summarise_execution(name: str = "") -> dict:
    """Grouped view of what the current plan has touched — small
    enough to inline into every system prompt. Groups:
      - `created`: files written for the first time
      - `patched`: files edited
      - `migrations`: migration files generated
    Each bucket is de-duped and capped at 20 paths."""
    lp = _ledger_path(name)
    if lp is None or not lp.exists():
        return {"created": [], "patched": [], "migrations": [], "total": 0}
    try:
        entries = json.loads(lp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"created": [], "patched": [], "migrations": [], "total": 0}

    created: list[str] = []
    patched: list[str] = []
    migrations: list[str] = []
    for e in entries:
        action = e.get("action")
        path = e.get("path")
        if not path:
            continue
        bucket = (
            migrations if action == "migration"
            else created if action == "created"
            else patched if action == "patched"
            else None
        )
        if bucket is not None and path not in bucket:
            bucket.append(path)
    return {
        "created": created[-20:],
        "patched": patched[-20:],
        "migrations": migrations[-20:],
        "total": len(entries),
    }


def flesh(name: str = "", prompt: str = "") -> dict:
    """Auto-generate concrete build steps for an existing (usually empty)
    plan by asking the Tina4 AI backend. Mirrors PHP ``Plan::flesh()``.

    1. Loads plan by ``name`` (defaults to current).
    2. Builds a structured qwen prompt from title + goal + existing
       steps + caller-supplied ``prompt``.
    3. Posts to ``TINA4_AI_URL`` with ``stream: false`` and parses the
       response as a JSON array of step strings. Falls back to
       extracting ``- item`` / ``1. item`` lines on parse failure.
    4. Calls :func:`add_step` for each proposed step, skipping dupes.
    """
    import os as _os
    import urllib.request as _urlreq

    target = (name or "").strip() or current_name()
    if not target:
        return {"ok": False, "error": "No current plan and no name given"}
    current_plan = read(target)
    if "error" in current_plan:
        return {"ok": False, "error": current_plan["error"]}

    existing = [s.get("text", "") for s in current_plan.get("steps", [])]
    title = current_plan.get("title") or target
    goal = current_plan.get("goal") or ""

    system_prompt = (
        "You are Tina4, a coding planner embedded in the Tina4 dev "
        "admin. Return ONLY a JSON array of short imperative step "
        "strings (no prose, no code-fences, no numbering). 3-8 steps, "
        "each referencing concrete files/routes/migrations. Example: "
        '["Create src/orm/Duck.py with id/name/sighted_at", '
        '"Add migration 001_create_ducks.sql", '
        '"Add GET/POST/PUT/DELETE /api/ducks routes in '
        'src/routes/ducks.py"]'
    )
    user_parts = [f"Plan title: {title}"]
    if goal:
        user_parts.append(f"Goal: {goal}")
    if existing:
        user_parts.append("Existing steps (don't repeat):\n- " + "\n- ".join(existing))
    if prompt:
        user_parts.append(f"Extra context from caller: {prompt}")
    user_parts.append("Reply with ONLY the JSON array — no explanation, no markdown fences.")

    ai_url = _os.environ.get("TINA4_AI_URL", "http://localhost:11437/api/chat")
    ai_model = _os.environ.get("TINA4_AI_MODEL", "qwen2.5-coder:14b")
    try:
        req = _urlreq.Request(
            ai_url,
            data=json.dumps({
                "model": ai_model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "\n\n".join(user_parts)},
                ],
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        with _urlreq.urlopen(req, timeout=120) as r:
            result = json.loads(r.read())
    except Exception as exc:
        return {"ok": False, "error": f"AI backend unreachable: {exc}"}

    reply = (result.get("message") or {}).get("content") or result.get("response") or ""
    body = reply.strip()
    if body.startswith("```"):
        body = body.strip("`")
        if body.lower().startswith("json"):
            body = body[4:].strip()
        body = body.rstrip("`").strip()

    proposed: list = []
    try:
        parsed = json.loads(body)
        if isinstance(parsed, list):
            proposed = [str(x).strip() for x in parsed if str(x).strip()]
    except Exception:
        import re as _re
        for line in reply.splitlines():
            m = _re.match(r"^\s*(?:[-*]|\d+[.)])\s+(.+?)\s*$", line)
            if m:
                proposed.append(m.group(1).strip())

    if not proposed:
        return {"ok": False, "error": "AI returned no usable steps", "raw_reply": reply[:400]}

    existing_lc = {s.lower() for s in existing}
    added: list = []
    for step in proposed:
        if step.lower() in existing_lc:
            continue
        res = add_step(step, target)
        if res.get("ok"):
            added.append(step)
            existing_lc.add(step.lower())

    return {
        "ok": True,
        "plan": target,
        "added": added,
        "added_count": len(added),
        "proposed_count": len(proposed),
        "plan_after": read(target),
    }


def archive(name: str = "") -> dict:
    """Move a plan to plan/done/ and clear the current pointer if it
    was pointing at this plan. A no-op + warning if it's already
    archived."""
    name = name or current_name()
    if not name:
        return {"ok": False, "error": "No current plan and no name given"}
    if not name.endswith(".md"):
        name += ".md"
    src = _plan_dir() / name
    if not src.exists():
        return {"ok": False, "error": f"No such plan: {name}"}
    dest = _archive_dir() / name
    # Handle name collisions — prefix with timestamp on conflict
    if dest.exists():
        dest = _archive_dir() / f"{int(time.time())}-{name}"
    src.rename(dest)
    if current_name() == name:
        clear_current()
    return {"ok": True, "archived_to": str(dest.relative_to(_project_root()))}
