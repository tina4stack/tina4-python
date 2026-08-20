"""RBAC role/permission guards — Feature 138 / ADR-0058.

The contract answer key is tina4-documentation/plan/v3/fixtures/rbac_contract.json.
Every case drives a REAL request through the front controller (TestClient), with
REAL HS256 tokens minted by Auth.get_token. NO MOCKS: the guard is exercised end
to end through the dispatch auth gate.

`role()`/`can()` read the VERIFIED JWT payload only. A guard implies auth (a
guarded GET still needs a token): no token -> 401, valid-but-unauthorised -> 403.
"""
import pytest

from tina4_python.auth import get_token
from tina4_python.core.router import Router
from tina4_python.test_client import TestClient


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    # Generator and validator resolve the same secret so a minted token verifies.
    monkeypatch.setenv("TINA4_SECRET", "rbac-contract-secret")
    yield


async def _ok(request, response):
    return response({"ok": True})


@pytest.fixture(autouse=True)
def _routes():
    """Register the guarded probe routes fresh before EVERY test, via the
    imperative Router.add(...).role()/.can() API — immune to another file's
    Router.clear() (the isolation pattern test_csrf_middleware.py established).
    These are GET routes (public by default) so the guard is what makes them
    require auth, which is exactly the 401-implication under test."""
    Router.add("GET", "/__rbac/role_admin", _ok).role("admin")
    Router.add("GET", "/__rbac/role_any", _ok).role("admin", "editor")
    Router.add("GET", "/__rbac/role_stacked", _ok).role("admin").role("editor")
    Router.add("GET", "/__rbac/can_delete", _ok).can("posts.delete")
    Router.add("GET", "/__rbac/can_users", _ok).can("users.delete")
    yield


def _bearer(payload):
    return {"Authorization": f"Bearer {get_token(payload)}"}


# ── rbac-role-allows ───────────────────────────────────────────
def test_role_claim_allows_the_route():
    resp = TestClient().get("/__rbac/role_admin", headers=_bearer({"sub": "u", "roles": ["admin"]}))
    assert resp.status == 200
    assert resp.json()["ok"] is True


# ── rbac-role-denies-403 ───────────────────────────────────────
def test_missing_role_is_forbidden_403():
    resp = TestClient().get("/__rbac/role_admin", headers=_bearer({"sub": "u", "roles": ["viewer"]}))
    assert resp.status == 403


# ── rbac-unauthenticated-401 ───────────────────────────────────
def test_unauthenticated_guard_is_401():
    # No token at all -> 401 (unauthenticated), NOT 403. A guard implies auth.
    resp = TestClient().get("/__rbac/role_admin")
    assert resp.status == 401


# ── rbac-role-or-and ───────────────────────────────────────────
def test_role_list_is_any_of():
    # role("admin", "editor") passes on EITHER.
    assert TestClient().get("/__rbac/role_any", headers=_bearer({"sub": "u", "roles": ["editor"]})).status == 200
    assert TestClient().get("/__rbac/role_any", headers=_bearer({"sub": "u", "roles": ["admin"]})).status == 200
    # Neither listed role -> 403.
    assert TestClient().get("/__rbac/role_any", headers=_bearer({"sub": "u", "roles": ["viewer"]})).status == 403


def test_stacked_guards_are_all_of():
    # .role("admin").role("editor") requires BOTH (AND across stacked guards).
    assert TestClient().get("/__rbac/role_stacked", headers=_bearer({"sub": "u", "roles": ["admin", "editor"]})).status == 200
    # Missing one of the two -> 403.
    assert TestClient().get("/__rbac/role_stacked", headers=_bearer({"sub": "u", "roles": ["admin"]})).status == 403


# ── rbac-can-permission ────────────────────────────────────────
def test_permission_grants_the_route():
    resp = TestClient().get("/__rbac/can_delete", headers=_bearer({"sub": "u", "permissions": ["posts.delete"]}))
    assert resp.status == 200


def test_missing_permission_is_forbidden_403():
    resp = TestClient().get("/__rbac/can_delete", headers=_bearer({"sub": "u", "permissions": ["posts.read"]}))
    assert resp.status == 403


def test_role_alone_does_not_satisfy_a_permission_guard():
    # A role is not a permission; the core never expands roles into permissions.
    resp = TestClient().get("/__rbac/can_delete", headers=_bearer({"sub": "u", "roles": ["admin"]}))
    assert resp.status == 403


# ── rbac-wildcard-grant ────────────────────────────────────────
def test_wildcard_permission_grants_within_scope():
    # Granted "posts.*" satisfies required "posts.delete".
    resp = TestClient().get("/__rbac/can_delete", headers=_bearer({"sub": "u", "permissions": ["posts.*"]}))
    assert resp.status == 200


def test_superuser_star_grants_everything():
    resp = TestClient().get("/__rbac/can_delete", headers=_bearer({"sub": "u", "permissions": ["*"]}))
    assert resp.status == 200


def test_wildcard_does_not_cross_scope():
    # Granted "posts.*" must NOT satisfy required "users.delete".
    resp = TestClient().get("/__rbac/can_users", headers=_bearer({"sub": "u", "permissions": ["posts.*"]}))
    assert resp.status == 403


# ── rbac-verified-payload-only ─────────────────────────────────
def test_spoofed_role_header_is_ignored():
    # A viewer token with a spoofed X-Role: admin header is still forbidden —
    # authorization trusts only the signed claim, never a raw header.
    headers = _bearer({"sub": "u", "roles": ["viewer"]})
    headers["X-Role"] = "admin"
    resp = TestClient().get("/__rbac/role_admin", headers=headers)
    assert resp.status == 403


# ── rbac-legacy-singular-role ──────────────────────────────────
def test_legacy_singular_role_is_coerced():
    # A legacy singular `role: "admin"` claim is read as roles: ["admin"].
    resp = TestClient().get("/__rbac/role_admin", headers=_bearer({"sub": "u", "role": "admin"}))
    assert resp.status == 200
