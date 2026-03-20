# Localization (i18n)

Tina4 supports internationalization via JSON translation files. The `I18n` class loads locale files, handles locale switching, fallback to default language, and placeholder interpolation.

## Setup

Create JSON translation files in `src/locales/`:

```json
// src/locales/en.json
{
    "greeting": "Hello",
    "welcome": "Welcome, {name}!",
    "items_count": "You have {count} items.",
    "nav.home": "Home",
    "nav.about": "About",
    "nav.contact": "Contact"
}
```

```json
// src/locales/fr.json
{
    "greeting": "Bonjour",
    "welcome": "Bienvenue, {name} !",
    "items_count": "Vous avez {count} articles.",
    "nav.home": "Accueil",
    "nav.about": "A propos",
    "nav.contact": "Contact"
}
```

```json
// src/locales/es.json
{
    "greeting": "Hola",
    "welcome": "Bienvenido, {name}!",
    "items_count": "Tienes {count} articulos."
}
```

## Basic Usage

```python
from tina4_python.i18n import I18n

i18n = I18n(locale_dir="src/locales", default_locale="en")

# Translate a key
print(i18n.t("greeting"))  # "Hello"

# With placeholder interpolation
print(i18n.t("welcome", name="Alice"))  # "Welcome, Alice!"
print(i18n.t("items_count", count=5))   # "You have 5 items."
```

## Switching Locale

```python
i18n.locale = "fr"
print(i18n.t("greeting"))              # "Bonjour"
print(i18n.t("welcome", name="Alice")) # "Bienvenue, Alice !"

i18n.locale = "es"
print(i18n.t("greeting"))              # "Hola"
```

## Fallback Behavior

If a key is missing in the current locale, the default locale is checked. If missing there too, the key itself is returned.

```python
i18n = I18n(default_locale="en")
i18n.locale = "es"

# Exists in Spanish
print(i18n.t("greeting"))    # "Hola"

# Missing in Spanish, falls back to English
print(i18n.t("nav.home"))    # "Home"

# Missing everywhere — returns the key
print(i18n.t("unknown.key")) # "unknown.key"
```

## Available Locales

```python
locales = i18n.available_locales()
print(locales)  # ["en", "es", "fr"]
```

## Environment Configuration

```bash
# .env
TINA4_LANGUAGE=en
TINA4_LOCALE_DIR=src/locales
```

```python
# Reads from environment
i18n = I18n()
```

## Using in Routes

```python
from tina4_python.core.router import get
from tina4_python.i18n import I18n

i18n = I18n()

@get("/api/greeting")
async def greeting(request, response):
    # Switch locale based on Accept-Language header or query param
    lang = request.params.get("lang", "en")
    i18n.locale = lang
    return response({"message": i18n.t("greeting")})
```

## Using in Templates

Make the translation function available in templates.

```python
# app.py
from tina4_python.frond import Frond
from tina4_python.i18n import I18n

i18n = I18n()
engine = Frond()
engine.add_global("t", i18n.t)
```

```twig
{# In a template #}
<h1>{{ t("greeting") }}</h1>
<p>{{ t("welcome", name=user.name) }}</p>

<nav>
    <a href="/">{{ t("nav.home") }}</a>
    <a href="/about">{{ t("nav.about") }}</a>
    <a href="/contact">{{ t("nav.contact") }}</a>
</nav>
```

## Per-Request Locale

Set locale per request using middleware.

```python
class LocaleMiddleware:
    @staticmethod
    def before_set_locale(request, response):
        lang = request.headers.get("accept-language", "en")[:2]
        if lang in i18n.available_locales():
            i18n.locale = lang
        return request, response
```

## Translation File Format

Use flat keys or dot-notation for namespacing:

```json
{
    "auth.login": "Log In",
    "auth.logout": "Log Out",
    "auth.register": "Create Account",
    "errors.not_found": "Page not found",
    "errors.server": "Internal server error"
}
```

## Tips

- Use dot-notation keys (`nav.home`, `auth.login`) to organize translations by section.
- Always provide an English (`en.json`) file as the fallback.
- Use `{placeholder}` syntax for dynamic values -- never concatenate strings.
- Set the locale early in the request lifecycle via middleware.
- Keep translation files in version control so translators can contribute via pull requests.
