# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Regressions for two TestClient DX footguns (#296, #300).

No mocks: a real .env file on disk, the real dotenv loader the app uses, and a
real TestResponse built from real ASGI header bytes.

Mirrors: tina4-php tests/TestClientEnvAndHeadersTest.php,
         tina4-ruby spec/test_client_env_and_headers_spec.rb,
         tina4-nodejs test/testClientEnvAndHeaders.test.ts
"""
import os
from pathlib import Path

from tina4_python.test_client import TestClient, TestResponse


# ─────────────────────────── #296 — TestClient loads .env ───────────────────────

def test_test_client_loads_env_without_importing_app(tmp_path, monkeypatch):
    """A fresh TestClient reads .env from the project root (#296).

    Before the fix, TestClient dispatched through the real front controller but
    never loaded .env (only run() did), so TINA4_SECRET read as unset and a
    token-signing route raised InsecureSecretError though .env was fine.
    """
    secret = "a" * 64  # a valid 64-char (32-byte) HMAC secret
    (tmp_path / ".env").write_text(f"TINA4_SECRET={secret}\n")

    monkeypatch.delenv("TINA4_SECRET", raising=False)
    monkeypatch.delenv("TINA4_ENV_FILE", raising=False)
    monkeypatch.chdir(tmp_path)

    assert os.environ.get("TINA4_SECRET") is None, "precondition: secret must start unset"

    TestClient()  # construction loads .env the way the app does

    assert os.environ.get("TINA4_SECRET") == secret, \
        "TestClient did not load TINA4_SECRET from .env — the #296 bug"


def test_test_client_env_load_is_first_wins(tmp_path, monkeypatch):
    """A real env var set before the client is NOT clobbered by .env (#296).

    The load is override=False (first-wins), so a test that set TINA4_SECRET
    itself keeps its value — the .env never overrides the real environment.
    """
    real = "r" * 64
    (tmp_path / ".env").write_text(f"TINA4_SECRET={'d' * 64}\n")  # a DIFFERENT value

    monkeypatch.setenv("TINA4_SECRET", real)
    monkeypatch.delenv("TINA4_ENV_FILE", raising=False)
    monkeypatch.chdir(tmp_path)

    TestClient()

    assert os.environ["TINA4_SECRET"] == real, \
        "TestClient clobbered a real env var — the load must be first-wins"


# ─────────────────────── #300 — case-insensitive response headers ───────────────

def test_response_headers_lookup_is_case_insensitive():
    """headers.get / [] / in find a header by its canonical name (#300)."""
    r = TestResponse(303, [(b"Location", b"/complaints")], b"")

    assert r.headers.get("Location") == "/complaints"   # was None
    assert r.headers["Location"] == "/complaints"       # was KeyError
    assert "Location" in r.headers                       # was False
    # the existing lower-case shape still works unchanged
    assert r.headers.get("location") == "/complaints"
    assert r.get_all("Location") == ["/complaints"]


def test_response_headers_absent_header_is_a_miss_not_a_false_hit():
    """A header never sent returns None / is absent — no accidental match (#300)."""
    r = TestResponse(200, [(b"Content-Type", b"text/html")], b"")

    assert r.headers.get("X-Absent") is None
    assert "X-Absent" not in r.headers
    assert r.get_all("X-Absent") == []
    # a dict it still is — readers that isinstance-check are unaffected
    assert isinstance(r.headers, dict)
