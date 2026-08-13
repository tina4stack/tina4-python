"""Feature 43 - request-id / correlation-id.

Real request-pipeline tests: every case drives the REAL front controller
(``tina4_python.core.server.app``) through ``TestClient`` (or, for the
concurrency case, ``app`` directly) - NO mocks. The logger case reads a REAL log
file the framework wrote.

Proves the four cross-framework invariants:

1. a well-formed inbound ``X-Request-ID`` is honoured and echoed on the response;
2. an absent id yields a generated id echoed on the response;
3. a CR/LF-bearing OR over-long OR illegal-charset inbound id is sanitized so it
   never reflects raw into the response header or a log line (no injection);
4. a log line written during the request carries the id (log correlation).

Plus the Python-specific correctness fix (RID-PY-NO-ISOLATION): two requests in
flight on the one asyncio thread keep DISTINCT ids - the whole reason storage
moved from ``threading.local`` to a ``contextvars.ContextVar``.
"""
from __future__ import annotations

import os

os.environ.setdefault("TINA4_SECRET", "rid-feature-43-secret")

import re
import json
import asyncio

from tina4_python.core.router import get
from tina4_python.debug import Log, get_request_id, sanitize_request_id
from tina4_python.test_client import TestClient

# A generated/honoured id is [A-Za-z0-9._-], 1..128 chars (the test strings never
# carry a trailing newline, so a plain ^...$ anchor is safe HERE - the SANITIZER
# itself uses the newline-proof disallowed-char test, exercised below).
_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


async def _drive_async(path: str, inbound: str) -> str:
    """Dispatch one request through the REAL ASGI app and return the ``rid`` the
    handler read AFTER awaiting. Used to run two requests truly concurrently on
    one event loop."""
    from tina4_python.core.server import app

    scope = {
        "type": "http", "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"",
        "headers": [(b"x-request-id", inbound.encode())],
        "client": ("127.0.0.1", 0), "server": ("localhost", 7145), "root_path": "",
    }
    body = bytearray()

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.body":
            chunk = message.get("body", b"") or b""
            body.extend(chunk if isinstance(chunk, (bytes, bytearray)) else chunk.encode())

    await app(scope, receive, send)
    return json.loads(bytes(body).decode())["rid"]


class TestRequestIdPipeline:
    """The four shared invariants, driven through the real front controller."""

    def setup_method(self, _method):
        @get("/rid-echo")
        async def _echo(request, response):
            # Return the id the framework threaded into the request context, so
            # the test can assert the handler and the wire agree.
            return response({"rid": get_request_id()})

        @get("/rid-slow")
        async def _slow(request, response):
            await asyncio.sleep(0.05)          # force two requests to interleave
            return response({"rid": get_request_id()})

    # 1. honour a valid inbound id -------------------------------------------
    def test_inbound_id_is_honoured_and_echoed(self):
        r = TestClient().get("/rid-echo", headers={"X-Request-ID": "trace-abc_123.4"})
        assert r.headers.get("x-request-id") == "trace-abc_123.4"
        assert r.json()["rid"] == "trace-abc_123.4"

    # 2. generate when absent -------------------------------------------------
    def test_absent_id_is_generated_and_echoed(self):
        r = TestClient().get("/rid-echo")
        rid = r.headers.get("x-request-id")
        assert rid, "no X-Request-ID emitted on the response"
        assert _ID_RE.match(rid), f"generated id is not well-formed: {rid!r}"
        assert r.json()["rid"] == rid, "handler id and response header disagree"

    # 3. sanitize a hostile inbound id (CR/LF) --------------------------------
    def test_crlf_id_is_sanitized(self):
        hostile = "abc\r\nSet-Cookie: pwned=1"
        r = TestClient().get("/rid-echo", headers={"X-Request-ID": hostile})
        rid = r.headers.get("x-request-id")
        assert "\r" not in rid and "\n" not in rid, "CR/LF reflected into response header"
        assert rid != hostile and _ID_RE.match(rid), "raw hostile id was reflected"
        # the injected header must not have materialised anywhere in the response
        assert "pwned" not in " ".join(f"{k}:{v}" for k, v in r.headers.items())
        # and the handler saw the clean generated id, not the raw header
        assert r.json()["rid"] == rid

    # 3. sanitize a hostile inbound id (over-long) ----------------------------
    def test_overlong_id_is_sanitized(self):
        hostile = "a" * 500
        r = TestClient().get("/rid-echo", headers={"X-Request-ID": hostile})
        rid = r.headers.get("x-request-id")
        assert rid != hostile, "over-long id was reflected"
        assert len(rid) <= 128 and _ID_RE.match(rid)

    # 3. sanitize a hostile inbound id (illegal charset) ----------------------
    def test_illegal_charset_id_is_sanitized(self):
        hostile = "no spaces or *stars*"
        r = TestClient().get("/rid-echo", headers={"X-Request-ID": hostile})
        rid = r.headers.get("x-request-id")
        assert rid != hostile, "illegal-charset id was reflected"
        assert _ID_RE.match(rid)

    # RID-PY-NO-ISOLATION: concurrent requests keep DISTINCT ids --------------
    async def test_concurrent_requests_keep_distinct_ids(self):
        first, second = await asyncio.gather(
            _drive_async("/rid-slow", "aaa-111"),
            _drive_async("/rid-slow", "bbb-222"),
        )
        # With threading.local (one slot for every coroutine on the one asyncio
        # thread) the first request reads the second's id after its await. A
        # ContextVar isolates them.
        assert first == "aaa-111", f"first request saw {first!r} - id isolation broken"
        assert second == "bbb-222", f"second request saw {second!r} - id isolation broken"


class TestRequestIdLogCorrelation:
    """A log line written during the request carries the request id (real file)."""

    def setup_method(self, _method):
        @get("/rid-log")
        async def _log(request, response):
            Log.info("rid-log-marker")
            return response({"rid": get_request_id()})

    def test_log_line_carries_the_request_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")   # force a real file sink
        Log.configure(log_dir=str(tmp_path), level="debug")
        try:
            r = TestClient().get("/rid-log", headers={"X-Request-ID": "corr-9f8e7d"})
            assert r.headers.get("x-request-id") == "corr-9f8e7d"

            log_text = (tmp_path / "tina4.log").read_text()
            marker_lines = [ln for ln in log_text.splitlines() if "rid-log-marker" in ln]
            assert marker_lines, "the handler's log line was never written to the file"
            # Decision 3 (tina4_python/debug/__init__.py): format defaults to
            # JSON outside TINA4_DEBUG, so the correlation id is the
            # "request_id" field -- the bracketed "[id]" rendering only
            # happens in TEXT format (covered separately by
            # test_log_contract.py's per-format encoding tests).
            parsed_lines = [json.loads(ln) for ln in marker_lines]
            assert any(entry.get("request_id") == "corr-9f8e7d" for entry in parsed_lines), (
                f"log line does not carry the request id: {marker_lines!r}"
            )
        finally:
            # Don't leave the process logger pointed at a tmp dir pytest deletes.
            Log.configure(log_dir="logs", level="info")


class TestSanitizeRequestId:
    """Direct, no-dependency unit checks of the sanitizer (a pure function).

    The tight mutation target: drop the disallowed-char test and every hostile
    case below reflects raw; drop the length cap and the over-long case reflects.
    """

    def test_honours_well_formed_ids(self):
        for good in ("abc123", "trace-id_9.8", "A" * 128, "0", "x.y-z_1"):
            assert sanitize_request_id(good) == good, f"should honour {good!r}"

    def test_rejects_hostile_or_malformed_ids(self):
        for bad in (
            "abc\r\nSet-Cookie: x=1",   # CRLF header injection
            "abc\rinject",              # bare CR
            "abc\ninject",              # bare LF
            "has space",                # space not allowed
            "semi;colon",               # ; not allowed
            "curl|bash",                # pipe not allowed
            "<script>",                 # angle brackets not allowed
            "a" * 129,                  # over the length cap
            "",                         # empty
            None,                       # absent
        ):
            assert sanitize_request_id(bad) is None, f"should reject {bad!r}"
