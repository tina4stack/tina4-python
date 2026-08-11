"""Real-process conformance for identity-checked port takeover (feature 129).

`tina4 serve` reclaims a busy port so a restart does not fail with "address
already in use". Before TAKEOVER-DEC-01/02/03 both takeover paths SIGTERM'd
WHATEVER held the port -- a foreign dev server, a database, a stray listener --
with no check that the victim was a Tina4 dev server. This suite pins the fix.

NO MOCKS. Every case starts a REAL child process that binds a REAL port and
asserts the outcome BY PID: a foreign holder must still be alive afterwards; a
Tina4 holder must be gone. The Tina4 holder records its identity through the REAL
framework `write_pidfile` (the same call the dev server makes for itself).

Mutation proof: delete the identity gate in
`tina4_python/core/port_takeover.take_over_port` (kill every selectable holder,
not just PID-file-confirmed ones) and `test_a_foreign_holder_is_not_killed...`
and `test_the_runtime_path_also_spares_a_foreign_holder` go RED -- the foreign
child gets SIGTERM'd. Restore it and they pass.
"""

import os
import socket
import subprocess
import sys
import time

import pytest

from tina4_python.core.port_takeover import (
    take_over_port,
    write_pidfile,
    KILLED,
    REFUSED_FOREIGN,
    REFUSED_OPTOUT,
    REFUSED_PROD,
)

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX lsof/SIGTERM takeover; the lab + dev are POSIX"
)

# A child that binds a real port and (for the Tina4 case) writes the real PID
# file, then blocks. Its own PID is what the identity check must match.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CHILD = r"""
import sys, socket, time
sys.path.insert(0, {repo!r})
port = int(sys.argv[1]); base = sys.argv[2]; tina4 = sys.argv[3] == "1"
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", port)); s.listen(5)
if tina4:
    from tina4_python.core.port_takeover import write_pidfile
    write_pidfile(port, base)   # REAL framework identity write, records this PID
sys.stdout.write("READY\n"); sys.stdout.flush()
time.sleep(60)
""".format(repo=_REPO_ROOT)


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _listening(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def _wait_exit(proc: subprocess.Popen, timeout: float = 3.0) -> bool:
    """True once *proc* has terminated. poll() reaps it, so a SIGTERM'd child
    is not mistaken for alive as an un-reaped zombie (os.kill(pid, 0) would)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.05)
    return proc.poll() is not None


class _Reaper:
    """Kill everything this suite spawned -- leave NOTHING on the lab."""

    def __init__(self):
        self.procs: list[subprocess.Popen] = []

    def spawn(self, port: int, base_dir: str, tina4: bool) -> subprocess.Popen:
        proc = subprocess.Popen(
            [sys.executable, "-c", _CHILD, str(port), base_dir, "1" if tina4 else "0"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )
        self.procs.append(proc)
        # Wait until it really holds the port (and, for a Tina4 child, has
        # written its PID file) so takeover sees a consistent state.
        deadline = time.time() + 10.0
        pidfile = os.path.join(base_dir, f".tina4-serve-{port}.pid")
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"child exited early: {proc.stderr.read()!r}")
            if _listening(port) and (not tina4 or os.path.exists(pidfile)):
                return proc
            time.sleep(0.05)
        raise RuntimeError(f"child never bound port {port}")

    def cleanup(self):
        for proc in self.procs:
            try:
                os.killpg(os.getpgid(proc.pid), 9)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=3)
            except Exception:
                pass


@pytest.fixture
def reaper():
    r = _Reaper()
    try:
        yield r
    finally:
        r.cleanup()


# ── the four conformance cases (all real processes, asserted by PID) ────────

def test_a_foreign_holder_is_not_killed_and_takeover_refuses(reaper, tmp_path):
    """A NON-Tina4 listener on the port is spared; takeover refuses with a message."""
    port = _free_port()
    foreign = reaper.spawn(port, str(tmp_path), tina4=False)

    result = take_over_port(port, dev=True, no_takeover=False, base_dir=str(tmp_path))

    assert result.status == REFUSED_FOREIGN
    assert "non-Tina4" in result.message
    assert result.killed == []
    # The foreign process must STILL be alive -- proven by PID, not by a mock.
    assert foreign.poll() is None, "takeover killed a foreign (non-Tina4) process"
    assert _listening(port), "the foreign listener was terminated"


def test_a_tina4_dev_server_holder_is_reclaimed(reaper, tmp_path):
    """A real Tina4 holder (identified via its PID file) IS reclaimed."""
    port = _free_port()
    server = reaper.spawn(port, str(tmp_path), tina4=True)

    result = take_over_port(port, dev=True, no_takeover=False, base_dir=str(tmp_path))

    assert result.status == KILLED
    assert result.killed == [server.pid]
    assert _wait_exit(server), "the Tina4 dev server was not reclaimed"


def test_opt_out_refuses_to_kill_the_holder(reaper, tmp_path):
    """TINA4_NO_TAKEOVER / --no-kill refuses to kill even a real Tina4 holder."""
    port = _free_port()
    server = reaper.spawn(port, str(tmp_path), tina4=True)

    result = take_over_port(port, dev=True, no_takeover=True, base_dir=str(tmp_path))

    assert result.status == REFUSED_OPTOUT
    assert result.killed == []
    assert server.poll() is None, "opt-out still killed the holder"


def test_production_mode_refuses_to_kill_the_holder(reaper, tmp_path):
    """Outside dev mode, takeover never kills a port holder (dev-gated)."""
    port = _free_port()
    server = reaper.spawn(port, str(tmp_path), tina4=True)

    result = take_over_port(port, dev=False, no_takeover=False, base_dir=str(tmp_path))

    assert result.status == REFUSED_PROD
    assert result.killed == []
    assert server.poll() is None, "production bind killed a port holder"


def test_the_runtime_path_also_spares_a_foreign_holder(reaper, tmp_path, monkeypatch):
    """The runtime bind-failure fallback runs the SAME identity gate (DEC-02).

    Proves the runtime path is no longer a weaker twin: a foreign holder makes
    it raise and leaves the process alive, instead of SIGTERMing it.
    """
    from tina4_python.core.server import _kill_port

    port = _free_port()
    foreign = reaper.spawn(port, str(tmp_path), tina4=False)
    monkeypatch.setenv("TINA4_DEBUG", "true")
    monkeypatch.delenv("TINA4_NO_TAKEOVER", raising=False)

    with pytest.raises(RuntimeError, match="non-Tina4"):
        _kill_port(port)

    assert foreign.poll() is None, "the runtime path killed a foreign process"
    assert _listening(port)
