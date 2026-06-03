"""Tests for tina4_python.env — typed env-var helpers (#43).

Same behaviour contract is mirrored in tina4-php (Tina4\\Env),
tina4-ruby (Tina4::Env), and tina4-nodejs (Env from @tina4/core).
"""
import pytest

from tina4_python import Env


class TestEnvBool:
    def test_returns_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("FOO", raising=False)
        assert Env.bool("FOO", default=True) is True
        assert Env.bool("FOO", default=False) is False
        assert Env.bool("FOO") is False  # default-default

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "True", "on", "ON", "yes", "YES", "y", "Y", "t", "T"])
    def test_truthy_values(self, value, monkeypatch):
        monkeypatch.setenv("FOO", value)
        assert Env.bool("FOO") is True

    @pytest.mark.parametrize("value", ["0", "false", "FALSE", "False", "off", "OFF", "no", "NO", "n", "N", "f", "F"])
    def test_falsy_values(self, value, monkeypatch):
        monkeypatch.setenv("FOO", value)
        assert Env.bool("FOO", default=True) is False

    def test_empty_string_uses_default(self, monkeypatch):
        # Empty string is in the falsy set, so it normalises to False regardless of default.
        monkeypatch.setenv("FOO", "")
        assert Env.bool("FOO", default=True) is False

    def test_garbage_uses_default(self, monkeypatch):
        monkeypatch.setenv("FOO", "maybe")
        assert Env.bool("FOO", default=True) is True
        assert Env.bool("FOO", default=False) is False

    def test_whitespace_stripped(self, monkeypatch):
        monkeypatch.setenv("FOO", "  true  ")
        assert Env.bool("FOO") is True


class TestEnvInt:
    def test_returns_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("FOO", raising=False)
        assert Env.int("FOO", default=42) == 42
        assert Env.int("FOO") == 0  # default-default

    def test_parses_decimal(self, monkeypatch):
        monkeypatch.setenv("FOO", "123")
        assert Env.int("FOO") == 123

    def test_parses_negative(self, monkeypatch):
        monkeypatch.setenv("FOO", "-456")
        assert Env.int("FOO") == -456

    def test_whitespace_stripped(self, monkeypatch):
        monkeypatch.setenv("FOO", "  789  ")
        assert Env.int("FOO") == 789

    def test_garbage_returns_default_and_warns(self, monkeypatch, caplog):
        monkeypatch.setenv("FOO", "not-a-number")
        assert Env.int("FOO", default=99) == 99
        # Should not raise

    def test_float_string_is_garbage_for_int(self, monkeypatch):
        # int("3.14") raises — that's the expected boundary.
        monkeypatch.setenv("FOO", "3.14")
        assert Env.int("FOO", default=7) == 7


class TestEnvFloat:
    def test_returns_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("FOO", raising=False)
        assert Env.float("FOO", default=1.5) == 1.5
        assert Env.float("FOO") == 0.0

    def test_parses_decimal(self, monkeypatch):
        monkeypatch.setenv("FOO", "3.14")
        assert Env.float("FOO") == 3.14

    def test_parses_integer_as_float(self, monkeypatch):
        monkeypatch.setenv("FOO", "42")
        assert Env.float("FOO") == 42.0

    def test_parses_scientific(self, monkeypatch):
        monkeypatch.setenv("FOO", "1.5e3")
        assert Env.float("FOO") == 1500.0

    def test_garbage_returns_default(self, monkeypatch):
        monkeypatch.setenv("FOO", "not-a-number")
        assert Env.float("FOO", default=2.5) == 2.5


class TestEnvStr:
    def test_returns_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("FOO", raising=False)
        assert Env.str("FOO", default="fallback") == "fallback"
        assert Env.str("FOO") == ""

    def test_returns_value(self, monkeypatch):
        monkeypatch.setenv("FOO", "hello")
        assert Env.str("FOO") == "hello"

    def test_preserves_whitespace(self, monkeypatch):
        # str() doesn't strip — caller decides whether to.
        monkeypatch.setenv("FOO", "  hello  ")
        assert Env.str("FOO") == "  hello  "

    def test_empty_string_is_empty_string_not_default(self, monkeypatch):
        # Setting "" is different from being unset — preserve that.
        monkeypatch.setenv("FOO", "")
        assert Env.str("FOO", default="fallback") == ""
