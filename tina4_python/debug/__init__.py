# Tina4 Debug — Structured logging with rotation (3.14 shared contract).
"""
Zero-dependency structured logger, conformant to the shared cross-framework
contract at ``plan/v3/fixtures/logger_contract.json`` (feature 2), decided in
``plan/v3/features/002-structured-logger.md`` and ADR-0041.

    from tina4_python.debug import Log

    Log.info("Request completed", context={"method": "GET", "path": "/api/users"})
    Log.error("Database failed", context={"error": "connection refused"})

BREAKING CHANGES from the pre-3.14 logger (this pass, 2026-08-13):

  * Format defaults to JSON in production and TEXT only when ``TINA4_DEBUG`` is
    truthy (Decision 3). The 2026-08-01 "text always unless TINA4_LOG_FORMAT=json"
    rule is superseded.
  * ``TINA4_LOG_APPEND`` is REMOVED -- setting it is now a hard configuration
    error. Logs always append; a caller wanting a clean file performs that
    explicit operation outside logger startup.
  * ``TINA4_LOG_MAX_SIZE`` / ``TINA4_LOG_KEEP`` / ``TINA4_DEBUG_LEVEL`` /
    ``TINA4_LOG_CRITICAL`` remain removed and now raise (previously some were
    silently ignored).
  * ``TINA4_LOG_STRICT`` / ``TINA4_LOG_FUNC`` accept ONLY the literal tokens
    ``true``/``false`` (case-insensitive) -- not ``1``/``yes``/``on``. Decision 19
    marks these "native booleans, not private truth-token parsing"; the shared
    fixture (LOG-V03) requires a non-boolean-shaped value (e.g. the numeral
    ``1``) to fail configuration rather than being coerced.
  * Embedded CR/LF in a message is now ESCAPED (``\\r``/``\\n`` literal two-char
    sequences) in text format rather than silently stripped, so a log call can
    never forge a second physical line (Decision 11).
  * New ``TINA4_LOG_FILE_LEVEL`` (default ``ALL``) independently gates the FILE
    sink; ``TINA4_LOG_LEVEL`` now gates the CONSOLE only (2026-08-10 owner
    override of Decision 8). ``is_enabled`` accepts an optional ``sink=`` and is
    sink-aware.
  * Rotation is now PREDICTIVE (checked before the append that would cross the
    threshold) rather than reactive, and an oversized single event is replaced
    by a bounded, valid overflow record instead of being written whole.
  * ``reset()`` is new: flushes/closes owned sinks and clears the snapshot AND
    the current execution context's request id.
  * A forked child discards inherited logger state (handles, snapshot, request
    id) and resolves its own snapshot on first use (``os.register_at_fork``).

Environment variables (Decision 19, all optional):
    TINA4_LOG_LEVEL         Console severity threshold. ALL|DEBUG|INFO|WARNING|
                             ERROR|CRITICAL|NONE, case-insensitive. Default INFO.
    TINA4_LOG_FILE_LEVEL     File severity threshold, same domain. Default ALL.
    TINA4_LOG_FORMAT        "text" or "json". Default: text when TINA4_DEBUG is
                             truthy, else json.
    TINA4_LOG_OUTPUT        "stdout", "file" or "both". Default: stdout always
                             on; file on only when TINA4_DEBUG is truthy.
    TINA4_LOG_DIR           Log directory (default "logs" under the project
                             root -- the current working directory).
    TINA4_LOG_FILE          Optional single log file name/path. Naming a file
                             does NOT by itself enable the file sink.
    TINA4_LOG_ROTATE_SIZE   Positive bytes per file before rotation, >= 1024.
                             Default 10485760 (10 MiB).
    TINA4_LOG_ROTATE_KEEP   Non-negative backup count. Default 5.
    TINA4_LOG_STRICT        "true"/"false". Raise on sink failures. Default false.
    TINA4_LOG_FUNC          "true"/"false". Include the calling function. Default false.

Removed settings that now hard-fail configuration: TINA4_LOG_MAX_SIZE,
TINA4_LOG_KEEP, TINA4_LOG_APPEND, TINA4_DEBUG_LEVEL, TINA4_LOG_CRITICAL.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import contextvars
from datetime import datetime, timezone
from pathlib import Path

# ── Error taxonomy (Decision 25 / section 9) ────────────────────────────────


class LogConfigurationError(ValueError):
    """Invalid setting, removed setting, or an inaccessible selected sink."""

    def __init__(self, message, *, setting=None, value=None, accepted=None,
                 sink=None, operation=None):
        super().__init__(message)
        self.category = "configuration"
        self.setting = setting
        self.value = value
        self.accepted = accepted
        self.sink = sink
        self.operation = operation


class LogArgumentError(ValueError):
    """Invalid argument to a public logger method."""

    def __init__(self, message, *, argument=None, accepted=None):
        super().__init__(message)
        self.category = "argument"
        self.argument = argument
        self.accepted = accepted


class LogWriteError(RuntimeError):
    """A selected sink failed after configuration succeeded, under strict mode."""

    def __init__(self, message, *, sink=None, operation=None):
        super().__init__(message)
        self.category = "write"
        self.sink = sink
        self.operation = operation


# ── Constants (fixture `constants` block) ───────────────────────────────────

LEVELS = {"ALL": 0, "DEBUG": 1, "INFO": 2, "WARNING": 3, "ERROR": 4, "CRITICAL": 5, "NONE": 6}
EVENT_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
FORMATS = ("text", "json")
OUTPUTS = ("stdout", "file", "both")

DEFAULT_LEVEL = "INFO"
DEFAULT_FILE_LEVEL = "ALL"
DEFAULT_FORMAT_DEBUG_TRUE = "text"
DEFAULT_FORMAT_DEBUG_FALSE = "json"
DEFAULT_ROTATE_SIZE = 10 * 1024 * 1024
DEFAULT_ROTATE_KEEP = 5
MIN_ROTATE_SIZE = 1024
STDOUT_MAX_BYTES = 8192
OVERFLOW_MESSAGE = "Log event omitted: encoded size exceeds sink limit"
_LOCK_TIMEOUT_SECONDS = 2.0

_JSON_KEY_ORDER = ("timestamp", "level", "message", "request_id", "function", "context")

_REMOVED_SETTINGS = {
    "TINA4_LOG_MAX_SIZE": "removed setting -- use TINA4_LOG_ROTATE_SIZE (bytes, not megabytes)",
    "TINA4_LOG_KEEP": "removed setting -- use TINA4_LOG_ROTATE_KEEP",
    "TINA4_LOG_APPEND": "removed setting -- logs always append; truncate explicitly outside logger startup",
    "TINA4_DEBUG_LEVEL": "removed setting -- use TINA4_LOG_LEVEL",
    "TINA4_LOG_CRITICAL": "removed setting -- critical always emits, subject only to TINA4_LOG_LEVEL",
}

_BOOL_TOKENS = {"true": True, "false": False}

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

COLORS = {
    "DEBUG": "\033[36m", "INFO": "\033[32m", "WARNING": "\033[33m",
    "ERROR": "\033[31m", "CRITICAL": "\033[35m",
}
RESET = "\033[0m"


# ── Request-id context (execution-local; Decision 12) ───────────────────────

_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "tina4_request_id", default=None
)

_REQUEST_ID_INVALID_RE = re.compile(r"[^A-Za-z0-9._-]")
_REQUEST_ID_MAX_LENGTH = 128


def set_request_id(request_id: str | None) -> None:
    """Set the current request ID (called by dispatch)."""
    _request_id_var.set(request_id)


def get_request_id() -> str | None:
    """Get the current request ID."""
    return _request_id_var.get()


def clear_request_id() -> None:
    """Clear the current execution context's request ID."""
    _request_id_var.set(None)


def sanitize_request_id(value: str | None) -> str | None:
    """Return an inbound X-Request-ID only if it is a safe correlation id."""
    if not value:
        return None
    if len(value) > _REQUEST_ID_MAX_LENGTH:
        return None
    if _REQUEST_ID_INVALID_RE.search(value):
        return None
    return value


def _after_fork_in_child():
    """A forked child discards inherited handles, locks and request context."""
    Log._snapshot = None
    Log._config_lock = threading.RLock()
    _request_id_var.set(None)


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_in_child)


# ── Native value normalization (Decision 14, section 6) ─────────────────────


def _is_finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decode_bytes(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return f"<binary {len(data)} bytes sha256={_sha256_hex(data)}>"


def _normalize(value, ancestors: frozenset = frozenset()):
    """Recursively normalize into the shared native domain.

    string / null / boolean / finite number / sequence / string-keyed map.
    A repeated (self-referential) container becomes "[Circular]"; anything
    outside the domain (non-finite float, arbitrary object) becomes
    "[Unsupported]" WITHOUT ever invoking the value's own stringification.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return _decode_bytes(bytes(value))
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else "[Unsupported]"
    if isinstance(value, (list, tuple)):
        oid = id(value)
        if oid in ancestors:
            return "[Circular]"
        nxt = ancestors | {oid}
        return [_normalize(v, nxt) for v in value]
    if isinstance(value, dict):
        oid = id(value)
        if oid in ancestors:
            return "[Circular]"
        nxt = ancestors | {oid}
        return {str(k): _normalize(v, nxt) for k, v in value.items()}
    return "[Unsupported]"


def _sort_keys_recursive(value):
    if isinstance(value, dict):
        return {k: _sort_keys_recursive(value[k]) for k in sorted(value.keys())}
    if isinstance(value, list):
        return [_sort_keys_recursive(v) for v in value]
    return value


def _compact_json(value) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _message_to_string(raw_message) -> str:
    """The top-level `message` field: a string passes through; anything else
    uses compact, key-sorted JSON spelling (Decision 14)."""
    if isinstance(raw_message, str):
        return raw_message
    if isinstance(raw_message, (bytes, bytearray, memoryview)):
        return _decode_bytes(bytes(raw_message))
    normalized = _normalize(raw_message)
    if normalized is None:
        return "null"
    if normalized is True:
        return "true"
    if normalized is False:
        return "false"
    if isinstance(normalized, (int, float)):
        return json.dumps(normalized)
    if isinstance(normalized, (list, dict)):
        return _compact_json(_sort_keys_recursive(normalized))
    return normalized  # already a marker string: [Unsupported] / [Circular] / <binary ...>


def _escape_text(s: str) -> str:
    """Escape backslash, CR, LF (in that order) and strip other C0/DEL so a
    text-format record is exactly one physical LF-terminated line (Decision 11)."""
    s = s.replace("\\", "\\\\")
    s = s.replace("\r", "\\r")
    s = s.replace("\n", "\\n")
    return _CONTROL_CHARS.sub("", s)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


# ── Canonical event + encoding (Decision 15) ────────────────────────────────


def _timestamp_now() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _build_event(level: str, message, request_id, caller_name, context) -> dict:
    event = {"timestamp": _timestamp_now(), "level": level, "message": _message_to_string(message)}
    if request_id:
        event["request_id"] = request_id
    if caller_name:
        event["function"] = caller_name
    if context:
        # Normalize the ORIGINAL object, not a shallow `dict(context)` copy: a
        # copy has a different id() from `context`, so a context that is
        # directly self-referential (context["self"] is context) would be
        # detected one hop too late -- `_normalize` already returns an
        # independent, freshly-built structure on its own (every dict/list it
        # walks is rebuilt), so no defensive copy is needed here first.
        normalized_ctx = _sort_keys_recursive(_normalize(context))
        if normalized_ctx:
            event["context"] = normalized_ctx
    return event


def _encode_json(event: dict) -> str:
    ordered = {k: event[k] for k in _JSON_KEY_ORDER if k in event}
    return _compact_json(ordered) + "\n"


def _encode_text(event: dict) -> str:
    level_str = event["level"].ljust(8)
    parts = [event["timestamp"], f"[{level_str}]"]
    if "request_id" in event:
        parts.append(f"[{event['request_id']}]")
    if "function" in event:
        parts.append(f"[{event['function']}]")
    parts.append(_escape_text(event["message"]))
    if "context" in event:
        parts.append(_compact_json(event["context"]))
    return " ".join(parts) + "\n"


def _encode(event: dict, fmt: str) -> str:
    return _encode_json(event) if fmt == "json" else _encode_text(event)


def _overflow_record(original_event: dict, original_encoded: str, fmt: str) -> str:
    """A bounded, valid replacement for an event that exceeds a sink's limit
    (Decision 7). Digest and byte count cover the ORIGINAL canonical record
    including its LF."""
    original_bytes = original_encoded.encode("utf-8")
    replacement = {
        "timestamp": original_event["timestamp"],
        "level": original_event["level"],
        "message": OVERFLOW_MESSAGE,
        "context": {
            "truncated": True,
            "original_bytes": len(original_bytes),
            "sha256": _sha256_hex(original_bytes),
        },
    }
    return _encode(replacement, fmt)


def _bounded_for_sink(event: dict, fmt: str, max_bytes: int) -> str:
    encoded = _encode(event, fmt)
    if len(encoded.encode("utf-8")) <= max_bytes:
        return encoded
    return _overflow_record(event, encoded, fmt)


# ── File sink: predictive rotation, single in-process lock (Decision 20) ────


class _FileSink:
    """One owned log file: bounded rotation guarded by a single in-process
    (thread) exclusive lock over the size check, rotation and append.

    Decision 20 (2026-08-10 owner override): SINGLE FILE + IN-PROCESS LOCK
    ONLY. Cross-process exclusive locking is deliberately not implemented;
    concurrent PROCESSES writing the same file may interleave. Run one file
    per process, or route through a log shipper, for that case.
    """

    def __init__(self, path: Path, rotate_size: int, rotate_keep: int):
        self.path = path
        self.rotate_size = rotate_size
        self.rotate_keep = rotate_keep
        self._lock = threading.Lock()
        self._closed = False

    def open(self) -> None:
        """Create the directory and prove the file is writable. Raises
        LogConfigurationError (never touches process state) on failure."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8"):
                pass
        except OSError as exc:
            raise LogConfigurationError(
                f"cannot open log sink {self.path}: {exc}",
                sink=str(self.path), operation="open",
            ) from exc

    def _rotate_locked(self, next_record_bytes: int) -> None:
        try:
            current_size = self.path.stat().st_size if self.path.exists() else 0
        except OSError:
            current_size = 0
        if current_size == 0:
            return
        if current_size + next_record_bytes <= self.rotate_size:
            return
        if self.rotate_keep <= 0:
            try:
                self.path.unlink()
            except OSError:
                pass
            return
        oldest = Path(f"{self.path}.{self.rotate_keep}")
        if oldest.exists():
            try:
                oldest.unlink()
            except OSError:
                pass
        for n in range(self.rotate_keep - 1, 0, -1):
            src = Path(f"{self.path}.{n}")
            dst = Path(f"{self.path}.{n + 1}")
            if src.exists():
                try:
                    src.rename(dst)
                except OSError:
                    pass
        try:
            self.path.rename(f"{self.path}.1")
        except OSError:
            pass

    def write(self, encoded_line: str) -> None:
        """Append one complete encoded record, rotating first if it would
        cross the threshold. Raises OSError/TimeoutError to the caller, which
        applies the sink failure policy."""
        clean = _strip_ansi(encoded_line)
        payload = clean.encode("utf-8")
        acquired = self._lock.acquire(timeout=_LOCK_TIMEOUT_SECONDS)
        if not acquired:
            raise TimeoutError(f"timed out acquiring the log sink lock for {self.path}")
        try:
            self._rotate_locked(len(payload))
            with open(self.path, "ab") as f:
                f.write(payload)
                f.flush()
        finally:
            self._lock.release()

    def close(self) -> None:
        self._closed = True


# ── Snapshot ─────────────────────────────────────────────────────────────


class _Snapshot:
    __slots__ = (
        "level", "file_level", "format", "output", "log_dir", "log_file",
        "layout", "rotate_size", "rotate_keep", "strict", "caller",
        "stdout_enabled", "file_enabled", "main_sink", "error_sink",
    )


def _is_truthy_debug() -> bool:
    """TINA4_DEBUG belongs to Feature 1 (framework-wide, lenient); Feature 2
    only reads it to derive its own defaults, never re-validates it."""
    raw = (os.environ.get("TINA4_DEBUG") or "").strip().lower()
    return raw in ("1", "true", "yes", "on", "y", "t")


def _parse_bool_setting(name: str, default: bool) -> bool:
    if name not in os.environ:
        return default
    raw = os.environ[name].strip().lower()
    if raw not in _BOOL_TOKENS:
        raise LogConfigurationError(
            f"{name}={os.environ[name]!r} is not a valid boolean; accepted: true, false",
            setting=name, value=os.environ[name], accepted=["true", "false"],
        )
    return _BOOL_TOKENS[raw]


def _resolve_bool(explicit, env_name: str, default: bool) -> bool:
    if explicit is not None:
        return bool(explicit)
    return _parse_bool_setting(env_name, default)


def _resolve_level(explicit, env_name: str, default: str) -> str:
    if explicit is not None:
        candidate = str(explicit)
        source = "argument"
    elif env_name in os.environ:
        candidate = os.environ[env_name]
        source = env_name
    else:
        return default
    key = candidate.strip().upper()
    if key not in LEVELS:
        raise LogConfigurationError(
            f"{source}={candidate!r} is not a valid level; accepted: {sorted(LEVELS)}",
            setting=env_name, value=candidate, accepted=sorted(LEVELS),
        )
    return key


def _resolve_format(explicit) -> str:
    if explicit is not None:
        candidate = str(explicit).strip().lower()
        if candidate not in FORMATS:
            raise LogConfigurationError(
                f"format={explicit!r} is not valid; accepted: {list(FORMATS)}",
                setting="TINA4_LOG_FORMAT", value=explicit, accepted=list(FORMATS),
            )
        return candidate
    if "TINA4_LOG_FORMAT" in os.environ:
        candidate = os.environ["TINA4_LOG_FORMAT"].strip().lower()
        if candidate not in FORMATS:
            raise LogConfigurationError(
                f"TINA4_LOG_FORMAT={os.environ['TINA4_LOG_FORMAT']!r} is not valid; "
                f"accepted: {list(FORMATS)}",
                setting="TINA4_LOG_FORMAT", value=os.environ["TINA4_LOG_FORMAT"],
                accepted=list(FORMATS),
            )
        return candidate
    return DEFAULT_FORMAT_DEBUG_TRUE if _is_truthy_debug() else DEFAULT_FORMAT_DEBUG_FALSE


def _resolve_output(explicit):
    """Returns (selector_or_None, stdout_enabled, file_enabled)."""
    if explicit is not None:
        candidate = str(explicit).strip().lower()
        source = "argument"
    elif "TINA4_LOG_OUTPUT" in os.environ:
        candidate = os.environ["TINA4_LOG_OUTPUT"].strip().lower()
        source = "TINA4_LOG_OUTPUT"
    else:
        return None, True, _is_truthy_debug()
    if candidate not in OUTPUTS:
        raise LogConfigurationError(
            f"{source}={candidate!r} is not valid; accepted: {list(OUTPUTS)}",
            setting="TINA4_LOG_OUTPUT", value=candidate, accepted=list(OUTPUTS),
        )
    if candidate == "stdout":
        return candidate, True, False
    if candidate == "file":
        return candidate, False, True
    return candidate, True, True


def _resolve_int(explicit, env_name: str, default: int, minimum: int | None = None) -> int:
    if explicit is not None:
        if not isinstance(explicit, int) or isinstance(explicit, bool):
            raise LogConfigurationError(
                f"{env_name}={explicit!r} is not a valid integer",
                setting=env_name, value=explicit,
            )
        value = explicit
        source = "argument"
    elif env_name in os.environ:
        raw = os.environ[env_name]
        try:
            if "." in raw or not raw.strip().lstrip("-").isdigit():
                raise ValueError
            value = int(raw)
        except (ValueError, TypeError):
            raise LogConfigurationError(
                f"{env_name}={raw!r} is not a valid integer",
                setting=env_name, value=raw,
            )
        source = env_name
    else:
        return default
    if minimum is not None and value < minimum:
        raise LogConfigurationError(
            f"{source}={value!r} must be >= {minimum}",
            setting=env_name, value=value, accepted=f">= {minimum}",
        )
    return value


def _resolve_str(explicit, env_name: str, default: str | None, allow_empty: bool = True):
    if explicit is not None:
        if explicit == "":
            raise LogConfigurationError(
                f"{env_name} may not be an empty string", setting=env_name, value=explicit,
            )
        return explicit
    if env_name in os.environ:
        raw = os.environ[env_name]
        if raw == "" and not allow_empty:
            raise LogConfigurationError(
                f"{env_name} may not be an empty string", setting=env_name, value=raw,
            )
        if raw == "":
            return default
        if "\x00" in raw:
            raise LogConfigurationError(
                f"{env_name} may not contain a NUL byte", setting=env_name, value=raw,
            )
        return raw
    return default


def _target_is_file(path: str) -> bool:
    if os.path.isdir(path):
        return False
    base = os.path.basename(path)
    return "." in base and not base.startswith(".")


class Log:
    """Structured logger. See module docstring for the full contract."""

    _snapshot: _Snapshot | None = None
    _config_lock = threading.RLock()

    # ── configuration ────────────────────────────────────────────────

    @classmethod
    def configure(cls, log_dir: str | None = None, log_file: str | None = None,
                  level: str | None = None, file_level: str | None = None,
                  format: str | None = None, output: str | None = None,
                  rotate_size: int | None = None, rotate_keep: int | None = None,
                  strict: bool | None = None, caller: bool | None = None) -> None:
        """Resolve and activate a new configuration snapshot.

        Precedence for every field (ADR-0041): explicit argument, then the
        matching TINA4_LOG_* environment value, then the built-in default.
        Every field is validated BEFORE any directory is created or file is
        opened; a failed reconfiguration leaves the prior snapshot (if any)
        untouched and mutates no filesystem state.
        """
        with cls._config_lock:
            for name, hint in _REMOVED_SETTINGS.items():
                if name in os.environ:
                    raise LogConfigurationError(
                        f"{name} is a removed setting -- {hint}",
                        setting=name, value=os.environ[name],
                    )

            resolved_level = _resolve_level(level, "TINA4_LOG_LEVEL", DEFAULT_LEVEL)
            resolved_file_level = _resolve_level(file_level, "TINA4_LOG_FILE_LEVEL", DEFAULT_FILE_LEVEL)
            resolved_format = _resolve_format(format)
            _, stdout_enabled, file_enabled = _resolve_output(output)
            resolved_rotate_size = _resolve_int(
                rotate_size, "TINA4_LOG_ROTATE_SIZE", DEFAULT_ROTATE_SIZE, minimum=MIN_ROTATE_SIZE)
            resolved_rotate_keep = _resolve_int(
                rotate_keep, "TINA4_LOG_ROTATE_KEEP", DEFAULT_ROTATE_KEEP, minimum=0)
            resolved_strict = _resolve_bool(strict, "TINA4_LOG_STRICT", False)
            resolved_caller = _resolve_bool(caller, "TINA4_LOG_FUNC", False)

            resolved_dir_raw = _resolve_str(log_dir, "TINA4_LOG_DIR", "logs", allow_empty=False)
            resolved_file_raw = _resolve_str(log_file, "TINA4_LOG_FILE", None, allow_empty=True)

            # A directory argument/env value that is actually a FILE PATH names
            # a single file (identical rule in all four frameworks).
            project_root = Path(os.getcwd())
            dir_candidate = resolved_dir_raw
            file_candidate = resolved_file_raw
            if file_candidate is None and _target_is_file(dir_candidate):
                file_candidate = os.path.basename(dir_candidate)
                dir_candidate = os.path.dirname(dir_candidate) or "."

            resolved_log_dir = Path(dir_candidate)
            if not resolved_log_dir.is_absolute():
                resolved_log_dir = project_root / resolved_log_dir

            if file_candidate:
                file_path = Path(file_candidate)
                if not file_path.is_absolute():
                    file_path = resolved_log_dir / file_path
                resolved_log_file = file_path
                layout = "single"
            else:
                resolved_log_file = None
                layout = "directory"

            output_selector = "both" if (stdout_enabled and file_enabled) else (
                "file" if file_enabled else "stdout"
            )

            snap = _Snapshot()
            snap.level = resolved_level
            snap.file_level = resolved_file_level
            snap.format = resolved_format
            snap.output = output_selector
            snap.log_dir = str(resolved_log_dir)
            snap.log_file = str(resolved_log_file) if resolved_log_file else None
            snap.layout = layout
            snap.rotate_size = resolved_rotate_size
            snap.rotate_keep = resolved_rotate_keep
            snap.strict = resolved_strict
            snap.caller = resolved_caller
            snap.stdout_enabled = stdout_enabled
            snap.file_enabled = file_enabled
            snap.main_sink = None
            snap.error_sink = None

            if file_enabled:
                if layout == "single":
                    snap.main_sink = _FileSink(resolved_log_file, resolved_rotate_size, resolved_rotate_keep)
                    snap.main_sink.open()
                else:
                    main_path = resolved_log_dir / "tina4.log"
                    error_path = resolved_log_dir / "error.log"
                    snap.main_sink = _FileSink(main_path, resolved_rotate_size, resolved_rotate_keep)
                    snap.main_sink.open()
                    snap.error_sink = _FileSink(error_path, resolved_rotate_size, resolved_rotate_keep)
                    snap.error_sink.open()

            old = cls._snapshot
            cls._snapshot = snap
            if old is not None:
                if old.main_sink:
                    old.main_sink.close()
                if old.error_sink:
                    old.error_sink.close()

    @classmethod
    def _ensure(cls) -> _Snapshot:
        if cls._snapshot is None:
            cls.configure()
        return cls._snapshot

    @classmethod
    def reset(cls) -> None:
        """Flush/close owned sinks, clear the snapshot and the current
        execution context's request id. Idempotent; the next use resolves a
        fresh snapshot."""
        with cls._config_lock:
            snap = cls._snapshot
            if snap is not None:
                if snap.main_sink:
                    snap.main_sink.close()
                if snap.error_sink:
                    snap.error_sink.close()
            cls._snapshot = None
        clear_request_id()

    @classmethod
    def configuration(cls) -> dict:
        """A defensive native-map copy of the effective, stable configuration."""
        snap = cls._ensure()
        return {
            "level": snap.level,
            "file_level": snap.file_level,
            "format": snap.format,
            "output": snap.output,
            "log_dir": snap.log_dir,
            "log_file": snap.log_file,
            "layout": snap.layout,
            "rotate_size": snap.rotate_size,
            "rotate_keep": snap.rotate_keep,
            "strict": snap.strict,
            "caller": snap.caller,
            "stdout_enabled": snap.stdout_enabled,
            "file_enabled": snap.file_enabled,
        }

    # ── threshold ────────────────────────────────────────────────────

    @classmethod
    def is_enabled(cls, level: str, sink: str | None = None) -> bool:
        """True when `level` passes the queried sink's threshold and that
        sink is active. `sink` is None (console, the historical meaning),
        "console"/"stdout", or "file"."""
        if level is None:
            raise LogArgumentError("is_enabled requires a level", argument="level")
        key = str(level).strip().upper()
        if key not in LEVELS:
            raise LogArgumentError(
                f"{level!r} is not a valid level", argument="level", accepted=sorted(LEVELS),
            )
        snap = cls._ensure()
        if sink in (None, "console", "stdout"):
            return snap.stdout_enabled and LEVELS[key] >= LEVELS[snap.level]
        if sink == "file":
            return snap.file_enabled and LEVELS[key] >= LEVELS[snap.file_level]
        raise LogArgumentError(f"{sink!r} is not a valid sink", argument="sink", accepted=["console", "file"])

    # ── request id (module-level pass-through, kept as classmethods too) ──

    set_request_id = staticmethod(set_request_id)
    get_request_id = staticmethod(get_request_id)
    clear_request_id = staticmethod(clear_request_id)

    # ── caller capture (Decision 16) ────────────────────────────────────

    _OWN_FRAMES = frozenset({
        "_caller_name", "_emit", "debug", "info", "warning", "error", "critical",
    })

    @classmethod
    def _caller_name(cls) -> str | None:
        try:
            import inspect
            frame = inspect.currentframe()
            for _ in range(16):
                if frame is None:
                    return None
                name = frame.f_code.co_name
                if name not in cls._OWN_FRAMES:
                    if name in ("<module>", "<lambda>", "<genexpr>", "<listcomp>", "<setcomp>", "<dictcomp>"):
                        return None
                    return name
                frame = frame.f_back
            return None
        except Exception:
            return None

    # ── event methods (Decision 23, section 5) ──────────────────────────

    @classmethod
    def _emit(cls, level: str, message, context=None) -> None:
        snap = cls._ensure()
        console_ok = snap.stdout_enabled and LEVELS[level] >= LEVELS[snap.level]
        file_ok = snap.file_enabled and LEVELS[level] >= LEVELS[snap.file_level]
        if not console_ok and not file_ok:
            return

        request_id = get_request_id()
        caller_name = cls._caller_name() if snap.caller else None
        event = _build_event(level, message, request_id, caller_name, context)

        if console_ok:
            stdout_line = _bounded_for_sink(event, snap.format, STDOUT_MAX_BYTES).rstrip("\n")
            plain = snap.format == "json" or not _stdout_is_tty()
            color = "" if plain else COLORS.get(level, "")
            reset = "" if plain else RESET
            print(f"{color}{stdout_line}{reset}", flush=True)

        if file_ok and snap.main_sink is not None:
            main_line = _bounded_for_sink(event, snap.format, snap.rotate_size)
            cls._write_sink(snap.main_sink, main_line, snap.strict)
            if snap.layout == "directory" and snap.error_sink is not None and LEVELS[level] >= LEVELS["WARNING"]:
                cls._write_sink(snap.error_sink, main_line, snap.strict)

    @classmethod
    def _write_sink(cls, sink: _FileSink, line: str, strict: bool) -> None:
        try:
            sink.write(line)
        except TimeoutError as exc:
            if strict:
                raise LogWriteError(str(exc), sink=str(sink.path), operation="lock") from exc
        except OSError as exc:
            if strict:
                raise LogWriteError(str(exc), sink=str(sink.path), operation="write") from exc
            try:
                print(f"tina4: log sink {sink.path} failed: {exc}", flush=True)
            except Exception:
                pass

    @staticmethod
    def _merge_context(context, kwargs):
        """Merge the `context=` map with legacy **kwargs. When kwargs is
        empty, `context` is passed through UNCOPIED -- a fresh `dict(context)`
        here would give a directly self-referential context (context["x"] is
        context) a different id() from the object `_normalize` walks, which
        detects the cycle one hop too late. `_normalize` already returns an
        independent structure, so no defensive copy is needed on this path."""
        if not kwargs:
            return context
        merged = dict(context or {})
        merged.update(kwargs)
        return merged

    @classmethod
    def debug(cls, message, context=None, **kwargs):
        cls._emit("DEBUG", message, cls._merge_context(context, kwargs))

    @classmethod
    def info(cls, message, context=None, **kwargs):
        cls._emit("INFO", message, cls._merge_context(context, kwargs))

    @classmethod
    def warning(cls, message, context=None, **kwargs):
        cls._emit("WARNING", message, cls._merge_context(context, kwargs))

    @classmethod
    def error(cls, message, context=None, **kwargs):
        cls._emit("ERROR", message, cls._merge_context(context, kwargs))

    @classmethod
    def critical(cls, message, context=None, **kwargs):
        """Critical-level log -- the highest severity. Always emitted like
        every other level, subject only to the configured threshold."""
        cls._emit("CRITICAL", message, cls._merge_context(context, kwargs))


def _stdout_is_tty() -> bool:
    try:
        import sys
        return bool(sys.stdout.isatty())
    except Exception:
        return False
