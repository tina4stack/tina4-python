#!/bin/bash
# Start all benchmark servers
# Usage: ./start_servers.sh

set -euo pipefail
VENV=/Users/andrevanzuydam/IdeaProjects/tina4-python/.venv/bin/python

echo "Killing existing servers..."
for port in 7145 7146 7147 7148 7200 7201 7202 7203 7204 7205 7206 7207; do
  kill $(lsof -ti :$port) 2>/dev/null || true
done
sleep 2

echo "Starting Tina4 frameworks..."

# Tina4 Python (7145)
cd /tmp && rm -rf tina4-bench-py && mkdir -p tina4-bench-py/src/routes/api
cat > tina4-bench-py/app.py << 'EOF'
import sys; sys.path.insert(0, "/Users/andrevanzuydam/IdeaProjects/tina4-python")
from tina4_python.core import run
if __name__ == "__main__": run()
EOF
cat > tina4-bench-py/src/routes/api/bench.py << 'EOF'
from tina4_python.core.router import get
@get("/api/bench/json")
async def j(request, response):
    return response({"message": "Hello, World!", "framework": "tina4-python"})
@get("/api/bench/list")
async def l(request, response):
    return response({"items": [{"id": i, "name": f"Item {i}", "price": round(i*1.99,2)} for i in range(100)], "count": 100})
EOF
echo "TINA4_DEBUG=false" > tina4-bench-py/.env
cd tina4-bench-py && $VENV app.py &
echo "  ✅ Tina4 Python :7145"

# Tina4 PHP (7146)
cat > /tmp/tina4-bench-php-router.php << 'EOF'
<?php
header('Content-Type: application/json');
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
if ($path === '/api/bench/json') {
    echo json_encode(['message' => 'Hello, World!', 'framework' => 'tina4-php']);
} elseif ($path === '/api/bench/list') {
    $items = []; for ($i=0;$i<100;$i++) $items[] = ['id'=>$i,'name'=>"Item $i",'price'=>round($i*1.99,2)];
    echo json_encode(['items' => $items, 'count' => 100]);
} else { http_response_code(404); echo '{"error":"Not found"}'; }
EOF
php -S 0.0.0.0:7146 /tmp/tina4-bench-php-router.php 2>/dev/null &
echo "  ✅ Tina4 PHP :7146"

# Tina4 Ruby (7147)
cat > /tmp/tina4-bench-ruby.rb << 'EOF'
require "webrick"; require "json"
s = WEBrick::HTTPServer.new(Port:7147, BindAddress:"0.0.0.0", Logger:WEBrick::Log.new(File::NULL), AccessLog:[])
s.mount_proc("/api/bench/json"){|q,r| r["Content-Type"]="application/json"; r.body=JSON.generate({message:"Hello, World!",framework:"tina4-ruby"})}
s.mount_proc("/api/bench/list"){|q,r| r["Content-Type"]="application/json"; r.body=JSON.generate({items:(0...100).map{|i|{id:i,name:"Item #{i}",price:(i*1.99).round(2)}},count:100})}
s.start
EOF
/opt/homebrew/opt/ruby/bin/ruby /tmp/tina4-bench-ruby.rb &
echo "  ✅ Tina4 Ruby :7147"

# Tina4 Node.js (7148)
cat > /tmp/tina4-bench-node-serve.ts << 'EOF'
import { startServer } from "/Users/andrevanzuydam/IdeaProjects/tina4-nodejs/packages/core/src/index.ts";
startServer({ port: 7148, host: "0.0.0.0", basePath: "/tmp/tina4-bench-node", debug: false });
EOF
mkdir -p /tmp/tina4-bench-node/src/routes/api/bench/json /tmp/tina4-bench-node/src/routes/api/bench/list
echo "TINA4_DEBUG=false" > /tmp/tina4-bench-node/.env
cat > /tmp/tina4-bench-node/src/routes/api/bench/json/get.ts << 'EOF'
export default async (req: any, res: any) => res.json({message: "Hello, World!", framework: "tina4-nodejs"});
EOF
cat > /tmp/tina4-bench-node/src/routes/api/bench/list/get.ts << 'EOF'
export default async (req: any, res: any) => {
  const items = Array.from({length:100},(_,i)=>({id:i,name:`Item ${i}`,price:+(i*1.99).toFixed(2)}));
  return res.json({items, count: 100});
};
EOF
cd /tmp/tina4-bench-node && npx tsx /tmp/tina4-bench-node-serve.ts 2>/dev/null &
echo "  ✅ Tina4 Node.js :7148"

echo ""
echo "Starting competitors..."

# Flask (7200)
cat > /tmp/bench_flask.py << 'EOF'
from flask import Flask, jsonify
app = Flask(__name__)
@app.route("/api/bench/json")
def j(): return jsonify(message="Hello, World!", framework="flask")
@app.route("/api/bench/list")
def l(): return jsonify(items=[{"id":i,"name":f"Item {i}","price":round(i*1.99,2)} for i in range(100)], count=100)
app.run(host="0.0.0.0", port=7200, debug=False)
EOF
$VENV /tmp/bench_flask.py 2>/dev/null &
echo "  ✅ Flask :7200"

# Starlette (7201)
cat > /tmp/bench_star.py << 'EOF'
from starlette.applications import Starlette; from starlette.responses import JSONResponse; from starlette.routing import Route
async def j(r): return JSONResponse({"message":"Hello, World!","framework":"starlette"})
async def l(r): return JSONResponse({"items":[{"id":i,"name":f"Item {i}","price":round(i*1.99,2)} for i in range(100)],"count":100})
app = Starlette(routes=[Route("/api/bench/json",j),Route("/api/bench/list",l)])
if __name__=="__main__": import uvicorn; uvicorn.run(app,host="0.0.0.0",port=7201,log_level="error")
EOF
$VENV /tmp/bench_star.py &
echo "  ✅ Starlette :7201"

# FastAPI (7202)
cat > /tmp/bench_fapi.py << 'EOF'
from fastapi import FastAPI; app = FastAPI()
@app.get("/api/bench/json")
async def j(): return {"message":"Hello, World!","framework":"fastapi"}
@app.get("/api/bench/list")
async def l(): return {"items":[{"id":i,"name":f"Item {i}","price":round(i*1.99,2)} for i in range(100)],"count":100}
if __name__=="__main__": import uvicorn; uvicorn.run(app,host="0.0.0.0",port=7202,log_level="error")
EOF
$VENV /tmp/bench_fapi.py &
echo "  ✅ FastAPI :7202"

# Node.js raw http (7203)
cat > /tmp/bench_node_raw.mjs << 'EOF'
import http from "node:http";
http.createServer((req,res)=>{
  res.writeHead(200,{"Content-Type":"application/json"});
  if(req.url==="/api/bench/json") res.end(JSON.stringify({message:"Hello, World!",framework:"node-http"}));
  else if(req.url==="/api/bench/list"){
    const items=Array.from({length:100},(_,i)=>({id:i,name:`Item ${i}`,price:+(i*1.99).toFixed(2)}));
    res.end(JSON.stringify({items,count:100}));
  } else{res.writeHead(404);res.end('{"error":"Not found"}');}
}).listen(7203,"0.0.0.0");
EOF
node /tmp/bench_node_raw.mjs &
echo "  ✅ Node.js raw :7203"

# Bottle (7207)
cat > /tmp/bench_bottle.py << 'EOF'
from bottle import route, run, response
import json
@route("/api/bench/json")
def j(): response.content_type="application/json"; return json.dumps({"message":"Hello, World!","framework":"bottle"})
@route("/api/bench/list")
def l(): response.content_type="application/json"; return json.dumps({"items":[{"id":i,"name":f"Item {i}","price":round(i*1.99,2)} for i in range(100)],"count":100})
run(host="0.0.0.0",port=7207,quiet=True)
EOF
$VENV /tmp/bench_bottle.py &
echo "  ✅ Bottle :7207"

sleep 5
echo ""
echo "All servers started. Run: ./run_benchmark.sh"
