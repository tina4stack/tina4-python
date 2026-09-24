"""The server opens a browser only for a developer at a keyboard.

Test servers booted on a shared Mac were opening browser tabs: the gate read
TINA4_NO_BROWSER with its own true/1/yes list (so "on" did nothing), and it
opened a browser with debug OFF and under CI too.

The rule: open a browser only when ALL of these hold -
  * TINA4_DEBUG is truthy,
  * TINA4_NO_BROWSER is not truthy (the shared is_truthy list, "on" included),
  * --no-browser (run(no_browser=True)) was not passed,
  * no CI variable is set.

No mocks: each case boots the real server in a child process. The "browser" is
Python's own webbrowser module driven by the standard BROWSER variable, pointed
at a real script that appends the URL to a marker file - so an open is observed
as a real process writing a real file.
"""
import os
import stat
import sys
import time

import pytest

from conftest import boot_child_server

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="[needs:posix] the marker opener is a POSIX shell script")

OPEN_DELAY = 2.0      # _open_browser waits this long before opening
WAIT_FOR_OPEN = 8.0   # generous: a slow lab still opens well inside this


def _boot(tmp_path, *, debug: bool, no_browser_flag: bool = False, extra=None, unset=()):
    marker = tmp_path / "opened.txt"
    opener = tmp_path / "opener.sh"
    opener.write_text(f'#!/bin/sh\necho "$1" >> "{marker}"\n')
    opener.chmod(opener.stat().st_mode | stat.S_IXUSR)

    def write_app(project, port):
        (project / "app.py").write_text(
            "from tina4_python.core.server import run\n"
            f"run(host='127.0.0.1', port={port}, no_browser={no_browser_flag!r}, no_reload=True)\n"
        )

    env = {"TINA4_DEBUG": "true" if debug else "false", "BROWSER": f"{opener} %s"}
    env.update(extra or {})
    proc, port = boot_child_server(
        tmp_path, write_app, extra_env=env,
        # boot_child_server pins TINA4_NO_BROWSER=true for safety; each case
        # removes exactly the guards it is about.
        unset_env=("TINA4_NO_BROWSER", "CI", "TINA4_DEFAULT_WEBSERVER", *unset),
    )
    return proc, port, marker


def _opened(marker, wait: float) -> str:
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if marker.exists() and marker.read_text().strip():
            return marker.read_text().strip()
        time.sleep(0.1)
    return ""


def _stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
        proc.wait(timeout=10)


def test_debug_on_with_no_guard_opens_the_browser(tmp_path):
    proc, port, marker = _boot(tmp_path, debug=True)
    try:
        opened = _opened(marker, WAIT_FOR_OPEN)
        assert opened == f"http://127.0.0.1:{port}", f"expected one open of the app URL, got {opened!r}"
    finally:
        _stop(proc)


@pytest.mark.parametrize("case", ["debug_off", "no_browser_on", "no_browser_flag", "ci_set"])
def test_the_browser_stays_closed_when_any_guard_holds(tmp_path, case):
    kwargs = {
        "debug_off": dict(debug=False),
        "no_browser_on": dict(debug=True, extra={"TINA4_NO_BROWSER": "on"}),
        "no_browser_flag": dict(debug=True, no_browser_flag=True),
        "ci_set": dict(debug=True, extra={"CI": "true"}),
    }[case]
    # boot_child_server applies extra_env AFTER unset_env, so a guard passed in
    # extra survives the removal of the outer one.
    proc, port, marker = _boot(tmp_path, **kwargs)
    try:
        opened = _opened(marker, OPEN_DELAY + 3)
        assert opened == "", f"{case}: the browser was opened ({opened!r})"
    finally:
        _stop(proc)


def test_conftest_pins_no_browser_for_the_whole_session():
    from tina4_python.dotenv import is_truthy
    assert is_truthy(os.environ.get("TINA4_NO_BROWSER", "")), (
        "tests/conftest.py must default TINA4_NO_BROWSER to true so no test opens a browser")
