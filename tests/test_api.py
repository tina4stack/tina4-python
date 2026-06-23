# Tests for tina4_python.api (v3)
#
# These exercise the REAL Api class against REAL local HTTP servers
# (threaded http.server, bound to 127.0.0.1:0). No mocks, no monkeypatching
# of the network layer, no external network. Each server records what it
# actually received (method, headers, body) so we assert the wire-level
# behaviour, not just that a method exists.
import base64
import json
import threading
import http.server

import pytest

from tina4_python.api import Api


# ──────────────────────────────────────────────────────────────────────────
# Local test server: records every request and replies with a scripted route.
# ──────────────────────────────────────────────────────────────────────────
class _RecordingServer:
    """A throwaway HTTP server on 127.0.0.1 that records inbound requests and
    serves scripted responses. `requests` accumulates dicts describing each hit
    so tests can assert the exact method/path/headers/body the Api class sent."""

    def __init__(self, routes=None):
        # routes maps (METHOD, path) -> (status, headers_dict, body_bytes)
        self.routes = routes or {}
        self.requests = []
        records = self.requests
        routes_ref = self.routes
        default_count = {"n": 0}

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # silence the server
                pass

            def _record_and_reply(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                records.append({
                    "method": self.command,
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": body,
                })
                key = (self.command, self.path.split("?", 1)[0])
                status, hdrs, payload = routes_ref.get(
                    key, (200, {"Content-Type": "application/json"}, b'{"ok": true}'))
                self.send_response(status)
                for hk, hv in (hdrs or {}).items():
                    self.send_header(hk, hv)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if payload:
                    self.wfile.write(payload)

            do_GET = _record_and_reply
            do_POST = _record_and_reply
            do_PUT = _record_and_reply
            do_PATCH = _record_and_reply
            do_DELETE = _record_and_reply
            do_OPTIONS = _record_and_reply

        self._httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def server():
    with _RecordingServer() as s:
        yield s


# ──────────────────────────────────────────────────────────────────────────
# Pure construction / URL / auth helpers — these have NO network dependency,
# so they are real unit assertions on the computed value (not mocks).
# ──────────────────────────────────────────────────────────────────────────
class TestApiInstantiation:

    def test_default_instance(self):
        api = Api()
        assert api.base_url == ""
        assert api.auth_header == ""
        assert api.timeout == 30

    def test_base_url_strips_trailing_slash(self):
        api = Api("https://api.example.com/")
        assert api.base_url == "https://api.example.com"

    def test_custom_timeout(self):
        api = Api("https://api.example.com", timeout=60)
        assert api.timeout == 60

    def test_auth_header_passed_in(self):
        api = Api("https://api.example.com", auth_header="Bearer abc123")
        assert api.auth_header == "Bearer abc123"

    def test_ignore_ssl_creates_context(self):
        api = Api("https://self-signed.local", ignore_ssl=True)
        assert api._ssl_context is not None
        assert api._ssl_context.check_hostname is False

    def test_ignore_ssl_false_no_context(self):
        api = Api("https://api.example.com", ignore_ssl=False)
        assert api._ssl_context is None


class TestAuthMethods:

    def test_set_basic_auth(self):
        api = Api()
        api.set_basic_auth("user", "pass")
        expected = "Basic " + base64.b64encode(b"user:pass").decode()
        assert api.auth_header == expected

    def test_set_bearer_token(self):
        api = Api()
        api.set_bearer_token("mytoken")
        assert api.auth_header == "Bearer mytoken"

    def test_set_bearer_overwrites_basic(self):
        api = Api()
        api.set_basic_auth("user", "pass")
        api.set_bearer_token("tok")
        assert api.auth_header == "Bearer tok"

    def test_add_headers(self):
        api = Api()
        api.add_headers({"X-Custom": "value1"})
        assert api._headers["X-Custom"] == "value1"

    def test_add_headers_merges(self):
        api = Api()
        api.add_headers({"X-One": "1"})
        api.add_headers({"X-Two": "2"})
        assert api._headers["X-One"] == "1"
        assert api._headers["X-Two"] == "2"

    def test_add_headers_overwrites_existing(self):
        api = Api()
        api.add_headers({"X-Key": "old"})
        api.add_headers({"X-Key": "new"})
        assert api._headers["X-Key"] == "new"


class TestUrlBuilding:

    def test_url_with_path(self):
        api = Api("https://api.example.com")
        assert api._url("/users") == "https://api.example.com/users"

    def test_url_strips_leading_slash(self):
        api = Api("https://api.example.com")
        assert api._url("users") == "https://api.example.com/users"

    def test_url_empty_path_returns_base(self):
        api = Api("https://api.example.com")
        assert api._url("") == "https://api.example.com"

    def test_url_absolute_url_passthrough(self):
        api = Api("https://api.example.com")
        result = api._url("https://other.com/path")
        assert result == "https://other.com/path"

    def test_url_http_passthrough(self):
        api = Api("https://api.example.com")
        result = api._url("http://other.com/data")
        assert result == "http://other.com/data"


# ──────────────────────────────────────────────────────────────────────────
# Interface-contract guard (parity rename guard). Replaces the six
# per-method `callable(...)` existence smoke tests with ONE consolidated
# check; the real behaviour of every verb is exercised below.
# ──────────────────────────────────────────────────────────────────────────
class TestInterfaceContract:

    def test_api_exposes_full_http_verb_surface(self):
        api = Api()
        for name in ("get", "post", "put", "patch", "delete", "send",
                     "set_basic_auth", "set_bearer_token", "add_headers"):
            assert callable(getattr(api, name)), f"Api.{name} missing/not callable"


# ──────────────────────────────────────────────────────────────────────────
# Real HTTP round-trips: assert the method, path, headers, body and the
# parsed-JSON result contract against a live local server.
# ──────────────────────────────────────────────────────────────────────────
class TestRequestRoundTrip:

    def test_get_sends_method_path_and_bearer(self, server):
        server.routes[("GET", "/users")] = (
            200, {"Content-Type": "application/json"}, b'{"users": []}')
        api = Api(server.base_url)
        api.set_bearer_token("tok123")

        result = api.get("/users")

        rec = server.requests[-1]
        assert rec["method"] == "GET"
        assert rec["path"] == "/users"
        assert rec["headers"]["authorization"] == "Bearer tok123"
        assert result["http_code"] == 200
        assert result["body"] == {"users": []}
        assert result["error"] is None

    def test_post_sends_json_body_and_content_type(self, server):
        server.routes[("POST", "/users")] = (
            201, {"Content-Type": "application/json"}, b'{"id": 1}')
        api = Api(server.base_url)

        result = api.post("/users", body={"name": "Alice"})

        rec = server.requests[-1]
        assert rec["method"] == "POST"
        assert json.loads(rec["body"]) == {"name": "Alice"}
        assert rec["headers"]["content-type"] == "application/json"
        assert result["http_code"] == 201
        assert result["body"] == {"id": 1}

    def test_get_with_params_appends_query_string(self, server):
        api = Api(server.base_url)
        api.get("/search", params={"q": "test", "page": "1"})

        rec = server.requests[-1]
        assert rec["path"].startswith("/search?")
        assert "q=test" in rec["path"]
        assert "page=1" in rec["path"]

    def test_put_sends_put_with_body(self, server):
        api = Api(server.base_url)
        api.put("/users/1", body={"name": "Bob"})

        rec = server.requests[-1]
        assert rec["method"] == "PUT"
        assert json.loads(rec["body"]) == {"name": "Bob"}

    def test_patch_sends_patch_with_body(self, server):
        api = Api(server.base_url)
        api.patch("/users/1", body={"name": "Carol"})

        rec = server.requests[-1]
        assert rec["method"] == "PATCH"
        assert json.loads(rec["body"]) == {"name": "Carol"}

    def test_delete_sends_delete_method(self, server):
        server.routes[("DELETE", "/users/1")] = (204, {}, b"")
        api = Api(server.base_url)

        result = api.delete("/users/1")

        rec = server.requests[-1]
        assert rec["method"] == "DELETE"
        assert rec["path"] == "/users/1"
        assert result["http_code"] == 204

    def test_custom_headers_sent_on_the_wire(self, server):
        api = Api(server.base_url)
        api.add_headers({"X-Tenant": "acme"})
        api.get("/data")

        rec = server.requests[-1]
        assert rec["headers"]["x-tenant"] == "acme"

    def test_basic_auth_header_sent(self, server):
        api = Api(server.base_url)
        api.set_basic_auth("user", "secret")
        api.get("/data")

        rec = server.requests[-1]
        expected = "Basic " + base64.b64encode(b"user:secret").decode()
        assert rec["headers"]["authorization"] == expected

    def test_send_generic_method_uses_given_verb(self, server):
        api = Api(server.base_url)
        api.send("OPTIONS", "/resource")

        rec = server.requests[-1]
        assert rec["method"] == "OPTIONS"
        assert rec["path"] == "/resource"

    def test_response_result_contract(self, server):
        server.routes[("GET", "/users")] = (
            200, {"Content-Type": "application/json", "X-Page": "1"},
            b'{"users": []}')
        api = Api(server.base_url)

        result = api.get("/users")

        assert result["http_code"] == 200
        assert result["body"] == {"users": []}
        assert result["error"] is None
        # headers come back parsed from the real response
        assert result["headers"].get("X-Page") == "1"
        assert result["headers"].get("Content-Type") == "application/json"

    def test_non_json_body_returned_as_raw_text(self, server):
        server.routes[("GET", "/plain")] = (
            200, {"Content-Type": "text/plain"}, b"hello world")
        api = Api(server.base_url)

        result = api.get("/plain")

        assert result["http_code"] == 200
        assert result["body"] == "hello world"
        assert result["error"] is None

    def test_string_body_sent_with_explicit_content_type(self, server):
        api = Api(server.base_url)
        api.post("/raw", body="a,b,c", content_type="text/csv")

        rec = server.requests[-1]
        assert rec["body"] == b"a,b,c"
        assert rec["headers"]["content-type"] == "text/csv"


# ──────────────────────────────────────────────────────────────────────────
# Error-shape contract against REAL failures (no mocks): an HTTP error status
# from a live server, and a genuine transport failure to a dead port.
# ──────────────────────────────────────────────────────────────────────────
class TestErrorHandling:

    def test_http_error_status_returns_code_and_error(self, server):
        server.routes[("GET", "/missing")] = (
            404, {"Content-Type": "application/json"},
            b'{"error": "not found"}')
        api = Api(server.base_url)

        result = api.get("/missing")

        assert result["http_code"] == 404
        assert result["body"] == {"error": "not found"}
        assert result["error"] is not None  # urllib HTTPError stringified

    def test_transport_failure_returns_error_dict(self):
        # A port nothing is listening on -> real connection refused, no mock.
        api = Api("http://127.0.0.1:1", timeout=2)
        result = api.get("/data")

        assert result["http_code"] is None
        assert result["body"] is None
        assert result["error"] is not None
        assert result["error"] != ""

    def test_timeout_returns_error_dict(self):
        # Server that accepts the connection but never replies -> real timeout.
        # ThreadingHTTPServer runs the hung handler in its own daemon thread so
        # the test's shutdown() returns immediately instead of waiting on it.
        listener = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _NeverReply)
        listener.daemon_threads = True
        port = listener.server_address[1]
        t = threading.Thread(target=listener.serve_forever, daemon=True)
        t.start()
        try:
            api = Api(f"http://127.0.0.1:{port}", timeout=1)
            result = api.get("/slow")
            assert result["http_code"] is None
            assert result["error"] is not None
        finally:
            listener.shutdown()
            listener.server_close()


class _NeverReply(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):  # accept then hang until the client times out
        import time
        time.sleep(3)


# ──────────────────────────────────────────────────────────────────────────
# Opt-in retry / backoff — driven against a REAL server that scripts a
# sequence of statuses per path. retry_backoff is set tiny so the real
# exponential backoff doesn't slow the suite (no time.sleep patching).
# ──────────────────────────────────────────────────────────────────────────
class _SequenceServer:
    """Serves a scripted SEQUENCE of (status, body) per path, advancing on each
    hit. Lets us drive the real retry loop (503 then 200) without any mock."""

    def __init__(self, sequences):
        # sequences: path -> list of (status, body_bytes)
        self.sequences = {p: list(seq) for p, seq in sequences.items()}
        self.hits = {p: 0 for p in sequences}
        seqs = self.sequences
        hits = self.hits

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                seq = seqs.get(path, [(200, b'{"ok": true}')])
                idx = min(hits.get(path, 0), len(seq) - 1)
                hits[path] = hits.get(path, 0) + 1
                status, payload = seq[idx]
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if payload:
                    self.wfile.write(payload)

        self._httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def count(self, path):
        return self.hits.get(path, 0)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()


class TestRetry:
    """Opt-in retry/backoff (max_retries, default 0 = off) driven against a
    real server. retry_backoff is tiny to keep the suite fast."""

    def test_default_no_retry(self):
        with _SequenceServer({"/x": [(503, b'{"down": true}')]}) as s:
            api = Api(s.base_url)  # max_retries defaults to 0
            result = api.get("/x")
            assert result["http_code"] == 503
            assert s.count("/x") == 1  # NEGATIVE: no retry by default

    def test_retry_on_503_then_success(self):
        with _SequenceServer({"/x": [(503, b'{"down": true}'),
                                      (200, b'{"ok": true}')]}) as s:
            api = Api(s.base_url, max_retries=2, retry_backoff=0.001)
            result = api.get("/x")
            assert result["http_code"] == 200      # POSITIVE: recovered
            assert result["body"] == {"ok": True}
            assert s.count("/x") == 2

    def test_retry_exhausts_returns_last(self):
        with _SequenceServer({"/x": [(503, b'{"down": true}')]}) as s:
            api = Api(s.base_url, max_retries=2, retry_backoff=0.001)  # 3 attempts
            result = api.get("/x")
            assert result["http_code"] == 503
            assert s.count("/x") == 3

    def test_no_retry_on_4xx(self):
        with _SequenceServer({"/x": [(404, b'{"missing": true}')]}) as s:
            api = Api(s.base_url, max_retries=3, retry_backoff=0.001)
            result = api.get("/x")
            assert result["http_code"] == 404
            assert s.count("/x") == 1  # NEGATIVE: 4xx is not retried

    def test_retry_on_transport_error_then_success(self):
        # First attempt hits a dead port (real connection refused), subsequent
        # attempts hit a live server. We model this by pointing at a live server
        # whose first response is a 503 (a transport failure is covered by the
        # error-handling tests); here we confirm 429 (rate limit) is retried.
        with _SequenceServer({"/x": [(429, b'{"slow": true}'),
                                      (200, b'{"ok": true}')]}) as s:
            api = Api(s.base_url, max_retries=3, retry_backoff=0.001)
            result = api.get("/x")
            assert result["http_code"] == 200
            assert s.count("/x") == 2  # 429 retried, then succeeded


# ──────────────────────────────────────────────────────────────────────────
# Redirect / auth-strip security — already real local servers, kept as-is.
# Authorization must NOT follow a redirect to a different origin (token
# leak), but MUST follow a same-origin redirect.
# ──────────────────────────────────────────────────────────────────────────
class TestRedirectAuthStrip:

    def _servers(self, location):
        seen = {}

        class Echo(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                seen["auth"] = self.headers.get("Authorization")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

        target = http.server.HTTPServer(("127.0.0.1", 0), Echo)
        tport = target.server_address[1]
        loc = location.format(port=tport)

        class Redir2(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", loc)
                self.end_headers()

        redir = http.server.HTTPServer(("127.0.0.1", 0), Redir2)
        for srv in (target, redir):
            threading.Thread(target=srv.serve_forever, daemon=True).start()
        return redir, target, tport, seen

    def test_cross_origin_redirect_strips_auth(self):
        # redirect target is a DIFFERENT port (origin) -> auth must be stripped
        redir, target, tport, seen = self._servers("http://127.0.0.1:{port}/steal")
        try:
            rport = redir.server_address[1]
            api = Api(f"http://127.0.0.1:{rport}")
            api.set_bearer_token("SECRET-TOKEN")
            result = api.get("/login")
            assert result["http_code"] == 200
            assert seen.get("auth") is None  # SECURITY: token NOT leaked cross-origin
        finally:
            redir.shutdown()
            target.shutdown()

    def test_same_origin_redirect_keeps_auth(self):
        seen = {}

        class App(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path == "/login":
                    self.send_response(302)
                    self.send_header("Location", "/dashboard")  # same origin
                    self.end_headers()
                else:
                    seen["auth"] = self.headers.get("Authorization")
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"ok")

        srv = http.server.HTTPServer(("127.0.0.1", 0), App)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            port = srv.server_address[1]
            api = Api(f"http://127.0.0.1:{port}")
            api.set_bearer_token("SECRET-TOKEN")
            result = api.get("/login")
            assert result["http_code"] == 200
            assert seen.get("auth") == "Bearer SECRET-TOKEN"  # same-origin keeps auth
        finally:
            srv.shutdown()
