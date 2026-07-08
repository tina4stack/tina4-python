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

A lightweight (<10KB) JavaScript library that ships with the framework. Include it:

```html
<script src="/js/frond.js"></script>
```

### HTTP Requests

```javascript
const users = await Frond.get("/api/users");
await Frond.post("/api/users", { name: "Alice" });
await Frond.put("/api/users/1", { name: "Alice Smith" });
await Frond.delete("/api/users/1");
```

### Forms

```javascript
Frond.submitForm("#user-form", "/api/users");
Frond.fillForm("#user-form", { name: "Alice", email: "alice@example.com" });
Frond.resetForm("#user-form");
```

### CRUD Table (auto-generated)

```javascript
Frond.crud({
    target: "#users-table",
    endpoint: "/api/users",
    columns: ["id", "name", "email"],
    searchable: true,
    paginated: true
});
```

### Notifications and Modals

```javascript
Frond.notify("Saved!", "success");
Frond.notify("Error!", "error");
Frond.confirm("Delete this item?").then(ok => { if (ok) { /* delete */ } });
Frond.modal({ title: "Edit User", body: "<form>...</form>" });
```

### Authentication

```javascript
Frond.config({ auth: true });
Frond.setToken(jwt);        // stored in memory
// All subsequent requests auto-attach the Bearer token
```

### WebSocket

```javascript
const ws = Frond.ws("/ws/chat", {
    reconnect: true,
    onMessage: (data) => console.log(data),
});
ws.send({ type: "message", text: "Hello" });
```
