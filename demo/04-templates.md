# Templates (Frond Engine)

Tina4 v3 includes Frond, a zero-dependency Twig-compatible template engine. Templates live in `src/templates/` and use `{{ }}` for output, `{% %}` for logic, and `{# #}` for comments. Frond supports inheritance, includes, macros, filters, tests, and fragment caching.

## Variables

```twig
{# Output a variable #}
<h1>{{ title }}</h1>
<p>Welcome, {{ user.name }}!</p>

{# Default value for undefined/None #}
<p>{{ subtitle|default("No subtitle") }}</p>

{# String concatenation uses ~ operator #}
<p>{{ "Hello " ~ name ~ "!" }}</p>
```

## Filters

Filters transform output. Chain them with `|`.

```twig
{{ name|upper }}                  {# "ALICE" #}
{{ name|lower }}                  {# "alice" #}
{{ name|capitalize }}             {# "Alice" #}
{{ name|title }}                  {# "Alice Johnson" #}
{{ text|trim }}                   {# Strip whitespace #}
{{ items|length }}                {# Count #}
{{ items|join(", ") }}            {# "a, b, c" #}
{{ items|first }}                 {# First element #}
{{ items|last }}                  {# Last element #}
{{ items|sort }}                  {# Sorted list #}
{{ items|reverse }}               {# Reversed list #}
{{ items|unique }}                {# Deduplicated #}
{{ items|slice(0, 3) }}           {# First 3 items #}
{{ dict|keys }}                   {# Dict keys #}
{{ list1|merge(list2) }}          {# Merge lists/dicts #}
{{ number|abs }}                  {# Absolute value #}
{{ number|round(2) }}             {# Round to 2 decimals #}
{{ price|number_format(2) }}      {# "1,234.56" #}
{{ html_content|e }}              {# HTML escape #}
{{ html_content|safe }}           {# Output unescaped HTML #}
{{ html_content|striptags }}      {# Remove HTML tags #}
{{ text|nl2br }}                  {# Newlines to <br> #}
{{ text|replace("old", "new") }}  {# String replace #}
{{ csv|split(",") }}              {# Split to list #}
{{ data|json_encode }}            {# To JSON string #}
{{ text|base64encode }}           {# Base64 encode #}
{{ encoded|base64decode }}        {# Base64 decode #}
{{ url|url_encode }}              {# URL encode #}
{{ "user_email"|nice_label }}     {# "User Email" #}
{{ "%.2f"|format(price) }}        {# Number format #}
{{ items|batch(3) }}              {# Chunk into groups of 3 #}
```

## Conditionals

```twig
{% if user.role == "admin" %}
    <span class="badge">Admin</span>
{% elif user.role == "editor" %}
    <span class="badge">Editor</span>
{% else %}
    <span class="badge">User</span>
{% endif %}

{# Inline ternary #}
<p>{{ "s" if count != 1 else "" }}</p>
```

Note: use `elif`, not `elseif`. There is no `?:` ternary operator.

## Loops

```twig
{% for user in users %}
    <tr>
        <td>{{ loop.index }}</td>    {# 1-based index #}
        <td>{{ user.name }}</td>
        <td>{{ user.email }}</td>
    </tr>
{% else %}
    <tr><td colspan="3">No users found.</td></tr>
{% endfor %}
```

### Loop Variables

| Variable | Description |
|----------|-------------|
| `loop.index` | Current iteration (1-based) |
| `loop.index0` | Current iteration (0-based) |
| `loop.first` | True on first iteration |
| `loop.last` | True on last iteration |
| `loop.length` | Total number of items |

## Template Inheritance

### Base template

```twig
{# src/templates/base.twig #}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{% block title %}My App{% endblock %}</title>
    <link rel="stylesheet" href="/css/tina4.min.css">
    {% block stylesheets %}{% endblock %}
</head>
<body>
    {% block nav %}{% include "partials/nav.twig" ignore missing %}{% endblock %}
    <main class="container mt-4">
        {% block content %}{% endblock %}
    </main>
    {% block javascripts %}
    <script src="/js/tina4helper.js"></script>
    {% endblock %}
</body>
</html>
```

### Child template

```twig
{# src/templates/pages/dashboard.twig #}
{% extends "base.twig" %}

{% block title %}Dashboard{% endblock %}

{% block content %}
<h1>{{ title }}</h1>
<div class="row">
    {% for stat in stats %}
        {% include "partials/stat-card.twig" %}
    {% endfor %}
</div>
{% endblock %}
```

## Includes

```twig
{# Include a partial — inherits parent context automatically #}
{% include "partials/user-card.twig" %}

{# Ignore if file is missing #}
{% include "partials/optional.twig" ignore missing %}
```

## Macros

Macros are reusable template functions. They do NOT inherit parent context -- pass variables explicitly.

```twig
{# src/templates/macros/forms.twig #}
{% macro input(name, label, type="text", value="") %}
<div class="form-group">
    <label for="{{ name }}">{{ label }}</label>
    <input type="{{ type }}" name="{{ name }}" id="{{ name }}"
           value="{{ value }}" class="form-control"
           placeholder="{{ label }}">
</div>
{% endmacro %}
```

```twig
{# Use in a page #}
{% from "macros/forms.twig" import input %}

<form id="userForm">
    {{ input("name", "Full Name") }}
    {{ input("email", "Email Address", "email") }}
    {{ input("age", "Age", "number") }}
</form>
```

## Set Variables

```twig
{% set greeting = "Hello, " ~ user.name ~ "!" %}
<p>{{ greeting }}</p>

{% set colors = ["red", "green", "blue"] %}
```

## Tests

```twig
{% if user is defined %}...{% endif %}
{% if value is none %}...{% endif %}
{% if items is empty %}...{% endif %}
{% if count is even %}...{% endif %}
{% if count is odd %}...{% endif %}
{% if items is iterable %}...{% endif %}
{% if name is string %}...{% endif %}
{% if age is number %}...{% endif %}
{% if count is divisible by(3) %}...{% endif %}
```

## Whitespace Control

Add `-` to trim whitespace before/after a tag.

```twig
{%- if condition -%}
    No surrounding whitespace
{%- endif -%}

{{- variable -}}
```

## Comments

```twig
{# This is a comment — it does not appear in the output #}
```

## Fragment Caching

Cache expensive template blocks with a TTL.

```twig
{% cache "sidebar-stats" 300 %}
    {# This block is cached for 300 seconds #}
    <div class="sidebar">
        {% for stat in expensive_query() %}
            <p>{{ stat }}</p>
        {% endfor %}
    </div>
{% endcache %}
```

## Custom Filters and Globals

Register in `app.py` before `run()`.

```python
from tina4_python.frond import Frond

engine = Frond()

# Custom filter
engine.add_filter("money", lambda v: f"{float(v or 0):,.2f}")
# Usage: {{ price|money }}

# Custom global
engine.add_global("APP_NAME", "My Application")
# Usage: {{ APP_NAME }}

# Custom test
engine.add_test("positive", lambda x: x > 0)
# Usage: {% if balance is positive %}
```

## Rendering from a Route

```python
from tina4_python.core.router import get

@get("/dashboard")
async def dashboard(request, response):
    return response.render("pages/dashboard.twig", {
        "title": "Dashboard",
        "stats": [{"label": "Users", "value": 150}],
    })
```

## Tips

- Every page should extend `base.twig`. Never create standalone HTML files.
- Put reusable UI components in `src/templates/partials/`.
- Use `{{ var|e }}` (no arguments) for HTML escaping -- `|e('js')` does not exist in Frond.
- Use `{{ var|default('fallback') }}` for safe access to possibly-undefined variables.
- The `|safe` filter outputs unescaped HTML -- use it only for trusted content.
