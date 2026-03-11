#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""Session management with pluggable storage backends.

This module provides a session system for the Tina4 web framework. Sessions
store key-value data across HTTP requests, persisted as JWT tokens via a
configurable backend.

Available backends:
    - ``SessionFileHandler``: Stores JWT tokens as files on disk (default).
    - ``SessionRedisHandler``: Stores JWT tokens in a Redis server.
    - ``SessionValkeyHandler``: Stores JWT tokens in a Valkey server.
    - ``SessionMongoHandler``: Stores JWT tokens in a MongoDB collection.

All backends extend ``SessionHandler``, which defines the shared interface
(load, set, get, unset, close, save). The ``Session`` class is the public
API that delegates to whichever backend was chosen at construction time.

Typical usage inside a route handler::

    session = request.session
    session.set("user_id", 42)
    uid = session.get("user_id")   # -> 42
    session.unset("user_id")
    session.close()                # destroy the session entirely
"""

__all__ = [
    "Session", "LazySession", "SessionHandler", "SessionFileHandler",
    "SessionRedisHandler", "SessionValkeyHandler",
    "SessionMongoHandler",
]

import os
from http import cookies
import sys
import importlib
import hashlib
import tina4_python
from tina4_python.Debug import Debug
from tina4_python import Constant

class SessionHandler(object):
    """Abstract base class that defines the session backend interface.

    Every session backend (file, Redis, Valkey) must subclass this and
    override ``load``, ``close``, and ``save``.  The default ``set``,
    ``get``, and ``unset`` implementations work with the in-memory
    ``session.session_values`` dict and call ``session.save()`` to persist
    changes; backends typically inherit them as-is.
    """

    @staticmethod
    def load(session, session_hash):
        """Load session data from the backend into ``session.session_values``.

        Subclasses must override this method. The implementation should
        read the persisted JWT for *session_hash*, validate it, and
        populate the session via ``session.set(key, value)`` for each
        stored key.

        Args:
            session: The ``Session`` instance to populate.
            session_hash: Unique identifier (MD5 hex digest) for the session.
        """
        pass

    @staticmethod
    def set(session, key, value):
        """Store a key-value pair in the session and persist it.

        Args:
            session: The ``Session`` instance.
            key: The name of the session variable.
            value: The value to store (must be JSON-serialisable).

        Returns:
            True on success, False if an error occurred.
        """
        try:
            session.session_values[key] = value
            session.save()
            return True
        except Exception:
            return False

    @staticmethod
    def unset(session, key):
        """Remove a key from the session and persist the change.

        Args:
            session: The ``Session`` instance.
            key: The name of the session variable to remove.

        Returns:
            True if the key existed and was removed, False otherwise.
        """
        if key in session.session_values:
            del session.session_values[key]
            session.save()
            return True
        else:
            return False

    @staticmethod
    def get(session, key):
        """Retrieve a value from the session by key.

        Args:
            session: The ``Session`` instance.
            key: The name of the session variable to retrieve.

        Returns:
            The stored value, or None if the key does not exist.
        """
        if key in session.session_values:
            return session.session_values[key]
        else:
            return None

    @staticmethod
    def close(session):
        """Destroy the session, removing all persisted data.

        Subclasses must override this to delete the session's stored JWT
        (e.g. remove the file, clear the Redis/Valkey key).

        Args:
            session: The ``Session`` instance to destroy.

        Returns:
            True on success, False on failure.
        """
        pass

    @staticmethod
    def save(session):
        """Persist the current ``session.session_values`` to the backend.

        Subclasses must override this. The implementation should encode
        ``session.session_values`` as a JWT and write it to the backend
        keyed by ``session.session_hash``.

        Args:
            session: The ``Session`` instance to persist.

        Returns:
            True on success, False on failure.
        """
        pass

class SessionFileHandler(SessionHandler):
    """File-system session backend.

    Each session is stored as a single file whose name is the session hash
    and whose content is a signed JWT token. Files are written to the
    directory specified by ``session.session_path`` (default ``sessions/``).

    On ``load``, the file is read and the JWT is validated via
    ``tina4_python.tina4_auth``. If the token has expired or the file is
    missing, a fresh session is started automatically.
    """

    @staticmethod
    def load(session, session_hash):
        session.session_hash = session_hash
        if os.path.isfile(session.session_path + os.sep + session_hash):
            with open(session.session_path + os.sep + session_hash, "r") as file:
                token = file.read()
                file.close()
                if tina4_python.tina4_auth.valid(token):
                    payload = tina4_python.tina4_auth.get_payload(token)
                    for key in payload:
                        if key != "expires":
                            session.set(key, payload[key])
                else:
                    Debug.debug("Session expired, starting a new one")
                    session.start(session_hash)
        else:
            Debug.debug("Cannot load session, starting a new one")
            session.start(session_hash)

    @staticmethod
    def close(session):
        try:
            file_path = session.session_path + os.sep + session.session_hash
            if os.path.isfile(file_path):
                os.remove(file_path)
                return True
            return False
        except Exception:
            return False

    @staticmethod
    def save(session):
        try:
            if not os.path.exists(session.session_path):
                os.makedirs(session.session_path)
            token = tina4_python.tina4_auth.get_token(payload_data=session.session_values)
            with open(session.session_path + os.sep + session.session_hash, "w") as file:
                file.write(token)
                file.close()
                return True
        except Exception as e:
            Debug.error("Session save failure", e)
            return False

class SessionRedisHandler(SessionHandler):
    """Redis session backend.

    Stores session JWT tokens in a Redis key-value store. The Redis
    connection is configured via environment variables:

    - ``TINA4_SESSION_REDIS_HOST`` (default ``localhost``)
    - ``TINA4_SESSION_REDIS_PORT`` (default ``6379``)
    - ``TINA4_SESSION_REDIS_SECRET`` (optional password)

    Requires the ``redis`` Python package (``pip install redis``).
    A new Redis connection is created for each operation via
    ``__init_redis()``.
    """

    @staticmethod
    def __init_redis():
        try:
            redis = importlib.import_module("redis")
        except Exception as e:
            Debug.error("Redis not installed, install with pip install redis or poetry add redis", str(e))
            sys.exit(1)

        if os.getenv("TINA4_SESSION_REDIS_SECRET", "") != "":
            redis_instance = redis.Redis(host=os.getenv("TINA4_SESSION_REDIS_HOST", "localhost"),
                                         port=os.getenv("TINA4_SESSION_REDIS_PORT",6379),
                                         password=os.getenv("TINA4_SESSION_REDIS_SECRET", ""),
                                         decode_responses=True)
        else:
            redis_instance = redis.Redis(host=os.getenv("TINA4_SESSION_REDIS_HOST", "localhost"),
                                         port=os.getenv("TINA4_SESSION_REDIS_PORT",6379),
                                         decode_responses=True)
        return redis_instance

    @staticmethod
    def load(session, session_hash):
        """Load session data from Redis.

        Reads the JWT stored under *session_hash*, validates it, and
        populates ``session.session_values``. If the token is expired or
        missing, a new session is started.

        Args:
            session: The ``Session`` instance to populate.
            session_hash: The Redis key identifying this session.
        """
        try:
            session.session_hash = session_hash
            r = SessionRedisHandler.__init_redis()
            token = r.get(session_hash)
            if tina4_python.tina4_auth.valid(token):
                payload = tina4_python.tina4_auth.get_payload(token)
                for key in payload:
                    if key != "expires":
                        session.set(key, payload[key])
            else:
                Debug.warning("Session expired, starting a new one")
                session_hash = None
                session.start(session_hash)
        except Exception as e:
            Debug.error("Redis not available, sessions will fail", e)


    @staticmethod
    def close(session):
        """Destroy the session by clearing its Redis key.

        Args:
            session: The ``Session`` instance to destroy.

        Returns:
            True on success, False on failure.
        """
        r = SessionRedisHandler.__init_redis()
        try:
            r.set(session.session_hash, "")
            return True
        except Exception:
            return False

    @staticmethod
    def save(session):
        """Persist session data to Redis as a signed JWT.

        Args:
            session: The ``Session`` instance whose values are persisted.

        Returns:
            True on success, False on failure.
        """
        r = SessionRedisHandler.__init_redis()
        try:
            token = tina4_python.tina4_auth.get_token(payload_data=session.session_values)
            r.set(session.session_hash, token)
            return True
        except Exception as e:
            Debug.error("Session save failure", str(e))
            return False

class SessionValkeyHandler(SessionHandler):
    """Valkey session backend.

    Stores session JWT tokens in a Valkey key-value store (a Redis-compatible
    server). The connection is configured via environment variables:

    - ``TINA4_SESSION_VALKEY_HOST`` (default ``localhost``)
    - ``TINA4_SESSION_VALKEY_PORT`` (default ``6379``)
    - ``TINA4_SESSION_VALKEY_SECRET`` (optional password)
    - ``TINA4_SESSION_VALKEY_USER`` (default ``default``)
    - ``TINA4_SESSION_VALKEY_SSL`` (set to ``True`` to enable TLS)

    Requires the ``valkey`` Python package (``pip install valkey``).
    A new connection is created for each operation via ``__init_valkey()``.
    """

    @staticmethod
    def __init_valkey():
        try:
            valkey = importlib.import_module("valkey")
        except Exception as e:
            Debug.error("Valkey not installed, install with pip/uv", str(e))
            sys.exit(1)

        params = {
            "host": os.getenv("TINA4_SESSION_VALKEY_HOST", "localhost"),
            "port": int(os.getenv("TINA4_SESSION_VALKEY_PORT", 6379)),
            "decode_responses": True
        }
        if os.getenv("TINA4_SESSION_VALKEY_SECRET", ""):
            params["password"] = os.getenv("TINA4_SESSION_VALKEY_SECRET", "")
            params["username"] = os.getenv("TINA4_SESSION_VALKEY_USER", "default")

        if os.getenv("TINA4_SESSION_VALKEY_SSL", "False").upper() == "TRUE":
            params["ssl"] = True

        valkey_instance = valkey.Valkey(**params)

        return valkey_instance

    @staticmethod
    def load(session, session_hash):
        """Load session data from Valkey.

        Reads the JWT stored under *session_hash*, validates it, and
        populates ``session.session_values``. If the token is expired or
        missing, a new session is started.

        Args:
            session: The ``Session`` instance to populate.
            session_hash: The Valkey key identifying this session.
        """
        try:
            session.session_hash = session_hash
            r = SessionValkeyHandler.__init_valkey()
            token = r.get(session_hash)
            if tina4_python.tina4_auth.valid(token):
                payload = tina4_python.tina4_auth.get_payload(token)
                for key in payload:
                    if key != "expires":
                        session.set(key, payload[key])
            else:
                Debug.error("Session expired, starting a new one")
                session.start(session_hash)
        except Exception as e:
            Debug.error("Valkey not available, sessions will fail", str(e))


    @staticmethod
    def close(session):
        """Destroy the session by clearing its Valkey key.

        Args:
            session: The ``Session`` instance to destroy.

        Returns:
            True on success, False on failure.
        """
        r = SessionValkeyHandler.__init_valkey()
        try:
            r.set(session.session_hash, "")
            return True
        except Exception:
            return False

    @staticmethod
    def save(session):
        """Persist session data to Valkey as a signed JWT.

        Args:
            session: The ``Session`` instance whose values are persisted.

        Returns:
            True on success, False on failure.
        """
        r = SessionValkeyHandler.__init_valkey()
        try:
            token = tina4_python.tina4_auth.get_token(payload_data=session.session_values)
            r.set(session.session_hash, token)
            return True
        except Exception as e:
            Debug.error("Session save failure", str(e))
            return False

class SessionMongoHandler(SessionHandler):
    """MongoDB session backend.

    Stores session JWT tokens in a MongoDB collection. The MongoDB
    connection is configured via environment variables:

    - ``TINA4_SESSION_MONGO_HOST`` (default ``localhost``)
    - ``TINA4_SESSION_MONGO_PORT`` (default ``27017``)
    - ``TINA4_SESSION_MONGO_URI`` (optional full connection URI, overrides host/port)
    - ``TINA4_SESSION_MONGO_USERNAME`` (optional username)
    - ``TINA4_SESSION_MONGO_PASSWORD`` (optional password)
    - ``TINA4_SESSION_MONGO_DB`` (default ``tina4_sessions``)
    - ``TINA4_SESSION_MONGO_COLLECTION`` (default ``sessions``)

    Requires the ``pymongo`` Python package (``pip install pymongo``).
    """

    @staticmethod
    def __init_mongo():
        try:
            pymongo = importlib.import_module("pymongo")
        except Exception as e:
            Debug.error("pymongo not installed, install with pip install pymongo or poetry add pymongo", str(e))
            sys.exit(1)

        uri = os.getenv("TINA4_SESSION_MONGO_URI", "")
        if uri:
            client = pymongo.MongoClient(uri)
        else:
            params = {
                "host": os.getenv("TINA4_SESSION_MONGO_HOST", "localhost"),
                "port": int(os.getenv("TINA4_SESSION_MONGO_PORT", 27017)),
            }
            username = os.getenv("TINA4_SESSION_MONGO_USERNAME", "")
            password = os.getenv("TINA4_SESSION_MONGO_PASSWORD", "")
            if username and password:
                params["username"] = username
                params["password"] = password
            client = pymongo.MongoClient(**params)

        db_name = os.getenv("TINA4_SESSION_MONGO_DB", "tina4_sessions")
        collection_name = os.getenv("TINA4_SESSION_MONGO_COLLECTION", "sessions")
        return client[db_name][collection_name]

    @staticmethod
    def load(session, session_hash):
        """Load session data from MongoDB.

        Reads the JWT stored under *session_hash*, validates it, and
        populates ``session.session_values``. If the token is expired or
        missing, a new session is started.

        Args:
            session: The ``Session`` instance to populate.
            session_hash: The document key identifying this session.
        """
        try:
            session.session_hash = session_hash
            collection = SessionMongoHandler.__init_mongo()
            doc = collection.find_one({"_id": session_hash})
            if doc and "token" in doc:
                token = doc["token"]
                if tina4_python.tina4_auth.valid(token):
                    payload = tina4_python.tina4_auth.get_payload(token)
                    for key in payload:
                        if key != "expires":
                            session.set(key, payload[key])
                else:
                    Debug.warning("Session expired, starting a new one")
                    session.start(session_hash)
            else:
                Debug.debug("Cannot load session from MongoDB, starting a new one")
                session.start(session_hash)
        except Exception as e:
            Debug.error("MongoDB not available, sessions will fail", e)

    @staticmethod
    def close(session):
        """Destroy the session by removing its MongoDB document.

        Args:
            session: The ``Session`` instance to destroy.

        Returns:
            True on success, False on failure.
        """
        try:
            collection = SessionMongoHandler.__init_mongo()
            collection.delete_one({"_id": session.session_hash})
            return True
        except Exception:
            return False

    @staticmethod
    def save(session):
        """Persist session data to MongoDB as a signed JWT.

        Args:
            session: The ``Session`` instance whose values are persisted.

        Returns:
            True on success, False on failure.
        """
        try:
            collection = SessionMongoHandler.__init_mongo()
            token = tina4_python.tina4_auth.get_token(payload_data=session.session_values)
            collection.update_one(
                {"_id": session.session_hash},
                {"$set": {"token": token}},
                upsert=True
            )
            return True
        except Exception as e:
            Debug.error("Session save failure", str(e))
            return False


class Session:
    """Public API for session management in Tina4.

    A ``Session`` holds an in-memory dict of key-value pairs
    (``session_values``) that are persisted to a pluggable backend as a
    signed JWT token.  The backend is selected at construction time via the
    *default_handler* parameter.

    Attributes:
        session_name: Cookie name used to track the session ID (default
            ``PY_SESS``).
        cookie: A ``http.cookies.SimpleCookie`` instance for the session
            cookie.
        session_path: Directory path used by ``SessionFileHandler`` to
            store session files.
        session_values: Dict of the current session's key-value data.
        session_hash: The unique identifier (MD5 hex digest) for this
            session, used as the storage key / filename.
        default_handler: The ``SessionHandler`` subclass that performs
            persistence operations.
    """

    def __init__(self, default_name="PY_SESS", default_path="sessions", default_handler="SessionFileHandler"):
        """Initialise a new Session instance.

        Args:
            default_name: The cookie name used to identify the session
                (default ``PY_SESS``).
            default_path: File-system directory where ``SessionFileHandler``
                stores session files (default ``sessions``).
            default_handler: Name of the backend class to use. One of
                ``"SessionFileHandler"`` (default),
                ``"SessionRedisHandler"``,
                ``"SessionValkeyHandler"``, or
                ``"SessionMongoHandler"``.
        """
        self.session_name = default_name
        self.cookie = cookies.SimpleCookie()
        self.session_path = default_path
        self.session_values = {}
        self.session_hash = ""
        handlers = {
            "SessionFileHandler": SessionFileHandler,
            "SessionRedisHandler": SessionRedisHandler,
            "SessionValkeyHandler": SessionValkeyHandler,
            "SessionMongoHandler": SessionMongoHandler,
        }
        self.default_handler = handlers.get(default_handler, SessionFileHandler)

    def start(self, session_hash=None):
        """Create or reinitialise a session and persist it.

        Generates a signed JWT from the current ``session_values``,
        derives a session hash (MD5 of the JWT) if one is not provided,
        and saves the session to the backend.

        Args:
            session_hash: An existing session identifier to reuse. If
                None, a new hash is generated from the JWT token.

        Returns:
            The session hash string identifying this session.
        """
        token = tina4_python.tina4_auth.get_token(payload_data=self.session_values)
        if session_hash is None:
            file_hash = hashlib.md5(token.encode()).hexdigest()
        else:
            file_hash = session_hash
        self.session_hash = file_hash
        self.save()

        return file_hash

    def load(self, session_hash):
        """Load an existing session from the backend.

        Delegates to the configured backend handler to read the persisted
        JWT, validate it, and populate ``session_values``.

        Args:
            session_hash: The unique session identifier to load.
        """
        self.default_handler.load(self, session_hash)

    def set(self, key, value):
        """Store a key-value pair in the session.

        The value is saved in memory and immediately persisted to the
        backend.

        Args:
            key: The session variable name.
            value: The value to store (must be JSON-serialisable).

        Returns:
            True on success, False on failure.
        """
        return self.default_handler.set(self, key, value)


    def unset(self, key):
        """Remove a key from the session.

        Args:
            key: The session variable name to remove.

        Returns:
            True if the key existed and was removed, False otherwise.
        """
        return self.default_handler.unset(self, key)

    def get(self, key):
        """Retrieve a session value by key.

        Args:
            key: The session variable name to look up.

        Returns:
            The stored value, or None if the key does not exist.
        """
        return self.default_handler.get(self, key)

    def close(self):
        """Destroy the session, removing all persisted data.

        After calling this, the session hash and stored JWT are deleted
        from the backend.

        Returns:
            True on success, False on failure.
        """
        return self.default_handler.close(self)

    def save(self):
        """Persist the current session data to the backend.

        Encodes ``session_values`` as a signed JWT and writes it to the
        configured backend.

        Returns:
            True on success, False on failure.
        """
        return self.default_handler.save(self)

    def __iter__(self):
        """Iterate over session key-value pairs.

        Yields all entries in ``session_values`` except the internal
        ``expires`` key used by the JWT layer.

        Yields:
            Tuples of ``(key, value)`` for each session variable.
        """
        for key, value in self.session_values.items():
            if key != "expires":
                yield key, value


class LazySession:
    """Proxy that defers expensive Session creation until first use.

    Creating and starting a ``Session`` requires RSA key signing (~1ms
    per call) which dominates request latency for API routes that never
    touch the session.  ``LazySession`` wraps the session creation
    parameters and only instantiates the real ``Session`` when a method
    like ``set()``, ``get()``, or ``load()`` is called.

    The ``activated`` property lets the response builder know whether
    to emit a ``Set-Cookie`` header.
    """

    def __init__(self, name, path, handler, cookies):
        self._name = name
        self._path = path
        self._handler = handler
        self._cookies = cookies
        self._real = None

    @property
    def activated(self):
        """True if the real Session has been created."""
        return self._real is not None

    def _activate(self):
        """Create and start/load the real Session on first access."""
        if self._real is None:
            self._real = Session(self._name, self._path, self._handler)
            if self._name in self._cookies:
                self._real.load(self._cookies[self._name])
            else:
                self._cookies[self._name] = self._real.start()
        return self._real

    # --- Forwarded Session API ---

    @property
    def session_name(self):
        return self._name

    @property
    def session_values(self):
        if self._real is None:
            return {}
        return self._real.session_values

    @property
    def session_hash(self):
        if self._real is None:
            return ""
        return self._real.session_hash

    @session_hash.setter
    def session_hash(self, value):
        self._activate().session_hash = value

    def start(self, session_hash=None):
        return self._activate().start(session_hash)

    def load(self, session_hash):
        return self._activate().load(session_hash)

    def set(self, key, value):
        return self._activate().set(key, value)

    def get(self, key):
        return self._activate().get(key)

    def unset(self, key):
        return self._activate().unset(key)

    def close(self):
        if self._real is not None:
            return self._real.close()
        return True

    def save(self):
        if self._real is not None:
            return self._real.save()
        return True

    def __iter__(self):
        if self._real is not None:
            return iter(self._real)
        return iter([])
