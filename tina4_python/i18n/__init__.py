# Tina4 i18n — Internationalization and localization, zero dependencies.
"""
Simple key-based translations loaded from JSON files.

    from tina4_python.i18n import I18n

    i18n = I18n(locale_dir="src/locales", default_locale="en")
    _ = i18n.t
    _("greeting")  # "Hello" or "Bonjour" depending on locale
"""
import os
import json
from pathlib import Path


class I18n:
    """Internationalization support with JSON translation files.

    Locale files: src/locales/en.json, src/locales/fr.json, etc.
    Format: {"key": "translated value", "nested.key": "value"}
    """

    def __init__(self, locale_dir: str = None, default_locale: str = None):
        self._locale_dir = Path(
            locale_dir or os.environ.get("TINA4_LOCALE_DIR", "src/locales")
        )
        self._default_locale = default_locale or os.environ.get(
            "TINA4_LOCALE", "en"
        )
        self._current_locale = self._default_locale
        self._translations: dict[str, dict] = {}
        self._load_locale(self._default_locale)

    @property
    def locale(self) -> str:
        return self._current_locale

    @locale.setter
    def locale(self, value: str):
        self._current_locale = value
        self._load_locale(value)

    def t(self, key: str, **kwargs) -> str:
        """Translate a key. Supports {placeholder} interpolation.

        Falls back to default locale, then returns the key itself.
        """
        # Try current locale
        translations = self._translations.get(self._current_locale, {})
        value = self._resolve(key, translations)

        # Fallback to default locale
        if value is None and self._current_locale != self._default_locale:
            fallback = self._translations.get(self._default_locale, {})
            value = self._resolve(key, fallback)

        # Fallback to key itself
        if value is None:
            value = key

        # Interpolate
        if kwargs:
            try:
                value = value.format(**kwargs)
            except (KeyError, IndexError):
                pass

        return value

    def available_locales(self) -> list[str]:
        """List available locale codes."""
        if not self._locale_dir.is_dir():
            return [self._default_locale]
        locales = set()
        for ext in ("*.json", "*.yml", "*.yaml"):
            for f in self._locale_dir.glob(ext):
                locales.add(f.stem)
        return sorted(locales)

    def _load_locale(self, locale: str):
        """Load a locale file if not already loaded. Supports JSON and YAML."""
        if locale in self._translations:
            return
        # Try JSON first
        path = self._locale_dir / f"{locale}.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._translations[locale] = self._flatten(data)
                return
            except (json.JSONDecodeError, OSError):
                self._translations[locale] = {}
                return
        # Try YAML (.yml or .yaml) — zero-dep parser for simple key: value files
        for ext in (".yml", ".yaml"):
            yaml_path = self._locale_dir / f"{locale}{ext}"
            if yaml_path.is_file():
                try:
                    data = self._parse_simple_yaml(yaml_path.read_text(encoding="utf-8"))
                    self._translations[locale] = self._flatten(data)
                    return
                except OSError:
                    pass
        self._translations[locale] = {}


    @staticmethod
    def _parse_simple_yaml(text: str) -> dict:
        """Zero-dep YAML parser for simple key: value locale files.

        Supports:
          key: value
          parent:
            child: value    (1 level nesting via indentation)
          key: "quoted value"
          key: 'single quoted'
          # comments
        """
        result = {}
        current_parent = None
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            if ":" not in stripped:
                continue
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            # Strip quotes
            if value and value[0] in ('"', "'") and value[-1] == value[0]:
                value = value[1:-1]
            if not value:
                # Parent key — next indented lines are children
                current_parent = key
                result[key] = {}
            elif indent > 0 and current_parent:
                # Child of current parent
                if isinstance(result.get(current_parent), dict):
                    result[current_parent][key] = value
                else:
                    result[key] = value
            else:
                current_parent = None
                result[key] = value
        return result

    @staticmethod
    def _flatten(data: dict, prefix: str = "") -> dict:
        """Flatten nested dict: {"a": {"b": "c"}} → {"a.b": "c"}"""
        result = {}
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                result.update(I18n._flatten(value, full_key))
            else:
                result[full_key] = str(value)
        return result

    @staticmethod
    def _resolve(key: str, translations: dict) -> str | None:
        return translations.get(key)


__all__ = ["I18n"]
