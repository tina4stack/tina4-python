# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Real tests for scripts/check-no-symlinks.sh.

A committed symbolic link breaks Windows extraction: 7-Zip (and therefore
Composer on Windows) refuses "dangerous link paths", so a leaked symlink in the
tree fails every Windows install. The sibling tina4-php repo shipped 134 of them
by accident. This guard rejects any file recorded in git with mode 120000, and
these tests prove it -- positive and negative -- against a REAL git repo on disk,
no mocks.

The negative case is mutation-proof: it builds a real temporary git repository,
stages an actual symlink (git records it as mode 120000), runs the real script
there, and asserts the script FAILS and names the offending path. If the guard
ever stops detecting committed symlinks this test goes red.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check-no-symlinks.sh"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60,
    )


def _run_guard(cwd: Path) -> subprocess.CompletedProcess:
    """Invoke the real guard script in a real subprocess, from ``cwd``."""
    return subprocess.run(
        ["sh", str(SCRIPT)], cwd=cwd, capture_output=True, text=True, timeout=60,
    )


def test_guard_passes_against_the_real_checkout():
    """The script exits 0 on this repo, which carries zero committed symlinks."""
    result = _run_guard(ROOT)
    assert result.returncode == 0, (
        f"guard failed on the real checkout\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "OK: no committed symlinks" in result.stdout


@pytest.mark.skipif(
    not hasattr(__import__("os"), "symlink"),
    reason="[needs:symlink-support] platform cannot create symbolic links",
)
def test_guard_fails_when_a_symlink_is_committed(tmp_path):
    """Mutation proof: stage a REAL symlink in a REAL temp git repo and assert
    the guard detects it, exits non-zero, and names the offending path."""
    if shutil.which("git") is None:
        pytest.skip("[needs:git] git binary not on PATH")

    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init").returncode == 0
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "core.symlinks", "true")

    # A normal file, so the repo is not empty and the guard has something to skip.
    (repo / "real.txt").write_text("not a link\n", encoding="utf-8")

    # The actual offender: a symbolic link, staged so git records mode 120000.
    link = repo / "conf.d"
    try:
        link.symlink_to("/etc/nginx/conf.d")
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform gate
        pytest.skip(f"[needs:symlink-support] cannot create symlink: {exc}")

    assert _git(repo, "add", "-A").returncode == 0

    # Sanity: git must have recorded the link with mode 120000, or the test would
    # pass for the wrong reason (a ghost test).
    staged = _git(repo, "ls-files", "-s").stdout
    assert "120000" in staged and "conf.d" in staged, (
        f"symlink was not staged as mode 120000; git recorded:\n{staged}"
    )

    result = _run_guard(repo)
    assert result.returncode != 0, (
        "guard passed although a committed symlink is present\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "conf.d" in result.stderr, (
        f"guard did not name the offending symlink path:\n{result.stderr}"
    )
    assert "OK: no committed symlinks" not in result.stdout
