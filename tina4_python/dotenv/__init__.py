# Tina4 DotEnv — Zero-dependency .env file parser.
"""
Parse .env files into os.environ. No third-party libraries.

Usage:
    from tina4_python.dotenv import load_env, get_env, require_env, has_env, all_env, reset_env

    load_env()                           # Load .env from current directory
    load_env(".env.staging")             # Load specific file
    db_url = get_env("DATABASE_URL")     # Get with None default
    secret = require_env("JWT_SECRET")   # Raises on missing
    if has_env("DEBUG"):                 # Check if variable exists
        ...
    env_vars = all_env()                 # Get all env vars as dict
"""
import os
from pathlib import Path


def load_env(file_path: str = ".env", override: bool = False) -> dict:
    """Load environment variables from a .env file.

    Supports:
        KEY=value
        KEY="value with spaces"
        KEY='single quoted'
        KEY=value # inline comments
        # full line comments
        empty lines
        export KEY=value (export prefix stripped)
        multi-word unquoted values

    Args:
        file_path: Path to .env file (default: ".env")
        override: If True, overwrite existing env vars (default: False)

    Returns:
        Dict of loaded key-value pairs
    """
    env_file = Path(file_path)
    loaded = {}

    if not env_file.is_file():
        return loaded

    for line_num, raw_line in enumerate(env_file.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()

        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue

        # Strip optional "export " prefix
        if line.startswith("export "):
            line = line[7:].strip()

        # Split on first "="
        if "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        if not key:
            continue

        # Remove surrounding quotes
        if len(value) >= 2:
            if (value[0] == '"' and value[-1] == '"') or \
               (value[0] == "'" and value[-1] == "'"):
                value = value[1:-1]
            else:
                # Remove inline comments (only for unquoted values)
                comment_idx = value.find(" #")
                if comment_idx != -1:
                    value = value[:comment_idx].rstrip()

        loaded[key] = value

        # Set in os.environ
        if override or key not in os.environ:
            os.environ[key] = value
            _loaded_keys.append(key)

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
        SystemExit: If any required variables are missing (fail fast)
    """
    missing = [k for k in keys if not os.environ.get(k)]
    if missing:
        print(f"[FATAL] Missing required environment variables:")
        for k in missing:
            print(f"  - {k}: not set")
        raise SystemExit(1)

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
