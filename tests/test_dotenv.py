# Tests for tina4_python.dotenv
import os
import tempfile
import pytest
from tina4_python.dotenv import load_env, get_env, require_env, has_env, all_env


class TestLoadEnv:
    """Positive tests for .env file parsing."""

    def test_basic_key_value(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\nBAZ=qux\n")
        result = load_env(str(env_file), override=True)
        assert result == {"FOO": "bar", "BAZ": "qux"}
        assert os.environ["FOO"] == "bar"

    def test_quoted_values(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text('NAME="hello world"\nSINGLE=\'single quoted\'\n')
        result = load_env(str(env_file), override=True)
        assert result["NAME"] == "hello world"
        assert result["SINGLE"] == "single quoted"

    def test_comments_and_blank_lines(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\nKEY=value\n# another comment\n")
        result = load_env(str(env_file), override=True)
        assert result == {"KEY": "value"}

    def test_inline_comments(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("PORT=8080 # server port\n")
        result = load_env(str(env_file), override=True)
        assert result["PORT"] == "8080"

    def test_export_prefix(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("export DB_HOST=localhost\n")
        result = load_env(str(env_file), override=True)
        assert result["DB_HOST"] == "localhost"

    def test_no_override_existing(self, tmp_path):
        os.environ["EXISTING_VAR"] = "original"
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING_VAR=new_value\n")
        load_env(str(env_file), override=False)
        assert os.environ["EXISTING_VAR"] == "original"
        del os.environ["EXISTING_VAR"]

    def test_override_existing(self, tmp_path):
        os.environ["OVERRIDE_ME"] = "original"
        env_file = tmp_path / ".env"
        env_file.write_text("OVERRIDE_ME=new_value\n")
        load_env(str(env_file), override=True)
        assert os.environ["OVERRIDE_ME"] == "new_value"
        del os.environ["OVERRIDE_ME"]


class TestLoadEnvNegative:
    """Negative tests for .env file parsing."""

    def test_missing_file(self):
        result = load_env("/nonexistent/.env")
        assert result == {}

    def test_empty_file(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("")
        result = load_env(str(env_file))
        assert result == {}

    def test_malformed_lines(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("no_equals_sign\n=no_key\nVALID=ok\n")
        result = load_env(str(env_file), override=True)
        assert result == {"VALID": "ok"}


class TestGetEnv:
    def test_existing_var(self):
        os.environ["TEST_GET"] = "hello"
        assert get_env("TEST_GET") == "hello"
        del os.environ["TEST_GET"]

    def test_missing_with_default(self):
        assert get_env("NONEXISTENT_VAR", "fallback") == "fallback"

    def test_missing_no_default(self):
        assert get_env("NONEXISTENT_VAR") is None


class TestRequireEnv:
    def test_all_present(self):
        os.environ["REQ_A"] = "1"
        os.environ["REQ_B"] = "2"
        result = require_env("REQ_A", "REQ_B")
        assert result == {"REQ_A": "1", "REQ_B": "2"}
        del os.environ["REQ_A"]
        del os.environ["REQ_B"]

    def test_missing_var_exits(self):
        with pytest.raises(SystemExit):
            require_env("DEFINITELY_NOT_SET_12345")


class TestHasEnv:
    def test_existing_var(self):
        os.environ["HAS_ENV_TEST"] = "yes"
        assert has_env("HAS_ENV_TEST") is True
        del os.environ["HAS_ENV_TEST"]

    def test_missing_var(self):
        assert has_env("DEFINITELY_NOT_SET_HAS_ENV") is False

    def test_empty_value_still_exists(self):
        os.environ["HAS_ENV_EMPTY"] = ""
        assert has_env("HAS_ENV_EMPTY") is True
        del os.environ["HAS_ENV_EMPTY"]


class TestAllEnv:
    def test_returns_dict(self):
        result = all_env()
        assert isinstance(result, dict)

    def test_contains_known_var(self):
        os.environ["ALL_ENV_TEST"] = "present"
        result = all_env()
        assert result["ALL_ENV_TEST"] == "present"
        del os.environ["ALL_ENV_TEST"]

    def test_returns_copy(self):
        result = all_env()
        result["SHOULD_NOT_LEAK"] = "nope"
        assert "SHOULD_NOT_LEAK" not in os.environ
