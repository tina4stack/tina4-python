#!/usr/bin/env python3
"""Run Tina4 carbon benchmarks through Carbonah and produce a report."""
import subprocess
import json
import sys
import os

BENCHMARKS = [
    ("json", "JSON Hello World"),
    ("db_single", "Single DB Query"),
    ("db_multi", "Multiple DB Queries"),
    ("template", "Template Rendering"),
    ("json_large", "Large JSON Payload"),
    ("plaintext", "Plaintext Response"),
    ("crud", "CRUD Cycle"),
    ("paginated", "Paginated Query"),
    ("startup", "Framework Startup"),
]

REGION = os.environ.get("CARBONAH_REGION", "ZA")
PYTHON = sys.executable


def measure(cmd: list[str]) -> dict:
    """Run carbonah measure and extract the JSON result."""
    full_cmd = ["carbonah", "--region", REGION, "--format", "json", "measure", "--"] + cmd
    result = subprocess.run(full_cmd, capture_output=True, text=True)
    output = result.stdout + result.stderr

    # Find the JSON object in the output
    brace_depth = 0
    start = -1
    for i, ch in enumerate(output):
        if ch == "{":
            if brace_depth == 0:
                start = i
            brace_depth += 1
        elif ch == "}":
            brace_depth -= 1
            if brace_depth == 0 and start >= 0:
                try:
                    return json.loads(output[start:i + 1])
                except json.JSONDecodeError:
                    continue
    return {}


def main():
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║           TINA4 v3 CARBON BENCHMARK REPORT                     ║")
    print(f"║           Region: {REGION:<4} | 1000 iterations per test               ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()
    print(f"  {'Benchmark':<26} {'SCI (gCO2eq)':<15} {'Grade':<8} {'Energy (kWh)':<20} {'Time'}")
    print("  " + "─" * 78)

    results = []

    for key, label in BENCHMARKS:
        data = measure([PYTHON, "benchmarks/carbon_benchmarks.py", key])
        if data:
            sci = data.get("value", 0)
            grade = data.get("grade", "?").replace("Plus", "+")
            energy = data.get("energy_kwh", 0)
            duration = data.get("duration_s", 0)
            print(f"  {label:<26} {sci:<15.6f} {grade:<8} {energy:<20.9f} {duration:.3f}s")
            results.append({"benchmark": label, "sci": sci, "grade": grade, "energy": energy, "duration": duration})
        else:
            print(f"  {label:<26} {'ERROR':<15}")

    # Full suite
    print("  " + "─" * 78)
    data = measure([PYTHON, "benchmarks/carbon_benchmarks.py"])
    if data:
        sci = data.get("value", 0)
        grade = data.get("grade", "?").replace("Plus", "+")
        energy = data.get("energy_kwh", 0)
        duration = data.get("duration_s", 0)
        print(f"  {'ALL BENCHMARKS':<26} {sci:<15.6f} {grade:<8} {energy:<20.9f} {duration:.3f}s")

    # Test suite
    print()
    data = measure([PYTHON, "-m", "pytest", "tests/", "-q"])
    if data:
        sci = data.get("value", 0)
        grade = data.get("grade", "?").replace("Plus", "+")
        duration = data.get("duration_s", 0)
        tests = 622
        print(f"  {'TEST SUITE (' + str(tests) + ' tests)':<26} {sci:<15.6f} {grade:<8} {'':20} {duration:.3f}s")

    # Carbon per 1M requests estimate
    print()
    print("  ── Carbon per 1,000,000 requests (estimated) ──")
    for r in results:
        carbon_1m = r["sci"] * 1_000_000 / 1000  # SCI is per run of 1000 iterations
        print(f"  {r['benchmark']:<26} {carbon_1m:,.2f} gCO2eq  ({carbon_1m/1000:.2f} kgCO2eq)")

    print()

    # Save report
    report = {"region": REGION, "benchmarks": results}
    report_path = "benchmarks/carbon_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  Report saved: {report_path}")
    print()


if __name__ == "__main__":
    main()
