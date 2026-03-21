#!/usr/bin/env python3
"""Benchmark: Frond template pre-compilation (token caching).

Compares cold render (first render, no cache) vs warm render (cached tokens).

Usage:
    .venv/bin/python benchmarks/bench_frond_cache.py
"""

import os
import sys
import time
import tempfile

# Ensure tina4_python is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tina4_python.frond.engine import Frond


def make_template(complexity: str = "simple") -> str:
    """Generate a template string of given complexity."""
    if complexity == "simple":
        return "<h1>{{ title }}</h1><p>{{ body }}</p>"
    elif complexity == "medium":
        return """
<html>
<head><title>{{ title }}</title></head>
<body>
  <h1>{{ heading }}</h1>
  {% for item in items %}
    <div class="item">
      <span>{{ item.name }}</span>
      <span>{{ item.price | default('N/A') }}</span>
      {% if item.active %}
        <span class="badge">Active</span>
      {% endif %}
    </div>
  {% endfor %}
  {% if show_footer %}
    <footer>{{ footer_text }}</footer>
  {% endif %}
</body>
</html>
"""
    elif complexity == "complex":
        rows = []
        for i in range(20):
            rows.append(f"""
    <tr>
      <td>{{{{ items[{i}].id }}}}</td>
      <td>{{{{ items[{i}].name | upper }}}}</td>
      <td>{{{{ items[{i}].value | default(0) }}}}</td>
      {{% if items[{i}].active %}}
        <td class="active">Yes</td>
      {{% else %}}
        <td class="inactive">No</td>
      {{% endif %}}
    </tr>""")
        return f"""
<html>
<head><title>{{{{ title }}}}</title></head>
<body>
  <h1>{{{{ heading }}}}</h1>
  <table>
    <thead><tr><th>ID</th><th>Name</th><th>Value</th><th>Status</th></tr></thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
  {{% if pagination %}}
    <nav>
      {{% for page in pages %}}
        <a href="?p={{{{ page }}}}"{{% if page == current_page %}} class="active"{{% endif %}}>{{{{ page }}}}</a>
      {{% endfor %}}
    </nav>
  {{% endif %}}
</body>
</html>
"""


def make_data(complexity: str = "simple") -> dict:
    """Generate template data matching the template complexity."""
    if complexity == "simple":
        return {"title": "Hello", "body": "World"}
    elif complexity == "medium":
        return {
            "title": "Products",
            "heading": "Product List",
            "items": [
                {"name": f"Product {i}", "price": f"${i * 10:.2f}", "active": i % 2 == 0}
                for i in range(10)
            ],
            "show_footer": True,
            "footer_text": "Copyright 2026",
        }
    elif complexity == "complex":
        return {
            "title": "Dashboard",
            "heading": "Data Table",
            "items": [
                {"id": i, "name": f"Item {i}", "value": i * 100, "active": i % 3 != 0}
                for i in range(20)
            ],
            "pagination": True,
            "pages": list(range(1, 11)),
            "current_page": 3,
        }


def bench_render_string(iterations: int, complexity: str) -> dict:
    """Benchmark render_string cold vs warm."""
    template_src = make_template(complexity)
    data = make_data(complexity)

    # Cold render (new engine each time — no cache)
    cold_times = []
    for _ in range(iterations):
        engine = Frond(template_dir="/tmp")
        start = time.perf_counter()
        engine.render_string(template_src, data)
        cold_times.append(time.perf_counter() - start)

    # Warm render (same engine — cached tokens)
    engine = Frond(template_dir="/tmp")
    engine.render_string(template_src, data)  # prime the cache

    warm_times = []
    for _ in range(iterations):
        start = time.perf_counter()
        engine.render_string(template_src, data)
        warm_times.append(time.perf_counter() - start)

    cold_avg = sum(cold_times) / len(cold_times)
    warm_avg = sum(warm_times) / len(warm_times)
    speedup = cold_avg / warm_avg if warm_avg > 0 else float("inf")

    return {
        "complexity": complexity,
        "iterations": iterations,
        "cold_avg_ms": round(cold_avg * 1000, 4),
        "warm_avg_ms": round(warm_avg * 1000, 4),
        "speedup": round(speedup, 2),
        "cold_ops_sec": round(1 / cold_avg) if cold_avg > 0 else 0,
        "warm_ops_sec": round(1 / warm_avg) if warm_avg > 0 else 0,
    }


def bench_render_file(iterations: int, complexity: str) -> dict:
    """Benchmark file-based render cold vs warm."""
    template_src = make_template(complexity)
    data = make_data(complexity)

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path = os.path.join(tmpdir, "test.html")
        with open(template_path, "w") as f:
            f.write(template_src)

        # Cold render (new engine each time)
        cold_times = []
        for _ in range(iterations):
            engine = Frond(template_dir=tmpdir)
            start = time.perf_counter()
            engine.render("test.html", data)
            cold_times.append(time.perf_counter() - start)

        # Warm render (same engine — cached tokens)
        engine = Frond(template_dir=tmpdir)
        engine.render("test.html", data)  # prime cache

        warm_times = []
        for _ in range(iterations):
            start = time.perf_counter()
            engine.render("test.html", data)
            warm_times.append(time.perf_counter() - start)

    cold_avg = sum(cold_times) / len(cold_times)
    warm_avg = sum(warm_times) / len(warm_times)
    speedup = cold_avg / warm_avg if warm_avg > 0 else float("inf")

    return {
        "complexity": complexity,
        "iterations": iterations,
        "cold_avg_ms": round(cold_avg * 1000, 4),
        "warm_avg_ms": round(warm_avg * 1000, 4),
        "speedup": round(speedup, 2),
        "cold_ops_sec": round(1 / cold_avg) if cold_avg > 0 else 0,
        "warm_ops_sec": round(1 / warm_avg) if warm_avg > 0 else 0,
    }


def main():
    iterations = 1000
    print("=" * 70)
    print("Frond Template Pre-Compilation Benchmark")
    print("=" * 70)
    print(f"Iterations per test: {iterations}\n")

    for complexity in ("simple", "medium", "complex"):
        print(f"--- {complexity.upper()} template ---")

        result_str = bench_render_string(iterations, complexity)
        print(f"  render_string:")
        print(f"    Cold:  {result_str['cold_avg_ms']:.4f} ms/op  ({result_str['cold_ops_sec']:,} ops/sec)")
        print(f"    Warm:  {result_str['warm_avg_ms']:.4f} ms/op  ({result_str['warm_ops_sec']:,} ops/sec)")
        print(f"    Speedup: {result_str['speedup']}x")

        result_file = bench_render_file(iterations, complexity)
        print(f"  render (file):")
        print(f"    Cold:  {result_file['cold_avg_ms']:.4f} ms/op  ({result_file['cold_ops_sec']:,} ops/sec)")
        print(f"    Warm:  {result_file['warm_avg_ms']:.4f} ms/op  ({result_file['warm_ops_sec']:,} ops/sec)")
        print(f"    Speedup: {result_file['speedup']}x")
        print()

    print("=" * 70)
    print("Expected: 2-5x improvement on warm renders (skips tokenization)")
    print("=" * 70)


if __name__ == "__main__":
    main()
