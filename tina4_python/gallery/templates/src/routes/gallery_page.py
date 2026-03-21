"""Gallery: Templates — render an HTML page with dynamic data."""
from tina4_python.core.router import get


@get("/gallery/page")
async def gallery_page(request, response):
    items = [
        {"name": "Tina4 Python", "description": "Zero-dep web framework", "badge": "v3.0.0"},
        {"name": "Twig Engine", "description": "Built-in template rendering", "badge": "included"},
        {"name": "Auto-Reload", "description": "Templates refresh on save", "badge": "dev mode"},
    ]

    html = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Gallery Demo</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:system-ui;background:#0f172a;color:#e2e8f0;padding:2rem}
h1{font-size:2rem;margin-bottom:1.5rem}.cards{display:flex;gap:1rem;flex-wrap:wrap}
.card{background:#1e293b;border:1px solid #334155;border-radius:.75rem;padding:1.5rem;flex:1 1 250px}
.card h3{margin-bottom:.5rem}.card p{color:#94a3b8;font-size:.9rem;margin-bottom:.75rem}
.badge{background:#3572A5;color:#fff;padding:2px 8px;border-radius:4px;font-size:.75rem}</style></head>
<body><h1>Gallery Demo Page</h1><div class="cards">"""

    for item in items:
        html += f'<div class="card"><h3>{item["name"]}</h3><p>{item["description"]}</p><span class="badge">{item["badge"]}</span></div>'

    html += "</div></body></html>"
    return response(html)
