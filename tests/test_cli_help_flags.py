# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""`--help` / `-h` print usage and change nothing, for every command.

Handlers never looked for a help flag, so it ran the command for real:
`generate model --help` wrote a model named `--help` (four files), `lint --help`
installed ruff, `migrate --help` created app.db. NO MOCKS: each case runs the
REAL `tina4python` entrypoint in a real temp project and diffs the directory.
"""
import hashlib
import os
import subprocess
import sys

import pytest

from conftest import child_pythonpath
from tina4_python.cli import COMMANDS, GENERATORS

_ENTRYPOINT = "import sys; from tina4_python.cli import main; main()"


def _run_cli(argv, cwd):
    env = os.environ.copy()
    env["PYTHONPATH"] = child_pythonpath()
    return subprocess.run(
        [sys.executable, "-c", _ENTRYPOINT, *argv],
        cwd=str(cwd), env=env, capture_output=True, text=True, timeout=60,
        stdin=subprocess.DEVNULL,
    )


def _snapshot(root):
    """Every path under root with a hash of its bytes."""
    seen = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for d in dirnames:
            seen[os.path.relpath(os.path.join(dirpath, d), root)] = "dir"
        for f in filenames:
            path = os.path.join(dirpath, f)
            with open(path, "rb") as fh:
                seen[os.path.relpath(path, root)] = hashlib.sha256(fh.read()).hexdigest()
    return seen


def _project(tmp_path):
    """A minimal project: an app.py and a pyproject.toml that lint could rewrite."""
    (tmp_path / "app.py").write_text("print('app')\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.0.0"\n')
    return tmp_path


_COMMAND_CASES = [[name] for name in COMMANDS if name != "help"]
_GENERATOR_CASES = [["generate", name] for name in GENERATORS]


@pytest.mark.parametrize("flag", ["--help", "-h"])
@pytest.mark.parametrize("argv", _COMMAND_CASES + _GENERATOR_CASES, ids=" ".join)
def test_help_flag_prints_usage_and_writes_nothing(tmp_path, argv, flag):
    project = _project(tmp_path)
    before = _snapshot(project)
    result = _run_cli([*argv, flag], project)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Usage: tina4python {' '.join(argv)}" in result.stdout
    assert _snapshot(project) == before, "a --help run changed the project"


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_flag_after_the_name_still_wins(tmp_path, flag):
    project = _project(tmp_path)
    before = _snapshot(project)
    result = _run_cli(["generate", "model", "Product", "--fields", "name:string", flag], project)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Usage: tina4python generate model" in result.stdout
    assert _snapshot(project) == before


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_top_level_help_flag_prints_the_reference(tmp_path, flag):
    result = _run_cli([flag], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Usage: tina4python <command>" in result.stdout


@pytest.mark.parametrize("argv", [["help"], ["help", "--help"], ["help", "-h"]])
def test_the_help_command_always_prints_the_reference(tmp_path, argv):
    result = _run_cli(argv, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Usage: tina4python <command>" in result.stdout
    assert "Unknown option" not in result.stdout


def test_generate_help_lists_every_generator(tmp_path):
    result = _run_cli(["generate", "--help"], tmp_path)
    assert result.returncode == 0
    for name in GENERATORS:
        assert name in result.stdout


@pytest.mark.parametrize("argv", [
    ["generate", "model", "--fields", "name:string"],   # name forgotten
    ["generate", "route", "--public"],
])
def test_a_name_that_looks_like_an_option_is_refused(tmp_path, argv):
    project = _project(tmp_path)
    before = _snapshot(project)
    result = _run_cli(argv, project)
    assert result.returncode == 1
    assert "can't start with '-'" in result.stdout
    assert _snapshot(project) == before


# ---- options: unknown ones, missing values, --name=value, ai --all -------

@pytest.mark.parametrize("argv, wrong, suggestion", [
    (["generate", "model", "Product", "--feilds", "name:string"], "--feilds", "--fields"),
    (["generate", "route", "products", "--publc"], "--publc", "--public"),
    (["serve", "--prot", "9000"], "--prot", "--port"),
    (["queue", "work", "--onse"], "--onse", "--once"),
])
def test_a_misspelled_option_is_refused_with_a_suggestion(tmp_path, argv, wrong, suggestion):
    project = _project(tmp_path)
    before = _snapshot(project)
    result = _run_cli(argv, project)
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"Unknown option {wrong}" in result.stdout
    assert f"Did you mean {suggestion}?" in result.stdout
    assert _snapshot(project) == before


@pytest.mark.parametrize("argv", [
    ["generate", "model", "Product", "-f", "name:string"],   # short options don't exist
    ["lint", "--everything"],
    ["migrate", "--force"],
])
def test_an_option_the_command_does_not_have_is_refused(tmp_path, argv):
    project = _project(tmp_path)
    before = _snapshot(project)
    result = _run_cli(argv, project)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Unknown option" in result.stdout
    assert _snapshot(project) == before


@pytest.mark.parametrize("argv, option", [
    (["generate", "model", "Product", "--fields"], "--fields"),          # used to crash
    (["generate", "service", "Nightly", "--every"], "--every"),         # used to ignore it
    (["generate", "model", "Product", "--fields", "--no-migration"], "--fields"),
])
def test_a_value_option_without_a_value_is_refused(tmp_path, argv, option):
    project = _project(tmp_path)
    before = _snapshot(project)
    result = _run_cli(argv, project)
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"Option {option} for" in result.stdout and "needs a value" in result.stdout
    assert "Traceback" not in result.stderr
    assert _snapshot(project) == before


@pytest.mark.parametrize("fields_arg", [["--fields", "price:float"], ["--fields=price:float"]])
def test_a_value_option_works_in_both_spellings(tmp_path, fields_arg):
    project = _project(tmp_path)
    result = _run_cli(["generate", "model", "Product", *fields_arg], project)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "price" in (project / "src" / "orm" / "Product.py").read_text()


def test_test_passes_its_arguments_to_pytest_unchecked(tmp_path):
    project = _project(tmp_path)
    (project / "tests").mkdir()
    (project / "tests" / "test_x.py").write_text("def test_one():\n    assert True\n")
    result = _run_cli(["test", "-q", "-k", "one"], project)
    assert "Unknown option" not in result.stdout
    assert "1 passed" in result.stdout + result.stderr


def test_ai_all_installs_without_the_menu(tmp_path):
    result = _run_cli(["ai", "--all"], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "CLAUDE.md").exists()


def test_every_option_in_the_help_is_an_accepted_option():
    """The usage text and the accepted options can't drift apart again."""
    import re
    from tina4_python.cli import _QUEUE_FLAGS, _RESOLUTION_FLAGS, _RESOLUTION_TARGETS
    for name, spec in COMMANDS.items():
        for option in re.findall(r"--([a-z][a-z-]*)", spec.get("usage", "")):
            assert option in (spec.get("flags") or {}), f"{name}: --{option} documented, not accepted"
    for name, spec in GENERATORS.items():
        accepted = dict(spec["flags"], **(_RESOLUTION_FLAGS if name in _RESOLUTION_TARGETS else {}))
        for option in re.findall(r"--([a-z][a-z-]*)", spec.get("usage", "")):
            assert option in accepted, f"generate {name}: --{option} documented, not accepted"
    assert set(_QUEUE_FLAGS) == set(COMMANDS["queue"]["subcommands"])


def test_crud_skip_model_follows_the_model_generators_hint(tmp_path):
    """`generate model` suggests `generate crud <Name> --skip-model`; it must work."""
    project = _project(tmp_path)
    assert _run_cli(["generate", "model", "Product", "--fields", "price:float"], project).returncode == 0
    model = (project / "src" / "orm" / "Product.py").read_text()
    result = _run_cli(["generate", "crud", "Product", "--skip-model"], project)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "already exists" not in result.stdout
    assert (project / "src" / "orm" / "Product.py").read_text() == model
    assert list((project / "src" / "routes").glob("*.py")), "crud wrote no admin route"
