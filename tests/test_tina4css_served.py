"""tina4css_contract.json :: tina4css-is-served-at-one-url-in-all-four

tina4css is ONE artefact shipped by four packages. Every framework serves it at
``/css/tina4.css`` from its own built-in public directory, and the bytes are
identical in all four.

MEASURED 2026-08-06 on real servers over real sockets - including a PHP project
built by ``composer require`` whose own ``src/public/css`` was empty - all four
answered 200 with 35962 bytes for ``tina4.css`` and 28472 for ``tina4.min.css``.

That parity was true by luck. Nothing asserted it, so a packaging change in one
framework would have gone unnoticed in the other three. This is the assertion.

The companion half - that the committed CSS is a current compile of its .scss
source, and that the four sources have not drifted apart - is checked by
``tina4-documentation/scripts/build-tina4css.py --check``, which needs no
running server. It caught a real one: the shipped ``tina4.min.css`` was 15 bytes
adrift from the current toolchain because its producer, the per-framework SCSS
compiler, had been deleted.

No mocks: a real child server over a real loopback socket.
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
SHIPPED = REPO_ROOT / "tina4_python" / "public" / "css"


def _boot(root: Path, port: int) -> subprocess.Popen:
    (root / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (root / "app.py").write_text(
        "from tina4_python.core.server import start\n"
        "if __name__ == '__main__':\n"
        f"    start(host='127.0.0.1', port={port}, no_browser=True, no_reload=True)\n"
    )
    env = dict(os.environ)
    env.update({
        "TINA4_OVERRIDE_CLIENT": "true",
        "TINA4_DEBUG": "false",
        "PYTHONPATH": str(REPO_ROOT),
        "TINA4_PORT": str(port),
    })
    proc = subprocess.Popen(
        [sys.executable, "app.py"], cwd=str(root), env=env,
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


def _get(port: int, path: str):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        conn.request("GET", path)
        res = conn.getresponse()
        return res.status, res.getheader("content-type") or "", res.read()
    finally:
        conn.close()


@pytest.fixture
def live_server(tmp_path):
    port = free_port()
    proc = _boot(tmp_path, port)
    try:
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


class TestTina4CssServed:
    def test_tina4css_is_served_at_the_canonical_url(self, live_server):
        status, ctype, body = _get(live_server, "/css/tina4.css")
        assert status == 200, f"expected 200, got {status}"
        assert "text/css" in ctype, f"expected text/css, got {ctype!r}"
        # A real stylesheet, not an error page that happened to return 200.
        assert b".container" in body, "served CSS does not contain the .container rule"

    def test_the_minified_build_is_served_at_the_canonical_url(self, live_server):
        status, ctype, minified = _get(live_server, "/css/tina4.min.css")
        assert status == 200, f"expected 200, got {status}"
        assert "text/css" in ctype, f"expected text/css, got {ctype!r}"
        _s, _c, full = _get(live_server, "/css/tina4.css")
        assert len(minified) < len(full), (
            f"the minified build ({len(minified)} bytes) is not smaller than "
            f"the full one ({len(full)} bytes) - it is probably a copy"
        )

    def test_the_served_bytes_are_the_shipped_file_byte_for_byte(self, live_server):
        _status, _ctype, body = _get(live_server, "/css/tina4.css")
        on_disk = (SHIPPED / "tina4.css").read_bytes()
        # Byte equality, not a size check: a truncated or half-written asset
        # still has a plausible length.
        assert body == on_disk, (
            f"served {len(body)} bytes but {SHIPPED / 'tina4.css'} holds "
            f"{len(on_disk)} - the server is not serving the shipped file"
        )
