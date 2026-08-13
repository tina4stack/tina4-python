"""Feature 128: dual development/test port (the "AI port" at base + 1000).

While a developer edits code, the main dev port hot-reloads. In debug mode
Tina4 also opens a SECOND listener at ``base + 1000`` serving the identical
app with the reload signal turned off -- a stable connection for an AI agent,
a test runner, or an MCP session. See
plan/v3/features/128-dual-test-port.md and
plan/v3/OWNER-DECISIONS.md (DUALPORT-DEC-01/02).

DUALPORT-DEC-01 (DUALPORT-TEST-GAP): before this suite, the bound
``base + 1000`` port had NO real test in Python -- every server-boot test in
this file's own conftest.boot_child_server forced TINA4_NO_AI_PORT=true. Node's
test/aiPortRange.test.ts was the only real dual-port test in any of the four
frameworks. This suite ports that shape to Python: boot a REAL child server
with TINA4_DEBUG=true and assert, over REAL sockets:

  1. base + 1000 accepts a connection and serves the SAME app (a known route
     -- /health -- returns its real body).
  2. a reload-WebSocket UPGRADE on base + 1000 is REFUSED (404, not 101) --
     the AI port suppresses the human dev-toolbar's reload channel.
  3. TINA4_NO_AI_PORT=true leaves ONLY the base port listening.
  4. a BUSY base + 1000 (pre-bound by this test, before the child even starts)
     yields a WARNING and the base port still serves -- non-fatal skip. This is
     the deliberate OPPOSITE of the main port's takeover behaviour (feature
     129): the AI port is a courtesy, not something worth killing a foreign
     process over.

DUALPORT-STABLE-SEMANTICS: "stable" means the CONNECTION and the reload SIGNAL
are stable, not a pinned code version -- a hot-reload via /__dev/api/reload is
reflected on base + 1000 too, on the very next request there.

NO MOCKS: a real child process (``python app.py``), real TCP sockets, a real
raw RFC 6455 upgrade handshake, and the real log file the server actually
wrote to (via ``log_dir=``, so ``Log.warning`` on stdout lands in a file this
test can read without touching a pipe the child would otherwise block on).

Case names (shared with PHP/Ruby/Node --
tina4-documentation/plan/v3/fixtures/dual_port_contract.json):
  - debug_mode_opens_the_ai_port_at_base_plus_1000
  - the_ai_port_refuses_a_reload_websocket_upgrade
  - no_ai_port_env_leaves_only_the_base_port
  - a_busy_ai_port_is_skipped_without_failing_the_base_port

Mutation-proved (2026-08-13, macOS + the Linux lab): temporarily forcing
``_ai_port = port + 1000`` unconditionally in tina4_python/core/server.py
(ignoring TINA4_NO_AI_PORT) turned test_no_ai_port_env_leaves_only_the_base_port
RED -- the AI port opened anyway. Reverted.
"""
import base64
import http.client
import os
import socket
import time

from conftest import boot_child_server, free_port, port_open, read_child_log


def _write_app(project_dir, port):
    (project_dir / "app.py").write_text(
        "from tina4_python.core import run\nrun()\n"
    )


def _http_get(host: str, port: int, path: str, timeout: float = 5.0):
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        return response.status, response.read().decode("utf-8", errors="replace")
    finally:
        conn.close()


def _ws_upgrade_status_line(host: str, port: int, path: str, timeout: float = 5.0) -> str:
    """Send a real RFC 6455 upgrade request and return the response status line."""
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
        f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    )
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        sock.sendall(request.encode())
        sock.settimeout(timeout)
        data = sock.recv(4096)
        return data.decode("utf-8", errors="replace").split("\r\n", 1)[0]
    finally:
        sock.close()


def _free_base_with_headroom() -> int:
    """A free port whose derived AI port (base + 1000) is still a legal port."""
    for _ in range(20):
        candidate = free_port()
        if candidate + 1000 <= 65535:
            return candidate
    raise AssertionError("could not find a free base port with room for +1000")


def test_debug_mode_opens_the_ai_port_at_base_plus_1000(tmp_path):
    """base + 1000 accepts a connection and serves the SAME app."""
    proc, port = boot_child_server(
        tmp_path, _write_app,
        unset_env=("TINA4_NO_AI_PORT",),
        extra_env={"TINA4_DEBUG": "true"},
    )
    try:
        assert proc.poll() is None, "server exited during startup"
        status, body = _http_get("127.0.0.1", port + 1000, "/health")
        assert status == 200, f"AI port /health -> {status}"
        assert "tina4-python" in body, f"AI port did not serve the real app: {body!r}"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_the_ai_port_refuses_a_reload_websocket_upgrade(tmp_path):
    """A reload-WebSocket UPGRADE on base + 1000 is refused (404, not 101)."""
    proc, port = boot_child_server(
        tmp_path, _write_app,
        unset_env=("TINA4_NO_AI_PORT",),
        extra_env={"TINA4_DEBUG": "true"},
    )
    try:
        assert proc.poll() is None, "server exited during startup"
        status_line = _ws_upgrade_status_line("127.0.0.1", port + 1000, "/__dev_reload")
        assert "404" in status_line, f"AI port must refuse the reload WS, got: {status_line!r}"
        assert "101" not in status_line, f"AI port must NOT upgrade the reload WS: {status_line!r}"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_no_ai_port_env_leaves_only_the_base_port(tmp_path):
    """TINA4_NO_AI_PORT=true (the boot_child_server default) leaves only the base port."""
    # No unset_env here: this is the ONE case of the four that keeps
    # boot_child_server's default TINA4_NO_AI_PORT=true -- the negative control.
    proc, port = boot_child_server(
        tmp_path, _write_app,
        extra_env={"TINA4_DEBUG": "true"},
    )
    try:
        assert proc.poll() is None, "server exited during startup"
        status, _ = _http_get("127.0.0.1", port, "/health")
        assert status == 200, f"base port /health -> {status}"
        assert not port_open(port + 1000, timeout=0.5), (
            "TINA4_NO_AI_PORT=true must leave NOTHING listening on base + 1000"
        )
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_a_busy_ai_port_is_skipped_without_failing_the_base_port(tmp_path):
    """A pre-bound base + 1000 is skipped with a warning; the base port still serves."""
    base = _free_base_with_headroom()
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", base + 1000))
    blocker.listen(5)
    log_dir = tmp_path / "logs"
    proc = None
    try:
        proc, port = boot_child_server(
            tmp_path, _write_app,
            unset_env=("TINA4_NO_AI_PORT",),
            extra_env={"TINA4_DEBUG": "true"},
            fixed_port=base,
            log_dir=log_dir,
        )
        assert port == base
        assert proc.poll() is None, "server exited during startup"
        status, _ = _http_get("127.0.0.1", port, "/health")
        assert status == 200, f"base port must still serve when the AI port is busy: {status}"

        # The AI-port bind attempt and its warning run synchronously in the
        # same startup coroutine before the server begins accepting on the
        # base port, but give the write a moment to land on disk regardless.
        time.sleep(0.3)
        log = read_child_log(proc)
        assert str(base + 1000) in log, f"warning must name the busy port; log: {log!r}"
        lowered = log.lower()
        assert "in use" in lowered and "skip" in lowered, (
            f"a busy AI port must warn + skip, never fail the base port; log: {log!r}"
        )
        # The blocker we bound before boot is still the one holding the port --
        # the server never touched it.
        assert port_open(base + 1000), "the pre-bound AI port must remain exactly as we left it"
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=5)
        blocker.close()
