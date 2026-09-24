"""A binary body sent with an EXPLICIT content type arrives byte for byte.

The bug class (found in tina4-nodejs, checked here at parity): a byte body
given with a content type is re-encoded as text on the way out. In Python the
holes were ``send(bytes, status, content_type)`` - it kept only dict/list/str
and silently dropped a bytes body - and ``bytearray`` / ``memoryview``, which
fell through to ``str(data)`` and sent the text ``bytearray(b'...')``.

One REAL server started by the framework's own ``run()`` in a child process,
real routes, a real socket. Each route sends all 256 byte values (0x00-0xFF)
and the client compares the raw bytes it received. No mocks.
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ALL_BYTES = bytes(range(256))

_CHILD_APP = '''\
import os
from tina4_python.core.router import get

ALL_BYTES = bytes(range(256))


@get("/bin/call")
async def binary_call(request, response):
    return response(ALL_BYTES, 200, "image/png")


@get("/bin/send")
async def binary_send(request, response):
    return response.send(ALL_BYTES, 200, "application/octet-stream")


@get("/bin/bytearray")
async def binary_bytearray(request, response):
    return response(bytearray(ALL_BYTES), 200, "application/octet-stream")


@get("/bin/memoryview")
async def binary_memoryview(request, response):
    return response(memoryview(ALL_BYTES), 200, "application/octet-stream")


@get("/bin/auto")
async def binary_auto(request, response):
    return response(bytearray(ALL_BYTES))


@get("/bin/text")
async def text_explicit(request, response):
    return response("h\\u00e9llo", 200, "text/plain; charset=utf-8")


@get("/bin/json")
async def json_explicit(request, response):
    return response({"a": 1}, 200, "application/vnd.api+json")


from tina4_python.core.server import run
run(host="127.0.0.1", port=int(os.environ["BINARY_PORT"]), no_browser=True, no_reload=True)
'''


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _get(port: int, path: str):
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"Accept-Encoding": "identity"})
    with urllib.request.urlopen(request, timeout=10) as reply:
        return reply.status, reply.headers.get("Content-Type", ""), reply.read()


def test_binary_bodies_arrive_unchanged_through_a_real_server(tmp_path):
    script = tmp_path / "binary_app.py"
    script.write_text(_CHILD_APP)
    port = _free_port()
    env = {**os.environ, "BINARY_PORT": str(port), "TINA4_SUPPRESS": "true", "TINA4_NO_BROWSER": "true", "TINA4_OVERRIDE_CLIENT": "true"}
    proc = subprocess.Popen([sys.executable, str(script)], cwd=tmp_path, env=env)
    try:
        deadline = time.time() + 30
        while True:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                assert proc.poll() is None, "the server process exited before it listened"
                assert time.time() < deadline, "the server did not listen within 30s"
                time.sleep(0.2)

        # Positive: every byte body with an explicit type arrives identical.
        for path, content_type in (
            ("/bin/call", "image/png"),
            ("/bin/send", "application/octet-stream"),
            ("/bin/bytearray", "application/octet-stream"),
            ("/bin/memoryview", "application/octet-stream"),
        ):
            status, received_type, body = _get(port, path)
            assert status == 200, f"{path}: status {status}"
            assert received_type == content_type, f"{path}: content type {received_type!r}"
            assert body == ALL_BYTES, f"{path}: got {len(body)} bytes, starting {body[:24]!r}"

        # Controls: the other branches still behave.
        _, received_type, body = _get(port, "/bin/auto")
        assert received_type == "application/octet-stream" and body == ALL_BYTES, f"auto: {received_type!r} {body[:24]!r}"
        _, _, body = _get(port, "/bin/text")
        assert body == "héllo".encode("utf-8"), f"text: {body!r}"
        _, received_type, body = _get(port, "/bin/json")
        assert received_type == "application/vnd.api+json" and body == b'{"a":1}', f"json: {received_type!r} {body!r}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
