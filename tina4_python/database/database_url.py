# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

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
from typing import NamedTuple
from urllib.parse import quote, urlparse, unquote

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

# The password inside URL userinfo. GHSA-h2mr-m3v3-cq8c: the previous
# single-regex form, `(://[^/@\s:]*:)[^/\r\n]*@`, could not cross a `/`, never
# matched `scheme:/` or `scheme//`, and never matched a URL with no host, so
# `postgres://u:Pq1/Rs2@dbhost/appdb`, `postgres:/u:pw@h` and `postgres://u:pw`
# came back VERBATIM. ONE rule now decides where a password is, and the parser
# below (`parse_url`) follows the same rule, so what is masked in a log line is
# exactly what is read as the password on the connect path:
#
#   1. The authority starts after `scheme://`, `scheme:/` or `scheme//`.
#   2. The password starts at the FIRST `:` after that. A `/ ? #`, an `@` or
#      whitespace before that `:` means the text is a path, a query, a
#      `user@host:port` or prose - not a password. (RFC 3986: the user part
#      cannot hold an unencoded `:`, so the password starts at the first one.
#      Letting the user run reach the LAST `:` turned `tina4:s3:cret@host` into
#      `tina4:s3:***@host`, measured 2026-09-24.)
#   3. Userinfo ends at the LAST `@` on the line, so an unencoded `@ / ? # %`
#      or space inside the password cannot leave a tail behind. Over-redaction
#      can mask a host when a second `@` appears later on the same line; it
#      never shows a password. A line, not the whole value: a connection
#      string never spans lines, and one line's `@` must not swallow another's.
#   4. With no `@` after the `:`, the token there is a port or a password. A
#      number followed by the end, a `/` or a `?key=value` query is a port and
#      is left alone; anything else (`u:Pq1Rs2`, `u:12?Pq1Rs2`, `u:12#Pq1Rs2`)
#      is a password and is masked to the end of the line, keeping a trailing
#      `?key=value` query.
#
# KNOWN LIMIT, deliberately not solved: a host-less URL whose password is all
# digits (`postgres://u:123/x`) is indistinguishable from `host:port/path`, so
# it is left as it is. A real URL has a host, which puts an `@` after the
# password and takes rule 3 instead. Likewise `postgres://u:Pq1@Rs2` IS a
# well-formed URL whose password is `Pq1` and whose host is `Rs2`; the host is
# shown, as every host is.
_SCHEME_AUTHORITY = re.compile(r"(?<![A-Za-z0-9+.\-])[A-Za-z][A-Za-z0-9+.\-]*(?:://|:/|//)")
_NOT_A_USER = frozenset("/?#@")
_PORT_END = frozenset("/?#")
_KEPT_QUERY = re.compile(r"\?[A-Za-z0-9_.\-]+=[^\s?#&@]*(?:&[A-Za-z0-9_.\-]+=[^\s?#&@]*)*")
_LINE_BREAK = re.compile(r"(\r\n|\r|\n)")


def _ends_a_port(line: str, end: int) -> bool:
    """Whether what follows an all-digit token lets it be a port.

    A port is followed by the end, whitespace, a `/` path, or a `?key=value`
    query. A digit-led password is not: `driver://u:12?Pq1Rs2` and
    `driver://u:12#Pq1Rs2` would otherwise read as port 12 and show the rest
    (found by the cross-framework mutation run - a `?` with no `key=value`,
    or a `#`, never follows a port in a connection URL).
    """
    if end >= len(line) or line[end] == "/" or line[end].isspace():
        return True
    if line[end] == "?":
        kept = _KEPT_QUERY.match(line, end)
        return kept is not None and (kept.end() == len(line) or line[kept.end()].isspace())
    return False


def _password_span(line: str, start: int):
    """(begin, end) of the password in ``line`` whose authority starts at
    ``start``, or None when there is none. The rule is described above."""
    i = start
    if line.startswith("[", i):
        # A bracketed IPv6 host carries colons that are not a password's.
        close = line.find("]", i)
        if close != -1:
            i = close + 1
    colon = line.find(":", i)
    if colon == -1:
        return None
    if any(ch in _NOT_A_USER or ch.isspace() for ch in line[i:colon]):
        return None
    at = line.rfind("@", colon + 1)
    if at != -1:
        return colon + 1, at
    end = colon + 1
    while end < len(line) and line[end] not in _PORT_END and not line[end].isspace():
        end += 1
    token = line[colon + 1:end]
    if token == "":
        return None
    if token.isdigit() and token.isascii() and _ends_a_port(line, end):
        return None  # a port (see KNOWN LIMIT above)
    stop = len(line)
    query = line.rfind("?", colon + 1)
    if query != -1 and _KEPT_QUERY.fullmatch(line, query):
        stop = query
    return colon + 1, stop


def _redact_line(line: str) -> str:
    out, kept_from, search_from = [], 0, 0
    while True:
        match = _SCHEME_AUTHORITY.search(line, search_from)
        if match is None:
            break
        span = _password_span(line, match.end())
        if span is None:
            search_from = match.end()
            continue
        begin, end = span
        out.append(line[kept_from:begin])
        out.append("***")
        kept_from = search_from = end
    out.append(line[kept_from:])
    return "".join(out)


def redact_url(value: str) -> str:
    """Any connection string with its password replaced by ``***``.

    The ONLY form of a connection string allowed in a log line, an exception, an
    API response or a console print. Unlike :meth:`DatabaseUrl.to_safe_string`
    this needs no successful parse, so it is also safe on the values that reach
    a log precisely BECAUSE they are malformed, and on the non-SQL connection
    strings the framework carries (``TINA4_CACHE_URL``, a broker URL, an ODBC
    DSN). It works on a URL embedded in a longer message too. The scheme, the
    user and the host stay visible, so the line is still useful. A value with
    no credential in it is returned unchanged.
    """
    if not isinstance(value, str) or value == "":
        return value
    value = _ODBC_PASSWORD.sub(r"\1=***", value)
    parts = _LINE_BREAK.split(value)
    # Odd indexes are the line breaks themselves (the split keeps them).
    return "".join(part if index % 2 else _redact_line(part)
                   for index, part in enumerate(parts))


# ── The one URL parser for every connection string ────────────────
# GHSA-h2mr-m3v3-cq8c, the parsing half. `urlparse` ends the authority at the
# FIRST `/ ? #`, so for `postgres://u:Pq1/Rs2@dbhost/appdb` it reads host `u`
# and port `Pq1`, and `.port` raises "Port could not be cast to integer value
# as 'Pq1'" - a stdlib message that quotes the password, which every connect
# wrapper then logged. The AMQP, Kafka, memcached and Mongo-session splitters
# cut at the FIRST `@` and turned `Rs2@dbhost` into a host name. Every
# connection URL in the framework is now split here, by the redaction rule:
# userinfo ends at the LAST `@`, the password starts at the first `:` in it.

_SCHEME_PREFIX = re.compile(r"([A-Za-z][A-Za-z0-9+.\-]*)://")
_NOT_SHOWN = "The value is not shown because it may contain a password."


class UrlParts(NamedTuple):
    """A split connection URL. ``username``/``password`` are percent-DECODED,
    and None when absent (``user:@host`` gives an explicitly empty password)."""
    scheme: str
    username: "str | None"
    password: "str | None"
    hostname: "str | None"
    port: "int | None"
    path: str
    query: str
    fragment: str


def _split_userinfo(url: str, label: str):
    """(scheme as written, raw userinfo or None, host part). Raises generically."""
    match = _SCHEME_PREFIX.match(url) if isinstance(url, str) else None
    if match is None:
        # Covers `scheme:/u:pw@h`, `scheme//u:pw@h` and a bare value: none of
        # them is a URL this framework connects with, and echoing it would
        # print whatever password it carries.
        raise ValueError(
            f"{label}: Invalid URL format - no 'driver://' scheme. "
            f"Expected driver://user:password@host:port/database. {_NOT_SHOWN}"
        )
    rest = url[match.end():]
    if "@" not in rest:
        if _password_span(url, match.end()) is not None:
            # No `@`, yet the redaction rule sees a password (`driver://u:pw`,
            # `driver://u:12?pw`): urlparse would read host `u` and a port,
            # path or query that IS the password. Parser and redactor agree.
            raise ValueError(
                f"{label}: Invalid URL - a password with no '@host' after it, "
                f"or a port that is not a number. {_NOT_SHOWN}"
            )
        return match.group(1), None, rest
    userinfo, _, host_part = rest.rpartition("@")
    user = userinfo.partition(":")[0]
    if any(ch in "/?#" or ch.isspace() for ch in user):
        # The `@` the userinfo would end at sits in the path or the query
        # (`driver://host/db?owner=a@b`): the `@` count does not match what
        # can be userinfo. Refuse rather than guess a host.
        raise ValueError(
            f"{label}: Invalid URL - an '@' outside the user:password part. "
            f"Percent-encode an '@' in a path or query as %40. {_NOT_SHOWN}"
        )
    return match.group(1), userinfo, host_part


def parse_url(url: str, label: str = "Connection URL") -> UrlParts:
    """Split a ``scheme://user:password@host:port/path?query`` URL.

    Never puts the value, or any part of the userinfo, in an error, and never
    chains a stdlib error that quotes it (no ``__cause__``, no ``__context__``).
    """
    scheme, userinfo, host_part = _split_userinfo(url, label)
    username = password = None
    if userinfo is not None:
        user, colon, secret = userinfo.partition(":")
        username = unquote(user) if user else None
        password = unquote(secret) if colon else None
    # The error is raised OUTSIDE the except block. `raise ... from None` only
    # SUPPRESSES the context: the stdlib error (which quotes the token) still
    # rides along as `__context__` for a debugger, a traceback renderer or the
    # dev error overlay to print. Measured: it did, for `driver://u:Pq1Rs2`.
    reason = None
    try:
        parsed = urlparse(f"{scheme}://{host_part}")
        hostname = parsed.hostname or None
        port = parsed.port
    except ValueError as error:
        reason = str(error)
    if reason is not None:
        if userinfo is not None:
            # The host part is everything after the LAST `@`, so the stdlib's
            # text (e.g. "Port could not be cast to integer value as
            # 'notaport'") cannot hold the password - it names the bad token.
            raise ValueError(f"{label}: Invalid URL - {reason}")
        # No `@`: the "port" may BE the password (`driver://user:password`).
        raise ValueError(
            f"{label}: Invalid URL - the host or port is malformed "
            f"(a port must be a number from 0 to 65535). {_NOT_SHOWN}"
        )
    return UrlParts(scheme.lower(), username, password, hostname, port,
                    parsed.path or "", parsed.query or "", parsed.fragment or "")


def normalise_url(url: str, label: str = "Connection URL") -> str:
    """The same URL with its userinfo percent-encoded, for third-party clients.

    redis-py and pymongo parse a URL with ``urlparse`` themselves, so a password
    holding `/ ? # @` is misread there (and quoted in THEIR errors). Encoding
    the userinfo by the rule above hands them a URL they read the way Tina4
    does. Already-encoded input is decoded first, so nothing is encoded twice.
    Refuses a malformed URL with :func:`parse_url`'s generic errors.
    """
    parts = parse_url(url, label)
    scheme, userinfo, host_part = _split_userinfo(url, label)
    if userinfo is None:
        return url
    auth = quote(parts.username or "", safe="")
    if parts.password is not None:
        auth += ":" + quote(parts.password, safe="")
    return f"{scheme}://{auth}@{host_part}"


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

    DISPLAY REDACTS, FIDELITY DOES NOT. ``repr()``, ``str()`` and
    ``to_safe_string()`` replace the password with the redaction marker, so a log
    line, a traceback or a status payload is safe. ``pickle`` deliberately does
    not: its contract is a faithful round trip, and a masked pickle would restore
    an object whose password is the literal "***". tina4-php reaches the same
    boundary with ``serialize()``/``var_export()``.

    The consequence: DO NOT PERSIST THIS OBJECT. A DatabaseUrl pickled into a
    cache, a session, a queue payload or a multiprocessing hand-off puts the
    password in cleartext on disk or on a wire. Record ``to_safe_string()``
    instead, or store the redacted parts. ``TestTheFidelityBoundaryIsEnforced``
    in tests/test_credential_leak_paths.py fails the build if framework code
    ever pickles one.

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
        # GHSA-h2mr-m3v3-cq8c: split by the ONE shared rule (userinfo ends at
        # the LAST `@`), not by urlparse, which read `u:Pq1/Rs2@host` as host
        # `u`, port `Pq1` and raised a stdlib message quoting the password.
        # parse_url refuses a URL without `driver://` (so `postgres:/u:pw@h`
        # and `postgres//u:pw@h` too) generically and never chains (from None).
        parts = parse_url(url, "DatabaseUrl")
        scheme = parts.scheme
        host = parts.hostname
        port = parts.port
        path = parts.path

        engine = ENGINE_ALIASES.get(scheme)
        if engine is None:
            raise ValueError(
                f"DatabaseUrl: Unsupported database scheme '{scheme}'. "
                f"Supported: {', '.join(ENGINE_ALIASES)}"
            )

        self.engine = engine
        self.host = host
        self.port = port or DEFAULT_PORTS.get(engine)
        self.username = parts.username
        # None vs "": `postgres://user:@host/db` carries an EXPLICITLY EMPTY
        # password, which is a different value from no password at all and
        # must not let the env fallback fire. See __init__. (parse_url decodes.)
        self.password = parts.password

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
    parsed = parse_url(connection_string, "Database")
    user = parsed.username or (username or "")
    pwd = parsed.password if parsed.password is not None else (password or "")
    return user, pwd
