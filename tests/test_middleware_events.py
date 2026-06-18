# Lock-in tests for E1 (event listener isolation) + M1 (middleware
# ordering) + M2 (middleware-throw 500 / after-on-4xx rule).
#
# These are the regression guards for the "visible-but-resilient"
# philosophy: an event bus never lets one listener break the others, and
# the middleware chain is deterministic (registration/definition order),
# never silently skips a middleware, and a throwing middleware yields a
# logged clean 500 instead of crashing the worker.
#
# Same contract is mirrored in tina4-php, tina4-ruby, tina4-nodejs.
import pytest

from tina4_python.core.events import on, emit, emit_async, clear
from tina4_python.core.middleware import Middleware
from tina4_python.core.request import Request
from tina4_python.core.response import Response
from tina4_python.core.server import (
    _run_before_middleware,
    _run_after_middleware,
)


@pytest.fixture(autouse=True)
def clean_events():
    clear()
    yield
    clear()


def _make_request() -> Request:
    scope = {
        "method": "GET",
        "path": "/test",
        "query_string": b"",
        "headers": [],
        "scheme": "http",
    }
    return Request.from_scope(scope, body=b"")


# ────────────────────────────────────────────────────────────────────
# E1 — a throwing listener must NOT silently abort the rest of emit()
# ────────────────────────────────────────────────────────────────────


class TestEventListenerIsolation:
    def test_middle_listener_throws_others_still_run(self):
        """3 listeners, the MIDDLE one throws → 1st and 3rd STILL run,
        emit() does NOT raise, and returns the surviving results (the
        failed slot is None)."""
        ran = []

        @on("evt", priority=30)
        def first(x):
            ran.append("first")
            return "r1"

        @on("evt", priority=20)
        def boom(x):
            ran.append("boom")
            raise RuntimeError("listener exploded")

        @on("evt", priority=10)
        def third(x):
            ran.append("third")
            return "r3"

        results = emit("evt", "payload")  # must NOT raise

        assert ran == ["first", "boom", "third"], \
            f"a throwing listener aborted the rest of emit(); ran={ran}"
        # N listeners → N result slots, in priority order, failed = None
        assert results == ["r1", None, "r3"]

    def test_error_is_logged_never_silent(self, capsys):
        """The listener error must be LOGGED (event name + error), never
        silently swallowed."""
        from tina4_python.debug import Log
        Log.configure(level="warning", production=False)

        @on("evt.logged")
        def boom():
            raise ValueError("kaboom")

        emit("evt.logged")
        out = capsys.readouterr().out
        assert "evt.logged" in out
        assert "kaboom" in out or "ValueError" in out

    def test_strict_reraises_on_first_error(self):
        """strict=True re-raises on the first listener error instead of
        isolating it — and stops before later listeners run."""
        ran = []

        @on("evt.strict", priority=20)
        def boom():
            ran.append("boom")
            raise RuntimeError("strict boom")

        @on("evt.strict", priority=10)
        def after():
            ran.append("after")

        with pytest.raises(RuntimeError, match="strict boom"):
            emit("evt.strict", strict=True)
        assert ran == ["boom"], "strict mode must stop at the first error"

    def test_non_throwing_listeners_unchanged(self):
        """Existing contract: N non-throwing listeners still yield N
        results in priority order."""
        @on("evt.ok", priority=10)
        def a():
            return 1

        @on("evt.ok", priority=5)
        def b():
            return 2

        assert emit("evt.ok") == [1, 2]

    @pytest.mark.asyncio
    async def test_emit_async_isolates_each_listener(self):
        """emit_async isolates each awaited listener — one rejection does
        not abort the others; failed slot is None."""
        ran = []

        @on("evt.async", priority=30)
        async def first():
            ran.append("first")
            return "a1"

        @on("evt.async", priority=20)
        async def boom():
            ran.append("boom")
            raise RuntimeError("async boom")

        @on("evt.async", priority=10)
        def third():  # sync listener still runs
            ran.append("third")
            return "a3"

        results = await emit_async("evt.async")
        assert ran == ["first", "boom", "third"]
        assert results == ["a1", None, "a3"]

    @pytest.mark.asyncio
    async def test_emit_async_strict_reraises(self):
        @on("evt.async.strict")
        async def boom():
            raise RuntimeError("async strict")

        with pytest.raises(RuntimeError, match="async strict"):
            await emit_async("evt.async.strict", strict=True)


# ────────────────────────────────────────────────────────────────────
# M1 — middleware ordering: definition order within a class, NOT dir()
#       alphabetical; registration order across classes; none skipped.
# ────────────────────────────────────────────────────────────────────


class TestMiddlewareDefinitionOrder:
    def test_within_class_is_definition_order_not_alphabetical(self):
        """before_* methods run in the order they are DEFINED in the class
        body. Names are chosen so alphabetical order (before_alpha,
        before_mike, before_zulu) would differ from definition order."""
        class Mw:
            @staticmethod
            def before_zulu(req, resp):
                return req, resp

            @staticmethod
            def before_mike(req, resp):
                return req, resp

            @staticmethod
            def before_alpha(req, resp):
                return req, resp

        names = Middleware._discover_methods(Mw, "before_")
        assert names == ["before_zulu", "before_mike", "before_alpha"], \
            f"middleware methods must run in definition order, got {names}"
        # Prove it is NOT the old alphabetical behaviour:
        assert names != sorted(names)

    def test_after_methods_also_definition_order(self):
        class Mw:
            @staticmethod
            def after_zebra(req, resp):
                return req, resp

            @staticmethod
            def after_apple(req, resp):
                return req, resp

        assert Middleware._discover_methods(Mw, "after_") == [
            "after_zebra", "after_apple"
        ]

    def test_dispatch_runs_before_in_definition_order(self):
        """End-to-end through the server dispatcher: definition order."""
        trace = []

        class Mw:
            @staticmethod
            def before_zulu(req, resp):
                trace.append("zulu")
                return req, resp

            @staticmethod
            def before_alpha(req, resp):
                trace.append("alpha")
                return req, resp

        route = {"handler": None, "middleware": [Mw]}
        _run_before_middleware(_make_request(), Response(), route)
        assert trace == ["zulu", "alpha"]


class TestMiddlewareRegistrationOrder:
    def test_n_middleware_all_run_exactly_once_in_order(self):
        """N middleware classes attached in a known order execute in THAT
        order, each exactly once, none skipped. This guards the Node
        double-advance index-skip bug at the parity level."""
        trace = []

        def make_mw(tag):
            class Mw:
                @staticmethod
                def before_tag(req, resp):
                    trace.append(tag)
                    return req, resp
            return Mw

        order = ["one", "two", "three", "four", "five"]
        route = {"handler": None, "middleware": [make_mw(t) for t in order]}

        _run_before_middleware(_make_request(), Response(), route)

        assert trace == order, f"middleware skipped or reordered: {trace}"
        assert len(trace) == len(order) == len(set(trace))


# ────────────────────────────────────────────────────────────────────
# M2 — a throwing middleware → logged clean 500 (no unhandled crash);
#       after_* still run on a 4xx short-circuit.
# ────────────────────────────────────────────────────────────────────


class TestMiddlewareThrow:
    def test_before_throw_yields_clean_500_and_skips_handler(self, capsys):
        """A before_* middleware that THROWS must be caught, logged, and
        produce a clean 500 — never an unhandled crash. The handler is
        skipped."""
        from tina4_python.debug import Log
        Log.configure(level="error", production=False)

        class Mw:
            @staticmethod
            def before_boom(req, resp):
                raise RuntimeError("middleware exploded")

        route = {"handler": None, "middleware": [Mw]}
        req, resp, skip = _run_before_middleware(_make_request(), Response(), route)

        assert resp.status_code == 500
        assert skip is True, "a throwing before_* must skip the route handler"
        out = capsys.readouterr().out
        assert "Mw" in out and ("RuntimeError" in out or "exploded" in out), \
            "middleware throw must be logged"

    def test_after_throw_yields_clean_500_and_continues(self, capsys):
        """A throwing after_* is logged + converted to 500; later after_*
        still run."""
        from tina4_python.debug import Log
        Log.configure(level="error", production=False)
        ran = []

        class Mw:
            @staticmethod
            def after_boom(req, resp):
                ran.append("boom")
                raise RuntimeError("after exploded")

            @staticmethod
            def after_log(req, resp):
                ran.append("log")
                return req, resp

        route = {"handler": None, "middleware": [Mw]}
        req, resp = _run_after_middleware(_make_request(), Response(), route)

        assert resp.status_code == 500
        assert ran == ["boom", "log"], "later after_* must still run after a throw"


class TestAfterOn4xxRule:
    def test_after_runs_even_when_before_short_circuits(self):
        """Documented rule: after_* ALWAYS run, even when a before_* set
        status >= 400 and the handler was skipped — so after-middleware can
        still add headers / logging on error responses."""
        ran = []

        class Mw:
            @staticmethod
            def before_gate(req, resp):
                resp.status(403)
                return req, resp

            @staticmethod
            def after_headers(req, resp):
                ran.append("after")
                resp.header("x-audited", "yes")
                return req, resp

        route = {"handler": None, "middleware": [Mw]}
        req, resp, skip = _run_before_middleware(_make_request(), Response(), route)
        assert skip is True
        assert resp.status_code == 403

        # Dispatcher calls _run_after_middleware unconditionally:
        req, resp = _run_after_middleware(req, resp, route)
        assert ran == ["after"], "after_* must run on a 4xx short-circuit"
        assert ("x-audited", "yes") in resp._headers
