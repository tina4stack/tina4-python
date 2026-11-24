# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""A bare any() route keeps writes secure by default (ADR-0019).

Every route answers GET publicly and needs a token for POST, PUT, PATCH and
DELETE, unless it says otherwise. An any() route was the one exception in
Python: it was public for EVERY method, so ``Router.any("/x", h)`` took
anonymous writes that ``Router.post("/x", h)`` refused. tina4-php and
tina4-nodejs register any() as one route per method, so their write methods
were already gated; this brings Python to the same contract.

Real requests through the front controller (TestClient) with real tokens; no
mocks.
"""
import pytest

from tina4_python.auth import get_token
from tina4_python.core.router import Router, any_method, noauth
from tina4_python.test_client import TestClient

WRITES = ("post", "put", "patch", "delete")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("TINA4_SECRET", "any-write-auth-secret-0123456789")
    # CSRF is a separate gate; switch it off so the status is the auth gate's.
    monkeypatch.setenv("TINA4_CSRF", "false")
    yield


async def _ok(request, response):
    return response({"ok": True})


@pytest.fixture(autouse=True)
def _routes():
    Router.any("/__anyauth/bare", _ok)
    Router.any("/__anyauth/open", _ok).no_auth()
    Router.any("/__anyauth/locked", _ok).secure()
    Router.any("/__anyauth/explicit", _ok, auth_required=False)
    Router.group("/__anyauth/grp", lambda g: g.any("/bare", _ok))

    @any_method("/__anyauth/deco")
    async def _deco(request, response):
        return response({"ok": True})

    @noauth()
    @any_method("/__anyauth/deco_open")
    async def _deco_open(request, response):
        return response({"ok": True})

    yield


def _call(method, path, headers=None):
    client = TestClient()
    if method == "get":
        return client.get(path, headers=headers)
    if method == "delete":
        return client.delete(path, headers=headers)
    return getattr(client, method)(path, json={}, headers=headers)


def _bearer():
    return {"Authorization": f"Bearer {get_token({'sub': 'u'})}"}


@pytest.mark.parametrize("path", ["/__anyauth/bare", "/__anyauth/grp/bare", "/__anyauth/deco"])
def test_bare_any_route_reads_are_public(path):
    assert _call("get", path).status == 200


@pytest.mark.parametrize("path", ["/__anyauth/bare", "/__anyauth/grp/bare", "/__anyauth/deco"])
@pytest.mark.parametrize("method", WRITES)
def test_bare_any_route_writes_need_a_token(path, method):
    assert _call(method, path).status == 401, f"anonymous {method.upper()} {path} was let through"
    assert _call(method, path, _bearer()).status == 200, f"{method.upper()} {path} refused a valid token"


@pytest.mark.parametrize("path", ["/__anyauth/open", "/__anyauth/explicit", "/__anyauth/deco_open"])
@pytest.mark.parametrize("method", ("get",) + WRITES)
def test_an_any_route_opened_explicitly_stays_public(path, method):
    assert _call(method, path).status == 200, f"{method.upper()} {path} should be public"


@pytest.mark.parametrize("method", ("get",) + WRITES)
def test_a_secured_any_route_needs_a_token_for_every_method(method):
    assert _call(method, "/__anyauth/locked").status == 401
    assert _call(method, "/__anyauth/locked", _bearer()).status == 200


def test_the_write_default_does_not_leak_to_a_plain_get_route():
    Router.get("/__anyauth/plain_get", _ok)
    assert _call("get", "/__anyauth/plain_get").status == 200
