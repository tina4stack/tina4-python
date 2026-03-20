# SCSS Compiler

Tina4 includes a zero-dependency SCSS-to-CSS compiler. Place `.scss` files in `src/scss/` and they auto-compile to `src/public/css/` on startup. In development mode, SCSS changes trigger CSS-only hot-reload (no full page refresh).

## File Structure

```
src/scss/
  _variables.scss     # Partial (imported, not compiled standalone)
  _mixins.scss        # Partial
  default.scss        # Main file → compiles to src/public/css/default.css
  admin.scss          # → compiles to src/public/css/admin.css
```

Files starting with `_` are partials -- they are imported by other files but not compiled standalone.

## Variables

```scss
// src/scss/_variables.scss
$primary: #3498db;
$secondary: #2ecc71;
$danger: #e74c3c;
$font-stack: 'Segoe UI', Tahoma, sans-serif;
$spacing: 1rem;
$border-radius: 0.5rem;
```

```scss
// src/scss/default.scss
@import "variables";

body {
    font-family: $font-stack;
    color: #333;
}

.btn-primary {
    background: $primary;
    padding: $spacing;
    border-radius: $border-radius;
}
```

## Nesting

```scss
.card {
    border: 1px solid #ddd;
    border-radius: $border-radius;

    .card-header {
        padding: $spacing;
        background: #f8f9fa;
        border-bottom: 1px solid #ddd;
    }

    .card-body {
        padding: $spacing;
    }

    // & references the parent selector
    &:hover {
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    }

    &.card-primary {
        border-color: $primary;
    }
}
```

Compiles to:

```css
.card { border: 1px solid #ddd; border-radius: 0.5rem; }
.card .card-header { padding: 1rem; background: #f8f9fa; border-bottom: 1px solid #ddd; }
.card .card-body { padding: 1rem; }
.card:hover { box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1); }
.card.card-primary { border-color: #3498db; }
```

## Mixins

```scss
// src/scss/_mixins.scss
@mixin flex-center {
    display: flex;
    align-items: center;
    justify-content: center;
}

@mixin respond-to($breakpoint) {
    @media (max-width: $breakpoint) {
        @content;
    }
}

@mixin button-variant($bg, $color: white) {
    background-color: $bg;
    color: $color;
    border: none;
    padding: 0.5rem 1rem;
    border-radius: $border-radius;
    cursor: pointer;

    &:hover {
        background-color: darken($bg, 10%);
    }
}
```

```scss
@import "variables";
@import "mixins";

.hero {
    @include flex-center;
    min-height: 60vh;
}

.btn-primary {
    @include button-variant($primary);
}

.btn-danger {
    @include button-variant($danger);
}

.sidebar {
    width: 250px;

    @include respond-to(768px) {
        width: 100%;
    }
}
```

## @extend

```scss
%button-base {
    padding: 0.5rem 1rem;
    border-radius: $border-radius;
    border: none;
    cursor: pointer;
    font-size: 1rem;
}

.btn {
    @extend %button-base;
}

.btn-sm {
    @extend %button-base;
    padding: 0.25rem 0.5rem;
    font-size: 0.875rem;
}
```

## Math in Values

```scss
$base-size: 16px;

.container {
    max-width: $base-size * 75;    // 1200px
    padding: $base-size / 2;       // 8px
    margin: $base-size + 4px;      // 20px
}
```

## Color Functions

```scss
.button {
    background: $primary;

    &:hover {
        background: darken($primary, 10%);   // 10% darker
    }

    &:active {
        background: lighten($primary, 10%);  // 10% lighter
    }

    &.transparent {
        background: rgba($primary, 0.5);     // 50% opacity
    }
}
```

## @media Nesting

```scss
.grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: $spacing;

    @media (max-width: 768px) {
        grid-template-columns: 1fr;
    }
}
```

## Nested Properties

```scss
.heading {
    font: {
        size: 2rem;
        weight: bold;
        family: $font-stack;
    }
}
// Compiles to: .heading { font-size: 2rem; font-weight: bold; font-family: ... }
```

## Programmatic Usage

```python
from tina4_python.scss import compile_scss, compile_string

# Compile all .scss files in a directory
css = compile_scss("src/scss", "src/public/css/default.css")

# Compile with minification
css = compile_scss("src/scss", "src/public/css/default.min.css", minify=True)

# Compile a string
css = compile_string("""
$color: #3498db;
.box {
    background: $color;
    &:hover { background: darken($color, 10%); }
}
""")
```

## Linking in Templates

```twig
{# src/templates/base.twig #}
<link rel="stylesheet" href="/css/tina4.min.css">
<link rel="stylesheet" href="/css/default.css">
```

## Tips

- Use partials (`_variables.scss`, `_mixins.scss`) for shared values and keep them imported.
- Never hardcode hex colors in templates -- always use SCSS variables.
- One SCSS file per page or component for maintainability.
- In dev mode (`TINA4_DEBUG_LEVEL=ALL`), SCSS changes trigger CSS-only hot-reload.
- No inline styles on any HTML element -- always use CSS classes.
