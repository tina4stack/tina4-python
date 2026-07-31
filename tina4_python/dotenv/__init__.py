# Tina4 DotEnv — Zero-dependency .env file parser.
"""
Parse .env files into os.environ. No third-party libraries.

Usage:
    from tina4_python.dotenv import load_env, get_env, require_env, has_env, all_env, reset_env

    load_env()                           # Load .env from current directory
    load_env(".env.staging")             # Load specific file
    db_url = get_env("TINA4_DATABASE_URL")     # Get with None default
    secret = require_env("JWT_SECRET")   # Raises on missing
    if has_env("DEBUG"):                 # Check if variable exists
        ...
    env_vars = all_env()                 # Get all env vars as dict
"""
import os
import re
import sys
from pathlib import Path

_VALID_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _warn(message: str) -> None:
    """Emit a parse warning. dotenv loads before the logger exists, so stderr."""
    print(f"[tina4] {message}", file=sys.stderr)


def _interpolate(value: str, env_file, line_num: int, warned_refs: set) -> str:
    """Expand ${VAR} against already-loaded keys plus the real environment.

    An unresolved name stays LITERAL and is warned about once per name, so a typo
    is visible without breaking the load.
    """
    def replace(match):
        name = match.group(1)
        if name in os.environ:
            return os.environ[name]
        if name not in warned_refs:
            warned_refs.add(name)
            _warn(f"{env_file}:{line_num}: ${{{name}}} is not set, left as-is")
        return match.group(0)

    return _REFERENCE.sub(replace, value)


def _parse_value(value: str, env_file, line_num: int, warned_refs: set) -> str:
    """Quoting decides escapes AND interpolation, in that order.

    The rules are the cross-framework behaviour table (feature 1 of the feature
    audit): identical in Python, PHP, Ruby and Node, driven off one committed
    fixture.
    """
    # A fully single-quoted value is verbatim: no escapes, no interpolation.
    # Shell semantics, and the documented way to keep a literal ${...}.
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1]

    # A double-quoted value keeps its interior verbatim (a `#` inside stays a
    # `#`), minus the quotes, with escape processing.
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        inner = value[1:-1].replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")
        return _interpolate(inner, env_file, line_num, warned_refs)

    # An unquoted value is truncated at the first SPACE-HASH, then trimmed.
    comment_idx = value.find(" #")
    if comment_idx != -1:
        value = value[:comment_idx]
    return _interpolate(value.rstrip(), env_file, line_num, warned_refs)


def load_env(path: str = None, override: bool = False) -> dict:
    """Load environment variables from a root DIRECTORY or a single .env file.

    The directory form is canonical, in all four frameworks. Given a directory it
    loads ``<dir>/.env.local`` and then ``<dir>/.env``, both first-wins, which is
    the documented precedence: real environment > .env.local > .env.

    That ordering is the whole reason the directory form exists. It used to be the
    CALLER's job in Python, PHP and Node - two calls in the right order, with
    override left off - and it was duplicated at every boot site. Get it wrong
    (override=True on .env.local) and a stray gitignored file silently beats an
    explicitly-set production variable. Ruby encapsulated it and did not have that
    footgun; the other three now do the same.

    A FILE path still works and is unchanged, so every existing call keeps its
    behaviour. Only that file is read; the caller owns the ordering, as before.

    Args:
        path: A root directory (canonical) OR a path to a single .env file
            (back-compatible). When None, TINA4_ENV_FILE wins if set - so ops can
            still point at ".env.staging" without a code change - otherwise the
            current directory is used as the root.
        override: If True, overwrite existing env vars (default: False)

    Returns:
        Dict of loaded key-value pairs. For the directory form this is the merge
        of both files, with .env.local winning on a duplicate key.
    """
    if path is None:
        explicit_file = os.environ.get("TINA4_ENV_FILE")
        if explicit_file:
            # TINA4_ENV_FILE names the .env; .env.local BESIDE it still applies,
            # because the boot sites always loaded both and a bare load_env() has
            # to be self-sufficient. Collapsing them without this would silently
            # stop honouring .env.local whenever ops pointed at .env.staging.
            named = Path(explicit_file)
            loaded = _load_env_file(named.parent / ".env.local", override)
            for key, value in _load_env_file(named, override).items():
                loaded.setdefault(key, value)
            return loaded
        path = "."

    root = Path(path)
    if root.is_dir():
        # .env.local FIRST so it beats .env; both first-wins, so a variable
        # already in the real environment still beats both.
        loaded = _load_env_file(root / ".env.local", override)
        for key, value in _load_env_file(root / ".env", override).items():
            loaded.setdefault(key, value)
        return loaded

    return _load_env_file(root, override)


def _load_env_file(file_path, override: bool = False) -> dict:
    """Load one .env file.

    Supports:
        KEY=value
        KEY="value with spaces"
        KEY='single quoted'
        KEY=value # inline comments
        # full line comments
        empty lines
        export KEY=value (export prefix stripped)
        multi-word unquoted values

    A missing file is not an error: it returns an empty dict. A fresh checkout has
    no .env.local, and the directory form reads it unconditionally.
    """
    env_file = Path(file_path)
    loaded = {}

    if not env_file.is_file():
        return loaded

    warned_refs = set()
    for line_num, raw_line in enumerate(env_file.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()

        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue

        # Strip optional "export " prefix
        if line.startswith("export "):
            line = line[7:].strip()

        # Split on first "=". A line with no "=" sets nothing, so say so rather
        # than dropping it in silence.
        if "=" not in line:
            _warn(f"{env_file}:{line_num}: no '=' in {line!r}, line skipped")
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        if not _VALID_KEY.match(key):
            _warn(f"{env_file}:{line_num}: invalid key {key!r}, line skipped")
            continue

        value = _parse_value(value, env_file, line_num, warned_refs)

        # Set in os.environ. First-wins by default: a variable already in the
        # real environment is never clobbered.
        if override or key not in os.environ:
            os.environ[key] = value
            _loaded_keys.append(key)

        # Report the value that WON, not the one this file declared. They differ
        # exactly when the real environment beat the file, which is the case an
        # operator most needs to see: reporting the file's value there means the
        # returned map says "from_local" while the process is actually running
        # on "from_REAL". A map that disagrees with os.environ is worse than no
        # map, because it looks authoritative.
        loaded[key] = os.environ[key]

    return loaded


def get_env(key: str, default: str = None) -> str | None:
    """Get environment variable with optional default."""
    return os.environ.get(key, default)


def require_env(*keys: str) -> dict:
    """Validate that required environment variables exist.

    Args:
        *keys: Variable names that must be set

    Returns:
        Dict of key-value pairs for the required variables

    Raises:
        KeyError: If any required variables are missing, naming ALL of them.

    Reports every missing name in one raise rather than the first: an operator
    fixing a deployment wants the whole list, not one name per restart.

    This used to `raise SystemExit(1)` after printing to stdout. A library
    function must not terminate its host process - it cannot be caught in any
    useful way, it bypasses every error handler the app installed, and a web
    framework that exits on a config read is unusable in a worker. Callers who
    genuinely want fail-fast-and-exit can catch this and exit themselves.
    """
    missing = [k for k in keys if not os.environ.get(k)]
    if missing:
        raise KeyError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    return {k: os.environ[k] for k in keys}


def has_env(key: str) -> bool:
    """Check if an environment variable exists.

    Args:
        key: The environment variable name to check

    Returns:
        True if the variable is set in os.environ, False otherwise
    """
    return key in os.environ


def all_env() -> dict[str, str]:
    """Return all environment variables as a dict.

    Returns:
        A copy of all current environment variables
    """
    return dict(os.environ)


# Track keys loaded by load_env so reset_env can remove them
_loaded_keys: list[str] = []


def reset_env() -> None:
    """Remove all environment variables that were loaded by load_env().

    Useful for testing. Only removes keys that were set by load_env(),
    not pre-existing system environment variables.
    """
    global _loaded_keys
    for key in _loaded_keys:
        os.environ.pop(key, None)
    _loaded_keys = []


def is_truthy(val) -> bool:
    """Check if a value is truthy for env boolean checks.

    Accepts: "true", "True", "TRUE", "1", "yes", "Yes", "YES", "on", "On", "ON".
    Everything else is falsy (including empty string, None, not set).
    """
    return str(val).strip().lower() in ("true", "1", "yes", "on")
