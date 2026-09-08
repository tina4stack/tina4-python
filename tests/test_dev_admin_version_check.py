# Tina4 - The Intelligent Native Application 4ramework
# Copyright 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# The dev-admin version check must not report "up to date" for a check it never
# made. It used to answer latest == current whenever the call to PyPI failed,
# and the toolbar renders that as a green "You are up to date!" - so a developer
# several releases behind, on a machine with no route out, was told the opposite
# of the truth, and the toolbar's own "Could not check for updates" branch could
# never fire because the failure arrived as a success.
#
# No mocks: a REAL local HTTP server stands in for PyPI where the body has to be
# controlled, and a REAL closed port stands in for "no route out". The registry
# URL is chosen with TINA4_VERSION_CHECK_URL, the same seam an operator points at
# a mirror with.
import asyncio
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from tina4_python import __version__
from tina4_python.core.response import Response
from tina4_python.dev_admin import _api_version_check, toolbar_js


def _check(url, monkeypatch):
    """Run the REAL handler with the registry URL pointed at `url`."""
    monkeypatch.setenv("TINA4_VERSION_CHECK_URL", url)
    resp = Response()
    asyncio.run(_api_version_check(None, resp))
    return json.loads(resp.content)


class _Handler(BaseHTTPRequestHandler):
    body = b"{}"

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, *args):
        pass


def _serve(body):
    """Start a REAL local HTTP server returning `body`. Returns (url, stop)."""
    handler = type("H", (_Handler,), {"body": body})
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address
    return f"http://{host}:{port}/", server.shutdown


def _closed_port_url():
    """A real address with nothing listening - bind then close to free the port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/"


def test_an_unreachable_registry_is_not_reported_as_up_to_date(monkeypatch):
    payload = _check(_closed_port_url(), monkeypatch)
    assert payload["latest"] is None, "a check that did not happen must not answer with a version"
    assert payload["latest"] != payload["current"], 'the toolbar reads latest == current as "you are up to date"'
    assert payload.get("error"), "the reason has to reach the client"
    assert payload["current"] == __version__


def test_an_answer_with_no_version_is_not_reported_as_up_to_date(monkeypatch):
    url, stop = _serve(b'{"info": {}}')
    try:
        payload = _check(url, monkeypatch)
    finally:
        stop()
    assert payload["latest"] is None
    assert payload.get("error")


def test_a_reachable_registry_reports_the_version(monkeypatch):
    url, stop = _serve(b'{"info": {"version": "3.13.200"}}')
    try:
        payload = _check(url, monkeypatch)
    finally:
        stop()
    assert payload["latest"] == "3.13.200"
    assert "error" not in payload


def test_the_toolbar_acts_on_a_missing_latest_before_comparing_versions():
    js = toolbar_js()
    assert "couldNotCheck" in js, "no branch for a check that did not happen"
    assert "if (!latest) { couldNotCheck" in js
    assert js.index("if (!latest)") < js.index("if (latest === current)")
