#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
"""Tests for LazySession proxy and FreshToken conditional logic."""

import os
import shutil
import pytest
from tina4_python.Session import Session, LazySession


TEST_SESSION_PATH = "test_lazy_sessions"


@pytest.fixture(autouse=True)
def clean_session_dir():
    """Ensure clean session directory for each test."""
    if os.path.exists(TEST_SESSION_PATH):
        shutil.rmtree(TEST_SESSION_PATH)
    yield
    if os.path.exists(TEST_SESSION_PATH):
        shutil.rmtree(TEST_SESSION_PATH)


# --- LazySession deferred activation ---

def test_lazy_session_not_activated_on_creation():
    cookies = {}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)
    assert ls.activated is False


def test_lazy_session_session_name_without_activation():
    cookies = {}
    ls = LazySession("MY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)
    assert ls.session_name == "MY_SESS"
    assert ls.activated is False  # name doesn't trigger activation


def test_lazy_session_empty_values_without_activation():
    cookies = {}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)
    assert ls.session_values == {}
    assert ls.session_hash == ""
    assert ls.activated is False


def test_lazy_session_iter_without_activation():
    cookies = {}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)
    assert list(ls) == []
    assert ls.activated is False


def test_lazy_session_save_noop_without_activation():
    cookies = {}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)
    assert ls.save() is True
    assert ls.activated is False


def test_lazy_session_close_noop_without_activation():
    cookies = {}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)
    assert ls.close() is True
    assert ls.activated is False


# --- LazySession activates on first use ---

def test_lazy_session_activates_on_set():
    cookies = {}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)
    ls.set("user", "alice")
    assert ls.activated is True
    assert ls.get("user") == "alice"


def test_lazy_session_activates_on_get():
    cookies = {}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)
    result = ls.get("nonexistent")
    assert ls.activated is True
    assert result is None


def test_lazy_session_activates_on_start():
    cookies = {}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)
    file_hash = ls.start()
    assert ls.activated is True
    assert isinstance(file_hash, str)
    assert len(file_hash) == 32


# --- Cookie synchronisation ---

def test_lazy_session_sets_cookie_on_new_session():
    """When no cookie exists, activation should create one."""
    cookies = {}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)
    ls.set("key", "value")
    assert "PY_SESS" in cookies
    assert len(cookies["PY_SESS"]) == 32  # md5 hash


def test_lazy_session_preserves_cookie_on_load():
    """When cookie exists, activation should load from it."""
    # First: create a real session and save data
    session = Session("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler")
    file_hash = session.start()
    session.set("name", "bob")
    session.save()

    # Now create LazySession with that cookie
    cookies = {"PY_SESS": file_hash}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)
    assert ls.get("name") == "bob"
    assert cookies["PY_SESS"] == file_hash  # cookie unchanged


def test_lazy_session_start_updates_cookie():
    """Explicit start() after activation must update the cookie dict."""
    cookies = {}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)

    # First activation creates a session
    ls.set("temp", "data")
    first_hash = cookies["PY_SESS"]

    # Explicit start() should create a new hash and update cookie
    new_hash = ls.start()
    assert cookies["PY_SESS"] == new_hash
    # The hash may or may not differ (depends on timing), but cookie must match


def test_lazy_session_start_with_existing_cookie_updates():
    """start() on a LazySession with existing cookie must sync."""
    # Create initial session
    session = Session("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler")
    old_hash = session.start()

    # LazySession with that cookie
    cookies = {"PY_SESS": old_hash}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)

    # Explicit start with custom hash
    ls.start("new_custom_hash")
    assert cookies["PY_SESS"] == "new_custom_hash"


def test_lazy_session_load_updates_cookie():
    """load() must update cookie dict with the loaded session hash."""
    # Create two sessions
    s1 = Session("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler")
    hash1 = s1.start()
    s1.set("session", "one")

    s2 = Session("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler")
    hash2 = s2.start()
    s2.set("session", "two")

    # LazySession starts with hash1
    cookies = {"PY_SESS": hash1}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)

    # load hash2 explicitly — cookie must switch
    ls.load(hash2)
    assert cookies["PY_SESS"] == hash2


# --- Session data persistence through LazySession ---

def test_lazy_session_set_get_roundtrip():
    cookies = {}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)
    ls.set("counter", 42)
    assert ls.get("counter") == 42


def test_lazy_session_unset():
    cookies = {}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)
    ls.set("temp", "data")
    assert ls.get("temp") == "data"
    ls.unset("temp")
    assert ls.get("temp") is None


def test_lazy_session_persistence_across_instances():
    """Data set via LazySession must be loadable in a new session."""
    cookies = {}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)
    ls.set("user_id", 123)
    session_hash = cookies["PY_SESS"]

    # Load in a fresh Session
    s2 = Session("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler")
    s2.load(session_hash)
    assert s2.get("user_id") == 123


def test_lazy_session_persistence_across_lazy_instances():
    """Data set via LazySession must be loadable in a new LazySession."""
    cookies1 = {}
    ls1 = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies1)
    ls1.set("user_id", 456)
    session_hash = cookies1["PY_SESS"]

    # Simulate second request with same cookie
    cookies2 = {"PY_SESS": session_hash}
    ls2 = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies2)
    assert ls2.get("user_id") == 456


# --- Session iteration when activated ---

def test_lazy_session_iter_when_activated():
    cookies = {}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)
    ls.set("a", 1)
    ls.set("b", 2)
    result = dict(ls)
    assert result["a"] == 1
    assert result["b"] == 2


# --- Session hash setter triggers activation ---

def test_lazy_session_hash_setter_activates():
    cookies = {}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)
    ls.session_hash = "custom_hash"
    assert ls.activated is True
    assert ls.session_hash == "custom_hash"


# --- Activated session reflects real values ---

def test_lazy_session_values_after_activation():
    cookies = {}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)
    ls.set("color", "blue")
    assert ls.session_values["color"] == "blue"
    assert ls.session_hash != ""


# --- Close after activation ---

def test_lazy_session_close_after_set():
    cookies = {}
    ls = LazySession("PY_SESS", TEST_SESSION_PATH, "SessionFileHandler", cookies)
    ls.set("temp", "data")
    session_hash = cookies["PY_SESS"]
    file_path = os.path.join(TEST_SESSION_PATH, session_hash)
    assert os.path.isfile(file_path)

    ls.close()
    assert not os.path.isfile(file_path)
