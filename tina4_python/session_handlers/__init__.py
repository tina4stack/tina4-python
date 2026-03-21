# Tina4 Session Handlers — pluggable session storage backends, zero core dependencies.
"""
Optional session handlers for Redis, MongoDB, and Valkey.
Each handler extends SessionHandler and implements: read, write, destroy, gc.

All external packages are optional imports with clear error messages.

    from tina4_python.session_handlers import RedisSessionHandler
    from tina4_python.session import Session

    session = Session(handler=RedisSessionHandler(host="localhost"))
"""

from tina4_python.session_handlers.redis_handler import RedisSessionHandler
from tina4_python.session_handlers.mongodb_handler import MongoDBSessionHandler
from tina4_python.session_handlers.valkey_handler import ValkeySessionHandler

__all__ = ["RedisSessionHandler", "MongoDBSessionHandler", "ValkeySessionHandler"]
