# Tina4 PostgreSQL Driver — Uses psycopg2 (optional).
"""
PostgreSQL adapter using psycopg2.

    db = Database("postgresql://user:pass@localhost:5432/mydb")
    db = Database("postgres://user:pass@localhost:5432/mydb")

Requires: pip install psycopg2-binary
"""
import re
from urllib.parse import urlparse
from tina4_python.database.database_url import url_credentials
from tina4_python.database.adapter import DatabaseAdapter, DatabaseResult, SQLTranslator


class PostgreSQLAdapter(DatabaseAdapter):
    """PostgreSQL database driver using psycopg2."""

    # PostgreSQL is the only engine wanting RETURNING on an INSERT; that plus
    # the marker is the whole of what its CRUD used to justify overriding.
    PARAM_MARKER = "%s"
    INSERT_RETURNING = " RETURNING *"

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
        """Handle a failed query: log, store, auto-rollback if implicit.

        v3.13.11 (issue #49 Gap 1): inside an explicit transaction the
        auto-rollback step defers to the user — they may be running a
        SAVEPOINT/retry pattern. The visibility half stays: the original
        cause is still logged via ``Log.error``, and an additional
        ``Log.warning`` makes the context explicit so a tail-the-log
        operator can spot the upstream cause that's about to be buried
        by a downstream ``InFailedSqlTransaction`` cascade.
        """
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
            # v3.13.11: extra in-txn marker so the original cause is
            # easy to spot above the cascade line.
            if self._in_transaction:
                Log.warning(
                    "Above failure occurred inside an explicit transaction — "
                    "auto-rollback skipped (caller owns the transaction). "
                    "Subsequent queries on this connection will cascade with "
                    "'current transaction is aborted' until rollback() is called."
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

    def _log_silent_probe_failure(self, exc: Exception, sql: str, params=None):
        """v3.13.11 (issue #49 Gap 1): log a probe-query failure as a
        warning WITHOUT touching ``last_error`` or rolling back.

        Used by the COUNT probe in :meth:`fetch` which is best-effort —
        it's allowed to fail without surfacing to the caller — but inside
        an explicit transaction the connection is now poisoned, the
        paginated query that follows will cascade, and the real cause
        used to be lost entirely. This logs it so an operator scrolling
        back through the log can spot the upstream cause.
        """
        try:
            from tina4_python.debug import Log
            preview = sql.strip().splitlines()[0][:200] if sql else "<no sql>"
            Log.warning(
                f"PostgreSQL probe query failed (original cause, before "
                f"any cascade): {exc.__class__.__name__}: {exc}",
                sql=preview,
                params=params,
            )
        except Exception:
            pass

    def _end_read_txn(self):
        """v3.13.15 (issue #51): close the implicit transaction a read
        opens, so the connection doesn't leak as ``idle in transaction``.

        psycopg2 runs with ``autocommit = False`` (the framework's safe
        default — writes must be committed explicitly). A bare ``SELECT``
        therefore opens a transaction too, and with nothing to commit it
        sits ``idle in transaction`` for the life of the connection,
        holding a pool slot and any locks it touched. Short-lived boot
        connections (the migration runner's ``MAX(batch)`` lookup) leak
        one each, eventually exhausting ``max_connections`` — at which
        point module autodiscovery fails mid-boot and every route 404s
        while ``/health-check`` still passes ("ready but broken").

        A read has nothing to persist, so a ROLLBACK is the safe close.
        Inside an explicit ``start_transaction()`` the caller owns the
        transaction, so we defer (mirrors the heal / error-path guards).
        Writes go through :meth:`execute`, which is deliberately left
        untouched — with autocommit off they must be committed explicitly,
        so auto-closing them here would silently drop data.
        """
        if self._in_transaction or self._conn is None:
            return
        try:
            self._conn.rollback()
        except Exception:
            # Never let bookkeeping mask the rows we already fetched.
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

        # Percent-DECODED: urlparse leaves userinfo escaped.

        _url_user, _url_pass = url_credentials(connection_string, username, password)
        self._conn = psycopg2.connect(
            host=parsed.hostname or "localhost",
            port=parsed.port or 5432,
            user=_url_user,
            password=_url_pass,
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

        # Capture rowcount NOW, before the lastval()/SAVEPOINT probes below run
        # their own cursor.execute() calls and overwrite cursor.rowcount. A
        # no-RETURNING INSERT was reporting affected_rows=0 because those probe
        # statements clobbered the INSERT's rowcount before it was read at the end.
        affected = cursor.rowcount if cursor.rowcount >= 0 else 0

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

        # NOTE: affected_rows was captured right after the main statement above,
        # before the lastval()/SAVEPOINT probes ran their own cursor.execute()
        # calls (which reset cursor.rowcount). Do not recompute it from
        # cursor.rowcount here or a no-RETURNING INSERT reports 0.

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
        # v3.13.12: strip trailing `;` before the framework wraps with
        # COUNT(*) and appends LIMIT/OFFSET — otherwise a user-supplied
        # `"SELECT * FROM users;"` produces invalid wrapped SQL.
        sql = self._strip_trailing_semicolons(sql)
        sql = self._translate_sql(sql)

        # v3.13.8: heal first so the COUNT probe below doesn't open on a
        # poisoned connection — the probe uses raw _safe_execute (it's
        # allowed to fail without polluting last_error) so it bypasses
        # _exec_with_handling's heal step.
        self._heal_aborted_txn()

        # A PLAIN cursor (tuples), not RealDictCursor. RealDictCursor builds a
        # RealDictRow per row (an OrderedDict subclass -- a full dict allocation
        # with per-row column-name binding) which the old code then COPIED again
        # via dict(row): two dict allocations per row. Reading tuples and building
        # each dict once from the cached column names avoids both. Measured on
        # real PostgreSQL 16.14, a 5,000-row x 6-col fetch: 14.27ms -> 6.27ms
        # (2.28x), byte-identical output incl. native types (int/bool/Decimal/None)
        # -- cursor_factory only chooses the row CONTAINER, never value coercion,
        # so psycopg2's type adaptation is unchanged.
        cursor = self._conn.cursor()

        # Count total rows (plain cursor -> read the scalar positionally, not ["cnt"])
        count_sql = f"SELECT COUNT(*) AS cnt FROM ({sql}) AS _count_subquery"
        try:
            self._safe_execute(cursor, count_sql, params)
            total = cursor.fetchone()[0]
        except Exception as e:
            total = 0
            # v3.13.11 (issue #49 Gap 1): log the probe failure as a
            # warning so the original cause appears in the log even
            # though the probe itself swallows. Without this line, a
            # failure inside an explicit transaction is invisible —
            # the cascade message from the paginated query below is
            # all the operator sees.
            self._log_silent_probe_failure(e, count_sql, params)
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
        # v3.13.12: limit <= 0 means "no pagination" (fetch_all's
        # default — give me ALL rows, not a silent first-100 slice).
        # _has_trailing_limit: only SQLite deduped before, so SQL that already
        # carried its own LIMIT became `... LIMIT 3 LIMIT %s OFFSET %s` here --
        # a syntax error MEASURED on a live PostgreSQL. It worked on sqlite and
        # crashed on the server, which is the swap ADR-0024 exists to protect.
        if limit is None or limit <= 0 or self._has_trailing_limit(sql):
            paginated_sql = sql
            paginated_params = params or []
        else:
            paginated_sql = f"{sql}\nLIMIT %s OFFSET %s"
            paginated_params = (params or []) + [limit, offset]
        self._exec_with_handling(cursor, paginated_sql, paginated_params)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        indexes = range(len(columns))
        rows = [
            self._decode_blobs({columns[i]: row[i] for i in indexes})
            for row in cursor.fetchall()
        ]

        # v3.13.15 (#51): rows are materialised above — close the implicit
        # read transaction so the connection doesn't sit idle-in-transaction.
        self._end_read_txn()

        return DatabaseResult(records=rows, count=total, limit=limit, offset=offset, sql=sql, adapter=self)

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
        import psycopg2.extras

        # v3.13.12: see fetch() — trailing semicolons break the wrappers.
        sql = self._strip_trailing_semicolons(sql)
        sql = self._translate_sql(sql)
        cursor = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        self._exec_with_handling(cursor, sql, params)
        row = cursor.fetchone()
        result = self._decode_blobs(dict(row)) if row else None
        # v3.13.15 (#51): close the implicit read transaction so the
        # connection doesn't sit 'idle in transaction' (psycopg2 autocommit
        # is off). This is the path the migration runner's MAX(batch)
        # lookup leaked through.
        self._end_read_txn()
        return result

    @staticmethod
    def _decode_blobs(row: dict) -> dict:
        """Ensure binary columns (bytea) are proper bytes, not memoryview."""
        for key, value in row.items():
            if isinstance(value, memoryview):
                row[key] = bytes(value)
        return row

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
        # v3.13.x (#48): support schema-qualified names ("schema.table") and the
        # connection search_path. to_regclass() resolves a (possibly qualified)
        # relation name to its OID using the SAME rules Postgres applies to a
        # FROM clause, returning NULL when absent. Pre-fix this hardcoded
        # schemaname='public' AND matched the whole dotted string as a flat
        # tablename, so a table in a non-public schema was invisible —
        # table_exists() always returned False, so create_table()/migrations
        # misfired and ORM introspection saw nothing.
        row = self.fetch_one("SELECT to_regclass(%s) AS oid", [name])
        return bool(row and row.get("oid") is not None)

    def get_tables(self) -> list[str]:
        # v3.13.x (#48): list tables from every user schema, not just public.
        # public tables stay bare ("users"); tables in other schemas are
        # returned schema-qualified ("gift_cards.gift_card") so the names round
        # -trip back through table_exists()/get_columns().
        result = self.fetch(
            """
            SELECT schemaname, tablename FROM pg_tables
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
            ORDER BY schemaname, tablename
            """,
            limit=10000,
        )
        return [
            r["tablename"] if r["schemaname"] == "public"
            else f"{r['schemaname']}.{r['tablename']}"
            for r in result.records
        ]

    def get_columns(self, table: str) -> list[dict]:
        # v3.13.x (#48): honour a schema-qualified name; default to public.
        schema, tbl = self._split_schema(table)
        schema = schema or "public"
        sql = """
            SELECT c.column_name, c.data_type, c.is_nullable, c.column_default,
                   CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END AS is_primary
            FROM information_schema.columns c
            LEFT JOIN (
                SELECT ku.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage ku
                  ON tc.constraint_name = ku.constraint_name
                WHERE tc.table_name = %s AND tc.table_schema = %s AND tc.constraint_type = 'PRIMARY KEY'
            ) pk ON c.column_name = pk.column_name
            WHERE c.table_name = %s AND c.table_schema = %s
            ORDER BY c.ordinal_position
        """
        result = self.fetch(sql, [tbl, schema, tbl, schema], limit=10000)
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
        # v3.13.16: do NOT run boolean_to_int on PostgreSQL — PG has a native
        # BOOLEAN type, so TRUE/FALSE are valid literals and 1/0 are NOT
        # interchangeable with them. Converting (e.g. `DEFAULT FALSE` -> `DEFAULT 0`,
        # or `WHERE active = TRUE` -> `= 1`) raises "column is of type boolean but
        # expression is of type integer" / "operator does not exist: boolean = integer".
        # boolean_to_int stays for INTEGER/BIT-backed engines (SQLite, Firebird, MSSQL).
        return sql

    def _supports_returning(self) -> bool:
        return True
