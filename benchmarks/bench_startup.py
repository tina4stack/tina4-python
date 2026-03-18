#!/usr/bin/env python3
"""
bench_startup.py — Tina4 startup benchmark

Measures two things:
  1. Import time  — how long `import tina4_python` takes
  2. TTFR         — time from subprocess spawn to first successful HTTP response

Usage:
    python benchmarks/bench_startup.py
    python benchmarks/bench_startup.py --runs 10 --port 7199

Compares:
  - Tina4 dev mode   (TINA4_DEBUG_LEVEL=ALL)
  - Tina4 prod mode  (TINA4_DEBUG_LEVEL=INFO)
  - Flask            (if installed)
  - FastAPI          (if installed)
"""

import argparse
import importlib.util
import os
import statistics
import subprocess
import sys
import time
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_installed(package: str) -> bool:
    return importlib.util.find_spec(package) is not None


def _measure_import(module: str, env: dict, runs: int) -> list[float]:
    """Measure `import <module>` time by spawning a fresh interpreter each run."""
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        result = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            env={**os.environ, **env},
            capture_output=True,
        )
        t1 = time.perf_counter()
        if result.returncode == 0:
            times.append((t1 - t0) * 1000)
    return times


def _wait_for_server(url: str, timeout: float = 10.0) -> float | None:
    """Poll url until 200 or timeout. Returns elapsed ms or None."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as resp:
                if resp.status == 200:
                    return (time.perf_counter() - deadline + timeout) * 1000
        except Exception:
            time.sleep(0.02)
    return None


def _measure_ttfr(cmd: list[str], url: str, env: dict, runs: int, cwd: str | None = None) -> list[float]:
    """Spawn server, time until first HTTP 200, kill, repeat."""
    times = []
    for i in range(runs):
        proc = subprocess.Popen(
            cmd,
            env={**os.environ, **env},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=cwd,
        )
        t0 = time.perf_counter()
        elapsed = _wait_for_server(url)
        t1 = time.perf_counter()
        proc.kill()
        proc.wait()
        if elapsed is not None:
            times.append((t1 - t0) * 1000)
        time.sleep(0.3)  # let port free up
    return times


def _stats(times: list[float]) -> str:
    if not times:
        return "  n/a"
    med = statistics.median(times)
    mn  = min(times)
    mx  = max(times)
    return f"  median {med:6.0f}ms   min {mn:6.0f}ms   max {mx:6.0f}ms   (n={len(times)})"


def _bar(ms: float, scale: float) -> str:
    blocks = int(ms / scale)
    return "█" * min(blocks, 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Tina4 startup benchmark")
    parser.add_argument("--runs",  type=int, default=5,    help="Runs per scenario")
    parser.add_argument("--port",  type=int, default=7199, help="Port for TTFR tests")
    args = parser.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    port = args.port
    runs = args.runs

    tina4_app  = os.path.join(root, "benchmarks", "app_tina4_hypercorn.py")
    flask_app  = os.path.join(root, "benchmarks", "app_flask.py")
    fastapi_app = os.path.join(root, "benchmarks", "app_fastapi.py")

    dev_env  = {"TINA4_DEBUG_LEVEL": "ALL"}
    prod_env = {"TINA4_DEBUG_LEVEL": "INFO"}

    print()
    print("=" * 70)
    print("  Tina4 Startup Benchmark")
    print("=" * 70)

    # ------------------------------------------------------------------
    # 1. Import time
    # ------------------------------------------------------------------
    print()
    print("── Import time (fresh interpreter per run) ──────────────────────")
    print()

    scenarios_import = [
        ("tina4  [dev]",  "tina4_python", dev_env),
        ("tina4  [prod]", "tina4_python", prod_env),
    ]
    if _is_installed("flask"):
        scenarios_import.append(("flask         ", "flask", {}))
    if _is_installed("fastapi"):
        scenarios_import.append(("fastapi       ", "fastapi", {}))

    import_results = {}
    for label, module, env in scenarios_import:
        times = _measure_import(module, env, runs)
        import_results[label] = times
        print(f"  {label}  {_stats(times)}")

    # Bar chart
    print()
    if import_results:
        all_import = [t for ts in import_results.values() for t in ts]
        scale = max(all_import) / 40 if all_import else 1
        for label, times in import_results.items():
            if times:
                bar = _bar(statistics.median(times), scale)
                print(f"  {label}  {bar}")

    # ------------------------------------------------------------------
    # 2. Time to first request
    # ------------------------------------------------------------------
    print()
    print("── Time to first request (TTFR) ─────────────────────────────────")
    print()

    url = f"http://localhost:{port}/api/hello"
    benchmarks_dir = os.path.join(root, "benchmarks")
    hypercorn_bin = os.path.join(root, ".venv", "bin", "hypercorn")
    base_cmd = [
        hypercorn_bin,
        f"--bind=0.0.0.0:{port}",
        "app_tina4_hypercorn:app",
    ]

    scenarios_ttfr = []
    if os.path.isfile(tina4_app) and os.path.isfile(hypercorn_bin):
        scenarios_ttfr += [
            ("tina4  [dev]",  base_cmd, {**dev_env,  "PYTHONPATH": root}),
            ("tina4  [prod]", base_cmd, {**prod_env, "PYTHONPATH": root}),
        ]
    if _is_installed("flask") and os.path.isfile(flask_app):
        scenarios_ttfr.append(("flask         ", [sys.executable, flask_app, str(port)], {}))
    if _is_installed("fastapi") and os.path.isfile(fastapi_app):
        scenarios_ttfr.append(("fastapi       ", [sys.executable, fastapi_app, str(port)], {}))

    ttfr_results = {}
    for label, cmd, env in scenarios_ttfr:
        cwd = benchmarks_dir if "hypercorn" in cmd[0] else None
        times = _measure_ttfr(cmd, url, env, runs, cwd=cwd)
        ttfr_results[label] = times
        print(f"  {label}  {_stats(times)}")

    # Bar chart
    print()
    if ttfr_results:
        all_ttfr = [t for ts in ttfr_results.values() for t in ts]
        scale = max(all_ttfr) / 40 if all_ttfr else 1
        for label, times in ttfr_results.items():
            if times:
                bar = _bar(statistics.median(times), scale)
                print(f"  {label}  {bar}")

    # ------------------------------------------------------------------
    # 3. Dev vs prod savings summary
    # ------------------------------------------------------------------
    dev_import  = import_results.get("tina4  [dev]",  [])
    prod_import = import_results.get("tina4  [prod]", [])
    dev_ttfr    = ttfr_results.get("tina4  [dev]",    [])
    prod_ttfr   = ttfr_results.get("tina4  [prod]",   [])

    if dev_import and prod_import:
        diff = statistics.median(dev_import) - statistics.median(prod_import)
        print()
        print("── Prod vs dev savings ───────────────────────────────────────────")
        print(f"  import  : prod is {diff:+.0f}ms vs dev")
    if dev_ttfr and prod_ttfr:
        diff = statistics.median(dev_ttfr) - statistics.median(prod_ttfr)
        print(f"  TTFR    : prod is {diff:+.0f}ms vs dev")

    print()
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
