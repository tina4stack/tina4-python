"""Thin dev-admin adapter for the native ``tina4 metrics`` engine (ADR-0054)."""

import json
import shutil
import subprocess
from pathlib import Path


class MetricsEngineError(RuntimeError):
    """The native CLI could not provide a usable metrics payload."""


_TIMEOUT_SECONDS = 60
_SUMMARY_KEYS = ("files_analyzed", "total_functions", "avg_complexity", "avg_maintainability")
_FILE_KEYS = ("path", "loc", "avg_complexity", "maintainability", "has_referencing_test")
_FUNCTION_KEYS = ("name", "file", "line", "complexity", "loc")
_INSTALL_HINT = "update the native tina4 CLI: https://tina4.com/cli"
_last_scan_root = ""


def _resolve_target(root: str = "src") -> tuple[str, str]:
    global _last_scan_root
    source = Path(root)
    if source.exists() and any(source.rglob("*.py")):
        resolved = source.resolve()
        mode = "project"
    else:
        import tina4_python
        resolved = Path(tina4_python.__file__).parent.resolve()
        mode = "framework"
    _last_scan_root = str(resolved)
    return str(resolved), mode


def _run(path: str) -> dict:
    binary = shutil.which("tina4")
    if binary is None:
        raise MetricsEngineError(f"tina4 not found on PATH - {_INSTALL_HINT}")
    try:
        process = subprocess.run(
            [binary, "metrics", "--path", path, "--json"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise MetricsEngineError(f"tina4 metrics timed out after {_TIMEOUT_SECONDS}s on {path}") from error
    except OSError as error:
        raise MetricsEngineError(f"could not run {binary}: {error}") from error
    if process.returncode != 0:
        lines = (process.stderr or process.stdout or "").strip().splitlines()
        raise MetricsEngineError(f"tina4 metrics failed on {path}: {lines[0] if lines else process.returncode}")
    try:
        payload = json.loads(process.stdout)
    except (json.JSONDecodeError, ValueError) as error:
        raise MetricsEngineError(f"tina4 metrics returned unreadable JSON: {error}") from error
    if not isinstance(payload, dict):
        raise MetricsEngineError("tina4 metrics returned a non-object payload")
    return payload


def _array(payload: dict, key: str) -> list:
    value = payload.get(key)
    if not isinstance(value, list):
        raise MetricsEngineError(f"engine payload has no usable '{key}' - {_INSTALL_HINT}")
    return value


def full_analysis(root: str = "src") -> dict:
    """Return native metrics shaped for the existing dev-admin chart."""
    resolved, scan_mode = _resolve_target(root)
    payload = _run(resolved)
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise MetricsEngineError(f"engine payload has no usable 'summary' - {_INSTALL_HINT}")
    missing = [key for key in _SUMMARY_KEYS if key not in summary]
    if missing:
        raise MetricsEngineError(f"engine summary is missing {', '.join(missing)} - {_INSTALL_HINT}")
    files = _array(payload, "file_metrics")
    functions = _array(payload, "most_complex_functions")
    if files and (missing := [key for key in _FILE_KEYS if key not in files[0]]):
        raise MetricsEngineError(f"engine file_metrics is missing {', '.join(missing)}")
    if functions and (missing := [key for key in _FUNCTION_KEYS if key not in functions[0]]):
        raise MetricsEngineError(f"engine function metrics are missing {', '.join(missing)}")
    result = {key: summary[key] for key in _SUMMARY_KEYS}
    result.update({
        "file_metrics": files,
        "most_complex_functions": functions[:15],
        "dependency_graph": payload.get("dependency_graph") or {},
        "scan_mode": scan_mode,
        "scan_root": resolved,
        "engine": "tina4-cli",
    })
    return result


def file_detail(file_path: str) -> dict:
    """Return one file's native metrics for the dev-admin detail panel."""
    if not file_path:
        raise MetricsEngineError("file_detail needs a path")
    target = Path(file_path)
    if not target.exists() and _last_scan_root:
        target = Path(_last_scan_root) / file_path
    if not target.exists():
        raise MetricsEngineError(f"no such file: {file_path}")
    if target.is_dir():
        raise MetricsEngineError(f"not a file: {file_path}")
    payload = _run(str(target))
    files = _array(payload, "file_metrics")
    if not files:
        raise MetricsEngineError(f"engine reported no metrics for {file_path}")
    functions = _array(payload, "most_complex_functions")
    return {
        **files[0],
        "function_count": files[0].get("functions", 0),
        "functions": functions,
        "engine": "tina4-cli",
    }
