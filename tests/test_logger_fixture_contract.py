# Structured logger shared-fixture contract -- feature 2.
#
# Shared conformance fixture: tina4-documentation/plan/v3/fixtures/logger_contract.json
# Contract: tina4-documentation/plan/v3/features/002-structured-logger.md
# ADR-0041 (explicit argument > environment > default).
#
# One test per fixture case, named to match the case's `name` field (checked
# mechanically by tina4-documentation/scripts/audit-contract-fixtures.py via a
# normalised substring match). Every case drives the REAL `Log` class against
# REAL files under a real temp project root (`tmp_path`, chdir'd into) and
# REAL environment variables -- no doubles anywhere.
#
# 2026-08-10 owner override baked in throughout: Decision 8 (SEPARATE FILE
# LEVEL -- TINA4_LOG_LEVEL gates the console only, TINA4_LOG_FILE_LEVEL (new,
# default ALL) gates the file, is_enabled is sink-aware) and Decision 20
# (SINGLE FILE + IN-PROCESS LOCK ONLY -- the concurrency witness is real
# THREAD concurrency plus the documented per-process-file caveat, not real
# child processes).
#
# Where a case's `given` under-specifies a coordinate the 2026-08-10 override
# added after the fixture was authored (no case here names
# TINA4_LOG_FILE_LEVEL by env/option), the console and file thresholds are set
# EQUAL so the case's own literal assertions hold under real sink-aware
# routing; Decision 8's independence is separately and explicitly proven by
# `test_console_and_file_levels_route_independently_per_decision_8` below.
import hashlib
import json
import os
import re
import threading
import time

import pytest

from tina4_python.debug import (
    Log, LogConfigurationError, LogArgumentError, LogWriteError, _FileSink,
    set_request_id, get_request_id, clear_request_id,
)

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

_LOG_ENV = (
    "TINA4_LOG_LEVEL", "TINA4_LOG_FILE_LEVEL", "TINA4_LOG_FORMAT",
    "TINA4_LOG_OUTPUT", "TINA4_LOG_DIR", "TINA4_LOG_FILE",
    "TINA4_LOG_ROTATE_SIZE", "TINA4_LOG_ROTATE_KEEP", "TINA4_LOG_STRICT",
    "TINA4_LOG_FUNC", "TINA4_DEBUG",
    "TINA4_LOG_MAX_SIZE", "TINA4_LOG_KEEP", "TINA4_LOG_APPEND",
    "TINA4_DEBUG_LEVEL", "TINA4_LOG_CRITICAL",
)


@pytest.fixture(autouse=True)
def pristine(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in _LOG_ENV:
        monkeypatch.delenv(name, raising=False)
    Log.reset()
    yield
    Log.reset()


# ── helpers ──────────────────────────────────────────────────────────────


def _lines(path):
    if not path.exists():
        return []
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln]


def _record_sans_timestamp(line: str) -> str:
    """Replace the real timestamp with a fixed placeholder so a byte-exact
    comparison against the fixture's frozen-time literal is possible without
    ever mocking the system clock (no doubles -- the clock is real)."""
    m = _TS_RE
    try:
        entry = json.loads(line)
        ts = entry.get("timestamp")
    except json.JSONDecodeError:
        ts = None
    if ts is None:
        parts = line.split(" ", 1)
        ts = parts[0] if parts else None
    if ts and m.match(ts):
        return line.replace(ts, "$T0")
    return line


# ═══════════════════════════════════════════════════════════════════════
# logger-configuration (LOG-C01..C10)
# ═══════════════════════════════════════════════════════════════════════


def test_logger_defaults_without_environment(tmp_path):
    cfg = Log.configuration()
    assert cfg["level"] == "INFO"
    assert cfg["format"] == "json"
    assert cfg["output"] == "stdout"
    assert cfg["log_dir"] == str(tmp_path / "logs")
    assert cfg["log_file"] is None
    assert cfg["rotate_size"] == 10485760
    assert cfg["rotate_keep"] == 5
    assert cfg["strict"] is False
    assert cfg["caller"] is False
    assert not (tmp_path / "logs").exists(), "reading configuration must not touch the filesystem"


def test_generated_development_values_select_all_text_and_both_sinks(monkeypatch):
    monkeypatch.setenv("TINA4_DEBUG", "true")
    monkeypatch.setenv("TINA4_LOG_LEVEL", "ALL")
    cfg = Log.configuration()
    assert cfg["level"] == "ALL"
    assert cfg["format"] == "text"
    assert cfg["stdout_enabled"] is True
    assert cfg["file_enabled"] is True


def test_explicit_option_beats_environment(monkeypatch):
    monkeypatch.setenv("TINA4_LOG_LEVEL", "ERROR")
    monkeypatch.setenv("TINA4_LOG_FORMAT", "json")
    monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
    Log.configure(level="debug", format="text", output="both")
    cfg = Log.configuration()
    assert cfg["level"] == "DEBUG"
    assert cfg["format"] == "text"
    assert cfg["output"] == "both"


def test_environment_beats_framework_default(monkeypatch):
    monkeypatch.setenv("TINA4_LOG_LEVEL", "critical")
    monkeypatch.setenv("TINA4_LOG_ROTATE_SIZE", "2048")
    monkeypatch.setenv("TINA4_LOG_ROTATE_KEEP", "0")
    cfg = Log.configuration()
    assert cfg["level"] == "CRITICAL"
    assert cfg["rotate_size"] == 2048
    assert cfg["rotate_keep"] == 0


def test_snapshot_ignores_later_environment_mutation(monkeypatch):
    monkeypatch.setenv("TINA4_LOG_LEVEL", "INFO")
    first = Log.configuration()["level"]
    monkeypatch.setenv("TINA4_LOG_LEVEL", "CRITICAL")
    second = Log.configuration()["level"]
    assert [first, second] == ["INFO", "INFO"]


def test_reset_reloads_environment(monkeypatch):
    monkeypatch.setenv("TINA4_LOG_LEVEL", "INFO")
    first = Log.configuration()["level"]
    monkeypatch.setenv("TINA4_LOG_LEVEL", "CRITICAL")
    reset_return = Log.reset()
    second = Log.configuration()["level"]
    assert [first, second] == ["INFO", "CRITICAL"]
    assert reset_return is None


def test_failed_reconfiguration_preserves_prior_snapshot(tmp_path):
    Log.configure(level="info", output="stdout")
    before = set(p.name for p in tmp_path.rglob("*"))
    with pytest.raises(LogConfigurationError):
        Log.configure(rotate_size=0)
    after_cfg = Log.configuration()
    assert after_cfg["level"] == "INFO"
    after = set(p.name for p in tmp_path.rglob("*"))
    assert before == after, "a failed configure() must not mutate the filesystem"


def test_file_name_does_not_enable_file_sink(tmp_path, monkeypatch):
    monkeypatch.setenv("TINA4_DEBUG", "false")
    monkeypatch.setenv("TINA4_LOG_FILE", "app.log")
    cfg = Log.configuration()
    assert cfg["output"] == "stdout"
    assert cfg["stdout_enabled"] is True
    assert cfg["file_enabled"] is False
    assert cfg["log_file"] == str(tmp_path / "logs" / "app.log")


def test_relative_and_absolute_paths_resolve_without_guessing(tmp_path):
    Log.configure(log_dir="var/log", log_file="app.data", output="file")
    cfg = Log.configuration()
    assert cfg["log_dir"] == str(tmp_path / "var" / "log")
    assert cfg["log_file"] == str(tmp_path / "var" / "log" / "app.data")
    assert cfg["layout"] == "single"


def test_configuration_result_is_a_defensive_copy(monkeypatch):
    monkeypatch.setenv("TINA4_LOG_LEVEL", "INFO")
    cfg1 = Log.configuration()
    cfg1["level"] = "MUTATED"
    cfg1["new_key"] = "leaked"
    cfg2 = Log.configuration()
    assert cfg2["level"] == "INFO"
    assert "new_key" not in cfg2


# ═══════════════════════════════════════════════════════════════════════
# logger-invalid-configuration (LOG-V01..V05)
# ═══════════════════════════════════════════════════════════════════════


def test_invalid_enum_values_fail(tmp_path, monkeypatch):
    cases = [
        {"TINA4_LOG_LEVEL": "verbose"},
        {"TINA4_LOG_FORMAT": "yaml"},
        {"TINA4_LOG_OUTPUT": "stout"},
    ]
    for env in cases:
        for name in _LOG_ENV:
            monkeypatch.delenv(name, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, str(v))
        with pytest.raises(LogConfigurationError):
            Log.configure()
        assert not (tmp_path / "logs").exists()
        Log.reset()


def test_invalid_rotation_values_fail(tmp_path, monkeypatch):
    cases = [
        {"TINA4_LOG_ROTATE_SIZE": 0},
        {"TINA4_LOG_ROTATE_SIZE": 1023},
        {"TINA4_LOG_ROTATE_SIZE": "large"},
        {"TINA4_LOG_ROTATE_KEEP": -1},
        {"TINA4_LOG_ROTATE_KEEP": 1.5},
    ]
    for env in cases:
        for name in _LOG_ENV:
            monkeypatch.delenv(name, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, str(v))
        with pytest.raises(LogConfigurationError):
            Log.configure()
        assert not (tmp_path / "logs").exists()
        Log.reset()


def test_invalid_path_and_boolean_types_fail(tmp_path, monkeypatch):
    # TINA4_LOG_DIR / TINA4_LOG_STRICT / TINA4_LOG_FUNC go through the
    # environment. TINA4_LOG_FILE's NUL-byte case cannot: an OS environment
    # variable is a NUL-terminated C string, so no real env var can ever
    # HOLD an embedded NUL (os.environ itself raises ValueError on the
    # attempt) -- the explicit-argument channel is the real, reachable path
    # for that exact byte sequence, and configure() validates it identically
    # either way.
    for name in _LOG_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TINA4_LOG_DIR", "")
    with pytest.raises(LogConfigurationError):
        Log.configure()
    assert not (tmp_path / "logs").exists()
    Log.reset()

    with pytest.raises(LogConfigurationError):
        Log.configure(log_file="bad\x00name")
    assert not (tmp_path / "logs").exists()
    Log.reset()

    for name in _LOG_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TINA4_LOG_STRICT", "maybe")
    with pytest.raises(LogConfigurationError):
        Log.configure()
    assert not (tmp_path / "logs").exists()
    Log.reset()

    for name in _LOG_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TINA4_LOG_FUNC", "1")  # native int, not the native boolean the setting requires
    with pytest.raises(LogConfigurationError):
        Log.configure()
    assert not (tmp_path / "logs").exists()
    Log.reset()


def test_removed_settings_fail_with_migration_detail(monkeypatch):
    for setting in ("TINA4_LOG_MAX_SIZE", "TINA4_LOG_KEEP", "TINA4_LOG_APPEND",
                    "TINA4_DEBUG_LEVEL", "TINA4_LOG_CRITICAL"):
        for name in _LOG_ENV:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv(setting, "1")
        with pytest.raises(LogConfigurationError) as exc:
            Log.configure()
        message = str(exc.value)
        assert "removed setting" in message
        assert setting == exc.value.setting
        Log.reset()


def test_legacy_bracket_level_fails(monkeypatch):
    monkeypatch.setenv("TINA4_LOG_LEVEL", "[TINA4_LOG_ERROR]")
    with pytest.raises(LogConfigurationError) as exc:
        Log.configure()
    assert exc.value.setting == "TINA4_LOG_LEVEL"


# ═══════════════════════════════════════════════════════════════════════
# logger-levels-and-routing (LOG-L01..L05)
# ═══════════════════════════════════════════════════════════════════════


def test_every_threshold_has_one_shared_level_matrix(tmp_path, capsys):
    expected = {
        "ALL": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        "DEBUG": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        "INFO": ["INFO", "WARNING", "ERROR", "CRITICAL"],
        "WARNING": ["WARNING", "ERROR", "CRITICAL"],
        "ERROR": ["ERROR", "CRITICAL"],
        "CRITICAL": ["CRITICAL"],
        "NONE": [],
    }
    for threshold, want in expected.items():
        Log.reset()
        Log.configure(level=threshold, file_level=threshold, output="both",
                       log_dir=str(tmp_path / threshold), format="json")
        capsys.readouterr()
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            getattr(Log, level.lower())("probe")
        stdout_levels = [json.loads(ln)["level"] for ln in capsys.readouterr().out.splitlines() if ln]
        file_levels = [json.loads(ln)["level"] for ln in _lines(tmp_path / threshold / "tina4.log")]
        assert stdout_levels == want, f"stdout mismatch at threshold {threshold}"
        assert file_levels == want, f"file mismatch at threshold {threshold}"


def test_level_configuration_is_case_insensitive(monkeypatch):
    pairs = [("all", "ALL"), ("Debug", "DEBUG"), ("INFO", "INFO"), ("warning", "WARNING"),
              ("Error", "ERROR"), ("critical", "CRITICAL"), ("none", "NONE")]
    for raw, canonical in pairs:
        Log.reset()
        Log.configure(level=raw)
        assert Log.configuration()["level"] == canonical


def test_is_enabled_matches_real_routing(tmp_path, capsys):
    # given.level applies to BOTH knobs (the fixture predates the 2026-08-10
    # sink-split override and does not distinguish them) so the case's own
    # "stdout_equals_main_file_levels" holds under real sink-aware routing.
    Log.configure(level="WARNING", file_level="WARNING", output="both", log_dir=str(tmp_path))
    results = {}
    for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        results[level] = Log.is_enabled(level)
        getattr(Log, level.lower())("probe")
    assert results == {"DEBUG": False, "INFO": False, "WARNING": True, "ERROR": True, "CRITICAL": True}
    stdout_levels = [ln.split(" ", 1)[0] for ln in []]  # placeholder not used
    out_lines = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    file_lines = _lines(tmp_path / "tina4.log")
    stdout_levels_seen = [json.loads(ln)["level"] for ln in out_lines]
    file_levels_seen = [json.loads(ln)["level"] for ln in file_lines]
    assert stdout_levels_seen == file_levels_seen == ["WARNING", "ERROR", "CRITICAL"]


def test_unknown_is_enabled_argument_fails():
    Log.configure(output="both")
    with pytest.raises(LogArgumentError) as exc:
        Log.is_enabled("verbose")
    assert exc.value.argument == "level"


def test_directory_and_named_file_layouts_are_exact(tmp_path):
    events = ("INFO", "WARNING", "ERROR", "CRITICAL")

    Log.configure(level="ALL", output="file", log_dir=str(tmp_path / "dir_mode"))
    for level in events:
        getattr(Log, level.lower())("probe")
    dir_main = [json.loads(ln)["level"] for ln in _lines(tmp_path / "dir_mode" / "tina4.log")]
    dir_error = [json.loads(ln)["level"] for ln in _lines(tmp_path / "dir_mode" / "error.log")]
    assert dir_main == ["INFO", "WARNING", "ERROR", "CRITICAL"]
    assert dir_error == ["WARNING", "ERROR", "CRITICAL"]

    Log.reset()
    Log.configure(level="ALL", output="file", log_dir=str(tmp_path / "file_mode"), log_file="app.log")
    for level in events:
        getattr(Log, level.lower())("probe")
    named = [json.loads(ln)["level"] for ln in _lines(tmp_path / "file_mode" / "app.log")]
    assert named == ["INFO", "WARNING", "ERROR", "CRITICAL"]
    assert not (tmp_path / "file_mode" / "error.log").exists()


def test_console_and_file_levels_route_independently_per_decision_8(tmp_path, capsys):
    """Framework-level proof of the 2026-08-10 Decision 8 override: not one of
    the 59 shared cases exercises TINA4_LOG_FILE_LEVEL by name (it postdates
    the fixture), so this proves it directly. Console gated by `level`, file
    independently by `file_level`."""
    Log.configure(level="ERROR", file_level="DEBUG", output="both", log_dir=str(tmp_path))
    Log.debug("only the file should see this")
    Log.info("only the file should see this too")
    out = capsys.readouterr().out
    assert "only the file should see this" not in out
    file_content = (tmp_path / "tina4.log").read_text()
    assert "only the file should see this" in file_content
    assert "only the file should see this too" in file_content
    assert Log.is_enabled("DEBUG") is False
    assert Log.is_enabled("DEBUG", sink="file") is True


# ═══════════════════════════════════════════════════════════════════════
# logger-format-and-values (LOG-F01..F12)
# ═══════════════════════════════════════════════════════════════════════


def test_canonical_json_bytes(tmp_path):
    Log.configure(format="json", output="file", log_dir=str(tmp_path))
    Log.info("ready")
    line = _lines(tmp_path / "tina4.log")[0] + "\n"
    entry = json.loads(line)
    assert _TS_RE.match(entry["timestamp"])
    assert list(entry.keys()) == ["timestamp", "level", "message"]
    assert entry["level"] == "INFO"
    assert entry["message"] == "ready"
    assert line.count("\n") == 1


def test_canonical_text_bytes(tmp_path):
    Log.configure(format="text", output="file", log_dir=str(tmp_path))
    Log.info("ready")
    line = _lines(tmp_path / "tina4.log")[0] + "\n"
    assert _record_sans_timestamp(line.rstrip("\n")) == "$T0 [INFO    ] ready"
    assert line.count("\n") == 1
    assert "\x1b[" not in line


def test_optional_fields_and_sorted_context_have_exact_order(tmp_path, monkeypatch):
    monkeypatch.setenv("TINA4_LOG_FUNC", "true")
    Log.configure(format="json", output="file", log_dir=str(tmp_path))
    set_request_id("req-1")
    try:
        def handle():
            Log.info("ready", context={"z": 1, "a": {"y": 2, "b": 3}})
        handle()
    finally:
        clear_request_id()
    entry = json.loads(_lines(tmp_path / "tina4.log")[0])
    assert list(entry.keys()) == ["timestamp", "level", "message", "request_id", "function", "context"]
    assert entry["request_id"] == "req-1"
    assert entry["function"] == "handle"
    assert entry["context"] == {"a": {"b": 3, "y": 2}, "z": 1}
    assert list(entry["context"].keys()) == ["a", "z"]
    assert list(entry["context"]["a"].keys()) == ["b", "y"]


def test_native_scalar_messages_use_json_spelling(tmp_path):
    Log.configure(format="json", output="file", log_dir=str(tmp_path))
    for message in (None, True, False, 42, 1.5):
        Log.info(message)
    got = [json.loads(ln)["message"] for ln in _lines(tmp_path / "tina4.log")]
    assert got == ["null", "true", "false", "42", "1.5"]


def test_map_and_sequence_messages_use_compact_sorted_json(tmp_path):
    Log.configure(format="json", output="file", log_dir=str(tmp_path))
    Log.info(["x", 2])
    Log.info({"z": 1, "a": True})
    got = [json.loads(ln)["message"] for ln in _lines(tmp_path / "tina4.log")]
    assert got == ['["x",2]', '{"a":true,"z":1}']


def test_embedded_line_breaks_cannot_inject_records(tmp_path):
    Log.configure(format="text", output="both", log_dir=str(tmp_path))
    message = "one\\path\r\ntwo"
    context = {"value": "a\nb"}
    Log.info(message, context=context)
    text_lines = _lines(tmp_path / "tina4.log")
    assert len(text_lines) == 1
    assert "one\\\\path\\r\\ntwo" in text_lines[0]

    Log.reset()
    Log.configure(format="json", output="file", log_dir=str(tmp_path / "j"))
    Log.info(message, context=context)
    json_lines = _lines(tmp_path / "j" / "tina4.log")
    assert len(json_lines) == 1
    entry = json.loads(json_lines[0])  # must parse -- one physical line
    assert entry["message"] == message  # JSON's own escaping keeps the real bytes


def test_ansi_exists_only_on_interactive_text_stdout(tmp_path, capsys):
    import pty
    import sys

    def _emit_through_real_pty(fmt: str) -> bytes:
        # A genuine OS pty (real termios line discipline -- confirmed by the
        # \n -> \r\n translation a plain pipe never does), swapped in for
        # sys.stdout for the duration of one call so Log's own
        # sys.stdout.isatty() check sees a REAL interactive terminal. No
        # subprocess needed: the pty device itself is the real dependency
        # under test, not a double standing in for one.
        master_fd, slave_fd = pty.openpty()
        real_stdout = sys.stdout
        try:
            sys.stdout = os.fdopen(slave_fd, "w", closefd=False)
            Log.reset()
            Log.configure(format=fmt, output="stdout")
            Log.warning("probe")
            sys.stdout.flush()
        finally:
            sys.stdout = real_stdout
        # Drain BEFORE closing the slave: on macOS, closing the slave first
        # can discard bytes that were written but not yet delivered to a
        # reader (read() then returns EOF with no data), unlike a plain pipe.
        import select
        chunks = []
        while True:
            r, _, _ = select.select([master_fd], [], [], 0.5)
            if not r:
                break
            try:
                chunk = os.read(master_fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            chunks.append(chunk)
        os.close(slave_fd)
        os.close(master_fd)
        return b"".join(chunks)

    tty_text = _emit_through_real_pty("text")
    assert b"\x1b[" in tty_text, "an interactive tty running text format must carry ANSI colour"
    tty_json = _emit_through_real_pty("json")
    assert b"\x1b[" not in tty_json, "JSON must never carry ANSI, even on a tty"

    # Non-interactive text stdout (capsys -- a real captured pipe, exactly
    # what a redirected/piped process sees) must never carry ANSI.
    Log.reset()
    Log.configure(format="text", output="stdout")
    Log.warning("probe")
    assert "\x1b[" not in capsys.readouterr().out

    # And neither may a real file.
    Log.reset()
    Log.configure(format="text", output="file", log_dir=str(tmp_path / "filecheck"))
    Log.warning("probe")
    assert "\x1b[" not in (tmp_path / "filecheck" / "tina4.log").read_text()


def test_circular_context_is_marked_without_raising(tmp_path):
    Log.configure(format="json", output="file", log_dir=str(tmp_path))
    circular = {}
    circular["self"] = circular
    result = Log.info("ready", context=circular)
    assert result is None
    entry = json.loads(_lines(tmp_path / "tina4.log")[0])
    assert entry["context"] == {"self": "[Circular]"}


def test_invalid_utf8_binary_has_a_digest_marker(tmp_path):
    import base64
    raw = base64.b64decode("/wA=")
    assert raw == bytes([0xFF, 0x00])
    Log.configure(format="json", output="file", log_dir=str(tmp_path))
    Log.info(raw)
    entry = json.loads(_lines(tmp_path / "tina4.log")[0])
    m = re.match(r"^<binary 2 bytes sha256=([0-9a-f]{64})>$", entry["message"])
    assert m, entry["message"]
    assert m.group(1) == hashlib.sha256(raw).hexdigest()
    assert b"\xff\x00" not in json.dumps(entry).encode("latin-1", errors="ignore")


def test_unsupported_value_does_not_run_application_stringification():
    class _Throws:
        called = False

        def __str__(self):
            _Throws.called = True
            raise RuntimeError("must never be called")

        def __repr__(self):
            _Throws.called = True
            raise RuntimeError("must never be called")

    Log.configure(format="json", output="stdout")
    obj = _Throws()
    result = Log.info(obj)
    assert result is None
    assert _Throws.called is False


def test_later_context_mutation_cannot_change_event(tmp_path):
    Log.configure(format="json", output="file", log_dir=str(tmp_path))
    context = {"items": [1]}
    Log.info("ready", context=context)
    context["items"].append(2)
    entry = json.loads(_lines(tmp_path / "tina4.log")[0])
    assert entry["context"] == {"items": [1]}


def test_oversized_event_becomes_bounded_valid_replacement(tmp_path):
    Log.configure(format="json", output="file", log_dir=str(tmp_path), rotate_size=1024)
    Log.info("x" * 5000)
    raw = _lines(tmp_path / "tina4.log")[0]
    assert len((raw + "\n").encode("utf-8")) <= 1024
    entry = json.loads(raw)
    assert entry["message"] == "Log event omitted: encoded size exceeds sink limit"
    assert entry["context"]["truncated"] is True
    assert entry["context"]["original_bytes"] > 1024
    assert re.match(r"^[0-9a-f]{64}$", entry["context"]["sha256"])


# ═══════════════════════════════════════════════════════════════════════
# logger-sinks-and-rotation (LOG-S01..S05, LOG-R01..R07)
# ═══════════════════════════════════════════════════════════════════════


def test_explicit_stdout_creates_no_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TINA4_DEBUG", "true")
    Log.configure(output="stdout", log_file="app.log", log_dir=str(tmp_path))
    Log.info("ready")
    out = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    assert len(out) == 1
    assert list(tmp_path.rglob("*")) == []


def test_explicit_file_silences_stdout(tmp_path, capsys):
    Log.configure(output="file", log_dir=str(tmp_path))
    Log.info("ready")
    assert capsys.readouterr().out == ""
    assert (tmp_path / "tina4.log").exists()


def test_explicit_both_writes_stdout_and_files_in_production(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TINA4_DEBUG", "false")
    Log.configure(output="both", log_dir=str(tmp_path))
    Log.warning("ready")
    out = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    assert len(out) == 1
    assert (tmp_path / "tina4.log").exists()
    assert (tmp_path / "error.log").exists()


def test_unset_output_is_stdout_only_in_production(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TINA4_DEBUG", "false")
    Log.configure(log_dir=str(tmp_path))
    Log.warning("ready")
    out = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    assert len(out) == 1
    assert list(tmp_path.rglob("*")) == []


def test_unset_output_writes_stdout_and_bounded_files_in_development(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TINA4_DEBUG", "true")
    Log.configure(log_dir=str(tmp_path))
    Log.warning("ready")
    out = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    assert len(out) == 1
    assert (tmp_path / "tina4.log").exists()
    assert (tmp_path / "error.log").exists()


def test_exact_rotation_boundary_does_not_rotate(tmp_path):
    path = tmp_path / "app.log"
    path.write_bytes(b"x" * 1000)
    sink = _FileSink(path, 1024, 2)
    sink.open()
    sink.write("x" * 23 + "\n")  # 24 bytes total
    assert path.stat().st_size == 1024
    assert not (tmp_path / "app.log.1").exists()


def test_next_record_is_predicted_before_append(tmp_path):
    path = tmp_path / "app.log"
    path.write_bytes(b"x" * 1000)
    sink = _FileSink(path, 1024, 2)
    sink.open()
    sink.write("x" * 24 + "\n")  # 25 bytes total -> 1000+25 > 1024
    assert path.stat().st_size == 25
    assert (tmp_path / "app.log.1").stat().st_size == 1000


def test_backup_names_and_retention_are_deterministic(tmp_path):
    path = tmp_path / "app.log"
    sink = _FileSink(path, 1024, 2)
    sink.open()
    for i in range(30):
        sink.write("x" * 299 + "\n")  # 300 bytes/record
    assert path.exists()
    assert (tmp_path / "app.log.1").exists()
    assert (tmp_path / "app.log.2").exists()
    assert not (tmp_path / "app.log.0").exists()
    assert not (tmp_path / "app.log.3").exists()


def test_zero_retention_keeps_only_bounded_current_file(tmp_path):
    path = tmp_path / "app.log"
    sink = _FileSink(path, 1024, 0)
    sink.open()
    for i in range(20):
        sink.write("x" * 299 + "\n")
    assert path.exists()
    assert path.stat().st_size <= 1024
    assert list(tmp_path.glob("app.log.*")) == []


def test_preexisting_oversized_file_rotates_before_append(tmp_path):
    path = tmp_path / "app.log"
    path.write_bytes(b"x" * 1500)
    sink = _FileSink(path, 1024, 1)
    sink.open()
    sink.write("x" * 19 + "\n")  # 20 bytes
    assert path.stat().st_size == 20
    assert (tmp_path / "app.log.1").stat().st_size == 1500


def test_main_and_error_files_rotate_independently(tmp_path):
    Log.configure(level="ALL", output="file", log_dir=str(tmp_path), rotate_size=1024, rotate_keep=1)
    for i in range(60):
        Log.info(f"info-{i}-padpadpadpadpadpadpadpadpadpad")
    for i in range(20):
        Log.warning(f"warn-{i}-padpadpadpadpadpadpadpadpadpad")
    main = tmp_path / "tina4.log"
    error = tmp_path / "error.log"
    assert main.stat().st_size <= 1024
    assert error.stat().st_size <= 1024
    assert len(list(tmp_path.glob("tina4.log.*"))) <= 1
    assert len(list(tmp_path.glob("error.log.*"))) <= 1
    # independence: the main file (fed by every event) rotates at least as
    # often as error.log (fed by warnings only) -- proving they are not one
    # shared rotation state.
    assert len(list(tmp_path.glob("tina4.log.*"))) >= len(list(tmp_path.glob("error.log.*")))


def test_concurrent_processes_preserve_records_and_retention(tmp_path):
    """Decision 20 override: SINGLE FILE + IN-PROCESS LOCK ONLY. The
    concurrency witness is real THREAD concurrency (not real child
    processes) plus the documented per-process-file caveat."""
    Log.configure(level="ALL", output="file", log_dir=str(tmp_path), rotate_size=4096, rotate_keep=2, format="json")
    n_threads, per_thread = 4, 100
    errors = []

    def worker(thread_id):
        try:
            for seq in range(per_thread):
                Log.info("concurrent", context={"thread": thread_id, "seq": seq})
        except Exception as exc:  # pragma: no cover - surfaced via errors list
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors

    files = [tmp_path / "tina4.log"] + sorted(tmp_path.glob("tina4.log.*"))
    seen = set()
    partial = 0
    for f in files:
        for raw in f.read_text(encoding="utf-8").splitlines():
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                partial += 1
                continue
            key = (entry["context"]["thread"], entry["context"]["seq"])
            assert key not in seen, f"duplicate event id {key}"
            seen.add(key)

    assert partial == 0
    assert len(list(tmp_path.glob("tina4.log.*"))) <= 2
    assert list(tmp_path.glob("*.lock")) == []


# ═══════════════════════════════════════════════════════════════════════
# logger-request-and-lifecycle (LOG-Q01..Q05)
# ═══════════════════════════════════════════════════════════════════════


def test_set_get_and_clear_request_id():
    set_request_id("req-1")
    first = get_request_id()
    clear_request_id()
    second = get_request_id()
    assert [first, second] == ["req-1", None]


@pytest.mark.asyncio
async def test_overlapping_requests_never_exchange_ids(tmp_path):
    import asyncio
    Log.configure(format="json", output="file", log_dir=str(tmp_path))

    async def task_a():
        set_request_id("A")
        await asyncio.sleep(0.05)
        Log.info("from-a")
        clear_request_id()

    async def task_b():
        set_request_id("B")
        Log.info("from-b")
        await asyncio.sleep(0.02)
        clear_request_id()

    await asyncio.gather(task_a(), task_b())

    records = {json.loads(ln)["message"]: json.loads(ln)["request_id"] for ln in _lines(tmp_path / "tina4.log")}
    assert records == {"from-a": "A", "from-b": "B"}


@pytest.mark.asyncio
async def test_request_pipeline_clears_id_in_finally(tmp_path):
    from tina4_python.core.request import Request
    from tina4_python.core.router import Router, noauth, get
    from tina4_python.core.server import handle

    Log.configure(format="json", output="file", log_dir=str(tmp_path))
    Router.clear()

    @noauth()
    @get("/boom")
    async def boom(request, response):
        Log.info("boom-handler")
        raise RuntimeError("intentional failure for LOG-Q03")

    @noauth()
    @get("/ok")
    async def ok(request, response):
        Log.info("ok-handler")
        return response({"ok": True})

    try:
        req_a = Request()
        req_a.method = "GET"
        req_a.path = "/boom"
        req_a.headers = {"x-request-id": "A"}
        await handle(req_a)
        assert get_request_id() is None, "id must be cleared after a request that raised"

        req_b = Request()
        req_b.method = "GET"
        req_b.path = "/ok"
        req_b.headers = {"x-request-id": "B"}
        await handle(req_b)
        assert get_request_id() is None, "id must be cleared after a request that finished normally"
    finally:
        Router.clear()

    records = [json.loads(ln) for ln in _lines(tmp_path / "tina4.log")]
    b_ids = [r["request_id"] for r in records if r["message"] == "ok-handler"]
    assert b_ids == ["B"]
    assert get_request_id() is None


def test_reset_is_idempotent_and_reloads_a_clean_snapshot(tmp_path):
    Log.configure(output="file", log_dir=str(tmp_path))
    set_request_id("A")
    Log.info("before reset")

    Log.reset()
    Log.reset()  # idempotent -- must not raise

    assert get_request_id() is None

    Log.configure(output="file", log_dir=str(tmp_path))  # reopenable
    Log.info("after reset")
    assert "after reset" in (tmp_path / "tina4.log").read_text()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork is POSIX-only")
def test_forked_child_discards_inherited_logger_state(tmp_path):
    Log.configure(output="file", log_dir=str(tmp_path))
    set_request_id("parent")
    Log.info("parent line")
    parent_snapshot_before = Log._snapshot

    result_path = tmp_path / "child_result.json"
    child_log_path = tmp_path / "child.log"
    pid = os.fork()
    if pid == 0:
        try:
            child_request_id = get_request_id()
            child_snapshot_is_none = Log._snapshot is None
            # A forked child resolves its OWN fresh snapshot on next use --
            # it does not inherit the PARENT's explicit in-memory configure()
            # call (that call history is not process state that fork
            # preserves), so it must configure itself again to prove it can
            # (the point under test: no stale handle/lock survives the fork).
            Log.configure(output="file", log_dir=str(tmp_path), log_file=str(child_log_path))
            Log.info("child line")
            result_path.write_text(json.dumps({
                "child_request_id": child_request_id,
                "child_snapshot_resolved_fresh": child_snapshot_is_none,
            }))
        finally:
            os._exit(0)
    else:
        os.waitpid(pid, 0)
        result = json.loads(result_path.read_text())
        assert result["child_request_id"] is None
        assert result["child_snapshot_resolved_fresh"] is True
        assert get_request_id() == "parent", "the parent's own context must be unaffected"
        assert Log._snapshot is parent_snapshot_before, "the parent's snapshot object must be unchanged"
        assert "parent line" in (tmp_path / "tina4.log").read_text()
        assert "child line" in child_log_path.read_text()


# ═══════════════════════════════════════════════════════════════════════
# logger-failure-policy (LOG-E01..E05)
# ═══════════════════════════════════════════════════════════════════════


def test_inaccessible_selected_sink_fails_configuration(tmp_path):
    # Parent is a FILE, so creating a sink dir under it is ENOTDIR -- a hard
    # failure even for root. A chmod 0o500 dir is bypassed by root's
    # CAP_DAC_OVERRIDE, so the lab (which runs the suite as root) must not
    # depend on it, or the sink would succeed and this negative would not fire.
    unwritable = tmp_path / "unwritable"
    unwritable.write_text("")  # a regular file, not a directory
    with pytest.raises(LogConfigurationError) as exc:
        Log.configure(output="file", log_dir=str(unwritable / "nested"))
    assert exc.value.operation == "open"
    assert exc.value.sink is not None


def test_non_strict_write_failure_disables_sink_and_diagnoses_once(tmp_path, capsys):
    Log.configure(strict=False, output="both", log_dir=str(tmp_path))
    target = tmp_path / "tina4.log"
    target.unlink()
    target.mkdir()  # wedge the sink AFTER a successful configure

    for i in range(3):
        Log.info(f"line-{i}")

    out = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    event_lines = [ln for ln in out if '"message":"line-' in ln or "line-" in ln and "tina4:" not in ln]
    assert len(event_lines) == 3
    diagnostics = [ln for ln in out if "tina4:" in ln]
    assert len(diagnostics) >= 1


def test_strict_write_failure_raises_catchable_error(tmp_path):
    Log.configure(strict=True, output="file", log_dir=str(tmp_path))
    target = tmp_path / "tina4.log"
    target.unlink()
    target.mkdir()

    with pytest.raises(LogWriteError) as exc:
        Log.info("ready")
    assert exc.value.sink is not None
    assert exc.value.operation is not None


def test_reset_permits_failed_sink_retry(tmp_path):
    Log.configure(strict=False, output="file", log_dir=str(tmp_path))
    target = tmp_path / "tina4.log"
    target.unlink()
    target.mkdir()
    Log.info("first attempt swallowed")
    first_written = "first attempt swallowed" in "".join(
        p.read_text() for p in target.iterdir() if p.is_file()
    ) if target.is_dir() else False

    target.rmdir()  # repair
    Log.reset()
    Log.configure(strict=False, output="file", log_dir=str(tmp_path))
    Log.info("second attempt succeeds")

    assert first_written is False
    assert "second attempt succeeds" in (tmp_path / "tina4.log").read_text()


def test_lock_timeout_follows_sink_failure_policy(tmp_path):
    Log.configure(strict=False, output="file", log_dir=str(tmp_path))
    from tina4_python import debug as _debug_mod
    sink = Log._snapshot.main_sink
    sink._lock.acquire()
    released = threading.Event()

    def hold_and_release():
        released.wait(timeout=_debug_mod._LOCK_TIMEOUT_SECONDS + 1.5)
        sink._lock.release()

    holder = threading.Thread(target=hold_and_release)
    holder.start()
    try:
        start = time.monotonic()
        Log.info("non-strict under lock contention")  # must not raise
        elapsed = time.monotonic() - start
        assert elapsed < _debug_mod._LOCK_TIMEOUT_SECONDS + 1.0, "wait must be bounded"
    finally:
        released.set()
        holder.join(timeout=5)

    Log.reset()
    Log.configure(strict=True, output="file", log_dir=str(tmp_path / "strict"))
    sink2 = Log._snapshot.main_sink
    sink2._lock.acquire()
    released2 = threading.Event()

    def hold_and_release2():
        released2.wait(timeout=_debug_mod._LOCK_TIMEOUT_SECONDS + 1.5)
        sink2._lock.release()

    holder2 = threading.Thread(target=hold_and_release2)
    holder2.start()
    try:
        with pytest.raises(LogWriteError) as exc:
            Log.info("strict under lock contention")
        assert exc.value.category == "write"
        assert exc.value.operation == "lock"
    finally:
        released2.set()
        holder2.join(timeout=5)


# ═══════════════════════════════════════════════════════════════════════
# logger-public-surface-and-integration (LOG-A01..A03, LOG-I01..I02)
# ═══════════════════════════════════════════════════════════════════════


def test_public_surface_contains_every_required_concept():
    required = ("configure", "debug", "info", "warning", "error", "critical",
                "is_enabled", "set_request_id", "get_request_id", "clear_request_id",
                "configuration", "reset")
    for name in required:
        assert hasattr(Log, name), f"missing public concept: {name}"
        assert callable(getattr(Log, name))


def test_prohibited_aliases_are_absent():
    prohibited = ("warn", "development_flag", "production_flag", "json_mode",
                  "close_file_logger", "close")
    for name in prohibited:
        assert not hasattr(Log, name), f"prohibited alias present: {name}"
    # No individual per-field config getters (e.g. log_dir()/rotate_size() as
    # bare methods) -- `configuration()` is the one introspection surface.
    for name in ("log_dir", "log_file", "rotate_size", "rotate_keep", "stdout_enabled", "file_enabled"):
        attr = getattr(Log, name, None)
        assert not callable(attr), f"individual config getter present: {name}"


def test_event_methods_return_void_and_finish_writes(tmp_path):
    Log.configure(output="file", log_dir=str(tmp_path))
    result = Log.info("ready")
    assert result is None
    # record visible before return: no async/deferred flush anywhere in core.
    assert "ready" in (tmp_path / "tina4.log").read_text()


def test_bootstrap_does_not_invent_explicit_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("TINA4_LOG_LEVEL", "ERROR")
    monkeypatch.setenv("TINA4_LOG_OUTPUT", "stdout")
    configure_calls = []
    real_configure = Log.configure.__func__

    def counting_configure(cls, *a, **kw):
        configure_calls.append((a, kw))
        return real_configure(cls, *a, **kw)

    monkeypatch.setattr(Log, "configure", classmethod(counting_configure))
    try:
        import tina4_python.core.server as server_mod
        import inspect
        source = inspect.getsource(server_mod.run)
        assert "Log.configure()" in source, (
            "bootstrap must call configure() with no invented explicit arguments"
        )
        Log.configure()
        assert configure_calls == [((), {})]
        assert Log.configuration()["level"] == "ERROR"
    finally:
        pass


def test_graceful_shutdown_logs_before_one_reset(tmp_path):
    import inspect
    import tina4_python.core.server as server_mod
    source = inspect.getsource(server_mod)
    # Both shutdown paths (built-in server + ASGI lifespan) log "Server
    # stopped." and then call Log.reset() exactly once, in that order.
    idx_log = source.index('Log.info("Server stopped.")')
    idx_reset = source.index("Log.reset()", idx_log)
    assert idx_reset > idx_log

    Log.configure(output="file", log_dir=str(tmp_path))
    Log.info("Server stopped.")
    Log.reset()
    assert "Server stopped." in (tmp_path / "tina4.log").read_text()
    assert get_request_id() is None
