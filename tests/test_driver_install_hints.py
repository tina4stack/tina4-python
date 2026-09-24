# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""A missing optional driver names the package AND the exact install command.

The standard (tina4-nodejs#67, all four frameworks):

    The 'X' package is required for FEATURE. Install it with: <command>

THE BUGS, MEASURED on v3 (13464d4):

  * ``S3Storage()`` did a bare ``import boto3``. With boto3 absent the user got
    CPython's "No module named 'boto3'" and nothing saying how to fix it, and
    ``select_storage()``'s fallback warning repeated that bare text.
  * The mongodb cache fell back to 'file' with "(driver missing or service
    unreachable)" - the same words whether pymongo was missing or Mongo was
    down, so the one case the user can fix with one command never said so.

HOW THE PACKAGE IS MADE GENUINELY UNAVAILABLE, WITHOUT ANY DOUBLE - the same
instrument as tests/test_session_zero_dependency_fallback.py: a REAL child
Python started with ``-S`` (the ``site`` module never runs, so no site-packages,
no user site, no .pth file is on sys.path), every PYTHON* variable dropped and
PYTHONPATH set to the repository root alone. ``import boto3`` / ``import
pymongo`` are the real import statements and the ImportError is the one CPython
really raises. Each child SELF-REPORTS that the package really is unimportable;
every test asserts that first, so a child that quietly inherited the venv cannot
pass while measuring nothing.

NEGATIVE CONTROL: with pymongo PRESENT (an ordinary child, the lab venv has it)
and Mongo UNREACHABLE (a real closed port), the fallback still happens but the
install hint must NOT be appended - the driver is not the problem there.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
REPORT_MARKER = "TINA4_REPORT "

BOTO3_HINT = (
    "The 'boto3' package is required for S3Storage. "
    "Install it with: uv add boto3 (or: pip install boto3)"
)
PYMONGO_HINT = (
    "The 'pymongo' package is required for the mongodb cache backend. "
    "Install it with: uv add pymongo (or: pip install pymongo)"
)

_INSTRUMENT = '''
import json
import sys


def _unavailable(name):
    try:
        __import__(name)
        return False
    except ImportError:
        return True


instrument = {
    "boto3_gone": _unavailable("boto3"),
    "pymongo_gone": _unavailable("pymongo"),
    "site_package_paths": len([p for p in sys.path if "site-packages" in p or "dist-packages" in p]),
}
import tina4_python
instrument["framework_file"] = tina4_python.__file__
'''


def _run_child(source: str, *, without_packages: bool, extra_environment: dict | None = None) -> tuple[dict, str]:
    """Run `source` in a real child Python and return (report, stdout+stderr).

    `without_packages=True` starts it with -S so no third-party package can be
    resolved; False starts it normally (the venv's packages are importable).
    The child runs in a fresh temp directory so any data/ or logs/ it creates
    lands there.
    """
    with tempfile.TemporaryDirectory(prefix="tina4-driver-hint-") as sandbox:
        environment = {key: value for key, value in os.environ.items() if not key.startswith("PYTHON")}
        environment.update({
            "PYTHONPATH": str(REPOSITORY_ROOT),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "TINA4_DEBUG": "false",
            "TINA4_LOG_LEVEL": "WARNING",
        })
        environment.update(extra_environment or {})
        command = [sys.executable] + (["-S"] if without_packages else []) + ["-c", _INSTRUMENT + source]
        completed = subprocess.run(command, cwd=sandbox, env=environment,
                                   capture_output=True, text=True, timeout=120)
    output = completed.stdout + completed.stderr
    for line in completed.stdout.splitlines():
        if line.startswith(REPORT_MARKER):
            return json.loads(line[len(REPORT_MARKER):]), output
    raise AssertionError(f"child reported nothing (exit {completed.returncode}):\n{output}")


def _assert_really_without(report: dict, package: str) -> None:
    instrument = report["instrument"]
    assert instrument[f"{package}_gone"] is True, (
        f"the child could still import {package}, so it measured nothing: {instrument}"
    )
    assert instrument["site_package_paths"] == 0, instrument
    assert instrument["framework_file"].startswith(str(REPOSITORY_ROOT)), instrument


def _closed_port() -> int:
    """A real TCP port on 127.0.0.1 that nothing is listening on."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


# ── S3Storage without boto3 ─────────────────────────────────────────


def test_s3_storage_without_boto3_names_the_package_and_the_command():
    report, output = _run_child('''
from tina4_python.realtime.storage import S3Storage
try:
    S3Storage(bucket="any-bucket")
    outcome = {"raised": None}
except ImportError as exc:
    outcome = {"raised": type(exc).__name__, "message": str(exc)}
print("TINA4_REPORT " + json.dumps({"instrument": instrument, "outcome": outcome}))
''', without_packages=True)

    _assert_really_without(report, "boto3")
    assert report["outcome"]["raised"] in ("ImportError", "ModuleNotFoundError"), report
    assert report["outcome"]["message"] == BOTO3_HINT, report


def test_select_storage_without_boto3_falls_back_and_warns_with_the_command():
    report, output = _run_child('''
from tina4_python.realtime.storage import LocalStorage, select_storage
store = select_storage()
print("TINA4_REPORT " + json.dumps({"instrument": instrument, "local": isinstance(store, LocalStorage)}))
''', without_packages=True, extra_environment={"TINA4_STORAGE_BACKEND": "s3", "TINA4_STORAGE_BUCKET": "any-bucket"})

    _assert_really_without(report, "boto3")
    assert report["local"] is True, output
    assert "falling back to local filesystem storage" in output, output
    assert BOTO3_HINT in output, output


# ── mongodb cache without pymongo ───────────────────────────────────


_MONGO_CACHE_CHILD = '''
import os
from tina4_python.cache import _create_backend
backend = _create_backend(backend="mongodb", url=os.environ["HINT_TEST_MONGO_URL"])
print("TINA4_REPORT " + json.dumps({"instrument": instrument, "backend": backend.name()}))
'''


def test_mongodb_cache_without_pymongo_warns_with_the_install_command():
    # The URL is never dialled: without pymongo the backend cannot even try.
    report, output = _run_child(_MONGO_CACHE_CHILD, without_packages=True,
                                extra_environment={"HINT_TEST_MONGO_URL": f"mongodb://127.0.0.1:{_closed_port()}"})

    _assert_really_without(report, "pymongo")
    assert report["backend"] == "file", output
    assert "Cache backend 'mongodb' is unavailable" in output, output
    assert PYMONGO_HINT in output, output


def test_mongodb_cache_with_pymongo_but_no_server_does_not_blame_the_driver():
    """NEGATIVE CONTROL: pymongo is installed, Mongo is unreachable. The fallback
    happens, but the install hint would be a lie here and must not appear."""
    pytest.importorskip("pymongo", reason="pymongo not installed (uv sync --extra test)")
    report, output = _run_child(_MONGO_CACHE_CHILD, without_packages=False,
                                extra_environment={"HINT_TEST_MONGO_URL": f"mongodb://127.0.0.1:{_closed_port()}"})

    assert report["instrument"]["pymongo_gone"] is False, report
    assert report["backend"] == "file", output
    assert "Cache backend 'mongodb' is unavailable" in output, output
    assert "is required for the mongodb cache backend" not in output, output
