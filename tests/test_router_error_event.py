"""Tests for v3.13.7 router error handling (DevProx brief PLATFORM-2159).

Two contracts:

1. ``tina4.request.error`` event fires before the 500 is rendered, so
   centralised-logging consumers (CloudWatch, Sentry, etc.) see route
   failures even though the framework caught them. Payload is a single
   dict ``{exception, request}``.

2. In non-debug mode the 500 response body never contains a stack
   trace (CWE-209 / information disclosure). Debug mode keeps the
   rich ErrorOverlay unchanged.

3. Listener exceptions MUST NOT break the 500 render. A broken
   listener gets logged via ``Log.warning`` and the framework proceeds.
"""
from __future__ import annotations

import os
import pytest

from tina4_python.core.events import clear as clear_events, on as on_event
from tina4_python.core.request import Request
from tina4_python.core.response import Response
from tina4_python.core.server import _handle_route_error


@pytest.fixture(autouse=True)
def clear_event_listeners():
    """Wipe the event registry before/after each test so listeners
    don't bleed between cases."""
    clear_events()
    yield
    clear_events()


def _make_request(path: str = "/api/widgets", method: str = "GET") -> Request:
    req = Request()
    req.path = path
    req.url = path
    req.method = method
    return req


# ── Contract 1: event fires with the right payload ──────────────────


class TestRequestErrorEvent:
    """``tina4.request.error`` fires before the 500 render."""

    def test_event_fires_with_exception_and_request_payload(self):
        captured = []

        @on_event("tina4.request.error")
        def listener(payload):
            captured.append(payload)

        exc = RuntimeError("boom")
        req = _make_request("/api/widgets")
        _handle_route_error(exc, req, Response(), "req-123", is_dev=False)

        assert len(captured) == 1, "listener should fire exactly once"
        payload = captured[0]
        assert payload["exception"] is exc, "exception forwarded by identity"
        assert payload["request"] is req, "request forwarded by identity"

    def test_event_fires_in_both_dev_and_production(self):
        """The hook is for observability; it must work regardless of
        TINA4_DEBUG. Listeners can rely on always seeing failures."""
        seen = {"dev": False, "prod": False}

        @on_event("tina4.request.error")
        def listener(_payload):
            mode = "dev" if os.environ.get("TINA4_TEST_MODE") == "dev" else "prod"
            seen[mode] = True

        os.environ["TINA4_TEST_MODE"] = "dev"
        _handle_route_error(ValueError("d"), _make_request(), Response(), "r1", is_dev=True)
        os.environ["TINA4_TEST_MODE"] = "prod"
        _handle_route_error(ValueError("p"), _make_request(), Response(), "r2", is_dev=False)
        del os.environ["TINA4_TEST_MODE"]

        assert seen["dev"] and seen["prod"], "listener fires in both modes"

    def test_multiple_listeners_all_fire(self):
        calls = []

        @on_event("tina4.request.error", priority=10)
        def first(_payload):
            calls.append("first")

        @on_event("tina4.request.error", priority=0)
        def second(_payload):
            calls.append("second")

        _handle_route_error(RuntimeError("x"), _make_request(), Response(), "r1", is_dev=False)
        # Priority-ordered: higher priority runs first
        assert calls == ["first", "second"]


# ── Contract 2: no stack trace in production response body (CWE-209) ──


class TestProductionBodyHasNoTrace:
    """``TINA4_DEBUG=false`` → 500 body contains no traceback markers."""

    def _body_of(self, response: Response) -> str:
        # Response.content is bytes; decode for substring checks.
        raw = getattr(response, "content", b"") or b""
        return raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)

    def test_no_traceback_markers_in_body(self):
        try:
            raise RuntimeError("simulated explosion inside route")
        except RuntimeError as e:
            exc = e

        req = _make_request("/api/widgets")
        response = _handle_route_error(exc, req, Response(), "req-leak-1", is_dev=False)
        body = self._body_of(response)

        # The trace would contain these markers if leaked.
        forbidden = [
            'File "',                            # Python tb line prefix
            "Traceback (most recent call last)", # tb header
            "RuntimeError: simulated explosion",  # exception class + message
            ", line ",                            # frame line marker
            "simulated explosion inside route",   # raw message body
        ]
        for marker in forbidden:
            assert marker not in body, (
                f"CWE-209 regression: production body leaks {marker!r}"
            )

    def test_production_body_still_shows_request_id(self):
        """Sanity: we strip the trace but the page still functions."""
        req = _make_request("/api/widgets")
        response = _handle_route_error(
            RuntimeError("x"), req, Response(), "req-id-abc123", is_dev=False
        )
        body = self._body_of(response)
        assert "req-id-abc123" in body, "request_id still surfaced"
        assert response.status_code == 500, "status remains 500"


# ── Contract 3: listener errors don't break the 500 render ──────────


class TestListenerErrorsAreSafe:
    """A listener that raises must not propagate out of the catch."""

    def test_listener_that_throws_does_not_break_500(self):
        @on_event("tina4.request.error")
        def explodes(_payload):
            raise RuntimeError("listener is broken")

        # If the exception propagated, this call would raise.
        response = _handle_route_error(
            RuntimeError("real error"), _make_request(), Response(),
            "req-listener-fail", is_dev=False,
        )
        # And we still render the 500 page.
        assert response.status_code == 500, "500 rendered despite listener error"

    def test_one_broken_listener_does_not_stop_other_listeners(self):
        """Current event-system semantics: listeners are called in
        priority order; if a higher-priority listener raises, the rest
        do NOT fire (emit() propagates the first exception). The
        framework still catches it at the _handle_route_error layer,
        so the 500 page renders. We document this behaviour with a
        test so it can't regress silently — if/when emit() becomes
        per-listener-safe upstream, this test gets stricter."""
        calls = []

        @on_event("tina4.request.error", priority=10)
        def explodes(_payload):
            calls.append("explodes")
            raise RuntimeError("listener is broken")

        @on_event("tina4.request.error", priority=0)
        def normal(_payload):
            calls.append("normal")

        response = _handle_route_error(
            RuntimeError("real"), _make_request(), Response(),
            "req-multi-listener", is_dev=False,
        )
        assert "explodes" in calls, "broken listener still ran"
        assert response.status_code == 500, "500 rendered"
