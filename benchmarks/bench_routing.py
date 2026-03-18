#!/usr/bin/env python3
"""
bench_routing.py — Tina4 route-resolution microbenchmark

Measures per-request overhead of the Router hot path:
  1. Route matching (with prefix index vs O(n) scan)
  2. Signature resolution (cached vs inspect.signature per request)
  3. Static file cache hit vs filesystem lookup
  4. URL normalization (string ops vs regex)

Usage:
    python benchmarks/bench_routing.py
    python benchmarks/bench_routing.py --routes 200 --requests 10000
"""

import argparse
import os
import sys
import time
import statistics

# Ensure the project root is on the path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("TINA4_DEBUG_LEVEL", "ERROR")  # suppress debug output


def setup_routes(n_routes):
    """Register n_routes with varied patterns."""
    import tina4_python
    from tina4_python.Router import Router

    Router.reset()

    # Register routes with a mix of fixed and parameterized patterns
    prefixes = ["api", "admin", "auth", "users", "products", "orders", "reports", "settings", "dashboard", "webhook"]
    registered = 0
    for i in range(n_routes):
        prefix = prefixes[i % len(prefixes)]
        if i % 3 == 0:
            path = f"/{prefix}/item{i}"
        elif i % 3 == 1:
            path = f"/{prefix}/item{i}/{{id:int}}"
        else:
            path = f"/{prefix}/item{i}/{{name}}/detail"

        async def handler(request, response, _i=i):
            return response({"route": _i})

        handler.__name__ = f"handler_{i}"
        Router.add("GET", path, handler)
        registered += 1

    return registered


def bench_match(n_routes, n_requests):
    """Benchmark route matching."""
    from tina4_python.Router import Router

    # Pick URLs that match routes at various positions
    prefixes = ["api", "admin", "auth", "users", "products", "orders", "reports", "settings", "dashboard", "webhook"]
    test_urls = []
    for i in range(min(n_requests, n_routes)):
        prefix = prefixes[i % len(prefixes)]
        if i % 3 == 0:
            test_urls.append(f"/{prefix}/item{i}")
        elif i % 3 == 1:
            test_urls.append(f"/{prefix}/item{i}/42")
        else:
            test_urls.append(f"/{prefix}/item{i}/alice/detail")
    # Pad if more requests than routes
    while len(test_urls) < n_requests:
        test_urls.append(test_urls[len(test_urls) % len(test_urls[:n_routes])])

    # Also include some 404 URLs
    miss_urls = ["/nonexistent/path", "/api/missing", "/zzz/nothing"]

    import tina4_python

    # Benchmark indexed matching
    times_indexed = []
    for url in test_urls:
        t0 = time.perf_counter_ns()
        # Simulate what get_result does: use index
        url_segments = Router._normalize_request_url(url)
        first_seg = url_segments[0] if url_segments else ""
        candidates = set()
        if first_seg in Router._route_index:
            candidates.update(Router._route_index[first_seg])
        candidates.update(Router._wildcard_routes)

        for cb in candidates:
            route = tina4_python.tina4_routes.get(cb)
            if route and "GET" in route.get("methods", []):
                if Router.match(url, route["routes"], compiled_routes=route.get("_compiled_routes")):
                    break
        t1 = time.perf_counter_ns()
        times_indexed.append((t1 - t0) / 1000)  # microseconds

    # Benchmark full scan (old behavior)
    times_scan = []
    for url in test_urls:
        t0 = time.perf_counter_ns()
        for route in tina4_python.tina4_routes.values():
            if "GET" in route.get("methods", []):
                if Router.match(url, route["routes"]):
                    break
        t1 = time.perf_counter_ns()
        times_scan.append((t1 - t0) / 1000)

    # Benchmark 404 misses
    times_miss_indexed = []
    for url in miss_urls * (n_requests // 3):
        t0 = time.perf_counter_ns()
        url_segments = Router._normalize_request_url(url)
        first_seg = url_segments[0] if url_segments else ""
        candidates = set()
        if first_seg in Router._route_index:
            candidates.update(Router._route_index[first_seg])
        candidates.update(Router._wildcard_routes)
        for cb in candidates:
            route = tina4_python.tina4_routes.get(cb)
            if route and "GET" in route.get("methods", []):
                Router.match(url, route["routes"], compiled_routes=route.get("_compiled_routes"))
        t1 = time.perf_counter_ns()
        times_miss_indexed.append((t1 - t0) / 1000)

    times_miss_scan = []
    for url in miss_urls * (n_requests // 3):
        t0 = time.perf_counter_ns()
        for route in tina4_python.tina4_routes.values():
            if "GET" in route.get("methods", []):
                Router.match(url, route["routes"])
        t1 = time.perf_counter_ns()
        times_miss_scan.append((t1 - t0) / 1000)

    return times_indexed, times_scan, times_miss_indexed, times_miss_scan


def bench_url_normalization(n_requests):
    """Benchmark URL normalization: string ops vs regex."""
    from tina4_python.Router import Router
    import re

    test_urls = [
        "/api/users/42",
        "/api/products/search?q=test&page=2",
        "//api///items//",
        "/admin/dashboard",
        "/",
        "/api/users/42/orders/100/items",
    ]

    # String-based (current)
    times_string = []
    for _ in range(n_requests):
        for url in test_urls:
            t0 = time.perf_counter_ns()
            Router._normalize_request_url(url)
            t1 = time.perf_counter_ns()
            times_string.append((t1 - t0) / 1000)

    # Regex-based (old)
    def _old_normalize(url):
        url_norm = url.split('?')[0]
        url_norm = re.sub(r'\s+', '', url_norm)
        url_norm = re.sub(r'/+', '/', url_norm)
        url_norm = url_norm.strip('/')
        if not url_norm:
            return []
        return url_norm.split('/')

    times_regex = []
    for _ in range(n_requests):
        for url in test_urls:
            t0 = time.perf_counter_ns()
            _old_normalize(url)
            t1 = time.perf_counter_ns()
            times_regex.append((t1 - t0) / 1000)

    return times_string, times_regex


def _stats(times):
    if not times:
        return "  n/a"
    med = statistics.median(times)
    p95 = sorted(times)[int(len(times) * 0.95)]
    return f"median {med:6.1f}µs   p95 {p95:6.1f}µs   (n={len(times)})"


def main():
    parser = argparse.ArgumentParser(description="Tina4 routing microbenchmark")
    parser.add_argument("--routes", type=int, default=100, help="Number of routes to register")
    parser.add_argument("--requests", type=int, default=5000, help="Number of requests to simulate")
    args = parser.parse_args()

    n_routes = args.routes
    n_requests = args.requests

    print()
    print("=" * 70)
    print("  Tina4 Routing Microbenchmark")
    print("=" * 70)

    registered = setup_routes(n_routes)
    print(f"\n  Registered {registered} routes")

    # Route matching
    print("\n── Route matching (hit) ──────────────────────────────────────────")
    t_idx, t_scan, t_miss_idx, t_miss_scan = bench_match(n_routes, n_requests)
    print(f"  indexed + compiled  {_stats(t_idx)}")
    print(f"  full O(n) scan      {_stats(t_scan)}")

    if t_idx and t_scan:
        speedup = statistics.median(t_scan) / statistics.median(t_idx)
        print(f"  → {speedup:.1f}x faster with index")

    print("\n── Route matching (404 miss) ─────────────────────────────────────")
    print(f"  indexed + compiled  {_stats(t_miss_idx)}")
    print(f"  full O(n) scan      {_stats(t_miss_scan)}")

    if t_miss_idx and t_miss_scan:
        speedup = statistics.median(t_miss_scan) / statistics.median(t_miss_idx)
        print(f"  → {speedup:.1f}x faster with index")

    # URL normalization
    print("\n── URL normalization ─────────────────────────────────────────────")
    t_string, t_regex = bench_url_normalization(n_requests // 6)
    print(f"  string ops          {_stats(t_string)}")
    print(f"  regex               {_stats(t_regex)}")

    if t_string and t_regex:
        speedup = statistics.median(t_regex) / statistics.median(t_string)
        print(f"  → {speedup:.1f}x faster with string ops")

    print()
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
