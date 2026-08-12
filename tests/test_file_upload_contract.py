"""File upload contract (feature 44) - repeated field -> LIST, safe-save, per-chunk cap.

Shared invariants: tina4-documentation/plan/v3/fixtures/fileupload_contract.json
(UP-DEC-02 / UP-DEC-03, OWNER-DECISIONS Batch 4).

No mocks:
  * the repeated-field cases parse a REAL multipart body through the real parser;
  * the safe-save cases write to a REAL temp directory on the real filesystem and
    read back what actually landed (and what did not);
  * the per-chunk cap cases POST to a REAL child server over a real loopback
    socket - a chunked over-size body with NO Content-Length, so only a running
    counter (not the declared-length check) can stop it.

Mutation-proved: revert the repeated-field merge to last-wins and the 'two files'
case goes RED; drop the basename strip in save_upload and the traversal case goes
RED (the escaped path appears); remove the per-chunk counter in server.py and the
over-limit case is accepted (RED).
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
from tina4_python.core.request import Request, save_upload

REPO_ROOT = Path(__file__).resolve().parent.parent
BOUNDARY = "----Tina4FileUploadContract"


def _multipart(files):
    """Build a real multipart body. `files` is a list of (field_name, filename, bytes)."""
    body = b""
    for name, filename, content in files:
        body += (
            f"--{BOUNDARY}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        body += content + b"\r\n"
    body += f"--{BOUNDARY}--\r\n".encode()
    return body


def _parse(body):
    scope = {
        "method": "POST", "path": "/upload", "query_string": b"",
        "headers": [
            (b"content-type", f"multipart/form-data; boundary={BOUNDARY}".encode()),
            (b"content-length", str(len(body)).encode()),
        ],
    }
    return Request.from_scope(scope, body)


# ── UP-MULTIFILE-LOSS: repeated field name -> a LIST ────────────────────────

class TestRepeatedFieldList:
    def test_two_files_under_one_field_name_arrive_as_a_list(self):
        body = _multipart([
            ("photos", "a.txt", b"AAAA-first"),
            ("photos", "b.txt", b"BBBB-second"),
        ])
        files = _parse(body).files
        entry = files["photos"]
        assert isinstance(entry, list), f"expected a list of 2, got {type(entry)}: {entry!r}"
        assert len(entry) == 2, "both files must survive - neither silently dropped"
        assert [f["filename"] for f in entry] == ["a.txt", "b.txt"]
        assert entry[0]["content"] == b"AAAA-first"
        assert entry[1]["content"] == b"BBBB-second"

    def test_a_single_file_stays_a_single_descriptor(self):
        body = _multipart([("avatar", "solo.txt", b"only-one")])
        entry = _parse(body).files["avatar"]
        assert isinstance(entry, dict), "a single occurrence stays a plain descriptor"
        assert entry["filename"] == "solo.txt"
        assert entry["content"] == b"only-one"


# ── UP-FILENAME-UNTRUSTED: safe-save confines the write ─────────────────────

class TestSafeSaveConfines:
    def test_safe_save_writes_a_traversal_filename_inside_the_target_dir(self, tmp_path):
        target = tmp_path / "uploads"
        target.mkdir()
        descriptor = {"filename": "../../evil.txt", "content": b"payload", "type": "text/plain"}

        saved = save_upload(descriptor, str(target))

        # It landed INSIDE the target dir, under the stripped basename ...
        assert Path(saved).parent == target
        assert Path(saved).name == "evil.txt"
        assert (target / "evil.txt").read_bytes() == b"payload"
        # ... and NOT at the escaped location the raw name pointed at.
        assert not (tmp_path / "evil.txt").exists(), "the traversal escaped the target dir"

    def test_safe_save_refuses_an_unusable_filename(self, tmp_path):
        target = tmp_path / "uploads"
        target.mkdir()
        # A bare '..' has no usable basename; a NUL byte is an attack marker.
        with pytest.raises(ValueError):
            save_upload({"filename": "..", "content": b"x"}, str(target))
        with pytest.raises(ValueError):
            save_upload({"filename": "ok\x00.txt", "content": b"x"}, str(target))


# ── UP-CHUNKED-BYPASS: running per-chunk size guard (413 mid-stream) ─────────

LIMIT = 1_048_576          # 1MB cap for the child server
OVERSIZE = LIMIT * 4       # 4MB, comfortably over


def _write_project(root, port):
    (root / "src" / "routes").mkdir(parents=True, exist_ok=True)
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


def _boot(root, port):
    env = dict(os.environ)
    env.update({
        "TINA4_OVERRIDE_CLIENT": "true", "TINA4_DEBUG": "false",
        "PYTHONPATH": str(REPO_ROOT), "TINA4_PORT": str(port),
        "TINA4_MAX_UPLOAD_SIZE": str(LIMIT),
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


@pytest.fixture
def live_server(tmp_path):
    port = free_port()
    _write_project(tmp_path, port)
    proc = _boot(tmp_path, port)
    try:
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _post_chunked(port, total, block=262_144):
    """POST with Transfer-Encoding: chunked and NO Content-Length - the case the
    running counter exists for (the declared-length check sees nothing)."""
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
            return None
        res = conn.getresponse()
        return res.status
    except (http.client.RemoteDisconnected, ConnectionResetError):
        return None
    finally:
        conn.close()


class TestPerChunkSizeGuard:
    def test_an_over_limit_upload_is_refused_with_413(self, live_server):
        status = _post_chunked(live_server, OVERSIZE)
        # None = the server refused and closed while we were still writing, which
        # is the refusal landing early - also acceptable.
        assert status in (413, None), f"expected 413 (or an early close), got {status}"

    def test_a_body_under_the_limit_is_accepted(self, live_server):
        conn = http.client.HTTPConnection("127.0.0.1", live_server, timeout=60)
        try:
            conn.request("POST", "/upload", body=b"a" * 1024,
                         headers={"Content-Type": "application/json"})
            res = conn.getresponse()
            res.read()
            assert res.status == 200, f"expected 200, got {res.status}"
        finally:
            conn.close()
