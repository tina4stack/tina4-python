"""Profile tina4-python ASGI handler to find performance bottlenecks.

Creates a mock ASGI request and measures time spent in each section
of the app() function. Run from the benchmarks/ directory:

    python profile_tina4.py
"""
import sys
import os
import time
import asyncio
import cProfile
import pstats
import io

# Setup paths (same as benchmark apps)
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.makedirs("migrations", exist_ok=True)
os.makedirs("src/routes", exist_ok=True)

if "src" in sys.modules:
    del sys.modules["src"]

# Suppress debug output
os.environ["TINA4_DEBUG_LEVEL"] = "[TINA4_LOG_ERROR]"

from tina4_python.Router import get
from tina4_python import app as tina4_app


@get("/api/hello")
async def hello(request, response):
    return response({"message": "Hello, World!"})


# ------------------------------------------------------------------
# Mock ASGI primitives
# ------------------------------------------------------------------
def make_scope(path="/api/hello", method="GET"):
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "server": ("127.0.0.1", 8100),
        "headers": [
            (b"host", b"127.0.0.1:8100"),
            (b"accept", b"application/json"),
            (b"user-agent", b"benchmark/1.0"),
        ],
    }


class MockReceive:
    """Yields a single http.request message with no body."""
    def __init__(self):
        self.called = False

    async def __call__(self):
        if not self.called:
            self.called = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}


class MockSend:
    """Captures ASGI send() calls."""
    def __init__(self):
        self.messages = []

    async def __call__(self, message):
        self.messages.append(message)


# ------------------------------------------------------------------
# Micro-benchmark: time individual components
# ------------------------------------------------------------------
async def time_components():
    """Measure time of each section of the request pipeline."""
    from tina4_python.Webserver import Webserver
    from tina4_python.Router import Router
    from tina4_python.Session import Session
    import tina4_python
    import hashlib

    print("=" * 60)
    print("Component-level timing (1000 iterations each)")
    print("=" * 60)

    N = 1000

    # 1. Webserver instantiation
    t0 = time.perf_counter()
    for _ in range(N):
        ws = Webserver("127.0.0.1", 8100)
    t1 = time.perf_counter()
    print(f"  Webserver()            : {(t1-t0)/N*1000:.4f} ms/call")

    # 2. Router instantiation
    t0 = time.perf_counter()
    for _ in range(N):
        r = Router()
    t1 = time.perf_counter()
    print(f"  Router()               : {(t1-t0)/N*1000:.4f} ms/call")

    # 3. Session instantiation
    t0 = time.perf_counter()
    for _ in range(N):
        s = Session("PY_SESS", os.path.join(os.getcwd(), "sessions"), "SessionFileHandler")
    t1 = time.perf_counter()
    print(f"  Session()              : {(t1-t0)/N*1000:.4f} ms/call")

    # 4. os.getenv (3 calls as in app())
    t0 = time.perf_counter()
    for _ in range(N):
        os.getenv("TINA4_SESSION", "PY_SESS")
        os.getenv("TINA4_SESSION_FOLDER", "sessions")
        os.getenv("TINA4_SESSION_HANDLER", "SessionFileHandler")
    t1 = time.perf_counter()
    print(f"  3x os.getenv()         : {(t1-t0)/N*1000:.4f} ms/call")

    # 5. Session.start() (JWT + MD5 + file write)
    t0 = time.perf_counter()
    for _ in range(N):
        s = Session("PY_SESS", os.path.join(os.getcwd(), "sessions"), "SessionFileHandler")
        s.start()
    t1 = time.perf_counter()
    print(f"  Session() + start()    : {(t1-t0)/N*1000:.4f} ms/call")

    # 6. tina4_auth.get_token() alone
    t0 = time.perf_counter()
    for _ in range(N):
        tina4_python.tina4_auth.get_token(payload_data={})
    t1 = time.perf_counter()
    print(f"  tina4_auth.get_token() : {(t1-t0)/N*1000:.4f} ms/call")

    # 7. tina4_auth.valid() alone
    token = tina4_python.tina4_auth.get_token(payload_data={})
    t0 = time.perf_counter()
    for _ in range(N):
        tina4_python.tina4_auth.valid(token)
    t1 = time.perf_counter()
    print(f"  tina4_auth.valid()     : {(t1-t0)/N*1000:.4f} ms/call")

    # 8. Header parsing
    raw_headers = [
        (b"host", b"127.0.0.1:8100"),
        (b"accept", b"application/json"),
        (b"user-agent", b"benchmark/1.0"),
        (b"content-type", b"application/json"),
        (b"authorization", b"Bearer abc123"),
    ]
    t0 = time.perf_counter()
    for _ in range(N):
        parsed = {}
        parsed_lc = {}
        for h in raw_headers:
            parsed[h[0].decode()] = h[1].decode()
            parsed_lc[h[0].decode().lower()] = h[1].decode()
    t1 = time.perf_counter()
    print(f"  Header parse (5 hdrs)  : {(t1-t0)/N*1000:.4f} ms/call")

    # 9. os.path.isfile() on non-existent path (static file check)
    fake_path = os.path.join(os.getcwd(), "src", "public", "api", "hello")
    t0 = time.perf_counter()
    for _ in range(N):
        os.path.isfile(fake_path)
    t1 = time.perf_counter()
    print(f"  os.path.isfile()       : {(t1-t0)/N*1000:.4f} ms/call")

    # 10. Route matching (Router.match)
    t0 = time.perf_counter()
    for _ in range(N):
        Router.match("/api/hello", ["/api/hello"])
    t1 = time.perf_counter()
    print(f"  Router.match()         : {(t1-t0)/N*1000:.4f} ms/call")

    # 11. inspect.signature (called per request in get_result)
    import inspect
    t0 = time.perf_counter()
    for _ in range(N):
        inspect.signature(hello)
    t1 = time.perf_counter()
    print(f"  inspect.signature()    : {(t1-t0)/N*1000:.4f} ms/call")

    # 12. sys.stdout redirect + StringIO
    t0 = time.perf_counter()
    for _ in range(N):
        old = sys.stdout
        sys.stdout = io.StringIO()
        sys.stdout = old
    t1 = time.perf_counter()
    print(f"  stdout redirect        : {(t1-t0)/N*1000:.4f} ms/call")

    # 13. Full ASGI request cycle
    t0 = time.perf_counter()
    for _ in range(N):
        scope = make_scope()
        receive = MockReceive()
        send = MockSend()
        await tina4_app(scope, receive, send)
    t1 = time.perf_counter()
    full_ms = (t1 - t0) / N * 1000
    print(f"\n  FULL REQUEST CYCLE     : {full_ms:.4f} ms/call")
    print(f"  Theoretical max RPS    : {1000/full_ms:.0f} req/s (single-threaded)")


# ------------------------------------------------------------------
# cProfile: detailed call tree
# ------------------------------------------------------------------
async def profile_with_cprofile():
    """Run cProfile on 500 ASGI requests to see call tree."""
    N = 500

    async def run_requests():
        for _ in range(N):
            scope = make_scope()
            receive = MockReceive()
            send = MockSend()
            await tina4_app(scope, receive, send)

    pr = cProfile.Profile()
    pr.enable()
    await run_requests()
    pr.disable()

    print("\n" + "=" * 60)
    print(f"cProfile results ({N} requests)")
    print("=" * 60)

    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s)
    ps.sort_stats("cumulative")
    ps.print_stats(40)
    print(s.getvalue())

    # Also show by total time
    s2 = io.StringIO()
    ps2 = pstats.Stats(pr, stream=s2)
    ps2.sort_stats("tottime")
    ps2.print_stats(30)
    print("\n--- Sorted by total time ---")
    print(s2.getvalue())


async def main():
    # Warmup: one request to initialize everything
    scope = make_scope()
    receive = MockReceive()
    send = MockSend()
    await tina4_app(scope, receive, send)

    # Verify it works
    assert len(send.messages) == 2, f"Expected 2 ASGI messages, got {len(send.messages)}"
    assert send.messages[0]["status"] == 200, f"Expected 200, got {send.messages[0]['status']}"
    print("Warmup OK: 200 response received\n")

    await time_components()
    await profile_with_cprofile()


if __name__ == "__main__":
    asyncio.run(main())
