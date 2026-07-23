"""D6: TestClient must dispatch through the REAL front controller.

Regression for the cross-framework audit finding. The in-process ``TestClient``
used to call ``Router.match`` directly and invoke the handler itself, so it
FABRICATED ``{"error":"Not found"}`` on a miss and skipped everything the front
controller does around a route (middleware, static files, the real 404/405).
A green test asserting that fabricated body proved nothing about the live server.

``TestClient`` now builds an ASGI scope and dispatches it through
``tina4_python.core.server.app`` — the same entry a live request uses — so:

* an unmatched path returns the framework's REAL 404 (an HTML error page), NOT
  the fabricated ``{"error":"Not found"}`` JSON the old client invented;
* a matched route returns its real response through the full pipeline;
* the response exposes ``.status`` (parity with Ruby ``attr_reader :status``,
  PHP ``readonly int $status``, Node ``readonly status``) — Python was the lone
  outlier with ``.status_code``.

NOT a mock: real Router registration, the real ``core.server.app`` ASGI entry,
real dispatch. Routes are registered in ``setup_method`` so they survive suites
that clear the registry.
"""
from __future__ import annotations

import os

os.environ["TINA4_SECRET"] = "d6-front-controller-secret"

from tina4_python.core.router import get
from tina4_python.test_client import TestClient, TestResponse


class TestTestClientFrontController:
    def setup_method(self, _method):
        @get("/d6-open")
        async def _open(request, response):
            return response({"ok": True})

    def test_unmatched_path_is_the_real_404_not_a_fabricated_body(self):
        # THE discriminator. Pre-fix this returned 404 with the invented body
        # {"error":"Not found"} that the server never sends; the front controller
        # returns the framework's real 404 page.
        r = TestClient().get("/d6-definitely-not-a-route")
        assert r.status == 404
        body = r.body.decode() if isinstance(r.body, (bytes, bytearray)) else str(r.body)
        assert '"error": "Not found"' not in body and '"error":"Not found"' not in body, (
            "TestClient still fabricates the pre-fix 404 body instead of dispatching "
            "through the front controller"
        )

    def test_matched_route_runs_through_the_pipeline(self):
        r = TestClient().get("/d6-open")
        assert r.status == 200
        assert r.json() == {"ok": True}

    def test_response_exposes_status_for_cross_framework_parity(self):
        # Ruby/PHP/Node all expose `status`; Python used to be the outlier with
        # `status_code`. Lock the parity accessor and lock OUT the old name so a
        # future revert is caught.
        r = TestClient().get("/d6-open")
        assert hasattr(r, "status")
        assert not hasattr(TestResponse, "status_code"), (
            "status_code came back — Python has diverged from the other three again"
        )
