# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""HTTP hardening contract (ADR-0068) - the Python runner for
tina4-documentation/plan/v3/fixtures/http_hardening_contract.json.

Two defects, both found by a security audit of the reference implementation:

* The zero-dependency asyncio server (the fallback whenever uvicorn and
  hypercorn are not installed, the shipped Docker image included) read the
  whole DECLARED body before TINA4_MAX_UPLOAD_SIZE was checked, crashed its
  connection task on a non-numeric Content-Length or an oversized head (leaking
  the socket both times), ignored chunked bodies, and let a stalled body raise
  an uncaught timeout.
* Response.header(), .cookie() and .redirect() accepted CR, LF and NUL, and the
  built-in server wrote header lines to the socket as it found them.

No mocks. The response cases drive the real Response object (pure logic, no
collaborator). The server cases boot the real framework in a child process,
with the built-in server pinned by TINA4_DEFAULT_WEBSERVER, and talk to it over
a real loopback socket; resident memory is read from the operating system.
The ASGI shape case boots the same app under a real uvicorn (a dev dependency).

Case names match the fixture so scripts/audit-contract-fixtures.py can find them.
"""
import json
import socket
import subprocess
import time

import pytest

from conftest import boot_child_server, read_child_log
from tina4_python.core.response import Response

LIMIT = 1_048_576          # TINA4_MAX_UPLOAD_SIZE for every server here
HEADER_LIMIT = 8192        # TINA4_MAX_REQUEST_HEADER
IDLE_SECONDS = 3           # TINA4_REQUEST_TIMEOUT

SECURITY_HEADERS = {
    "x-frame-options": "SAMEORIGIN",
    "x-content-type-options": "nosniff",
    "content-security-policy": "default-src 'self'",
    "referrer-policy": "strict-origin-when-cross-origin",
    "x-xss-protection": "0",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
}

ROUTES = '''
from tina4_python.core.router import get, post, noauth


@post("/upload")
@noauth()
async def upload(request, response):
    return response({"size": len(request.raw_body),
                     "body": request.raw_body.decode(errors="replace")})


@get("/hello")
async def hello(request, response):
    return response({"ok": True})


@get("/redirect")
async def go(request, response):
    return response.redirect(request.query.get("to", "/"))


@get("/echo-header")
async def echo(request, response):
    return response.header("X-Echo", request.query.get("v", "")).json({"ok": True})


@get("/cookies")
async def cookies(request, response):
    response.cookie("first", "one").cookie("second", "two", path="/app")
    return response({"ok": True})


@get("/direct-append")
async def direct(request, response):
    # Bypasses header() on purpose: the writer must still refuse it.
    response._headers.append(("X-Direct", "a\\r\\nX-Injected: yes"))
    return response({"ok": True})
'''


def _write_app(project, port):
    (project / "src" / "routes" / "hardening.py").write_text(ROUTES)
    (project / "app.py").write_text(
        "from tina4_python.core.server import start\n"
        "if __name__ == '__main__':\n"
        f"    start(host='127.0.0.1', port={port}, no_browser=True, no_reload=True)\n"
    )


def _env(builtin: bool):
    env = {
        "TINA4_DEBUG": "false",
        "TINA4_MAX_UPLOAD_SIZE": str(LIMIT),
        "TINA4_MAX_REQUEST_HEADER": str(HEADER_LIMIT),
        "TINA4_REQUEST_TIMEOUT": str(IDLE_SECONDS),
    }
    if builtin:
        env["TINA4_DEFAULT_WEBSERVER"] = "true"
    return env


def _boot(tmp_path, builtin=True):
    unset = ("TINA4_CSP", "TINA4_FRAME_OPTIONS", "TINA4_REFERRER_POLICY",
             "TINA4_PERMISSIONS_POLICY", "TINA4_HSTS", "TINA4_DEFAULT_WEBSERVER")
    return boot_child_server(tmp_path, _write_app, extra_env=_env(builtin),
                             unset_env=unset, log_dir=tmp_path / "logs")


def _stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    proc, port = _boot(tmp_path_factory.mktemp("hardening"))
    try:
        yield proc, port
    finally:
        _stop(proc)


class Answer:
    def __init__(self, raw: bytes):
        self.raw = raw
        head, sep, self.body = raw.partition(b"\r\n\r\n")
        self.head = head.decode("latin-1")
        self.status = None
        self.headers: dict[str, list[str]] = {}
        if not sep:
            return
        lines = self.head.split("\r\n")
        self.status = int(lines[0].split(" ")[1])
        for line in lines[1:]:
            name, _, value = line.partition(":")
            self.headers.setdefault(name.strip().lower(), []).append(value.strip())

    def one(self, name):
        values = self.headers.get(name, [])
        return values[0] if values else None

    def __repr__(self):
        return f"<Answer {self.status} {self.raw[:400]!r}>"


def _read_all(sock) -> bytes:
    data = b""
    try:
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
    except (socket.timeout, ConnectionResetError):
        pass
    return data


def _exchange(port, raw: bytes, timeout: float = 8.0) -> Answer:
    """Send one request and read until the server closes.

    HTTP/1.1 keeps the connection open, so a request that does not say
    otherwise gets Connection: close added after its request line; the
    keep-alive cases in TestHttp11 use their own sockets.
    """
    head_end = raw.find(b"\r\n\r\n")
    head = raw if head_end == -1 else raw[:head_end]
    first_line_end = raw.find(b"\r\n")
    if first_line_end != -1 and b"\r\nconnection:" not in head.lower():
        raw = raw[:first_line_end + 2] + b"Connection: close\r\n" + raw[first_line_end + 2:]
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        try:
            sock.sendall(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass
        return Answer(_read_all(sock))


def _post_head(extra: str) -> bytes:
    return ("POST /upload HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            "Content-Type: application/octet-stream\r\n" + extra + "\r\n").encode()


def _body_413(size: int) -> bytes:
    return (b'{"error":"Request body (%d bytes) exceeds TINA4_MAX_UPLOAD_SIZE (%d bytes)"}'
            % (size, LIMIT))


def _rss_megabytes(pid: int) -> float:
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)],
                         capture_output=True, text=True, check=False).stdout.strip()
    return int(out) / 1024 if out else 0.0


def _assert_serving(port):
    answer = _exchange(port, b"GET /hello HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
    assert answer.status == 200, answer


# -- Response: call-site refusal (pure logic, the real Response object) -------

class TestResponseHeaderRefusal:
    @pytest.mark.parametrize("bad", ["a\rb", "a\nb", "a\x00b", "a\r\nX-Other: 1"])
    def test_a_header_value_containing_cr_lf_or_nul_is_refused(self, bad):
        expected = 'Invalid character in header content ["X-Test"]'
        with pytest.raises(ValueError) as caught:
            Response().header("X-Test", bad)
        assert str(caught.value) == expected
        with pytest.raises(ValueError) as caught:
            Response().add_header("X-Test", bad)
        assert str(caught.value) == expected
        with pytest.raises(ValueError) as caught:
            Response()({"ok": True}, 200, headers={"X-Test": bad})
        assert str(caught.value) == expected

    @pytest.mark.parametrize("bad", ["X Test", "X:Test", "", "X\r\nTest", "Tëst", "X(Test)"])
    def test_a_header_name_that_is_not_a_token_is_refused(self, bad):
        with pytest.raises(ValueError) as caught:
            Response().header(bad, "value")
        assert str(caught.value) == f"Header name must be a valid HTTP token [{json.dumps(bad)}]"

    def test_a_redirect_location_containing_cr_or_lf_is_refused(self, tmp_path):
        for bad in ("/next\r\nX-Other: 1", "/next\n", "/next\x00"):
            with pytest.raises(ValueError) as caught:
                Response().redirect(bad)
            assert str(caught.value) == 'Invalid character in header content ["Location"]'
        with pytest.raises(ValueError) as caught:
            Response()("x", 200, "text/plain\r\nX-Other: 1")
        assert str(caught.value) == 'Invalid character in header content ["Content-Type"]'
        target = tmp_path / "report.txt"
        target.write_text("report")
        with pytest.raises(ValueError) as caught:
            Response().file(str(target), download_name="report\r\n.txt")
        assert str(caught.value) == 'Invalid character in header content ["Content-Disposition"]'

    def test_normal_headers_and_redirects_still_work(self, tmp_path):
        response = Response().header("X-Plain", "a value, with; punctuation = fine")
        response.header("X-Number", 42)
        assert ("X-Plain", "a value, with; punctuation = fine") in response._headers
        assert ("X-Number", "42") in response._headers
        redirected = Response().redirect("/login?next=/a%20b&x=1", 303)
        assert redirected.status_code == 303
        assert ("location", "/login?next=/a%20b&x=1") in redirected._headers
        target = tmp_path / "report.txt"
        target.write_text("report")
        downloaded = Response().file(str(target), download_name="report.txt")
        assert ("content-disposition", 'attachment; filename="report.txt"') in downloaded._headers


class TestCookieRefusal:
    @pytest.mark.parametrize("name", ["a b", "a=b", "a;b", "", "a\r\nb", "a,b"])
    def test_a_cookie_name_value_or_attribute_that_could_inject_is_refused(self, name):
        with pytest.raises(ValueError) as caught:
            Response().cookie(name, "v")
        assert str(caught.value) == f"Cookie name must be a valid HTTP token [{json.dumps(name)}]"

        expected = 'Invalid character in cookie content ["sid"]'
        for bad_value in ("v; Domain=example.com", "v\r\nX-Other: 1", "v\n", "v\x00"):
            with pytest.raises(ValueError) as caught:
                Response().cookie("sid", bad_value)
            assert str(caught.value) == expected
        for attributes in ({"path": "/; Domain=example.com"}, {"same_site": "Lax\r\nX: 1"},
                           {"max_age": "60; Domain=example.com"}):
            with pytest.raises(ValueError) as caught:
                Response().cookie("sid", "v", **attributes)
            assert str(caught.value) == expected
        with pytest.raises(ValueError) as caught:
            Response().cookie("sid", "v", {"path": "/x\n"})
        assert str(caught.value) == expected

    def test_multiple_set_cookie_headers_all_reach_the_client(self, server):
        response = Response().cookie("first", "one").cookie("second", "two", path="/app")
        assert response._cookies == [
            "first=one; Path=/; Max-Age=3600; SameSite=Lax; HttpOnly",
            "second=two; Path=/app; Max-Age=3600; SameSite=Lax; HttpOnly",
        ]
        _proc, port = server
        answer = _exchange(port, b"GET /cookies HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        assert answer.status == 200, answer
        cookies = answer.headers.get("set-cookie", [])
        assert "first=one; Path=/; Max-Age=3600; SameSite=Lax; HttpOnly" in cookies, answer
        assert "second=two; Path=/app; Max-Age=3600; SameSite=Lax; HttpOnly" in cookies, answer


# -- Built-in server --------------------------------------------------------

class TestBuiltinServer:
    def test_the_route_refusal_holds_end_to_end(self, server):
        _proc, port = server
        answer = _exchange(
            port, b"GET /redirect?to=/next%0D%0AX-Injected:%20yes HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        assert answer.status == 500, answer
        assert "x-injected" not in answer.headers, answer
        ok = _exchange(port, b"GET /echo-header?v=plain%20value HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        assert ok.status == 200 and ok.one("x-echo") == "plain value", ok
        assert ok.one("server") is None, "expected the built-in server, got " + repr(ok.one("server"))

    def test_the_built_in_server_refuses_to_write_an_unsafe_header(self, server):
        proc, port = server
        answer = _exchange(port, b"GET /direct-append HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        assert answer.status == 500, answer
        assert answer.body == b'{"error":"Invalid response header"}', answer
        assert "x-injected" not in answer.headers and "x-direct" not in answer.headers, answer
        assert answer.one("connection") == "close", answer
        time.sleep(0.2)
        assert "X-Direct" in read_child_log(proc)
        _assert_serving(port)

    def test_a_declared_content_length_over_the_cap_is_refused_before_the_body_is_read(self, server):
        _proc, port = server
        declared = 50 * 1_048_576
        started = time.monotonic()
        answer = _exchange(port, _post_head(f"Content-Length: {declared}\r\n"))
        elapsed = time.monotonic() - started
        assert answer.status == 413, answer
        assert answer.body == _body_413(declared), answer
        # Answered at once, not after waiting for (or timing out on) the body.
        assert elapsed < IDLE_SECONDS - 1, f"answered after {elapsed:.1f}s"
        _assert_serving(port)

    def test_an_oversized_declared_body_does_not_grow_server_memory(self, tmp_path):
        proc, port = _boot(tmp_path)
        sockets = []
        try:
            _assert_serving(port)
            time.sleep(0.5)
            before = _rss_megabytes(proc.pid)
            assert before > 0, "could not read the server's RSS"
            block = b"a" * (8 * 1_048_576)
            for _ in range(6):
                sock = socket.create_connection(("127.0.0.1", port), timeout=5)
                sockets.append(sock)
                try:
                    sock.sendall(_post_head(f"Content-Length: {256 * 1_048_576}\r\n"))
                    sock.sendall(block)
                except (BrokenPipeError, ConnectionResetError, socket.timeout):
                    pass
            time.sleep(1.0)
            during = _rss_megabytes(proc.pid)
            grew = during - before
            # Six clients each pushed 8MB against a 1MB cap. The old reader held
            # all of it (48MB+) waiting for the declared 256MB.
            assert grew < 16, f"server grew {grew:.1f}MB ({before:.1f} -> {during:.1f})"
        finally:
            for sock in sockets:
                sock.close()
            _stop(proc)

    def test_a_chunked_body_over_the_cap_is_refused_as_it_arrives(self, server):
        _proc, port = server
        piece = b"%x\r\n" % 65536 + b"a" * 65536 + b"\r\n"
        raw = _post_head("Transfer-Encoding: chunked\r\n") + piece * 32 + b"0\r\n\r\n"
        answer = _exchange(port, raw)
        assert answer.status == 413, answer
        assert answer.body == _body_413(17 * 65536), answer
        _assert_serving(port)

    def test_a_chunked_body_under_the_cap_is_decoded_and_served(self, server):
        _proc, port = server
        raw = (_post_head("Transfer-Encoding: chunked\r\n")
               + b"5;name=value\r\nhello\r\n6\r\n world\r\n0\r\nX-Trailer: t\r\n\r\n")
        answer = _exchange(port, raw)
        assert answer.status == 200, answer
        assert json.loads(answer.body) == {"size": 11, "body": "hello world"}

    def test_a_body_under_the_cap_is_still_served(self, server):
        _proc, port = server
        for size in (0, 1000, LIMIT):
            answer = _exchange(port, _post_head(f"Content-Length: {size}\r\n") + b"b" * size)
            assert answer.status == 200, answer
            assert json.loads(answer.body)["size"] == size

    @pytest.mark.parametrize("header", [
        "Content-Length: abc\r\n", "Content-Length: -1\r\n", "Content-Length: +5\r\n",
        "Content-Length: 1 2\r\n", "Content-Length: 0x10\r\n", "Content-Length: \r\n",
        "Content-Length: 5\r\nContent-Length: 6\r\n",
    ])
    def test_an_invalid_content_length_answers_400(self, server, header):
        _proc, port = server
        answer = _exchange(port, _post_head(header) + b"hello")
        assert answer.status == 400, answer
        assert answer.body == b'{"error":"Invalid Content-Length"}', answer
        _assert_serving(port)

    def test_two_content_length_headers_answer_400_even_when_they_agree(self, server):
        """ADR-0068: a second Content-Length is refused outright, agreeing or
        not - the stricter reading, and what llhttp (Node) already does."""
        _proc, port = server
        for pair in ("Content-Length: 3\r\nContent-Length: 3\r\n", "Content-Length: 3\r\ncontent-length: 3\r\n"):
            answer = _exchange(port, _post_head(pair) + b"abc")
            assert answer.status == 400, answer
            assert answer.body == b'{"error":"Invalid Content-Length"}', answer
        _assert_serving(port)

    @pytest.mark.parametrize("raw", [
        _post_head("Content-Length: 5\r\nTransfer-Encoding: chunked\r\n") + b"0\r\n\r\n",
        _post_head("Transfer-Encoding: gzip\r\n") + b"hello",
        _post_head("Transfer-Encoding: gzip, chunked\r\n") + b"0\r\n\r\n",
        _post_head("Transfer-Encoding: chunked\r\n") + b"zz\r\nhello\r\n0\r\n\r\n",
        _post_head("Transfer-Encoding: chunked\r\n") + b"5\r\nhelloXX0\r\n\r\n",
    ])
    def test_conflicting_content_length_and_transfer_encoding_answer_400(self, server, raw):
        _proc, port = server
        answer = _exchange(port, raw)
        assert answer.status == 400, answer
        assert answer.body == b'{"error":"Invalid Transfer-Encoding"}', answer
        _assert_serving(port)

    @pytest.mark.parametrize("raw", [
        b"GET /hello\nX HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
        b"GET /hello HTTP/1.1\r\nHost: 127.0.0.1\r\nX-A: a\nb\r\n\r\n",
        b"GET /hello HTTP/1.1\r\nHost: 127.0.0.1\r\nX-A: a\rb\r\n\r\n",
        b"GET /hello HTTP/1.1\r\nHost: 127.0.0.1\r\nX-A: a\x00b\r\n\r\n",
    ])
    def test_a_request_head_with_a_bare_line_feed_answers_400(self, server, raw):
        _proc, port = server
        answer = _exchange(port, raw)
        assert answer.status == 400, answer
        assert answer.body == b'{"error":"Malformed request head"}', answer
        _assert_serving(port)

    @pytest.mark.parametrize("raw", [
        b"GET /hello HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Big: " + b"a" * 9000 + b"\r\n\r\n",
        b"GET /hello HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Big: " + b"a" * 200_000,
    ])
    def test_an_oversized_header_block_answers_431(self, server, raw):
        _proc, port = server
        answer = _exchange(port, raw)
        assert answer.status == 431, answer
        assert answer.body == (b'{"error":"Request header fields exceed '
                               b'TINA4_MAX_REQUEST_HEADER (8192 bytes)"}'), answer
        _assert_serving(port)

    def test_a_stalled_partial_request_answers_408(self, server):
        _proc, port = server
        for partial in (_post_head("Content-Length: 10\r\n") + b"abc",
                        b"GET /hello HTTP/1.1\r\nHost: 127.0.0.1\r\n"):
            started = time.monotonic()
            answer = _exchange(port, partial, timeout=IDLE_SECONDS + 5)
            elapsed = time.monotonic() - started
            assert answer.status == 408, answer
            assert answer.body == b'{"error":"Request timed out before it was complete"}', answer
            assert IDLE_SECONDS - 0.5 <= elapsed < IDLE_SECONDS + 3, f"{elapsed:.1f}s"
        # A connection that never sent a byte has no request to answer.
        silent = _exchange(port, b"", timeout=IDLE_SECONDS + 5)
        assert silent.raw == b"", silent
        _assert_serving(port)

    def test_the_server_keeps_serving_after_every_rejection(self, server):
        proc, port = server
        rejections = [
            _post_head("Content-Length: abc\r\n"),
            _post_head(f"Content-Length: {LIMIT + 1}\r\n"),
            b"GET /hello HTTP/1.1\r\nX-Big: " + b"a" * 20_000 + b"\r\n\r\n",
            b"GET /hello\nX HTTP/1.1\r\n\r\n",
            b"GET /direct-append HTTP/1.1\r\n\r\n",
        ]
        for raw in rejections * 3:
            assert _exchange(port, raw).status in (400, 413, 431, 500)
        _assert_serving(port)
        assert proc.poll() is None, "the server process died"
        log = read_child_log(proc)
        for leak in ("Task exception was never retrieved", "Traceback", "LimitOverrunError"):
            assert leak not in log, f"server logged {leak!r}:\n{log[-2000:]}"


def _read_one_response(sock, head_only=False) -> Answer:
    """One response off a connection that stays open: head, then Content-Length bytes."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(65536)
        if not chunk:
            return Answer(data)
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    answer = Answer(head + b"\r\n\r\n")
    length = 0 if head_only else int(answer.one("content-length") or 0)
    while len(rest) < length:
        chunk = sock.recv(65536)
        if not chunk:
            break
        rest += chunk
    answer.body = rest[:length]
    answer.extra = rest[length:]
    return answer


def _closed_by_server(sock) -> bool:
    try:
        return sock.recv(1) == b""
    except (socket.timeout, TimeoutError):
        return False
    except ConnectionResetError:
        return True


class TestAsgiPath:
    def test_the_asgi_path_refuses_an_unsafe_header_with_the_same_answer(self, tmp_path):
        """Under uvicorn, h11 refuses the header natively - but the client must
        still get the ADR-0068 answer, not h11's own plain-text 500."""
        proc, port = _boot(tmp_path, builtin=False)
        try:
            answer = _exchange(port, b"GET /direct-append HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            assert answer.one("server") == "uvicorn", "expected uvicorn: " + repr(answer)
            assert answer.status == 500, answer
            assert answer.body == b'{"error":"Invalid response header"}', answer
            assert answer.one("content-type") == "application/json", answer
            assert "x-injected" not in answer.headers and "x-direct" not in answer.headers, answer
            for name, value in SECURITY_HEADERS.items():
                assert answer.one(name) == value, f"{name}: {answer}"
            time.sleep(0.2)
            assert "X-Direct" in read_child_log(proc)
        finally:
            _stop(proc)


class TestHttp11:
    def test_keep_alive_serves_every_request_on_one_connection(self, server):
        _proc, port = server
        request = b"GET /hello HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            for _ in range(3):  # one at a time on the same socket
                sock.sendall(request)
                answer = _read_one_response(sock)
                assert answer.status == 200 and json.loads(answer.body) == {"ok": True}, answer
            sock.sendall(request * 2)  # pipelined
            first = _read_one_response(sock)
            second = _read_one_response(sock) if not first.extra else Answer(first.extra)
            assert first.status == 200 and second.status == 200, (first, second)

    def test_connection_close_is_honoured(self, server):
        _proc, port = server
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            sock.sendall(b"GET /hello HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
            answer = _read_one_response(sock)
            assert answer.status == 200, answer
            assert answer.one("connection") == "close", answer
            assert _closed_by_server(sock), "the server kept a Connection: close socket open"
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            sock.sendall(b"GET /hello HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
            assert _read_one_response(sock).status == 200
            assert _closed_by_server(sock), "an HTTP/1.0 request without keep-alive must close"

    def test_head_answers_the_get_content_length_without_a_body(self, server, tmp_path):
        def check(port):
            with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
                sock.sendall(b"GET /hello HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
                get = _read_one_response(sock)
                sock.sendall(b"HEAD /hello HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
                head = _read_one_response(sock, head_only=True)
                assert head.status == 200, head
                assert head.headers.get("content-length") == [str(len(get.body))], head
                # No body follows: the next thing on the socket is the next answer.
                sock.sendall(b"GET /hello HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
                after = _read_one_response(sock)
                assert after.status == 200 and after.body == get.body, after

        check(server[1])
        proc, asgi_port = _boot(tmp_path, builtin=False)
        try:
            check(asgi_port)
        finally:
            _stop(proc)


class TestRejectionShape:
    def _assert_shape(self, answer, status, body, builtin=True):
        assert answer.status == status, answer
        assert answer.body == body, answer
        assert answer.one("content-type") == "application/json", answer
        assert answer.one("content-length") == str(len(body)), answer
        if builtin:
            # Under uvicorn the connection is uvicorn's to manage.
            assert answer.one("connection") == "close", answer
        for name, value in SECURITY_HEADERS.items():
            assert answer.one(name) == value, f"{name}: {answer}"
        assert "strict-transport-security" not in answer.headers, answer

    def test_a_transport_rejection_carries_the_json_body_and_security_headers(self, server, tmp_path):
        _proc, port = server
        self._assert_shape(_exchange(port, _post_head(f"Content-Length: {LIMIT + 1}\r\n")),
                           413, _body_413(LIMIT + 1))
        self._assert_shape(_exchange(port, _post_head("Content-Length: x\r\n")),
                           400, b'{"error":"Invalid Content-Length"}')
        self._assert_shape(
            _exchange(port, b"GET / HTTP/1.1\r\nX-Big: " + b"a" * 9000 + b"\r\n\r\n"),
            431, b'{"error":"Request header fields exceed TINA4_MAX_REQUEST_HEADER (8192 bytes)"}')

        # The ASGI path answers the same bytes under a real uvicorn.
        proc, asgi_port = _boot(tmp_path, builtin=False)
        try:
            answer = _exchange(asgi_port, _post_head(f"Content-Length: {LIMIT + 1}\r\n"))
            assert answer.one("server") == "uvicorn", "expected uvicorn: " + repr(answer)
            self._assert_shape(answer, 413, _body_413(LIMIT + 1), builtin=False)
        finally:
            _stop(proc)
