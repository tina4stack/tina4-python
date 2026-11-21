# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""ProjectIndex keys are "/"-separated on every OS.

``str(path.relative_to(root))`` gives ``src\\routes\\users.py`` on Windows, so
``file_entry("src/routes/users.py")`` - the form every caller, the MCP tools and
the other three frameworks use - found nothing there. PHP already normalises
to "/"; Python and Node now do too. Real files, a real index on disk.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tina4_python.dev_admin import project_index


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A scratch project with a nested route file; cwd is the project root."""
    routes = tmp_path / "src" / "routes" / "api"
    routes.mkdir(parents=True)
    (routes / "users.py").write_text(
        "from tina4_python.core.router import get\n\n"
        "@get('/api/users')\n"
        "async def users(request, response):\n"
        "    return response([])\n"
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_index_keys_use_forward_slashes(project: Path) -> None:
    project_index.refresh()
    keys = list(project_index._load_raw()["files"])
    assert "src/routes/api/users.py" in keys, keys
    assert not any("\\" in key for key in keys), keys


def test_entry_path_uses_forward_slashes(project: Path) -> None:
    entry = project_index.file_entry("src/routes/api/users.py")
    assert "error" not in entry, entry
    assert entry["path"] == "src/routes/api/users.py"


def test_refresh_reports_the_index_path_with_forward_slashes(project: Path) -> None:
    assert project_index.refresh()["path"] == ".tina4/project_index.json"
