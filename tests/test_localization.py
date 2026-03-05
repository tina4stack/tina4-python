#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#

import os
import pytest


@pytest.fixture(autouse=True)
def reset_language(monkeypatch):
    """Reset TINA4_LANGUAGE before each test."""
    monkeypatch.delenv("TINA4_LANGUAGE", raising=False)
    yield


# --- localize() returns a callable ---

def test_localize_returns_callable():
    from tina4_python.Localization import localize
    result = localize()
    assert callable(result)


def test_localize_returns_gettext_function():
    from tina4_python.Localization import localize
    _ = localize()
    # English passthrough — msgid == msgstr for English
    assert _("Load all things") == "Load all things"


# --- Language selection via env var ---

def test_localize_english_default():
    from tina4_python.Localization import localize
    _ = localize()
    assert _("Server stopped.") == "Server stopped."


def test_localize_french(monkeypatch):
    monkeypatch.setenv("TINA4_LANGUAGE", "fr")
    from tina4_python.Localization import localize
    _ = localize()
    assert _("Server stopped.") == "Serveur arrêté."


def test_localize_afrikaans(monkeypatch):
    monkeypatch.setenv("TINA4_LANGUAGE", "af")
    from tina4_python.Localization import localize
    _ = localize()
    assert _("Server stopped.") == "Bediener gestop."


# --- Fallback for unsupported language ---

def test_localize_fallback_unsupported_language(monkeypatch):
    monkeypatch.setenv("TINA4_LANGUAGE", "xx")
    from tina4_python.Localization import localize
    _ = localize()
    # Should not crash, falls back to returning msgid
    assert _("Server stopped.") == "Server stopped."


# --- Format strings preserved ---

def test_localize_format_string_french(monkeypatch):
    monkeypatch.setenv("TINA4_LANGUAGE", "fr")
    from tina4_python.Localization import localize
    _ = localize()
    translated = _("Server started http://{host_name}:{port}")
    assert "{host_name}" in translated
    assert "{port}" in translated
    result = translated.format(host_name="localhost", port=7145)
    assert "localhost" in result
    assert "7145" in result


def test_localize_format_string_afrikaans(monkeypatch):
    monkeypatch.setenv("TINA4_LANGUAGE", "af")
    from tina4_python.Localization import localize
    _ = localize()
    translated = _("Starting webserver on {port}")
    assert "{port}" in translated
    result = translated.format(port=8080)
    assert "8080" in result


# --- Available languages constant ---

def test_available_languages_list():
    from tina4_python.Localization import AVAILABLE_LANGUAGES
    assert "en" in AVAILABLE_LANGUAGES
    assert "fr" in AVAILABLE_LANGUAGES
    assert "af" in AVAILABLE_LANGUAGES
    assert "zh" in AVAILABLE_LANGUAGES
    assert "ja" in AVAILABLE_LANGUAGES
    assert "es" in AVAILABLE_LANGUAGES


# --- New language tests ---

def test_localize_chinese(monkeypatch):
    monkeypatch.setenv("TINA4_LANGUAGE", "zh")
    from tina4_python.Localization import localize
    _ = localize()
    assert _("Server stopped.") == "服务器已停止。"


def test_localize_japanese(monkeypatch):
    monkeypatch.setenv("TINA4_LANGUAGE", "ja")
    from tina4_python.Localization import localize
    _ = localize()
    assert _("Server stopped.") == "サーバー停止。"


def test_localize_spanish(monkeypatch):
    monkeypatch.setenv("TINA4_LANGUAGE", "es")
    from tina4_python.Localization import localize
    _ = localize()
    assert _("Server stopped.") == "Servidor detenido."


# --- All message keys translate in each language ---

MESSAGE_KEYS = [
    "Debug: {message}",
    "Warning: {message}",
    "Error: {message}",
    "Info: {message}",
    "Matching: {matching}",
    "Variables: {variables}",
    "Root Path {root_path} {url}",
    "Attempting to serve static file: {static_file}",
    "Attempting to serve CSS file: {css_file}",
    "Attempting to serve image file: {image_file}",
    "Assuming root path: {root_path}, library path: {library_path}",
    "Load all things",
    "Server started http://{host_name}:{port}",
    "Server stopped.",
    "Starting webserver on {port}",
    "Entry point name ... {name}",
    "403 - Forbidden",
    "500 - Internal Server Error",
    "404 - File Not Found",
    "Redirecting...",
    "Project ready!",
    "Running migrations...",
    "All migrations completed successfully!",
]


@pytest.mark.parametrize("lang", ["en", "fr", "af", "zh", "ja", "es"])
def test_all_keys_translate(monkeypatch, lang):
    """Every message key should return a non-empty string for each language."""
    monkeypatch.setenv("TINA4_LANGUAGE", lang)
    from tina4_python.Localization import localize
    _ = localize()
    for key in MESSAGE_KEYS:
        translated = _(key)
        assert translated, f"Empty translation for '{key}' in {lang}"
        assert isinstance(translated, str)
