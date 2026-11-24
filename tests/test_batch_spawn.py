# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""tina4_python.core.batch_spawn: the pure parts, on every OS.

The end-to-end proofs (a real tina4.cmd / npm.cmd receiving hostile arguments
verbatim, nothing injected) live in test_cli_delegated_commands.py and
test_dev_admin_deps_install_spawn.py and need Windows. These pin the escaping
itself, so a change to it fails on Linux CI too. The expected strings are the
ones tina4-nodejs escapeBatchArgument() produces for the same inputs.
"""

import os

import pytest

from tina4_python.core.batch_spawn import (
    batch_command_line,
    escape_batch_argument,
    find_executable,
    is_batch_file,
)


@pytest.mark.parametrize("arg, expected", [
    ("plain", '^^^"plain^^^"'),
    ("", '^^^"^^^"'),
    ("a&b", '^^^"a^^^&b^^^"'),
    ("x|y", '^^^"x^^^|y^^^"'),
    ("100%PATH%", '^^^"100^^^%PATH^^^%^^^"'),
    ("a^b", '^^^"a^^^^b^^^"'),
    ('say "hi"', '^^^"say^^^ \\^^^"hi\\^^^"^^^"'),
    ("tail\\", '^^^"tail\\\\^^^"'),
    ('a\\"b', '^^^"a\\\\\\^^^"b^^^"'),
])
def test_each_argument_is_quoted_and_caret_escaped_twice(arg, expected):
    assert escape_batch_argument(arg) == expected


def test_the_command_line_runs_the_batch_file_through_cmd_with_s_and_d(monkeypatch):
    monkeypatch.setenv("COMSPEC", r"C:\Windows\system32\cmd.exe")
    line = batch_command_line(r"C:\tools\tina4.cmd", ["deploy", "a&b"])
    assert line == (
        '"C:\\Windows\\system32\\cmd.exe" /d /s /c '
        '"C:\\tools\\tina4.cmd ^^^"deploy^^^" ^^^"a^^^&b^^^""'
    )


@pytest.mark.parametrize("path, platform, expected", [
    (r"C:\tools\tina4.cmd", "win32", True),
    (r"C:\tools\TINA4.BAT", "win32", True),
    (r"C:\tools\tina4.exe", "win32", False),
    ("/usr/local/bin/tina4.cmd", "linux", False),
])
def test_only_a_windows_batch_file_is_treated_as_one(path, platform, expected):
    assert is_batch_file(path, platform) is expected


def test_find_executable_leaves_every_non_windows_name_alone():
    assert find_executable("npm", platform="linux") == "npm"


def test_find_executable_resolves_a_bare_name_with_pathext(tmp_path, monkeypatch):
    (tmp_path / "npm.cmd").write_text("@echo off\r\n")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    assert find_executable("npm", platform="win32") == os.path.join(str(tmp_path), "npm.cmd")
    # A name with an extension or a directory is never rewritten.
    assert find_executable("npm.cmd", platform="win32") == "npm.cmd"
    assert find_executable(str(tmp_path / "npm"), platform="win32") == str(tmp_path / "npm")
    # Not found: unchanged, so the spawn reports its own error.
    assert find_executable("not-a-tool", platform="win32") == "not-a-tool"
