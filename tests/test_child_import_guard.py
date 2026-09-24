# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Every Python child a test starts must import the checkout under test.

The bug (a ghost-test class): the venv's editable install is ONE ``.pth`` line
that points at ONE checkout. A child that starts with a working directory other
than the repo root - a script in ``tmp_path``, ``-c`` with ``cwd=tmp``, a
console script, a nested pytest in a generated project - and no ``PYTHONPATH``
pin reaches ``tina4_python`` through that ``.pth`` line. Run the suite from a
git worktree and the child silently exercises the OTHER checkout, so the test
passes or fails on code that is not under test. Observed 2026-09-24:
test_response_binary_body failed from a worktree whose own code was correct.

No mocks. Each case builds a REAL bare virtualenv whose site-packages carries a
REAL ``.pth`` file pointing at a decoy checkout - the same mechanism an editable
install uses - and asks a real child interpreter which copy it imported.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD_DIR = REPO_ROOT / "tests" / "_child_guard"
WHICH_COPY = "import tina4_python, os; print(os.path.realpath(tina4_python.__file__))"


def _under(path: str, root: Path) -> bool:
    return os.path.realpath(path).startswith(os.path.realpath(root) + os.sep)


@pytest.fixture(scope="module")
def decoy_editable_venv(tmp_path_factory):
    """A real venv whose editable ``.pth`` points at a decoy tina4_python.

    Built from sys._base_executable: a venv created by a venv inherits an
    @executable_path libpython reference that does not resolve under a
    uv-managed interpreter (see test_docstore_substitutability).
    """
    root = tmp_path_factory.mktemp("decoy_venv")
    decoy_checkout = root / "decoy_checkout"
    (decoy_checkout / "tina4_python").mkdir(parents=True)
    (decoy_checkout / "tina4_python" / "__init__.py").write_text("DECOY = True\n")

    base = getattr(sys, "_base_executable", None) or sys.executable
    venv = root / "venv"
    subprocess.run([base, "-m", "venv", "--without-pip", str(venv)], check=True, timeout=120)
    python_binary = venv / ("Scripts" if os.name == "nt" else "bin") / "python"
    # NOT with -S: without site.py sys.prefix is the BASE interpreter, and the
    # .pth would land in a shared Python used by everything else on the host.
    control_env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    purelib = subprocess.run(
        [str(python_binary), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        env=control_env, check=True, capture_output=True, text=True, timeout=60,
    ).stdout.strip()
    assert _under(purelib, venv), f"refusing to write a .pth outside the throwaway venv: {purelib}"
    # Exactly what `pip install -e` / `uv sync` writes for this project.
    Path(purelib, "_editable_impl_tina4_python.pth").write_text(str(decoy_checkout))

    # Control: with NO pin at all, this interpreter really does import the
    # decoy. If it did not, the cases below would prove nothing.
    control = subprocess.run(
        [str(python_binary), "-c", WHICH_COPY], cwd=str(root),
        env=control_env, capture_output=True, text=True, timeout=60,
    )
    assert control.returncode == 0 and _under(control.stdout.strip(), decoy_checkout), (
        "CONTROL FAILED: the decoy venv did not import the decoy checkout, so it "
        f"cannot stand in for an editable install of another checkout:\n{control.stdout}{control.stderr}"
    )
    return python_binary, decoy_checkout


def test_the_pytest_process_itself_imports_the_checkout_under_test():
    import tina4_python

    assert _under(tina4_python.__file__, REPO_ROOT), (
        f"pytest imported {tina4_python.__file__}, not the checkout under test {REPO_ROOT}"
    )


@pytest.mark.parametrize("launch", ["script", "dash_c"])
def test_an_inherited_environment_pins_the_child_past_another_checkouts_editable_install(
    decoy_editable_venv, tmp_path, launch
):
    """Positive: a child that inherits the suite's environment - the way almost
    every test starts one - imports THIS checkout, even though its interpreter's
    editable ``.pth`` points somewhere else and its cwd is not the repo."""
    python_binary, decoy_checkout = decoy_editable_venv
    script = tmp_path / "which_copy.py"
    script.write_text(WHICH_COPY + "\n")
    argv = [str(python_binary), str(script)] if launch == "script" else [str(python_binary), "-c", WHICH_COPY]

    result = subprocess.run(argv, cwd=str(tmp_path), env=dict(os.environ),
                            capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stdout + result.stderr
    loaded = result.stdout.strip()
    assert _under(loaded, REPO_ROOT), (
        f"the child imported {loaded} - the editable install's checkout "
        f"({decoy_checkout}) - instead of the checkout under test {REPO_ROOT}"
    )


def test_the_guard_aborts_a_child_that_resolves_another_checkout(decoy_editable_venv, tmp_path):
    """Negative: when something puts another checkout AHEAD of the pin, the
    child must refuse to run, and say which copy it found and which it wanted.
    Without the guard it would import the decoy and exit 0."""
    python_binary, decoy_checkout = decoy_editable_venv
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(decoy_checkout), str(REPO_ROOT), str(GUARD_DIR)])

    result = subprocess.run([str(python_binary), "-c", WHICH_COPY], cwd=str(tmp_path),
                            env=env, capture_output=True, text=True, timeout=60)

    assert result.returncode != 0, (
        f"the child ran with the wrong tina4_python instead of aborting:\n{result.stdout}"
    )
    assert result.stdout.strip() == "", result.stdout
    assert "loaded the WRONG tina4_python" in result.stderr, result.stderr
    assert os.path.realpath(decoy_checkout) in result.stderr, result.stderr
    assert os.path.realpath(REPO_ROOT) in result.stderr, result.stderr
