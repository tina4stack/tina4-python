# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""`migrate:create <description>` names the file from a slug of the description.

The description is prose - `migrate:create add things`, or the CLI's own
example `migrate:create create users table`. Since `migrate:create` started
delegating to `generate migration` (3.13.121) the prose went into the filename
verbatim: `<ts>_add things.sql`, `<ts>_Add Things!.sql`, and an empty
description wrote `<ts>_.sql`. A `create users` description also missed the
`create_` CREATE TABLE scaffold. Before that release, and in php, ruby and
nodejs today, the description is slugged first: lowercase, every run of
characters outside [a-z0-9] becomes one `_`, edge `_` trimmed - the same rule
`create_migration()` and the MCP `migration_create` tool apply.

NO mocks. Each case runs the real `tina4_python.cli.main` in a fresh
subprocess under `tmp_path`, so what it observes is what a user gets.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest

CLI_INVOKE = (
    "import sys; sys.argv={argv!r}; "
    "from tina4_python.cli import main; main()"
)


def _run(cwd, argv):
    return subprocess.run(
        [sys.executable, "-c", CLI_INVOKE.format(argv=argv)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=60,
    )


def _migration_files(cwd):
    folder = cwd / "migrations"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


# (words after `migrate:create`, the name php/ruby/nodejs give the file)
SLUG_CASES = [
    (["add things"], "add_things"),
    (["add", "things"], "add_things"),
    (["Add Things"], "add_things"),
    (["add-things"], "add_things"),
    (["add things!"], "add_things"),
    (["add, things."], "add_things"),
    (["add   things"], "add_things"),
    (["  add things  "], "add_things"),
    (["add_things"], "add_things"),
    (["add__things"], "add_things"),
    (["add 2 things"], "add_2_things"),
    (["CreateUsers"], "createusers"),
    (["café crème"], "caf_cr_me"),
    (["a/b"], "a_b"),
    (["../x"], "x"),
    (["a\\b"], "a_b"),
]


@pytest.mark.parametrize("words,slug", SLUG_CASES,
                         ids=["|".join(w) for w, _ in SLUG_CASES])
def test_migrate_create_writes_the_slugged_name(tmp_path, words, slug):
    result = _run(tmp_path, ["tina4python", "migrate:create", *words])
    assert result.returncode == 0, result.stdout + result.stderr
    files = _migration_files(tmp_path)
    assert len(files) == 2 and all(
        re.fullmatch(rf"\d{{14}}_{slug}(\.down)?\.sql", f) for f in files
    ), f"migrate:create {words!r} wrote {files!r}, expected <ts>_{slug}.sql + .down.sql"
    # Nothing escaped migrations/ (a `/` or `..` in the description).
    others = [p for p in tmp_path.rglob("*")
              if p.is_file() and p.parent != tmp_path / "migrations"]
    assert others == [], others


def test_slug_matches_create_migration(tmp_path):
    """The CLI and the Python API name a description the same way."""
    from tina4_python.migration.runner import create_migration

    for words, _ in SLUG_CASES:
        desc = " ".join(words)
        cli_dir = tmp_path / f"cli{len(list(tmp_path.iterdir()))}"
        cli_dir.mkdir()
        assert _run(cli_dir, ["tina4python", "migrate:create", desc]).returncode == 0
        api_dir = tmp_path / f"api{len(list(tmp_path.iterdir()))}"
        api = create_migration(desc, str(api_dir))
        strip = lambda name: re.sub(r"^\d{14}_", "", name)
        cli_up = [f for f in _migration_files(cli_dir) if not f.endswith(".down.sql")]
        assert [strip(f) for f in cli_up] == [strip(api.rsplit("/", 1)[-1])], desc


def test_create_description_gets_the_create_table_scaffold(tmp_path):
    """`migrate:create create users` is a CREATE migration, like `create_users`."""
    result = _run(tmp_path, ["tina4python", "migrate:create", "create", "users"])
    assert result.returncode == 0, result.stdout + result.stderr
    up = [f for f in _migration_files(tmp_path) if not f.endswith(".down.sql")]
    assert len(up) == 1 and up[0].endswith("_create_users.sql"), up
    assert "CREATE TABLE IF NOT EXISTS users" in (tmp_path / "migrations" / up[0]).read_text()


def test_envelope_names_the_slug(tmp_path):
    """--json --dry-run reports the same name it would write."""
    result = _run(tmp_path, ["tina4python", "migrate:create", "Add Things!",
                             "--json", "--dry-run"])
    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["input"]["name"] == "add_things"
    assert re.fullmatch(r"migrations/\d{14}_add_things\.sql",
                        envelope["resolution"]["file_path"]), envelope["resolution"]
    assert _migration_files(tmp_path) == []


@pytest.mark.parametrize("words", [[""], ["!!!"], ["日本"], ["-", "?"]],
                         ids=["empty", "punctuation", "non-ascii", "dash-question"])
def test_description_without_a_letter_or_digit_is_refused(tmp_path, words):
    result = _run(tmp_path, ["tina4python", "migrate:create", *words])
    assert result.returncode != 0
    assert "Usage:" in result.stdout
    assert _migration_files(tmp_path) == []
