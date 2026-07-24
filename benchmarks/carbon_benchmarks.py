#!/usr/bin/env python3
"""Tina4 v3 Carbon Benchmarks — 9 workload categories.

Run all:      python benchmarks/carbon_benchmarks.py
Run one:      python benchmarks/carbon_benchmarks.py json
Startup cost: python benchmarks/carbon_benchmarks.py --startup
Carbon (SCI): python benchmarks/carbon_benchmarks.py --carbon
Categories:   json, db_single, db_multi, template, json_large,
              plaintext, crud, paginated, startup

By default this reports WALL-CLOCK time and throughput. `--carbon` shells out to
the real Carbonah CLI for Software Carbon Intensity; `--startup` spawns fresh
interpreters to measure per-process import cost, which no in-process loop can
see (Python caches modules, so a repeated import is a dict lookup).
"""
import sys
import os
import time
import json
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

ITERATIONS = 1000


def bench_json():
    """1. JSON serialization — raw overhead."""
    from tina4_python.core.response import Response
    for _ in range(ITERATIONS):
        r = Response()
        r.json({"message": "Hello, World!", "status": "ok"})


def bench_db_single():
    """2. Single database query."""
    from tina4_python.database import Database
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(f"sqlite:///{tmp}/bench.db")
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
        db.execute("INSERT INTO users VALUES (1, 'Alice', 'alice@test.com')")
        db.commit()
        for _ in range(ITERATIONS):
            db.fetch_one("SELECT * FROM users WHERE id = ?", [1])
        db.close()


def bench_db_multi():
    """3. Multiple database queries."""
    from tina4_python.database import Database
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(f"sqlite:///{tmp}/bench.db")
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, price REAL)")
        for i in range(100):
            db.execute("INSERT INTO items VALUES (?, ?, ?)", [i, f"Item {i}", i * 1.5])
        db.commit()
        for _ in range(ITERATIONS):
            db.fetch("SELECT * FROM items WHERE price > ?", [50.0], limit=20)
            db.fetch_one("SELECT COUNT(*) as cnt FROM items")
            db.fetch("SELECT * FROM items ORDER BY price DESC", limit=5)
        db.close()


def bench_template():
    """4. Template rendering."""
    from tina4_python.frond import Frond
    with tempfile.TemporaryDirectory() as tmp:
        engine = Frond(template_dir=tmp)
        tpl = """<!DOCTYPE html>
<html>
<head><title>{{ title }}</title></head>
<body>
<h1>{{ heading }}</h1>
<ul>
{% for item in items %}
<li class="{{ loop.even ? 'even' : 'odd' }}">{{ loop.index }}. {{ item.name | upper }} — ${{ item.price | number_format(2) }}</li>
{% endfor %}
</ul>
{% if show_footer %}
<footer>{{ footer_text | truncate(50) }}</footer>
{% endif %}
</body>
</html>"""
        data = {
            "title": "Benchmark Page",
            "heading": "Product List",
            "items": [{"name": f"Product {i}", "price": i * 9.99} for i in range(20)],
            "show_footer": True,
            "footer_text": "This is a footer with some text that may be truncated for display purposes.",
        }
        for _ in range(ITERATIONS):
            engine.render_string(tpl, data)


def bench_json_large():
    """5. Large JSON payload."""
    from tina4_python.core.response import Response
    payload = {
        "users": [
            {"id": i, "name": f"User {i}", "email": f"user{i}@test.com",
             "active": i % 2 == 0, "score": i * 1.5,
             "tags": ["tag1", "tag2", "tag3"],
             "address": {"street": f"{i} Main St", "city": "TestCity", "zip": f"{10000+i}"}}
            for i in range(100)
        ],
        "meta": {"total": 100, "page": 1, "per_page": 100},
    }
    for _ in range(ITERATIONS):
        r = Response()
        r.json(payload)


def bench_plaintext():
    """6. Plaintext response."""
    from tina4_python.core.response import Response
    for _ in range(ITERATIONS):
        r = Response()
        r.html("Hello, World!")


def bench_crud():
    """7. Full CRUD cycle."""
    from tina4_python.database import Database
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(f"sqlite:///{tmp}/bench.db")
        db.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, done INTEGER DEFAULT 0)")
        db.commit()
        for _ in range(ITERATIONS // 10):  # 100 full cycles
            # Create
            result = db.insert("tasks", {"title": "Benchmark task", "done": 0})
            task_id = result.last_id
            # Read
            db.fetch_one("SELECT * FROM tasks WHERE id = ?", [task_id])
            # Update
            db.update("tasks", {"done": 1}, "id = ?", [task_id])
            # Delete
            db.delete("tasks", "id = ?", [task_id])
            db.commit()
        db.close()


def bench_paginated():
    """8. Paginated query with count."""
    from tina4_python.database import Database
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(f"sqlite:///{tmp}/bench.db")
        db.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, category TEXT, price REAL)")
        for i in range(500):
            db.execute("INSERT INTO products VALUES (?, ?, ?, ?)",
                       [i, f"Product {i}", f"Cat {i % 10}", i * 2.5])
        db.commit()
        for _ in range(ITERATIONS):
            result = db.fetch("SELECT * FROM products WHERE category = ?", ["Cat 3"], limit=20, offset=0)
            result.to_paginate(page=1, per_page=20)
        db.close()


def bench_startup():
    """9. Framework startup — import + initialize all components.

    Runs the work ONCE in this process. Startup cannot be measured by looping:
    Python caches modules in sys.modules, so from the second iteration onward a
    repeated import is a dict lookup, not a load. The previous version of this
    function looped 100 times and therefore reported ~400us per "startup" while
    the real cost of importing the package was 79ms -- which is exactly why the
    eager-import cost went unnoticed for so long. `--startup` below measures the
    real thing by spawning fresh interpreters.
    """
    # Simulate what happens at app startup
    from tina4_python.core.router import Router
    from tina4_python.core.response import Response
    from tina4_python.core.request import Request
    from tina4_python.core.middleware import CorsMiddleware, RateLimiter
    from tina4_python.core.cache import Cache
    from tina4_python.frond import Frond
    from tina4_python.auth import Auth
    from tina4_python.session import Session
    from tina4_python.swagger import Swagger
    from tina4_python.queue import Queue
    from tina4_python.api import Api
    from tina4_python.seeder import FakeData
    from tina4_python.i18n import I18n
    from tina4_python.graphql import GraphQL
    from tina4_python.wsdl import WSDL
    from tina4_python.websocket import WebSocketServer, WebSocketManager
    from tina4_python.messenger import Messenger
    from tina4_python.scss import compile_string
    from tina4_python.ai import detect_ai, generate_context
    from tina4_python.dev_admin import MessageLog, RequestInspector, BrokenTracker

    # Initialize components (lightweight)
    CorsMiddleware()
    RateLimiter()
    Cache()
    Auth(secret="bench-secret")
    Swagger()
    GraphQL()
    WebSocketManager()


# ── Runner ─────────────────────────────────────────────────────

BENCHMARKS = {
    "json": ("JSON Hello World", bench_json),
    "db_single": ("Single DB Query", bench_db_single),
    "db_multi": ("Multiple DB Queries", bench_db_multi),
    "template": ("Template Rendering", bench_template),
    "json_large": ("Large JSON Payload", bench_json_large),
    "plaintext": ("Plaintext Response", bench_plaintext),
    "crud": ("CRUD Cycle", bench_crud),
    "paginated": ("Paginated Query", bench_paginated),
    "startup": ("Framework Startup", bench_startup),
}


def run_benchmark(name: str):
    """Run a single benchmark and report timing."""
    label, fn = BENCHMARKS[name]
    start = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - start
    if name == "startup":
        print(f"  {label:<25} {elapsed:.3f}s  (1 run, in-process)")
    else:
        print(f"  {label:<25} {elapsed:.3f}s  ({ITERATIONS / elapsed:,.0f} ops/sec)")
    return elapsed


# ── Real startup cost ──────────────────────────────────────────
#
# Import cost is per-PROCESS, so it can only be measured by spawning fresh
# interpreters. This is where deferred loading shows up; per-request throughput
# is unaffected by it.

STARTUP_SNIPPETS = {
    "bare python": "pass",
    "import tina4_python": "import tina4_python",
    "core surface used": (
        "import tina4_python as t; t.get; t.post; t.HTTP_OK; t.run"
    ),
    "+ one lazy feature": "import tina4_python as t; t.Queue",
    # Every name in the _LAZY table -- the worst case, equivalent to the old
    # eager barrel. Read from the table itself so it cannot drift.
    "+ every lazy feature": (
        "import tina4_python as t; "
        "[getattr(t, n) for n in t._LAZY]"
    ),
}


def measure_startup(runs: int = 10) -> None:
    """Time a fresh interpreter per snippet, reporting the best of `runs`.

    Best-of rather than mean: process spawn is noisy and we want the floor cost,
    not the scheduler's mood. (Same reason the Ruby perf spec went best-of-20
    after a single-sample flake.)
    """
    import subprocess

    print(f"\n  Startup cost — fresh interpreter, best of {runs}\n")
    print(f"  {'Scenario':<24} {'Best':>9} {'Modules':>9}")
    print("  " + "-" * 45)

    baseline = None
    for label, snippet in STARTUP_SNIPPETS.items():
        # One untimed warm-up per scenario. Without it the FIRST row pays the
        # cold-file-cache cost for every .pyc it touches and can read higher
        # than a strictly-larger scenario measured after it -- a nonsense
        # ordering that makes the whole table untrustworthy.
        subprocess.run([sys.executable, "-c", snippet], capture_output=True)

        best = None
        for _ in range(runs):
            start = time.perf_counter()
            proc = subprocess.run(
                [sys.executable, "-c", snippet], capture_output=True, text=True
            )
            elapsed = time.perf_counter() - start
            if proc.returncode != 0:
                print(f"  {label:<24}  FAILED: {proc.stderr.strip()[:60]}")
                best = None
                break
            best = elapsed if best is None else min(best, elapsed)
        if best is None:
            continue

        mods = subprocess.run(
            [sys.executable, "-c", snippet + "; import sys; print(len(sys.modules))"],
            capture_output=True, text=True,
        ).stdout.strip() or "?"

        if baseline is None:
            baseline = best
            delta = ""
        else:
            delta = f"  (+{(best - baseline) * 1000:.1f}ms over bare)"
        print(f"  {label:<24} {best * 1000:>7.1f}ms {mods:>9}{delta}")
    print()


def measure_carbon(selected) -> None:
    """Measure each benchmark's SCI with the real Carbonah CLI.

    The module docstring has always claimed these categories were "measured via
    Carbonah", but nothing here ever invoked it -- the numbers were wall-clock
    only. This makes the claim true. Carbonah is an external tool, so its
    absence is reported rather than faked.
    """
    import shutil
    import subprocess

    if not shutil.which("carbonah"):
        print("\n  carbonah not on PATH — skipping SCI measurement.")
        print("  Install it (https://carbonah.dev) and re-run with --carbon.\n")
        return

    region = os.environ.get("CARBONAH_REGION", "ZA")
    print(f"\n  Software Carbon Intensity via Carbonah (region {region})\n")
    print(f"  {'Benchmark':<25} {'gCO2e/run':>11} {'Grade':>7} {'Energy kWh':>13}")
    print("  " + "-" * 60)

    script = str(Path(__file__).resolve())
    for name in selected:
        if name not in BENCHMARKS:
            continue
        label = BENCHMARKS[name][0]
        proc = subprocess.run(
            ["carbonah", "measure", "--format", "json", "--region", region,
             "--", sys.executable, script, "--single", name],
            capture_output=True, text=True,
        )
        # carbonah prints a progress line before the JSON body.
        brace = proc.stdout.find("{")
        if brace < 0:
            print(f"  {label:<25}  no JSON from carbonah: {proc.stderr.strip()[:40]}")
            continue
        try:
            d = json.loads(proc.stdout[brace:])
        except json.JSONDecodeError:
            print(f"  {label:<25}  unparseable carbonah output")
            continue
        measured = "" if d.get("energy_measured") else "  (modelled)"
        print(f"  {label:<25} {d['value']:>11.6f} {d['grade']:>7} "
              f"{d['energy_kwh']:>13.3e}{measured}")
    print("\n  'modelled' means Carbonah had no hardware energy counter on this")
    print("  platform and derived energy from duration x grid intensity. Treat")
    print("  those as comparative, not absolute.\n")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]

    # --single runs ONE benchmark bare, with no reporting: this is the form
    # `carbonah measure` wraps, so the SCI reflects the benchmark and not the
    # printing around it.
    if "--single" in args:
        i = args.index("--single")
        run_only = args[i + 1]
        BENCHMARKS[run_only][1]()
        sys.exit(0)

    want_carbon = "--carbon" in args
    want_startup = "--startup" in args
    selected = [a for a in args if not a.startswith("--")] or list(BENCHMARKS.keys())

    print(f"\nTina4 v3 Carbon Benchmarks — {ITERATIONS} iterations per test\n")
    print(f"  {'Benchmark':<25} {'Time':<10} {'Throughput'}")
    print("  " + "-" * 55)

    total = 0
    for name in selected:
        if name in BENCHMARKS:
            total += run_benchmark(name)
        else:
            print(f"  Unknown benchmark: {name}")

    print(f"\n  Total: {total:.3f}s")

    if want_startup:
        measure_startup()
    if want_carbon:
        measure_carbon(selected)
    if not (want_startup or want_carbon):
        print("\n  --startup  measure real per-process startup (fresh interpreters)")
        print("  --carbon   measure Software Carbon Intensity via the Carbonah CLI")
    print()
