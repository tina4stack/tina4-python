# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""A request that writes nothing to the session stores no session and sets no
session cookie.

Python already skipped saving a new session the route never wrote to, and sent
no cookie for it. But a request that carried a cookie the store does not know
(an expired session, a cookie from another deployment) was handed a freshly
minted replacement id in a Set-Cookie on every response, for a session that was
never stored: the next request could not resume it either, so it was handed
another. php, ruby and nodejs had the same cookie, and php and nodejs stored a
session for every request (static files, 404s and /health included).

A REAL child server, real sockets: every cell counts the session files and
reads every Set-Cookie line off the wire.
"""

import http.client
import secrets
from pathlib import Path

import pytest

from conftest import boot_child_server


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("anon_session")
    store = tmp / "sessions"
    store.mkdir()

    def write_app(proj: Path, port: int) -> None:
        (proj / "src" / "public").mkdir(parents=True, exist_ok=True)
        (proj / "src" / "public" / "hello.txt").write_text("static file")
        (proj / "app.py").write_text(
            "from tina4_python.core import run\n"
            "from tina4_python.core.router import get\n\n"
            "@get('/plain')\n"
            "async def plain(request, response):\n"
            "    return response('plain')\n\n"
            "@get('/read')\n"
            "async def read(request, response):\n"
            "    return response('user=' + (request.session.get('user') or '-'))\n\n"
            "@get('/write')\n"
            "async def write(request, response):\n"
            "    request.session.set('user', 'alice')\n"
            "    return response('wrote')\n\n"
            "# Calls that mark a session changed without leaving anything in it.\n"
            "# A record with no data is not a session, so none may store one.\n"
            "@get('/clear')\n"
            "async def clear(request, response):\n"
            "    request.session.clear()\n"
            "    return response('cleared')\n\n"
            "@get('/delete-missing')\n"
            "async def delete_missing(request, response):\n"
            "    request.session.delete('never-set')\n"
            "    return response('deleted nothing')\n\n"
            "@get('/set-then-delete')\n"
            "async def set_then_delete(request, response):\n"
            "    request.session.set('a', '1')\n"
            "    request.session.delete('a')\n"
            "    return response('set then deleted')\n\n"
            "@get('/regenerate-empty')\n"
            "async def regenerate_empty(request, response):\n"
            "    request.session.regenerate()\n"
            "    return response('regenerated')\n\n"
            "@get('/read-flash')\n"
            "async def read_flash(request, response):\n"
            "    return response('flash=' + str(request.session.get_flash('error') or '-'))\n\n"
            "run()\n"
        )

    proc, port = boot_child_server(
        tmp, write_app,
        extra_env={"TINA4_SESSION_BACKEND": "file", "TINA4_SESSION_PATH": str(store)},
    )
    try:
        yield port, store
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


def _get(port: int, path: str, cookie: str | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
    try:
        conn.request("GET", path, headers={"Cookie": cookie} if cookie else {})
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace")
        cookies = [v for (k, v) in resp.getheaders() if k.lower() == "set-cookie"]
        return resp.status, body, cookies
    finally:
        conn.close()


def _files(store: Path) -> int:
    return sum(1 for p in store.rglob("*") if p.is_file())


EMPTY_TOUCHES = ["/clear", "/delete-missing", "/set-then-delete", "/regenerate-empty", "/read-flash"]
EMPTY_TOUCH_IDS = ["route that clears the session", "route that deletes a key it never set",
                   "route that sets then deletes a key", "route that regenerates an empty session",
                   "route that reads a flash message"]


@pytest.mark.parametrize("path", ["/hello.txt", "/missing", "/health", "/plain", "/read"] + EMPTY_TOUCHES,
                         ids=["static file", "404", "health", "route that never touches the session",
                              "route that reads the session"] + EMPTY_TOUCH_IDS)
def test_a_request_that_writes_nothing_stores_no_session_and_sets_no_cookie(server, path):
    port, store = server
    before = _files(store)
    for _ in range(3):
        _status, _body, cookies = _get(port, path)
        assert cookies == [], f"{path} must set no cookie; got {cookies}"
    assert _files(store) == before, f"{path} must store no session"


@pytest.mark.parametrize("path", EMPTY_TOUCHES, ids=EMPTY_TOUCH_IDS)
def test_a_request_with_an_unknown_cookie_that_leaves_the_session_empty_stores_nothing(server, path):
    # An expired or foreign cookie takes the "not new" path in the server, which
    # saves unconditionally: every visit used to store an empty record.
    port, store = server
    before = _files(store)
    for _ in range(3):
        _status, _body, cookies = _get(port, path, f"tina4_session={secrets.token_urlsafe(32)}")
        assert cookies == [], f"{path} must set no cookie; got {cookies}"
    assert _files(store) == before, f"{path} must store no session"


def test_a_cookie_the_store_never_issued_gets_no_replacement_cookie(server):
    port, store = server
    before = _files(store)
    for _ in range(3):
        _status, body, cookies = _get(port, "/read", f"tina4_session={secrets.token_urlsafe(32)}")
        assert body == "user=-"
        assert cookies == [], f"a session that was never stored needs no cookie; got {cookies}"
    assert _files(store) == before


def test_a_write_stores_the_session_and_a_replay_resumes_it(server):
    port, store = server
    before = _files(store)
    _status, _body, cookies = _get(port, "/write")
    session_cookies = [c for c in cookies if c.startswith("tina4_session=")]
    assert len(session_cookies) == 1, f"a write must set the session cookie; got {cookies}"
    assert _files(store) == before + 1
    pair = session_cookies[0].split(";", 1)[0]
    _status, body, replay_cookies = _get(port, "/read", pair)
    assert body == "user=alice"
    assert _files(store) == before + 1
    # A stored session is re-sent its cookie on a read-only request, so the
    # browser's copy keeps sliding with the server's (ADR-0087).
    assert [c.split(";", 1)[0] for c in replay_cookies if c.startswith("tina4_session=")] == [pair]


def test_clearing_a_stored_session_still_ends_it(server):
    # Only a session nothing ever stored is skipped for being empty. One the store
    # holds that a request empties is a logout: the stored record must go, or the
    # next request is logged straight back in.
    port, _store = server
    _status, _body, cookies = _get(port, "/write")
    pair = [c for c in cookies if c.startswith("tina4_session=")][0].split(";", 1)[0]
    assert _get(port, "/read", pair)[1] == "user=alice"
    _get(port, "/clear", pair)
    assert _get(port, "/read", pair)[1] == "user=-", "the cleared session must not be resumable"


def test_saving_a_fresh_session_writes_nothing_until_it_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("TINA4_SESSION_BACKEND", "file")
    monkeypatch.setenv("TINA4_SESSION_PATH", str(tmp_path))
    from tina4_python.session import Session
    session = Session()
    session.start(None)
    assert session.is_fresh()
    assert session.save() is True
    assert _files(tmp_path) == 0, "an unchanged, never-stored session writes nothing"
    session.set("user", "alice")
    assert not session.is_fresh()
    assert session.save() is True
    assert _files(tmp_path) == 1
