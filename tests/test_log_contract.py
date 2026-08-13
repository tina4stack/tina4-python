# The settled structured-logger contract (owner decision, 2026-08-09/10),
# superseding the 2026-08-01 pass this file used to pin.
#
# Four clauses, each with a positive AND a negative half, all against REAL log
# files on disk and REAL environment variables. No doubles anywhere.
#
# L1  FORMAT IS DEBUG-DERIVED (Decision 3, supersedes the 2026-08-01 "text
#     always" rule): explicit TINA4_LOG_FORMAT wins; otherwise truthy
#     TINA4_DEBUG selects text and a false/absent TINA4_DEBUG selects JSON.
#     An OBJECT passed as the message is still JSON-encoded INLINE inside the
#     text line -- unchanged, and pinned here so it stays.
#
# L2  THE ENV IS READ LAZILY, ON FIRST USE. A script, worker, CLI tool or test
#     that logs without booting a server still gets the operator's .env.
#
# L3  TINA4_LOG_STRICT EXISTS. Truthy = a log-write failure RAISES instead of
#     being swallowed.
#
# L4  EXPLICIT ARGUMENT BEATS ENVIRONMENT, WHICH BEATS DEFAULT (ADR-0041), for
#     every configure() field, not just log_dir.
#
# L5  REMOVED SETTINGS NOW HARD-FAIL CONFIGURATION (Decision 19; this is a
#     STRICTER rule than the 2026-08-01 "the old names have no effect" pass:
#     TINA4_LOG_MAX_SIZE / TINA4_LOG_KEEP / TINA4_LOG_APPEND / TINA4_DEBUG_LEVEL
#     / TINA4_LOG_CRITICAL now RAISE a LogConfigurationError rather than being
#     silently ignored).
import json

import pytest

from tina4_python.debug import Log, LogConfigurationError

_LOG_ENV = (
    "TINA4_LOG_FILE", "TINA4_LOG_DIR", "TINA4_LOG_FORMAT", "TINA4_LOG_OUTPUT",
    "TINA4_LOG_LEVEL", "TINA4_LOG_FILE_LEVEL", "TINA4_LOG_ROTATE_SIZE",
    "TINA4_LOG_ROTATE_KEEP", "TINA4_LOG_STRICT", "TINA4_LOG_FUNC",
    "TINA4_LOG_MAX_SIZE", "TINA4_LOG_KEEP", "TINA4_LOG_APPEND",
    "TINA4_DEBUG_LEVEL", "TINA4_LOG_CRITICAL",
    "TINA4_DEBUG", "TINA4_ENV", "RACK_ENV",
)


@pytest.fixture(autouse=True)
def pristine_log(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in _LOG_ENV:
        monkeypatch.delenv(name, raising=False)
    Log.reset()
    yield
    Log.reset()


@pytest.fixture
def log_to_file(monkeypatch, tmp_path):
    monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
    monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))

    def lines():
        path = tmp_path / "tina4.log"
        if not path.exists():
            return []
        return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln]

    return lines


# ── L1: format is debug-derived ──────────────────────────────────────────


class TestFormatIsDebugDerived:
    """POSITIVE half: TINA4_DEBUG (or nothing) picks the default format."""

    def test_no_debug_selects_json_by_default(self, log_to_file, monkeypatch):
        monkeypatch.delenv("TINA4_DEBUG", raising=False)
        Log.configure(level="info")
        Log.info("prod default is json")
        line = log_to_file()[-1]
        entry = json.loads(line)  # must parse
        assert entry["message"] == "prod default is json"

    def test_truthy_debug_selects_text_by_default(self, log_to_file, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        Log.configure(level="info")
        Log.info("dev default is text")
        line = log_to_file()[-1]
        assert "[INFO" in line
        with pytest.raises(json.JSONDecodeError):
            json.loads(line)


class TestExplicitFormatOverridesDebug:
    """NEGATIVE half: an explicit TINA4_LOG_FORMAT beats the TINA4_DEBUG
    default in both directions."""

    def test_explicit_text_wins_even_without_debug(self, log_to_file, monkeypatch):
        monkeypatch.delenv("TINA4_DEBUG", raising=False)
        monkeypatch.setenv("TINA4_LOG_FORMAT", "text")
        Log.configure(level="info")
        Log.info("still text")
        assert "[INFO" in log_to_file()[-1]

    def test_explicit_json_wins_even_with_debug(self, log_to_file, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        monkeypatch.setenv("TINA4_LOG_FORMAT", "json")
        Log.configure(level="info")
        Log.error("boom", context={"code": 500})
        entry = json.loads(log_to_file()[-1])
        assert entry["level"] == "ERROR"
        assert entry["context"]["code"] == 500


class TestAnObjectMessageIsJsonEncodedInlineInTheTextLine:
    """All four frameworks do this correctly. Pinned so it stays."""

    def test_a_dict_message_is_json_inside_a_text_line(self, log_to_file, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        Log.configure(level="info")
        Log.info({"user": "alice", "id": 7})
        line = log_to_file()[-1]
        assert '{"id":7,"user":"alice"}' in line  # context/message keys sorted
        assert "[INFO" in line
        assert not line.lstrip().startswith("{")

    def test_a_plain_string_message_is_not_json_encoded(self, log_to_file, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        Log.configure(level="info")
        Log.info("just a string")
        assert log_to_file()[-1].endswith("just a string")


# ── L2: the env is read lazily, on first use ─────────────────────────────


class TestEnvIsResolvedOnFirstUseWithoutConfigure:

    def test_log_format_is_honoured_without_configure(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_FORMAT", "json")
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        assert Log._snapshot is None, "premise: nothing has configured the logger"

        Log.info("from a script that never called configure")

        entry = json.loads((tmp_path / "tina4.log").read_text().splitlines()[-1])
        assert entry["message"] == "from a script that never called configure"

    def test_log_output_and_dir_are_honoured_without_configure(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("TINA4_LOG_FILE", "worker.log")

        Log.info("worker line")

        assert "worker line" in (tmp_path / "worker.log").read_text()
        assert "worker line" not in capsys.readouterr().out

    def test_log_level_is_honoured_without_configure(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_LEVEL", "error")
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "both")
        assert Log.is_enabled("info") is False
        assert Log.is_enabled("error") is True

    def test_strict_is_honoured_without_configure(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_STRICT", "true")
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        Log.is_enabled("info")  # any first use resolves the env
        assert Log.configuration()["strict"] is True


class TestExplicitConfigureStillWins:

    def test_configure_level_beats_the_env_level(self, monkeypatch):
        monkeypatch.setenv("TINA4_LOG_LEVEL", "error")
        Log.configure(level="debug", output="both")
        assert Log.is_enabled("debug") is True

    def test_the_env_is_not_re_read_on_every_log_call(self, monkeypatch, capsys):
        Log.configure(level="info", format="text", output="stdout")
        monkeypatch.setenv("TINA4_LOG_FORMAT", "json")
        Log.info("still text")
        assert "[INFO" in capsys.readouterr().out


# ── L4: explicit argument > environment > default (ADR-0041) ─────────────


class TestExplicitArgumentBeatsTheEnvironmentForTheLogDirectory:

    def test_an_explicit_log_dir_beats_a_conflicting_env_log_dir(self, monkeypatch, tmp_path):
        env_dir = tmp_path / "from_env"
        arg_dir = tmp_path / "from_argument"
        env_dir.mkdir()
        arg_dir.mkdir()
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(env_dir))

        Log.configure(log_dir=str(arg_dir), level="info")
        Log.info("which directory won?")

        assert (arg_dir / "tina4.log").exists(), \
            "the explicit configure() argument did not win"
        assert not (env_dir / "tina4.log").exists(), \
            "the environment beat the argument"

    def test_the_env_log_dir_still_applies_when_no_argument_is_given(self, monkeypatch, tmp_path):
        env_dir = tmp_path / "from_env"
        env_dir.mkdir()
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(env_dir))

        Log.configure(level="info")
        Log.info("the env should win here")

        assert (env_dir / "tina4.log").exists()

    def test_log_dir_defaults_to_none_so_unset_is_distinguishable(self):
        import inspect
        assert inspect.signature(Log.configure).parameters["log_dir"].default is None


# ── L3: TINA4_LOG_STRICT ─────────────────────────────────────────────────


class TestStrictRaisesOnAWriteFailure:
    """configure() now itself proves the sink opens (LOG-E01), so the wedge
    must land AFTER a successful configure to exercise a WRITE-time failure
    (a real directory replacing the file between configure and the write --
    a live sink that dies later, e.g. an unmounted volume)."""

    def _wedge_after_configure(self, tmp_path):
        target = tmp_path / "tina4.log"
        target.unlink()
        target.mkdir()

    def test_strict_true_raises(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_STRICT", "true")
        Log.configure(log_dir=str(tmp_path), level="info", output="file")
        self._wedge_after_configure(tmp_path)
        from tina4_python.debug import LogWriteError
        with pytest.raises(LogWriteError):
            Log.info("this cannot be written")

    def test_strict_unset_swallows_and_the_caller_survives(self, tmp_path):
        Log.configure(log_dir=str(tmp_path), level="info", output="file")
        self._wedge_after_configure(tmp_path)
        Log.info("this cannot be written either")  # must NOT raise

    def test_strict_false_swallows(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_STRICT", "false")
        Log.configure(log_dir=str(tmp_path), level="info", output="file")
        self._wedge_after_configure(tmp_path)
        Log.info("still swallowed")


# ── L5: removed settings now hard-fail configuration (BREAKING) ──────────

_REMOVED = ("TINA4_LOG_MAX_SIZE", "TINA4_LOG_KEEP", "TINA4_LOG_APPEND",
            "TINA4_DEBUG_LEVEL", "TINA4_LOG_CRITICAL")


class TestRemovedSettingsHardFailConfiguration:
    """POSITIVE half: any removed setting, present with ANY value, raises."""

    @pytest.mark.parametrize("name", _REMOVED)
    def test_removed_setting_raises(self, monkeypatch, name):
        monkeypatch.setenv(name, "1")
        with pytest.raises(LogConfigurationError):
            Log.configure()

    def test_removed_setting_does_not_mutate_the_filesystem(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_MAX_SIZE", "1")
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path / "logs"))
        with pytest.raises(LogConfigurationError):
            Log.configure()
        assert not (tmp_path / "logs").exists()


class TestCanonicalRotationNamesStillWork:
    """NEGATIVE half: rejecting the legacy aliases must not break the real
    names -- TINA4_LOG_ROTATE_SIZE/_KEEP still rotate correctly."""

    def test_rotate_size_in_bytes_still_rotates(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("TINA4_LOG_FILE", "canonical.log")
        monkeypatch.setenv("TINA4_LOG_ROTATE_SIZE", "1024")
        Log.configure(level="info")
        for i in range(120):
            Log.info(f"canonical-line-{i}-padding-padding-padding")
        assert list(tmp_path.glob("canonical.log.*")), \
            "TINA4_LOG_ROTATE_SIZE is the canonical name and must still rotate"

    def test_rotate_keep_still_caps_the_number_of_backups(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("TINA4_LOG_FILE", "canonkeep.log")
        monkeypatch.setenv("TINA4_LOG_ROTATE_SIZE", "1024")
        monkeypatch.setenv("TINA4_LOG_ROTATE_KEEP", "2")
        Log.configure(level="info")
        for i in range(200):
            Log.info(f"canon-line-{i}-padding-padding-padding-padding")
        assert len(list(tmp_path.glob("canonkeep.log.*"))) == 2
