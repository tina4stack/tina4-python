# Frond — Tina4's Template Engine

Zero-dependency, Twig-like template engine built from scratch. Part of the Tina4 v3 Python framework.

## Quick Start

```python
from tina4_python.frond import Frond

engine = Frond(template_dir="src/templates")

# Render from file
html = engine.render("page.html", {"name": "World"})

# Render from string
html = engine.render_string("Hello {{ name }}", {"name": "World"})
```

---

## Variables

Output variables with double curly braces. All output is **auto-escaped** (HTML-safe) by default.

```twig
{{ name }}                     {# Simple variable #}
{{ user.name }}                {# Dotted access #}
{{ items[0] }}                 {# Array access #}
{{ user["email"] }}            {# Dict bracket access #}
{{ missing }}                  {# Missing variables render as empty string #}
```

### String Concatenation

Use the `~` operator:

```twig
{{ "Hello " ~ name ~ "!" }}   {# "Hello World!" #}
```

### Ternary Operator

```twig
{{ active ? "yes" : "no" }}
```

### Null Coalescing

```twig
{{ name ?? "default" }}        {# Use "default" if name is None #}
```

---

## Filters

Filters transform output. Chain them with `|`:

```twig
{{ name | upper }}             {# "ALICE" #}
{{ text | trim | upper }}      {# Chained: trim then uppercase #}
{{ price | number_format(2) }} {# "1,234.50" #}
```

### Text / String Filters

| Filter | Description | Example |
|--------|-------------|---------|
| `upper` | Uppercase | `{{ "hi" \| upper }}` -> `HI` |
| `lower` | Lowercase | `{{ "HI" \| lower }}` -> `hi` |
| `capitalize` | First letter uppercase | `{{ "alice" \| capitalize }}` -> `Alice` |
| `title` | Title Case | `{{ "hello world" \| title }}` -> `Hello World` |
| `trim` | Strip whitespace | `{{ "  hi  " \| trim }}` -> `hi` |
| `ltrim` | Strip left whitespace | |
| `rtrim` | Strip right whitespace | |
| `replace(from, to)` | Replace substring | `{{ "hello world" \| replace("world", "frond") }}` |
| `striptags` | Remove HTML tags | `{{ "<b>bold</b>" \| striptags }}` -> `bold` |
| `nl2br` | Newlines to `<br>` | `{{ text \| nl2br \| raw }}` |
| `slug` | URL-safe slug | `{{ "Hello World!" \| slug }}` -> `hello-world` |
| `truncate(n)` | Truncate to N chars + "..." | `{{ text \| truncate(5) }}` -> `Hello...` |
| `wordwrap(width)` | Wrap text at word boundaries | Default width: 75 |

### Encoding Filters

| Filter | Description |
|--------|-------------|
| `escape` / `e` | HTML-escape (default behavior) |
| `raw` / `safe` | Disable auto-escaping |
| `json_encode` | Serialize to JSON |
| `json_decode` | Parse JSON string |
| `base64_encode` | Base64 encode |
| `base64_decode` | Base64 decode |
| `url_encode` | URL-encode |
| `format` | Printf-style formatting |

### Hash Filters

| Filter | Description |
|--------|-------------|
| `md5` | MD5 hash |
| `sha256` | SHA-256 hash |

### Number Filters

| Filter | Description | Example |
|--------|-------------|---------|
| `abs` | Absolute value | `{{ -5 \| abs }}` -> `5` |
| `round(n)` | Round to N decimals | `{{ 3.14159 \| round(2) }}` -> `3.14` |
| `int` | Convert to integer | |
| `float` | Convert to float | |
| `number_format(n)` | Format with thousands separator | `{{ 1234.5 \| number_format(2) }}` -> `1,234.50` |

### Date Filter

```twig
{{ created_at | date }}                {# Default: 2024-01-15 #}
{{ created_at | date("%d/%m/%Y") }}    {# Custom format: 15/01/2024 #}
```

Accepts datetime objects or ISO format strings.

### Array / List Filters

| Filter | Description | Example |
|--------|-------------|---------|
| `length` | Count items | `{{ items \| length }}` -> `3` |
| `first` | First element | `{{ [1,2,3] \| first }}` -> `1` |
| `last` | Last element | `{{ [1,2,3] \| last }}` -> `3` |
| `reverse` | Reverse order | |
| `sort` | Sort ascending | |
| `shuffle` | Randomize order | |
| `join(sep)` | Join with separator | `{{ items \| join(", ") }}` -> `a, b, c` |
| `split(sep)` | Split string to array | |
| `unique` | Remove duplicates | |
| `slice(start, end)` | Extract sub-array | |
| `batch(size)` | Group into batches | |
| `map(key)` | Extract property from each item | |
| `filter` | Remove falsy items | |
| `column(key)` | Extract column from list of dicts | |

### Dictionary Filters

| Filter | Description |
|--------|-------------|
| `keys` | Get dictionary keys |
| `values` | Get dictionary values |
| `merge(dict)` | Merge two dictionaries |

### Utility Filters

| Filter | Description |
|--------|-------------|
| `default(fallback)` | Use fallback if value is None/empty |
| `dump` | Python repr() — useful for debugging |
| `string` | Convert to string |

### Custom Filters

```python
engine.add_filter("double", lambda v: str(v) * 2)
engine.add_filter("money", lambda v: f"${float(v):,.2f}")
```

```twig
{{ "ha" | double }}     {# "haha" #}
{{ 1234.5 | money }}    {# "$1,234.50" #}
```

---

## Control Structures

### If / Elseif / Else

```twig
{% if user.active %}
    Welcome, {{ user.name }}!
{% elseif user.pending %}
    Your account is pending.
{% else %}
    Please sign up.
{% endif %}
```

Both `elseif` and `elif` are supported.

#### Comparison Operators

```twig
{% if x == 1 %}...{% endif %}
{% if x != 1 %}...{% endif %}
{% if x > 5 %}...{% endif %}
{% if x < 5 %}...{% endif %}
{% if x >= 5 %}...{% endif %}
{% if x <= 5 %}...{% endif %}
```

#### Logical Operators

```twig
{% if a and b %}...{% endif %}
{% if a or b %}...{% endif %}
{% if not hidden %}...{% endif %}
```

#### Membership Test

```twig
{% if "admin" in roles %}...{% endif %}
{% if "banned" not in roles %}...{% endif %}
```

#### Tests

Use `is` to test values:

```twig
{% if x is defined %}       {# Variable exists in context #}
{% if items is empty %}      {# Empty list/string/dict #}
{% if x is null %}           {# None/null #}
{% if x is none %}           {# Same as null #}
{% if n is even %}           {# Divisible by 2 #}
{% if n is odd %}            {# Not divisible by 2 #}
{% if val is string %}       {# Is a string #}
{% if val is number %}       {# Is int or float #}
{% if val is boolean %}      {# Is bool #}
{% if items is iterable %}   {# Is list/tuple/dict #}
{% if n is divisible by(3) %} {# Custom divisibility #}
```

Custom tests:

```python
engine.add_test("positive", lambda x: x > 0)
```

```twig
{% if balance is positive %}...{% endif %}
```

### For Loops

```twig
{% for item in items %}
    {{ item }}
{% endfor %}
```

#### Empty Fallback

```twig
{% for item in items %}
    {{ item }}
{% else %}
    No items found.
{% endfor %}
```

#### Key-Value Iteration (Dictionaries)

```twig
{% for key, value in data %}
    {{ key }}: {{ value }}
{% endfor %}
```

#### Loop Variable

Inside every for loop, a `loop` object is available:

| Variable | Description |
|----------|-------------|
| `loop.index` | Current iteration (1-based) |
| `loop.index0` | Current iteration (0-based) |
| `loop.first` | True on first iteration |
| `loop.last` | True on last iteration |
| `loop.length` | Total number of items |
| `loop.revindex` | Iterations remaining (1-based) |
| `loop.revindex0` | Iterations remaining (0-based) |
| `loop.even` | True on even iterations |
| `loop.odd` | True on odd iterations |

```twig
{% for item in items %}
    {% if loop.first %}<ul>{% endif %}
    <li class="{{ loop.even ? 'even' : 'odd' }}">
        {{ loop.index }}. {{ item }}
    </li>
    {% if loop.last %}</ul>{% endif %}
{% endfor %}
```

#### Nested Loops

```twig
{% for group in groups %}
    {% for item in group %}
        {{ item }}
    {% endfor %}
{% endfor %}
```

### Set (Variable Assignment)

```twig
{% set greeting = "Hello" %}
{% set full_name = first ~ " " ~ last %}
{{ greeting }}, {{ full_name }}!
```

---

## Template Inheritance

The most powerful feature for building layouts.

### Base Template (`base.html`)

```twig
<!DOCTYPE html>
<html>
<head>
    <title>{% block title %}Default Title{% endblock %}</title>
</head>
<body>
    <nav>{% block nav %}{% endblock %}</nav>
    <main>{% block content %}{% endblock %}</main>
    <footer>{% block footer %}Copyright 2024{% endblock %}</footer>
</body>
</html>
```

### Child Template (`page.html`)

```twig
{% extends "base.html" %}

{% block title %}My Page{% endblock %}

{% block content %}
    <h1>Welcome</h1>
    <p>This replaces the content block.</p>
{% endblock %}
```

Blocks not overridden in the child keep the parent's default content.

---

## Include

Include another template. The included template inherits the current context.

```twig
{% include "partials/header.html" %}
{% include "partials/card.html" with {"title": "Hello"} %}
```

### Ignore Missing

Silently skip if the file doesn't exist:

```twig
{% include "optional.html" ignore missing %}
```

---

## Macros

Define reusable template functions:

```twig
{% macro button(label, type) %}
    <button class="btn btn-{{ type }}">{{ label }}</button>
{% endmacro %}

{{ button("Save", "primary") | raw }}
{{ button("Cancel", "secondary") | raw }}
```

Macros don't inherit parent context — pass everything explicitly via parameters.

---

## Comments

```twig
{# This comment won't appear in output #}

{#
    Multi-line comments
    are also supported
#}
```

---

## Whitespace Control

Add `-` to trim whitespace before/after tags:

```twig
<p>
    {{- name -}}        {# Trims whitespace on both sides #}
</p>

{%- if true -%}
    no surrounding whitespace
{%- endif -%}
```

- `{{-` / `{%-` strips whitespace **before** the tag
- `-}}` / `-%}` strips whitespace **after** the tag

---

## Auto-Escaping

All variable output is HTML-escaped by default to prevent XSS:

```twig
{{ user_input }}             {# "<script>" becomes "&lt;script&gt;" #}
{{ trusted_html | raw }}     {# Output as-is, no escaping #}
{{ trusted_html | safe }}    {# Same as raw #}
```

---

## Global Variables

Register variables available in every template:

```python
engine.add_global("app_name", "My App")
engine.add_global("version", "1.0.0")
engine.add_global("now", lambda: datetime.now())
```

```twig
{{ app_name }} v{{ version }}
```

Template data overrides globals with the same name.

---

## API Reference

### `Frond(template_dir: str = "src/templates")`

Create a new engine instance.

### `engine.render(template: str, data: dict = None) -> str`

Load and render a template file relative to `template_dir`.

### `engine.render_string(source: str, data: dict = None) -> str`

Render a template string directly.

### `engine.add_filter(name: str, fn: callable)`

Register a custom filter.

### `engine.add_global(name: str, value)`

Register a global variable or function.

### `engine.add_test(name: str, fn: callable)`

Register a custom test for use with `is`.

---

## Differences from Twig/Jinja2

| Feature | Frond | Twig | Jinja2 |
|---------|-------|------|--------|
| `elseif` keyword | Yes | Yes | No (`elif`) |
| `elif` keyword | Yes | No | Yes |
| `raw` filter | Yes | Yes | No (`safe`) |
| `safe` filter | Yes | No | Yes |
| Ternary `? :` | Yes | Yes | No (use inline if) |
| `~` concatenation | Yes | Yes | Yes |
| `??` null coalescing | Yes | Yes | No |
| Auto-escaping | Yes | Yes | Yes |
| Zero dependencies | Yes | No (PHP) | No (markupsafe) |

Frond accepts both Twig and Jinja2 conventions where possible — `elseif`/`elif`, `raw`/`safe` — so templates are portable.
