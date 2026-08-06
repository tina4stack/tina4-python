"""The upload limit has to bound MEMORY, not report a number afterwards.

Measured 2026-08-06, tina4-python 3.13.95, against a real uvicorn-served app
with the default 10MB ``TINA4_MAX_UPLOAD_SIZE``, POSTing 40MB:

    HTTP 500 Internal Server Error
    server RSS 51.0MB -> 1213.3MB

Two separate defects produced that.

The ASGI reader accumulated with ``body += chunk``. Python bytes are immutable,
so each chunk reallocated and copied the whole buffer - O(N^2) for an N-byte
body, and with uvicorn's ~16KB chunks a 40MB upload cost 1.16GB of resident
memory. The limit was then enforced by ``Request.from_scope`` AFTER that loop
finished, so a body 4x over the limit was accumulated in full and only then
refused. The limit measured the damage instead of preventing it.

And ``PayloadTooLarge`` was raised but caught by nobody, so an oversized upload
answered 500 - which tells the caller to retry the request that will fail again.

After:

    HTTP 413
    server RSS 51.0MB -> 61.4MB     (the 10MB it was allowed, and no more)

Same defect and same fix as the Node request reader; this is the parity half.

No mocks: a real child server over a real loopback socket, a real 40MB POST,
and RSS read from the OS.
"""
import http.client
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import free_port

REPO_ROOT = Path(__file__).resolve().parent.parent

LIMIT = 1_048_576          # 1MB, so the test does not need a 40MB payload
OVERSIZE = LIMIT * 8       # 8MB, comfortably over


def _write_project(root: Path, port: int) -> None:
    (root / "src" / "routes").mkdir(parents=True, exist_ok=True)
    # noauth: writes are secure by default, and a 401 would say nothing about
    # the body cap. The oversized cases never reach the gate anyway - the body
    # is refused before a route is matched - but the under-limit one does.
    (root / "src" / "routes" / "upload.py").write_text(
        "from tina4_python.core.router import post, noauth\n"
        "\n"
        "@post('/upload')\n"
        "@noauth()\n"
        "async def upload(request, response):\n"
        "    return response({'ok': True}, 200)\n"
    )
    (root / "app.py").write_text(
        "from tina4_python.core.server import start\n"
        "if __name__ == '__main__':\n"
        f"    start(host='127.0.0.1', port={port}, no_browser=True, no_reload=True)\n"
    )


def _boot(root: Path, port: int) -> subprocess.Popen:
    env = dict(os.environ)
    env.update({
        "TINA4_OVERRIDE_CLIENT": "true",
        "TINA4_DEBUG": "false",
        "PYTHONPATH": str(REPO_ROOT),
        "TINA4_PORT": str(port),
        "TINA4_MAX_UPLOAD_SIZE": str(LIMIT),
    })
    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=str(root), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return proc
        except OSError:
            if proc.poll() is not None:
                raise AssertionError(f"child server died:\n{proc.stdout.read()}")
            time.sleep(0.2)
    proc.terminate()
    raise AssertionError("child server never bound the port")


def _rss_mb(pid: int) -> float:
    """Resident memory of the server process tree, in MB, from the OS."""
    out = subprocess.run(
        ["ps", "-Ao", "rss,pid,ppid"], capture_output=True, text=True, check=False
    ).stdout
    total = 0
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 3:
            continue
        rss, this_pid, parent = parts[0], parts[1], parts[2]
        if this_pid == str(pid) or parent == str(pid):
            try:
                total += int(rss)
            except ValueError:
                pass
    return total / 1024


def _post(port: int, body: bytes, content_type: str = "application/octet-stream"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
    try:
        conn.request("POST", "/upload", body=body, headers={"Content-Type": content_type})
        res = conn.getresponse()
        return res.status, res.read().decode(errors="replace")
    finally:
        conn.close()


def _post_chunked(port: int, total: int, block: int = 262_144):
    """POST with Transfer-Encoding: chunked and NO Content-Length.

    This is the case the per-chunk cap exists for: with no declared length the
    up-front check has nothing to look at, so the only thing that can stop an
    arbitrarily large body is counting it as it arrives.
    """
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
    try:
        conn.putrequest("POST", "/upload")
        conn.putheader("Content-Type", "application/octet-stream")
        conn.putheader("Transfer-Encoding", "chunked")
        conn.endheaders()
        sent = 0
        payload = b"a" * block
        try:
            while sent < total:
                n = min(block, total - sent)
                conn.send(b"%x\r\n" % n + payload[:n] + b"\r\n")
                sent += n
            conn.send(b"0\r\n\r\n")
        except (BrokenPipeError, ConnectionResetError):
            # The server answered and closed while we were still writing. That
            # is the refusal landing early, which is the point.
            return None, ""
        res = conn.getresponse()
        return res.status, res.read().decode(errors="replace")
    except (http.client.RemoteDisconnected, ConnectionResetError):
        return None, ""
    finally:
        conn.close()


@pytest.fixture
def live_server(tmp_path):
    port = free_port()
    _write_project(tmp_path, port)
    proc = _boot(tmp_path, port)
    try:
        yield proc, port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


class TestRequestBodyCap:
    def test_oversized_body_answers_413_not_500(self, live_server):
        _proc, port = live_server
        status, body = _post(port, b"a" * OVERSIZE)
        assert status == 413, f"expected 413, got {status}: {body[:300]}"
        assert "TINA4_MAX_UPLOAD_SIZE" in body

    def test_oversized_body_does_not_grow_the_server_by_the_payload(self, live_server):
        proc, port = live_server
        time.sleep(0.5)
        before = _rss_mb(proc.pid)
        assert before > 0, "could not read server RSS"

        _post(port, b"a" * OVERSIZE)
        time.sleep(0.75)
        after = _rss_mb(proc.pid)

        grew_mb = after - before
        payload_mb = OVERSIZE / 1_048_576
        # Half the payload is a generous line. The old code grew by ~29x the
        # payload; the fixed one stops at the limit.
        assert grew_mb < payload_mb / 2, (
            f"server grew {grew_mb:.1f}MB on a {payload_mb:.0f}MB body "
            f"with a {LIMIT / 1_048_576:.0f}MB limit"
        )

    def test_body_under_the_limit_still_serves(self, live_server):
        _proc, port = live_server
        status, body = _post(port, b"a" * 1024, "application/json")
        assert status == 200, f"expected 200, got {status}: {body[:300]}"

    def test_a_declared_oversize_content_length_is_refused(self, live_server):
        """from_scope also refuses on the DECLARED length, and that path must
        answer 413 too - it is reached when the client lies about the size."""
        _proc, port = live_server
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
        try:
            body = b"a" * 2048
            conn.putrequest("POST", "/upload")
            conn.putheader("Content-Type", "application/octet-stream")
            conn.putheader("Content-Length", str(OVERSIZE * 4))  # a lie
            conn.endheaders()
            conn.send(body)
            # The server refuses without waiting for the rest; a connection
            # reset here is that refusal arriving before we finished writing.
            try:
                res = conn.getresponse()
                assert res.status == 413, f"expected 413, got {res.status}"
            except (http.client.RemoteDisconnected, ConnectionResetError):
                pass
        finally:
            conn.close()

    def test_a_chunked_body_is_capped_as_it_arrives(self, live_server):
        """No Content-Length means the up-front check sees nothing, so only a
        running count can stop the body. This is the case that grew the server
        by the whole payload before the fix."""
        proc, port = live_server
        time.sleep(0.5)
        before = _rss_mb(proc.pid)
        assert before > 0, "could not read server RSS"

        status, _body = _post_chunked(port, OVERSIZE)
        time.sleep(0.75)
        after = _rss_mb(proc.pid)

        # None means the server closed on us mid-write, which is also a refusal.
        assert status in (413, None), f"expected 413 (or an early close), got {status}"
        grew_mb = after - before
        payload_mb = OVERSIZE / 1_048_576
        assert grew_mb < payload_mb / 2, (
            f"server grew {grew_mb:.1f}MB on a {payload_mb:.0f}MB chunked body "
            f"with a {LIMIT / 1_048_576:.0f}MB limit"
        )
