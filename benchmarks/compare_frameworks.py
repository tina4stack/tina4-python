#!/usr/bin/env python3
"""Cross-framework benchmark comparison: Tina4 vs Flask vs Django vs Starlette.

Measures identical operations across all four frameworks and prints a
formatted comparison table.  Results are also saved to comparison_report.json.

Run:  python benchmarks/compare_frameworks.py
"""
import subprocess
import sys
import os
import time
import json
import importlib
from pathlib import Path

# ---------------------------------------------------------------------------
# 0. Ensure project root is on sys.path
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ITERATIONS = 1_000
REPORT_PATH = Path(__file__).resolve().parent / "comparison_report.json"


# ---------------------------------------------------------------------------
# 1. Install missing third-party frameworks
# ---------------------------------------------------------------------------
def _ensure_installed():
    """Install Flask, Starlette and Django if they are not already available."""
    needed = []
    for pkg, import_name in [("flask", "flask"), ("starlette[standard]", "starlette"), ("django", "django")]:
        try:
            importlib.import_module(import_name)
        except ImportError:
            needed.append(pkg)
    if needed:
        print(f"  Installing missing packages: {', '.join(needed)} ...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", *needed],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("  Done.\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _timeit(fn, iterations=ITERATIONS):
    """Run *fn* for *iterations* and return (total_seconds, ops_per_sec)."""
    start = time.perf_counter()
    fn(iterations)
    elapsed = time.perf_counter() - start
    ops = iterations / elapsed if elapsed > 0 else float("inf")
    return round(elapsed, 4), round(ops, 1)


# ===================================================================
# A) JSON serialization
# ===================================================================
DATA_HELLO = {"message": "Hello, World!"}


def _json_tina4(n):
    from tina4_python.core.response import Response
    for _ in range(n):
        Response().json(DATA_HELLO)


def _json_flask(n):
    from flask import Flask, jsonify
    app = Flask(__name__)
    with app.app_context():
        for _ in range(n):
            jsonify(DATA_HELLO)


def _json_starlette(n):
    from starlette.responses import JSONResponse
    for _ in range(n):
        JSONResponse(DATA_HELLO)


def _json_django(n):
    from django.http import JsonResponse
    for _ in range(n):
        JsonResponse(DATA_HELLO)


# ===================================================================
# B) Template rendering (20 items)
# ===================================================================
TPL_JINJA = """\
<!DOCTYPE html>
<html><head><title>{{ title }}</title></head>
<body><h1>{{ heading }}</h1>
<ul>
{% for item in items %}
<li>{{ loop.index }}. {{ item.name }} - ${{ item.price }}</li>
{% endfor %}
</ul></body></html>"""

TPL_DJANGO = """\
<!DOCTYPE html>
<html><head><title>{{ title }}</title></head>
<body><h1>{{ heading }}</h1>
<ul>
{% for item in items %}
<li>{{ forloop.counter }}. {{ item.name }} - ${{ item.price }}</li>
{% endfor %}
</ul></body></html>"""

TPL_DATA = {
    "title": "Benchmark",
    "heading": "Products",
    "items": [{"name": f"Product {i}", "price": f"{i * 9.99:.2f}"} for i in range(20)],
}


def _template_tina4(n):
    import tempfile
    from tina4_python.frond import Frond
    with tempfile.TemporaryDirectory() as tmp:
        engine = Frond(template_dir=tmp)
        for _ in range(n):
            engine.render_string(TPL_JINJA, TPL_DATA)


def _template_flask(n):
    from flask import Flask
    from jinja2 import Template
    app = Flask(__name__)
    tpl = Template(TPL_JINJA)
    with app.app_context():
        for _ in range(n):
            tpl.render(**TPL_DATA)


def _template_starlette(n):
    from jinja2 import Template
    tpl = Template(TPL_JINJA)
    for _ in range(n):
        tpl.render(**TPL_DATA)


def _template_django(n):
    from django.template import Template, Context
    tpl = Template(TPL_DJANGO)
    ctx = Context(TPL_DATA)
    for _ in range(n):
        tpl.render(ctx)


# ===================================================================
# C) URL routing — register 100 routes, then match
# ===================================================================
def _dummy_handler():
    pass


def _routing_tina4(n):
    from tina4_python.core import router as router_mod
    for _ in range(n):
        # Save and reset global route list
        saved = router_mod._routes[:]
        router_mod._routes.clear()
        for i in range(100):
            router_mod.Router.add("GET", f"/api/resource{i}/{{id}}", _dummy_handler)
        router_mod.Router.match("GET", "/api/resource50/123")
        router_mod._routes[:] = saved


def _routing_flask(n):
    from flask import Flask
    for _ in range(n):
        app = Flask(__name__)
        for i in range(100):
            app.add_url_rule(f"/api/resource{i}/<int:id>", f"r{i}", _dummy_handler)
        with app.test_request_context("/api/resource50/123"):
            adapter = app.url_map.bind("")
            adapter.match("/api/resource50/123")


def _routing_starlette(n):
    from starlette.routing import Route, Router
    from starlette.testclient import TestClient

    async def _handler(request):
        from starlette.responses import PlainTextResponse
        return PlainTextResponse("ok")

    for _ in range(n):
        routes = [Route(f"/api/resource{i}/{{id:int}}", _handler) for i in range(100)]
        router = Router(routes=routes)
        # Scope-based match
        scope = {"type": "http", "method": "GET", "path": "/api/resource50/123", "query_string": b"", "headers": []}
        for route in router.routes:
            match, child_scope = route.matches(scope)
            if match:
                break


def _routing_django(n):
    from django.urls import path, resolve
    from django.urls.resolvers import URLResolver, URLPattern

    def _view(request, id):
        pass

    for _ in range(n):
        patterns = [path(f"api/resource{i}/<int:id>/", _view, name=f"r{i}") for i in range(100)]
        resolver = URLResolver("", patterns)
        resolver.resolve("/api/resource50/123/")


# ===================================================================
# D) Plaintext response
# ===================================================================
def _plaintext_tina4(n):
    from tina4_python.core.response import Response
    for _ in range(n):
        Response().html("Hello, World!")


def _plaintext_flask(n):
    from flask import Flask, make_response
    app = Flask(__name__)
    with app.app_context():
        for _ in range(n):
            make_response("Hello, World!")


def _plaintext_starlette(n):
    from starlette.responses import PlainTextResponse
    for _ in range(n):
        PlainTextResponse("Hello, World!")


def _plaintext_django(n):
    from django.http import HttpResponse
    for _ in range(n):
        HttpResponse("Hello, World!")


# ===================================================================
# Runner
# ===================================================================
BENCHMARKS = [
    ("JSON serialization", _json_tina4, _json_flask, _json_starlette, _json_django),
    ("Template rendering", _template_tina4, _template_flask, _template_starlette, _template_django),
    ("URL routing (100 routes)", _routing_tina4, _routing_flask, _routing_starlette, _routing_django),
    ("Plaintext response", _plaintext_tina4, _plaintext_flask, _plaintext_starlette, _plaintext_django),
]

FRAMEWORKS = ["Tina4", "Flask", "Starlette", "Django"]


def main():
    _ensure_installed()

    # Django requires minimal settings before any django.* import
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "__django_bench_settings")

    # Create a tiny settings module on the fly
    import types
    settings_mod = types.ModuleType("__django_bench_settings")
    settings_mod.DEBUG = False
    settings_mod.SECRET_KEY = "benchmark-only"
    settings_mod.INSTALLED_APPS = []
    settings_mod.ROOT_URLCONF = "__django_bench_settings"
    settings_mod.urlpatterns = []
    settings_mod.TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [], "APP_DIRS": False, "OPTIONS": {}}]
    sys.modules["__django_bench_settings"] = settings_mod

    import django
    django.setup()

    print(f"\n{'='*80}")
    print(f"  Framework Benchmark Comparison  --  {ITERATIONS} iterations per test")
    print(f"{'='*80}\n")

    # Header
    hdr = f"  {'Benchmark':<28}"
    for fw in FRAMEWORKS:
        hdr += f"{'|':>2} {fw:>14}"
    print(hdr)
    print("  " + "-" * 76)

    report = {"iterations": ITERATIONS, "results": []}

    for label, *fns in BENCHMARKS:
        row = f"  {label:<28}"
        entry = {"benchmark": label, "frameworks": {}}

        for fw, fn in zip(FRAMEWORKS, fns):
            try:
                elapsed, ops = _timeit(fn)
                row += f"| {ops:>11,.0f} op/s"
                entry["frameworks"][fw] = {"time_s": elapsed, "ops_per_sec": ops}
            except Exception as exc:
                row += f"|      ERROR    "
                entry["frameworks"][fw] = {"error": str(exc)}

        print(row)
        report["results"].append(entry)

    # Summary: fastest per benchmark
    print(f"\n  {'='*76}")
    print("  Winner per benchmark:\n")
    for entry in report["results"]:
        best_fw = None
        best_ops = -1
        for fw, data in entry["frameworks"].items():
            if "ops_per_sec" in data and data["ops_per_sec"] > best_ops:
                best_ops = data["ops_per_sec"]
                best_fw = fw
        if best_fw:
            print(f"    {entry['benchmark']:<30} {best_fw} ({best_ops:,.0f} ops/sec)")

    # Save report
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  Report saved to {REPORT_PATH}\n")


if __name__ == "__main__":
    main()
