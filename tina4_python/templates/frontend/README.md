# Frontend

This folder is where your frontend application lives. Tina4 serves everything from `public/` — your frontend build just needs to output there.

## Quick Start

Pick your approach:

### Option 1: Plain JavaScript (no build step)

Just write JS directly in `public/js/`. Include `frond.js` for AJAX, forms, and WebSocket helpers:

```html
<script src="/js/frond.js"></script>
<script>
  const users = await Frond.get("/api/users");
  Frond.submitForm("#myForm", { onSuccess: (r) => console.log(r) });
</script>
```

### Option 2: tina4-js (reactive components)

```bash
cd frontend
npm init -y
npm install tina4js
```

Create `frontend/src/main.js`:
```javascript
import { signal, component } from "tina4js";

const count = signal(0);

component("my-counter", () => `
  <button onclick="${() => count.value++}">
    Clicked ${count} times
  </button>
`);
```

Add a build script to `frontend/package.json`:
```json
{
  "scripts": {
    "build": "vite build --outDir ../public",
    "dev": "vite --proxy http://localhost:7145"
  }
}
```

### Option 3: React / Vue / Svelte / Any SPA

```bash
cd frontend
npm create vite@latest . -- --template react
```

Edit `frontend/vite.config.js`:
```javascript
export default {
  build: {
    outDir: "../public",
    emptyOutDir: false,
  },
  server: {
    proxy: {
      "/api": "http://localhost:7145",
    },
  },
};
```

Then:
```bash
npm install
npm run dev    # dev with hot reload (proxies API to Tina4)
npm run build  # production build → outputs to public/
```

### Option 4: HTMX / Alpine.js (hypermedia)

```html
<script src="https://unpkg.com/htmx.org@2"></script>

<button hx-get="/api/users" hx-target="#list">Load Users</button>
<div id="list"></div>
```

No build step needed — Tina4's Frond templates return HTML fragments that HTMX swaps in.

## How It Works

```
frontend/          ← Your source code (any framework)
  src/
  package.json
  vite.config.js

public/            ← Tina4 serves this at /
  js/              ← Built JS goes here
  css/             ← Built CSS goes here
  index.html       ← SPA entry point (if applicable)

src/routes/        ← Your API endpoints
src/templates/     ← Server-rendered templates (Frond/Twig)
```

**The rule is simple:** anything in `public/` is served as static files at `/`. Point your frontend build tool's output directory at `public/` and everything just works.

## API Integration

All Tina4 routes are available at their registered paths. During development, proxy API calls to Tina4:

- **Tina4 backend:** `http://localhost:7145`
- **Frontend dev server:** `http://localhost:5173` (Vite default)
- **API routes:** `/api/*` proxied to Tina4

In production, both are served from the same origin — no proxy needed.

## frond.js

The built-in `frond.js` helper (served from `public/js/frond.js`) provides:
- `Frond.get()`, `post()`, `put()`, `patch()`, `delete()` — fetch wrapper with auth token handling
- `Frond.submitForm()` — AJAX form submission with validation
- `Frond.ws()` — WebSocket with auto-reconnect
- `Frond.notify()` — toast notifications
- `Frond.modal()` — modal dialogs

Works alongside any frontend framework or standalone.
