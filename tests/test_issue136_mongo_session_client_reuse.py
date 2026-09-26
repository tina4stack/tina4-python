# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Issue #136 - the MongoDB session backend must reuse ONE client per process.

With ``TINA4_SESSION_BACKEND=mongodb`` every request builds a ``Session``,
every ``Session`` resolves a new handler, and each handler opened a NEW
``pymongo.MongoClient`` - with its own monitor threads and connection pool -
that was never closed. Threads and server connections grew with every request
until the process or the database ran out. pymongo clients are thread-safe and
meant to be created once per process and shared.

The contract pinned here: every session handler for the same URI shares one
client, request after request, and closing a handler never strands the others.

NO MOCKS: a real MongoDB (its own database, ``tina4_issue136_py``), real
Session objects, and a REAL uvicorn child served over real HTTP whose own
thread count is read back from inside the process.
"""
import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import textwrap
import time
import urllib.request
from urllib.parse import urlparse

import pytest

MONGO_URI = os.environ.get("TINA4_TEST_MONGO_URI") or "mongodb://localhost:27017"
_PARSED = urlparse(MONGO_URI)
MONGO_HOST, MONGO_PORT = _PARSED.hostname or "localhost", _PARSED.port or 27017
MONGO_DB = "tina4_issue136_py"
REQUESTS = 20


def _mongo_reachable() -> bool:
    try:
        with socket.create_connection((MONGO_HOST, MONGO_PORT), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _mongo_reachable(),
    reason=f"MongoDB not reachable at {MONGO_HOST}:{MONGO_PORT} - skip integration test",
)

ROUTES = textwrap.dedent('''
    import threading
    from tina4_python.core.router import get, noauth


    @noauth()
    @get("/issue136/visits")
    async def visits(request, response):
        request.session.set("visits", (request.session.get("visits") or 0) + 1)
        return response({"visits": request.session.get("visits")})


    @noauth()
    @get("/issue136/threads")
    async def threads(request, response):
        return response({"threads": threading.active_count()})
''')

SERVE = textwrap.dedent('''
    import os
    import uvicorn
    from tina4_python.core.server import asgi

    uvicorn.run(asgi(), host="127.0.0.1", port=int(os.environ["ISSUE136_PORT"]), log_level="warning")
''')


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module", autouse=True)
def drop_test_database():
    import pymongo
    client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    client.drop_database(MONGO_DB)
    yield
    client.drop_database(MONGO_DB)
    client.close()


@pytest.fixture
def mongo_backend(monkeypatch):
    monkeypatch.setenv("TINA4_SESSION_BACKEND", "mongodb")
    monkeypatch.setenv("TINA4_SESSION_MONGO_URI", MONGO_URI)
    monkeypatch.setenv("TINA4_SESSION_MONGO_DB", MONGO_DB)


def _client_of(session):
    """The pymongo client a Session's handler actually talks through."""
    return session._handler._collection.database.client


def test_every_session_shares_one_mongo_client(mongo_backend):
    from tina4_python.session import Session

    first, second = Session(), Session()
    first.start()
    first.set("who", "first")
    assert first.save() is True
    second.start(first.session_id)
    assert second.get("who") == "first", "the second session did not read what the first wrote"
    assert _client_of(first) is _client_of(second), (
        "two Sessions on the same MongoDB URI opened two MongoClients: one per "
        "request, each with its own monitor threads and pool, never closed (#136)"
    )


def test_closing_one_handler_does_not_strand_the_next(mongo_backend):
    """Negative case: a shared client must not turn one close() into an outage."""
    from tina4_python.session import Session

    closed = Session()
    closed.start()
    closed.set("n", 1)
    assert closed.save() is True
    closed._handler.close()

    fresh = Session()
    fresh.start(closed.session_id)
    assert fresh.get("n") == 1, "after one handler closed, a new session could not read the store"
    fresh.set("n", 2)
    assert fresh.save() is True


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    project = tmp_path_factory.mktemp("issue136_project")
    (project / "src" / "routes").mkdir(parents=True)
    (project / "src" / "routes" / "issue136.py").write_text(ROUTES)
    (project / "serve.py").write_text(SERVE)
    port = _free_port()
    env = {
        **os.environ,
        "ISSUE136_PORT": str(port),
        "TINA4_DEBUG": "false",
        "TINA4_SECRET": "issue136-contract-secret-0123456789abcdef",
        "TINA4_SESSION_BACKEND": "mongodb",
        "TINA4_SESSION_MONGO_URI": MONGO_URI,
        "TINA4_SESSION_MONGO_DB": MONGO_DB,
        "TINA4_NO_BROWSER": "true",
    }
    process = subprocess.Popen([sys.executable, "serve.py"], cwd=str(project), env=env)
    try:
        deadline = time.time() + 20
        while time.time() < deadline and process.poll() is None:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail(f"issue136 uvicorn child never became ready (exit={process.poll()})")
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_threads_stay_flat_across_session_requests(server):
    jar = http.cookiejar.CookieJar()
    browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def get(path):
        with browser.open(f"{server}{path}", timeout=10) as response:
            return json.loads(response.read())

    # Warm up: the first session request builds the one client this process needs.
    get("/issue136/visits")
    get("/issue136/visits")
    start = get("/issue136/threads")["threads"]
    for _ in range(REQUESTS):
        last = get("/issue136/visits")
    end = get("/issue136/threads")["threads"]

    assert last == {"visits": REQUESTS + 2}, "the session counter did not persist across requests"
    assert end - start <= 3, (
        f"{REQUESTS} session requests grew the server from {start} to {end} threads: "
        "a MongoClient (monitor threads + pool) is being opened per request (#136)"
    )
