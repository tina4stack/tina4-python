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


@pytest.mark.skipif(not hasattr(os, "mkfifo") or not hasattr(os, "O_NOFOLLOW"), reason="POSIX FIFO and no-follow contract")
@pytest.mark.parametrize("writer", ["bootstrap", "connections"])
def test_linked_fifo_is_refused_before_reading(tmp_path, writer):
    # A path-based pre-read would block on this FIFO before reaching open guards.
    import subprocess
    import sys
    from pathlib import Path

    target = tmp_path / "unrelated-pipe"
    os.mkfifo(target)
    (tmp_path / (".env.local" if writer == "bootstrap" else ".env")).symlink_to(target)
    code = """
import asyncio, os, sys
from tina4_python.auth import ensure_dev_secret
from tina4_python.core.request import Request
from tina4_python.core.response import Response
from tina4_python.dev_admin import _api_connections_save
os.environ.pop('TINA4_SECRET', None)
os.environ.pop('CI', None)
os.environ.pop('TINA4_ENV', None)
os.environ['TINA4_DEBUG'] = 'true'
if sys.argv[1] == 'bootstrap':
    assert ensure_dev_secret()
else:
    request = Request()
    request.body = {'url': 'sqlite:///private.db', 'password': 'private-test-value'}
    asyncio.run(_api_connections_save(request, Response()))
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable, "-c", code, writer], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert target.is_fifo()
