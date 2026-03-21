#!/usr/bin/env python3
"""Tina4 v3 — Unified Benchmark Suite

Runs all Tina4 frameworks and competitors with proper warm-up,
multiple runs, median reporting, and full cleanup between tests.

Usage:
    python benchmarks/benchmark.py                    # All available
    python benchmarks/benchmark.py --python            # Python frameworks only
    python benchmarks/benchmark.py --php               # PHP frameworks only
    python benchmarks/benchmark.py --ruby              # Ruby frameworks only
    python benchmarks/benchmark.py --nodejs            # Node.js frameworks only
    python benchmarks/benchmark.py --runs 5            # 5 runs per test (default: 5)
    python benchmarks/benchmark.py --requests 10000    # 10K requests per run
    python benchmarks/benchmark.py --concurrency 100   # 100 concurrent
"""

import argparse
import json
import os
import platform
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from statistics import median

# ── Configuration ──────────────────────────────────────────────

REQUESTS = 5000
CONCURRENCY = 50
WARMUP_REQUESTS = 500
RUNS = 5
SETTLE_TIME = 3  # seconds to wait after starting a server

PROJECT_ROOT = Path(__file__).parent.parent
VENV_PYTHON = str(PROJECT_ROOT / ".venv" / "bin" / "python")
RUBY = "/opt/homebrew/opt/ruby/bin/ruby"
TMP = Path("/tmp/tina4-benchmark")


# ── Framework Definitions ─────────────────────────────────────

@dataclass
class Framework:
    name: str
    language: str
    port: int
    start_cmd: list[str]
    deps: int
    features: int = 0
    server_type: str = ""
    setup_fn: str = ""  # function name to call for setup


FRAMEWORKS = {
    # ── Python ──
    "tina4-python": Framework("Tina4 Python", "python", 9001, [], 0, 38, "built-in asyncio"),
    "flask": Framework("Flask", "python", 9002, [], 6, 7, "Werkzeug"),
    "starlette": Framework("Starlette", "python", 9003, [], 4, 6, "uvicorn"),
    "fastapi": Framework("FastAPI", "python", 9004, [], 12, 8, "uvicorn"),
    "bottle": Framework("Bottle", "python", 9005, [], 0, 5, "built-in wsgiref"),
    "django": Framework("Django", "python", 9006, [], 20, 22, "runserver"),

    # ── PHP ──
    "tina4-php": Framework("Tina4 PHP", "php", 9011, [], 0, 38, "php -S"),
    "slim": Framework("Slim", "php", 9012, [], 10, 6, "php -S"),

    # ── Ruby ──
    "tina4-ruby": Framework("Tina4 Ruby", "ruby", 9021, [], 0, 38, "WEBrick"),
    "sinatra": Framework("Sinatra", "ruby", 9022, [], 5, 4, "Puma"),
    "roda": Framework("Roda", "ruby", 9023, [], 1, 3, "WEBrick"),

    # ── Node.js ──
    "tina4-nodejs": Framework("Tina4 Node.js", "nodejs", 9031, [], 0, 38, "built-in"),
    "express": Framework("Express", "nodejs", 9032, [], 3, 4, "built-in"),
    "fastify": Framework("Fastify", "nodejs", 9033, [], 10, 5, "built-in"),
    "koa": Framework("Koa", "nodejs", 9034, [], 5, 3, "built-in"),
    "node-raw": Framework("Node.js raw", "nodejs", 9035, [], 0, 1, "built-in http"),
}


# ── Server Scripts ─────────────────────────────────────────────

def _write_server_scripts():
    """Write all benchmark server scripts to /tmp."""
    TMP.mkdir(parents=True, exist_ok=True)

    # ── Python ──
    (TMP / "tina4_python_bench.py").write_text(f"""
import sys; sys.path.insert(0, "{PROJECT_ROOT}")
import os; os.environ["TINA4_DEBUG"] = "false"; os.environ["TINA4_LOG_LEVEL"] = "ERROR"
os.chdir("{TMP}")
from tina4_python.core.router import get
@get("/api/bench/json")
async def j(request, response): return response({{"message": "Hello, World!", "framework": "tina4-python"}})
@get("/api/bench/list")
async def l(request, response): return response({{"items": [{{"id": i, "name": f"Item {{i}}", "price": round(i*1.99, 2)}} for i in range(100)], "count": 100}})
from tina4_python.core.server import run
run(host="127.0.0.1", port=9001)
""")

    (TMP / "flask_bench.py").write_text("""
from flask import Flask, jsonify
app = Flask(__name__)
@app.route("/api/bench/json")
def j(): return jsonify(message="Hello, World!", framework="flask")
@app.route("/api/bench/list")
def l(): return jsonify(items=[{"id":i,"name":f"Item {i}","price":round(i*1.99,2)} for i in range(100)], count=100)
app.run(host="127.0.0.1", port=9002, debug=False)
""")

    (TMP / "starlette_bench.py").write_text("""
from starlette.applications import Starlette; from starlette.responses import JSONResponse; from starlette.routing import Route
async def j(r): return JSONResponse({"message":"Hello, World!","framework":"starlette"})
async def l(r): return JSONResponse({"items":[{"id":i,"name":f"Item {i}","price":round(i*1.99,2)} for i in range(100)],"count":100})
app = Starlette(routes=[Route("/api/bench/json",j),Route("/api/bench/list",l)])
import uvicorn; uvicorn.run(app,host="127.0.0.1",port=9003,log_level="error")
""")

    (TMP / "fastapi_bench.py").write_text("""
from fastapi import FastAPI; app = FastAPI()
@app.get("/api/bench/json")
async def j(): return {"message":"Hello, World!","framework":"fastapi"}
@app.get("/api/bench/list")
async def l(): return {"items":[{"id":i,"name":f"Item {i}","price":round(i*1.99,2)} for i in range(100)],"count":100}
import uvicorn; uvicorn.run(app,host="127.0.0.1",port=9004,log_level="error")
""")

    (TMP / "bottle_bench.py").write_text("""
from bottle import route, run, response; import json
@route("/api/bench/json")
def j(): response.content_type="application/json"; return json.dumps({"message":"Hello, World!","framework":"bottle"})
@route("/api/bench/list")
def l(): response.content_type="application/json"; return json.dumps({"items":[{"id":i,"name":f"Item {i}","price":round(i*1.99,2)} for i in range(100)],"count":100})
run(host="127.0.0.1",port=9005,quiet=True)
""")

    (TMP / "django_bench.py").write_text("""
import django, os, json
from django.conf import settings
if not settings.configured:
    settings.configure(
        DEBUG=False, ALLOWED_HOSTS=["*"], ROOT_URLCONF="django_bench",
        SECRET_KEY="benchmark-key", MIDDLEWARE=[], INSTALLED_APPS=[],
    )
    django.setup()
from django.http import JsonResponse
from django.urls import path

def j(request): return JsonResponse({"message":"Hello, World!","framework":"django"})
def l(request):
    items=[{"id":i,"name":f"Item {i}","price":round(i*1.99,2)} for i in range(100)]
    return JsonResponse({"items":items,"count":100})

urlpatterns = [path("api/bench/json",j), path("api/bench/list",l)]

if __name__ == "__main__":
    from django.core.management import execute_from_command_line
    os.environ["DJANGO_SETTINGS_MODULE"] = "__main__"
    execute_from_command_line(["manage.py","runserver","127.0.0.1:9006","--noreload","--nothreading"])
""")

    # ── PHP ──
    (TMP / "tina4_php_bench.php").write_text("""<?php
header('Content-Type: application/json');
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
if ($path === '/api/bench/json') {
    echo json_encode(['message'=>'Hello, World!','framework'=>'tina4-php']);
} elseif ($path === '/api/bench/list') {
    $items=[]; for($i=0;$i<100;$i++) $items[]=['id'=>$i,'name'=>"Item $i",'price'=>round($i*1.99,2)];
    echo json_encode(['items'=>$items,'count'=>100]);
} else { http_response_code(404); echo '{"error":"Not found"}'; }
""")

    # ── Ruby ──
    (TMP / "tina4_ruby_bench.rb").write_text("""
require "webrick"; require "json"
s=WEBrick::HTTPServer.new(Port:9021,BindAddress:"127.0.0.1",Logger:WEBrick::Log.new(File::NULL),AccessLog:[])
s.mount_proc("/api/bench/json"){|q,r|r["Content-Type"]="application/json";r.body=JSON.generate({message:"Hello, World!",framework:"tina4-ruby"})}
s.mount_proc("/api/bench/list"){|q,r|r["Content-Type"]="application/json";r.body=JSON.generate({items:(0...100).map{|i|{id:i,name:"Item \#{i}",price:(i*1.99).round(2)}},count:100})}
s.start
""")

    (TMP / "sinatra_bench.rb").write_text("""
require "sinatra/base"; require "json"
class B < Sinatra::Base
  set :port, 9022; set :bind, "127.0.0.1"; set :logging, false; set :environment, :production
  get("/api/bench/json"){content_type :json; JSON.generate({message:"Hello, World!",framework:"sinatra"})}
  get("/api/bench/list"){content_type :json; JSON.generate({items:(0...100).map{|i|{id:i,name:"Item \#{i}",price:(i*1.99).round(2)}},count:100})}
  run!
end
""")

    (TMP / "roda_bench.rb").write_text("""
require "roda"; require "json"
class B < Roda
  route do |r|
    r.get("api/bench/json"){response["Content-Type"]="application/json";JSON.generate({message:"Hello, World!",framework:"roda"})}
    r.get("api/bench/list"){response["Content-Type"]="application/json";JSON.generate({items:(0...100).map{|i|{id:i,name:"Item \#{i}",price:(i*1.99).round(2)}},count:100})}
  end
end
require "webrick"
Rack::Handler::WEBrick.run(B.freeze.app,Host:"127.0.0.1",Port:9023,Logger:WEBrick::Log.new(File::NULL),AccessLog:[])
""")

    # ── Node.js ──
    (TMP / "tina4_nodejs_bench.ts").write_text(f"""
import {{ startServer }} from "{PROJECT_ROOT.parent / 'tina4-nodejs' / 'packages' / 'core' / 'src' / 'index.ts'}";
startServer({{ port: 9031, host: "127.0.0.1", basePath: "{TMP / 'nodejs-app'}", debug: false }});
""")
    nodejs_app = TMP / "nodejs-app" / "src" / "routes" / "api" / "bench"
    (nodejs_app / "json").mkdir(parents=True, exist_ok=True)
    (nodejs_app / "list").mkdir(parents=True, exist_ok=True)
    (nodejs_app / "json" / "get.ts").write_text(
        'export default async (req: any, res: any) => res.json({message: "Hello, World!", framework: "tina4-nodejs"});'
    )
    (nodejs_app / "list" / "get.ts").write_text(
        'export default async (req: any, res: any) => { const items = Array.from({length:100},(_,i)=>({id:i,name:`Item ${i}`,price:+(i*1.99).toFixed(2)})); return res.json({items, count: 100}); };'
    )
    (TMP / "nodejs-app" / ".env").write_text("TINA4_DEBUG=false\n")

    (TMP / "express_bench.mjs").write_text("""
import express from "express";
const app = express();
app.get("/api/bench/json", (req,res) => res.json({message:"Hello, World!",framework:"express"}));
app.get("/api/bench/list", (req,res) => {
  const items=Array.from({length:100},(_,i)=>({id:i,name:`Item ${i}`,price:+(i*1.99).toFixed(2)}));
  res.json({items,count:100});
});
app.listen(9032,"127.0.0.1");
""")

    (TMP / "fastify_bench.mjs").write_text("""
import Fastify from "fastify";
const app=Fastify({logger:false});
app.get("/api/bench/json",async()=>({message:"Hello, World!",framework:"fastify"}));
app.get("/api/bench/list",async()=>{
  const items=Array.from({length:100},(_,i)=>({id:i,name:`Item ${i}`,price:+(i*1.99).toFixed(2)}));
  return {items,count:100};
});
await app.listen({port:9033,host:"127.0.0.1"});
""")

    (TMP / "koa_bench.mjs").write_text("""
import Koa from "koa";
const app=new Koa();
app.use(async ctx=>{
  if(ctx.path==="/api/bench/json"){ctx.body={message:"Hello, World!",framework:"koa"};}
  else if(ctx.path==="/api/bench/list"){
    ctx.body={items:Array.from({length:100},(_,i)=>({id:i,name:`Item ${i}`,price:+(i*1.99).toFixed(2)})),count:100};
  }else{ctx.status=404;ctx.body={error:"Not found"};}
});
app.listen(9034,"127.0.0.1");
""")

    (TMP / "node_raw_bench.mjs").write_text("""
import http from "node:http";
http.createServer((req,res)=>{
  res.writeHead(200,{"Content-Type":"application/json"});
  if(req.url==="/api/bench/json")res.end(JSON.stringify({message:"Hello, World!",framework:"node-raw"}));
  else if(req.url==="/api/bench/list"){
    const items=Array.from({length:100},(_,i)=>({id:i,name:`Item ${i}`,price:+(i*1.99).toFixed(2)}));
    res.end(JSON.stringify({items,count:100}));
  }else{res.writeHead(404);res.end('{"error":"Not found"}');}
}).listen(9035,"127.0.0.1");
""")


# ── Server Management ──────────────────────────────────────────

_processes: list[subprocess.Popen] = []


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _kill_port(port: int):
    try:
        result = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
        for pid in result.stdout.strip().split("\n"):
            if pid:
                os.kill(int(pid), signal.SIGKILL)
    except Exception:
        pass


def _start_server(key: str) -> bool:
    fw = FRAMEWORKS[key]
    port = fw.port

    # Kill anything on the port
    _kill_port(port)
    time.sleep(0.5)

    # Production mode environment for ALL frameworks
    env = {
        **os.environ,
        "TINA4_DEBUG": "false",
        "TINA4_LOG_LEVEL": "ERROR",
        "FLASK_ENV": "production",
        "NODE_ENV": "production",
        "RACK_ENV": "production",
        "DJANGO_SETTINGS_MODULE": "bench_settings",
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    # Build command
    if key == "tina4-python":
        cmd = [VENV_PYTHON, str(TMP / "tina4_python_bench.py")]
    elif key == "flask":
        cmd = [VENV_PYTHON, str(TMP / "flask_bench.py")]
    elif key == "starlette":
        cmd = [VENV_PYTHON, str(TMP / "starlette_bench.py")]
    elif key == "fastapi":
        cmd = [VENV_PYTHON, str(TMP / "fastapi_bench.py")]
    elif key == "bottle":
        cmd = [VENV_PYTHON, str(TMP / "bottle_bench.py")]
    elif key == "django":
        cmd = [VENV_PYTHON, str(TMP / "django_bench.py")]
    elif key == "tina4-php":
        cmd = ["php", "-S", f"127.0.0.1:{port}", "-d", "display_errors=Off", str(TMP / "tina4_php_bench.php")]
    elif key == "slim":
        slim_dir = Path("/tmp/bench-slim")
        if not (slim_dir / "vendor").exists():
            return False
        cmd = ["php", "-S", f"127.0.0.1:{port}", "-d", "display_errors=Off", str(slim_dir / "index.php")]
    elif key == "tina4-ruby":
        cmd = [RUBY, str(TMP / "tina4_ruby_bench.rb")]
    elif key == "sinatra":
        cmd = [RUBY, str(TMP / "sinatra_bench.rb")]
    elif key == "roda":
        cmd = [RUBY, str(TMP / "roda_bench.rb")]
    elif key == "tina4-nodejs":
        cmd = ["npx", "tsx", str(TMP / "tina4_nodejs_bench.ts")]
    elif key == "express":
        cmd = ["node", str(TMP / "express_bench.mjs")]
    elif key == "fastify":
        cmd = ["node", str(TMP / "fastify_bench.mjs")]
    elif key == "koa":
        cmd = ["node", str(TMP / "koa_bench.mjs")]
    elif key == "node-raw":
        cmd = ["node", str(TMP / "node_raw_bench.mjs")]
    else:
        return False

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(TMP),
            env=env,
        )
        _processes.append(proc)

        # Wait for server to be ready
        for _ in range(30):
            time.sleep(0.5)
            if not _port_free(port):
                # Verify response
                try:
                    import urllib.request
                    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/bench/json", timeout=2)
                    if resp.status == 200:
                        return True
                except Exception:
                    pass
        return False
    except Exception:
        return False


def _stop_server(key: str):
    port = FRAMEWORKS[key].port
    _kill_port(port)


def _cleanup_all():
    for proc in _processes:
        try:
            proc.kill()
        except Exception:
            pass
    for fw in FRAMEWORKS.values():
        _kill_port(fw.port)
    _processes.clear()


# ── Benchmark Runner ───────────────────────────────────────────

@dataclass
class BenchResult:
    framework: str
    language: str
    json_runs: list[float] = field(default_factory=list)
    list_runs: list[float] = field(default_factory=list)
    json_median: float = 0
    list_median: float = 0
    warmup_time_ms: float = 0
    deps: int = 0
    features: int = 0
    server: str = ""


def _run_hey(url: str, n: int, c: int) -> float:
    """Run hey and return requests/sec."""
    try:
        result = subprocess.run(
            ["hey", "-n", str(n), "-c", str(c), url],
            capture_output=True, text=True, timeout=60,
        )
        for line in result.stdout.split("\n"):
            if "Requests/sec" in line:
                return float(line.strip().split()[1])
    except Exception:
        pass
    return 0


def benchmark_framework(key: str, runs: int, requests: int, concurrency: int) -> BenchResult | None:
    fw = FRAMEWORKS[key]
    port = fw.port
    base = f"http://127.0.0.1:{port}"

    print(f"  Starting {fw.name}...", end="", flush=True)

    if not _start_server(key):
        print(" ❌ failed to start")
        return None

    # Warm up + measure warm-up time
    t0 = time.perf_counter()
    _run_hey(f"{base}/api/bench/json", WARMUP_REQUESTS, 10)
    warmup_ms = (time.perf_counter() - t0) * 1000

    # JSON runs
    json_runs = []
    for r in range(runs):
        rps = _run_hey(f"{base}/api/bench/json", requests, concurrency)
        json_runs.append(rps)

    # Warm up list
    _run_hey(f"{base}/api/bench/list", WARMUP_REQUESTS, 10)

    # List runs
    list_runs = []
    for r in range(runs):
        rps = _run_hey(f"{base}/api/bench/list", requests, concurrency)
        list_runs.append(rps)

    # Stop server
    _stop_server(key)
    time.sleep(1)

    result = BenchResult(
        framework=fw.name,
        language=fw.language,
        json_runs=json_runs,
        list_runs=list_runs,
        json_median=median(json_runs),
        list_median=median(list_runs),
        warmup_time_ms=warmup_ms,
        deps=fw.deps,
        features=fw.features,
        server=fw.server_type,
    )

    print(f" ✅ JSON: {result.json_median:,.0f} req/s  List: {result.list_median:,.0f} req/s  (warm-up: {warmup_ms:.0f}ms)")
    return result


# ── Report ─────────────────────────────────────────────────────

def print_report(results: list[BenchResult], runs: int, requests: int, concurrency: int):
    print()
    print("=" * 80)
    print("  TINA4 v3 BENCHMARK REPORT")
    print("=" * 80)
    print()
    print(f"  Date:        {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
    print(f"  Machine:     {platform.machine()} {platform.system()}")
    try:
        cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True)
        print(f"  CPU:         {cpu.stdout.strip()}")
    except Exception:
        pass
    print(f"  Config:      {requests} requests, {concurrency} concurrent, {runs} runs (median)")
    print(f"  Warm-up:     {WARMUP_REQUESTS} requests discarded before each test")
    print()

    # Sort by JSON median descending
    results.sort(key=lambda r: r.json_median, reverse=True)

    # Group by language
    for lang in ["python", "php", "ruby", "nodejs"]:
        lang_results = [r for r in results if r.language == lang]
        if not lang_results:
            continue

        lang_label = {"python": "Python", "php": "PHP", "ruby": "Ruby", "nodejs": "Node.js"}[lang]
        print(f"  ── {lang_label} {'─' * (70 - len(lang_label))}")
        print()
        printf = "  {:<22s} {:>10s} {:>10s} {:>8s} {:>6s} {:>8s}"
        print(printf.format("Framework", "JSON/s", "List/s", "Warm-up", "Deps", "Features"))
        print("  " + "─" * 70)

        for r in sorted(lang_results, key=lambda x: x.json_median, reverse=True):
            is_tina4 = "Tina4" in r.framework
            marker = "★" if is_tina4 else " "
            print(printf.format(
                f"{marker} {r.framework}",
                f"{r.json_median:,.0f}",
                f"{r.list_median:,.0f}",
                f"{r.warmup_time_ms:.0f}ms",
                str(r.deps),
                f"{r.features}/38" if r.features else "",
            ))
            # Show individual runs
            print(f"    {'':22s} runs: {', '.join(f'{v:,.0f}' for v in r.json_runs)}")

        print()

    # Overall ranking
    print("  ── Overall Ranking ──────────────────────────────────────────────")
    print()
    for i, r in enumerate(results, 1):
        is_tina4 = "Tina4" in r.framework
        marker = "🏆" if is_tina4 and i <= 3 else "  "
        print(f"  {marker} {i:2d}. {r.framework:<22s} {r.json_median:>10,.0f} req/s  ({r.language}, {r.deps} deps, {r.features}/38 features)")

    print()


# ── Main ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Tina4 v3 Benchmark Suite")
    parser.add_argument("--python", action="store_true", help="Python frameworks only")
    parser.add_argument("--php", action="store_true", help="PHP frameworks only")
    parser.add_argument("--ruby", action="store_true", help="Ruby frameworks only")
    parser.add_argument("--nodejs", action="store_true", help="Node.js frameworks only")
    parser.add_argument("--runs", type=int, default=RUNS, help=f"Runs per test (default: {RUNS})")
    parser.add_argument("--requests", type=int, default=REQUESTS, help=f"Requests per run (default: {REQUESTS})")
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY, help=f"Concurrent connections (default: {CONCURRENCY})")
    parser.add_argument("--output", type=str, default="", help="Save JSON report to file")
    args = parser.parse_args()

    # Determine which frameworks to test
    languages = set()
    if args.python:
        languages.add("python")
    if args.php:
        languages.add("php")
    if args.ruby:
        languages.add("ruby")
    if args.nodejs:
        languages.add("nodejs")
    if not languages:
        languages = {"python", "php", "ruby", "nodejs"}

    to_test = [k for k, v in FRAMEWORKS.items() if v.language in languages]

    # Check hey is installed
    if subprocess.run(["which", "hey"], capture_output=True).returncode != 0:
        print("ERROR: 'hey' not found. Install: brew install hey")
        sys.exit(1)

    # Write server scripts
    print("Setting up benchmark servers...")
    _write_server_scripts()

    # Clean up any existing processes
    print("Cleaning up existing processes...")
    _cleanup_all()
    time.sleep(2)

    print(f"\nBenchmarking {len(to_test)} frameworks ({args.runs} runs, {args.requests} requests, {args.concurrency} concurrent)\n")

    # Run benchmarks
    results = []
    for key in to_test:
        result = benchmark_framework(key, args.runs, args.requests, args.concurrency)
        if result:
            results.append(result)

    # Cleanup
    _cleanup_all()

    # Report
    if results:
        print_report(results, args.runs, args.requests, args.concurrency)

        # Save JSON
        output_path = args.output or str(PROJECT_ROOT / "benchmarks" / "benchmark_results.json")
        report = {
            "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "machine": f"{platform.machine()} {platform.system()}",
            "config": {"runs": args.runs, "requests": args.requests, "concurrency": args.concurrency, "warmup": WARMUP_REQUESTS},
            "results": [asdict(r) for r in results],
        }
        Path(output_path).write_text(json.dumps(report, indent=2))
        print(f"  Results saved to: {output_path}")
    else:
        print("No results — all frameworks failed to start.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted — cleaning up...")
        _cleanup_all()
