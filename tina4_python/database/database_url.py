# Tina4 DatabaseUrl — a parsed connection URL, as a value.
"""
Feature 5 of the feature audit.

Python had no parser to call. URL handling was inline in ``Database.__init__`` /
``_create_adapter``, so a URL could not be parsed without building a connection
object: the parse could not be unit tested on its own, the four frameworks could
not be compared without standing up a database, and `tina4 doctor` or the setup
wizard had nothing to call to validate a URL before using it.

Python also parsed TWICE, two different ways - ``urlparse`` for the scheme, then
a deliberate raw-string strip for sqlite because urlparse collapses the path.
That second parse is still the right call and now lives in one place.

Core Principle 6 says a connection string must mean literally the same thing in
every framework. ``tests/fixtures/database_url_corpus.json`` is the answer key,
byte-identical in all four.
"""
import os
from urllib.parse import urlparse, unquote

# URL scheme to CANONICAL engine. Alias resolution happens ONCE, here, so
# nothing downstream ever compares raw schemes.
#
# `sqlite3` is accepted because the driver is literally named sqlite3 in every
# framework (Python's sqlite3 module, Ruby's sqlite3 gem, PHP's ext-sqlite3,
# Node's node:sqlite), so people type it. The "3" is a file-format version, not
# a different engine, which is why the canonical name stays `sqlite`.
ENGINE_ALIASES = {
    "sqlite": "sqlite",
    "sqlite3": "sqlite",
    "postgres": "postgres",
    "postgresql": "postgres",
    "pgsql": "postgres",
    "mysql": "mysql",
    "mssql": "mssql",
    "sqlserver": "mssql",
    "firebird": "firebird",
    "mongodb": "mongodb",
    "odbc": "odbc",
}

# Applied AT PARSE. The port is part of our contract, not the driver's business:
# a URL with no port must yield the same struct in all four.
DEFAULT_PORTS = {
    "postgres": 5432,
    "mysql": 3306,
    "mssql": 1433,
    "firebird": 3050,
    "mongodb": 27017,
}


def _strip_one_slash(path: str) -> str:
    """Strip EXACTLY ONE leading slash: the URL path separator, never more."""
    return path[1:] if path.startswith("/") else path


class DatabaseUrl:
    """A parsed connection URL. Constructed from a string, and nothing else.

    Attributes:
        engine: canonical engine name (sqlite, postgres, mysql, mssql, firebird,
            mongodb, odbc). Never an adapter class name.
        host: None for sqlite and odbc - a file or a DSN string has no host.
        port: None for sqlite and odbc; otherwise always set (engine default).
        database: the database name, or the file for sqlite.
        username: None when absent, never an empty string - absent and blank differ.
        password: None when absent.
        connection_string: odbc only - the raw string handed to the driver.
    """

    __slots__ = ("engine", "host", "port", "database", "username", "password",
                 "connection_string")

    def __init__(self, url: str, username: str = "", password: str = ""):
        if not isinstance(url, str) or url.strip() == "":
            raise ValueError("DatabaseUrl: the URL is empty")

        self.host = None
        self.port = None
        self.database = ""
        self.username = None
        self.password = None
        self.connection_string = None

        if url.startswith("sqlite:") or url.startswith("sqlite3:"):
            self._parse_sqlite(url)
        elif url.startswith("odbc:///"):
            self.engine = "odbc"
            self.connection_string = url[len("odbc:///"):]
        else:
            self._parse_standard(url)

        # Separate credentials fill in only when the URL carried none.
        if self.username is None and username:
            self.username = username
        if self.password is None and password:
            self.password = password

    @classmethod
    def from_env(cls, key: str = "TINA4_DATABASE_URL") -> "DatabaseUrl | None":
        """Parse the configured URL, or None when the variable is not set."""
        url = (os.environ.get(key) or "").strip()
        if url == "":
            return None
        return cls(
            url,
            os.environ.get("TINA4_DATABASE_USERNAME", ""),
            os.environ.get("TINA4_DATABASE_PASSWORD", ""),
        )

    def dsn(self) -> str:
        """Connection target. sqlite and odbc are the whole value."""
        if self.engine == "sqlite":
            return self.database
        if self.engine == "odbc":
            return self.connection_string or ""
        dsn = self.host or ""
        if self.port is not None:
            dsn += f":{self.port}"
        if self.database:
            dsn += f"/{self.database}"
        return dsn

    def to_safe_string(self) -> str:
        """The URL with the password replaced by ``***``.

        The ONLY form allowed in a log line or an error message: a connection URL
        in a log is a credential leak. It round-trips the input, so it stays
        readable as well as safe.
        """
        if self.engine == "sqlite":
            return f"sqlite:///{self.database}"
        if self.engine == "odbc":
            return f"odbc:///{self.connection_string or ''}"

        out = f"{self.engine}://"
        if self.username is not None:
            out += self.username
            if self.password is not None:
                out += ":***"
            out += "@"
        out += self.host or ""
        if self.port is not None:
            out += f":{self.port}"
        if self.database:
            out += f"/{self.database}"
        return out

    def __repr__(self) -> str:
        # repr() lands in tracebacks and debuggers, so it MUST be the safe form.
        return f"DatabaseUrl({self.to_safe_string()!r})"

    # ── parsing ───────────────────────────────────────────────

    def _parse_sqlite(self, url: str) -> None:
        """sqlite is parsed on the RAW string, never through urlparse.

        urlparse collapses ``sqlite:/x`` and ``sqlite:///x`` to the same path,
        which loses the difference between a one-slash ABSOLUTE path and the
        documented three-slash RELATIVE form - the "sqlite:<abspath> silently
        goes relative" footgun.

            sqlite:///app.db       -> app.db        (three slashes = relative)
            sqlite:////abs/app.db  -> /abs/app.db   (four slashes = absolute)
            sqlite:/abs/app.db     -> /abs/app.db   (one slash = a real absolute)
            sqlite:app.db          -> app.db
        """
        self.engine = "sqlite"
        if url.startswith("sqlite3:"):
            url = "sqlite:" + url[len("sqlite3:"):]

        if url in ("sqlite::memory:", "sqlite:///:memory:"):
            self.database = ":memory:"
        elif url.startswith("sqlite:///"):
            self.database = _strip_one_slash(url[len("sqlite://"):])
        elif url.startswith("sqlite://"):
            self.database = url[len("sqlite://"):]
        else:
            self.database = url[len("sqlite:"):]

    def _parse_standard(self, url: str) -> None:
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        if scheme == "":
            raise ValueError(f"DatabaseUrl: Invalid URL format '{url}'")

        engine = ENGINE_ALIASES.get(scheme)
        if engine is None:
            raise ValueError(
                f"DatabaseUrl: Unsupported database scheme '{scheme}'. "
                f"Supported: {', '.join(ENGINE_ALIASES)}"
            )

        self.engine = engine
        self.host = parsed.hostname or None
        self.port = parsed.port or DEFAULT_PORTS.get(engine)
        self.username = unquote(parsed.username) if parsed.username else None
        self.password = unquote(parsed.password) if parsed.password else None

        # Strip EXACTLY ONE leading slash - the URL path separator. Stripping
        # every slash turns the documented absolute Firebird form
        # `firebird://host:3050//var/lib/db.fdb` into the RELATIVE
        # `var/lib/db.fdb`. Verified against live Firebird 5.0.4: the driver
        # takes one or two leading slashes and rejects a relative path outright.
        database = _strip_one_slash(parsed.path or "")
        self.database = database or ("tina4" if engine == "mongodb" else "")


def url_credentials(connection_string: str,
                    username: str = "",
                    password: str = "") -> tuple[str, str]:
    """The (username, password) a URL carries, PERCENT-DECODED.

    ``urlparse().username`` and ``.password`` return the RAW userinfo - Python's
    stdlib does not decode them. Five adapters read those attributes directly,
    so a password containing any character that has to be escaped in a URL
    (``!``, ``@``, ``:``, ``/``, ``#``) was sent to the driver still encoded and
    the connection failed with a plain "login failed". Nothing in the message
    pointed at the URL, which is what made it expensive to find.

    Ruby, PHP and Node all decode on this path already; Python was the only one
    that did not, and Python is the master.

    An explicit ``username``/``password`` argument is used only when the URL
    carries none, which preserves the documented "URL wins" precedence.

    Args:
        connection_string: A ``driver://user:pass@host:port/db`` URL.
        username: Fallback used when the URL has no user.
        password: Fallback used when the URL has no password.

    Returns:
        The decoded ``(username, password)`` pair; empty strings when neither
        the URL nor the fallback supplies one.
    """
    parsed = urlparse(connection_string)
    user = unquote(parsed.username) if parsed.username else (username or "")
    pwd = unquote(parsed.password) if parsed.password else (password or "")
    return user, pwd
