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
import shutil
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Nominal count, still used by --single (carbonah needs a fixed amount of work,
# not a fixed duration).
ITERATIONS = 1000

# Timed runs continue until this much wall-clock has elapsed...
MIN_SECONDS = 0.25

# ...but never fewer than this many iterations, however fast the operation.
MIN_ITERATIONS = 200


def bench_json():
    """1. JSON serialization — raw overhead."""
    from tina4_python.core.response import Response
    payload = {"message": "Hello, World!", "status": "ok"}
    return lambda: Response().json(payload), None


def bench_db_single():
    """2. Single database query."""
    from tina4_python.database import Database
    tmp = tempfile.mkdtemp()
    db = Database(f"sqlite:///{tmp}/bench.db")
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
    db.execute("INSERT INTO users VALUES (1, 'Alice', 'alice@test.com')")
    db.commit()

    def teardown():
        db.close()
        shutil.rmtree(tmp, ignore_errors=True)

    return lambda: db.fetch_one("SELECT * FROM users WHERE id = ?", [1]), teardown


def bench_db_multi():
    """3. Multiple database queries."""
    from tina4_python.database import Database
    tmp = tempfile.mkdtemp()
    db = Database(f"sqlite:///{tmp}/bench.db")
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, price REAL)")
    for i in range(100):
        db.execute("INSERT INTO items VALUES (?, ?, ?)", [i, f"Item {i}", i * 1.5])
    db.commit()

    def op():
        db.fetch("SELECT * FROM items WHERE price > ?", [50.0], limit=20)
        db.fetch_one("SELECT COUNT(*) as cnt FROM items")
        db.fetch("SELECT * FROM items ORDER BY price DESC", limit=5)

    def teardown():
        db.close()
        shutil.rmtree(tmp, ignore_errors=True)

    return op, teardown


def bench_template():
    """4. Template rendering."""
    import os
    from tina4_python.frond import Frond
    tmp = tempfile.mkdtemp()
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
    # render() from a FILE rather than render_string(): it is the per-request call a
    # real app makes, and the honest counterpart to Jinja2's tpl.render().
    #
    # Corrects an earlier comment here that justified this as "render_string
    # recompiles every call (Frond has no compiled-template cache)". Frond DOES
    # cache compiled tokens on both paths -- by md5 for strings, by name+TTL for
    # files -- and measured on this template tokenizing is only 1.9% of a full
    # render (348.1us forced-tokenize vs 341.5us cached). So the reason to pick
    # render(file) is fidelity to real usage, not compile overhead.
    with open(os.path.join(tmp, "bench.twig"), "w") as fh:
        fh.write(tpl)

    def teardown():
        shutil.rmtree(tmp, ignore_errors=True)

    return lambda: engine.render("bench.twig", data), teardown


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
    return lambda: Response().json(payload), None


def bench_plaintext():
    """6. Plaintext response."""
    from tina4_python.core.response import Response
    return lambda: Response().html("Hello, World!"), None


def bench_crud():
    """7. Full CRUD cycle."""
    from tina4_python.database import Database
    tmp = tempfile.mkdtemp()
    db = Database(f"sqlite:///{tmp}/bench.db")
    db.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, done INTEGER DEFAULT 0)")
    db.commit()

    def op():
        """ONE full create/read/update/delete cycle.

        This used to run ITERATIONS // 10 == 100 cycles inside a single timed
        call while the reported rate divided by ITERATIONS == 1000, so the
        number was 10x too high and made CRUD look like one of the cheapest
        categories when it is the most expensive.
        """
        result = db.insert("tasks", {"title": "Benchmark task", "done": 0})
        task_id = result.last_id
        db.fetch_one("SELECT * FROM tasks WHERE id = ?", [task_id])
        db.update("tasks", {"done": 1}, "id = ?", [task_id])
        db.delete("tasks", "id = ?", [task_id])
        db.commit()

    def teardown():
        db.close()
        shutil.rmtree(tmp, ignore_errors=True)

    return op, teardown


def bench_paginated():
    """8. Paginated query with count."""
    from tina4_python.database import Database
    tmp = tempfile.mkdtemp()
    db = Database(f"sqlite:///{tmp}/bench.db")
    db.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, category TEXT, price REAL)")
    for i in range(500):
        db.execute("INSERT INTO products VALUES (?, ?, ?, ?)",
                   [i, f"Product {i}", f"Cat {i % 10}", i * 2.5])
    db.commit()

    def op():
        result = db.fetch("SELECT * FROM products WHERE category = ?", ["Cat 3"], limit=20, offset=0)
        result.to_paginate(page=1, per_page=20)

    def teardown():
        db.close()
        shutil.rmtree(tmp, ignore_errors=True)

    return op, teardown


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
    def op():
        # Simulate what happens at app startup: import the package surface an app
        # touches, then construct the components. The imports MUST stay inside the
        # timed region -- they are the thing being measured. Caveat: in a full-suite
        # run the earlier benchmarks have already populated sys.modules, so this
        # reports near-zero. The honest number comes from `--startup`, which spawns
        # fresh interpreters.
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

    return op, None


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
    """Run one benchmark: setup and teardown OUTSIDE the clock.

    This used to time the whole bench function, so each benchmark's own setup sat
    inside the measurement. Measured in the PHP twin, the equivalent db_single
    setup (temp dir + sqlite file + CREATE TABLE + INSERT + commit) cost 11.20ms
    against 4.26ms of actual reads -- 72% of the reported number was setup,
    understating read throughput 87x. Same class of bug as compare_frameworks.py
    timing its own imports.

    Duration-based rather than a fixed count: these categories span five orders of
    magnitude, so 1,000 iterations is a few ms of noise for plaintext and seconds
    for templates. n is printed so a suspiciously small sample is visible.
    """
    label, fn = BENCHMARKS[name]
    op, teardown = fn()

    # Startup is one-shot: looping it would time sys.modules dict lookups, which
    # is precisely the bug this suite already had.
    if name == "startup":
        start = time.perf_counter()
        op()
        elapsed = time.perf_counter() - start
        if teardown:
            teardown()
        print(f"  {label:<25} {'-':>13} {'-':>13}   1 run, in-process ({elapsed:.3f}s)")
        return elapsed

    # Warm-up doubles as batch-size calibration. It must be a LOOP, not one call:
    # the first op runs cold (imports resolved, caches empty, JIT-less first pass)
    # and reading a single cold op put every batch size at 2, which defeats the
    # amortisation below.
    # TWO passes, keep the second: one pass still pays the cold costs (first-call
    # imports, lazily-built caches). Measured in the PHP twin a single 64-op pass
    # read JSON at ~50us/op against a real ~375ns, inflating the estimate 130x and
    # collapsing the batch back to 1 -- the very thing the batching exists to avoid.
    CALIBRATION_OPS = 64
    for _ in range(2):
        t0 = time.perf_counter()
        for _ in range(CALIBRATION_OPS):
            op()
        one = max((time.perf_counter() - t0) / CALIBRATION_OPS, 1e-9)

    # Sample in BATCHES sized so a batch costs >= ~50us. Two reasons:
    #  1. A mean alone hides a fat tail. Measured here, the CRUD cycle has a
    #     ~108us median but ONE op per run costs ~711ms (a SQLite flush), which
    #     drags mean throughput from ~9,300 to ~1,350 ops/sec -- a mean-only line
    #     understates CRUD 7x. p50 next to the mean makes that gap visible.
    #  2. Timing every single op would distort the very benchmarks that are
    #     fastest: plaintext runs at ~170ns/op, where two perf_counter() reads are
    #     the same order as the work. Batching amortises the clock reads to <0.2%,
    #     so the mean stays honest while p50 still catches a spike (a 711ms stall
    #     inside one batch still dwarfs the median batch).
    batch = min(max(int(5e-5 / one), 1), 10_000)

    batches = []
    iterations = 0
    start = time.perf_counter()
    while True:
        b0 = time.perf_counter()
        for _ in range(batch):
            op()
        batches.append((time.perf_counter() - b0) / batch)
        iterations += batch
        if iterations >= MIN_ITERATIONS and (time.perf_counter() - start) >= MIN_SECONDS:
            break
    elapsed = time.perf_counter() - start

    if teardown:
        teardown()

    # p50 is the HEADLINE, mean is secondary. Across repeat runs on the same host
    # the mean for JSON Hello World swung 215k -> 630k ops/sec (3x) while p50 held
    # at 774k-792k: the mean absorbs scheduler/GC/flush stalls, p50 does not. A
    # figure that moves 3x run-to-run cannot support a "faster than X" claim, so
    # the stable statistic leads and the gap to the mean shows the tail.
    p50 = sorted(batches)[len(batches) // 2]
    print(
        f"  {label:<25} {1 / p50:>13,.0f} {iterations / elapsed:>13,.0f}   "
        f"{iterations:,}x{batch}"
    )
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
        # Benchmarks return (op, teardown); carbonah needs a FIXED amount of work
        # rather than a fixed duration, so run the op ITERATIONS times.
        op, teardown = BENCHMARKS[run_only][1]()
        if run_only == "startup":
            op()
        else:
            for _ in range(ITERATIONS):
                op()
        if teardown:
            teardown()
        sys.exit(0)

    want_carbon = "--carbon" in args
    want_startup = "--startup" in args
    selected = [a for a in args if not a.startswith("--")] or list(BENCHMARKS.keys())

    print(
        f"\nTina4 v3 Carbon Benchmarks — >={MIN_SECONDS}s / >={MIN_ITERATIONS} iterations per test\n"
    )
    print(f"  {'Benchmark':<25} {'p50 ops/sec':>13} {'mean ops/sec':>13}   {'samples'}")
    print("  " + "-" * 72)

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
