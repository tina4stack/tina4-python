# tests/test_tina4_official_guide.py
"""
OFFICIAL Tina4 Python Routing Guide – Full Compliance Test Suite
Based on: https://tina4stack.github.io/tina4python/routing.html (2025 version)
Tests EVERY feature-by-feature using the real, current Tina4 Python API.
"""

import json
import pytest
import requests
from urllib.parse import urljoin

# ------------------------------------------------------------------
# Configuration – adjust only if your Tina4 runs on a different port
# ------------------------------------------------------------------
import os
BASE_URL = "http://localhost:7145"
session = requests.Session()
session.headers.update({"Authorization": "Bearer "+os.getenv("API_KEY", "38168ba8aad6c91ba13d959c3f91c7a7")})


def get(path, **kwargs):
    return session.get(urljoin(BASE_URL, path), **kwargs)


def post(path, **kwargs):
    return session.post(urljoin(BASE_URL, path), **kwargs)


def put(path, **kwargs):
    return session.put(urljoin(BASE_URL, path), **kwargs)


def delete(path, **kwargs):
    return session.delete(urljoin(BASE_URL, path), **kwargs)


# ------------------------------------------------------------------
# 1. Basic GET Route
# ------------------------------------------------------------------
def test_basic_get_route():
    r = get("/hello")
    assert r.status_code == 200
    assert r.text.strip() == "Hello, Tina4 Python!"


# ------------------------------------------------------------------
# 2. POST Route with body parsing
# ------------------------------------------------------------------
def test_post_route_with_body():
    payload = {"name": "Alice", "age": 30}
    r = post("/submit", json=payload)
    assert r.status_code == 200
    assert "Alice" in r.text
    assert "30" in r.text


# ------------------------------------------------------------------
# 3. All HTTP Methods
# ------------------------------------------------------------------
def test_get_users():
    r = get("/users")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["users"], list)
    assert "Alice" in data["users"]


def test_post_create_user():
    r = post("/users", json={"name": "Charlie"})
    assert r.status_code == 200
    assert r.json()["created"] == "Charlie"


def test_put_update_user():
    r = put("/users/123", json={"name": "David"})
    assert r.status_code == 200
    assert "David" in r.text
    assert "123" in r.text


def test_delete_user():
    r = delete("/users/999")
    assert r.status_code == 200
    assert "999" in r.text


# ------------------------------------------------------------------
# 4. Path Parameters (injected as function args)
# ------------------------------------------------------------------
def test_path_parameters():
    r = get("/users/42/posts/7")
    assert r.status_code == 200
    assert "42" in r.text
    assert "7" in r.text


# ------------------------------------------------------------------
# 5. Query Parameters via request.params
# ------------------------------------------------------------------
def test_query_parameters():
    r = get("/search?q=tina4&page=2")
    assert r.status_code == 200
    assert "tina4" in r.text
    assert "2" in r.text


# ------------------------------------------------------------------
# 6. Route Groups / Namespaces (via file structure or prefix)
# ------------------------------------------------------------------
def test_admin_route_with_prefix():
    r = get("/admin/dashboard")
    assert r.status_code == 200
    assert "Admin Dashboard" in r.text


# ------------------------------------------------------------------
# 7. Middleware – before_route & after_route
# ------------------------------------------------------------------
def test_middleware_auth_blocked():
    r = get("/protected")
    assert r.status_code == 401
    assert "Unauthorized" in r.text


def test_middleware_auth_passed():
    r = get("/protected", headers={"Authorization": "Bearer valid-jwt-token"})
    assert r.status_code == 200
    assert "Secure data" in r.text


def test_middleware_adds_header():
    r = get("/protected", headers={"Authorization": "Bearer valid-jwt-token"})
    assert r.headers.get("X-Custom") == "Processed"


# ------------------------------------------------------------------
# 8. Error Handling in Routes
# ------------------------------------------------------------------
def test_divide_by_zero():
    r = get("/divide/0")
    assert r.status_code == 400
    assert "Cannot divide by zero" in r.text


def test_invalid_number():
    r = get("/divide/abc")
    assert r.status_code == 400
    assert "Invalid number" in r.text


# ------------------------------------------------------------------
# 9. Async Handlers
# ------------------------------------------------------------------
def test_async_db_route():
    r = get("/async-db")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)  # assumes it returns users


# ------------------------------------------------------------------
# 10. Response Types
# ------------------------------------------------------------------
def test_response_string():
    r = get("/hello")
    assert r.headers["content-type"].startswith("text/plain")

def test_response_json_auto():
    r = get("/api/health")
    assert r.headers["content-type"] == "application/json"
    assert r.json()["status"] == "ok"


def test_response_redirect():
    r = get("/old-page")
    assert r.status_code == 302
    assert r.headers["location"] == "/new-page"


def test_render_template_twig():
    r = get("/page/about")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "John Doe" in r.text
    assert "<title>About Us" in r.text


# ------------------------------------------------------------------
# 11. Swagger / OpenAPI Auto-Documentation
# ------------------------------------------------------------------
def test_swagger_ui_served():
    r = get("/swagger")
    assert r.status_code == 200
    assert "Swagger UI" in r.text or "Redoc" in r.text


def test_swagger_json_endpoint():
    r = get("/swagger.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec["openapi"].startswith("3.")
    assert "/api/users" in spec["paths"]
    assert "Create a new user" in str(spec)


# ------------------------------------------------------------------
# 12. @secured() decorator
# ------------------------------------------------------------------
def test_secured_route_without_token():
    r = get("/profile")
    assert r.status_code in (401, 403)


def test_secured_route_with_token():
    # Assumes your app sets a valid token via login or header
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.x"  # dummy
    r = get("/profile", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert "user" in r.text.lower()


# ------------------------------------------------------------------
# 13. Static Files Auto-Served
# ------------------------------------------------------------------
def test_static_css():
    r = get("/css/style.css")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/css"


def test_static_image():
    r = get("/images/logo.png")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")


# ------------------------------------------------------------------
# 14. WebSocket Route
# ------------------------------------------------------------------
from tina4_python.Websocket import Websocket
def test_websocket_connection():
    from simple_websocket import Client
    try:
        ws = Client.connect("ws://localhost:7145/chat")
        ws.send("Hello Tina4!")
        reply = ws.recv()
        assert reply == "Echo: Hello Tina4!"
        ws.close()
    except Exception as e:
        pytest.fail(f"WebSocket test failed: {e}")


# ------------------------------------------------------------------
# 15. 404 Handler
# ------------------------------------------------------------------
def test_404_not_found():
    r = get("/this-does-not-exist-404")
    assert r.status_code == 404
    assert "Not Found" in r.text or "404" in r.text


# ------------------------------------------------------------------
# Run with: pytest tests/test_tina4_official_guide.py -v -s
# ------------------------------------------------------------------