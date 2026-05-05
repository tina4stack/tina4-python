# Tina4 Firebird Driver — Uses firebird-driver or fdb (optional).
"""
Firebird adapter using firebird-driver (preferred) or fdb (fallback).

    db = Database("firebird://user:pass@localhost:3050/path/to/database.fdb")

Requires: pip install firebird-driver  (or pip install fdb for legacy)
"""
import os
import re
from urllib.parse import urlparse, unquote
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
                "A Firebird driver is required. "
                "Install: pip install firebird-driver  (or pip install fdb for legacy)"
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

        user = parsed.username or username or "SYSDBA"
        password = parsed.password or password or "masterkey"
        charset = kwargs.pop("charset", "UTF8")

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
        sql = self._translate_sql(sql)
        cursor = self._conn.cursor()

        # Count total rows
        count_sql = f"SELECT COUNT(*) FROM ({sql})"
        try:
            cursor = self._safe_cursor_execute(cursor, count_sql, params)
            total = cursor.fetchone()[0]
        except Exception:
            total = 0
            # Reconnect may have just happened — get a fresh cursor for the
            # paginated query below regardless of whether count succeeded.
            cursor = self._conn.cursor()

        # Apply Firebird pagination — ROWS start TO end
        start = offset + 1
        end = offset + limit
        paginated_sql = f"{sql} ROWS {start} TO {end}"
        cursor = self._safe_cursor_execute(cursor, paginated_sql, params)

        desc = cursor.description
        col_names = [d[0].strip().lower() for d in desc] if desc else []
        rows = [self._decode_blobs(dict(zip(col_names, row))) for row in cursor.fetchall()]

        return DatabaseResult(records=rows, count=total, limit=limit, offset=offset, sql=sql, adapter=self)

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
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

    def insert(self, table: str, data: dict) -> DatabaseResult:
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        return self.execute(sql, list(data.values()))

    def update(self, table: str, data: dict,
               filter_sql: str = "", params: list = None) -> DatabaseResult:
        set_clause = ", ".join(f"{k} = ?" for k in data.keys())
        sql = f"UPDATE {table} SET {set_clause}"
        all_params = list(data.values())

        if filter_sql:
            sql += f" WHERE {filter_sql}"
            all_params += params or []

        return self.execute(sql, all_params)

    def delete(self, table: str,
               filter_sql: str = "", params: list = None) -> DatabaseResult:
        sql = f"DELETE FROM {table}"
        if filter_sql:
            sql += f" WHERE {filter_sql}"
        return self.execute(sql, params or [])

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
                "primary_key": False,
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
