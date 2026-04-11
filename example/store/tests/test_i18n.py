"""Test I18n (internationalization) — demonstrates: loading translations from JSON files,
key lookup, fallback behaviour, locale switching, and interpolation.
"""
import os
import pytest
from tina4_python.i18n import I18n


STORE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCALE_DIR = os.path.join(STORE_ROOT, "src", "locales")


class TestI18nLoading:
    def test_loads_default_locale(self):
        i18n = I18n(locale_dir=LOCALE_DIR, default_locale="en")
        assert i18n.locale == "en"

    def test_loads_english_translations(self):
        i18n = I18n(locale_dir=LOCALE_DIR, default_locale="en")
        translations = i18n.load_translations("en")
        assert "store_name" in translations
        assert translations["store_name"] == "Tina4 Store"

    def test_loads_french_translations(self):
        i18n = I18n(locale_dir=LOCALE_DIR, default_locale="en")
        i18n.load_translations("fr")
        i18n.locale = "fr"
        assert i18n.t("home") == "Accueil"

    def test_available_locales(self):
        i18n = I18n(locale_dir=LOCALE_DIR, default_locale="en")
        locales = i18n.available_locales()
        assert "en" in locales
        assert "fr" in locales


class TestI18nTranslation:
    def test_translate_english_key(self):
        i18n = I18n(locale_dir=LOCALE_DIR, default_locale="en")
        assert i18n.t("home") == "Home"
        assert i18n.t("cart") == "Cart"
        assert i18n.t("checkout") == "Checkout"

    def test_translate_french_key(self):
        i18n = I18n(locale_dir=LOCALE_DIR, default_locale="en")
        i18n.locale = "fr"
        assert i18n.t("cart") == "Panier"
        assert i18n.t("checkout") == "Commander"

    def test_translate_store_tagline(self):
        i18n = I18n(locale_dir=LOCALE_DIR, default_locale="en")
        assert i18n.t("store_tagline") == "Simple. Fast. Human."

        i18n.locale = "fr"
        assert i18n.t("store_tagline") == "Simple. Rapide. Humain."


class TestI18nFallback:
    def test_missing_key_returns_key(self):
        i18n = I18n(locale_dir=LOCALE_DIR, default_locale="en")
        result = i18n.t("nonexistent.key.here")
        assert result == "nonexistent.key.here"

    def test_missing_in_current_falls_back_to_default(self):
        i18n = I18n(locale_dir=LOCALE_DIR, default_locale="en")
        # Add a key only to english
        i18n.add_translation("en", "english_only", "Only in English")
        i18n.locale = "fr"
        assert i18n.t("english_only") == "Only in English"

    def test_missing_locale_dir_returns_key(self):
        i18n = I18n(locale_dir="/nonexistent/path", default_locale="en")
        assert i18n.t("anything") == "anything"


class TestI18nLocaleSwitching:
    def test_switch_locale_via_property(self):
        i18n = I18n(locale_dir=LOCALE_DIR, default_locale="en")
        assert i18n.t("login") == "Login"

        i18n.locale = "fr"
        assert i18n.t("login") == "Connexion"

        i18n.locale = "en"
        assert i18n.t("login") == "Login"

    def test_set_locale_method(self):
        i18n = I18n(locale_dir=LOCALE_DIR, default_locale="en")
        i18n.set_locale("fr")
        assert i18n.get_locale() == "fr"
        assert i18n.t("products") == "Produits"

    def test_translate_with_locale_override(self):
        i18n = I18n(locale_dir=LOCALE_DIR, default_locale="en")
        # Use translate() with explicit locale override
        result = i18n.translate("cart", locale="fr")
        assert result == "Panier"
        # Current locale should remain unchanged
        assert i18n.get_locale() == "en"


class TestI18nInterpolation:
    def test_add_translation_with_placeholder(self):
        i18n = I18n(locale_dir=LOCALE_DIR, default_locale="en")
        i18n.add_translation("en", "greeting", "Hello, {name}!")
        result = i18n.t("greeting", name="Alice")
        assert result == "Hello, Alice!"

    def test_interpolation_missing_placeholder(self):
        i18n = I18n(locale_dir=LOCALE_DIR, default_locale="en")
        i18n.add_translation("en", "msg", "Hi {name}, welcome to {place}")
        # Missing 'place' should not crash — returns the raw template string
        result = i18n.t("msg", name="Bob")
        assert "{place}" in result or "Bob" in result
