# Dev Admin Dashboard

Tina4 includes a built-in development dashboard at `/__dev/` with 11 tabs for inspecting and debugging your application at runtime. It is enabled when `TINA4_DEBUG_LEVEL` is set to `ALL` or `DEBUG`.

## Enabling the Dashboard

```bash
# .env
TINA4_DEBUG_LEVEL=ALL
```

Start your server and visit `http://localhost:7145/__dev/`.

## Dashboard Tabs

### 1. Routes

Lists all registered routes with method, path, auth status, and middleware. Use this to verify your routes are correctly registered and configured.

### 2. Queue

Inspect the job queue: pending, reserved, completed, and failed jobs. View job data, retry counts, and error messages. Useful for debugging background processing.

### 3. Mailbox

View emails sent during development (when using a local mail trap). Inspect HTML content, headers, and attachments without checking an actual inbox.

### 4. Messages

System messages and notifications. Tracks internal framework events and communications.

### 5. Database

Browse database tables, view schema information, and run ad-hoc queries. Shows table structure, row counts, and column types.

### 6. Requests

Request inspector that captures recent HTTP requests with timing and statistics. Shows:
- Request method, path, and status code
- Response time
- Request/response headers
- Request body

### 7. Errors

Error tracker (BrokenTracker) with file-based error deduplication. Shows:
- Error message and stack trace
- File and line number
- First and last occurrence
- Occurrence count

### 8. WS (WebSocket)

Monitor active WebSocket connections: connection ID, path, IP address, connected duration, and message count.

### 9. System

System information: Python version, OS, memory usage, uptime, framework version, loaded modules, and environment variables.

### 10. Tools

Development tools:
- SCSS compiler trigger
- Migration runner
- Seeder runner
- Cache inspection
- Carbonah green benchmarks

### 11. Tina4

AI chat panel with Claude/OpenAI integration. Ask questions about your codebase, debug errors, and get framework guidance. Supports runtime API key configuration.

## Error Overlay

In dev mode, runtime errors display a rich overlay in the browser with:
- Syntax-highlighted stack trace
- Source code context around the error
- Request details that caused the error

The overlay connects via WebSocket at `/__dev_reload` for instant display.

## Ask Tina4 (AI Diagnosis)

The error tracker includes an "Ask Tina4" button that sends error context to Claude or OpenAI for AI-powered diagnosis. Configure the API key:

```bash
# .env
OPENAI_API_KEY=sk-...        # For OpenAI
ANTHROPIC_API_KEY=sk-ant-...  # For Claude
```

Or set it at runtime through the Tina4 tab in the dashboard.

## Dev Reload

When `TINA4_DEBUG_LEVEL=ALL`, the framework watches for file changes:

| File Type | Behavior |
|-----------|----------|
| `.py` | Hot-patched via jurigged (no server restart) |
| `.twig`, `.html` | Browser auto-refreshes |
| `.js` | Browser auto-refreshes |
| `.scss`, `.css` | CSS-only hot-reload (no full refresh) |

The dev reload WebSocket runs at `/__dev_reload`.

## Tips

- The dev admin is only available in debug mode -- it is automatically disabled in production.
- Use the Request tab to debug API calls without external tools.
- The Error tab deduplicates errors, so repeated issues show a count instead of flooding logs.
- The Database tab is for inspection only in production -- use migrations for schema changes.
- The `tina4-dev-admin.js` file is reusable across all four Tina4 frameworks (Python, PHP, TypeScript, Go).
