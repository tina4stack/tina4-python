# Tina4 Debug — Structured logging with rotation.
"""
Zero-dependency structured logger.

    from tina4_python.debug import Log

    Log.info("Request completed", method="GET", path="/api/users", duration_ms=45)
    Log.error("Database failed", error="connection refused")

Production: JSON lines → logs/tina4.log (with rotation)
Development: Human-readable → stdout + logs/tina4.log
"""
import os
import re
import json
import threading
from datetime import datetime, timezone
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


class _LogWriter:
    """File writer with numbered rotation support.

    Rotation scheme:
        tina4.log → tina4.log.1 → tina4.log.2 → ... → tina4.log.{keep}

    When tina4.log exceeds max_size:
    1. Delete tina4.log.{keep} if it exists
    2. Rename tina4.log.{n} → tina4.log.{n+1} for all existing rotated files
    3. Rename tina4.log → tina4.log.1
    4. Create new empty tina4.log
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


class Log:
    """Structured logger with request ID tracking and log rotation."""

    _writer: _LogWriter | None = None
    _error_writer: _LogWriter | None = None
    _level: str = "info"
    _is_production: bool = False
    _initialized: bool = False

    LEVELS = {"debug": 0, "info": 1, "warning": 2, "error": 3}

    @classmethod
    def init(cls, log_dir: str = "logs", level: str = "info",
             production: bool = False):
        """Initialize the logger. Called once at startup."""
        cls._level = level.lower()
        cls._is_production = production

        # Read rotation config from env (with defaults)
        max_size_mb = int(os.environ.get("TINA4_LOG_MAX_SIZE", "10"))
        keep = int(os.environ.get("TINA4_LOG_KEEP", "5"))

        cls._writer = _LogWriter(log_dir, "tina4.log", max_size_mb, keep)
        cls._error_writer = _LogWriter(log_dir, "error.log", max_size_mb, keep)
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

    @classmethod
    def _format(cls, level: str, message: str, **kwargs) -> str:
        timestamp = cls._timestamp()
        request_id = get_request_id()

        if cls._is_production:
            # JSON format for production
            entry = {
                "timestamp": timestamp,
                "level": level.upper(),
                "message": message,
            }
            if request_id:
                entry["request_id"] = request_id
            if kwargs:
                entry["context"] = {k: v for k, v in kwargs.items()}
            return json.dumps(entry, default=str)
        else:
            # Human-readable for development
            level_str = level.upper().ljust(7)
            parts = [timestamp, f"[{level_str}]"]
            if request_id:
                parts.append(f"[{request_id}]")
            parts.append(message)
            if kwargs:
                parts.append(json.dumps(kwargs, default=str))
            return " ".join(parts)

    @classmethod
    def _log(cls, level: str, message: str, **kwargs):
        # File always gets ALL levels (no filtering for file output)
        line = cls._format(level, message, **kwargs)

        # Console output respects TINA4_LOG_LEVEL
        if not cls._is_production and cls._should_log(level):
            color = cls.COLORS.get(level, "")
            print(f"{color}{line}{cls.RESET}")

        # Always write ALL levels to file (raw log, no filtering)
        if cls._writer:
            cls._writer.write(line)

        # Write errors to separate file
        if level == "error" and cls._error_writer:
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
