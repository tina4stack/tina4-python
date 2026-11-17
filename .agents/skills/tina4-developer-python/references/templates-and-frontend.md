# Templates & Frontend (Python)

## Frond Templates

Tina4 uses Frond, a Twig-like template engine. Templates go in `src/templates/`.

### Rendering

```python
@get("/")
async def home(request, response):
    return response.render("index.twig", {
        "title": "My App",
        "users": [u.to_dict() for u in User.all()],
    })
```

Need the rendered HTML as a string instead of a response? Instantiate the engine — `render` is
an instance method, not a static one:

```python
from tina4_python.frond import Frond
html = Frond(template_dir="src/templates").render("index.twig", {"title": "My App"})
```

### Globals (values available in every template)

Register a value every template can read with the CLASS-level `Frond.add_global`, once, at boot
(in `app.py`, before `run()`):

```python
from tina4_python.frond import Frond
Frond.add_global("app_name", "My App")      # class call: every engine gets it
```

Call it on the class, not on an instance. `add_global` works both ways, but an instance call
(`Frond(template_dir=...).add_global(...)`) changes only that one engine. A throwaway instance is
not the engine `response.render` uses, so the global never reaches your pages. Each engine copies
the class-level globals when it is created, and the `response.render` engine is created on the
first render, so register at boot, before any request.

```twig
<title>{{ app_name }}</title>
```

**A zero-argument function global is called for you (ADR-0085).** When you pass
`add_global` a plain function, lambda, or method that takes NO parameters, Frond wraps
it. A bare reference in a template then uses the RETURN value, and `name()` still
calls it. So this works as you expect:

```python
Frond.add_global("admin_only", lambda: access.admin_only())
```

```twig
{% if admin_only %} ...admin link... {% endif %}   {# uses the lambda's return value #}
{% if admin_only() %} ...admin link... {% endif %} {# same result #}
```

The function runs on every reference, at render time, so keep it cheap. Two cases are
NOT wrapped and are stored as-is:

- **A callable that takes parameters** (`lambda user: ...`). A bare `{% if name %}` sees
  the function object, which is always truthy. Call it with its arguments: `{{ name(user) }}`.
- **An object with `__call__`** that is not a plain function or method. Same rule: call it
  explicitly.

Older releases (before ADR-0085) stored every callable uncalled, so a bare `{% if g %}`
was always true. If the project pins an older tina4-python, pass a resolved value or
write `{% if g() %}`.

**Tests must register the global the way the app does.** A plain bool passed in the
render context (`render(tpl, {"admin_only": False})`) skips the `add_global` path, so a
test that passes a bool cannot catch a mistake in how the app registers the global.

### Basic Syntax

```twig
{# Output variables #}
<h1>{{ title }}</h1>
<p>{{ user.name }}</p>
<p>{{ user.email | upper }}</p>

{# Conditionals #}
{% if user.is_active %}
    <span class="badge-green">Active</span>
{% else %}
    <span class="badge-red">Inactive</span>
{% endif %}

{# Loops #}
{% for user in users %}
    <div>{{ loop.index }}. {{ user.name }}</div>
{% else %}
    <p>No users found.</p>
{% endfor %}

{# Template inheritance #}
{% extends "base.twig" %}
{% block content %}
    <h1>Page Title</h1>
{% endblock %}
```

### Useful Filters

```twig
{{ name | upper }}                 → UPPERCASE
{{ name | lower }}                 → lowercase
{{ name | capitalize }}            → First letter cap
{{ text | truncate(100) }}         → Truncate
{{ list | join(", ") }}            → Join list
{{ value | default("N/A") }}       → Default if null/empty
{{ html | raw }}                   → No auto-escaping
{{ price | number_format(2) }}     → 1,234.56
{{ date | date("%Y-%m-%d") }}      → Formatted date
{{ text | slug }}                  → url-friendly-slug
```

Other built-ins include `title`, `trim`, `length`, `reverse`, `sort`, `first`, `last`, `split`,
`replace`, `nl2br`, `round`, `json_encode`, `to_json`, `keys`, `values`, `merge`, `slice`,
`escape`. All filter names are snake_case.

> There is **no** `timeago` filter and **no** `trans` filter. For relative times, format in the
> route/helper and pass a string. For translation, use the `I18n` class in Python (see
> `auth-and-services.md`) and pass translated strings into the template context.

### Includes and Macros

```twig
{# Include a partial #}
{% include "partials/header.twig" %}
{% include "partials/card.twig" with {"title": "Hello"} %}

{# Reusable macros #}
{% macro input(name, value, type) %}
    <input type="{{ type | default('text') }}" name="{{ name }}" value="{{ value }}">
{% endmacro %}

{% import "macros/forms.twig" as forms %}
{{ forms.input("email", "", "email") }}
```

> There is **no** `{% query %}` inline-SQL tag. Do data access in the route or a helper class in
> `src/app/` and pass the results into the template context — never query the database from a
> template.

### Live Blocks (server-rendered, self-refreshing)

A live block renders on the server for first paint, then re-fetches its own HTML and swaps it in
place. Pick a transport: `poll N` (every N seconds), `sse`, or `ws "path"`. `frond.js` (already
loaded) wires the marker and morphs the result, so a focused input survives the swap.

```twig
{# Poll every 5 seconds #}
{% live "cart" poll 5 %}
    <strong>{{ count }}</strong> items
{% endlive %}

{# WebSocket — the server pushes updates #}
{% live "chat" ws "/ws/chat" %}
    {% for msg in messages %}<div>{{ msg.user }}: {{ msg.text }}</div>{% endfor %}
{% endlive %}
```

Supply the data with a provider registered by name. It runs on every refresh with the live
request, so auth re-applies each time (an unauthenticated caller never sees another user's data):

```python
from tina4_python.frond import live_source, push_live

@live_source("cart")
def cart_data(request):
    return {"count": cart_count(request), "items": cart_items(request)}
```

The provider feeds the always-on `GET /__frond/live/{name}` endpoint — the block name is the
route. For a `ws` block, push a fresh render the instant data changes with
`push_live("cart", {...})`. Nested live blocks are rejected.

### Cache Blocks

Wrap expensive-to-render markup in a `{% cache %}` block — the rendered fragment is stored and
reused for the given number of seconds:

```twig
{% cache "sidebar" 300 %}
    {# Rendered once, then served from cache for 300 seconds #}
    <ul>
    {% for post in popular_posts %}
        <li><a href="/posts/{{ post.id }}">{{ post.title }}</a></li>
    {% endfor %}
    </ul>
{% endcache %}
```

Provide the data (`popular_posts` here) from the route context as usual — a cache block caches
rendered output, it does not run queries.

## frond.js — Frontend Helper

A small JavaScript helper that ships with the framework. Include it:

```html
<script src="/js/frond.js"></script>
```

It defines ONE global, `window.frond` (lower case). Its members are `request`, `load`, `post`,
`inject`, `form` (`collect` / `submit` / `show`), `ws`, `sse`, `live`, `cookie`, `message`,
`popup`, `report`, `graphql`, and the `token` property. Nothing else exists: there is no
`Frond` global, no `saveForm` / `loadPage` / `sendRequest`, and no notify, modal, confirm, or
CRUD-table helper. If you think you need one, read `tina4_python/public/js/frond.js` first.

### HTTP Requests

Callback style (it uses `XMLHttpRequest`, not promises):

```javascript
frond.request("/api/users", {
    method: "GET",                                  // default GET
    onSuccess: (data, status, xhr) => render(data), // JSON is parsed for you
    onError: (status, xhr) => frond.message("Load failed", "danger"),
});

// An object body is sent as JSON; a FormData body is sent as-is.
frond.request("/api/users", { method: "POST", body: { name: "Alice" }, onSuccess: done });
frond.request("/api/users/1", { method: "PUT", body: { name: "Alice Smith" }, onSuccess: done });
frond.request("/api/users/1", { method: "DELETE", onSuccess: done });
```

### Load and post HTML fragments

```javascript
frond.load("/users/partial", "user-list");            // GET, inject the HTML into #user-list
frond.post("/users/search", { q: "ali" }, "results"); // POST, inject the response into #results
```

The target is an element id without `#`. Both default to `content`. If the JSON response has a
`message` key, `post` injects that.

### Forms

```javascript
// Collect every input / select / textarea inside #user-form (files and checkboxes too)
// and POST it as FormData. The response goes into #message by default.
frond.form.submit("user-form", "/api/users", "message");

const data = frond.form.collect("user-form");       // just build the FormData
frond.form.show("edit", "/users/1/form", "form");   // GET a form fragment into #form
```

The form id is passed WITHOUT `#`. A `formToken` field rendered by `{{ form_token() }}` is sent
as the server rendered it.

### Messages and popups

```javascript
frond.message("Saved!", "success");   // writes an alert into the #message element
frond.popup("/report/1", "Report", 800, 600);
```

### Authentication

```javascript
frond.token = jwt;   // kept in memory only, never in storage
// From now on, same-origin requests send Authorization: Bearer <jwt>. Cross-origin never.
```

frond.js also takes a `FreshToken` response header from your own origin as the new token. It
sends no token until one is set or received.

### WebSocket

```javascript
const ws = frond.ws("/ws/chat", { reconnect: true });   // auto-reconnect with backoff
ws.on("message", (data) => console.log(data));          // JSON is parsed for you
ws.on("open", () => ws.send({ type: "message", text: "Hello" }));
```

`frond.ws` does NOT send the bearer token. For a secured socket pass it as a subprotocol:
`frond.ws("/ws/chat/1", { protocols: ["bearer", frond.token] })`. The server also accepts
`?token=<jwt>`, but a query string ends up in access logs, so prefer the subprotocol.
