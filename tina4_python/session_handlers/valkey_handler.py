# Tina4 Valkey Session Handler — Valkey (Redis-compatible) via `redis` package or raw RESP.
"""
Valkey session handler. Valkey is wire-compatible with Redis and speaks the same
RESP protocol, so this is a thin subclass of RedisSessionHandler. It changes only
the env-var prefix (TINA4_SESSION_VALKEY_*) and the brand word in messages -- every
read/write/destroy/RESP method is inherited, so there is no duplicated logic.

Environment variables:
    TINA4_SESSION_VALKEY_HOST     — hostname (default: localhost)
    TINA4_SESSION_VALKEY_PORT     — port (default: 6379)
    TINA4_SESSION_VALKEY_PASSWORD — password (default: none)
    TINA4_SESSION_VALKEY_DB       — database number (default: 0)
    TINA4_SESSION_VALKEY_PREFIX   — key prefix (default: tina4:session:)
    TINA4_SESSION_TTL             — session TTL in seconds (default: 3600)
"""
from tina4_python.session_handlers.redis_handler import RedisSessionHandler


class ValkeySessionHandler(RedisSessionHandler):
    """Valkey-backed session handler with TTL support.

    Valkey is wire-compatible with Redis, so the RESP logic is inherited from
    RedisSessionHandler. This subclass only reads the TINA4_SESSION_VALKEY_* env
    vars and reports "Valkey" in its error messages.
    """

    _ENV = "VALKEY"
    _BRAND = "Valkey"
