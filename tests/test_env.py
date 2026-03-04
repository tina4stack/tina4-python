#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#

import os
import pytest
from tina4_python.Env import load_env


@pytest.fixture(autouse=True)
def clean_env_file(tmp_path):
    """Use tmp_path to avoid polluting the project directory."""
    yield tmp_path


def test_creates_env_file(tmp_path):
    env_path = str(tmp_path / ".env")
    assert not os.path.exists(env_path)
    load_env(env_path)
    assert os.path.isfile(env_path)


def test_env_file_has_defaults(tmp_path):
    env_path = str(tmp_path / ".env")
    load_env(env_path)
    with open(env_path) as f:
        content = f.read()
    assert "PROJECT_NAME" in content
    assert "VERSION" in content
    assert "TINA4_LANGUAGE" in content
    assert "API_KEY" in content
    assert "TINA4_DEBUG_LEVEL" in content


def test_loads_env_variables(tmp_path):
    env_path = str(tmp_path / ".env")
    load_env(env_path)
    assert os.environ.get("PROJECT_NAME") is not None


def test_existing_env_not_overwritten(tmp_path):
    env_path = str(tmp_path / ".env")
    with open(env_path, "w") as f:
        f.write('CUSTOM_VAR="hello"\n')
        f.write('TINA4_LANGUAGE=fr\n')
        f.write('TINA4_DEBUG_LEVEL=[TINA4_LOG_ALL]\n')
        f.write('API_KEY=testkey\n')
    load_env(env_path)
    with open(env_path) as f:
        content = f.read()
    assert 'CUSTOM_VAR="hello"' in content


def test_appends_missing_language(tmp_path):
    env_path = str(tmp_path / ".env")
    with open(env_path, "w") as f:
        f.write('PROJECT_NAME="Test"\n')
    # Remove TINA4_LANGUAGE from env if present
    os.environ.pop("TINA4_LANGUAGE", None)
    load_env(env_path)
    with open(env_path) as f:
        content = f.read()
    assert "TINA4_LANGUAGE" in content


def test_appends_missing_debug_level(tmp_path):
    env_path = str(tmp_path / ".env")
    with open(env_path, "w") as f:
        f.write('PROJECT_NAME="Test"\n')
    os.environ.pop("TINA4_DEBUG_LEVEL", None)
    load_env(env_path)
    with open(env_path) as f:
        content = f.read()
    assert "TINA4_DEBUG_LEVEL" in content


def test_appends_missing_api_key(tmp_path):
    env_path = str(tmp_path / ".env")
    with open(env_path, "w") as f:
        f.write('PROJECT_NAME="Test"\n')
    os.environ.pop("API_KEY", None)
    load_env(env_path)
    with open(env_path) as f:
        content = f.read()
    assert "API_KEY" in content
