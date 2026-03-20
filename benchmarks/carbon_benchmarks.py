#!/usr/bin/env python3
"""Tina4 v3 Carbon Benchmarks — 9 categories measured via Carbonah.

Run all:     python benchmarks/carbon_benchmarks.py
Run one:     python benchmarks/carbon_benchmarks.py json
Categories:  json, db_single, db_multi, template, json_large,
             plaintext, crud, paginated, startup
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
            result = db.fetch("SELECT * FROM products WHERE category = ?", ["Cat 3"], limit=20, skip=0)
            result.to_paginate(page=1, per_page=20)
        db.close()


def bench_startup():
    """9. Framework startup — import + initialize all components."""
    for _ in range(100):
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
        from tina4_python.seeder import Fake
        from tina4_python.i18n import I18n
        from tina4_python.graphql import GraphQL
        from tina4_python.wsdl import WSDL
        from tina4_python.websocket import WebSocketServer, WebSocketManager
        from tina4_python.messenger import Messenger
        from tina4_python.scss import compile_string
        from tina4_python.ai import detect_ai, generate_context
        from tina4_python.dev_admin import MessageLog, RequestInspector, BrokenTracker, render_dashboard, render_overlay_script

        # Initialize components (lightweight)
        cors = CorsMiddleware()
        limiter = RateLimiter()
        cache = Cache()
        auth = Auth(secret="bench-secret")
        swagger = Swagger()
        gql = GraphQL()
        ws_mgr = WebSocketManager()


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
    ops = ITERATIONS / elapsed if name != "startup" else 100 / elapsed
    print(f"  {label:<25} {elapsed:.3f}s  ({ops:,.0f} ops/sec)")
    return elapsed


if __name__ == "__main__":
    selected = sys.argv[1:] if len(sys.argv) > 1 else list(BENCHMARKS.keys())

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
    print()
