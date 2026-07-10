"""Meta-tests: every code-producing generator co-emits a REAL, green test.

For each generator we scaffold into a fresh temp project via the ACTUAL
``tina4python generate <what> <name>`` command (a real subprocess through the
real CLI entry point), then RUN the co-emitted test file with real pytest in a
real subprocess and assert it passes (exit 0). No mocks anywhere: real generate,
real pytest run of the emitted file, real SQLite / TestClient / Router /
ServiceRunner / Queue / event bus underneath.

This proves the co-emitted test is (a) actually written next to the code and
(b) green on generation — a scaffolded test that fails on creation is bad DX.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _cli_prefix() -> list[str]:
    """The real `tina4python` entry point. Prefer the installed console script
    next to this interpreter; fall back to invoking main() on this interpreter
    (identical entry point) if the script isn't present."""
    script = Path(sys.executable).parent / "tina4python"
    if script.exists():
        return [str(script)]
    return [sys.executable, "-c", "from tina4_python.cli import main; main()"]


def _run_cli(project: Path, *args: str) -> None:
    """Run `tina4python <args>` in the project dir; require success."""
    env = {**os.environ, "PYTHONPATH": str(project)}
    result = subprocess.run(
        [*_cli_prefix(), *args],
        cwd=str(project), env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"`tina4python {' '.join(args)}` failed:\n{result.stdout}\n{result.stderr}"
    )


def _run_generated_test(project: Path, test_rel: str) -> None:
    """Run the co-emitted test file with real pytest; require it to pass."""
    test_file = project / test_rel
    assert test_file.exists(), f"generator did not co-emit {test_rel}"
    env = {**os.environ, "PYTHONPATH": str(project)}
    env.pop("TINA4_API_KEY", None)
    env.setdefault("TINA4_SECRET", "meta-test-secret")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-q"],
        cwd=str(project), env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"co-emitted {test_rel} did NOT pass on generation:\n"
        f"{result.stdout}\n{result.stderr}"
    )


# (id, [pre-generate commands], generate command, co-emitted test file)
CASES = [
    ("model", [],
     ["generate", "model", "Product", "--fields", "name:string,price:float"],
     "tests/test_product_model.py"),
    ("route_with_model", [["generate", "model", "Product"]],
     ["generate", "route", "products", "--model", "Product"],
     "tests/test_products.py"),
    ("route_public", [["generate", "model", "Widget"]],
     ["generate", "route", "widgets", "--model", "Widget", "--public"],
     "tests/test_widgets.py"),
    ("route_no_model", [],
     ["generate", "route", "notes"],
     "tests/test_notes.py"),
    ("middleware", [],
     ["generate", "middleware", "AuthLog"],
     "tests/test_auth_log.py"),
    ("service", [],
     ["generate", "service", "Reaper", "--every", "5m"],
     "tests/test_reaper.py"),
    ("queue", [],
     ["generate", "queue", "order-emails"],
     "tests/test_order_emails.py"),
    ("validator", [],
     ["generate", "validator", "CreateUser"],
     "tests/test_create_user.py"),
    ("seeder", [["generate", "model", "Product"]],
     ["generate", "seeder", "Product"],
     "tests/test_product_seeder.py"),
    ("websocket", [],
     ["generate", "websocket", "chat"],
     "tests/test_ws_chat.py"),
    ("listener", [],
     ["generate", "listener", "user.created"],
     "tests/test_user_created.py"),
    ("auth", [],
     ["generate", "auth"],
     "tests/test_auth.py"),
    ("migration", [],
     ["generate", "migration", "create_widget", "--fields", "name:string"],
     "tests/test_widget_migration.py"),
    ("crud", [],
     ["generate", "crud", "Trinket", "--fields", "name:string,qty:int"],
     "tests/test_trinkets.py"),
]


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_generator_co_emits_a_green_test(tmp_path, case):
    _id, pre_commands, generate_command, test_rel = case
    for pre in pre_commands:
        _run_cli(tmp_path, *pre)
    _run_cli(tmp_path, *generate_command)
    _run_generated_test(tmp_path, test_rel)


def test_form_and_view_are_template_only_and_exempt(tmp_path):
    """form / view scaffold Frond templates (no Python logic), so they are
    exempt from co-emitting a test — assert they produce a .twig and NO test."""
    _run_cli(tmp_path, "generate", "form", "Product", "--fields", "name:string")
    _run_cli(tmp_path, "generate", "view", "Product", "--fields", "name:string")
    assert (tmp_path / "src" / "templates" / "forms" / "product.twig").exists()
    assert (tmp_path / "src" / "templates" / "pages" / "products.twig").exists()
    # No test files emitted for pure-template generators.
    tests_dir = tmp_path / "tests"
    emitted = list(tests_dir.glob("test_*.py")) if tests_dir.exists() else []
    assert emitted == [], f"template-only generators should emit no test, got {emitted}"
