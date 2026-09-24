# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Secret-bearing development configuration uses private real files."""
import os
import stat

import pytest

from tina4_python.auth import ensure_dev_secret
from tina4_python.core.request import Request
from tina4_python.core.response import Response
from tina4_python.dev_admin import _api_connections_save


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission contract")
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.asyncio
async def test_saved_database_credentials_are_owner_only(tmp_path, monkeypatch, existing):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / ".env"
    if existing:
        target.write_text("OTHER=keep\n")
        target.chmod(0o644)
    request = Request()
    request.body = {"url": "sqlite:///private.db", "username": "alice", "password": "private-test-value"}
    await _api_connections_save(request, Response())
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert "TINA4_DATABASE_PASSWORD=private-test-value" in target.read_text()
    if existing:
        assert "OTHER=keep" in target.read_text()


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="Requires no-follow file opens")
@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
@pytest.mark.asyncio
async def test_config_writers_refuse_linked_targets(tmp_path, monkeypatch, link_kind):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "untouched"
    target.write_text("original")
    for filename in (".env", ".env.local"):
        if link_kind == "symlink":
            (tmp_path / filename).symlink_to(target)
        else:
            os.link(target, tmp_path / filename)
    request = Request()
    request.body = {"url": "sqlite:///private.db", "password": "private-test-value"}
    await _api_connections_save(request, Response())
    monkeypatch.delenv("TINA4_SECRET", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("TINA4_ENV", raising=False)
    monkeypatch.setenv("TINA4_DEBUG", "true")
    assert ensure_dev_secret(cwd=str(tmp_path))
    assert target.read_text() == "original"
