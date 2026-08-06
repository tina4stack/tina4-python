# The settled structured-logger contract (owner decision, 2026-08-01).
#
# Four clauses, each with a positive AND a negative half, all against REAL log
# files on disk and REAL environment variables. No doubles anywhere: the failure
# modes below are produced by genuinely un-writable paths on the filesystem, not
# simulated.
#
# L1  FORMAT IS TEXT BY DEFAULT. Only TINA4_LOG_FORMAT=json selects JSON.
#     The implicit production->JSON switch is DELETED. It had to go because
#     "production" meant four different things and silently picked your format:
#         node   !isTruthy(TINA4_DEBUG)                    -> JSON, TINA4_DEBUG unset
#         ruby   TINA4_ENV|RACK_ENV|RUBY_ENV == production -> text
#         python only via configure(production=True)       -> text
#         php    no switch at all                          -> JSON always
#     Same machine, same .env, four formats. An OBJECT passed as the message is
#     still JSON-encoded INLINE inside the text line -- that part is correct in
#     all four and is pinned here so it stays.
#
# L2  THE ENV IS READ LAZILY, ON FIRST USE. Ruby and Node already did; Python
#     and PHP read TINA4_LOG_* only inside configure(), which only the SERVER
#     calls. Every script, worker, CLI tool and test that logged without booting
#     a server therefore ignored the operator's .env and fell back to defaults
#     that were OPPOSITE across frameworks (python: stdout + text + no file;
#     php: no stdout + files in ./logs + json).
#
# L3  TINA4_LOG_STRICT EXISTS. It is documented on all four env-var pages and,
#     before this change, implemented only in Ruby -- a documented no-op in
#     three frameworks. Truthy = a log-write failure RAISES instead of being
#     swallowed.
#
# L4  THE LEGACY ALIASES ARE GONE (BREAKING). TINA4_LOG_MAX_SIZE and
#     TINA4_LOG_KEEP are deleted; TINA4_LOG_ROTATE_SIZE / TINA4_LOG_ROTATE_KEEP
#     are the canonical names. The size alias even took a different UNIT
#     (megabytes) from the name it aliased (bytes), so one .env value meant two
#     different sizes depending on which name you reached for.
import json
import logging.handlers

import pytest

from tina4_python.debug import Log

# Every TINA4_LOG_* the logger reads, plus the three "which environment am I?"
# variables the deleted format switch keyed off in the other frameworks. Cleared
# before each test so nothing leaks in from the developer's shell or a .env.
_LOG_ENV = (
    "TINA4_LOG_FILE", "TINA4_LOG_DIR", "TINA4_LOG_FORMAT", "TINA4_LOG_OUTPUT",
    "TINA4_LOG_LEVEL", "TINA4_LOG_ROTATE_SIZE", "TINA4_LOG_ROTATE_KEEP",
    "TINA4_LOG_APPEND", "TINA4_LOG_STRICT", "TINA4_LOG_FUNC",
    "TINA4_LOG_MAX_SIZE", "TINA4_LOG_KEEP",
    "TINA4_DEBUG", "TINA4_ENV", "RACK_ENV",
)


def _reset_log_class():
    """Return Log to its never-configured state.

    Not a stand-in for the logger -- it IS the logger, put back the way a fresh
    interpreter would find it, so the lazy first-use path (L2) can actually run.
    """
    writer = Log._writer
    if hasattr(writer, "close"):
        writer.close()
    Log._writer = None
    Log._error_writer = None
    Log._initialized = False
    Log._level = "info"
    Log._is_production = False
    Log._stdout_enabled = True
    Log._file_enabled = True
    Log._format_mode = "text"
    Log._strict = False


@pytest.fixture(autouse=True)
def pristine_log(monkeypatch):
    for name in _LOG_ENV:
        monkeypatch.delenv(name, raising=False)
    _reset_log_class()
    yield
    _reset_log_class()


@pytest.fixture
def log_to_file(monkeypatch, tmp_path):
    """Point the logger at a real file under tmp_path, stdout off.

    Returns a callable that reads the lines actually written to disk -- the
    assertions below check the bytes an operator would `tail`, not an in-memory
    string the logger merely intended to write.
    """
    monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
    monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))

    def lines():
        path = tmp_path / "tina4.log"
        if not path.exists():
            return []
        return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln]

    return lines


# ── L1: format is TEXT by default ────────────────────────────────────────


class TestFormatIsTextByDefault:
    """POSITIVE half: nothing except TINA4_LOG_FORMAT may turn on JSON."""

    def test_the_production_flag_alone_does_not_select_json(self, log_to_file, tmp_path):
        # This is the deleted switch, in Python's own shape.
        Log.configure(log_dir=str(tmp_path), level="info", production=True)
        Log.info("still text in production")
        line = log_to_file()[-1]
        assert "[INFO" in line, f"expected a text line, got {line!r}"
        assert not line.lstrip().startswith("{")
        with pytest.raises(json.JSONDecodeError):
            json.loads(line)

    def test_tina4_env_production_does_not_select_json(self, log_to_file, monkeypatch, tmp_path):
        # Ruby's shape of the same switch — must not reappear here either.
        monkeypatch.setenv("TINA4_ENV", "production")
        monkeypatch.setenv("RACK_ENV", "production")
        Log.configure(log_dir=str(tmp_path), level="info")
        Log.info("tina4_env is not a format switch")
        assert "[INFO" in log_to_file()[-1]

    def test_tina4_debug_being_unset_does_not_select_json(self, log_to_file, monkeypatch, tmp_path):
        # Node's shape: JSON whenever TINA4_DEBUG is not truthy. The pristine
        # fixture already removed TINA4_DEBUG, so this is exactly that case.
        monkeypatch.delenv("TINA4_DEBUG", raising=False)
        Log.configure(log_dir=str(tmp_path), level="info")
        Log.info("debug-unset is not a format switch")
        assert "[INFO" in log_to_file()[-1]


class TestExplicitJsonStillSelectsJson:
    """NEGATIVE half: deleting the implicit switch must not delete the explicit
    one. Without this, "format is always text" would pass every test above."""

    def test_log_format_json_produces_json_lines(self, log_to_file, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_FORMAT", "json")
        Log.configure(log_dir=str(tmp_path), level="info")
        Log.error("boom", code=500)
        entry = json.loads(log_to_file()[-1])
        assert entry["level"] == "ERROR"
        assert entry["message"] == "boom"
        assert entry["context"]["code"] == 500

    def test_json_stdout_is_parseable_without_ansi(self, monkeypatch, capsys, tmp_path):
        # JSON you cannot parse is not JSON. An ANSI colour wrapper around the
        # line would make the one format you can explicitly ask for unusable on
        # stdout, which is where 12-factor deployments read logs.
        monkeypatch.setenv("TINA4_LOG_FORMAT", "json")
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "stdout")
        Log.configure(log_dir=str(tmp_path), level="info", production=False)
        Log.info("machine readable")
        out = capsys.readouterr().out.strip().splitlines()[-1]
        assert "\x1b[" not in out
        assert json.loads(out)["message"] == "machine readable"


class TestAnObjectMessageIsJsonEncodedInlineInTheTextLine:
    """All four frameworks already do this correctly. Pinned so it stays: it is
    the ONE piece of implicit JSON the contract keeps, and it is what makes a
    text log useful."""

    def test_a_dict_message_is_json_inside_a_text_line(self, log_to_file, tmp_path):
        Log.configure(log_dir=str(tmp_path), level="info")
        Log.info({"user": "alice", "id": 7})
        line = log_to_file()[-1]
        # Compact separators — byte-identical to PHP/Ruby/Node ({"a":1}, not {"a": 1}).
        assert '{"user":"alice","id":7}' in line
        # INLINE: the surrounding line is still a TEXT line, not a JSON document.
        assert "[INFO" in line
        assert not line.lstrip().startswith("{")

    def test_a_list_message_is_json_inside_a_text_line(self, log_to_file, tmp_path):
        Log.configure(log_dir=str(tmp_path), level="info")
        Log.warning([1, "two", {"three": 3}])
        line = log_to_file()[-1]
        assert '[1,"two",{"three":3}]' in line
        assert "[WARNING" in line

    def test_a_plain_string_message_is_not_json_encoded(self, log_to_file, tmp_path):
        # The negative half: strings pass through untouched — no stray quotes.
        Log.configure(log_dir=str(tmp_path), level="info")
        Log.info("just a string")
        line = log_to_file()[-1]
        assert line.endswith("just a string")


# ── L2: the env is read lazily, on first use ─────────────────────────────


class TestEnvIsResolvedOnFirstUseWithoutConfigure:
    """POSITIVE half: a worker, a CLI tool or a cron script that never boots a
    server must still get the operator's TINA4_LOG_* settings."""

    def test_log_format_is_honoured_without_configure(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_FORMAT", "json")
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        assert Log._initialized is False, "premise: nothing has configured the logger"

        Log.info("from a script that never called configure")

        entry = json.loads((tmp_path / "tina4.log").read_text().splitlines()[-1])
        assert entry["message"] == "from a script that never called configure"

    def test_log_output_and_dir_are_honoured_without_configure(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("TINA4_LOG_FILE", "worker.log")

        Log.info("worker line")

        assert "worker line" in (tmp_path / "worker.log").read_text()
        assert "worker line" not in capsys.readouterr().out, (
            "TINA4_LOG_OUTPUT=file must silence stdout even on the lazy path"
        )

    def test_log_level_is_honoured_without_configure(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_LEVEL", "error")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        assert Log.is_enabled("info") is False
        assert Log.is_enabled("error") is True

    def test_strict_is_honoured_without_configure(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_STRICT", "true")
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        Log.is_enabled("info")          # any first use resolves the env
        assert Log._strict is True


class TestExplicitConfigureStillWins:
    """NEGATIVE half: lazy resolution must not trample an explicit configure().
    Without this, "always re-read the env" would satisfy every test above and
    would silently override what the server asked for."""

    def test_configure_level_beats_the_env_level(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_LEVEL", "error")
        Log.configure(log_dir=str(tmp_path), level="debug")
        assert Log.is_enabled("debug") is True

    def test_the_env_is_not_re_read_on_every_log_call(self, monkeypatch, tmp_path, capsys):
        # configure() resolves once. Changing the env afterwards must NOT
        # reconfigure the live logger mid-process.
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        Log.configure(log_dir=str(tmp_path), level="info")
        monkeypatch.setenv("TINA4_LOG_FORMAT", "json")
        Log.info("still text")
        assert "[INFO" in capsys.readouterr().out


# ── L5: explicit argument > environment > default (ADR-0041) ─────────────


class TestExplicitArgumentBeatsTheEnvironmentForTheLogDirectory:
    """L5. `Log.configure("/srv/app/logs")` is one line that means one thing,
    and it did three different things across the four frameworks.

    This was `os.environ.get("TINA4_LOG_DIR", log_dir)` -- an idiom that reads
    naturally and says the opposite of what it looks like, because it demotes
    the CALLER'S argument to the fallback default. TINA4_LOG_DIR therefore beat
    an explicit argument and "put the logs exactly here" was inexpressible.

    Both halves are load-bearing and neither is sufficient alone: the positive
    test passes on an implementation that ignores the environment ENTIRELY, and
    the negative test passes on the old inverted code. Only together do they pin
    the ordering.

    The coordinate under test IS "which value wins", so these must not ask the
    logger which directory it chose -- that would delegate the asserted
    property to the code being tested. They CONTROL both candidates and read the
    FILESYSTEM for the answer.
    """

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
            "the explicit configure() argument did not win -- TINA4_LOG_DIR overrode it"
        assert not (env_dir / "tina4.log").exists(), \
            "the log landed in the env directory, so the environment beat the argument"

    def test_the_env_log_dir_still_applies_when_no_argument_is_given(self, monkeypatch, tmp_path):
        # NEGATIVE half: prove the fix did not simply stop reading the env.
        env_dir = tmp_path / "from_env"
        env_dir.mkdir()
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(env_dir))

        Log.configure(level="info")     # no log_dir -- nothing explicit to beat it
        Log.info("the env should win here")

        assert (env_dir / "tina4.log").exists(), \
            "TINA4_LOG_DIR was ignored even with no explicit argument to outrank it"

    def test_log_dir_defaults_to_none_so_unset_is_distinguishable(self):
        # The signature is the mechanism. With a real default ("logs") the
        # function cannot tell "the caller said nothing" from "the caller asked
        # for logs/", and the three-way precedence is inexpressible -- so this
        # pins the default rather than leaving it to be quietly restored.
        import inspect
        assert inspect.signature(Log.configure).parameters["log_dir"].default is None


# ── L3: TINA4_LOG_STRICT ─────────────────────────────────────────────────


class TestStrictRaisesOnAWriteFailure:
    """A REAL un-writable log target: a DIRECTORY sitting where the log file
    should be. open(path, "a") on a directory raises IsADirectoryError (an
    OSError) on every platform, and it does so as root too — no permission
    games, no simulation."""

    def _wedge_the_log_file(self, tmp_path):
        (tmp_path / "tina4.log").mkdir()

    def test_strict_true_raises(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("TINA4_LOG_STRICT", "true")
        self._wedge_the_log_file(tmp_path)
        Log.configure(log_dir=str(tmp_path), level="info")
        with pytest.raises(OSError):
            Log.info("this cannot be written")

    def test_strict_unset_swallows_and_the_caller_survives(self, monkeypatch, tmp_path):
        # The default, and the reason strict has to be opt-in: a broken log
        # target must not take a request down unless the operator says so.
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        self._wedge_the_log_file(tmp_path)
        Log.configure(log_dir=str(tmp_path), level="info")
        Log.info("this cannot be written either")   # must NOT raise

    def test_strict_false_swallows(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("TINA4_LOG_STRICT", "false")
        self._wedge_the_log_file(tmp_path)
        Log.configure(log_dir=str(tmp_path), level="info")
        Log.info("still swallowed")


class TestStrictReachesThroughStdlibLogging:
    """The other writer. When TINA4_LOG_FILE names a file, the backend is
    stdlib RotatingFileHandler, and stdlib swallows write failures INSIDE
    Handler.emit and routes them to handleError() -- which only warns on stderr.
    A plain `except OSError: raise` around emit() can therefore never fire, and
    strict mode would be a documented no-op through this path. That is exactly
    the trap Ruby hit (::Logger::LogDevice swallowing one layer below Tina4).

    The failure here is real: rotation is forced at 150 bytes and the rotated
    name .1 is already a DIRECTORY, so doRollover's os.remove(dfn) raises."""

    def _wedge_the_rotation_target(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("TINA4_LOG_FILE", "rot.log")
        monkeypatch.setenv("TINA4_LOG_ROTATE_SIZE", "150")
        monkeypatch.setenv("TINA4_LOG_ROTATE_KEEP", "1")
        (tmp_path / "rot.log.1").mkdir()

    def test_strict_true_raises_through_the_stdlib_handler(self, monkeypatch, tmp_path):
        self._wedge_the_rotation_target(monkeypatch, tmp_path)
        monkeypatch.setenv("TINA4_LOG_STRICT", "true")
        Log.configure(log_dir=str(tmp_path), level="info")
        with pytest.raises(OSError):
            for i in range(20):
                Log.info(f"rotation-line-{i}-padding-padding-padding-padding")

    def test_strict_unset_swallows_through_the_stdlib_handler(self, monkeypatch, tmp_path):
        self._wedge_the_rotation_target(monkeypatch, tmp_path)
        Log.configure(log_dir=str(tmp_path), level="info")
        for i in range(20):
            Log.info(f"rotation-line-{i}-padding-padding-padding-padding")


# ── L4: the legacy rotation aliases are gone (BREAKING) ──────────────────

_FAT_LINE = "x" * 1000          # 1000 chars per line
_LINES_FOR_OVER_A_MEGABYTE = 1200   # -> ~1.2 MB on disk


class TestLegacyRotationAliasesAreDeleted:
    """POSITIVE half: the old names must have NO effect at all."""

    def test_log_max_size_no_longer_sets_the_rotation_threshold(self, monkeypatch, tmp_path):
        # Under the deleted alias this meant "rotate at 1 MB" (the alias was in
        # MEGABYTES while the name it aliased is in BYTES -- one value, two
        # meanings). 1.2 MB is written below, so the old code rotated here.
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("TINA4_LOG_FILE", "maxsize.log")
        monkeypatch.setenv("TINA4_LOG_MAX_SIZE", "1")
        Log.configure(log_dir=str(tmp_path), level="info")
        for _ in range(_LINES_FOR_OVER_A_MEGABYTE):
            Log.info(_FAT_LINE)
        assert (tmp_path / "maxsize.log").stat().st_size > 1024 * 1024, "premise: over 1 MB written"
        assert list(tmp_path.glob("maxsize.log.*")) == [], (
            "TINA4_LOG_MAX_SIZE is deleted — it must not rotate anything"
        )

    def test_log_keep_no_longer_caps_the_number_of_backups(self, monkeypatch, tmp_path):
        # Under the deleted alias this meant "keep 2". The canonical default is
        # 5, so more than 2 backups proves the alias is not being read.
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("TINA4_LOG_FILE", "keep.log")
        monkeypatch.setenv("TINA4_LOG_ROTATE_SIZE", "150")
        monkeypatch.setenv("TINA4_LOG_KEEP", "2")
        Log.configure(log_dir=str(tmp_path), level="info")
        for i in range(200):
            Log.info(f"keep-line-{i}-padding-padding-padding-padding")
        assert len(list(tmp_path.glob("keep.log.*"))) == 5, (
            "TINA4_LOG_KEEP is deleted — the canonical default of 5 must apply"
        )


class TestCanonicalRotationNamesStillWork:
    """NEGATIVE half: deleting the aliases must not break the real names.
    Without this, "ignore both env vars entirely" would pass the tests above."""

    def test_rotate_size_in_bytes_still_rotates(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("TINA4_LOG_FILE", "canonical.log")
        monkeypatch.setenv("TINA4_LOG_ROTATE_SIZE", str(1024 * 1024))   # 1 MB, in BYTES
        Log.configure(log_dir=str(tmp_path), level="info")
        for _ in range(_LINES_FOR_OVER_A_MEGABYTE):
            Log.info(_FAT_LINE)
        assert list(tmp_path.glob("canonical.log.*")), (
            "TINA4_LOG_ROTATE_SIZE is the canonical name and must still rotate"
        )

    def test_rotate_keep_still_caps_the_number_of_backups(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("TINA4_LOG_FILE", "canonkeep.log")
        monkeypatch.setenv("TINA4_LOG_ROTATE_SIZE", "150")
        monkeypatch.setenv("TINA4_LOG_ROTATE_KEEP", "2")
        Log.configure(log_dir=str(tmp_path), level="info")
        for i in range(200):
            Log.info(f"canon-line-{i}-padding-padding-padding-padding")
        assert len(list(tmp_path.glob("canonkeep.log.*"))) == 2

    def test_rotate_size_zero_still_disables_rotation(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        monkeypatch.setenv("TINA4_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("TINA4_LOG_FILE", "norot.log")
        monkeypatch.setenv("TINA4_LOG_ROTATE_SIZE", "0")
        Log.configure(log_dir=str(tmp_path), level="info")
        for i in range(200):
            Log.info(f"norot-line-{i}-padding-padding-padding-padding")
        assert list(tmp_path.glob("norot.log.*")) == []
        assert not isinstance(Log._writer._handler, logging.handlers.RotatingFileHandler)
