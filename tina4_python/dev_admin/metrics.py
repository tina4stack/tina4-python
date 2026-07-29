# Tina4 Code Metrics — one engine, per ADR-0002.
"""
Two tiers, two different jobs:

  1. Quick metrics (instant): a FILE CENSUS. Line, file and template counts by
     glob. No code is parsed. It stays in-process because the dashboard calls it
     on every load and the native engine takes ~1s on a 100-file tree.
  2. Full analysis, offenders and per-file detail: the NATIVE ENGINE
     (`tina4 metrics --json`). One tree-sitter implementation covering every
     language, so a number measured in Python is comparable with the same number
     measured in PHP, Ruby or Node.

The hand-rolled AST analyzer that used to live here is GONE (672 lines). It
duplicated the engine and, because each framework had its own, the four
frameworks reported numbers that could not be compared - which silently
undermined every cross-framework comparison built on them.

There is NO FALLBACK. A missing or broken CLI RAISES MetricsEngineError naming
the fix. Degrading to a second implementation is what produced incomparable
numbers in the first place; a loud failure is honest where a quiet substitution
is not.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path


# ── Scan root tracking ────────────────────────────────────────
# Stores the resolved root so file_detail() can locate framework files.
_last_scan_root: str = ""


# ── Quick Metrics ──────────────────────────────────────────────


def _is_code_line(line: str) -> bool:
    """True for a line that counts toward LOC: not blank, not a comment.

    The single definition of the rule. It used to be restated at each file-level
    call site while function LOC ignored it entirely and returned a raw line
    span, so `loc` meant two different things in one payload - see
    _function_loc.
    """
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def _resolve_root(root: str = "src") -> str:
    """Pick the right directory to scan.

    If src/ has Python files, scan the user's project code.
    Otherwise, scan the framework itself — so the bubble chart is never empty.
    """
    global _last_scan_root
    src = Path(root)
    if src.exists() and list(src.rglob("*.py")):
        _last_scan_root = str(Path(root).resolve())
        return root
    # Fallback: scan the framework package
    import tina4_python
    framework_dir = str(Path(tina4_python.__file__).parent)
    _last_scan_root = framework_dir
    return framework_dir


def resolve_scan_target(root: str = "src") -> tuple[str, str]:
    """Return (directory to scan, scan_mode) for any metrics producer.

    The CLI engine is language-agnostic and cannot know which directory holds a
    framework package, so root resolution and the "framework" label stay here -
    shared by this module and the engine adapter so the two never disagree about
    what was measured.
    """
    resolved = _resolve_root(root)
    framework_dir = str(Path(__import__("tina4_python").__file__).parent)
    resolved_path = Path(resolved)
    scanning_framework = (
        resolved_path == Path(framework_dir) or str(resolved_path).startswith(framework_dir)
    )
    return resolved, "framework" if scanning_framework else "project"


def quick_metrics(root: str = "src") -> dict:
    """Scan project files and return instant metrics."""
    root = _resolve_root(root)
    root_path = Path(root)
    if not root_path.exists():
        return {"error": f"Directory not found: {root}"}

    py_files = list(root_path.rglob("*.py"))
    twig_files = list(root_path.rglob("*.twig")) + list(root_path.rglob("*.html"))
    sql_files = list(Path("migrations").rglob("*.sql")) if Path("migrations").exists() else []
    scss_files = list(root_path.rglob("*.scss")) + list(root_path.rglob("*.css"))

    total_loc = 0
    total_blank = 0
    total_comment = 0
    total_classes = 0
    total_functions = 0
    file_details = []

    for f in py_files:
        try:
            source = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        lines = source.splitlines()
        loc = 0
        blank = 0
        comment = 0
        in_docstring = False
        docstring_char = None

        for line in lines:
            stripped = line.strip()
            if not stripped:
                blank += 1
                continue

            # Docstring detection (triple quotes)
            if in_docstring:
                comment += 1
                if docstring_char in stripped:
                    in_docstring = False
                continue

            if stripped.startswith('"""') or stripped.startswith("'''"):
                comment += 1
                quote = stripped[:3]
                # Single-line docstring
                if stripped.count(quote) >= 2:
                    continue
                in_docstring = True
                docstring_char = quote
                continue

            if stripped.startswith("#"):
                comment += 1
                continue

            loc += 1

        # Count classes and functions via simple pattern matching
        classes = sum(1 for l in lines if l.strip().startswith("class ") and ":" in l)
        functions = sum(1 for l in lines if l.strip().startswith("def ") and ":" in l)

        total_loc += loc
        total_blank += blank
        total_comment += comment
        total_classes += classes
        total_functions += functions

        file_details.append({
            "path": str(f.relative_to(root_path)).replace("\\", "/"),
            "loc": loc,
            "blank": blank,
            "comment": comment,
            "classes": classes,
            "functions": functions,
        })

    # Sort by LOC descending
    file_details.sort(key=lambda x: x["loc"], reverse=True)

    # Route and ORM counts
    route_count = 0
    orm_count = 0
    try:
        from tina4_python.core.router import Router
        route_count = len(Router.get_routes())
    except Exception:
        pass
    try:
        from tina4_python.orm.model import ORM
        orm_count = len(ORM.__subclasses__())
    except Exception:
        pass

    # File type breakdown
    breakdown = {
        "python": len(py_files),
        "templates": len(twig_files),
        "migrations": len(sql_files),
        "stylesheets": len(scss_files),
    }

    return {
        "file_count": len(py_files),
        "total_loc": total_loc,
        "total_blank": total_blank,
        "total_comment": total_comment,
        "lloc": total_loc,
        "classes": total_classes,
        "functions": total_functions,
        "route_count": route_count,
        "orm_count": orm_count,
        "template_count": len(twig_files),
        "migration_count": len(sql_files),
        "avg_file_size": round(total_loc / len(py_files), 1) if py_files else 0,
        "largest_files": file_details[:10],
        "breakdown": breakdown,
    }


# ── The native engine (ADR-0002) ──────────────────────────────


class MetricsEngineError(RuntimeError):
    """The native metrics engine could not produce a payload.

    Raised instead of falling back to a second implementation: two engines is
    exactly the condition that made the four frameworks' numbers incomparable.
    """


_TIMEOUT_SECONDS = 60

_INSTALL_HINT = (
    "the tina4 CLI provides the metrics engine (ADR-0002). Install it with\n"
    "  curl -fsSL https://tina4.com/install.sh | sh\n"
    "or see https://tina4.com/cli"
)

# Fields the dashboard renders. Checking for the DATA is honest where checking a
# version string is not: a user may run any CLI build, and the payload is what
# tells us what that build can actually do.
_SUMMARY_KEYS = ("files_analyzed", "total_functions", "avg_complexity", "avg_maintainability")
_FILE_KEYS = ("path", "loc", "avg_complexity", "maintainability", "has_tests")
_FUNCTION_KEYS = ("name", "file", "line", "complexity", "loc")


def engine_path() -> str | None:
    """Absolute path to the tina4 CLI binary, or None when it is not installed."""
    return shutil.which("tina4")


def _run_engine(path: str) -> dict:
    """Run `tina4 metrics --json` over path and return the raw payload.

    Raises MetricsEngineError with the actual cause: a caller that cannot get
    metrics needs to know whether the binary is missing, the run failed, or the
    output was unreadable.
    """
    binary = engine_path()
    if binary is None:
        raise MetricsEngineError(f"tina4 not found on PATH - {_INSTALL_HINT}")

    try:
        proc = subprocess.run(
            [binary, "metrics", "--path", str(path), "--json"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise MetricsEngineError(
            f"tina4 metrics timed out after {_TIMEOUT_SECONDS}s on {path}"
        ) from exc
    except OSError as exc:
        raise MetricsEngineError(f"could not run {binary}: {exc}") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        first = detail[0] if detail else f"exit code {proc.returncode}"
        raise MetricsEngineError(f"tina4 metrics failed on {path}: {first}")

    if not proc.stdout.strip():
        raise MetricsEngineError(f"tina4 metrics produced no output for {path}")

    try:
        payload = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        raise MetricsEngineError(f"tina4 metrics returned unreadable JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise MetricsEngineError("tina4 metrics returned a non-object payload")
    return payload


def _require(payload: dict, key: str, kind: type):
    """Pull a key out of the payload or raise naming what the engine is missing."""
    value = payload.get(key)
    if not isinstance(value, kind):
        raise MetricsEngineError(
            f"engine payload has no usable '{key}' - the installed tina4 CLI predates "
            f"a field the dashboard renders. Update it: {_INSTALL_HINT}"
        )
    return value


def full_analysis(root: str = "src") -> dict:
    """Full code analysis from the native engine, shaped for the dashboard."""
    resolved, scan_mode = resolve_scan_target(root)
    payload = _run_engine(resolved)

    summary = _require(payload, "summary", dict)
    file_metrics = _require(payload, "file_metrics", list)
    functions = _require(payload, "most_complex_functions", list)

    missing = [k for k in _SUMMARY_KEYS if k not in summary]
    if missing:
        raise MetricsEngineError(
            f"engine summary is missing {', '.join(missing)} - update the CLI: {_INSTALL_HINT}"
        )
    if file_metrics and (absent := [k for k in _FILE_KEYS if k not in file_metrics[0]]):
        raise MetricsEngineError(f"engine file_metrics is missing {', '.join(absent)}")
    if functions and (absent := [k for k in _FUNCTION_KEYS if k not in functions[0]]):
        raise MetricsEngineError(f"engine function metrics are missing {', '.join(absent)}")

    result = {key: summary[key] for key in _SUMMARY_KEYS}
    result["file_metrics"] = file_metrics
    # Display cap only. offenders() reads the engine's own uncapped list, so a
    # 16th over-threshold function is never hidden from the gate.
    result["most_complex_functions"] = functions[:15]
    result["dependency_graph"] = payload.get("dependency_graph") or {}
    # The framework owns these two: the engine always reports "project" because
    # it cannot know which directory is a framework package.
    result["scan_mode"] = scan_mode
    result["scan_root"] = str(Path(resolved).resolve())
    result["engine"] = "tina4-cli"
    return result


def offenders(root: str = "src", top: int = 20) -> dict:
    """Top code-health offenders from the native engine.

    The engine ranks and severity-tags them, and its own --fail-on gate reads
    the same list, so the CLI and the dashboard can never disagree about what
    counts as an offender.
    """
    resolved, scan_mode = resolve_scan_target(root)
    payload = _run_engine(resolved)

    found = _require(payload, "offenders", list)
    summary = dict(_require(payload, "summary", dict))
    summary["scan_mode"] = scan_mode
    summary["scan_root"] = str(Path(resolved).resolve())
    summary["engine"] = "tina4-cli"
    summary.setdefault("total_offenders", len(found))
    return {"offenders": found[:top], "summary": summary}


def file_detail(file_path: str) -> dict:
    """Per-file metrics from the native engine.

    The engine accepts a single file for --path, so one code path serves both
    the whole-tree scan and one file.
    """
    if not file_path:
        raise MetricsEngineError("file_detail needs a path")

    target = Path(file_path)
    if not target.exists():
        # Try it relative to whatever quick_metrics last resolved, so the
        # dashboard can pass a path taken straight out of file_metrics.
        if _last_scan_root:
            candidate = Path(_last_scan_root) / file_path
            if candidate.exists():
                target = candidate
    if not target.exists():
        raise MetricsEngineError(f"no such file: {file_path}")
    if target.is_dir():
        raise MetricsEngineError(f"not a file: {file_path}")

    payload = _run_engine(str(target))
    file_metrics = _require(payload, "file_metrics", list)
    if not file_metrics:
        raise MetricsEngineError(f"engine reported no metrics for {file_path}")

    detail = dict(file_metrics[0])
    detail["engine"] = "tina4-cli"
    return detail
