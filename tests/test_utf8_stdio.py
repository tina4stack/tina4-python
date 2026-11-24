# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The CLI and the logger write UTF-8 to a pipe, whatever the locale codepage.

PHP, Ruby and Node emit UTF-8 bytes. Python encodes text with the locale
codepage, which on Windows is cp1252 whenever stdout is not a console (a pipe, a
redirect, a service manager, the `tina4` client capturing output). The CLI's
status marks (U+2713 / U+2717) then raised UnicodeEncodeError, so
`tina4python migrate:create ... | more` crashed after writing its files, and a
Log line carrying such a character took the request that logged it down too.

Each case runs a REAL child interpreter whose stdout is a pipe encoded as
cp1252 (PYTHONIOENCODING sets the stream encoding exactly as the Windows locale
does), so the same failure reproduces on any OS. Mutation: make
tina4_python.debug.ensure_utf8_stdio a no-op and every case here goes red.
"""

import os
import subprocess
import sys

from conftest import child_pythonpath


def _run_child(code, cwd, *argv):
    env = {**os.environ, "PYTHONPATH": child_pythonpath(), "PYTHONIOENCODING": "cp1252",
           "TINA4_NO_BROWSER": "true"}
    env.pop("PYTHONUTF8", None)
    return subprocess.run([sys.executable, "-c", code, *argv], cwd=str(cwd), env=env,
                          capture_output=True, timeout=120)


def test_cli_status_marks_survive_a_cp1252_pipe(tmp_path):
    result = _run_child("from tina4_python.cli import main; main()", tmp_path,
                        "migrate:create", "add things")
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    out = result.stdout.decode("utf-8")      # must be UTF-8, not cp1252 or mojibake
    assert "\u2713" in out, out
    assert list((tmp_path / "migrations").glob("*_add_things.sql")), "the command did not run"


def test_a_log_line_outside_cp1252_does_not_crash_the_caller(tmp_path):
    code = (
        "from tina4_python.debug import Log\n"
        "Log.configure(output='stdout', format='json')\n"
        "Log.info('snowman \\u2603 check \\u2713')\n"
        "print('after-log', flush=True)\n"
    )
    result = _run_child(code, tmp_path)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    out = result.stdout.decode("utf-8")
    assert "snowman \u2603 check \u2713" in out, out
    assert "after-log" in out, "the caller died at the log line"
