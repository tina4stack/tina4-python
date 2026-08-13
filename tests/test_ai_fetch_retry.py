"""`install_skills()`'s GitHub fetch (`tina4_python.ai._fetch_bytes`) must survive
raw.githubusercontent.com's intermittent 503-under-load — a freshly cut release
tag is "cold" on GitHub's CDN until it warms, and one `tina4 ai` install makes
~30 fetches, so a single transient blip must not abort the whole install.

Real local HTTP server (stdlib http.server on a real socket), no mocks, no
monkeypatched urllib/time — proves the retry loop actually rides through
retryable statuses, and that a permanent 404 is NOT retried (fails fast)."""
import http.server
import threading
import time

from tina4_python.ai import _fetch_bytes


class _SequenceServer:
    """Serves a scripted SEQUENCE of (status, body) per path, advancing one
    step on every hit to that path. Lets us drive the real retry loop
    (503, 503, 200) against a real socket — no mock, no monkeypatched
    urllib, and no patched time.sleep."""

    def __init__(self, sequences):
        # sequences: path -> list of (status, body_bytes)
        self.sequences = {p: list(seq) for p, seq in sequences.items()}
        self.hits = {p: 0 for p in sequences}
        seqs = self.sequences
        hits = self.hits

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # silence the test server
                pass

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                seq = seqs.get(path, [(200, b"ok")])
                idx = min(hits.get(path, 0), len(seq) - 1)
                hits[path] = hits.get(path, 0) + 1
                status, payload = seq[idx]
                self.send_response(status)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if payload:
                    self.wfile.write(payload)

        self._httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def count(self, path):
        return self.hits.get(path, 0)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()


def test_fetch_retries_transient_503_then_returns_body():
    """POSITIVE: two transient 503s, then a 200 — _fetch_bytes must ride
    through both and hand back the real body (not None)."""
    with _SequenceServer({"/skill": [(503, b"down"), (503, b"down"),
                                      (200, b"skill body")]}) as s:
        data = _fetch_bytes(f"{s.base_url}/skill")
        assert data == b"skill body"
        assert s.count("/skill") == 3  # proves it actually retried twice, not just once


def test_fetch_fast_fails_persistent_404_without_retrying():
    """NEGATIVE: a permanent 404 must return None on the FIRST attempt — no
    retry, no backoff sleep. If the loop wrongly retried a 404 this would
    take 2 + 4 + 6 + 8 = 20s+ (and hit the server 5 times instead of 1); the
    elapsed-time bound is what makes this a "fails fast" assertion rather
    than just a status check."""
    with _SequenceServer({"/missing": [(404, b"not found")]}) as s:
        start = time.monotonic()
        data = _fetch_bytes(f"{s.base_url}/missing")
        elapsed = time.monotonic() - start

        assert data is None
        assert s.count("/missing") == 1  # NEGATIVE: no retry on a permanent 404
        assert elapsed < 2.0  # fast — well under even a single 2s backoff sleep
