# Tina4 Firebird Driver — Uses firebird-driver or fdb (optional).
"""
Firebird adapter using firebird-driver (preferred) or fdb (fallback).

    db = Database("firebird://user:pass@localhost:3050/path/to/database.fdb")

Requires: pip install firebird-driver  (or pip install fdb for legacy)
"""
import os
import re
from urllib.parse import urlparse, unquote, parse_qs
from tina4_python.database.database_url import url_credentials
from tina4_python.database.adapter import DatabaseAdapter, DatabaseResult, SQLTranslator


# Detects a Windows drive-letter prefix like "C:/" or "C:\". The leading-slash
# variant ("/C:/...") shows up after a URL parse strips one slash off
# "firebird://host:port/C:/...".
_WIN_DRIVE_RE = re.compile(r"^/?[A-Za-z]:[/\\]")


def _normalize_firebird_db_identifier(raw_path: str) -> str:
    """Turn the URL path component into a Firebird database identifier.

    Firebird is the awkward one — it needs either an absolute file path
    on the server, a Windows drive-letter path, or an alias name. The
    classic URI form uses a double-slash to keep the leading "/" of an
    absolute path through ``urlparse``::

        firebird://host:port//firebird/data/app.fdb   →  /firebird/data/app.fdb

    But that double slash is unintuitive to anyone used to the way
    postgres / mysql / mssql encode the database name. We accept five
    equivalent forms and normalise all of them:

    * ``//abs/path/db.fdb``    → ``/abs/path/db.fdb``    (classic double-slash)
    * ``/abs/path/db.fdb``     → ``/abs/path/db.fdb``    (single-slash, what most people type)
    * ``/C:/Data/db.fdb``      → ``C:/Data/db.fdb``      (Windows, leading URL slash dropped)
    * ``/C%3A/Data/db.fdb``    → ``C:/Data/db.fdb``      (Windows with URL-encoded colon)
    * ``/employee``            → ``employee``            (alias — single token)

    Aliases are detected as the leftover case: a single token with no
    slashes. Anything path-like is kept as a path.
    """
    decoded = unquote(raw_path)

    # Classic double-slash form: //abs/path → /abs/path
    if decoded.startswith("//"):
        decoded = decoded[1:]

    # Windows drive-letter — drop the URL-introduced leading slash.
    # /C:/Data/db.fdb → C:/Data/db.fdb
    if _WIN_DRIVE_RE.match(decoded):
        if decoded.startswith("/"):
            decoded = decoded[1:]
        return decoded

    # Look at the content after stripping the leading slash. If it's a
    # single token with no separators, it's a Firebird alias — return
    # WITHOUT the leading slash (the alias name itself is the identifier).
    body = decoded[1:] if decoded.startswith("/") else decoded
    if body and "/" not in body and "\\" not in body:
        return body

    # Otherwise it's a file path. If it already has a leading slash,
    # keep it. If it's a relative-looking path (slash-separated but no
    # leading "/") promote it to absolute — Firebird needs absolute paths
    # and we don't know the server's CWD anyway.
    return decoded if decoded.startswith("/") else "/" + decoded


def _resolve_firebird_charset(connection_string: str, kwarg_charset: str | None = None) -> str:
    """Resolve the Firebird connection charset (php #160).

    The adapter used to hardcode ``UTF8`` with no override, which
    double-encodes UTF-8 bytes stored under a legacy ``NONE`` database. This
    resolves the charset from, in precedence order:

    1. the connection URL query — ``firebird://host:port/path?charset=NONE``
    2. an explicit ``charset=`` keyword passed to :meth:`connect`
    3. the ``TINA4_DATABASE_CHARSET`` environment variable
    4. the ``UTF8`` default (unchanged — non-breaking for existing connections)

    Pure config resolution over its inputs (URL string, kwarg, env) — no
    connection is opened, so it is unit-testable without a live server.
    """
    url_charset = None
    query = urlparse(connection_string).query
    if query:
        values = parse_qs(query).get("charset")
        if values:
            url_charset = values[0]
    return (
        url_charset
        or kwarg_charset
        or os.environ.get("TINA4_DATABASE_CHARSET")
        or "UTF8"
    )


# Try modern firebird-driver first, fall back to legacy fdb
_driver = None
_driver_name = None
try:
    import firebird.driver as _driver
    _driver_name = "firebird-driver"
except ImportError:
    try:
        import fdb as _driver
        _driver_name = "fdb"
    except ImportError:
        _driver = None
        _driver_name = None


class FirebirdAdapter(DatabaseAdapter):
    """Firebird database driver using firebird-driver or fdb."""

    # Substring markers (lowercased) that identify a dead-socket Firebird
    # error worth reconnecting for. Idle Firebird connections die silently
    # behind NAT timeouts, server-side ConnectionIdleTimeout, or Docker
    # network rotation; without this the next prepare() crashes the request.
    _DEAD_CONN_MARKERS = (
        "error writing data to the connection",
        "error reading data from the connection",
        "connection shutdown",
        "connection lost",
        "network error",
        "connection is not active",
        "broken pipe",
    )

    def __init__(self):
        super().__init__()
        self._conn = None
        self._in_transaction: bool = False
        # Remembered connection params — populated by connect(), used by
        # _reconnect() when a dead socket is detected mid-request.
        self._connect_params: dict | None = None

    def connect(self, connection_string: str, username: str = "", password: str = "", **kwargs):
        """Connect to Firebird.

        Connection string: firebird://user:pass@host:port/path/to/db.fdb
        Credentials priority: URL > username/password params > adapter defaults (SYSDBA/masterkey).
        """
        if _driver is None:
            raise ImportError(
                "A Firebird driver is required. Install one of:\n"
                "    uv add tina4-python[firebird]    # extra for projects using uv\n"
                "    pip install firebird-driver      # bare driver (or 'fdb' for legacy)\n"
                "    uv add tina4-python[all-db]      # all five database drivers"
            )

        parsed = urlparse(connection_string)
        host = parsed.hostname or "localhost"
        port = parsed.port or 3050

        # Firebird database identifier resolution — two layers:
        #
        # 1. ``TINA4_DATABASE_FIREBIRD_PATH`` env override wins if set.
        #    Useful for Windows users with raw backslash paths (no URL
        #    encoding required) and for ops setups that keep server URL
        #    and DB location in separate config layers.
        # 2. Otherwise normalise the URL path component — accepts every
        #    sensible variant (single/double slash, drive letter, alias).
        env_override = os.environ.get("TINA4_DATABASE_FIREBIRD_PATH", "")
        if env_override:
            db_path = env_override
        else:
            db_path = _normalize_firebird_db_identifier(parsed.path)

        user, password = url_credentials(connection_string, username, password)
        user = user or "SYSDBA"
        password = password or "masterkey"
        # php #160: honour ?charset= in the URL and TINA4_DATABASE_CHARSET so a
        # legacy NONE database isn't force-connected as UTF8 (double-encoding).
        # Pop the kwarg first so it isn't also forwarded into the driver connect
        # via **extra below (which would raise a duplicate-keyword error).
        charset = _resolve_firebird_charset(connection_string, kwargs.pop("charset", None))

        # Cache for transparent reconnect — never logged, lives only in
        # adapter memory alongside the connection it owns.
        self._connect_params = {
            "host": host, "port": port, "db_path": db_path,
            "user": user, "password": password, "charset": charset,
            "extra": dict(kwargs),
        }
        self._open()

    def _open(self) -> None:
        """Open the underlying Firebird connection from cached params."""
        p = self._connect_params
        if p is None:
            raise RuntimeError("FirebirdAdapter._open called before connect()")

        if _driver_name == "firebird-driver":
            # Modern firebird-driver uses dsn format: host/port:path
            dsn = f"{p['host']}/{p['port']}:{p['db_path']}" if p['port'] != 3050 else f"{p['host']}:{p['db_path']}"
            self._conn = _driver.connect(
                dsn,
                user=p["user"],
                password=p["password"],
                charset=p["charset"],
                **p["extra"],
            )
        else:
            # Legacy fdb
            self._conn = _driver.connect(
                host=p["host"],
                port=p["port"],
                database=p["db_path"],
                user=p["user"],
                password=p["password"],
                charset=p["charset"],
                **p["extra"],
            )

    @classmethod
    def _is_dead_connection(cls, exc: BaseException) -> bool:
        """Match dead-socket error messages from firebird-driver / fdb.
        Substring + case-insensitive so we catch both driver wording variants.
        """
        msg = str(exc).lower()
        return any(m in msg for m in cls._DEAD_CONN_MARKERS)

    def _reconnect(self) -> None:
        """Force-close any stale handle and reopen. Safe to call repeatedly;
        idempotent on a dead connection."""
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass  # connection already gone — nothing to clean up
        self._conn = None
        self._in_transaction = False
        self._open()

    def _safe_cursor_execute(self, cursor, sql: str, params: list | None):
        """Execute on a cursor with one transparent reconnect+retry on
        dead-connection errors. Skipped inside an explicit transaction —
        atomicity beats resilience there; the caller handles rollback.

        Returns the cursor (possibly a fresh one after reconnect) so the
        caller can fetch results from it.
        """
        try:
            cursor.execute(sql, params or [])
            return cursor
        except Exception as e:
            if not self._is_dead_connection(e) or self._in_transaction:
                raise
            self._reconnect()
            cursor = self._conn.cursor()
            cursor.execute(sql, params or [])
            return cursor

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: list = None) -> DatabaseResult:
        sql = self._translate_sql(sql)

        # Firebird does not support RETURNING in all versions — strip and emulate
        returning_cols = None
        returning_match = re.search(r"\s+RETURNING\s+(.+)$", sql, re.IGNORECASE)
        if returning_match:
            returning_cols = returning_match.group(1).strip()
            sql = sql[:returning_match.start()]

        cursor = self._conn.cursor()
        cursor = self._safe_cursor_execute(cursor, sql, params)

        records = []
        last_id = None

        if returning_cols:
            # Firebird 2.1+ supports RETURNING but we already stripped it.
            # Use a generator/sequence approach to find the last ID.
            sql_upper = sql.strip().upper()
            if sql_upper.startswith("INSERT"):
                table = self._extract_table(sql)
                try:
                    # Try to get the last inserted row by querying the generator
                    gen_name = f"GEN_{table.upper()}_ID"
                    cursor.execute(f"SELECT GEN_ID({gen_name}, 0) FROM RDB$DATABASE")
                    row = cursor.fetchone()
                    if row:
                        last_id = row[0]
                        if returning_cols.strip() == "*":
                            fetch_sql = f"SELECT * FROM {table} WHERE id = ?"
                        else:
                            fetch_sql = f"SELECT {returning_cols} FROM {table} WHERE id = ?"
                        cursor.execute(fetch_sql, [last_id])
                        desc = cursor.description
                        row = cursor.fetchone()
                        if row and desc:
                            col_names = [d[0].strip().lower() for d in desc]
                            records = [dict(zip(col_names, row))]
                except Exception:
                    pass

        affected = cursor.rowcount if cursor.rowcount >= 0 else 0

        if not self._in_transaction and self.autocommit:
            self._conn.commit()

        return DatabaseResult(
            records=records,
            count=len(records),
            affected_rows=affected,
            last_id=last_id,
            sql=sql,
            adapter=self,
        )

    def fetch(self, sql: str, params: list = None,
              limit: int = 100, offset: int = 0) -> DatabaseResult:
        # v3.13.12: strip trailing `;` — Firebird wraps with COUNT(*)
        # and appends ROWS pagination; a trailing semicolon breaks both.
        sql = self._strip_trailing_semicolons(sql)
        sql = self._translate_sql(sql)
        cursor = self._conn.cursor()

        # Count total rows. The COUNT probe is best-effort — a failure here
        # defaults `total` to 0 — but it must NEVER mask a real failure in the
        # MAIN query below. On a probe failure we get a fresh cursor and let
        # the paginated query run through _safe_cursor_execute, which FAILS
        # LOUD (parity with execute()) instead of looking like "no rows".
        count_sql = f"SELECT COUNT(*) FROM ({sql})"
        try:
            cursor = self._safe_cursor_execute(cursor, count_sql, params)
            total = cursor.fetchone()[0]
        except Exception:
            total = 0
            # Reconnect may have just happened — get a fresh cursor for the
            # paginated query below regardless of whether count succeeded.
            cursor = self._conn.cursor()

        # Apply Firebird pagination — ROWS start TO end.
        # v3.13.12: limit <= 0 means "no pagination" (fetch_all's
        # default — give me ALL rows).
        if limit is None or limit <= 0:
            paginated_sql = sql
        else:
            start = offset + 1
            end = offset + limit
            paginated_sql = f"{sql} ROWS {start} TO {end}"
        cursor = self._safe_cursor_execute(cursor, paginated_sql, params)  # FAILS LOUD

        desc = cursor.description
        col_names = [d[0].strip().lower() for d in desc] if desc else []
        rows = [self._decode_blobs(dict(zip(col_names, row))) for row in cursor.fetchall()]

        return DatabaseResult(records=rows, count=total, limit=limit, offset=offset, sql=sql, adapter=self)

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
        sql = self._strip_trailing_semicolons(sql)
        sql = self._translate_sql(sql)
        cursor = self._conn.cursor()
        cursor = self._safe_cursor_execute(cursor, sql, params)
        desc = cursor.description
        row = cursor.fetchone()
        if row is None:
            return None
        col_names = [d[0].strip().lower() for d in desc] if desc else []
        return self._decode_blobs(dict(zip(col_names, row)))

    @staticmethod
    def _decode_blobs(row: dict) -> dict:
        """Ensure Firebird BLOB columns are proper bytes, not memoryview."""
        for key, value in row.items():
            if isinstance(value, memoryview):
                row[key] = bytes(value)
        return row

    def start_transaction(self):
        # fdb starts transactions automatically on first operation
        self._in_transaction = True

    def commit(self):
        if self._conn:
            self._conn.commit()
        self._in_transaction = False

    def rollback(self):
        if self._conn:
            self._conn.rollback()
        self._in_transaction = False

    def table_exists(self, name: str) -> bool:
        row = self.fetch_one(
            "SELECT RDB$RELATION_NAME FROM RDB$RELATIONS "
            "WHERE RDB$SYSTEM_FLAG = 0 AND RDB$VIEW_BLR IS NULL "
            "AND TRIM(RDB$RELATION_NAME) = ?",
            [name.upper()],
        )
        return row is not None

    def get_tables(self) -> list[str]:
        result = self.fetch(
            "SELECT RDB$RELATION_NAME FROM RDB$RELATIONS "
            "WHERE RDB$SYSTEM_FLAG = 0 AND RDB$VIEW_BLR IS NULL "
            "ORDER BY RDB$RELATION_NAME",
            limit=10000,
        )
        return [r["rdb$relation_name"].strip() for r in result.records]

    def quote_identifier(self, name: str) -> str:
        """Quote an identifier the way Firebird actually stores it: UPPERCASE.

        Firebird folds an UNQUOTED identifier to upper case, and treats a QUOTED
        one as case-sensitive. So `CREATE TABLE probe_t (...)` stores `PROBE_T`,
        and the base implementation's `"probe_t"` then matches nothing:

            INSERT INTO "probe_t" ...  ->  Table unknown - probe_t

        That broke insert/update/delete/truncate against every table created the
        conventional (unquoted) way -- verified against a live Firebird 5.0.4.

        A name the caller has ALREADY quoted is passed through untouched, which is
        the escape hatch for a genuinely case-sensitive lower-case table created
        as `CREATE TABLE "orders"`.
        """
        if not name:
            return name
        open_q, close_q = self.IDENTIFIER_QUOTE
        name = name.strip()
        if name.startswith(open_q) and name.endswith(close_q):
            return name
        if "." in name:
            return ".".join(self.quote_identifier(part) for part in name.split("."))
        # Leave expressions and wildcards alone, exactly like the base class.
        if not name.replace("_", "").replace("$", "").isalnum():
            return name
        return f"{open_q}{name.upper().replace(close_q, close_q * 2)}{close_q}"

    def get_columns(self, table: str) -> list[dict]:
        sql = (
            "SELECT RF.RDB$FIELD_NAME, F.RDB$FIELD_TYPE, RF.RDB$NULL_FLAG, "
            "RF.RDB$DEFAULT_SOURCE "
            "FROM RDB$RELATION_FIELDS RF "
            "JOIN RDB$FIELDS F ON RF.RDB$FIELD_SOURCE = F.RDB$FIELD_NAME "
            "WHERE RF.RDB$RELATION_NAME = ? "
            "ORDER BY RF.RDB$FIELD_POSITION"
        )
        result = self.fetch(sql, [table.upper()], limit=10000)

        # The primary key comes from the constraint catalogue. This used to be
        # hardcoded False for every column, so primary_key() always reported []
        # on Firebird -- which silently broke anything that introspects the key,
        # including the filterless-write guard that takes the PK out of `data`.
        pk_sql = (
            "SELECT SG.RDB$FIELD_NAME FROM RDB$INDEX_SEGMENTS SG "
            "JOIN RDB$RELATION_CONSTRAINTS RC ON SG.RDB$INDEX_NAME = RC.RDB$INDEX_NAME "
            "WHERE RC.RDB$CONSTRAINT_TYPE = 'PRIMARY KEY' "
            "AND RC.RDB$RELATION_NAME = ? "
            "ORDER BY SG.RDB$FIELD_POSITION"
        )
        pk_names: set[str] = set()
        try:
            pk_rows = self.fetch(pk_sql, [table.upper()], limit=10000)
            for row in pk_rows.records:
                value = row.get("rdb$field_name")
                if value:
                    pk_names.add(value.strip().upper())
        except Exception:  # noqa: BLE001 - no PK is not an error
            pk_names = set()
        # Map Firebird field type codes to names
        type_map = {
            7: "SMALLINT", 8: "INTEGER", 10: "FLOAT", 12: "DATE",
            13: "TIME", 14: "CHAR", 16: "BIGINT", 27: "DOUBLE PRECISION",
            35: "TIMESTAMP", 37: "VARCHAR", 261: "BLOB",
        }
        return [
            {
                "name": r["rdb$field_name"].strip() if r["rdb$field_name"] else "",
                "type": type_map.get(r.get("rdb$field_type"), str(r.get("rdb$field_type", ""))),
                "nullable": r.get("rdb$null_flag") is None,
                "default": r.get("rdb$default_source"),
                "primary_key": (r["rdb$field_name"].strip().upper()
                                if r["rdb$field_name"] else "") in pk_names,
            }
            for r in result.records
        ]

    def get_database_type(self) -> str:
        return "firebird"

    # -- SQL Translation -----------------------------------------------

    def _translate_sql(self, sql: str) -> str:
        """Translate portable SQL to Firebird dialect.

        Firebird uses ? placeholders, ROWS...TO instead of LIMIT/OFFSET,
        || for concat (native), no ILIKE, no boolean type, and generators
        instead of AUTOINCREMENT.
        """
        sql = SQLTranslator.limit_to_rows(sql)
        sql = SQLTranslator.ilike_to_like(sql)
        sql = SQLTranslator.boolean_to_int(sql)
        sql = SQLTranslator.auto_increment_syntax(sql, "firebird")
        return sql

    def _supports_returning(self) -> bool:
        # Firebird 2.1+ supports it, but we emulate for consistency
        return False
