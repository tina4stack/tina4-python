"""Code metrics from the tina4 CLI engine (ADR-0002).

The metrics engine now lives in the Rust CLI: one tree-sitter implementation
covering every language, instead of a hand-rolled AST walker per framework. This
adapter shells out to it and reshapes the payload into the dashboard's contract.

It returns None whenever the CLI cannot supply a COMPLETE payload - no binary on
PATH, a non-zero exit, unparseable JSON, or an older CLI whose engine predates a
field the dashboard renders. The caller then falls back to the in-framework
module, so a stale CLI degrades quietly instead of blanking the chart.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

# The dashboard reads these at the top level; the CLI nests them under "summary"
# because its own text report and the --fail-on gate group them there.
_SUMMARY_KEYS = (
    "files_analyzed",
    "total_functions",
    "avg_complexity",
    "avg_maintainability",
)

# Fields the dashboard renders that a pre-3.8.59 engine does not emit. Checking
# for the DATA is honest where checking a version string is not: a user may run
# any CLI build, and the payload tells us what it can actually do.
_REQUIRED_FILE_KEYS = ("path", "loc", "avg_complexity", "maintainability", "has_tests")
_REQUIRED_FUNCTION_KEYS = ("name", "file", "line", "complexity", "loc")

_TIMEOUT_SECONDS = 60


def engine_path() -> str | None:
    """Absolute path to the tina4 CLI binary, or None when it is not installed."""
    return shutil.which("tina4")


def engine_analysis(root: str, scan_mode: str = "project") -> dict | None:
    """Run `tina4 metrics --json` over root and adapt it to the dashboard shape.

    The framework passes --path and owns scan_mode: it knows where its own
    package lives, and the engine is deliberately language-agnostic, so root
    resolution stays on this side of the boundary.
    """
    binary = engine_path()
    if binary is None:
        return None

    try:
        proc = subprocess.run(
            [binary, "metrics", "--path", str(root), "--json"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if proc.returncode != 0 or not proc.stdout.strip():
        return None

    try:
        payload = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return None

    return adapt_payload(payload, root, scan_mode)


def adapt_payload(payload: dict, root: str, scan_mode: str = "project") -> dict | None:
    """Flatten the engine payload into the dashboard contract, or None if short.

    Split out from engine_analysis so the reshaping is testable without a
    subprocess - the shaping is where the contract actually lives.
    """
    if not isinstance(payload, dict):
        return None

    summary = payload.get("summary")
    file_metrics = payload.get("file_metrics")
    functions = payload.get("most_complex_functions")
    if not isinstance(summary, dict) or not isinstance(file_metrics, list):
        return None
    if not isinstance(functions, list):
        return None

    if any(key not in summary for key in _SUMMARY_KEYS):
        return None
    if file_metrics and any(key not in file_metrics[0] for key in _REQUIRED_FILE_KEYS):
        return None
    if functions and any(key not in functions[0] for key in _REQUIRED_FUNCTION_KEYS):
        return None

    result = {key: summary[key] for key in _SUMMARY_KEYS}
    result["file_metrics"] = file_metrics
    result["most_complex_functions"] = functions[:15]
    result["dependency_graph"] = payload.get("dependency_graph") or {}
    # The framework decides these two - the engine always reports "project"
    # because it cannot know which directory is a framework package.
    result["scan_mode"] = scan_mode
    result["scan_root"] = str(Path(root).resolve())
    result["engine"] = "tina4-cli"
    return result
