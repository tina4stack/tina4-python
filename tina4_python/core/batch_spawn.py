# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Run a program that may be a Windows batch file (``.cmd`` / ``.bat``).

Two things go wrong with batch files on Windows when a program is spawned with
an argument list, and Tina4 hit both:

* A bare name is never found. Without a shell, CreateProcess only appends
  ``.exe``, so ``npm`` (really ``npm.cmd``), ``composer.bat``, ``bundle.bat`` and
  ``gem.cmd`` fail with FileNotFoundError. :func:`find_executable` resolves the
  name with PATHEXT, the way cmd.exe does.
* A batch file is always run by cmd.exe, which re-parses the command line.
  CPython quotes arguments for the C runtime (``list2cmdline``), not for cmd.exe,
  so an argument holding ``%PATH%`` is expanded, ``^`` vanishes, and ``x|y`` runs
  ``y`` as a command (the BatBadBut class, CVE-2024-24576; CPython documents it
  and leaves it to the caller). :func:`run_allowing_batch` builds the cmd.exe
  line itself instead, the way cross-spawn does (https://qntm.org/cmd): each
  argument quoted, embedded quotes and the backslashes before them escaped, and
  every cmd.exe metacharacter caret-escaped TWICE, once for the ``cmd /c`` line
  and once more because a batch file re-parses the ``%*`` it forwards.

This is the same algorithm as tina4-nodejs ``packages/core/src/batchSpawn.ts``.
Anything that is not a batch file, and every non-Windows platform, is spawned
exactly as before.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

# cmd.exe metacharacters, the same set cross-spawn (and tina4-nodejs) escapes.
_CMD_META = re.compile(r'([()\][%!^"`<>&|;, *?])')


def is_batch_file(path: str, platform: str | None = None) -> bool:
    """True when ``path`` is a batch file cmd.exe must run (Windows only)."""
    return (platform or sys.platform) == "win32" and path.lower().endswith((".cmd", ".bat"))


def escape_batch_argument(arg: str) -> str:
    """One argument, quoted and escaped for a batch file run by ``cmd /d /s /c``."""
    # Backslashes before a quote double, and the quote is backslash-escaped;
    # backslashes before the closing quote we are about to add double too.
    quoted = re.sub(r'(\\*)"', r'\1\1\\"', str(arg))
    quoted = re.sub(r"(\\*)$", r"\1\1", quoted)
    quoted = f'"{quoted}"'
    return _CMD_META.sub(r"^\1", _CMD_META.sub(r"^\1", quoted))


def batch_command_line(path: str, args) -> str:
    """The full ``cmd.exe /d /s /c "..."`` line that runs batch file ``path``."""
    line = " ".join([_CMD_META.sub(r"^\1", path), *(escape_batch_argument(a) for a in args)])
    shell = os.environ.get("COMSPEC") or "cmd.exe"
    return f'"{shell}" /d /s /c "{line}"'


def find_executable(name: str, platform: str | None = None) -> str:
    """Resolve a bare program name to the file Windows would run.

    A name with a directory or an extension, any other platform, and a name that
    is not found come back unchanged, so the spawn reports its own error.
    """
    if (platform or sys.platform) != "win32" or "/" in name or "\\" in name or os.path.splitext(name)[1]:
        return name
    exts = [e for e in (os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD").split(";") if e]
    for directory in (os.environ.get("PATH") or "").split(os.pathsep):
        if not directory:
            continue
        for ext in exts:  # PATH order first, then PATHEXT order, as cmd.exe does
            candidate = os.path.join(directory, name + ext.lower())
            if os.path.isfile(candidate):
                return candidate
    return name


def run_allowing_batch(argv, **kwargs) -> subprocess.CompletedProcess:
    """``subprocess.run(argv, **kwargs)``, except that a batch file on Windows
    runs through cmd.exe with every argument escaped. ``argv[0]`` may be a bare
    name (``npm``); it is resolved with :func:`find_executable` first."""
    program = find_executable(argv[0])
    check = kwargs.pop("check", False)
    if not is_batch_file(program):
        return subprocess.run([program, *argv[1:]], check=check, **kwargs)
    return subprocess.run(batch_command_line(program, argv[1:]), check=check, **kwargs)
