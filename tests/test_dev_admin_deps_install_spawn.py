# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""POST /__dev/api/deps/install reaches the REAL package manager, safely.

Two Windows defects, both in how the endpoint spawned ``npm`` / ``composer`` /
``bundle`` / ``gem``:

1. Not found. Those tools are batch files on Windows (``npm.cmd``,
   ``composer.bat``), and a bare name spawned without a shell only ever
   resolves to ``.exe``, so every npm/packagist/rubygems install answered
   "Package manager not found".
2. Injection, the moment (1) is fixed naively. cmd.exe re-parses a batch file's
   command line, and the package name and version come straight from the
   request body, so ``left-pad&echo pwned>file`` would run the second command.

The package manager here is a genuine program named ``npm`` on PATH (a batch
file on Windows, a shell script elsewhere) that records the argv it received,
not a stand-in object: the endpoint does its real PATH lookup and real spawn.
Mutation proof: spawn with ``subprocess.run(cmd)`` again and, on Windows, the
install fails with "Package manager not found" (and with only the lookup fixed,
the injected marker file appears).
"""

import json
import os
import sys

import pytest

from test_dev_admin_conformance import _dispatch


def _install_recording_npm(bindir, record):
    """A real ``npm`` on PATH that appends each argument to ``record``."""
    bindir.mkdir()
    if sys.platform == "win32":
        recorder = bindir / "record_npm.py"
        recorder.write_text(
            "import sys\n"
            f"with open({str(record)!r}, 'a') as fh:\n"
            "    fh.writelines(arg + '\\n' for arg in sys.argv[1:])\n"
        )
        (bindir / "npm.cmd").write_text(f'@"{sys.executable}" "{recorder}" %*\r\n')
    else:
        script = bindir / "npm"
        script.write_text(f'#!/bin/sh\nfor arg in "$@"; do printf "%s\\n" "$arg" >> "{record}"; done\n')
        script.chmod(0o755)


@pytest.fixture
def project_with_npm(tmp_path, monkeypatch):
    (tmp_path / "src" / "routes").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TINA4_DEBUG", "true")
    record = tmp_path / "npm_argv.txt"
    bindir = tmp_path / "bin"
    _install_recording_npm(bindir, record)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    return tmp_path, record


def _install(name, version=""):
    return _dispatch(
        "POST", "/__dev/api/deps/install",
        headers={"sec-fetch-site": "same-origin"},
        json={"registry": "npm", "name": name, "version": version},
    )


def test_an_npm_install_reaches_the_real_package_manager(project_with_npm):
    _, record = project_with_npm
    status, body, _ = _install("left-pad")
    assert status == 200, body
    assert record.read_text().splitlines() == ["install", "left-pad"]


def test_a_hostile_package_name_reaches_npm_verbatim_and_runs_nothing(project_with_npm):
    project, record = project_with_npm
    # No spaces on purpose: CPython quotes an argument only when it holds a
    # space or tab, so an unquoted `&` / `|` is exactly what cmd.exe acts on.
    # `cd.>file` creates a file without needing a space.
    name = "left-pad&cd.>pwned_by_name"
    version = "1.0|cd.>pwned_by_version"

    status, body, _ = _install(name, version)

    assert status == 200, body
    assert record.read_text().splitlines() == ["install", f"{name}@{version}"]
    assert not (project / "pwned_by_name").exists(), "the package name ran a second command"
    assert not (project / "pwned_by_version").exists(), "the version ran a second command"
    assert json.loads(body)["message"].startswith("Installed")
