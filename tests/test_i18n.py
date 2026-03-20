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
