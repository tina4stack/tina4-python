# Tina4 Env — Typed environment-variable helpers.
# Copyright 2007 - present Tina4
# License: MIT
"""Typed environment-variable helpers — zero-deps.

Reading env vars by hand gets old fast: every boolean flag becomes a
``os.getenv("TINA4_DEBUG", "false").lower() in ("1", "true", "on", "yes")``
incantation. Every numeric tuning knob needs a try/except around int().
Env centralises that. Same API across all four Tina4 frameworks
(``Tina4\\Env`` in PHP, ``Tina4::Env`` in Ruby, ``Env`` in Node.js).

    from tina4_python import Env

    debug   = Env.bool("TINA4_DEBUG", default=False)
    workers = Env.int("WORKERS", default=4)
    rate    = Env.float("RATE_LIMIT", default=10.0)
    region  = Env.str("AWS_REGION", default="us-east-1")

Values are accepted case-insensitively after ``strip()``. Truthy:
``1 / true / on / yes / y / t``. Falsy: ``0 / false / off / no / n / f``.
Any other value triggers the ``default``. Unparseable ints and floats
log a warning via ``Log`` and fall back to ``default`` — never raise.
"""
from __future__ import annotations

import os

# Lazy import so ``import tina4_python.env`` doesn't drag the whole Log
# chain in for callers who don't want it (CLI scaffolding, etc).
_TRUTHY = frozenset({"1", "true", "on", "yes", "y", "t"})
_FALSY = frozenset({"0", "false", "off", "no", "n", "f", ""})


def _log_warning(message: str) -> None:
    """Emit a warning via Log without creating a circular import at module load."""
    try:
        from tina4_python.debug import Log
        Log.warning(message)
    except Exception:
        # Log not yet wired (e.g. very early bootstrap) — silently skip.
        pass


class Env:
    """Typed environment-variable helpers.

    All methods are classmethods so callers can write ``Env.bool(...)``
    without instantiating anything — matching the PHP/Ruby/Node ports.
    """

    @classmethod
    def bool(cls, name: str, default: bool = False) -> bool:
        """Read ``name`` and coerce to bool.

        Truthy values (case-insensitive after strip): ``1``, ``true``,
        ``on``, ``yes``, ``y``, ``t``. Falsy: ``0``, ``false``, ``off``,
        ``no``, ``n``, ``f``, empty string. Anything else returns the
        ``default`` — never raises.
        """
        raw = os.environ.get(name)
        if raw is None:
            return default
        token = raw.strip().lower()
        if token in _TRUTHY:
            return True
        if token in _FALSY:
            return False
        return default

    @classmethod
    def int(cls, name: str, default: int = 0) -> int:
        """Read ``name`` and coerce to int. Returns ``default`` on parse failure."""
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            return int(raw.strip())
        except (ValueError, TypeError):
            _log_warning(
                f"Env.int({name!r}): could not parse {raw!r} as int — "
                f"using default {default!r}"
            )
            return default

    @classmethod
    def float(cls, name: str, default: float = 0.0) -> float:
        """Read ``name`` and coerce to float. Returns ``default`` on parse failure."""
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            return float(raw.strip())
        except (ValueError, TypeError):
            _log_warning(
                f"Env.float({name!r}): could not parse {raw!r} as float — "
                f"using default {default!r}"
            )
            return default

    @classmethod
    def str(cls, name: str, default: str = "") -> str:
        """Read ``name`` as a string. Returns ``default`` if unset.

        Whitespace is preserved — this is a pass-through for the raw env
        value. ``Env.str("PATH")`` is exactly ``os.environ.get("PATH", "")``
        with a more discoverable name.
        """
        raw = os.environ.get(name)
        if raw is None:
            return default
        return raw
