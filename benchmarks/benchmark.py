#!/usr/bin/env python3
"""Tina4 v3 — Unified Benchmark Suite

Runs all Tina4 frameworks and competitors with proper warm-up,
multiple runs, median reporting, and full cleanup between tests.

Usage:
    python benchmarks/benchmark.py --all                  # All available
    python benchmarks/benchmark.py --python               # Python frameworks only
    python benchmarks/benchmark.py --php                  # PHP frameworks only
    python benchmarks/benchmark.py --ruby                 # Ruby frameworks only
    python benchmarks/benchmark.py --nodejs               # Node.js frameworks only
    python benchmarks/benchmark.py --runs 5               # 5 runs per test (default: 5)
    python benchmarks/benchmark.py --requests 10000       # 10K requests per run
    python benchmarks/benchmark.py --concurrency 100      # 100 concurrent
    python benchmarks/benchmark.py --fresh                # Force recreate cached projects
    python benchmarks/benchmark.py --db                   # Database benchmarks only
"""

import argparse
import json
import os
import platform
import shutil
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
RESULTS_DIR = PROJECT_ROOT / "benchmarks" / "results"


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
    "laravel": Framework("Laravel", "php", 9013, [], 50, 25, "artisan serve"),
    "symfony": Framework("Symfony", "php", 9014, [], 30, 20, "php -S"),

    # ── Ruby ──
    "tina4-ruby": Framework("Tina4 Ruby", "ruby", 9021, [], 0, 38, "WEBrick"),
    "sinatra": Framework("Sinatra", "ruby", 9022, [], 5, 4, "Puma"),
    "roda": Framework("Roda", "ruby", 9023, [], 1, 3, "WEBrick"),
    "rails": Framework("Rails", "ruby", 9024, [], 40, 20, "Puma"),

    # ── Node.js ──
    "tina4-nodejs": Framework("Tina4 Node.js", "nodejs", 9031, [], 0, 38, "built-in"),
    "express": Framework("Express", "nodejs", 9032, [], 3, 4, "built-in"),
    "fastify": Framework("Fastify", "nodejs", 9033, [], 10, 5, "built-in"),
    "koa": Framework("Koa", "nodejs", 9034, [], 5, 3, "built-in"),
    "node-raw": Framework("Node.js raw", "nodejs", 9035, [], 0, 1, "built-in http"),
}


# ── Route templates ───────────────────────────────────────────

LARAVEL_ROUTES = r"""<?php
use Illuminate\Support\Facades\Route;
use Illuminate\Http\JsonResponse;

Route::get('/api/bench/json', function () {
    return new JsonResponse(['message' => 'Hello, World!', 'framework' => 'laravel']);
});

Route::get('/api/bench/list', function () {
    $items = [];
    for ($i = 0; $i < 100; $i++) {
        $items[] = ['id' => $i, 'name' => "Item $i", 'price' => round($i * 1.99, 2)];
    }
    return new JsonResponse(['items' => $items, 'count' => 100]);
});
"""

SYMFONY_CONTROLLER = r"""<?php
namespace App\Controller;

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\Routing\Annotation\Route;

class BenchController
{
    #[Route('/api/bench/json', methods: ['GET'])]
    public function json(): JsonResponse
    {
        return new JsonResponse(['message' => 'Hello, World!', 'framework' => 'symfony']);
    }

    #[Route('/api/bench/list', methods: ['GET'])]
    public function list(): JsonResponse
    {
        $items = [];
        for ($i = 0; $i < 100; $i++) {
            $items[] = ['id' => $i, 'name' => "Item $i", 'price' => round($i * 1.99, 2)];
        }
        return new JsonResponse(['items' => $items, 'count' => 100]);
    }
}
"""

SYMFONY_ROUTES_YAML = """controllers:
    resource:
        path: ../src/Controller/
        namespace: App\\Controller
    type: attribute
"""

RAILS_CONTROLLER = """class BenchController < ApplicationController
  def json_bench
    render json: { message: 'Hello, World!', framework: 'rails' }
  end

  def list_bench
    items = (0...100).map { |i| { id: i, name: "Item #{i}", price: (i * 1.99).round(2) } }
    render json: { items: items, count: 100 }
  end
end
"""

RAILS_ROUTES = """Rails.application.routes.draw do
  get '/api/bench/json', to: 'bench#json_bench'
  get '/api/bench/list', to: 'bench#list_bench'
end
"""

RODA_CONFIG_RU = r"""require "roda"
require "json"

class BenchApp < Roda
  route do |r|
    r.get("api", "bench", "json") do
      response["Content-Type"] = "application/json"
      JSON.generate({message: "Hello, World!", framework: "roda"})
    end
    r.get("api", "bench", "list") do
      response["Content-Type"] = "application/json"
      items = (0...100).map { |i| {id: i, name: "Item #{i}", price: (i * 1.99).round(2)} }
      JSON.generate({items: items, count: 100})
    end
  end
end

run BenchApp.freeze.app
"""


# ── Dependency check helpers ──────────────────────────────────

def _has_command(cmd: str) -> bool:
    """Check if a command is available on PATH."""
    return shutil.which(cmd) is not None


# ── Framework auto-setup ──────────────────────────────────────

def _setup_laravel(fresh: bool = False):
    """Create a Laravel project for benchmarking if it doesn't exist."""
    path = Path("/tmp/bench-laravel")
    if fresh and path.exists():
        shutil.rmtree(path)
    if (path / "artisan").exists():
        # Just update routes
        (path / "routes" / "web.php").write_text(LARAVEL_ROUTES)
        return True

    if not _has_command("composer"):
        print("  [WARN] composer not found -- skipping Laravel setup")
        return False

    try:
        print("  Setting up Laravel project (cached in /tmp/bench-laravel)...")
        result = subprocess.run(
            ["composer", "create-project", "--no-interaction", "--prefer-dist",
             "laravel/laravel", str(path)],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            print(f"  [WARN] Laravel create-project failed: {result.stderr[:200]}")
            return False
        (path / "routes" / "web.php").write_text(LARAVEL_ROUTES)
        return True
    except Exception as e:
        print(f"  [WARN] Laravel setup failed: {e}")
        return False


def _setup_symfony(fresh: bool = False):
    """Create a Symfony project for benchmarking if it doesn't exist."""
    path = Path("/tmp/bench-symfony")
    if fresh and path.exists():
        shutil.rmtree(path)

    if (path / "bin" / "console").exists():
        # Update controller + routes
        (path / "src" / "Controller").mkdir(parents=True, exist_ok=True)
        (path / "src" / "Controller" / "BenchController.php").write_text(SYMFONY_CONTROLLER)
        (path / "config" / "routes.yaml").write_text(SYMFONY_ROUTES_YAML)
        return True

    if not _has_command("composer"):
        print("  [WARN] composer not found -- skipping Symfony setup")
        return False

    try:
        print("  Setting up Symfony project (cached in /tmp/bench-symfony)...")
        result = subprocess.run(
            ["composer", "create-project", "--no-interaction",
             "symfony/skeleton", str(path)],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            print(f"  [WARN] Symfony create-project failed: {result.stderr[:200]}")
            return False
        # Install annotations/attributes routing support
        subprocess.run(
            ["composer", "require", "--no-interaction", "symfony/routing"],
            capture_output=True, text=True, timeout=60, cwd=str(path),
        )
        (path / "src" / "Controller").mkdir(parents=True, exist_ok=True)
        (path / "src" / "Controller" / "BenchController.php").write_text(SYMFONY_CONTROLLER)
        (path / "config" / "routes.yaml").write_text(SYMFONY_ROUTES_YAML)
        return True
    except Exception as e:
        print(f"  [WARN] Symfony setup failed: {e}")
        return False


def _setup_rails(fresh: bool = False):
    """Create a Rails project for benchmarking if it doesn't exist."""
    path = Path("/tmp/bench-rails")
    if fresh and path.exists():
        shutil.rmtree(path)

    if (path / "Gemfile").exists():
        # Update controller + routes
        (path / "app" / "controllers" / "bench_controller.rb").write_text(RAILS_CONTROLLER)
        (path / "config" / "routes.rb").write_text(RAILS_ROUTES)
        return True

    if not _has_command("rails"):
        print("  [WARN] rails not found -- skipping Rails setup")
        return False

    try:
        print("  Setting up Rails project (cached in /tmp/bench-rails)...")
        result = subprocess.run(
            ["rails", "new", str(path), "--api", "--minimal", "--skip-git",
             "--skip-docker", "--skip-test"],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            print(f"  [WARN] rails new failed: {result.stderr[:200]}")
            return False
        subprocess.run(
            ["bundle", "config", "set", "--local", "path", "vendor/bundle"],
            capture_output=True, cwd=str(path),
        )
        result = subprocess.run(
            ["bundle", "install"],
            capture_output=True, text=True, timeout=180, cwd=str(path),
        )
        if result.returncode != 0:
            print(f"  [WARN] bundle install failed: {result.stderr[:200]}")
            return False
        (path / "app" / "controllers" / "bench_controller.rb").write_text(RAILS_CONTROLLER)
        (path / "config" / "routes.rb").write_text(RAILS_ROUTES)
        return True
    except Exception as e:
        print(f"  [WARN] Rails setup failed: {e}")
        return False


def _setup_roda(fresh: bool = False):
    """Create a Roda config.ru for benchmarking."""
    path = Path("/tmp/bench-roda")
    if fresh and path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

    # Check that roda gem is available
    if not _has_command("puma"):
        print("  [WARN] puma not found -- skipping Roda setup")
        return False

    (path / "config.ru").write_text(RODA_CONFIG_RU)

    # Create a minimal Gemfile if missing
    gemfile = path / "Gemfile"
    if not gemfile.exists():
        gemfile.write_text('source "https://rubygems.org"\ngem "roda"\ngem "puma"\n')
        result = subprocess.run(
            ["bundle", "install"],
            capture_output=True, text=True, timeout=60, cwd=str(path),
        )
        if result.returncode != 0:
            print(f"  [WARN] Roda bundle install failed: {result.stderr[:200]}")
            return False

    return True


def _setup_slim(fresh: bool = False):
    """Create a Slim PHP project for benchmarking."""
    path = Path("/tmp/bench-slim")
    if fresh and path.exists():
        shutil.rmtree(path)

    if (path / "vendor").exists():
        return True

    if not _has_command("composer"):
        print("  [WARN] composer not found -- skipping Slim setup")
        return False

    try:
        print("  Setting up Slim project (cached in /tmp/bench-slim)...")
        path.mkdir(parents=True, exist_ok=True)
        # Create composer.json
        (path / "composer.json").write_text(json.dumps({
            "require": {"slim/slim": "^4.0", "slim/psr7": "^1.0"},
        }))
        result = subprocess.run(
            ["composer", "install", "--no-interaction"],
            capture_output=True, text=True, timeout=120, cwd=str(path),
        )
        if result.returncode != 0:
            print(f"  [WARN] Slim composer install failed: {result.stderr[:200]}")
            return False

        (path / "index.php").write_text(r"""<?php
require __DIR__ . '/vendor/autoload.php';
use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;

$app = AppFactory::create();

$app->get('/api/bench/json', function (Request $request, Response $response) {
    $response->getBody()->write(json_encode(['message' => 'Hello, World!', 'framework' => 'slim']));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->get('/api/bench/list', function (Request $request, Response $response) {
    $items = [];
    for ($i = 0; $i < 100; $i++) {
        $items[] = ['id' => $i, 'name' => "Item $i", 'price' => round($i * 1.99, 2)];
    }
    $response->getBody()->write(json_encode(['items' => $items, 'count' => 100]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->run();
""")
        return True
    except Exception as e:
        print(f"  [WARN] Slim setup failed: {e}")
        return False


def _setup_tina4_project(language: str, fresh: bool = False):
    """Scaffold a Tina4 project using `tina4 init` and add benchmark routes."""
    path = Path(f"/tmp/bench-tina4-{language}")
    if fresh and path.exists():
        shutil.rmtree(path)

    # Route templates per language
    routes = {
        "python": (
            "src/routes/bench.py",
            'from tina4_python.core.router import get\n\n'
            '@get("/api/bench/json")\n'
            'async def bench_json(request, response):\n'
            '    return response({"message": "Hello, World!", "framework": "tina4-python"})\n\n'
            '@get("/api/bench/list")\n'
            'async def bench_list(request, response):\n'
            '    return response({"items": [{"id": i, "name": f"Item {i}", "price": round(i*1.99, 2)} for i in range(100)], "count": 100})\n'
        ),
        "php": (
            "src/routes/bench.php",
            '<?php\n'
            '\\Tina4\\Router::get("/api/bench/json", function($request, $response) {\n'
            '    return $response(["message" => "Hello, World!", "framework" => "tina4-php"]);\n'
            '});\n\n'
            '\\Tina4\\Router::get("/api/bench/list", function($request, $response) {\n'
            '    $items = array_map(fn($i) => ["id" => $i, "name" => "Item $i", "price" => round($i * 1.99, 2)], range(0, 99));\n'
            '    return $response(["items" => $items, "count" => 100]);\n'
            '});\n'
        ),
        "ruby": (
            "src/routes/bench.rb",
            'Tina4::Router.get("/api/bench/json") do |request, response|\n'
            '  response.json({message: "Hello, World!", framework: "tina4-ruby"})\n'
            'end\n\n'
            'Tina4::Router.get("/api/bench/list") do |request, response|\n'
            '  items = (0...100).map { |i| {id: i, name: "Item #{i}", price: (i * 1.99).round(2)} }\n'
            '  response.json({items: items, count: 100})\n'
            'end\n'
        ),
        "nodejs": (
            "src/routes/bench.ts",
            'import { get } from "tina4-nodejs";\n\n'
            'get("/api/bench/json", (req: any, res: any) => {\n'
            '  return res.json({message: "Hello, World!", framework: "tina4-nodejs"});\n'
            '});\n\n'
            'get("/api/bench/list", (req: any, res: any) => {\n'
            '  const items = Array.from({length: 100}, (_, i) => ({id: i, name: `Item ${i}`, price: +(i * 1.99).toFixed(2)}));\n'
            '  return res.json({items, count: 100});\n'
            '});\n'
        ),
    }

    route_file, route_code = routes[language]

    # Check if already scaffolded (cached)
    markers = {"python": ".venv", "php": "vendor", "ruby": "Gemfile.lock", "nodejs": "node_modules"}
    if (path / markers[language]).exists():
        # Just update routes and .env
        route_path = path / route_file
        route_path.parent.mkdir(parents=True, exist_ok=True)
        route_path.write_text(route_code)
        (path / ".env").write_text("TINA4_DEBUG=false\nTINA4_LOG_LEVEL=ERROR\n")
        return True

    if not _has_command("tina4"):
        print(f"  [WARN] tina4 CLI not found -- skipping Tina4 {language}")
        return False

    try:
        print(f"  Setting up Tina4 {language} via `tina4 init` (cached in {path})...")
        result = subprocess.run(
            ["tina4", "init", language, str(path)],
            capture_output=True, text=True, timeout=180,
            input="n\n",  # Answer "Start server now?" with no
        )
        if result.returncode != 0:
            print(f"  [WARN] tina4 init {language} failed: {result.stderr[:200]}")
            return False

        # Set production .env
        (path / ".env").write_text("TINA4_DEBUG=false\nTINA4_LOG_LEVEL=ERROR\n")

        # Add benchmark routes
        route_path = path / route_file
        route_path.parent.mkdir(parents=True, exist_ok=True)
        route_path.write_text(route_code)

        return True
    except Exception as e:
        print(f"  [WARN] Tina4 {language} setup failed: {e}")
        return False


# ── Server Scripts ────────────────────────────────────────────

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

    # ── PHP (Tina4 PHP uses a real project setup via _setup_tina4_php) ──

    # ── Ruby (Tina4 Ruby uses a real project setup via _setup_tina4_ruby) ──

    (TMP / "sinatra_bench.rb").write_text(
        'require "sinatra/base"; require "json"\n'
        'class B < Sinatra::Base\n'
        '  set :port, 9022; set :bind, "127.0.0.1"; set :logging, false; set :environment, :production\n'
        '  get("/api/bench/json"){content_type :json; JSON.generate({message:"Hello, World!",framework:"sinatra"})}\n'
        '  get("/api/bench/list"){content_type :json; JSON.generate({items:(0...100).map{|i|{id:i,name:"Item \\#{i}",price:(i*1.99).round(2)}},count:100})}\n'
        '  run!\n'
        'end\n'
    )

    # ── Node.js (Tina4 Node.js uses a real project setup via _setup_tina4_nodejs) ──

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


def _wait_for_server(port: int, timeout: float = 15.0) -> bool:
    """Wait for a server to respond on the given port. Returns True if ready."""
    import urllib.request
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if not _port_free(port):
                resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/bench/json", timeout=2)
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _start_server(key: str, fresh: bool = False) -> bool:
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
        "TINA4_NO_BROWSER": "true",
        "FLASK_ENV": "production",
        "NODE_ENV": "production",
        "RACK_ENV": "production",
        "DJANGO_SETTINGS_MODULE": "bench_settings",
        "PYTHONDONTWRITEBYTECODE": "1",
        "APP_DEBUG": "false",
        "APP_ENV": "production",
    }

    # Build command based on framework
    cmd = None
    cwd = str(TMP)

    if key == "tina4-python":
        if not _setup_tina4_project("python", fresh):
            return False
        cmd = ["tina4", "serve", "--port", str(port), "--no-browser"]
        cwd = str(Path("/tmp/bench-tina4-python"))
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
        if not _setup_tina4_project("php", fresh):
            return False
        cmd = ["tina4", "serve", "--port", str(port), "--no-browser"]
        cwd = str(Path("/tmp/bench-tina4-php"))

    elif key == "slim":
        slim_dir = Path("/tmp/bench-slim")
        if not _setup_slim(fresh):
            return False
        if not (slim_dir / "vendor").exists():
            return False
        cmd = ["php", "-S", f"127.0.0.1:{port}", "-d", "display_errors=Off",
               str(slim_dir / "index.php")]

    elif key == "laravel":
        if not _setup_laravel(fresh):
            return False
        laravel_dir = Path("/tmp/bench-laravel")
        if not (laravel_dir / "artisan").exists():
            return False
        env["APP_DEBUG"] = "false"
        cmd = ["php", "artisan", "serve", f"--host=127.0.0.1", f"--port={port}", "--no-reload"]
        cwd = str(laravel_dir)

    elif key == "symfony":
        if not _setup_symfony(fresh):
            return False
        symfony_dir = Path("/tmp/bench-symfony")
        if not (symfony_dir / "bin" / "console").exists():
            return False
        env["APP_ENV"] = "prod"
        env["APP_DEBUG"] = "0"
        cmd = ["php", "-S", f"127.0.0.1:{port}", "-d", "display_errors=Off",
               str(symfony_dir / "public" / "index.php")]
        cwd = str(symfony_dir / "public")

    elif key == "tina4-ruby":
        if not _setup_tina4_project("ruby", fresh):
            return False
        cmd = ["tina4", "serve", "--port", str(port), "--no-browser"]
        cwd = str(Path("/tmp/bench-tina4-ruby"))

    elif key == "sinatra":
        cmd = [RUBY, str(TMP / "sinatra_bench.rb")]

    elif key == "roda":
        if not _setup_roda(fresh):
            return False
        roda_dir = Path("/tmp/bench-roda")
        cmd = ["bundle", "exec", "puma", "-b", f"tcp://127.0.0.1:{port}",
               "-e", "production", "-q", str(roda_dir / "config.ru")]
        cwd = str(roda_dir)

    elif key == "rails":
        if not _setup_rails(fresh):
            return False
        rails_dir = Path("/tmp/bench-rails")
        if not (rails_dir / "Gemfile").exists():
            return False
        env["RAILS_ENV"] = "production"
        env["SECRET_KEY_BASE"] = "benchmarkkeybenchmarkkeybenchmarkkeybenchmarkkeyxx"
        env["RAILS_LOG_TO_STDOUT"] = "false"
        cmd = ["bundle", "exec", "puma", "-b", f"tcp://127.0.0.1:{port}",
               "-e", "production", "-q"]
        cwd = str(rails_dir)

    elif key == "tina4-nodejs":
        if not _setup_tina4_project("nodejs", fresh):
            return False
        cmd = ["tina4", "serve", "--port", str(port), "--no-browser"]
        cwd = str(Path("/tmp/bench-tina4-nodejs"))
    elif key == "express":
        cmd = ["node", str(TMP / "express_bench.mjs")]
    elif key == "fastify":
        cmd = ["node", str(TMP / "fastify_bench.mjs")]
    elif key == "koa":
        cmd = ["node", str(TMP / "koa_bench.mjs")]
    elif key == "node-raw":
        cmd = ["node", str(TMP / "node_raw_bench.mjs")]

    if cmd is None:
        return False

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=cwd,
            env=env,
        )
        _processes.append(proc)

        if _wait_for_server(port):
            return True

        # Server didn't respond -- check if process died
        if proc.poll() is not None:
            return False
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


def benchmark_framework(key: str, runs: int, requests: int, concurrency: int,
                        fresh: bool = False) -> BenchResult | None:
    fw = FRAMEWORKS[key]
    port = fw.port
    base = f"http://127.0.0.1:{port}"

    print(f"  Starting {fw.name}...", end="", flush=True)

    if not _start_server(key, fresh=fresh):
        print(" [SKIP] failed to start")
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

    print(f" OK  JSON: {result.json_median:,.0f} req/s  List: {result.list_median:,.0f} req/s  (warm-up: {warmup_ms:.0f}ms)")
    return result


# ── Report ─────────────────────────────────────────────────────

LANG_LABELS = {"python": "Python", "php": "PHP", "ruby": "Ruby", "nodejs": "Node.js"}


def _print_language_table(lang: str, lang_results: list[BenchResult],
                          runs: int, requests: int, concurrency: int):
    """Print a per-language benchmark table."""
    label = LANG_LABELS.get(lang, lang)
    print()
    print(f"=== {label} Benchmark ({requests:,} req x {concurrency} concurrent x {runs} runs) ===")
    print()

    fmt = "  {:<22s} {:>12s} {:>12s} {:>16s} {:>6s}"
    print(fmt.format("Framework", "JSON req/s", "List req/s", "Server", "Deps"))
    print("  " + "-" * 72)

    for r in sorted(lang_results, key=lambda x: x.json_median, reverse=True):
        is_tina4 = "Tina4" in r.framework
        marker = "*" if is_tina4 else " "
        deps_str = str(r.deps) if r.deps == 0 else f"{r.deps}+"
        print(fmt.format(
            f"{marker} {r.framework}",
            f"{r.json_median:,.0f}",
            f"{r.list_median:,.0f}",
            r.server,
            deps_str,
        ))

    print()


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

    # Per-language tables
    for lang in ["python", "php", "ruby", "nodejs"]:
        lang_results = [r for r in results if r.language == lang]
        if not lang_results:
            continue
        _print_language_table(lang, lang_results, runs, requests, concurrency)

    # Overall ranking
    results_sorted = sorted(results, key=lambda r: r.json_median, reverse=True)
    print("  -- Overall Ranking " + "-" * 58)
    print()
    for i, r in enumerate(results_sorted, 1):
        is_tina4 = "Tina4" in r.framework
        marker = " *" if is_tina4 and i <= 3 else "  "
        print(f"  {marker} {i:2d}. {r.framework:<22s} {r.json_median:>10,.0f} req/s  ({r.language}, {r.deps} deps, {r.features}/38 features)")

    print()


def _save_per_language_results(results: list[BenchResult], runs: int, requests: int, concurrency: int):
    """Save results split by language into benchmarks/results/<language>.json."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    meta = {
        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "machine": f"{platform.machine()} {platform.system()}",
        "config": {"runs": runs, "requests": requests, "concurrency": concurrency, "warmup": WARMUP_REQUESTS},
    }

    for lang in ["python", "php", "ruby", "nodejs"]:
        lang_results = [r for r in results if r.language == lang]
        if not lang_results:
            continue
        report = {**meta, "results": [asdict(r) for r in lang_results]}
        out = RESULTS_DIR / f"{lang}.json"
        out.write_text(json.dumps(report, indent=2))
        print(f"  Saved {lang} results to: {out}")


# ── Database Benchmarks ────────────────────────────────────────

DB_ITERATIONS = 1000
DB_PATH = "/tmp/tina4_bench.db"


@dataclass
class DbBenchResult:
    name: str
    framework: str
    ops_per_sec: float
    total_ms: float


def _setup_tina4_db():
    """Create a Tina4 SQLite database with test tables and seed data."""
    import sqlite3
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT, age INTEGER)")
    conn.execute("CREATE TABLE bench (id INTEGER PRIMARY KEY, name TEXT, value REAL)")
    for i in range(1, 1001):
        conn.execute("INSERT INTO users (id, name, email, age) VALUES (?, ?, ?, ?)",
                     (i, f"User {i}", f"user{i}@example.com", 20 + (i % 50)))
    conn.commit()
    conn.close()


def _bench_tina4_db(iterations: int) -> list[DbBenchResult]:
    """Run database benchmarks using Tina4 Database."""
    sys.path.insert(0, str(PROJECT_ROOT))

    _setup_tina4_db()
    results = []

    os.environ.pop("TINA4_DB_CACHE", None)
    os.environ["TINA4_DB_CACHE"] = "false"
    from tina4_python.database.connection import Database

    db = Database(f"sqlite:///{DB_PATH}")

    # 1. Single row fetch
    t0 = time.perf_counter()
    for i in range(iterations):
        db.fetch_one("SELECT * FROM users WHERE id = ?", [i % 1000 + 1])
    elapsed = time.perf_counter() - t0
    results.append(DbBenchResult("Single row fetch", "Tina4", iterations / elapsed, elapsed * 1000))

    # 2. Multi-row fetch (100 rows)
    t0 = time.perf_counter()
    for _ in range(iterations):
        db.fetch("SELECT * FROM users", limit=100)
    elapsed = time.perf_counter() - t0
    results.append(DbBenchResult("Multi-row fetch (100)", "Tina4", iterations / elapsed, elapsed * 1000))

    # 3. Insert
    t0 = time.perf_counter()
    for i in range(iterations):
        db.insert("bench", {"name": f"item_{i}", "value": i * 1.5})
    db.commit()
    elapsed = time.perf_counter() - t0
    results.append(DbBenchResult("Insert", "Tina4", iterations / elapsed, elapsed * 1000))

    # 4. CRUD cycle (insert + read + update + delete)
    t0 = time.perf_counter()
    for i in range(iterations):
        db.execute("INSERT INTO bench (name, value) VALUES (?, ?)", [f"crud_{i}", i])
        db.fetch_one("SELECT * FROM bench WHERE name = ?", [f"crud_{i}"])
        db.execute("UPDATE bench SET value = ? WHERE name = ?", [i + 1, f"crud_{i}"])
        db.execute("DELETE FROM bench WHERE name = ?", [f"crud_{i}"])
    db.commit()
    elapsed = time.perf_counter() - t0
    results.append(DbBenchResult("CRUD cycle", "Tina4", iterations / elapsed, elapsed * 1000))

    db.close()

    # 5. Fetch with cache ON
    os.environ["TINA4_DB_CACHE"] = "true"
    os.environ["TINA4_DB_CACHE_TTL"] = "30"

    db_cached = Database(f"sqlite:///{DB_PATH}")
    db_cached.fetch_one("SELECT * FROM users WHERE id = ?", [1])

    t0 = time.perf_counter()
    for i in range(iterations):
        db_cached.fetch_one("SELECT * FROM users WHERE id = ?", [1])
    elapsed = time.perf_counter() - t0
    cached_ops = iterations / elapsed
    results.append(DbBenchResult("Cached fetch (TTL=30)", "Tina4", cached_ops, elapsed * 1000))

    # 6. Fetch with cache OFF
    os.environ["TINA4_DB_CACHE"] = "false"
    db_nocache = Database(f"sqlite:///{DB_PATH}")

    t0 = time.perf_counter()
    for i in range(iterations):
        db_nocache.fetch_one("SELECT * FROM users WHERE id = ?", [1])
    elapsed = time.perf_counter() - t0
    uncached_ops = iterations / elapsed
    results.append(DbBenchResult("Uncached fetch", "Tina4", uncached_ops, elapsed * 1000))

    # Cache speedup ratio
    speedup = cached_ops / uncached_ops if uncached_ops > 0 else 0
    results.append(DbBenchResult("Cache speedup", "Tina4", speedup, 0))

    db_cached.close()
    db_nocache.close()

    return results


def _bench_django_db(iterations: int) -> list[DbBenchResult]:
    """Run database benchmarks using Django ORM (if installed)."""
    try:
        import django
    except ImportError:
        return []

    results = []
    db_path = "/tmp/tina4_bench_django.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    from django.conf import settings
    if not settings.configured:
        settings.configure(
            DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": db_path}},
            INSTALLED_APPS=["django.contrib.contenttypes"],
            DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        )
        django.setup()

    from django.db import connection
    cursor = connection.cursor()
    cursor.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT, age INTEGER)")
    for i in range(1, 1001):
        cursor.execute("INSERT INTO users (id, name, email, age) VALUES (%s, %s, %s, %s)",
                       [i, f"User {i}", f"user{i}@example.com", 20 + (i % 50)])
    cursor.execute("CREATE TABLE bench (id INTEGER PRIMARY KEY, name TEXT, value REAL)")

    t0 = time.perf_counter()
    for i in range(iterations):
        cursor.execute("SELECT * FROM users WHERE id = %s", [i % 1000 + 1])
        cursor.fetchone()
    elapsed = time.perf_counter() - t0
    results.append(DbBenchResult("Single row fetch", "Django", iterations / elapsed, elapsed * 1000))

    t0 = time.perf_counter()
    for _ in range(iterations):
        cursor.execute("SELECT * FROM users LIMIT 100")
        cursor.fetchall()
    elapsed = time.perf_counter() - t0
    results.append(DbBenchResult("Multi-row fetch (100)", "Django", iterations / elapsed, elapsed * 1000))

    t0 = time.perf_counter()
    for i in range(iterations):
        cursor.execute("INSERT INTO bench (name, value) VALUES (%s, %s)", [f"item_{i}", i * 1.5])
    elapsed = time.perf_counter() - t0
    results.append(DbBenchResult("Insert", "Django", iterations / elapsed, elapsed * 1000))

    t0 = time.perf_counter()
    for i in range(iterations):
        cursor.execute("INSERT INTO bench (name, value) VALUES (%s, %s)", [f"crud_{i}", i])
        cursor.execute("SELECT * FROM bench WHERE name = %s", [f"crud_{i}"])
        cursor.fetchone()
        cursor.execute("UPDATE bench SET value = %s WHERE name = %s", [i + 1, f"crud_{i}"])
        cursor.execute("DELETE FROM bench WHERE name = %s", [f"crud_{i}"])
    elapsed = time.perf_counter() - t0
    results.append(DbBenchResult("CRUD cycle", "Django", iterations / elapsed, elapsed * 1000))

    results.append(DbBenchResult("Cached fetch (TTL=30)", "Django", 0, 0))
    results.append(DbBenchResult("Uncached fetch", "Django", 0, 0))
    results.append(DbBenchResult("Cache speedup", "Django", 0, 0))

    connection.close()
    return results


def _bench_sqlalchemy_db(iterations: int) -> list[DbBenchResult]:
    """Run database benchmarks using SQLAlchemy (if installed)."""
    try:
        import sqlalchemy
    except ImportError:
        return []

    results = []
    db_path = "/tmp/tina4_bench_sa.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    from sqlalchemy import create_engine, text
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT, age INTEGER)"))
        for i in range(1, 1001):
            conn.execute(text("INSERT INTO users (id, name, email, age) VALUES (:id, :name, :email, :age)"),
                         {"id": i, "name": f"User {i}", "email": f"user{i}@example.com", "age": 20 + (i % 50)})
        conn.execute(text("CREATE TABLE bench (id INTEGER PRIMARY KEY, name TEXT, value REAL)"))
        conn.commit()

    with engine.connect() as conn:
        t0 = time.perf_counter()
        for i in range(iterations):
            conn.execute(text("SELECT * FROM users WHERE id = :id"), {"id": i % 1000 + 1}).fetchone()
        elapsed = time.perf_counter() - t0
        results.append(DbBenchResult("Single row fetch", "SQLAlchemy", iterations / elapsed, elapsed * 1000))

        t0 = time.perf_counter()
        for _ in range(iterations):
            conn.execute(text("SELECT * FROM users LIMIT 100")).fetchall()
        elapsed = time.perf_counter() - t0
        results.append(DbBenchResult("Multi-row fetch (100)", "SQLAlchemy", iterations / elapsed, elapsed * 1000))

        t0 = time.perf_counter()
        for i in range(iterations):
            conn.execute(text("INSERT INTO bench (name, value) VALUES (:name, :value)"),
                         {"name": f"item_{i}", "value": i * 1.5})
        conn.commit()
        elapsed = time.perf_counter() - t0
        results.append(DbBenchResult("Insert", "SQLAlchemy", iterations / elapsed, elapsed * 1000))

        t0 = time.perf_counter()
        for i in range(iterations):
            conn.execute(text("INSERT INTO bench (name, value) VALUES (:name, :value)"),
                         {"name": f"crud_{i}", "value": i})
            conn.execute(text("SELECT * FROM bench WHERE name = :name"), {"name": f"crud_{i}"}).fetchone()
            conn.execute(text("UPDATE bench SET value = :value WHERE name = :name"),
                         {"value": i + 1, "name": f"crud_{i}"})
            conn.execute(text("DELETE FROM bench WHERE name = :name"), {"name": f"crud_{i}"})
        conn.commit()
        elapsed = time.perf_counter() - t0
        results.append(DbBenchResult("CRUD cycle", "SQLAlchemy", iterations / elapsed, elapsed * 1000))

    results.append(DbBenchResult("Cached fetch (TTL=30)", "SQLAlchemy", 0, 0))
    results.append(DbBenchResult("Uncached fetch", "SQLAlchemy", 0, 0))
    results.append(DbBenchResult("Cache speedup", "SQLAlchemy", 0, 0))

    engine.dispose()
    return results


def run_db_benchmarks(iterations: int = DB_ITERATIONS):
    """Run all database benchmarks and print results."""
    print()
    print("=" * 80)
    print("  DATABASE BENCHMARKS")
    print("=" * 80)
    print()
    print(f"  Iterations: {iterations}")
    print(f"  Database:   SQLite (in /tmp)")
    print()

    print("  Running Tina4 database benchmarks...")
    tina4_results = _bench_tina4_db(iterations)

    print("  Running Django database benchmarks...")
    django_results = _bench_django_db(iterations)

    print("  Running SQLAlchemy database benchmarks...")
    sa_results = _bench_sqlalchemy_db(iterations)

    print()

    bench_names = []
    for r in tina4_results:
        if r.name not in bench_names:
            bench_names.append(r.name)

    def _lookup(results, name):
        for r in results:
            if r.name == name:
                return r
        return None

    has_django = len(django_results) > 0
    has_sa = len(sa_results) > 0

    header = f"  {'Benchmark':<28s} {'Tina4':>12s}"
    if has_django:
        header += f" {'Django':>12s}"
    if has_sa:
        header += f" {'SQLAlchemy':>12s}"
    print(header)
    print("  " + "-" * (28 + 12 + (14 if has_django else 0) + (14 if has_sa else 0)))

    for name in bench_names:
        t4 = _lookup(tina4_results, name)
        dj = _lookup(django_results, name) if has_django else None
        sa = _lookup(sa_results, name) if has_sa else None

        if name == "Cache speedup":
            t4_val = f"{t4.ops_per_sec:.1f}x" if t4 and t4.ops_per_sec > 0 else "N/A"
            dj_val = "N/A"
            sa_val = "N/A"
        else:
            t4_val = f"{t4.ops_per_sec:,.0f}" if t4 and t4.ops_per_sec > 0 else "N/A"
            dj_val = f"{dj.ops_per_sec:,.0f}" if dj and dj.ops_per_sec > 0 else "N/A"
            sa_val = f"{sa.ops_per_sec:,.0f}" if sa and sa.ops_per_sec > 0 else "N/A"

        line = f"  {name:<28s} {t4_val:>12s}"
        if has_django:
            line += f" {dj_val:>12s}"
        if has_sa:
            line += f" {sa_val:>12s}"
        print(line)

    print()

    for p in [DB_PATH, "/tmp/tina4_bench_django.db", "/tmp/tina4_bench_sa.db"]:
        if os.path.exists(p):
            os.remove(p)

    return tina4_results, django_results, sa_results


# ── Main ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Tina4 v3 Benchmark Suite")
    parser.add_argument("--all", action="store_true", help="Run all frameworks (default if no language specified)")
    parser.add_argument("--python", action="store_true", help="Python frameworks only")
    parser.add_argument("--php", action="store_true", help="PHP frameworks only")
    parser.add_argument("--ruby", action="store_true", help="Ruby frameworks only")
    parser.add_argument("--nodejs", action="store_true", help="Node.js frameworks only")
    parser.add_argument("--runs", type=int, default=RUNS, help=f"Runs per test (default: {RUNS})")
    parser.add_argument("--requests", type=int, default=REQUESTS, help=f"Requests per run (default: {REQUESTS})")
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY, help=f"Concurrent connections (default: {CONCURRENCY})")
    parser.add_argument("--output", type=str, default="", help="Save JSON report to file (in addition to per-language files)")
    parser.add_argument("--db", action="store_true", help="Run database benchmarks (SQLite, 1000 iterations)")
    parser.add_argument("--fresh", action="store_true", help="Force recreate temporary projects (Laravel, Symfony, Rails, etc.)")
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
    if not languages or args.all:
        languages = {"python", "php", "ruby", "nodejs"}

    # Database benchmarks mode
    if args.db:
        run_db_benchmarks(DB_ITERATIONS)
        return

    to_test = [k for k, v in FRAMEWORKS.items() if v.language in languages]

    # Check hey is installed
    if not _has_command("hey"):
        print("ERROR: 'hey' not found. Install: brew install hey")
        sys.exit(1)

    # Write server scripts
    print("Setting up benchmark servers...")
    _write_server_scripts()

    # Clean up any existing processes
    print("Cleaning up existing processes...")
    _cleanup_all()
    time.sleep(2)

    print(f"\nBenchmarking {len(to_test)} frameworks ({args.runs} runs, {args.requests} requests, {args.concurrency} concurrent)")
    if args.fresh:
        print("  --fresh: forcing recreation of cached projects")
    print()

    # Run benchmarks
    results = []
    for key in to_test:
        try:
            result = benchmark_framework(key, args.runs, args.requests, args.concurrency,
                                         fresh=args.fresh)
            if result:
                results.append(result)
        except Exception as e:
            fw = FRAMEWORKS[key]
            print(f"  [SKIP] {fw.name} -- error: {e}")

    # Cleanup
    _cleanup_all()

    # Report
    if results:
        print_report(results, args.runs, args.requests, args.concurrency)

        # Save per-language JSON files
        _save_per_language_results(results, args.runs, args.requests, args.concurrency)

        # Save combined JSON
        output_path = args.output or str(PROJECT_ROOT / "benchmarks" / "benchmark_results.json")
        report = {
            "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "machine": f"{platform.machine()} {platform.system()}",
            "config": {"runs": args.runs, "requests": args.requests, "concurrency": args.concurrency, "warmup": WARMUP_REQUESTS},
            "results": [asdict(r) for r in results],
        }
        Path(output_path).write_text(json.dumps(report, indent=2))
        print(f"  Combined results saved to: {output_path}")
    else:
        print("No results -- all frameworks failed to start.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted -- cleaning up...")
        _cleanup_all()
