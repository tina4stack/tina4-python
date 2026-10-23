# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""RTC config + signalling require auth by default (ADR-0101, tina4-python#252).

The `/api/rtc/config` route mints a fresh TURN credential on every call, and the
`/ws/rtc/{room}` signalling socket relays a call. Left public, anyone can use the
operator's TURN server as a relay - unbounded bandwidth on their bill - and a
short credential TTL does not bound it (a script just fetches a new one). So both
are secured by default; an app that genuinely wants anonymous calling opts out
with TINA4_RTC_REQUIRE_AUTH=false.

Answer key: tina4-documentation/plan/v3/fixtures/rtc_auth_contract.json. The same
cases run in all four frameworks on the REAL router tables after a real
realtime() registration - no mocks; auth_required is read straight off the
registered route.
"""
import pytest

from tina4_python.core import router
from tina4_python.core.router import Router
from tina4_python.realtime import realtime

CONFIG = "/api/rtc/config"
SIGNAL = "/ws/rtc"


def _http_auth(path_contains: str) -> bool:
    routes = [r for r in router._routes if path_contains in r["path"]]
    assert routes, f"no HTTP route registered containing {path_contains}"
    return bool(routes[-1]["auth_required"])


def _ws_auth(path_contains: str) -> bool:
    routes = [r for r in Router.get_web_socket_routes() if path_contains in r["path"]]
    assert routes, f"no WS route registered containing {path_contains}"
    return bool(routes[-1]["auth_required"])


@pytest.fixture(autouse=True)
def _clean_routes():
    Router.clear()
    yield
    Router.clear()


def _register(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("TINA4_RTC_REQUIRE_AUTH", raising=False)
    else:
        monkeypatch.setenv("TINA4_RTC_REQUIRE_AUTH", value)
    realtime(prefix="/rtc-t", features=["calls", "chat"])


def test_config_route_requires_auth_by_default(monkeypatch):
    _register(monkeypatch, None)
    assert _http_auth(CONFIG) is True


def test_signalling_socket_requires_auth_by_default(monkeypatch):
    _register(monkeypatch, None)
    assert _ws_auth(SIGNAL) is True


def test_require_auth_false_opens_the_config_route(monkeypatch):
    _register(monkeypatch, "false")
    assert _http_auth(CONFIG) is False


def test_require_auth_false_opens_the_signalling_socket(monkeypatch):
    _register(monkeypatch, "false")
    assert _ws_auth(SIGNAL) is False


def test_require_auth_explicit_true_secures_both(monkeypatch):
    _register(monkeypatch, "true")
    assert _http_auth(CONFIG) is True and _ws_auth(SIGNAL) is True


def test_only_explicit_falsey_opens_the_route(monkeypatch):
    # An unrecognised value is NOT an opt-out - secure-by-default holds.
    _register(monkeypatch, "yes-please")
    assert _http_auth(CONFIG) is True
