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
import json
import gzip
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path


# Request ID context (set per-request by middleware)
_request_id_var = threading.local()


def set_request_id(request_id: str):
    """Set the current request ID (called by middleware)."""
    _request_id_var.id = request_id


def get_request_id() -> str | None:
    """Get the current request ID."""
    return getattr(_request_id_var, "id", None)


class _LogWriter:
    """File writer with rotation support."""

    def __init__(self, log_dir: str = "logs", filename: str = "tina4.log",
                 max_size: int = 10 * 1024 * 1024, retain_days: int = 30,
                 compress: bool = True):
        self.log_dir = Path(log_dir)
        self.filename = filename
        self.max_size = max_size
        self.retain_days = retain_days
        self.compress = compress
        self._lock = threading.Lock()
        self._current_date = None
        self._file = None
        self._ensure_dir()

    def _ensure_dir(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _log_path(self) -> Path:
        return self.log_dir / self.filename

    def _rotate_if_needed(self):
        today = datetime.now().strftime("%Y-%m-%d")
        log_path = self._log_path()

        needs_rotate = False

        # Date-based rotation
        if self._current_date and self._current_date != today:
            needs_rotate = True

        # Size-based rotation
        if log_path.exists() and log_path.stat().st_size >= self.max_size:
            needs_rotate = True

        if needs_rotate and log_path.exists():
            # Close current file
            if self._file:
                self._file.close()
                self._file = None

            # Rename to dated file
            date_str = self._current_date or today
            stem = Path(self.filename).stem
            rotated = self.log_dir / f"{stem}.{date_str}.log"
            counter = 0
            while rotated.exists():
                counter += 1
                rotated = self.log_dir / f"{stem}.{date_str}.{counter}.log"

            log_path.rename(rotated)

            # Compress old logs (>2 days) in background
            if self.compress:
                threading.Thread(target=self._compress_old, daemon=True).start()

            # Prune old logs
            threading.Thread(target=self._prune_old, daemon=True).start()

        self._current_date = today

    def _compress_old(self):
        """Gzip log files older than 2 days."""
        cutoff = datetime.now().timestamp() - (2 * 86400)
        for f in self.log_dir.glob("*.log"):
            if f.name == self.filename:
                continue
            if f.stat().st_mtime < cutoff:
                gz_path = f.with_suffix(".log.gz")
                if not gz_path.exists():
                    try:
                        with open(f, "rb") as fin, gzip.open(gz_path, "wb") as fout:
                            shutil.copyfileobj(fin, fout)
                        f.unlink()
                    except OSError:
                        pass

    def _prune_old(self):
        """Delete logs older than retain_days."""
        cutoff = datetime.now().timestamp() - (self.retain_days * 86400)
        for f in self.log_dir.glob("*"):
            if f.name == self.filename:
                continue
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass

    def write(self, line: str):
        with self._lock:
            self._rotate_if_needed()
            log_path = self._log_path()
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
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
             production: bool = False, max_size: int = 10 * 1024 * 1024,
             retain_days: int = 30, compress: bool = True):
        """Initialize the logger. Called once at startup."""
        cls._level = level.lower()
        cls._is_production = production
        cls._writer = _LogWriter(log_dir, "tina4.log", max_size, retain_days, compress)
        cls._error_writer = _LogWriter(log_dir, "error.log", max_size, retain_days, compress)
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
        if not cls._should_log(level):
            return

        line = cls._format(level, message, **kwargs)

        # Always print to stdout in dev with ANSI colors
        if not cls._is_production:
            color = cls.COLORS.get(level, "")
            print(f"{color}{line}{cls.RESET}")

        # Write to file
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
