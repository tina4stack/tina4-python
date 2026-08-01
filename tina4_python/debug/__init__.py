# Tina4 Debug — Structured logging with rotation.
"""
Zero-dependency structured logger.

    from tina4_python.debug import Log

    Log.info("Request completed", method="GET", path="/api/users", duration_ms=45)
    Log.error("Database failed", error="connection refused")

FORMAT IS TEXT BY DEFAULT, in every environment. Only TINA4_LOG_FORMAT=json
selects JSON. Nothing else may — the implicit "production means JSON" switch was
DELETED on 2026-08-01 because "production" meant four different things across
the four frameworks (Node: TINA4_DEBUG unset; Ruby: TINA4_ENV/RACK_ENV/RUBY_ENV;
Python: only Log.configure(production=True); PHP: no switch at all, JSON always),
so the same machine with the same .env produced four different log formats and
your format was picked for you by a variable you never associated with logging.
An OBJECT passed as the message is still JSON-encoded INLINE inside the text
line — that is what makes a text log useful, and it is unchanged.

CONFIG IS RESOLVED ON FIRST USE. TINA4_LOG_* used to be read only inside
configure(), which only the server calls, so any script, worker, CLI tool or
test that logged without booting a server silently got the class defaults and
ignored the operator's .env entirely. configure() still works and still wins as
an explicit override.

Environment variables (all optional):
    TINA4_LOG_FILE          Log filename. Empty string = stdout only.
    TINA4_LOG_DIR           Directory for log files (default: "logs"). Joined
                            with TINA4_LOG_FILE unless that is absolute.
    TINA4_LOG_FORMAT        "text" (default) or "json".
    TINA4_LOG_OUTPUT        "stdout" (default), "file", or "both".
    TINA4_LOG_LEVEL         Console verbosity (default: "info"). Read on the
                            first-use path; configure(level=...) overrides it.
    TINA4_LOG_ROTATE_SIZE   Bytes per file before rotation. Default 10 MB.
                            Set to 0 to disable rotation.
    TINA4_LOG_ROTATE_KEEP   Number of rotated files to keep (default: 5).
    TINA4_LOG_APPEND        Append (default) or truncate the file at startup.
    TINA4_LOG_STRICT        Truthy = a log-write failure RAISES instead of
                            being swallowed.
    TINA4_LOG_FUNC          Truthy = include the calling function name.

Breaking (2026-08-01): the legacy aliases TINA4_LOG_MAX_SIZE and TINA4_LOG_KEEP
are GONE. Use TINA4_LOG_ROTATE_SIZE (BYTES, not megabytes) and
TINA4_LOG_ROTATE_KEEP. TINA4_LOG_MAX_SIZE=10 becomes
TINA4_LOG_ROTATE_SIZE=10485760.
"""
import os
import re
import json
import logging
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


# The logger must never be surprised by what it is handed, and must never be
# the reason a request dies. Anything can arrive as a message: a dict from a
# handler, a bytes payload off a socket, a 10MB string. Every framework coerces
# to text the same way (feature 2 of the feature audit).
_STDOUT_MAX_CHARS = 2000
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _coerce_message(message) -> str:
    """Turn anything into a single safe line of text.

    A str passes through. Bytes are decoded when they are valid UTF-8 and
    described when they are not - dumping raw bytes at a terminal garbles it and
    can emit escape sequences. Anything else is JSON, because a dict rendered as
    text is the whole reason the caller logged it; a value JSON cannot represent
    falls back to repr rather than raising. Logging a dict used to raise
    TypeError from str.join and take the request down with it.
    """
    if isinstance(message, str):
        text = message
    elif isinstance(message, (bytes, bytearray, memoryview)):
        raw = bytes(message)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return f"<binary {len(raw)} bytes>"
    else:
        try:
            # Compact separators so the rendered line is byte-identical to the
            # other three (PHP/Ruby/Node all emit {"a":1}, not {"a": 1}).
            text = json.dumps(message, default=str, separators=(",", ":"))
        except (TypeError, ValueError):
            text = repr(message)
    return _CONTROL_CHARS.sub("", text)


def _truncate_for_stdout(line: str) -> str:
    """Cap a console line. The file keeps the whole thing; a terminal does not."""
    if len(line) <= _STDOUT_MAX_CHARS:
        return line
    return f"{line[:_STDOUT_MAX_CHARS]}... (truncated, {len(line)} chars)"


def _target_is_file(path: str) -> bool:
    """Is this target a FILE PATH or a DIRECTORY?

    An existing directory is always a directory, extension or not. Otherwise a
    basename with an extension (app.log, app.txt) is a file and anything else is
    a directory to create, so the path need not exist yet. Identical rule in all
    four frameworks (feature 2 of the feature audit).
    """
    if os.path.isdir(path):
        return False
    base = os.path.basename(path)
    return "." in base and not base.startswith(".")


# Request ID context (set per-request by middleware)
_request_id_var = threading.local()

# Regex to strip ANSI escape codes
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def set_request_id(request_id: str):
    """Set the current request ID (called by middleware)."""
    _request_id_var.id = request_id


def get_request_id() -> str | None:
    """Get the current request ID."""
    return getattr(_request_id_var, "id", None)


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return _ANSI_RE.sub("", text)


def _is_truthy(val) -> bool:
    return str(val or "").strip().lower() in ("true", "1", "yes", "on")


def _reraise_write_error(record):
    """Re-raise the log-write failure stdlib logging is trying to swallow.

    Installed as ``Handler.handleError`` when TINA4_LOG_STRICT is truthy. A bare
    ``raise`` re-raises the exception currently being handled, and handleError is
    only ever called from inside ``emit``'s except block, so the original OSError
    (not a new one) reaches the caller.
    """
    raise


class _LogWriter:
    """File writer with numbered rotation support — used as the default
    fallback when TINA4_LOG_FILE is unset (legacy "logs/tina4.log" path).

    Rotation scheme:
        tina4.log → tina4.log.1 → tina4.log.2 → ... → tina4.log.{keep}
    """

    def __init__(self, log_dir: str = "logs", filename: str = "tina4.log",
                 max_size_mb: int = 10, keep: int = 5, strict: bool = False):
        self.log_dir = Path(log_dir)
        self.filename = filename
        self.max_size = max_size_mb * 1024 * 1024
        self.keep = keep
        # TINA4_LOG_STRICT. Documented on all four env-var pages and, before
        # 2026-08-01, implemented ONLY in Ruby — a documented no-op in the other
        # three. See write().
        self.strict = strict
        self._lock = threading.Lock()
        self._ensure_dir()

    def _ensure_dir(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _log_path(self) -> Path:
        return self.log_dir / self.filename

    def _rotate_if_needed(self):
        log_path = self._log_path()

        if not log_path.exists():
            return

        try:
            if log_path.stat().st_size < self.max_size:
                return
        except OSError:
            return

        # Delete the oldest rotated file if it exists
        oldest = self.log_dir / f"{self.filename}.{self.keep}"
        if oldest.exists():
            try:
                oldest.unlink()
            except OSError:
                pass

        # Shift existing rotated files: .{n} → .{n+1}
        for n in range(self.keep - 1, 0, -1):
            src = self.log_dir / f"{self.filename}.{n}"
            dst = self.log_dir / f"{self.filename}.{n + 1}"
            if src.exists():
                try:
                    src.rename(dst)
                except OSError:
                    pass

        # Rename current log to .1
        try:
            log_path.rename(self.log_dir / f"{self.filename}.1")
        except OSError:
            pass

    def write(self, line: str):
        """Write a line to the log file, stripping ANSI codes. Rotates if needed."""
        clean_line = _strip_ansi(line)
        with self._lock:
            self._rotate_if_needed()
            log_path = self._log_path()
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(clean_line + "\n")
            except OSError:
                # Default: can't write logs — don't crash the app.
                # TINA4_LOG_STRICT flips that: an audit trail you cannot write
                # is worse than a crash when the operator has said so.
                if self.strict:
                    raise


class _StdlibFileWriter:
    """Adapter around stdlib logging.handlers.RotatingFileHandler / FileHandler.

    Used when TINA4_LOG_FILE is set explicitly. Keeps the same .write(line)
    interface as _LogWriter so the Log class doesn't care which backend
    produced the file output.
    """

    def __init__(self, path: Path, max_bytes: int, backup_count: int,
                 strict: bool = False):
        # Resolve dir up-front so callers can fail fast on a bad path.
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.strict = strict   # TINA4_LOG_STRICT — see write()
        if max_bytes > 0:
            self._handler = RotatingFileHandler(
                str(path),
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
        else:
            # 0 disables rotation — use a plain FileHandler so the file just
            # grows. Matches the documented contract for TINA4_LOG_ROTATE_SIZE=0.
            self._handler = logging.FileHandler(str(path), encoding="utf-8")
        # Bare formatter — Log already builds the full line itself.
        self._handler.setFormatter(logging.Formatter("%(message)s"))
        if strict:
            # stdlib logging swallows write failures INSIDE Handler.emit and
            # routes them to handleError(), which only prints to stderr. A plain
            # `except OSError: raise` around emit() below can therefore never
            # fire, and TINA4_LOG_STRICT would be a no-op through this writer —
            # the exact trap Ruby hit, where ::Logger::LogDevice swallowed the
            # error one layer BELOW Tina4's own rescue. handleError is the
            # stdlib's own seam for this, so re-raise through it.
            self._handler.handleError = _reraise_write_error
        self._lock = threading.Lock()

    def write(self, line: str):
        clean = _strip_ansi(line)
        record = logging.LogRecord(
            name="tina4",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=clean,
            args=(),
            exc_info=None,
        )
        with self._lock:
            try:
                self._handler.emit(record)
                self._handler.flush()
            except OSError:
                if self.strict:
                    raise

    def close(self):
        try:
            self._handler.close()
        except Exception:
            pass


class Log:
    """Structured logger with request ID tracking and log rotation."""

    _writer: _LogWriter | _StdlibFileWriter | None = None
    _error_writer: _LogWriter | None = None
    _level: str = "info"
    # Production affects the CONSOLE PRESENTATION only (no ANSI colour). It has
    # not selected the log FORMAT since 2026-08-01 — see _format_line.
    _is_production: bool = False
    _initialized: bool = False
    # Output toggles — driven by TINA4_LOG_OUTPUT.
    _stdout_enabled: bool = True
    _file_enabled: bool = True
    # Format — "text" or "json", set ONLY by TINA4_LOG_FORMAT. Stored under
    # _format_mode so it doesn't clash with the legacy _format() method
    # name kept below for backward compatibility.
    _format_mode: str = "text"
    # TINA4_LOG_STRICT — raise on a log-write failure instead of swallowing it.
    _strict: bool = False
    LEVELS = {"debug": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}

    @classmethod
    def _resolve_env(cls):
        """Resolve TINA4_LOG_* on FIRST USE, if configure() never ran.

        MEASURED 2026-08-01: Ruby and Node resolved lazily, Python and PHP read
        TINA4_LOG_* only inside configure() — and only the SERVER calls
        configure(). So a worker, a CLI tool, a cron script or a test that
        logged without booting a server silently got the class defaults and
        ignored the operator's .env completely; worse, those defaults were
        OPPOSITE across frameworks (python: stdout + text + no file;
        php: no stdout + files in ./logs + json). One .env, four behaviours.

        configure() remains the explicit override and always wins: it sets
        _initialized, which turns this into a no-op.
        """
        if cls._initialized:
            return
        cls.configure(level=os.environ.get("TINA4_LOG_LEVEL", "info") or "info")

    @classmethod
    def configure(cls, log_dir: str = "logs", level: str = "info",
                  production: bool = False):
        """Configure the logger. Called once at startup.

        Reads the new TINA4_LOG_* env vars (rotation size/keep, format,
        output, file, dir, critical) so individual deployments can tune
        the logger without code changes. Defaults preserve existing
        behaviour: file output to logs/tina4.log + stdout, text format,
        10 MB rotation, keep 5.
        """
        cls._level = level.lower()
        cls._is_production = production

        # ── Output channels ──────────────────────────────────────
        output = os.environ.get("TINA4_LOG_OUTPUT", "stdout").lower().strip()
        if output == "file":
            cls._stdout_enabled = False
            cls._file_enabled = True
        elif output == "both":
            cls._stdout_enabled = True
            cls._file_enabled = True
        else:
            # "stdout" (default): stdout is ALWAYS on. The log FILE is written
            # only in development (TINA4_DEBUG truthy). In production /
            # containers a logs/tina4.log + error.log just bloat the writable
            # layer and disk, and 12-factor wants logs on stdout for the
            # platform to capture. Explicit TINA4_LOG_OUTPUT=file/both (or an
            # explicit TINA4_LOG_FILE path) overrides this and writes a file.
            cls._stdout_enabled = True
            cls._file_enabled = _is_truthy(os.environ.get("TINA4_DEBUG"))

        # ── Format ───────────────────────────────────────────────
        fmt = os.environ.get("TINA4_LOG_FORMAT", "text").lower().strip()
        cls._format_mode = "json" if fmt == "json" else "text"

        # ── Rotation config ──────────────────────────────────────
        # TINA4_LOG_ROTATE_SIZE is in BYTES (0 = rotation disabled).
        #
        # Breaking (2026-08-01): the legacy aliases TINA4_LOG_MAX_SIZE (in
        # MEGABYTES) and TINA4_LOG_KEEP were DELETED. They were documented for
        # all four frameworks and implemented in only two, and the size alias
        # took a different UNIT from the name it aliased — so the same .env
        # rotated at 10 MB here and at 10 BYTES nowhere else. One canonical name
        # per setting; rename the primary rather than keep an alias.
        # Migration: TINA4_LOG_MAX_SIZE=10 -> TINA4_LOG_ROTATE_SIZE=10485760,
        #            TINA4_LOG_KEEP=n      -> TINA4_LOG_ROTATE_KEEP=n.
        try:
            rotate_bytes = int(os.environ.get("TINA4_LOG_ROTATE_SIZE", 10 * 1024 * 1024))
        except ValueError:
            rotate_bytes = 10 * 1024 * 1024

        try:
            keep = int(os.environ.get("TINA4_LOG_ROTATE_KEEP", "5"))
        except ValueError:
            keep = 5

        # ── Strict mode ──────────────────────────────────────────
        # TINA4_LOG_STRICT: a log-write failure RAISES instead of being
        # swallowed. Documented on all four env-var pages since forever and,
        # until 2026-08-01, implemented ONLY in Ruby.
        cls._strict = _is_truthy(os.environ.get("TINA4_LOG_STRICT"))

        # ── File path resolution ─────────────────────────────────
        # `log_dir` accepts a DIRECTORY or a FILE PATH. Passing a file path used
        # to create a DIRECTORY with that name (logs/app.log/tina4.log), which is
        # never what anyone means (feature 2 of the feature audit). Identical
        # rule in all four: an existing directory is a directory; otherwise a
        # basename with an extension is a file.
        log_file = os.environ.get("TINA4_LOG_FILE", "")
        log_dir_env = os.environ.get("TINA4_LOG_DIR", log_dir)
        if not log_file and _target_is_file(log_dir_env):
            log_file = log_dir_env
            log_dir_env = os.path.dirname(log_dir_env) or "."

        # TINA4_LOG_APPEND — append (default) or overwrite on startup.
        #
        # APPEND IS THE DEFAULT: a log you can lose by restarting the process is
        # not a log. Set it false for one file per run (a short CLI, a test
        # fixture, a container shipping logs elsewhere); the file is truncated
        # once here at configure time, never per line.
        append_env = os.environ.get("TINA4_LOG_APPEND")
        cls._append = append_env is None or append_env.strip().lower() in (
            "1", "true", "yes", "on", "y", "t"
        )
        if not cls._append:
            target_dir = Path(log_dir_env)
            names = [os.path.basename(log_file)] if log_file else ["tina4.log", "error.log"]
            for name in names:
                path = Path(log_file) if log_file and os.path.isabs(log_file) else target_dir / name
                try:
                    if path.exists():
                        path.write_text("", encoding="utf-8")
                except OSError:
                    pass

        # Close any previous writer so reconfigure during tests doesn't
        # leak file handles.
        if isinstance(cls._writer, _StdlibFileWriter):
            cls._writer.close()
        cls._writer = None

        if log_file:
            # Explicit log file path. Honour absolute paths verbatim;
            # otherwise join with TINA4_LOG_DIR per spec.
            if os.path.isabs(log_file):
                resolved = Path(log_file)
            else:
                resolved = Path(log_dir_env) / log_file
            cls._writer = _StdlibFileWriter(resolved, rotate_bytes, keep, cls._strict)
        elif cls._file_enabled:
            # Default behaviour: keep the existing logs/tina4.log writer
            # so v2 deployments don't need to change a thing.
            mb = max(1, rotate_bytes // (1024 * 1024)) if rotate_bytes > 0 else 10
            cls._writer = _LogWriter(log_dir_env, "tina4.log", mb, keep, cls._strict)

        # Error mirror — only when no explicit TINA4_LOG_FILE is set.
        # When the operator points at a custom file they almost certainly
        # don't want a second sibling error.log appearing alongside it.
        if not log_file and cls._file_enabled:
            mb = max(1, rotate_bytes // (1024 * 1024)) if rotate_bytes > 0 else 10
            cls._error_writer = _LogWriter(log_dir_env, "error.log", mb, keep, cls._strict)
        else:
            cls._error_writer = None

        cls._initialized = True

    @classmethod
    def _should_log(cls, level: str) -> bool:
        cls._resolve_env()
        return cls.LEVELS.get(level, 0) >= cls.LEVELS.get(cls._level, 0)

    # ANSI color codes for dev mode (matching PHP reference)
    COLORS = {
        "debug": "\033[36m",     # Cyan
        "info": "\033[32m",      # Green
        "warning": "\033[33m",   # Yellow
        "error": "\033[31m",     # Red
        "critical": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    @classmethod
    def _timestamp(cls) -> str:
        """ISO 8601 UTC timestamp with milliseconds: YYYY-MM-DDTHH:MM:SS.mmmZ"""
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

    # Frame names that belong to Log itself — walk past them when looking
    # for the real caller. Kept as a class attribute so subclasses can
    # extend if they layer extra wrappers (and so tests can introspect).
    _OWN_FRAMES = frozenset({
        "_caller_name", "_format_line", "_format", "_log",
        "debug", "info", "warning", "error", "critical",
    })

    @classmethod
    def _caller_name(cls) -> str | None:
        """Return the function name that called Log.{debug,info,warning,error}.

        Active only when ``TINA4_LOG_FUNC=true`` — the lookup uses
        ``inspect.currentframe()`` which is ~5% overhead per log call.
        Walks past Log's own frames (``_OWN_FRAMES``) to land on the
        real caller, so the count is robust whether the test calls
        ``_format_line`` directly or goes through ``Log.info`` →
        ``_log`` → ``_format_line``. Returns ``None`` if the stack is
        too shallow (e.g. log called from module import) or if anything
        goes wrong — never raises. Parity feature #41 across all four
        Tina4 frameworks.
        """
        import os
        if os.environ.get("TINA4_LOG_FUNC", "").strip().lower() not in (
            "1", "true", "on", "yes", "y", "t"
        ):
            return None
        try:
            import inspect
            frame = inspect.currentframe()
            # Walk past Log's own frames. Cap the walk at 16 to defend
            # against any pathological recursion / wrapper stack.
            for _ in range(16):
                if frame is None:
                    return None
                name = frame.f_code.co_name
                if name not in cls._OWN_FRAMES:
                    # Filter out anonymous / module-level callers — they're noise.
                    if name in ("<module>", "<lambda>", "<genexpr>", "<listcomp>", "<setcomp>", "<dictcomp>"):
                        return None
                    return name
                frame = frame.f_back
            return None
        except Exception:
            return None

    @classmethod
    def _format_line(cls, level: str, message: str, **kwargs) -> str:
        timestamp = cls._timestamp()
        request_id = get_request_id()
        caller = cls._caller_name()

        # TEXT BY DEFAULT, EVERYWHERE. Only TINA4_LOG_FORMAT=json selects JSON.
        #
        # `or cls._is_production` used to sit here, and it is deliberately GONE
        # (owner decision 2026-08-01). "Production" meant four different things
        # across the four frameworks — Node keyed off TINA4_DEBUG being unset,
        # Ruby off TINA4_ENV/RACK_ENV/RUBY_ENV, Python only off an explicit
        # configure(production=True), PHP had no switch at all and always shipped
        # JSON — so one machine with one .env produced four different formats and
        # your log format was chosen by a variable you never connected to
        # logging. An object passed as the message is still JSON-encoded inline
        # in the text line (see _coerce_message); that is the only implicit JSON
        # left, and it is the useful one.
        if cls._format_mode == "json":
            entry = {
                "timestamp": timestamp,
                "level": level.upper(),
                "message": message,
            }
            if request_id:
                entry["request_id"] = request_id
            if caller:
                entry["function"] = caller
            if kwargs:
                entry["context"] = {k: v for k, v in kwargs.items()}
            return json.dumps(entry, default=str)

        # Human-readable for development.
        #
        # Pad to 8, not 7: CRITICAL is eight characters, so a 7-wide column was
        # broken by our own highest level -- every other line aligned and the one
        # that matters most did not. 8 is the only width that fits every level
        # name. This is the cross-framework format table (feature 2 of the
        # feature audit); all four pad to 8 so a log-shipping regex or column
        # split tuned on one framework is not off by one on another.
        level_str = level.upper().ljust(8)
        parts = [timestamp, f"[{level_str}]"]
        if request_id:
            parts.append(f"[{request_id}]")
        if caller:
            parts.append(f"[{caller}]")
        parts.append(message)
        if kwargs:
            parts.append(json.dumps(kwargs, default=str))
        return " ".join(parts)

    # Kept under the old name so any external code calling Log._format
    # (e.g. tests) still works.
    @classmethod
    def _format(cls, level: str, message: str, **kwargs) -> str:
        return cls._format_line(level, message, **kwargs)

    @classmethod
    def _log(cls, level: str, message, **kwargs):
        # Resolve TINA4_LOG_* here, at the top of the real write path, if the
        # server never called configure(). _format_line runs BEFORE _should_log
        # below, so the resolution cannot be left to either of them.
        cls._resolve_env()

        # Coerce FIRST: a dict, a bytes payload or anything else must become
        # text before formatting, or the logger raises and takes the caller with
        # it. See _coerce_message.
        message = _coerce_message(message)

        # File always gets ALL levels (no filtering for file output)
        line = cls._format_line(level, message, **kwargs)

        # Console output respects TINA4_LOG_LEVEL and the stdout toggle.
        # v3.13.14: stdout is NOT suppressed in production — containers
        # treat stdout as the canonical log sink (docker logs / k8s read
        # PID 1 stdout), and the pre-v3.13.14 `not _is_production` gate
        # meant deployed containers got nothing. (Production no longer changes
        # the FORMAT — set TINA4_LOG_FORMAT=json if you want JSON there.)
        # flush=True so logs appear immediately on a non-TTY pipe rather
        # than sitting in Python's block buffer until the process exits.
        if cls._stdout_enabled and cls._should_log(level):
            # No ANSI in production (a log shipper reads this) and none in JSON
            # mode either — an escape sequence wrapped around a JSON object makes
            # the line unparseable, which would make the one format you can
            # explicitly ask for useless on stdout.
            plain = cls._is_production or cls._format_mode == "json"
            color = "" if plain else cls.COLORS.get(level, "")
            reset = "" if plain else cls.RESET
            # Truncate on the CONSOLE only. The file keeps the full line so a
            # consumer parsing it loses nothing; a terminal does not need 10MB.
            print(f"{color}{_truncate_for_stdout(line)}{reset}", flush=True)

        # Always write ALL levels to the main file (raw log, no filtering)
        if cls._writer:
            cls._writer.write(line)

        # Mirror WARNING and ERROR into the dedicated error log so
        # `tail -f logs/error.log` gives just the stuff worth looking
        # at, without wading through DEBUG / INFO noise. Parity with
        # tina4-php's Log class.
        if cls._error_writer and cls.LEVELS.get(level, 0) >= cls.LEVELS["warning"]:
            cls._error_writer.write(line)

    @classmethod
    def debug(cls, message: str, **kwargs):
        cls._log("debug", message, **kwargs)

    @classmethod
    def info(cls, message: str, **kwargs):
        cls._log("info", message, **kwargs)

    @classmethod
    def warning(cls, message: str, **kwargs):
        cls._log("warning", message, **kwargs)

    @classmethod
    def error(cls, message: str, **kwargs):
        cls._log("error", message, **kwargs)

    @classmethod
    def critical(cls, message: str, **kwargs):
        """Critical-level log — the highest severity (above error).

        Always emitted (like every other level) and written to error.log.
        Use it for unrecoverable, alert-worthy failures.
        """
        cls._log("critical", message, **kwargs)

    @classmethod
    def is_enabled(cls, level: str) -> bool:
        """Return True if a message at ``level`` would pass the configured
        minimum console level.

        This reflects console (stdout) visibility — the log file always
        records every level regardless of this threshold. Use it to skip
        building an expensive log payload that would not be shown::

            if Log.is_enabled("debug"):
                Log.debug("state", snapshot=expensive_dump())

        ``level`` is case-insensitive (``debug`` / ``info`` / ``warning`` /
        ``error`` / ``critical``).
        """
        return cls._should_log((level or "").lower())
