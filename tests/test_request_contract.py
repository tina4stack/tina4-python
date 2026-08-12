# Feature 29 - HTTP request model - shared cross-language contract (3.13.99).
#
# Four named cases, identical across Python/PHP/Ruby/Node
# (plan/v3/fixtures/request_contract.json), each driven through the REAL
# front controller (TestClient -> tina4_python.core.server.app) or a real
# ASGI scope dispatched through that same app — no mocks, no hand-invoked
# handlers.
#
#   route_param_not_shadowed_by_query  - REQ-PARAM-POLLUTION (security):
#       params is route-only; a client ?id= can never shadow the route {id}.
#   malformed_json_body_agreed_result  - REQ-BODY-DIVERGE: malformed JSON ->
#       the raw string, in all four (was {} in Ruby).
#   auth_middleware_sets_request_user  - REQ-PY-NO-USER: the secure-by-default
#       auth gate stashes the verified payload on request.user.
#   ip_honours_xff_only_from_trusted_proxy - DO NOT REGRESS: remote_ip is
#       always the raw peer; ip honours X-Forwarded-For ONLY from a
#       TINA4_TRUSTED_PROXIES peer. Locks the existing algorithm, doesn't
#       change it (see tests/test_trusted_proxy.py for the deeper suite).
import json

import pytest

from tina4_python.auth import get_token
from tina4_python.core.request import Request
from tina4_python.core.router import Router
from tina4_python.test_client import TestClient


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("TINA4_SECRET", "request-contract-secret")
    yield


async def _rq29_echo_params(request, response):
    return response({"params": dict(request.params), "query": dict(request.query)})


async def _rq29_echo_body(request, response):
    return response({"body": request.body})


async def _rq29_whoami(request, response):
    return response({"user": request.user})


async def _rq29_ip_probe(request, response):
    return response({"ip": request.ip, "remote_ip": request.remote_ip})


@pytest.fixture(autouse=True)
def _routes():
    """Register this file's probe routes fresh before EVERY test.

    Several OTHER test files in the suite call Router.clear() in their own
    setup/fixtures (test_crud.py, test_dispatch_characterisation.py, etc.) —
    process-global Router state means a route registered only ONCE at import
    time (the usual @get/@post decorator pattern) can be wiped by an
    unrelated file that happens to run first when the whole suite executes
    together, even though every test in THIS file passes in isolation. Using
    Router.add directly, in an autouse fixture, makes this file immune to
    that ordering — matching the pattern tests/test_csrf_middleware.py
    already uses for the same reason.
    """
    Router.add("GET", "/__rq29/{id}", _rq29_echo_params)
    Router.add("POST", "/__rq29/body", _rq29_echo_body).no_auth()
    Router.add("POST", "/__rq29/whoami", _rq29_whoami)
    Router.add("GET", "/__rq29ip/probe", _rq29_ip_probe)
    yield


def test_route_param_not_shadowed_by_query():
    """A route `/{id}` hit with `?id=other` -> params["id"] is the ROUTE
    value; the client value is only ever in query (REQ-PARAM-POLLUTION).

    Also asserts an UNRELATED query key (`extra`) never leaks into params —
    same-name collisions alone don't distinguish old vs new (route already
    won a name collision in the old query-seeded-then-route-merged params;
    the pollution was any OTHER client-controlled key riding along in
    `params` under a route-derived-looking namespace). This is the part
    that actually goes RED under the mutation-proof.
    """
    client = TestClient()
    resp = client.get("/__rq29/1?id=other&extra=leak")
    assert resp.status == 200
    body = resp.json()
    assert body["params"]["id"] == "1"
    assert body["query"]["id"] == "other"
    assert "extra" not in body["params"]
    assert body["query"]["extra"] == "leak"


def test_malformed_json_body_agreed_result():
    """A malformed JSON body -> the raw string, in every language."""
    client = TestClient()
    malformed = "{not valid json"
    resp = client.post(
        "/__rq29/body",
        body=malformed,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 200
    assert resp.json()["body"] == malformed


def test_auth_middleware_sets_request_user():
    """The secure-by-default auth gate stashes the verified JWT payload on
    request.user, and a handler reads it back."""
    token = get_token({"sub": "contract-user", "role": "tester"})
    client = TestClient()
    resp = client.post("/__rq29/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status == 200
    user = resp.json()["user"]
    assert user is not None
    assert user["sub"] == "contract-user"
    assert user["role"] == "tester"


def test_ip_honours_xff_only_from_trusted_proxy(monkeypatch):
    """request.ip uses X-Forwarded-For ONLY when the peer is a configured
    trusted proxy; otherwise the raw peer wins (DO NOT REGRESS the
    algorithm — this locks the existing behaviour, real dispatch, no mock).

    TestClient hardcodes its scope's peer to 127.0.0.1, so a controlled peer
    needs a scope built directly here — dispatched through the SAME real
    front controller (tina4_python.core.server.app) TestClient itself calls.
    """
    import asyncio

    from tina4_python.core.server import app as asgi_app

    async def _dispatch_probe(peer_ip: str, xff: str | None):
        header_list = [(b"x-forwarded-for", xff.encode())] if xff else []
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/__rq29ip/probe",
            "query_string": b"",
            "headers": header_list,
            "client": (peer_ip, 0),
            "scheme": "http",
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        collected = {"status": None, "body": bytearray()}

        async def send(message):
            if message["type"] == "http.response.start":
                collected["status"] = message["status"]
            elif message["type"] == "http.response.body":
                collected["body"].extend(message.get("body", b""))

        await asgi_app(scope, receive, send)
        return collected

    trusted_peer = "203.0.113.9"
    untrusted_peer = "198.51.100.7"
    spoofed = "1.2.3.4"

    # Trusted peer: X-Forwarded-For IS honoured.
    monkeypatch.setenv("TINA4_TRUSTED_PROXIES", trusted_peer)
    result = asyncio.run(_dispatch_probe(trusted_peer, spoofed))
    payload = json.loads(bytes(result["body"]))
    assert payload["remote_ip"] == trusted_peer
    assert payload["ip"] == spoofed

    # Untrusted peer: X-Forwarded-For is ignored — the raw peer wins.
    monkeypatch.setenv("TINA4_TRUSTED_PROXIES", trusted_peer)
    result = asyncio.run(_dispatch_probe(untrusted_peer, spoofed))
    payload = json.loads(bytes(result["body"]))
    assert payload["remote_ip"] == untrusted_peer
    assert payload["ip"] == untrusted_peer
