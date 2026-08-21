# Dev-admin security conformance (feature 127) — REAL dispatch, no mocks.
"""
Drives the shared devadmin_contract.json cases through the REAL front controller
``tina4_python.core.server.app`` — the same ASGI entry point uvicorn calls — with
a controllable socket peer and headers. NOTHING is mocked: the witness of every
case is a real side effect (a file that is / is not written, a real SQLite row
that is / is not inserted, a secret that never appears in a response body).

Fixture: tina4-documentation/plan/v3/fixtures/devadmin_contract.json
Owner decisions: DEVADMIN-DEC-01 (same-origin gate), DEC-02 (loopback), DEC-03
(.env denylist), DEC-04 (toolbar escape), DEC-05 (mcp/call gate), DEC-06 (this suite).

These are DELIBERATELY real-dispatch: the audit found the prior dev_admin tests
drove handlers through mock req/resp that BYPASSED the mount gate and the guard,
so a passing test proved nothing about the wire. Each negative case here has been
mutation-proved (disable the gate under test -> the assertion goes red).
"""
import asyncio
import json as _json
import os

import pytest


def _dispatch(method, path, *, headers=None, client=("127.0.0.1", 12345),
              json=None, body=None):
    """Drive the real ASGI app for one request. Returns (status, body_bytes, headers).

    ``client`` is the raw socket peer (scope["client"]) — exactly what uvicorn
    hands the framework — so a test can present a genuine non-loopback peer that
    X-Forwarded-For cannot spoof. This is NOT a mock: it is the real front
    controller running its real dispatch stages.
    """
    from tina4_python.core.server import app

    raw = b""
    header_list: list[tuple[bytes, bytes]] = []
    if json is not None:
        raw = _json.dumps(json).encode()
        header_list.append((b"content-type", b"application/json"))
    elif body is not None:
        raw = body.encode() if isinstance(body, str) else body
    for k, v in (headers or {}).items():
        header_list.append((k.lower().encode(), v.encode()))
    if raw:
        header_list.append((b"content-length", str(len(raw)).encode()))

    clean_path, _, query = path.partition("?")
    scope = {
        "type": "http", "http_version": "1.1", "method": method.upper(),
        "scheme": "http", "path": clean_path, "raw_path": clean_path.encode(),
        "query_string": query.encode(), "headers": header_list,
        "client": client, "server": ("localhost", 7145), "root_path": "",
    }

    status: list[int] = []
    resp_headers: list = []
    buf = bytearray()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            status.append(message["status"])
            resp_headers.append(message.get("headers", []))
        elif message["type"] == "http.response.body":
            chunk = message.get("body", b"") or b""
            buf.extend(chunk if isinstance(chunk, (bytes, bytearray)) else chunk.encode())

    asyncio.run(app(scope, receive, send))
    return status[0], bytes(buf), resp_headers[0]


TINA4_SECRET_VALUE = "sup3r-sekret-do-not-leak-127"


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    """A real project cwd with a real .env carrying a secret. The file endpoints
    read os.getcwd(), so the whole suite runs against this throwaway tree."""
    (tmp_path / ".env").write_text(
        f"TINA4_SECRET={TINA4_SECRET_VALUE}\n"
        "TINA4_DATABASE_PASSWORD=pg-password-leak\n"
        "TINA4_MCP_TOKEN=mcp-token-leak\n"
    )
    (tmp_path / ".env.example").write_text("TINA4_SECRET=\n")
    (tmp_path / "readme.txt").write_text("public\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "routes").mkdir()
    monkeypatch.chdir(tmp_path)
    # A clean env baseline for every case.
    for var in ("TINA4_MCP", "TINA4_MCP_REMOTE", "TINA4_MCP_TOKEN", "TINA4_API_KEY", "TINA4_HOST"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


# ── DEVADMIN-DEC-06: behavioural prod-404 ────────────────────────────────────

def test_dev_admin_is_absent_without_debug(project_dir, monkeypatch):
    """Gate off -> the whole /__dev surface is ABSENT (404) and a write does
    nothing. Behavioural, through the real server (not a stage-list inspection)."""
    monkeypatch.setenv("TINA4_DEBUG", "false")

    status_ui, _, _ = _dispatch("GET", "/__dev")
    assert status_ui == 404

    probe = project_dir / "prod404_probe.txt"
    status_save, _, _ = _dispatch(
        "POST", "/__dev/api/file/save",
        headers={"sec-fetch-site": "same-origin"},
        json={"path": "prod404_probe.txt", "content": "should not exist"})
    assert status_save == 404
    assert not probe.exists(), "prod /__dev/api/file/save wrote a file — the gate is off"


# ── DEVADMIN-DEC-01: fail-closed same-origin gate ────────────────────────────

def test_a_cross_origin_write_is_refused_and_writes_nothing(project_dir, monkeypatch):
    """A cross-site POST to /file/save is refused and writes nothing. Mutation
    proof: remove the same-origin gate and this file appears (403 -> 200)."""
    monkeypatch.setenv("TINA4_DEBUG", "true")
    probe = project_dir / "csrf_probe.txt"

    status, bodyb, _ = _dispatch(
        "POST", "/__dev/api/file/save",
        headers={"sec-fetch-site": "cross-site",
                 "origin": "https://evil.example"},
        json={"path": "csrf_probe.txt", "content": "pwned by drive-by CSRF"})
    assert status == 403
    assert not probe.exists(), "cross-origin /file/save wrote the file — drive-by CSRF is open"

    # An explicit cross-origin Origin (no Sec-Fetch-Site, the older-browser path)
    # is refused the same way.
    status2, _, _ = _dispatch(
        "POST", "/__dev/api/file/save",
        headers={"origin": "https://evil.example", "host": "localhost:7145"},
        json={"path": "csrf_probe.txt", "content": "pwned"})
    assert status2 == 403
    assert not probe.exists()


def test_a_same_origin_write_is_allowed(project_dir):
    """The positive control: a same-origin POST writes. Proves the gate
    DISCRIMINATES rather than blanket-denying."""
    os.environ["TINA4_DEBUG"] = "true"
    try:
        probe = project_dir / "same_origin_probe.txt"
        status, _, _ = _dispatch(
            "POST", "/__dev/api/file/save",
            headers={"sec-fetch-site": "same-origin"},
            json={"path": "same_origin_probe.txt", "content": "legit save"})
        assert status == 200
        assert probe.read_text() == "legit save"
    finally:
        os.environ.pop("TINA4_DEBUG", None)


# ── DEVADMIN-DEC-03: .env / secret denylist ──────────────────────────────────

def test_the_file_read_endpoint_refuses_dotenv_secrets(project_dir, monkeypatch):
    """GET /file?path=.env and /file/raw?path=.env refuse and never return the
    secret. Mutation proof: drop the denylist and TINA4_SECRET appears in body."""
    monkeypatch.setenv("TINA4_DEBUG", "true")

    status, bodyb, _ = _dispatch("GET", "/__dev/api/file?path=.env")
    assert status == 403
    assert TINA4_SECRET_VALUE.encode() not in bodyb
    assert b"pg-password-leak" not in bodyb

    status_raw, bodyb_raw, _ = _dispatch("GET", "/__dev/api/file/raw?path=.env")
    assert status_raw == 403
    assert TINA4_SECRET_VALUE.encode() not in bodyb_raw

    # .env.example is a safe template (placeholder values) and stays readable.
    status_ex, _, _ = _dispatch("GET", "/__dev/api/file?path=.env.example")
    assert status_ex == 200


def test_the_file_listing_hides_dotenv(project_dir, monkeypatch):
    """The /files listing does NOT surface .env (Ruby+Node used to UN-hide it)."""
    monkeypatch.setenv("TINA4_DEBUG", "true")

    status, bodyb, _ = _dispatch("GET", "/__dev/api/files?path=.")
    assert status == 200
    names = {e["name"] for e in _json.loads(bodyb).get("entries", [])}
    assert ".env" not in names, ".env is listed by the file browser"
    assert "readme.txt" in names, "the listing lost a legitimate file"
    assert TINA4_SECRET_VALUE.encode() not in bodyb


# ── DEVADMIN-DEC-02: loopback-only mutations (defense in depth) ───────────────

def test_a_non_loopback_peer_cannot_mutate(project_dir, monkeypatch):
    """A non-loopback socket peer is refused, and a spoofed X-Forwarded-For:
    127.0.0.1 does NOT bypass it (the raw peer governs). Mutation proof: remove
    the loopback gate and the write lands (403 -> 200)."""
    monkeypatch.setenv("TINA4_DEBUG", "true")
    probe = project_dir / "loopback_probe.txt"

    status, _, _ = _dispatch(
        "POST", "/__dev/api/file/save",
        client=("8.8.8.8", 44444),
        headers={"sec-fetch-site": "same-origin"},
        json={"path": "loopback_probe.txt", "content": "remote write"})
    assert status == 403
    assert not probe.exists(), "a non-loopback peer wrote a file"

    status_xff, _, _ = _dispatch(
        "POST", "/__dev/api/file/save",
        client=("8.8.8.8", 44444),
        headers={"sec-fetch-site": "same-origin", "x-forwarded-for": "127.0.0.1"},
        json={"path": "loopback_probe.txt", "content": "xff bypass"})
    assert status_xff == 403
    assert not probe.exists(), "spoofed X-Forwarded-For bypassed the loopback gate"


def test_a_loopback_peer_may_mutate(project_dir, monkeypatch):
    """The positive control: a loopback peer with a same-origin request mutates."""
    monkeypatch.setenv("TINA4_DEBUG", "true")
    probe = project_dir / "loopback_ok_probe.txt"

    status, _, _ = _dispatch(
        "POST", "/__dev/api/file/save",
        client=("127.0.0.1", 12345),
        headers={"sec-fetch-site": "same-origin"},
        json={"path": "loopback_ok_probe.txt", "content": "local write"})
    assert status == 200
    assert probe.read_text() == "local write"


# ── DEVADMIN-DEC-04: toolbar path escaping ───────────────────────────────────

def test_the_injected_toolbar_escapes_the_request_path(project_dir, monkeypatch):
    """A request path containing <script> is HTML-escaped in the injected toolbar
    (the toolbar rides every text/html response, including this 404). Mutation
    proof: interpolate the raw path and the raw <script> tag reappears."""
    monkeypatch.setenv("TINA4_DEBUG", "true")

    status, bodyb, _ = _dispatch(
        "GET", "/x<script>alert(1)</script>y", headers={"accept": "text/html"})
    assert b"tina4-dev-toolbar" in bodyb, "the dev toolbar was not injected"
    assert b"<script>alert(1)</script>" not in bodyb, "raw <script> reflected in the toolbar (XSS)"
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in bodyb


# ── tina4stack #115: CSP-clean dev toolbar (external CSS/JS assets) ───────────

def _content_type(resp_headers):
    for k, v in resp_headers:
        if k.lower() == b"content-type":
            return v.decode()
    return ""


def test_toolbar_css_route_serves_text_css(project_dir, monkeypatch):
    """GET /__dev/toolbar.css is 200 text/css and non-empty — the external
    stylesheet that makes the injected toolbar CSP-clean. REAL dispatch through
    the front controller, no mocks."""
    monkeypatch.setenv("TINA4_DEBUG", "true")

    status, body, headers = _dispatch("GET", "/__dev/toolbar.css")
    assert status == 200
    assert "text/css" in _content_type(headers)
    assert len(body) > 0
    assert b"#tina4-dev-toolbar" in body


def test_toolbar_js_route_serves_application_javascript(project_dir, monkeypatch):
    """GET /__dev/toolbar.js is 200 application/javascript and non-empty — the
    external script wiring every toolbar event via addEventListener. REAL
    dispatch, no mocks."""
    monkeypatch.setenv("TINA4_DEBUG", "true")

    status, body, headers = _dispatch("GET", "/__dev/toolbar.js")
    assert status == 200
    assert "application/javascript" in _content_type(headers)
    assert len(body) > 0
    assert b"addEventListener" in body
    # Every handler is wired via addEventListener — no inline handler survives.
    assert b"onclick" not in body


def test_injected_toolbar_has_no_inline_style_onclick_or_inline_script(project_dir, monkeypatch):
    """The toolbar HTML injected into a real text/html response carries NO inline
    style=, NO onclick=, and NO inline <script> block — only <script src=...>.
    Anything else is stripped by the strict default-src 'self' CSP. Witness is
    the ACTUAL wire body of a real dispatched request, not a unit call."""
    import re
    monkeypatch.setenv("TINA4_DEBUG", "true")

    _status, bodyb, _headers = _dispatch(
        "GET", "/some-html-page", headers={"accept": "text/html"})
    assert b"tina4-dev-toolbar" in bodyb, "toolbar not injected"

    # Isolate the injected toolbar fragment (link + div + external script tag).
    frag = bodyb[bodyb.index(b'<link rel="stylesheet" href="/__dev/toolbar.css">'):]
    text = frag.decode("utf-8", errors="replace")
    assert 'style="' not in text and "style='" not in text, "inline style= in toolbar"
    assert "onclick" not in text, "inline onclick= in toolbar"
    # Every <script ...> in the toolbar must be an external src reference —
    # no inline <script>...</script> block.
    for tag in re.findall(r"<script[^>]*>", text):
        assert "src=" in tag, f"inline <script> in toolbar: {tag!r}"
    assert '<script src="/__dev/toolbar.js"></script>' in text


def test_toolbar_reloader_is_data_reload_gated_and_suppressed_on_ai_port(project_dir, monkeypatch):
    """The reloader is driven by the root div's data-reload attribute: "1" in a
    normal render, "0" when the AI/stable port context is active — and the JS
    early-returns unless it reads "1". Mutation proof: flipping the port context
    flips the emitted attribute."""
    from tina4_python.dev_admin import render_dev_toolbar, toolbar_js
    from tina4_python.core.server import _ai_port_ctx
    monkeypatch.setenv("TINA4_DEBUG", "true")
    monkeypatch.delenv("TINA4_NO_RELOAD", raising=False)

    normal = render_dev_toolbar("GET", "/", "/", "req-1", 3)
    assert 'data-reload="1"' in normal

    token = _ai_port_ctx.set(True)
    try:
        suppressed = render_dev_toolbar("GET", "/", "/", "req-1", 3)
    finally:
        _ai_port_ctx.reset(token)
    assert 'data-reload="0"' in suppressed

    # The JS refuses to start the reloader unless data-reload is exactly "1".
    assert "getAttribute('data-reload') !== '1'" in toolbar_js()


# ── DEVADMIN-DEC-05: mcp/call tool-execution gate ────────────────────────────

def _bind_probe_db(tmp_path):
    from tina4_python.database import Database
    from tina4_python.orm import bind_database
    db = Database(f"sqlite:///{tmp_path}/mcp_gate.db")
    bind_database(db)
    db.execute("CREATE TABLE IF NOT EXISTS gate_probe (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)")
    db.commit()
    return db


def _row_count(db):
    return db.fetch("SELECT count(*) AS n FROM gate_probe").records[0]["n"]


def test_a_remote_unauthenticated_mcp_call_is_refused_and_the_tool_does_not_run(project_dir, monkeypatch):
    """POST /__dev/api/mcp/call from a remote unauthenticated peer returns 404
    BEFORE the tool runs — proven by the real database_execute write NOT landing.
    A loopback caller runs it. Mutation proof: drop the _mcp_request_allowed gate
    on /call and the remote INSERT lands (row count 0 -> 1)."""
    monkeypatch.setenv("TINA4_DEBUG", "true")
    db = _bind_probe_db(project_dir)
    assert _row_count(db) == 0

    insert = {"name": "database_execute",
              "arguments": {"sql": "INSERT INTO gate_probe (v) VALUES ('x')"}}

    # Remote, no token -> 404 and NOTHING inserted.
    status, _, _ = _dispatch("POST", "/__dev/api/mcp/call", client=("8.8.8.8", 5555), json=insert)
    assert status == 404
    assert _row_count(db) == 0, "remote unauthenticated mcp/call executed database_execute"

    # Remote with a spoofed X-Forwarded-For loopback -> still 404 (raw peer governs).
    status_xff, _, _ = _dispatch(
        "POST", "/__dev/api/mcp/call", client=("8.8.8.8", 5555),
        headers={"x-forwarded-for": "127.0.0.1"}, json=insert)
    assert status_xff == 404
    assert _row_count(db) == 0, "spoofed X-Forwarded-For bypassed the mcp/call gate"

    # Loopback -> the tool runs (positive control): the row lands.
    status_ok, _, _ = _dispatch("POST", "/__dev/api/mcp/call", client=("127.0.0.1", 12345), json=insert)
    assert status_ok == 200
    assert _row_count(db) == 1
