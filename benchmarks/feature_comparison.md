# Framework Feature Comparison

Comparison of built-in (ships with the core package, no extra install) features across popular web frameworks.

| Feature | Tina4 | Flask | Django | Starlette | Express | Sinatra | Laravel |
|---------|:-----:|:-----:|:------:|:---------:|:-------:|:-------:|:-------:|
| Zero deps core | Yes | No | No | No | No | No | No |
| Built-in ORM | Yes | No | Yes | No | No | No | Yes |
| Built-in template engine | Yes | Yes (Jinja2) | Yes | No | No | Yes (ERB) | Yes (Blade) |
| JWT auth built-in | Yes | No | No | No | No | No | No |
| Queue system built-in | Yes | No | No | No | No | No | Yes |
| WebSocket built-in | Yes | No | No | Yes | No | No | No |
| GraphQL built-in | Yes | No | No | No | No | No | No |
| SOAP/WSDL built-in | Yes | No | No | No | No | No | No |
| Swagger/OpenAPI auto | Yes | No | No | No | No | No | No |
| SCSS auto-compile | Yes | No | No | No | No | No | Yes (Mix) |
| Database migrations | Yes | No | Yes | No | No | No | Yes |
| Dev admin dashboard | Yes | No | Yes | No | No | No | No |
| AI assistant context | Yes | No | No | No | No | No | No |
| Error overlay (dev) | Yes | Yes | Yes | No | No | No | Yes |
| Multi-language support (4 langs) | Yes | No | No | No | No | No | No |
| Gallery/examples deploy | Yes | No | No | No | No | No | No |
| Built-in HTTP client | Yes | No | No | No | No | No | Yes (Http) |
| Session management | Yes | Yes | Yes | No | No | No | Yes |
| Form CSRF protection | Yes | No | Yes | No | No | No | Yes |
| Event system | Yes | Yes (Signals) | Yes (Signals) | No | No | No | Yes |
| Dependency injection | Yes | No | No | Yes | No | No | Yes |
| Fake data / seeder | Yes | No | No | No | No | No | Yes |
| i18n / translations | Yes | No | Yes | No | No | No | Yes |
| CLI scaffolding | Yes | No | Yes | No | Yes | No | Yes |
| Auto-CRUD generator | Yes | No | Yes (admin) | No | No | No | No |
| Response caching | Yes | No | Yes | No | No | No | Yes |
| Inline testing framework | Yes | No | No | No | No | No | No |
| HTML builder (code) | Yes | No | No | No | No | No | No |

## Notes

- **Flask** depends on Werkzeug, Jinja2, MarkupSafe, ItsDangerous, Click, and Blinker. Many features (ORM, auth, migrations, admin) are available as extensions but do not ship with the core package.
- **Django** is batteries-included with ORM, admin, auth, migrations, sessions, i18n, and caching built in. However it depends on ~20 packages and does not include JWT, GraphQL, WebSocket, or queue support out of the box.
- **Starlette** is a lightweight ASGI framework. It depends on anyio, httpx (for TestClient), Jinja2 (optional), and python-multipart. WebSocket support is built in. OpenAPI generation comes via its sibling project FastAPI.
- **Express** (Node.js) is minimalist by design. Almost everything is middleware from npm. WebSocket requires ws or socket.io.
- **Sinatra** (Ruby) is a micro-framework. ERB ships with Ruby stdlib. Most features require gems.
- **Laravel** (PHP) is batteries-included with Eloquent ORM, Blade templates, queues (multiple drivers), Mix/Vite for asset compilation, and Artisan CLI. JWT requires a third-party package (tymon/jwt-auth).
- **Tina4** achieves zero external dependencies by implementing all features using Python stdlib only (asyncio, http.server, sqlite3, hashlib, hmac, json, re, etc.).

## What "built-in" means

A feature is marked "Yes" only if it ships with the core package install and requires no additional `pip install`, `npm install`, `gem install`, or `composer require`. Extensions, plugins, and community packages do not count.

Starlette itself does not generate OpenAPI docs. FastAPI (built on Starlette) does, but FastAPI is a separate package and does not count as "built-in" to Starlette.
