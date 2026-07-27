"""The shared child-server boot helper (tests/conftest.py).

Four test files each carried their own copy of a boot handshake with the same
race: pick a free port, close the socket, then let the child bind it. Anything
can take the port in that gap, and under a full suite that happens. The old
assertion said only "child server never bound the port" and threw away the
child's captured output, so a lost race and a real crash were indistinguishable.

These pin the two behaviours that make the helper trustworthy: a real failure
must fail FAST and say why, and only the port race may be retried.
"""

import time

from conftest import boot_child_server, free_port, port_open


def test_a_real_failure_reports_what_the_child_printed(tmp_path):
    """A child that dies for its own reasons must surface its output, not a bare
    "never bound the port"."""
    def write_app(proj, port):
        (proj / "app.py").write_text(
            "import sys\n"
            "print('BOOT_FAILED: the database exploded')\n"
            "sys.exit(3)\n"
        )

    start = time.time()
    try:
        boot_child_server(tmp_path, write_app, boot_timeout=10)
        raise AssertionError("expected the boot to fail")
    except AssertionError as exc:
        message = str(exc)

    assert "BOOT_FAILED: the database exploded" in message, message
    assert "exited during startup" in message, message
    # Fails fast: one attempt, not three, and nowhere near the 10s timeout.
    assert message.count("attempt ") == 1, f"a real failure must not retry:\n{message}"
    assert time.time() - start < 10, "should not have waited out the boot timeout"


def test_a_healthy_child_is_returned_once_it_answers(tmp_path):
    """The happy path returns only after the port genuinely accepts a connection."""
    def write_app(proj, port):
        (proj / "app.py").write_text(
            "import socket\n"
            f"s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            f"s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
            f"s.bind(('127.0.0.1', {port}))\n"
            "s.listen(5)\n"
            "import time\n"
            "time.sleep(30)\n"
        )

    proc, port = boot_child_server(tmp_path, write_app, boot_timeout=20)
    try:
        assert port_open(port), "helper returned before the port was accepting"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_free_port_hands_out_a_port_nothing_is_listening_on():
    port = free_port()
    assert 1024 < port < 65536
    assert not port_open(port, timeout=0.2)
