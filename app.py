"""Demo app for Tina4 Dev Admin dashboard."""
import os
os.environ["TINA4_DEBUG_LEVEL"] = "DEBUG"
os.environ["TINA4_DEBUG"] = "true"

from tina4_python.core.router import get
from tina4_python.core.server import run


@get("/")
async def home(request, response):
    return response.html("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tina4</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    min-height: 100vh;
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    color: #e2e8f0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    position: relative;
    overflow: hidden;
  }
  .watermark {
    position: fixed;
    bottom: -2rem;
    right: -2rem;
    width: 20rem;
    height: 20rem;
    opacity: 0.05;
    pointer-events: none;
    z-index: 0;
  }
  .content {
    text-align: center;
    z-index: 1;
    max-width: 600px;
    padding: 2rem;
  }
  .logo { width: 120px; margin-bottom: 1.5rem; opacity: 0.9; }
  h1 { font-size: 2.5rem; font-weight: 700; margin-bottom: 0.5rem; color: #f8fafc; }
  .subtitle { font-size: 1.1rem; color: #94a3b8; margin-bottom: 2rem; }
  .links { display: flex; gap: 1rem; justify-content: center; flex-wrap: wrap; }
  .links a {
    display: inline-flex; align-items: center; gap: 0.4rem;
    padding: 0.6rem 1.4rem; border-radius: 0.5rem;
    text-decoration: none; font-weight: 500; font-size: 0.95rem;
    transition: all 0.2s;
  }
  .primary { background: #3b82f6; color: #fff; }
  .primary:hover { background: #2563eb; transform: translateY(-1px); }
  .secondary { background: rgba(255,255,255,0.08); color: #cbd5e1; border: 1px solid rgba(255,255,255,0.1); }
  .secondary:hover { background: rgba(255,255,255,0.12); color: #f1f5f9; }
  .version { margin-top: 2.5rem; font-size: 0.8rem; color: #475569; }
  .features { margin-top: 2rem; display: flex; gap: 2rem; justify-content: center; color: #64748b; font-size: 0.85rem; }
  .features span { display: flex; align-items: center; gap: 0.3rem; }
  .dot { width: 6px; height: 6px; border-radius: 50%; background: #22c55e; display: inline-block; }
</style>
</head>
<body>
  <img src="https://tina4.com/logo.svg" class="watermark" alt="">
  <div class="content">
    <img src="https://tina4.com/logo.svg" class="logo" alt="Tina4">
    <h1>Tina4</h1>
    <p class="subtitle">This Is Now A 4Framework</p>
    <div class="links">
      <a href="/__dev/" class="primary">Dev Admin</a>
      <a href="/swagger" class="secondary">Swagger</a>
      <a href="/api/hello" class="secondary">API</a>
      <a href="https://tina4.com" class="secondary" target="_blank">Docs</a>
    </div>
    <div class="features">
      <span><span class="dot"></span> Server running</span>
      <span>Port 7145</span>
      <span>v3.0.0</span>
    </div>
    <p class="version">Zero dependencies &bull; Convention over configuration</p>
  </div>
</body>
</html>""")


@get("/api/hello")
async def hello(request, response):
    return response.json({"message": "Hello from Tina4!"})


@get("/api/error")
async def error_demo(request, response):
    raise ValueError("This is a demo error for testing the error tracker")


if __name__ == "__main__":
    run("localhost", 7145)
