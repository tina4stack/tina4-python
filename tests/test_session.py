#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#

import os
import shutil
import pytest
from tina4_python.Session import Session, SessionHandler, SessionFileHandler


TEST_SESSION_PATH = "test_sessions"


@pytest.fixture(autouse=True)
def clean_session_dir():
    """Ensure clean session directory for each test."""
    if os.path.exists(TEST_SESSION_PATH):
        shutil.rmtree(TEST_SESSION_PATH)
    yield
    if os.path.exists(TEST_SESSION_PATH):
        shutil.rmtree(TEST_SESSION_PATH)


# --- Session init ---

def test_session_init_defaults():
    session = Session()
    assert session.session_name == "PY_SESS"
    assert session.session_values == {}
    assert session.session_hash == ""
    assert session.default_handler is SessionFileHandler


def test_session_init_custom():
    session = Session(default_name="MY_SESS", default_path=TEST_SESSION_PATH)
    assert session.session_name == "MY_SESS"
    assert session.session_path == TEST_SESSION_PATH


def test_session_init_unknown_handler():
    session = Session(default_handler="NonExistent")
    assert session.default_handler is SessionFileHandler  # fallback


# --- SessionHandler base class ---

def test_session_handler_set():
    session = Session(default_path=TEST_SESSION_PATH)
    result = SessionHandler.set(session, "user", "alice")
    assert result is True
    assert session.session_values["user"] == "alice"


def test_session_handler_get():
    session = Session(default_path=TEST_SESSION_PATH)
    session.session_values["color"] = "blue"
    assert SessionHandler.get(session, "color") == "blue"


def test_session_handler_get_missing():
    session = Session(default_path=TEST_SESSION_PATH)
    assert SessionHandler.get(session, "missing") is None


def test_session_handler_unset():
    session = Session(default_path=TEST_SESSION_PATH)
    session.session_values["key"] = "value"
    result = SessionHandler.unset(session, "key")
    assert result is True
    assert "key" not in session.session_values


def test_session_handler_unset_missing():
    session = Session(default_path=TEST_SESSION_PATH)
    result = SessionHandler.unset(session, "nonexistent")
    assert result is False


# --- Session set/get/unset (via file handler) ---

def test_session_set_and_get():
    session = Session(default_path=TEST_SESSION_PATH)
    session.session_hash = "test_hash"
    session.set("username", "bob")
    assert session.get("username") == "bob"


def test_session_unset():
    session = Session(default_path=TEST_SESSION_PATH)
    session.session_hash = "test_hash"
    session.set("temp", "data")
    assert session.get("temp") == "data"
    session.unset("temp")
    assert session.get("temp") is None


# --- Session start ---

def test_session_start():
    session = Session(default_path=TEST_SESSION_PATH)
    file_hash = session.start()
    assert isinstance(file_hash, str)
    assert len(file_hash) == 32  # md5 hex digest
    assert session.session_hash == file_hash


def test_session_start_with_hash():
    session = Session(default_path=TEST_SESSION_PATH)
    file_hash = session.start("custom_hash")
    assert file_hash == "custom_hash"
    assert session.session_hash == "custom_hash"


# --- Session save/load (file handler) ---

def test_session_save_creates_file():
    session = Session(default_path=TEST_SESSION_PATH)
    session.session_hash = "save_test"
    session.set("key", "value")
    result = session.save()
    assert result is True
    assert os.path.isfile(os.path.join(TEST_SESSION_PATH, "save_test"))


def test_session_load():
    # Create and save a session
    session1 = Session(default_path=TEST_SESSION_PATH)
    session1.session_hash = "load_test"
    session1.set("name", "alice")
    session1.save()

    # Load in a new session instance
    session2 = Session(default_path=TEST_SESSION_PATH)
    session2.load("load_test")
    assert session2.get("name") == "alice"


def test_session_load_nonexistent():
    session = Session(default_path=TEST_SESSION_PATH)
    # Loading a nonexistent hash should start a new session without error
    session.load("nonexistent_hash")
    assert session.session_hash is not None


# --- Session close ---

def test_session_close():
    session = Session(default_path=TEST_SESSION_PATH)
    session.session_hash = "close_test"
    session.set("data", "temp")
    session.save()
    file_path = os.path.join(TEST_SESSION_PATH, "close_test")
    assert os.path.isfile(file_path)

    result = session.close()
    assert result is True
    assert not os.path.isfile(file_path)


def test_session_close_nonexistent():
    session = Session(default_path=TEST_SESSION_PATH)
    session.session_hash = "never_saved"
    result = session.close()
    assert result is False


# --- Session iteration ---

def test_session_iter():
    session = Session(default_path=TEST_SESSION_PATH)
    session.session_hash = "iter_test"
    session.set("a", 1)
    session.set("b", 2)
    result = dict(session)
    assert "a" in result
    assert "b" in result
    assert result["a"] == 1
    assert result["b"] == 2


def test_session_iter_excludes_expires():
    session = Session(default_path=TEST_SESSION_PATH)
    session.session_values = {"user": "alice", "expires": "2099-01-01"}
    result = dict(session)
    assert "user" in result
    assert "expires" not in result
