"""
Regression for https://github.com/tina4stack/tina4-python/issues/103.

The router logs `Route registered: METHOD PATH (auth=...)` from
`_register_route`, but Python decorators apply bottom-up, so the *outer*
`@noauth()` / `@secured()` decorator runs AFTER the inner `@post()`/`@get()`
that emitted the log. A public write route therefore spent a moment logged as
`auth=required`, and a secured GET spent a moment logged as `auth=public` --
and a human or AI reader of the startup log took the misleading initial line
as ground truth. In one reported case an AI reviewer drafted a false critical
security finding on top of a `@noauth()` login route.

Fix: `@noauth()` and `@secured()` now emit a corrective `Route auth updated:`
line when they flip the flag on an already-registered route, so the log
sequence ends on the true final state and identifies the responsible
decorator by name.

These tests are REAL: they drive the actual router with the documented
decorator order, capture the actual `Log.debug` output via pytest's
`capsys`, and assert on the real bytes -- no mocks, no monkeypatching.
"""
import os

import pytest

from tina4_python.core.router import Router, get, post, put, patch, delete, noauth, secured


@pytest.fixture(autouse=True)
def clear_routes_and_enable_debug(monkeypatch):
    """Router registry is process-global; wipe between tests. Log.debug is
    gated by TINA4_LOG_LEVEL, so DEBUG must be enabled for these tests --
    monkeypatch scopes the env change to the test."""
    monkeypatch.setenv("TINA4_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("TINA4_DEBUG", "true")
    Router.clear()
    yield
    Router.clear()


def _register_lines(captured_out: str) -> list[str]:
    """Every `Route registered` / `Route auth updated` line, order preserved."""
    return [
        line
        for line in captured_out.splitlines()
        if "Route registered" in line or "Route auth updated" in line
    ]


class TestNoauthEmitsCorrectiveLog:
    def test_noauth_write_route_logs_the_true_final_state(self, capsys):
        # The documented decorator order (SKILL.md, CLAUDE.md): auth OUTSIDE
        # the verb -- Python applies bottom-up, so this is the ONE ordering
        # that reproduces the misleading log.
        @noauth()
        @post("/api/auth/register")
        async def register(request, response):
            return {"ok": True}

        captured = capsys.readouterr()
        lines = _register_lines(captured.out)

        # The initial (misleading-in-isolation) line still appears -- removing
        # it would need to break the register-time contract every other route
        # relies on. The FIX is that a corrective line follows it.
        assert any(
            "Route registered: POST /api/auth/register (auth=required)" in ln
            for ln in lines
        ), f"missing initial register line; got {lines}"

        # The gate: a corrective line MUST follow, naming @noauth and the
        # true final state. Without the fix this line does not exist and the
        # startup log leaves a false claim standing.
        assert any(
            "Route auth updated: POST /api/auth/register (auth=public via @noauth)"
            in ln
            for ln in lines
        ), f"missing corrective @noauth line; got {lines}"

        # Order matters: the corrective line must come AFTER the misleading
        # one, else it does not correct anything.
        register_idx = next(
            i for i, ln in enumerate(lines)
            if "Route registered: POST /api/auth/register" in ln
        )
        corrective_idx = next(
            i for i, ln in enumerate(lines)
            if "Route auth updated: POST /api/auth/register" in ln
        )
        assert corrective_idx > register_idx, (
            f"corrective line came before the misleading one: {lines}"
        )

        # Stored state must agree with the corrective line, or the log would
        # only fix the log without fixing the bug it is trying to describe.
        route = next(
            r for r in Router.get_routes()
            if r["path"] == "/api/auth/register"
        )
        assert route["auth_required"] is False


class TestSecuredEmitsCorrectiveLog:
    def test_secured_get_route_logs_the_true_final_state(self, capsys):
        # GET is public by default, so @secured() also gets caught by the
        # exact same bottom-up-order issue in the other direction.
        @secured()
        @get("/api/admin/stats")
        async def admin_stats(request, response):
            return {"ok": True}

        captured = capsys.readouterr()
        lines = _register_lines(captured.out)

        assert any(
            "Route registered: GET /api/admin/stats (auth=public)" in ln
            for ln in lines
        ), f"missing initial register line; got {lines}"

        assert any(
            "Route auth updated: GET /api/admin/stats (auth=required via @secured)"
            in ln
            for ln in lines
        ), f"missing corrective @secured line; got {lines}"

        route = next(
            r for r in Router.get_routes()
            if r["path"] == "/api/admin/stats"
        )
        assert route["auth_required"] is True


class TestNoCorrectiveLineWhenNothingChanged:
    """The corrective log should ONLY fire when the flag actually flipped --
    otherwise we would double-log every route, defeating its own point."""

    def test_post_without_noauth_gets_one_line_only(self, capsys):
        @post("/api/orders")
        async def create_order(request, response):
            return {"ok": True}

        captured = capsys.readouterr()
        lines = _register_lines(captured.out)

        matching = [ln for ln in lines if "/api/orders" in ln]
        # Exactly ONE line for this route -- the register line. No corrective
        # line, because no decorator touched the flag.
        assert len(matching) == 1, f"expected 1 line, got {matching}"
        assert "Route registered: POST /api/orders (auth=required)" in matching[0]

    def test_get_without_secured_gets_one_line_only(self, capsys):
        @get("/api/products")
        async def list_products(request, response):
            return {"ok": True}

        captured = capsys.readouterr()
        lines = _register_lines(captured.out)

        matching = [ln for ln in lines if "/api/products" in ln]
        assert len(matching) == 1, f"expected 1 line, got {matching}"
        assert "Route registered: GET /api/products (auth=public)" in matching[0]


class TestIssue103ExactRepro:
    """The exact three-route scenario from
    https://github.com/tina4stack/tina4-python/issues/103, plus the
    complementary @secured case that has the same shape. Every stored
    `auth_required` MUST equal the value in the corrective log line for the
    same path -- if the log and the reality drift again, this test fails."""

    def test_three_route_scenario_from_the_issue(self, capsys):
        @noauth()
        @post("/api/auth/register")
        async def register(request, response):
            return {"ok": True}

        @noauth()
        @post("/api/auth/login")
        async def login(request, response):
            return {"ok": True}

        @secured()
        @get("/api/admin/stats")
        async def admin_stats(request, response):
            return {"secret": True}

        captured = capsys.readouterr()
        lines = _register_lines(captured.out)

        # Every corrective line must exist and match reality.
        expected = [
            ("POST", "/api/auth/register", False, "@noauth"),
            ("POST", "/api/auth/login", False, "@noauth"),
            ("GET", "/api/admin/stats", True, "@secured"),
        ]
        for method, path, want_required, decorator in expected:
            want_str = "public" if not want_required else "required"
            marker = (
                f"Route auth updated: {method} {path} "
                f"(auth={want_str} via {decorator})"
            )
            assert any(marker in ln for ln in lines), (
                f"missing corrective line for {method} {path}: "
                f"expected `{marker}` in {lines}"
            )
            route = next(
                r for r in Router.get_routes()
                if r["path"] == path and r["method"] == method
            )
            assert route["auth_required"] is want_required, (
                f"stored state disagrees with the log for {method} {path}"
            )
