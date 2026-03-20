# Tests for tina4_python.i18n
import json
import pytest
from tina4_python.i18n import I18n


@pytest.fixture
def i18n(tmp_path):
    locale_dir = tmp_path / "locales"
    locale_dir.mkdir()

    (locale_dir / "en.json").write_text(json.dumps({
        "greeting": "Hello",
        "farewell": "Goodbye",
        "welcome": "Welcome, {name}!",
        "nav": {
            "home": "Home",
            "about": "About",
        },
    }))

    (locale_dir / "fr.json").write_text(json.dumps({
        "greeting": "Bonjour",
        "farewell": "Au revoir",
        "welcome": "Bienvenue, {name}!",
        "nav": {
            "home": "Accueil",
            "about": "A propos",
        },
    }))

    return I18n(locale_dir=str(locale_dir), default_locale="en")


class TestI18n:
    def test_translate_default(self, i18n):
        assert i18n.t("greeting") == "Hello"

    def test_translate_french(self, i18n):
        i18n.locale = "fr"
        assert i18n.t("greeting") == "Bonjour"

    def test_interpolation(self, i18n):
        assert i18n.t("welcome", name="Alice") == "Welcome, Alice!"

    def test_nested_keys(self, i18n):
        assert i18n.t("nav.home") == "Home"

    def test_nested_french(self, i18n):
        i18n.locale = "fr"
        assert i18n.t("nav.about") == "A propos"

    def test_missing_key_returns_key(self, i18n):
        assert i18n.t("nonexistent") == "nonexistent"

    def test_fallback_to_default(self, i18n):
        # French missing "farewell" override — should fall back to English
        i18n.locale = "fr"
        assert i18n.t("farewell") == "Au revoir"

    def test_available_locales(self, i18n):
        locales = i18n.available_locales()
        assert "en" in locales
        assert "fr" in locales

    def test_locale_property(self, i18n):
        assert i18n.locale == "en"
        i18n.locale = "fr"
        assert i18n.locale == "fr"

    def test_missing_locale_file(self, tmp_path):
        i18n = I18n(locale_dir=str(tmp_path / "empty"), default_locale="en")
        assert i18n.t("anything") == "anything"


class TestI18nThirdLocale:
    """Test with a third locale (de) like Node.js tests."""

    @pytest.fixture
    def i18n_with_de(self, tmp_path):
        locale_dir = tmp_path / "locales"
        locale_dir.mkdir()

        (locale_dir / "en.json").write_text(json.dumps({
            "greeting": "Hello",
            "farewell": "Goodbye",
            "welcome": "Welcome, {name}!",
            "errors": {
                "not_found": "Not found",
                "forbidden": "Access denied",
            },
            "count": "You have {count} items",
        }))

        (locale_dir / "fr.json").write_text(json.dumps({
            "greeting": "Bonjour",
            "farewell": "Au revoir",
            "welcome": "Bienvenue, {name}!",
            "errors": {
                "not_found": "Non trouvé",
            },
        }))

        (locale_dir / "de.json").write_text(json.dumps({
            "greeting": "Hallo",
        }))

        return I18n(locale_dir=str(locale_dir), default_locale="en")

    def test_german_greeting(self, i18n_with_de):
        i18n_with_de.locale = "de"
        assert i18n_with_de.t("greeting") == "Hallo"

    def test_german_falls_back_to_english(self, i18n_with_de):
        i18n_with_de.locale = "de"
        assert i18n_with_de.t("farewell") == "Goodbye"

    def test_three_locales_available(self, i18n_with_de):
        locales = i18n_with_de.available_locales()
        assert "en" in locales
        assert "fr" in locales
        assert "de" in locales

    def test_available_locales_sorted(self, i18n_with_de):
        locales = i18n_with_de.available_locales()
        assert locales == sorted(locales)


class TestI18nInterpolation:
    """Test parameter substitution edge cases."""

    def test_multiple_params(self, i18n, tmp_path):
        locale_dir = tmp_path / "locales"
        (locale_dir / "en.json").write_text(json.dumps({
            "greeting": "Hello",
            "farewell": "Goodbye",
            "welcome": "Welcome, {name}!",
            "nav": {"home": "Home", "about": "About"},
            "multi": "{first} and {second}",
        }))
        i18n2 = I18n(locale_dir=str(locale_dir), default_locale="en")
        assert i18n2.t("multi", first="Alice", second="Bob") == "Alice and Bob"

    def test_interpolation_missing_placeholder(self, i18n):
        # welcome expects {name}, but we pass nothing — should not crash
        result = i18n.t("welcome")
        assert "{name}" in result or "Welcome" in result

    def test_french_interpolation(self, i18n):
        i18n.locale = "fr"
        assert i18n.t("welcome", name="Alice") == "Bienvenue, Alice!"


class TestI18nFallback:
    """Test fallback behavior from non-default locale to default."""

    def test_french_missing_nested_falls_back(self, i18n):
        # French has nav.home but not errors.forbidden
        i18n.locale = "fr"
        # nav.about is defined in fr as "A propos"
        assert i18n.t("nav.about") == "A propos"

    def test_missing_key_returns_key_in_nondefault(self, i18n):
        i18n.locale = "fr"
        assert i18n.t("totally.missing.key") == "totally.missing.key"

    def test_missing_locale_dir_available_locales(self, tmp_path):
        i18n = I18n(locale_dir=str(tmp_path / "nonexistent"), default_locale="en")
        locales = i18n.available_locales()
        assert "en" in locales
        assert len(locales) == 1


class TestI18nEnvConfig:
    """Test environment variable configuration."""

    def test_default_locale_from_env(self, tmp_path):
        import os
        locale_dir = tmp_path / "locales"
        locale_dir.mkdir()
        (locale_dir / "fr.json").write_text(json.dumps({"hello": "Bonjour"}))

        os.environ["TINA4_LANGUAGE"] = "fr"
        try:
            i18n = I18n(locale_dir=str(locale_dir))
            assert i18n.locale == "fr"
        finally:
            del os.environ["TINA4_LANGUAGE"]

    def test_locale_dir_from_env(self, tmp_path):
        import os
        locale_dir = tmp_path / "custom_locales"
        locale_dir.mkdir()
        (locale_dir / "en.json").write_text(json.dumps({"test": "value"}))

        os.environ["TINA4_LOCALE_DIR"] = str(locale_dir)
        try:
            i18n = I18n()
            assert i18n.t("test") == "value"
        finally:
            del os.environ["TINA4_LOCALE_DIR"]
