# Tina4 i18n — Internationalization and localization, zero dependencies.
"""
Simple key-based translations loaded from JSON files.

    from tina4_python.i18n import I18n

    i18n = I18n(locale="en", path="src/locales")
    _ = i18n.t
    _("greeting")  # "Hello" or "Bonjour" depending on locale
"""
import os
import re
import json
from pathlib import Path


_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _interpolate(template: str, params: dict) -> str:
    """Substitute {name} placeholders from params.

    Partial + literal-leftover: a placeholder present in params is replaced; a
    missing or malformed placeholder ({x.y}, {n:d}, a lone brace) is left
    untouched. Never raises -- a bad template must not crash t().
    """
    return _PLACEHOLDER.sub(
        lambda m: str(params[m.group(1)]) if m.group(1) in params else m.group(0),
        template,
    )


class I18n:
    """Internationalization support with JSON translation files.

    Locale files: src/locales/en.json, src/locales/fr.json, etc.
    Format: {"key": "translated value", "nested.key": "value"}
    """

    def __init__(self, locale: str = None, path: str = None,
                 # Legacy kwargs (3.12.x) — accepted but the docs use the
                 # shorter names. Renamed in 3.13.0 per the parity audit.
                 locale_dir: str = None, default_locale: str = None):
        self._locale_dir = Path(
            path or locale_dir or os.environ.get("TINA4_LOCALE_DIR", "src/locales")
        )
        self._default_locale = locale or default_locale or os.environ.get(
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

        # Interpolate {placeholder} tokens. Partial substitution: each token
        # present in kwargs is replaced; a missing or malformed placeholder is
        # left literal. Never raises (a bad template must not crash t()).
        if kwargs:
            value = _interpolate(value, kwargs)

        return value

    def set_locale(self, locale: str) -> None:
        """Set the active locale. Alias for the locale property setter."""
        self.locale = locale

    def get_locale(self) -> str:
        """Return the currently active locale code."""
        return self._current_locale

    def translate(self, key: str, params: dict = None, locale: str = None) -> str:
        """Translate a key with optional params dict and locale override.

        Equivalent to t() but accepts a params dict instead of **kwargs.
        """
        if locale:
            old = self._current_locale
            self.locale = locale
            try:
                return self.t(key, **(params or {}))
            finally:
                self.locale = old
        return self.t(key, **(params or {}))

    def load_translations(self, locale: str) -> dict:
        """Load and return the translation dict for a locale."""
        self._load_locale(locale)
        return dict(self._translations.get(locale, {}))

    def add_translation(self, locale: str, key: str, value: str) -> None:
        """Add or update a single translation key for a locale."""
        if locale not in self._translations:
            self._translations[locale] = {}
        self._translations[locale][key] = value

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
        """Flatten a nested dict to dot-paths, then add leaf-key aliases.

        {"nav": {"home": "Home"}} -> {"nav.home": "Home", "home": "Home"}

        Two passes so the alias rule is correct:
        1. Flatten to full dot-path keys only.
        2. Add each leaf key as a shortcut ONLY if it is not already present.

        So the FIRST dot-path wins on a leaf-key collision, and an explicit
        top-level flat key is never overwritten by a derived alias. (The old
        single-pass recursive merge was last-wins and could clobber an
        explicit flat key -- silent data loss.)
        """
        flat = I18n._flatten_paths(data, prefix)
        result = dict(flat)
        for full_key, value in flat.items():
            leaf = full_key.rsplit(".", 1)[-1]
            if leaf not in result:
                result[leaf] = value
        return result

    @staticmethod
    def _flatten_paths(data: dict, prefix: str = "") -> dict:
        """Flatten a nested dict to dot-path keys only (no leaf aliasing)."""
        result = {}
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                result.update(I18n._flatten_paths(value, full_key))
            else:
                result[full_key] = I18n._coerce_scalar(value)
        return result

    @staticmethod
    def _coerce_scalar(value) -> str:
        """Render a non-string locale scalar JSON-natively (true/false/null)."""
        if value is True:
            return "true"
        if value is False:
            return "false"
        if value is None:
            return "null"
        return str(value)

    @staticmethod
    def _resolve(key: str, translations: dict) -> str | None:
        return translations.get(key)


# ── Module-level shortcut ──────────────────────────────────────────────────
#
# GNU gettext convention: ``_("hello")`` everywhere, single import. We hold
# a process-wide default I18n that lazily configures itself from the same
# env vars (``TINA4_LOCALE``, ``TINA4_LOCALE_DIR``) the I18n class respects.
_default: I18n | None = None


def _get_default() -> I18n:
    global _default
    if _default is None:
        _default = I18n()
    return _default


def t(key: str, **kwargs) -> str:
    """Translate ``key`` using the default I18n instance.

    Lazy — the default instance is created on first call and reads its
    locale/path from environment (``TINA4_LOCALE``, ``TINA4_LOCALE_DIR``).
    For per-request locale switching, instantiate ``I18n`` directly.

        from tina4_python.i18n import t
        t("greeting", name="Alice")
    """
    return _get_default().t(key, **kwargs)


def set_default(i18n: I18n) -> None:
    """Replace the process-wide default I18n used by ``t()``."""
    global _default
    _default = i18n


__all__ = ["I18n", "t", "set_default"]
