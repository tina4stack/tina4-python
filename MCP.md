# MCP Server — AI Tool Integration

Tina4 Python ships with a built-in **MCP (Model Context Protocol)** server that turns your
running application into an AI-native backend.  Any tool-driven LLM — Claude Desktop, Cursor,
Copilot, Windsurf, or anything that speaks MCP — can connect over HTTP and interact with your
project: read logs, browse files, update templates, query the database, and more.

The server is embedded directly in your application — no extra process, no sidecar, no CLI
wrapper.  It runs on the same port as your web server at the `/__mcp` path.

---

## Quick Start

### 1. Install / upgrade tina4-python

```bash
pip install tina4-python
# or
uv add tina4-python
```

The `mcp` SDK is included as a dependency automatically.

### 2. Run in debug mode

```bash
python app.py
```

If your `.env` has `TINA4_DEBUG_LEVEL=[TINA4_LOG_ALL]` (the default for new projects), the
MCP server activates automatically — just like hot-reload.  You'll see it in the startup
banner:

```
🚀 Tina4 Python
🌐 http://localhost:7145
🤖 [MCP] endpoint: http://localhost:7145/__mcp  API_KEY: a3f8b2c1...
```

### 3. Connect your AI tool

Point your MCP client at the endpoint shown in the banner.  Every request must include your
`API_KEY` (from `.env`) as a Bearer token.

**Claude Desktop** — add to your MCP config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "my-tina4-app": {
      "url": "http://localhost:7145/__mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY_FROM_ENV"
      }
    }
  }
}
```

**Cursor / Windsurf / other MCP clients** — same URL and Bearer token, in whatever config
format the tool expects.

**curl** (manual testing):

```bash
# Initialize — should return MCP server info
curl -X POST http://localhost:7145/__mcp \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

That's it.  Your AI tool now has access to 26 tools for interacting with your running app.

---

## Activation Rules

| Mode | MCP enabled? | How |
|------|-------------|-----|
| **Debug** (`TINA4_DEBUG_LEVEL` = `ALL`, `DEBUG`, `[TINA4_LOG_ALL]`, or `[TINA4_LOG_DEBUG]`) | **Yes** — automatic | Same as hot-reload (jurigged) |
| **Production** (any other debug level) | **No** — unless opted in | Set `TINA4_MCP=true` in `.env` |

You can always force it off in debug mode with `TINA4_MCP=false`.

The mount path defaults to `/__mcp` but is configurable:

```env
TINA4_MCP_PATH=/__mcp
```

---

## Authentication

Every MCP request is validated before reaching any tool:

1. The middleware extracts the `Authorization` header.
2. It expects `Bearer <token>` format.
3. The token is validated through tina4's auth system (`tina4_auth.valid(token)`), which
   checks both static `API_KEY` and JWT tokens.
4. Invalid or missing tokens get a `401 Unauthorized` JSON-RPC error.

The `API_KEY` is generated automatically when your `.env` is first created (MD5 of the
current date).  You can replace it with any string you like.

---

## Permissions

Every tool belongs to a permission category.  Each category has an independent on/off
toggle in `.env`:

```env
# Master switch (auto-on in debug, opt-in for production)
TINA4_MCP=true

# Granular toggles
TINA4_MCP_LOGS=true           # Diagnostics: logs, routes, env, server info
TINA4_MCP_FILES_READ=true     # File reading: browse, search, read files
TINA4_MCP_FILES_WRITE=true    # Content writing: templates, public, scss
TINA4_MCP_CODE_WRITE=false    # Code writing: routes, app, orm (⚠️ dangerous)
TINA4_MCP_DB_READ=true        # Database reads: SELECT, list tables
TINA4_MCP_DB_WRITE=false      # Database writes: INSERT/UPDATE/DELETE (⚠️ dangerous)
TINA4_MCP_QUEUE=true          # Queue operations: produce, peek
```

### Defaults

| Permission | Debug mode | Production |
|-----------|-----------|------------|
| `TINA4_MCP_LOGS` | `true` | `false` |
| `TINA4_MCP_FILES_READ` | `true` | `false` |
| `TINA4_MCP_FILES_WRITE` | `true` | `false` |
| `TINA4_MCP_CODE_WRITE` | `true` | `false` |
| `TINA4_MCP_DB_READ` | `true` | `false` |
| `TINA4_MCP_DB_WRITE` | `true` | `false` |
| `TINA4_MCP_QUEUE` | `true` | `false` |

Disabled tools still appear in MCP tool discovery, but return a clear error explaining
which `.env` variable to enable.

---

## Tools Reference

### Diagnostics — `TINA4_MCP_LOGS`

| Tool | Parameters | Description |
|------|-----------|-------------|
| `get_logs` | `lines=100`, `level?`, `search?` | Tail the debug log with optional level/text filtering |
| `get_server_info` | — | Version, uptime, debug level, route count, active permissions |
| `list_routes` | `method?`, `search?` | All registered routes with methods, auth flags, handler file/line |
| `get_env` | `keys?` | Environment variables (sensitive values like passwords and API keys are redacted) |
| `get_swagger_spec` | — | Full OpenAPI 3.0 JSON specification |

### File Reading — `TINA4_MCP_FILES_READ`

| Tool | Parameters | Description |
|------|-----------|-------------|
| `read_file` | `path`, `offset?`, `limit?` | Read a project file's contents (max 1 MB) |
| `list_directory` | `path="src"`, `recursive?`, `pattern?` | List files/dirs with size and modified date |
| `search_files` | `pattern`, `path="src"`, `file_pattern?`, `max_results=50` | Regex search across files (like grep) |
| `get_project_structure` | `max_depth=4` | Full directory tree of the project |
| `get_route_handler` | `path`, `method="GET"` | Full source code of a route's handler function |
| `list_orm_models` | — | All ORM classes with fields, table names, source files |

### Content Writing — `TINA4_MCP_FILES_WRITE`

These tools write to safe content directories only:
`src/templates/`, `src/public/`, `src/scss/`, `migrations/`

| Tool | Parameters | Description |
|------|-----------|-------------|
| `write_file` | `path`, `content`, `create_directories=true` | Create or overwrite a file |
| `edit_file` | `path`, `start_line`, `end_line`, `new_content` | Replace a range of lines in a file |
| `delete_file` | `path` | Delete a single file (cannot delete `__init__.py`) |
| `rename_file` | `old_path`, `new_path` | Move or rename a file |

### Code Writing — `TINA4_MCP_CODE_WRITE`

Same four write tools as above, but with additional directories unlocked:
`src/routes/`, `src/app/`, `src/orm/`

> **Warning:** This permission lets an AI modify your application logic.  It defaults to
> `false` even in debug mode.  Enable it deliberately when you want AI-driven code generation.

### Templates — `TINA4_MCP_FILES_READ`

| Tool | Parameters | Description |
|------|-----------|-------------|
| `render_template` | `template`, `data={}` | Render a Twig template and return the HTML |
| `list_templates` | — | All `.twig` files with extends/blocks/includes relationships |
| `get_template_info` | `template` | Detailed template analysis: blocks, variables, filters, content |

### Database — `TINA4_MCP_DB_READ` / `TINA4_MCP_DB_WRITE`

| Tool | Gate | Parameters | Description |
|------|------|-----------|-------------|
| `db_query` | `DB_READ` | `sql`, `params=[]`, `limit=50` | Execute a SELECT query (reads only) |
| `db_tables` | `DB_READ` | — | List all tables with column definitions |
| `db_execute` | `DB_WRITE` | `sql`, `params=[]`, `confirm=true` | Execute INSERT/UPDATE/DELETE (requires explicit confirm) |
| `run_migration` | `DB_WRITE` | `dry_run=true` | List or execute pending SQL migrations |

### Operations — mixed permissions

| Tool | Gate | Parameters | Description |
|------|------|-----------|-------------|
| `compile_scss` | `FILES_WRITE` | — | Trigger SCSS → CSS compilation |
| `trigger_reload` | `LOGS` | `type="reload"` | Push a reload/css-reload to connected browsers (dev mode only) |
| `queue_produce` | `QUEUE` | `topic`, `data`, `user_id?` | Send a message to a named queue |
| `queue_peek` | `QUEUE` | `topic`, `limit=10` | Peek at queued messages without consuming |

---

## File Safety

The MCP server enforces strict file access boundaries, regardless of what an AI requests:

| Category | Paths | Required permission |
|----------|-------|-------------------|
| **Content writable** | `src/templates/`, `src/public/`, `src/scss/`, `migrations/` | `FILES_WRITE` |
| **Code writable** | `src/routes/`, `src/app/`, `src/orm/` | `CODE_WRITE` |
| **Readable** | `src/`, `migrations/`, `logs/`, `app.py`, `pyproject.toml`, `README.md`, `CLAUDE.md` | `FILES_READ` |
| **Blocked always** | `secrets/`, `.env`, `.git/`, `tina4_python/`, `__pycache__/`, `sessions/`, `node_modules/` | — (never accessible) |

Additional protections:
- **Path traversal** (`../`) is always rejected.
- **File size cap**: Reads are limited to 1 MB.
- **`__init__.py` files** cannot be deleted.
- **Sensitive env vars** (containing SECRET, PASSWORD, TOKEN, API_KEY, etc.) are redacted in `get_env` output.

### SQL Safety

- `db_query` only allows `SELECT` / `WITH` statements.  Keywords like INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE are blocked even in subqueries.
- `db_execute` blocks `DROP`, `ALTER`, and `TRUNCATE`.
- `db_execute` requires `confirm=true` — the AI must explicitly acknowledge the write.

---

## Architecture

The MCP server uses the **Streamable HTTP** transport from the official MCP Python SDK.
It is mounted as an ASGI sub-application inside your existing tina4 web server:

```
HTTP request → Hypercorn → app(scope, receive, send)
  │
  ├─ path starts with /__mcp  →  Auth middleware  →  MCP SDK sub-app
  ├─ path == /__dev_reload     →  WebSocket (hot reload)
  └─ everything else           →  Normal tina4 routing
```

No extra port.  No separate process.  The MCP server shares the same Hypercorn instance
as your web application.

The session manager lifecycle wraps the server's `serve()` call:

```python
async with mcp_server.session_manager.run():
    await serve(app, config, shutdown_trigger=shutdown_event.wait)
```

This ensures proper startup and cleanup of MCP resources alongside the web server.

---

## Use Cases

### Content Management
An AI assistant updates your website's templates, images, and stylesheets in real time while
you see changes instantly via hot-reload.

```
You: "Change the homepage hero text to 'Summer Sale 2026'"
AI:  read_file("src/templates/index.twig")
     edit_file("src/templates/index.twig", 12, 12, '<h1>Summer Sale 2026</h1>')
     trigger_reload("reload")
```

### Debugging
Point your AI at the running app and ask it to diagnose issues.

```
You: "Why is the /api/users endpoint returning 500?"
AI:  get_logs(lines=50, level="ERROR", search="/api/users")
     get_route_handler("/api/users", "GET")
     read_file("src/routes/users.py")
```

### Database Exploration
Let the AI explore your schema and data without writing raw SQL yourself.

```
You: "Show me the user table structure and the last 10 signups"
AI:  db_tables()
     db_query("SELECT * FROM users ORDER BY created_at DESC", limit=10)
```

### API Documentation
The AI reads your live Swagger spec and can explain or test your endpoints.

```
You: "What endpoints does this app expose?"
AI:  get_swagger_spec()
     list_routes()
```

### Code Generation (with CODE_WRITE enabled)
The AI writes new routes, ORM models, or app logic directly into your project.

```
You: "Add a POST /api/contacts endpoint that saves to the contacts table"
AI:  list_orm_models()
     db_tables()
     write_file("src/routes/contacts.py", "...")
     trigger_reload("reload")
```

---

## Production Deployment

In production, the MCP server is **off by default**.  To enable it:

```env
# Enable MCP in production
TINA4_MCP=true

# Enable only what you need
TINA4_MCP_LOGS=true
TINA4_MCP_FILES_READ=true
TINA4_MCP_FILES_WRITE=true
TINA4_MCP_CODE_WRITE=false    # Keep this off in production
TINA4_MCP_DB_READ=true
TINA4_MCP_DB_WRITE=false      # Keep this off in production
TINA4_MCP_QUEUE=true
```

**Security checklist for production:**
- Use a strong, unique `API_KEY` — not the auto-generated default.
- Keep `CODE_WRITE` and `DB_WRITE` disabled unless you have a specific use case.
- Run behind a reverse proxy (nginx, Caddy) that handles TLS.
- Restrict `/__mcp` access by IP at the proxy level if possible.
- Monitor `logs/debug.log` for unauthorized access attempts.

---

## .env Reference

All MCP-related environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `TINA4_MCP` | `false` (auto-`true` in debug) | Master switch to enable/disable MCP |
| `TINA4_MCP_PATH` | `/__mcp` | URL path where MCP is mounted |
| `TINA4_MCP_LOGS` | `true` in debug, `false` in prod | Enable diagnostic tools |
| `TINA4_MCP_FILES_READ` | `true` in debug, `false` in prod | Enable file reading tools |
| `TINA4_MCP_FILES_WRITE` | `true` in debug, `false` in prod | Enable content writing tools |
| `TINA4_MCP_CODE_WRITE` | `true` in debug, `false` in prod | Enable code writing tools |
| `TINA4_MCP_DB_READ` | `true` in debug, `false` in prod | Enable database read tools |
| `TINA4_MCP_DB_WRITE` | `true` in debug, `false` in prod | Enable database write tools |
| `TINA4_MCP_QUEUE` | `true` in debug, `false` in prod | Enable queue tools |
| `API_KEY` | Auto-generated MD5 | Shared secret for MCP authentication |

---

## Troubleshooting

**MCP not starting?**
- Check that `TINA4_DEBUG_LEVEL` is set to `ALL` or `DEBUG`, or that `TINA4_MCP=true` is in `.env`.
- Look for `[MCP]` lines in the startup banner.
- Ensure `mcp>=1.9.0` is installed: `pip show mcp`.

**401 Unauthorized?**
- Verify your `Authorization: Bearer <key>` header matches the `API_KEY` in `.env`.
- The key is shown (truncated) in the startup banner for easy copy.

**Tool returns "permission denied"?**
- The error message tells you exactly which `TINA4_MCP_*` variable to set.
- Example: `Tool 'write_file' requires TINA4_MCP_FILES_WRITE=true in .env`

**"No database connection available"?**
- Database tools require an active database connection in your app.
- Make sure your `app.py` creates a `Database(...)` instance.

---

**Tina4 Python** — AI-native by default.
