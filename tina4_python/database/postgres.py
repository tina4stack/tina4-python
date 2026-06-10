# Tina4 PostgreSQL Driver — Uses psycopg2 (optional).
"""
PostgreSQL adapter using psycopg2.

    db = Database("postgresql://user:pass@localhost:5432/mydb")
    db = Database("postgres://user:pass@localhost:5432/mydb")

Requires: pip install psycopg2-binary
"""
import re
from urllib.parse import urlparse
from tina4_python.database.adapter import DatabaseAdapter, DatabaseResult, SQLTranslator


class PostgreSQLAdapter(DatabaseAdapter):
    """PostgreSQL database driver using psycopg2."""

    def __init__(self):
        super().__init__()
        self._conn = None
        self._in_transaction: bool = False
        self.last_error: str | None = None

    @staticmethod
    def _safe_execute(cursor, sql: str, params=None):
        """Wrapper for ``cursor.execute`` that side-steps psycopg2's
        always-on ``%`` substitution when no params are needed.

        Issue #40: psycopg2 interprets ``%`` characters in the SQL
        as parameter placeholders WHENEVER the ``params`` argument is
        supplied — even an empty list ``[]``. So a migration body
        containing ``RAISE EXCEPTION 'thing % conflicts with %', a, b``
        (perfectly valid PL/pgSQL) blows up with the misleading
        ``list index out of range`` because psycopg2 thinks ``%`` is a
        placeholder and there are no values to substitute.

        Pass ``None`` (or omit the second arg) and psycopg2 skips the
        substitution pass entirely — literal ``%`` flows through
        untouched. So we route empty/None params through that path.

        Kept static for direct unit-test access (a number of
        regression tests in test_postgres_percent_substitution.py call
        it with a fake cursor). For the error-aware variant that adds
        logging + auto-rollback (issue #46), use the instance method
        :meth:`_exec_with_handling`.
        """
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)

    def _heal_aborted_txn(self):
        """Issue #46 follow-on (v3.13.8): pre-flight rollback if the
        connection arrived in an aborted-transaction state.

        v3.13.6 added auto-rollback inside :meth:`_on_query_error` — that
        clears the abort *on* a failure the wrapper catches. But the
        connection can still arrive poisoned from elsewhere:

        - A boot-time query that failed before request handling started
          (migration probe, ORM ``information_schema`` lookup, etc.)
        - A failure inside an explicit transaction where the user owned
          the rollback but never issued one
        - A direct ``cursor.execute`` call in another adapter method
          (e.g. the ``SELECT lastval()`` SAVEPOINT probe) that managed to
          leave the txn dirty

        In all those cases the *next* query — even one routed through
        our wrapper — hits ``InFailedSqlTransaction`` immediately, and
        the cascade message buries whatever the original cause was.

        Healing fix: before executing, ask psycopg2 whether the
        connection is in ``TRANSACTION_STATUS_INERROR`` and rollback if
        so. Only when NOT inside an explicit transaction — explicit txns
        stay under the caller's control.

        Reported by Schalk (24rent) against v3.13.7.
        """
        if self._in_transaction or self._conn is None:
            return
        try:
            import psycopg2.extensions as _ext
            status = self._conn.info.transaction_status
        except Exception:
            return
        if status != _ext.TRANSACTION_STATUS_INERROR:
            return
        try:
            self._conn.rollback()
        except Exception:
            # If even the heal-rollback fails, fall through — the next
            # cursor.execute will raise with the real psycopg2 error and
            # _on_query_error will pick it up. Better than masking.
            return
        try:
            from tina4_python.debug import Log
            Log.warning(
                "PostgreSQL connection arrived in aborted-transaction "
                "state — issued pre-flight ROLLBACK so the next query "
                "starts clean. Look back in the log for the original "
                "PostgreSQL query failed entry."
            )
        except Exception:
            pass

    def _exec_with_handling(self, cursor, sql: str, params=None):
        """Run a query through :meth:`_safe_execute` and surface failures.

        Issue #46: psycopg2 keeps the connection in an
        ``InFailedSqlTransaction`` state after any failed query — every
        subsequent statement returns the cascade message ``current
        transaction is aborted, commands ignored until end of transaction
        block``, *far* from the actual cause. Without framework-side
        logging, the original SQL + error never reach the user.

        This method:

        0. (v3.13.8) Pre-flight heal — if the connection arrived in an
           aborted-transaction state from anywhere outside this wrapper,
           rollback first so this query starts on a clean txn.
        1. Logs failures via ``Log.error`` with SQL+params context
        2. Stores them on ``self.last_error``
        3. Auto-rollbacks on failure when NOT inside an explicit
           transaction (so the next caller gets a clean connection)
        4. Re-raises so callers still see the failure

        Inside an explicit transaction we do NOT auto-rollback — the
        user owns that transaction (could be running a SAVEPOINT/retry
        pattern). We still log + store ``last_error`` so they can
        diagnose, and the heal step also defers to explicit txns.
        """
        self._heal_aborted_txn()
        try:
            self._safe_execute(cursor, sql, params)
        except Exception as e:
            self._on_query_error(e, sql, params)
            raise

    def _on_query_error(self, exc: Exception, sql: str, params=None):
        """Handle a failed query: log, store, auto-rollback if implicit."""
        # Lazy import — avoid circular import at module load and let the
        # framework boot without Log if something exotic is happening.
        try:
            from tina4_python.debug import Log
            preview = sql.strip().splitlines()[0][:200] if sql else "<no sql>"
            Log.error(
                f"PostgreSQL query failed: {exc.__class__.__name__}: {exc}",
                sql=preview,
                params=params,
            )
        except Exception:
            pass

        self.last_error = str(exc)

        # If the query failed *outside* an explicit transaction block,
        # rollback the implicit one so the connection becomes usable
        # again. Without this, every subsequent query on this connection
        # cascades into ``InFailedSqlTransaction`` until something else
        # calls rollback. With it, the next caller sees a clean conn
        # and the actual error from this call propagates as the cause.
        if not self._in_transaction and self._conn is not None:
            try:
                self._conn.rollback()
            except Exception:
                # Don't mask the original error if rollback itself fails.
                pass

    def connect(self, connection_string: str, username: str = "", password: str = "", **kwargs):
        """Connect to PostgreSQL.

        Connection string: postgresql://user:pass@host:port/dbname
        Credentials priority: URL > username/password params > adapter defaults.
        """
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError:
            raise ImportError(
                "psycopg2 is required for PostgreSQL connections. Install one of:\n"
                "    uv add tina4-python[postgres]   # extra for projects using uv\n"
                "    pip install psycopg2-binary    # bare driver\n"
                "    uv add tina4-python[all-db]    # all five database drivers"
            )

        parsed = urlparse(connection_string)
        self._conn = psycopg2.connect(
            host=parsed.hostname or "localhost",
            port=parsed.port or 5432,
            user=parsed.username or username or "",
            password=parsed.password or password or "",
            dbname=parsed.path.lstrip("/") if parsed.path else "",
            **kwargs,
        )
        # Use RealDictCursor for dict-style rows
        self._conn.autocommit = False

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: list = None) -> DatabaseResult:
        import psycopg2.extras

        sql = self._translate_sql(sql)

        # Handle RETURNING clause natively
        has_returning = bool(
            re.search(r"\bRETURNING\b", sql, re.IGNORECASE)
        )

        cursor = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        self._exec_with_handling(cursor, sql, params)

        records = []
        last_id = None

        if has_returning and cursor.description:
            records = [dict(row) for row in cursor.fetchall()]
            if records and "id" in records[0]:
                last_id = records[0]["id"]

        if not has_returning:
            # Try to get last inserted ID for INSERT statements.
            #
            # Issue #38: ``SELECT lastval()`` raises on tables with no sequence
            # (UUID, ULID, hash PKs etc.). The exception itself isn't fatal,
            # but psycopg2 marks the whole transaction as aborted, so every
            # subsequent statement on this connection fails with
            # ``InFailedSqlTransaction`` — far away from the real cause and
            # with ``last_error`` still ``None``.
            #
            # Fix: wrap the probe in a SAVEPOINT. If ``lastval()`` raises, we
            # ROLLBACK TO SAVEPOINT and the outer transaction stays usable;
            # ``last_id`` just stays ``None`` (same as before for non-INSERT
            # statements). On success we RELEASE SAVEPOINT.
            sql_upper = sql.strip().upper()
            if sql_upper.startswith("INSERT"):
                cursor.execute("SAVEPOINT _t4_lastval_probe")
                try:
                    cursor.execute("SELECT lastval()")
                    row = cursor.fetchone()
                    if row:
                        last_id = list(row.values())[0]
                    cursor.execute("RELEASE SAVEPOINT _t4_lastval_probe")
                except Exception:
                    cursor.execute("ROLLBACK TO SAVEPOINT _t4_lastval_probe")

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
        import psycopg2.extras

        sql = self._translate_sql(sql)

        # v3.13.8: heal first so the COUNT probe below doesn't open on a
        # poisoned connection — the probe uses raw _safe_execute (it's
        # allowed to fail without polluting last_error) so it bypasses
        # _exec_with_handling's heal step.
        self._heal_aborted_txn()

        cursor = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Count total rows
        count_sql = f"SELECT COUNT(*) AS cnt FROM ({sql}) AS _count_subquery"
        try:
            self._safe_execute(cursor, count_sql, params)
            total = cursor.fetchone()["cnt"]
        except Exception:
            total = 0
            # If the probe failed because the connection arrived (or
            # became) aborted, roll back so the real pagination query
            # below sees a clean txn. Without this we'd cascade.
            if not self._in_transaction and self._conn is not None:
                try:
                    self._conn.rollback()
                except Exception:
                    pass

        # Apply pagination — the real query, so use the error-handling
        # wrapper. The count probe above is best-effort and stays on
        # _safe_execute (a failed probe shouldn't taint last_error).
        paginated_sql = f"{sql} LIMIT %s OFFSET %s"
        paginated_params = (params or []) + [limit, offset]
        self._exec_with_handling(cursor, paginated_sql, paginated_params)
        rows = [self._decode_blobs(dict(row)) for row in cursor.fetchall()]

        return DatabaseResult(records=rows, count=total, limit=limit, offset=offset, sql=sql, adapter=self)

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
        import psycopg2.extras

        sql = self._translate_sql(sql)
        cursor = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        self._exec_with_handling(cursor, sql, params)
        row = cursor.fetchone()
        return self._decode_blobs(dict(row)) if row else None

    @staticmethod
    def _decode_blobs(row: dict) -> dict:
        """Ensure binary columns (bytea) are proper bytes, not memoryview."""
        for key, value in row.items():
            if isinstance(value, memoryview):
                row[key] = bytes(value)
        return row

    def insert(self, table: str, data: dict) -> DatabaseResult:
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) RETURNING *"
        return self.execute(sql, list(data.values()))

    def update(self, table: str, data: dict,
               filter_sql: str = "", params: list = None) -> DatabaseResult:
        set_clause = ", ".join(f"{k} = %s" for k in data.keys())
        sql = f"UPDATE {table} SET {set_clause}"
        all_params = list(data.values())

        if filter_sql:
            translated_filter = SQLTranslator.placeholder_style(filter_sql, "%s")
            sql += f" WHERE {translated_filter}"
            all_params += params or []

        return self.execute(sql, all_params)

    def delete(self, table: str,
               filter_sql: str = "", params: list = None) -> DatabaseResult:
        sql = f"DELETE FROM {table}"
        if filter_sql:
            translated_filter = SQLTranslator.placeholder_style(filter_sql, "%s")
            sql += f" WHERE {translated_filter}"
            all_params = params or []
        else:
            all_params = []
        return self.execute(sql, all_params)

    def start_transaction(self):
        # psycopg2 starts transactions automatically, but we track state
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
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename = %s",
            [name],
        )
        return row is not None

    def get_tables(self) -> list[str]:
        result = self.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename",
            limit=10000,
        )
        return [r["tablename"] for r in result.records]

    def get_columns(self, table: str) -> list[dict]:
        sql = """
            SELECT c.column_name, c.data_type, c.is_nullable, c.column_default,
                   CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END AS is_primary
            FROM information_schema.columns c
            LEFT JOIN (
                SELECT ku.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage ku
                  ON tc.constraint_name = ku.constraint_name
                WHERE tc.table_name = %s AND tc.constraint_type = 'PRIMARY KEY'
            ) pk ON c.column_name = pk.column_name
            WHERE c.table_name = %s AND c.table_schema = 'public'
            ORDER BY c.ordinal_position
        """
        result = self.fetch(sql, [table, table], limit=10000)
        return [
            {
                "name": r["column_name"],
                "type": r["data_type"],
                "nullable": r["is_nullable"] == "YES",
                "default": r["column_default"],
                "primary_key": r["is_primary"],
            }
            for r in result.records
        ]

    def get_database_type(self) -> str:
        return "postgresql"

    # -- SQL Translation -----------------------------------------------

    def _translate_sql(self, sql: str) -> str:
        """Translate portable SQL to PostgreSQL dialect.

        PostgreSQL uses %s placeholders, supports ILIKE natively,
        || for concat, RETURNING, and LIMIT/OFFSET.
        """
        sql = SQLTranslator.placeholder_style(sql, "%s")
        sql = SQLTranslator.auto_increment_syntax(sql, "postgresql")
        sql = SQLTranslator.boolean_to_int(sql)
        return sql

    def _supports_returning(self) -> bool:
        return True
