# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""ADR-0108: a failing seed file fails loud.

Real seed files on disk, a real SQLite database and the real CLI in a
subprocess. No doubles.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tina4_python.database import Database
from tina4_python.orm import model as orm_model
from tina4_python.orm import bind_database
from tina4_python.seeder import FakeData, SeedError


def _write(folder: Path, name: str, body: str) -> Path:
    path = folder / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def _tracker_lines(tracker: Path) -> list:
    return tracker.read_text(encoding="utf-8").split() if tracker.exists() else []


def _three_files(folder: Path, tracker: Path) -> dict:
    record = f"open({str(tracker)!r}, 'a').write('{{}}\\n')"
    return {
        "ok_first": _write(folder, "001_ok.py", record.format("001_ok")),
        "raises": _write(folder, "002_raises.py", "raise RuntimeError('seed exploded')\n"),
        "ok_last": _write(folder, "003_ok.py", record.format("003_ok")),
    }


def test_a_failing_seed_file_stops_the_run_and_raises_naming_it(tmp_path):
    tracker = tmp_path / "ran.txt"
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    files = _three_files(seeds, tracker)

    with pytest.raises(SeedError) as raised:
        FakeData().seed_dir(str(seeds))

    error = raised.value
    assert error.seed_file == str(files["raises"])
    assert error.completed == [str(files["ok_first"])]
    assert isinstance(error.__cause__, RuntimeError)
    assert "002_raises.py" in str(error) and "seed exploded" in str(error)
    # 001 ran, 003 never did: the run stopped at the failing file.
    assert _tracker_lines(tracker) == ["001_ok"]


def test_a_clean_folder_returns_the_executed_files_in_order_and_skips_underscore(tmp_path):
    tracker = tmp_path / "ran.txt"
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    record = f"open({str(tracker)!r}, 'a').write('{{}}\\n')"
    second = _write(seeds, "002_second.py", record.format("002_second"))
    first = _write(seeds, "001_first.py", record.format("001_first"))
    _write(seeds, "_helper.py", "raise RuntimeError('a helper must never run')\n")
    # Not a .py seed file: a runner that executes every file would run it.
    _write(seeds, "README.txt", "raise RuntimeError('a README must never run')\n")

    executed = FakeData().seed_dir(str(seeds))

    assert executed == [str(first), str(second)]
    assert _tracker_lines(tracker) == ["001_first", "002_second"]


def test_a_missing_folder_returns_an_empty_list(tmp_path):
    assert FakeData().seed_dir(str(tmp_path / "missing")) == []


_GENERATED_SHAPE = """\
def run(db):
    db.execute("INSERT INTO seeded (source) VALUES (?)", ["{source}"])
    db.commit()
"""


def _seeded_rows(db) -> list:
    return [row["source"] for row in db.fetch("SELECT source FROM seeded ORDER BY id").records]


def test_the_runner_calls_run_db_with_the_database_passed_in(tmp_path):
    db = Database("sqlite:///" + str(tmp_path / "app.db"))
    db.execute("CREATE TABLE seeded (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT)")
    db.commit()
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    _write(seeds, "001_users.py", _GENERATED_SHAPE.format(source="passed"))
    try:
        FakeData().seed_dir(str(seeds), db=db)
        assert _seeded_rows(db) == ["passed"]
    finally:
        db.close()


def test_the_runner_calls_run_db_with_the_bound_database_by_default(tmp_path):
    db = Database("sqlite:///" + str(tmp_path / "app.db"))
    db.execute("CREATE TABLE seeded (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT)")
    db.commit()
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    _write(seeds, "001_users.py", _GENERATED_SHAPE.format(source="bound"))
    previous = orm_model._database
    bind_database(db)
    try:
        FakeData().seed_dir(str(seeds))
        assert _seeded_rows(db) == ["bound"]
    finally:
        bind_database(previous)
        db.close()


def _run_cli_seed(project: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["TINA4_DATABASE_URL"] = "sqlite:///" + str(project / "app.db")
    return subprocess.run(
        [sys.executable, "-c", "from tina4_python.cli import main; main()", "seed"],
        cwd=str(project), env=env, capture_output=True, text=True, timeout=120,
    )


def test_cli_seed_exits_1_naming_the_failing_file(tmp_path):
    tracker = tmp_path / "ran.txt"
    seeds = tmp_path / "src" / "seeds"
    seeds.mkdir(parents=True)
    _three_files(seeds, tracker)

    result = _run_cli_seed(tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "002_raises.py" in result.stdout + result.stderr
    assert _tracker_lines(tracker) == ["001_ok"]


def test_cli_seed_exits_0_when_every_file_runs(tmp_path):
    tracker = tmp_path / "ran.txt"
    seeds = tmp_path / "src" / "seeds"
    seeds.mkdir(parents=True)
    record = f"open({str(tracker)!r}, 'a').write('{{}}\\n')"
    _write(seeds, "001_ok.py", record.format("001_ok"))

    result = _run_cli_seed(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _tracker_lines(tracker) == ["001_ok"]
