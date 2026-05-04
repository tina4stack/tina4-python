# Tests for automatic i18n → Frond global wiring.
#
# When src/locales/ contains .json locale files, the framework should
# auto-register t() as a Frond global so templates can use {{ t("key") }}
# without any manual setup in app.py.
import json
import pytest
from pathlib import Path

from tina4_python.frond import Frond
from tina4_python.core.server import _auto_wire_i18n


@pytest.fixture(autouse=True)
def clean_frond_registry():
    """Clear class-level Frond registry before and after each test."""
    Frond.clear_registry()
    yield
    Frond.clear_registry()


@pytest.fixture
def locale_dir(tmp_path, monkeypatch):
    """Create a temp locale directory with en.json and fr.json."""
    locales = tmp_path / "locales"
    locales.mkdir()

    en = {
        "greeting": "Hello",
        "welcome": "Welcome, {name}!",
        "store_name": "Test Store",
    }
    fr = {
        "greeting": "Bonjour",
        "welcome": "Bienvenue, {name} !",
        "store_name": "Boutique Test",
    }

    (locales / "en.json").write_text(json.dumps(en))
    (locales / "fr.json").write_text(json.dumps(fr))

    monkeypatch.setenv("TINA4_LOCALE_DIR", str(locales))
    monkeypatch.setenv("TINA4_LOCALE", "en")
    return locales


# ── Auto-wiring ────────────────────────────────────────────────


class TestAutoWireI18n:

    def test_t_registered_when_locales_exist(self, locale_dir):
        _auto_wire_i18n()
        assert "t" in Frond._class_globals
        t = Frond._class_globals["t"]
        assert t("greeting") == "Hello"

    def test_t_works_with_interpolation(self, locale_dir):
        _auto_wire_i18n()
        t = Frond._class_globals["t"]
        assert t("welcome", name="Alice") == "Welcome, Alice!"

    def test_t_available_on_new_frond_instance(self, locale_dir, tmp_path):
        _auto_wire_i18n()
        engine = Frond(template_dir=str(tmp_path))
        assert "t" in engine._globals
        assert engine._globals["t"]("store_name") == "Test Store"

    def test_t_works_in_templates(self, locale_dir, tmp_path):
        _auto_wire_i18n()
        engine = Frond(template_dir=str(tmp_path))
        tpl = tmp_path / "test.twig"
        # Explicit utf-8 — Windows default cp1252 encodes the em-dash as a
        # single byte 0x97; Frond reads with utf-8 and would crash.
        tpl.write_text('{{ t("greeting") }} — {{ t("store_name") }}', encoding="utf-8")
        result = engine.render("test.twig")
        assert result == "Hello — Test Store"

    def test_t_survives_frond_recreation(self, locale_dir, tmp_path):
        """Simulates hot-reload: t() should persist across new Frond instances."""
        _auto_wire_i18n()
        engine1 = Frond(template_dir=str(tmp_path))
        assert engine1._globals["t"]("greeting") == "Hello"

        # Simulate hot-reload creating a new instance
        engine2 = Frond(template_dir=str(tmp_path))
        assert engine2._globals["t"]("greeting") == "Hello"

    def test_no_locales_dir_does_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_LOCALE_DIR", str(tmp_path / "nonexistent"))
        _auto_wire_i18n()
        assert "t" not in Frond._class_globals

    def test_empty_locales_dir_does_nothing(self, tmp_path, monkeypatch):
        empty = tmp_path / "locales"
        empty.mkdir()
        monkeypatch.setenv("TINA4_LOCALE_DIR", str(empty))
        _auto_wire_i18n()
        assert "t" not in Frond._class_globals

    def test_user_t_not_overwritten(self, locale_dir):
        """If user already registered t(), auto-wire should not overwrite it."""
        custom_t = lambda key, **kw: f"CUSTOM:{key}"
        Frond._class_globals["t"] = custom_t

        _auto_wire_i18n()

        # Should still be the custom one
        assert Frond._class_globals["t"] is custom_t
        assert Frond._class_globals["t"]("greeting") == "CUSTOM:greeting"

    def test_reads_locale_from_env(self, tmp_path, monkeypatch):
        """TINA4_LOCALE controls which language is used."""
        locales = tmp_path / "locales"
        locales.mkdir()
        (locales / "en.json").write_text(json.dumps({"hi": "Hello"}))
        (locales / "fr.json").write_text(json.dumps({"hi": "Bonjour"}))

        monkeypatch.setenv("TINA4_LOCALE_DIR", str(locales))
        monkeypatch.setenv("TINA4_LOCALE", "fr")

        _auto_wire_i18n()
        t = Frond._class_globals["t"]
        assert t("hi") == "Bonjour"

    def test_missing_key_returns_key(self, locale_dir):
        _auto_wire_i18n()
        t = Frond._class_globals["t"]
        assert t("nonexistent_key") == "nonexistent_key"


# ── Nested locale files ────────────────────────────────────────


class TestNestedLocaleKeys:
    """Verify that nested JSON locale files work with both leaf and dot-path keys."""

    @pytest.fixture
    def nested_locale_dir(self, tmp_path, monkeypatch):
        locales = tmp_path / "locales"
        locales.mkdir()
        en = {
            "nav": {
                "home": "Home",
                "products": "Products",
                "cart": "Cart",
            },
            "store": {
                "add_to_cart": "Add to Cart",
                "out_of_stock": "Out of Stock",
            },
            "greeting": "Hello",
        }
        (locales / "en.json").write_text(json.dumps(en))
        monkeypatch.setenv("TINA4_LOCALE_DIR", str(locales))
        monkeypatch.setenv("TINA4_LOCALE", "en")
        return locales

    def test_leaf_key_works(self, nested_locale_dir):
        _auto_wire_i18n()
        t = Frond._class_globals["t"]
        assert t("home") == "Home"
        assert t("cart") == "Cart"
        assert t("add_to_cart") == "Add to Cart"

    def test_dot_path_still_works(self, nested_locale_dir):
        _auto_wire_i18n()
        t = Frond._class_globals["t"]
        assert t("nav.home") == "Home"
        assert t("store.add_to_cart") == "Add to Cart"

    def test_flat_key_at_root_works(self, nested_locale_dir):
        _auto_wire_i18n()
        t = Frond._class_globals["t"]
        assert t("greeting") == "Hello"

    def test_leaf_key_in_template(self, nested_locale_dir, tmp_path):
        _auto_wire_i18n()
        engine = Frond(template_dir=str(tmp_path))
        tpl = tmp_path / "nav.twig"
        tpl.write_text('{{ t("home") }} | {{ t("products") }} | {{ t("cart") }}')
        result = engine.render("nav.twig")
        assert result == "Home | Products | Cart"

    def test_mixed_flat_and_nested(self, tmp_path, monkeypatch):
        """Flat keys and nested keys coexist without conflicts."""
        locales = tmp_path / "locales"
        locales.mkdir()
        en = {
            "title": "My Store",
            "nav": {"home": "Home", "about": "About"},
            "footer": {"copyright": "2026 Tina4"},
        }
        (locales / "en.json").write_text(json.dumps(en))
        monkeypatch.setenv("TINA4_LOCALE_DIR", str(locales))
        monkeypatch.setenv("TINA4_LOCALE", "en")

        _auto_wire_i18n()
        t = Frond._class_globals["t"]
        assert t("title") == "My Store"
        assert t("home") == "Home"
        assert t("copyright") == "2026 Tina4"
        assert t("nav.home") == "Home"
        assert t("footer.copyright") == "2026 Tina4"
