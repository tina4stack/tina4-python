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
import re
from urllib.parse import urlparse, unquote

# ── Redaction ─────────────────────────────────────────────────
# THE single redaction primitive. Everything that puts a connection string in
# front of a human - a log line, an exception, an API dump, a console print -
# goes through `redact_url`, and `to_safe_string()` is built on it too.
#
# Measured 2026-08-02 on this tree, before the fix:
#   DatabaseUrl("odbc:///DRIVER={PostgreSQL};...;PWD=s3ntinel-Pa55 word;")
#       .to_safe_string()  ->  returned the DSN VERBATIM, PWD= and all.
# The negative test `to_safe_string_never_contains_the_password` was green the
# whole time because the shared corpus had no odbc row. A guard whose fixture
# has no row for the case that matters protects nothing.

# An ODBC keyword/value DSN: `KEY=VALUE;KEY=VALUE`. A VALUE may be brace-quoted,
# and the braces are what let it contain `;` and spaces - so match `{...}` FIRST
# and only then fall back to "up to the next `;`". Matching `\S*` here would be
# the tina4-php C4 bug (`preg_replace('/\bpassword=\S*/i')`), where a password
# containing a space kept its tail in the "redacted" message. `(?:[^}]|\}\})*`
# consumes ODBC's doubled-brace escape for a literal `}`, so `PWD={pa}}ss}` is
# redacted whole instead of ending at the first brace and leaving `ss` behind.
_ODBC_PASSWORD = re.compile(
    r"(?i)\b(PWD|PASSWORD)\s*=\s*(?:\{(?:[^}]|\}\})*\}|[^;]*)")

# The password inside URL userinfo: `scheme://user:PASSWORD@host`. The password
# run is greedy up to the LAST `@` before the authority ends, so an un-encoded
# `@` inside the password (`redis://u:p@ss@host`) cannot leave `ss` behind. It
# never crosses a `/`, so a port (`host:6379/db`) is never mistaken for one.
#
# It MUST allow a space. Excluding whitespace here was this very fix's first
# draft and the space-bearing sentinel caught it inside the hour: a password of
# "s3ntinel-Pa55 word" stopped the run at the space, the `@` was never reached,
# and the whole URL came back UNREDACTED - the same "stops at the first
# whitespace" defect as tina4-php's `\bpassword=\S*` (C4). Newlines stay
# excluded because a connection string never spans lines, and allowing them
# would let one line's `@` swallow another's.
_URL_PASSWORD = re.compile(r"(://[^/@\s]*:)[^/\r\n]*@")


def redact_url(value: str) -> str:
    """Any connection string with its password replaced by ``***``.

    The ONLY form of a connection string allowed in a log line, an exception, an
    API response or a console print. Unlike :meth:`DatabaseUrl.to_safe_string`
    this needs no successful parse, so it is also safe on the values that reach
    a log precisely BECAUSE they are malformed, and on the non-SQL connection
    strings the framework carries (``TINA4_CACHE_URL``, a broker URL, an ODBC
    DSN). A value with no credential in it is returned unchanged.
    """
    if not isinstance(value, str) or value == "":
        return value
    return _URL_PASSWORD.sub(r"\1***@", _ODBC_PASSWORD.sub(r"\1=***", value))

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
        password: None when the URL carries no password at all; ``""`` when the
            URL says ``user:@host``, which is an EXPLICITLY EMPTY password.
            Absent and blank are different values and they behave differently:
            only ``None`` lets the ``TINA4_DATABASE_PASSWORD`` fallback fire.
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

        # Separate credentials fill in only when the URL carried none. `is None`
        # is load-bearing: `postgres://user:@host/db` means "this account has an
        # empty password", so the env fallback must NOT quietly authenticate
        # with something else. Measured 2026-08-02 before the fix: that URL plus
        # TINA4_DATABASE_PASSWORD connected with the ENV password, so one .env
        # authenticated two different ways depending on the framework.
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
            # An ODBC DSN keeps its password in a `PWD=` keyword, not in
            # userinfo, so it needs the keyword redaction or this branch hands
            # back the credential verbatim - which is exactly what it did.
            return f"odbc:///{redact_url(self.connection_string or '')}"

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
        """Parse, and NEVER put the raw URL in an error message.

        Measured 2026-08-02 on this tree, before the fix::

            DatabaseUrl("notaurl-with-s3ntinel-Pa55 word")
            ValueError: DatabaseUrl: Invalid URL format 'notaurl-with-s3ntinel-Pa55 word'

        A typo in TINA4_DATABASE_URL therefore wrote the password into the boot
        log, the crash report, the dev error overlay (which renders
        ``str(exception)``) and the CI log. The SCHEME and the REASON are what
        fixes a broken URL; the URL itself never is, because it is the thing
        carrying the credential. When there is no scheme there is nothing safe
        left to echo, so we name the fault and the expected shape instead.
        """
        try:
            parsed = urlparse(url)
            scheme = (parsed.scheme or "").lower()
            # Read every attribute inside the guard: `.port` and `.hostname` are
            # lazy properties and raise for a non-integer port or a malformed
            # IPv6 literal, long after urlparse() itself returned.
            host = parsed.hostname or None
            port = parsed.port
            raw_username = parsed.username
            raw_password = parsed.password
            path = parsed.path or ""
        except ValueError as reason:
            # stdlib's text names only the offending token (e.g. "Port could not
            # be cast to integer value as 'notaport'"), never the userinfo - but
            # it does not identify itself as a Tina4 error. Re-raise as ours and
            # break the chain: a chained frame is one more place holding the raw
            # URL for a debugger or a traceback renderer to pick up.
            raise ValueError(f"DatabaseUrl: Invalid URL - {reason}") from None

        if scheme == "":
            raise ValueError(
                "DatabaseUrl: Invalid URL format - no 'driver://' scheme. "
                "Expected driver://user:password@host:port/database. "
                "The value is not shown because it may contain a password."
            )

        engine = ENGINE_ALIASES.get(scheme)
        if engine is None:
            raise ValueError(
                f"DatabaseUrl: Unsupported database scheme '{scheme}'. "
                f"Supported: {', '.join(ENGINE_ALIASES)}"
            )

        self.engine = engine
        self.host = host
        self.port = port or DEFAULT_PORTS.get(engine)
        self.username = unquote(raw_username) if raw_username else None
        # `is not None`, not truthiness: `postgres://user:@host/db` carries an
        # EXPLICITLY EMPTY password, which is a different value from no password
        # at all and must not let the env fallback fire. See __init__.
        self.password = unquote(raw_password) if raw_password is not None else None

        # Strip EXACTLY ONE leading slash - the URL path separator. Stripping
        # every slash turns the documented absolute Firebird form
        # `firebird://host:3050//var/lib/db.fdb` into the RELATIVE
        # `var/lib/db.fdb`. Verified against live Firebird 5.0.4: the driver
        # takes one or two leading slashes and rejects a relative path outright.
        database = _strip_one_slash(path)
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
    carries NO password at all. ``driver://user:@host/db`` carries an
    EXPLICITLY EMPTY password, which is a different value from an absent one, so
    it wins over the fallback exactly like any other URL password would.

    This is the function on the CONNECT path - five adapters call it - so it is
    where the difference actually authenticates. Measured 2026-08-02 against the
    live PostgreSQL on 192.168.88.99:55432 before the fix:
    ``Database("postgres://tina4:@.../tina4_py")`` with TINA4_DATABASE_PASSWORD
    set CONNECTED, using the env password the URL had explicitly overridden.

    Args:
        connection_string: A ``driver://user:pass@host:port/db`` URL.
        username: Fallback used when the URL has no user.
        password: Fallback used when the URL has no password at all.

    Returns:
        The decoded ``(username, password)`` pair; empty strings when neither
        the URL nor the fallback supplies one.
    """
    parsed = urlparse(connection_string)
    user = unquote(parsed.username) if parsed.username else (username or "")
    raw_password = parsed.password
    pwd = unquote(raw_password) if raw_password is not None else (password or "")
    return user, pwd
