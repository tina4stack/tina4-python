# Shared contract suite for feature 40 -- HTTP compression + ETag.
#
# Fixture: tina4-documentation/plan/v3/fixtures/compression_etag_contract.json
# Decisions: CE-DEC-01 (parity -- gzip + dynamic ETag + conditional-GET are a
# real four-language feature, ported to PHP/Ruby/Node) + CE-DEC-02 (one pinned
# weak static ETag format `W/"<size>-<mtime>"` across the four; Python's 304
# now preserves ETag/Last-Modified; If-None-Match matching unified on RFC-7232
# weak comparison).
#
# NO MOCKS. Every case boots a REAL server (uvicorn -- the production ASGI
# server tina4 ships -- in a child process), driven over REAL HTTP (urllib, a
# genuine TCP socket) with real Accept-Encoding / If-None-Match /
# If-Modified-Since request headers and a real gzip.decompress() of the wire
# body. One server is booted ONCE per module and shared by every case below.
import gzip
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A round epoch second -- avoids any float/timezone rounding ambiguity when
# comparing the static ETag's <mtime> component byte-for-byte.
_FIXED_MTIME = 1700000000


def _free_port() -> int:
    """A port free right now -- the child binds it a moment later (small race, fine for a test)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# The child app: real routes (a >1KB compressible JSON body, a tiny JSON body,
# and a >1KB octet-stream body) plus a real static CSS file with a FIXED mtime
# (via os.utime) so the pinned static-ETag format is byte-exact-assertable.
_CHILD_APP = '''\
import os

from tina4_python.core.router import get

STATIC_DIR = os.environ["CE_STATIC_DIR"]
STATIC_FILE = os.path.join(STATIC_DIR, "asset.css")


@get("/big")
async def _big(request, response):
    # ~2010 bytes serialized, all-'x' repeats -> compresses hard, a strong
    # positive gzip signal when the decompressed body is checked byte-exact.
    return response({"data": "x" * 2000})


@get("/small")
async def _small(request, response):
    return response({"ok": True})


@get("/binary")
async def _binary(request, response):
    # >1KB, highly-compressible BYTES, but a non-compressible declared
    # content-type -- proves the content-type gate, not just a size gate.
    return response(b"x" * 2000, 200, "application/octet-stream")


from tina4_python.core.server import app
import uvicorn

uvicorn.run(app, host="127.0.0.1", port=int(os.environ["CE_PORT"]), log_level="warning")
'''


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """One real server for the whole module -- real uvicorn, a real static
    file on disk, shared by every wire case below (no mocks anywhere)."""
    tmp_path = tmp_path_factory.mktemp("compression_etag_contract")
    static_dir = tmp_path / "public"
    static_dir.mkdir()
    static_file = static_dir / "asset.css"
    # Padded past 1KB so the static file ALSO exercises the compression gate,
    # not only the ETag-format gate.
    static_file.write_text(".contract-etag-fixture { color: red; }\n" + ("/* pad */\n" * 80))
    os.utime(static_file, (_FIXED_MTIME, _FIXED_MTIME))
    expected_size = static_file.stat().st_size

    script = tmp_path / "child_app.py"
    script.write_text(_CHILD_APP)
    port = _free_port()

    env = {
        **os.environ,
        "CE_PORT": str(port),
        "CE_STATIC_DIR": str(static_dir),
        "TINA4_PUBLIC_DIR": str(static_dir),
        "TINA4_SECRET": "compression-etag-contract-secret",
        "TINA4_SUPPRESS": "true",
        "TINA4_NO_BROWSER": "true",
        "TINA4_DEBUG": "false",
    }
    proc = subprocess.Popen([sys.executable, str(script)], cwd=REPO_ROOT, env=env)
    try:
        deadline = time.time() + 20
        ready = False
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    ready = True
                    break
            except OSError:
                pass
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        assert ready, f"compression/etag contract child server never became ready (exit={proc.poll()})"
        yield {
            "base": f"http://127.0.0.1:{port}",
            "static_path": "/asset.css",
            "static_size": expected_size,
            "static_mtime": _FIXED_MTIME,
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _request(server, path, *, headers=None):
    """A REAL HTTP round trip over a genuine TCP socket -- no in-process shortcut.

    Returns (status, headers_dict_lowercase, raw_bytes). Never auto-decompresses
    and never sends Accept-Encoding unless the caller asks for it -- urllib does
    neither by default, which is exactly the control this fixture needs.
    """
    req = urllib.request.Request(server["base"] + path, method="GET")
    for name, value in (headers or {}).items():
        req.add_header(name, value)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            hdrs = {k.lower(): v for k, v in resp.getheaders()}
            return resp.status, hdrs, raw
    except urllib.error.HTTPError as e:
        raw = e.read()
        hdrs = {k.lower(): v for k, v in e.headers.items()}
        return e.code, hdrs, raw


# ── 1. compressible_body_over_1kb_gzips_with_vary ──────────────────────────

def test_compressible_body_over_1kb_gzips_with_vary(server):
    status, hdrs, raw = _request(server, "/big", headers={"Accept-Encoding": "gzip"})
    assert status == 200
    assert hdrs.get("content-encoding") == "gzip"
    assert hdrs.get("vary") == "Accept-Encoding"
    decoded = gzip.decompress(raw)
    assert json.loads(decoded) == {"data": "x" * 2000}

    # Negative: WITHOUT the header -> identity (no Content-Encoding, body is
    # plain JSON as-is).
    status2, hdrs2, raw2 = _request(server, "/big")
    assert status2 == 200
    assert "content-encoding" not in hdrs2
    assert json.loads(raw2) == {"data": "x" * 2000}


# ── 2. small_or_incompressible_body_not_gzipped ─────────────────────────────

def test_small_or_incompressible_body_not_gzipped(server):
    # A body under the 1KB threshold, even with Accept-Encoding: gzip offered.
    status, hdrs, raw = _request(server, "/small", headers={"Accept-Encoding": "gzip"})
    assert status == 200
    assert "content-encoding" not in hdrs
    assert json.loads(raw) == {"ok": True}

    # A >1KB body with a NON-compressible declared content-type.
    status2, hdrs2, raw2 = _request(server, "/binary", headers={"Accept-Encoding": "gzip"})
    assert status2 == 200
    assert "content-encoding" not in hdrs2
    assert raw2 == b"x" * 2000


# ── 3. cacheable_response_carries_an_etag ───────────────────────────────────

def test_cacheable_response_carries_an_etag(server):
    status, hdrs, _raw = _request(server, "/small")
    assert status == 200
    assert hdrs.get("etag"), "a 200-with-content must carry an ETag"


# ── 4. matching_if_none_match_returns_304_preserving_validators ────────────

def test_matching_if_none_match_returns_304_preserving_validators(server):
    # Dynamic response: strong ETag only.
    _status, hdrs, _raw = _request(server, "/small")
    etag = hdrs["etag"]
    status2, hdrs2, raw2 = _request(server, "/small", headers={"If-None-Match": etag})
    assert status2 == 304
    assert raw2 == b""
    assert hdrs2.get("etag") == etag, "CE-PY-304-DROPS-VALIDATORS: a 304 must echo the ETag"

    # Static response: weak ETag AND Last-Modified -- the 304 must preserve BOTH.
    _status, shdrs, _raw = _request(server, server["static_path"])
    setag = shdrs["etag"]
    slast_modified = shdrs["last-modified"]
    status3, hdrs3, raw3 = _request(server, server["static_path"], headers={"If-None-Match": setag})
    assert status3 == 304
    assert raw3 == b""
    assert hdrs3.get("etag") == setag
    assert hdrs3.get("last-modified") == slast_modified, (
        "CE-PY-304-DROPS-VALIDATORS: a static 304 must echo Last-Modified too"
    )


# ── 5. rfc7232_weak_list_star_inm_matches ───────────────────────────────────

def test_rfc7232_weak_list_star_inm_matches(server):
    _status, hdrs, _raw = _request(server, "/small")
    etag = hdrs["etag"]  # a STRONG tag, e.g. "a1b2c3d4e5f60718"
    weak_form = "W/" + etag

    # A lone W/-prefixed candidate matches via weak comparison.
    status_w, _h, _r = _request(server, "/small", headers={"If-None-Match": weak_form})
    assert status_w == 304, "a W/-prefixed If-None-Match must weak-match the real ETag"

    # A comma-separated list where the SECOND candidate matches.
    status_list, _h, _r = _request(
        server, "/small", headers={"If-None-Match": f'"not-it", {weak_form}'}
    )
    assert status_list == 304, "a comma-list If-None-Match must match on any candidate"

    # The wildcard.
    status_star, _h, _r = _request(server, "/small", headers={"If-None-Match": "*"})
    assert status_star == 304, "If-None-Match: * must always match"

    # Negative: a genuinely non-matching tag must NOT 304.
    status_miss, _h, _r = _request(server, "/small", headers={"If-None-Match": '"totally-different"'})
    assert status_miss == 200, "a non-matching If-None-Match must serve the body, not 304"


# ── 6. static_etag_format_identical_across_the_four ─────────────────────────

def test_static_etag_format_identical_across_the_four(server):
    status, hdrs, _raw = _request(server, server["static_path"])
    assert status == 200
    expected = f'W/"{server["static_size"]}-{server["static_mtime"]}"'
    assert hdrs.get("etag") == expected, (
        "the pinned cross-language static ETag format is weak W/\"<size>-<mtime>\" "
        f"(decimal, integer-second mtime); got {hdrs.get('etag')!r}"
    )
