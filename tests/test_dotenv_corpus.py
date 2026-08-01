"""The shared .env corpus (feature 1 of the feature audit).

``tests/fixtures/dotenv_corpus.json`` is byte-identical in all four frameworks.
One answer key, four suites: a line that parses here and differently in Ruby is
a parity bug with a name, not a difference somebody has to notice.

Three of these rules were silent bugs before this row. Ruby dropped every
``export FOO=bar`` line and said nothing; Ruby kept a trailing comment inside the
value; and ``${VAR}`` expanded only in PHP, so a .env written against PHP
produced a broken literal in the other three.

Real files on disk in a temp directory, real process environment. A .env is a
file, so the real dependency is trivially available and there is nothing to mock.
"""
import json
import os
from pathlib import Path

import pytest

from tina4_python.dotenv import is_truthy, load_env
from tina4_python.mqtt import _truthy as _mqtt_truthy

FIXTURE = Path(__file__).parent / "fixtures" / "dotenv_corpus.json"
CORPUS = json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def env_dir(tmp_path, monkeypatch):
    """Write the shared .env and clear every key it declares from the real env.

    Loading is FIRST-WINS, so a key left over from another test would mask the
    file and quietly pass a test that proves nothing.
    """
    for key in list(CORPUS["expected"]) + CORPUS["_never_set"]["keys"]:
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / ".env"
    path.write_text(CORPUS["env_file"], encoding="utf-8")
    return path


class TestDotEnvCorpus:
    """Every rule in the shared answer key."""

    @pytest.mark.parametrize("key,want", sorted(CORPUS["expected"].items()))
    def test_every_key_parses_to_the_agreed_value(self, env_dir, key, want):
        load_env(str(env_dir))
        assert os.environ.get(key) == want

    # ── the three that were silently wrong ────────────────────

    def test_load_env_reads_an_export_prefixed_line(self, env_dir):
        load_env(str(env_dir))
        assert os.environ.get("EXPORTED") == "shellstyle"

    def test_load_env_does_not_silently_skip_an_export_line(self, env_dir):
        """The negative half: absent is the failure mode that hid this for so long.

        A .env copied out of a shell profile lost keys, and the failure surfaced
        somewhere unrelated - a blank TINA4_SECRET, a missing database URL.
        """
        load_env(str(env_dir))
        assert "EXPORTED" in os.environ

    def test_load_env_strips_a_trailing_comment_from_an_unquoted_value(self, env_dir):
        load_env(str(env_dir))
        assert os.environ.get("WITH_HASH") == "value"

    def test_load_env_does_not_keep_the_comment_in_the_value(self, env_dir):
        load_env(str(env_dir))
        assert "#" not in os.environ.get("WITH_HASH", "")

    def test_load_env_keeps_a_hash_inside_a_quoted_value(self, env_dir):
        load_env(str(env_dir))
        assert os.environ.get("QUOTED_HASH") == "a # b"

    def test_load_env_does_not_truncate_a_quoted_value_at_a_hash(self, env_dir):
        load_env(str(env_dir))
        assert os.environ.get("QUOTED_HASH", "").endswith("b")

    # ── interpolation ─────────────────────────────────────────

    def test_load_env_expands_a_dollar_brace_reference(self, env_dir):
        load_env(str(env_dir))
        assert os.environ.get("INTERP") == "example.com/api"
        assert os.environ.get("DQ_INTERP") == "example.com/v2"

    def test_load_env_does_not_expand_inside_single_quotes(self, env_dir):
        """Single quotes are the documented escape for a literal ${...}.

        This is the migration path for the breaking half of the change.
        """
        load_env(str(env_dir))
        assert os.environ.get("LITERAL") == "${HOST}/api"

    def test_load_env_leaves_an_unknown_reference_literal(self, env_dir):
        load_env(str(env_dir))
        assert os.environ.get("UNKNOWN") == "${NOPE}/x"

    def test_load_env_does_not_resolve_an_unknown_reference_to_nothing(self, env_dir, capsys):
        """PHP emptied it, so `URL=${DB_HOST}/db` with a typo became `/db`.

        A plausible-looking wrong value that reaches a connection attempt before
        failing, rather than a visible one. It must also SAY so.
        """
        load_env(str(env_dir))
        assert os.environ.get("UNKNOWN") != "/x"
        assert "NOPE" in capsys.readouterr().err

    # ── empty, escapes, malformed ─────────────────────────────

    def test_load_env_sets_an_empty_string_for_a_bare_equals(self, env_dir):
        load_env(str(env_dir))
        assert os.environ.get("EMPTY") == ""

    def test_load_env_does_not_unset_a_key_declared_empty(self, env_dir):
        """An empty value IS a value. Absent and blank are different things."""
        load_env(str(env_dir))
        assert "EMPTY" in os.environ

    def test_a_double_quoted_value_processes_escapes(self, env_dir):
        load_env(str(env_dir))
        assert os.environ.get("ESCAPES") == "line1\nline2\ttabbed"

    def test_load_env_warns_on_a_line_with_no_equals(self, env_dir, capsys):
        load_env(str(env_dir))
        assert "no_equals_sign" in capsys.readouterr().err

    def test_load_env_does_not_abort_the_whole_file_on_one_bad_line(self, env_dir):
        """The malformed lines sit in the MIDDLE of the fixture.

        Keys declared after them must still load, and the bad keys must not.
        """
        load_env(str(env_dir))
        assert os.environ.get("ESCAPES") == "line1\nline2\ttabbed"
        for key in CORPUS["_never_set"]["keys"]:
            assert key not in os.environ

    def test_whitespace_around_a_key_is_trimmed(self, env_dir):
        load_env(str(env_dir))
        assert os.environ.get("SPACED_KEY") == "spaced"


class TestDotEnvPrecedence:
    """real environment > .env.local > .env, first-wins."""

    def _write(self, tmp_path):
        p = CORPUS["precedence"]
        (tmp_path / ".env").write_text(p["env"], encoding="utf-8")
        (tmp_path / ".env.local").write_text(p["env_local"], encoding="utf-8")

    def test_env_local_overrides_env(self, tmp_path, monkeypatch):
        for key in CORPUS["precedence"]["expected_without_real_env"]:
            monkeypatch.delenv(key, raising=False)
        self._write(tmp_path)
        load_env(str(tmp_path / ".env.local"))
        load_env(str(tmp_path / ".env"))
        for key, want in CORPUS["precedence"]["expected_without_real_env"].items():
            assert os.environ.get(key) == want

    def test_load_env_does_not_overwrite_an_existing_process_variable(self, tmp_path, monkeypatch):
        """A stray gitignored .env.local must never clobber a production value.

        This is the security-correct ordering, not a convenience: a leftover
        dev secret beating an explicitly-set real one is the failure that matters.
        """
        real = CORPUS["precedence"]["real_env_wins"]
        monkeypatch.setenv(real["key"], real["value"])
        self._write(tmp_path)
        load_env(str(tmp_path / ".env.local"))
        load_env(str(tmp_path / ".env"))
        assert os.environ.get(real["key"]) == real["value"]


class TestEnvTruthiness:
    """One truthiness table, every subsystem, every framework.

    The env parser is only half the contract - the other half is what a parsed
    value MEANS as a boolean. This was not one table (see the fixture note), so
    the same .env answered differently depending on which subsystem asked.
    """

    @pytest.mark.parametrize("value", CORPUS["truthiness"]["truthy"])
    def test_truthy_values(self, value):
        assert is_truthy(value) is True

    @pytest.mark.parametrize("value", CORPUS["truthiness"]["falsy"])
    def test_falsy_values(self, value):
        assert is_truthy(value) is False

    @pytest.mark.parametrize("value", CORPUS["truthiness"]["truthy"])
    def test_mqtt_agrees_on_truthy(self, value):
        """The MQTT subsystem held a second copy of this table."""
        assert _mqtt_truthy(value) is True

    @pytest.mark.parametrize("value", CORPUS["truthiness"]["falsy"])
    def test_mqtt_agrees_on_falsy(self, value):
        assert _mqtt_truthy(value) is False
