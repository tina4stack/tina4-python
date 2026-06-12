# Tina4 Debug — Structured logging with rotation.
"""
Zero-dependency structured logger.

    from tina4_python.debug import Log

    Log.info("Request completed", method="GET", path="/api/users", duration_ms=45)
    Log.error("Database failed", error="connection refused")

Production: JSON lines → logs/tina4.log (with rotation)
Development: Human-readable → stdout + logs/tina4.log

Environment variables (all optional — defaults match v2 behaviour):
    TINA4_LOG_FILE          Log filename. Empty string = stdout only.
    TINA4_LOG_DIR           Directory for log files (default: "logs"). Joined
                            with TINA4_LOG_FILE unless that is absolute.
    TINA4_LOG_FORMAT        "text" (default) or "json".
    TINA4_LOG_OUTPUT        "stdout" (default), "file", or "both".
    TINA4_LOG_ROTATE_SIZE   Bytes per file before rotation. Default 10 MB.
                            Set to 0 to disable rotation.
    TINA4_LOG_ROTATE_KEEP   Number of rotated files to keep (default: 5).
    TINA4_LOG_CRITICAL      When truthy, Log.critical(...) is accepted and
                            mapped to error level. Default: false.
    TINA4_LOG_MAX_SIZE      [legacy] Megabytes per file. Used only when
                            TINA4_LOG_ROTATE_SIZE is unset (back-compat).
    TINA4_LOG_KEEP          [legacy] Alias for TINA4_LOG_ROTATE_KEEP.
"""
import os
import re
import json
import logging
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


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


class _LogWriter:
    """File writer with numbered rotation support — used as the default
    fallback when TINA4_LOG_FILE is unset (legacy "logs/tina4.log" path).

    Rotation scheme:
        tina4.log → tina4.log.1 → tina4.log.2 → ... → tina4.log.{keep}
    """

    def __init__(self, log_dir: str = "logs", filename: str = "tina4.log",
                 max_size_mb: int = 10, keep: int = 5):
        self.log_dir = Path(log_dir)
        self.filename = filename
        self.max_size = max_size_mb * 1024 * 1024
        self.keep = keep
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
                pass  # Can't write logs — don't crash the app


class _StdlibFileWriter:
    """Adapter around stdlib logging.handlers.RotatingFileHandler / FileHandler.

    Used when TINA4_LOG_FILE is set explicitly. Keeps the same .write(line)
    interface as _LogWriter so the Log class doesn't care which backend
    produced the file output.
    """

    def __init__(self, path: Path, max_bytes: int, backup_count: int):
        # Resolve dir up-front so callers can fail fast on a bad path.
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
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
                pass

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
    _is_production: bool = False
    _initialized: bool = False
    # Output toggles — driven by TINA4_LOG_OUTPUT.
    _stdout_enabled: bool = True
    _file_enabled: bool = True
    # Format — "text" or "json". Independent of _is_production so users
    # can opt into JSON in dev too (TINA4_LOG_FORMAT=json). Stored under
    # _format_mode so it doesn't clash with the legacy _format() method
    # name kept below for backward compatibility.
    _format_mode: str = "text"
    # Whether Log.critical() is accepted (TINA4_LOG_CRITICAL).
    _critical_enabled: bool = False

    LEVELS = {"debug": 0, "info": 1, "warning": 2, "error": 3}

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
            # "stdout" (default) — but we still keep file output on for
            # parity with v2 behaviour where logs/tina4.log is always
            # written. Operators who want stdout-only can flip the new
            # explicit "stdout-only" by setting TINA4_LOG_FILE="" AND
            # TINA4_LOG_OUTPUT=stdout — handled below where the file
            # path resolves to empty.
            cls._stdout_enabled = True
            cls._file_enabled = True

        # ── Format ───────────────────────────────────────────────
        fmt = os.environ.get("TINA4_LOG_FORMAT", "text").lower().strip()
        cls._format_mode = "json" if fmt == "json" else "text"

        # ── Critical level toggle ────────────────────────────────
        cls._critical_enabled = _is_truthy(os.environ.get("TINA4_LOG_CRITICAL"))

        # ── Rotation config ──────────────────────────────────────
        # New-style: TINA4_LOG_ROTATE_SIZE in BYTES (0 = disabled).
        # Legacy: TINA4_LOG_MAX_SIZE in MEGABYTES.
        rotate_size_env = os.environ.get("TINA4_LOG_ROTATE_SIZE")
        if rotate_size_env is not None:
            try:
                rotate_bytes = int(rotate_size_env)
            except ValueError:
                rotate_bytes = 10 * 1024 * 1024
        else:
            try:
                rotate_bytes = int(os.environ.get("TINA4_LOG_MAX_SIZE", "10")) * 1024 * 1024
            except ValueError:
                rotate_bytes = 10 * 1024 * 1024

        keep_env = os.environ.get("TINA4_LOG_ROTATE_KEEP", os.environ.get("TINA4_LOG_KEEP", "5"))
        try:
            keep = int(keep_env)
        except ValueError:
            keep = 5

        # ── File path resolution ─────────────────────────────────
        log_file = os.environ.get("TINA4_LOG_FILE", "")
        log_dir_env = os.environ.get("TINA4_LOG_DIR", log_dir)

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
            cls._writer = _StdlibFileWriter(resolved, rotate_bytes, keep)
        elif cls._file_enabled:
            # Default behaviour: keep the existing logs/tina4.log writer
            # so v2 deployments don't need to change a thing.
            mb = max(1, rotate_bytes // (1024 * 1024)) if rotate_bytes > 0 else 10
            cls._writer = _LogWriter(log_dir_env, "tina4.log", mb, keep)

        # Error mirror — only when no explicit TINA4_LOG_FILE is set.
        # When the operator points at a custom file they almost certainly
        # don't want a second sibling error.log appearing alongside it.
        if not log_file and cls._file_enabled:
            mb = max(1, rotate_bytes // (1024 * 1024)) if rotate_bytes > 0 else 10
            cls._error_writer = _LogWriter(log_dir_env, "error.log", mb, keep)
        else:
            cls._error_writer = None

        cls._initialized = True

    @classmethod
    def _should_log(cls, level: str) -> bool:
        return cls.LEVELS.get(level, 0) >= cls.LEVELS.get(cls._level, 0)

    # ANSI color codes for dev mode (matching PHP reference)
    COLORS = {
        "debug": "\033[36m",     # Cyan
        "info": "\033[32m",      # Green
        "warning": "\033[33m",   # Yellow
        "error": "\033[31m",     # Red
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

        # JSON format wins whenever the explicit env opt-in is set,
        # regardless of production flag (so dev devs can ship JSON to
        # `jq` if they prefer).
        if cls._format_mode == "json" or cls._is_production:
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

        # Human-readable for development
        level_str = level.upper().ljust(7)
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
    def _log(cls, level: str, message: str, **kwargs):
        # File always gets ALL levels (no filtering for file output)
        line = cls._format_line(level, message, **kwargs)

        # Console output respects TINA4_LOG_LEVEL and the stdout toggle.
        # v3.13.14: stdout is NOT suppressed in production — containers
        # treat stdout as the canonical log sink (docker logs / k8s read
        # PID 1 stdout), and the pre-v3.13.14 `not _is_production` gate
        # meant deployed containers got nothing. Production still emits
        # JSON (see _format_line / _is_production), just on stdout now.
        # flush=True so logs appear immediately on a non-TTY pipe rather
        # than sitting in Python's block buffer until the process exits.
        if cls._stdout_enabled and cls._should_log(level):
            color = "" if cls._is_production else cls.COLORS.get(level, "")
            reset = "" if cls._is_production else cls.RESET
            print(f"{color}{line}{reset}", flush=True)

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
        """Critical-level log — accepted only when TINA4_LOG_CRITICAL=true.

        Maps to error so existing log consumers (alerting, error.log)
        keep working. When the toggle is off the call is a no-op so
        deployments that have standardised on debug/info/warning/error
        don't get surprise log lines.
        """
        if cls._critical_enabled:
            cls._log("error", message, **kwargs)
