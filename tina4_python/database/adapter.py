# Tina4 Database Adapter — The contract every driver implements.
"""
All database drivers implement DatabaseAdapter. This is the only interface
the rest of the framework touches. Adding a new database = implementing this class.
"""
import contextlib
import math
import os
import re
import threading
import time
from dataclasses import dataclass, field


# ── Bounded connect ───────────────────────────────────────────────────────
# A connect that can block forever hangs the application with no log, no error
# and no signal to say what happened — the process just sits there at 0% CPU.
# Every adapter whose connect talks to a peer therefore hands the driver a
# connect timeout. Same variable, same unit and same default in all four
# frameworks.
CONNECT_TIMEOUT_VARIABLE = "TINA4_DATABASE_CONNECT_TIMEOUT"

# 10 seconds: long enough for a cold container, a TLS handshake and a slow
# intercontinental link, short enough that a black-holed host surfaces as an
# error on the first request instead of a hung worker.
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0


class DatabaseConnectTimeout(TimeoutError):
    """A database connect exceeded TINA4_DATABASE_CONNECT_TIMEOUT.

    A subclass of the builtin TimeoutError, so ``except TimeoutError`` in
    application code catches it without importing anything from Tina4.
    """


def resolve_connect_timeout() -> float | None:
    """Seconds a database connect may block. ``None`` means unbounded.

    Read from TINA4_DATABASE_CONNECT_TIMEOUT. A value <= 0 DISABLES the bound
    and restores the old wait-forever behaviour — the deliberate escape hatch
    for a link where a slow connect is normal and a hang is preferable to a
    failed request. A value that is not a number at all is a typo, not a
    choice, so it warns and uses the default rather than silently waiting
    forever on what the operator believed was a bound.
    """
    raw = os.environ.get(CONNECT_TIMEOUT_VARIABLE, "").strip()
    if not raw:
        return DEFAULT_CONNECT_TIMEOUT_SECONDS
    try:
        seconds = float(raw)
    except ValueError:
        from tina4_python.debug import Log
        Log.warning(
            f"{CONNECT_TIMEOUT_VARIABLE}={raw!r} is not a number of seconds — "
            f"bounding database connects at the {DEFAULT_CONNECT_TIMEOUT_SECONDS:g}s default instead"
        )
        return DEFAULT_CONNECT_TIMEOUT_SECONDS
    if seconds <= 0:
        return None
    return seconds


def driver_connect_timeout_seconds(seconds: float | None) -> int | None:
    """A driver's own connect-timeout option, in whole seconds, STRICTLY longer
    than the bound it protects.

    Every driver option here (libpq ``connect_timeout``, mysql-connector
    ``connection_timeout``, pymssql ``login_timeout``, pyodbc ``timeout``) is
    whole seconds, so the bound has to become an integer — and which integer
    decides whether the driver's deadline lands after ours or on top of it.
    ``ceil`` put it on top: for a whole-second bound ``ceil(N) == N``, and the
    shipped default of 10 is whole. ``floor(s) + 1`` is strictly greater for
    every input, fractional or whole, which is what leaves the driver's own
    timer the room to fire first — the thing this wrapper is built on. The
    cost is at most one extra second, on a path that has already failed.
    """
    return None if seconds is None else max(1, math.floor(seconds) + 1)


def bound_was_reached(elapsed_monotonic: float, elapsed_realtime: float,
                      seconds: float | None) -> bool:
    """Did a connect that failed take at least the configured bound?

    Two readings, because the framework and the driver do not share a clock.
    :func:`connect_deadline` times on ``time.monotonic()``; libpq times its own
    ``connect_timeout`` on ``gettimeofday()``. NTP moves the wall clock and
    never touches the monotonic one, so a forward step or slew can make the
    driver abort before a monotonic reading has reached the bound.

    Taking the LARGER of the two readings covers both directions: the realtime
    reading catches a forward jump, and keeping the monotonic reading means a
    BACKWARD jump cannot hide a timeout that really did happen.

    Pure, so the decision is testable without faking a clock.
    """
    if seconds is None:
        return False
    return max(elapsed_monotonic, elapsed_realtime) >= seconds


@contextlib.contextmanager
def connect_deadline(host, port):
    """Bound a driver connect, and name the bound when it expires.

    Yields the timeout in seconds (``None`` when unbounded, in which case the
    caller passes the driver no timeout option at all and the old behaviour is
    restored exactly). Any connect failure that took at least that long is
    re-raised as :class:`DatabaseConnectTimeout` naming the host, the port, the
    elapsed seconds and the variable that tunes it — the four things needed to
    tell "the bound fired" apart from "the database rejected me", which a bare
    driver timeout message does not.

    A failure that arrives FASTER than the bound is a real error (a refused
    connection, bad credentials, an unknown database) and is re-raised
    untouched.

    WHY THIS IS A WRAPPER AND NOT A COMPETING TIMER
    ----------------------------------------------
    The driver's own timer is MEANT to win the race. This is not a second
    countdown fighting the driver's — it is an exception translator, so when
    libpq or mysql-connector aborts at its own deadline we catch that failure
    and restate it in the framework's words, keeping the driver's error as
    ``__cause__``. The driver still gets to abort cleanly (no abandoned thread,
    no orphaned socket) AND the operator still gets a message naming the
    variable to tune.

    The alternative — giving the driver a GRACE so an outer timer expires first
    — was rejected: it inflates the operator's configured N into N+grace, it
    throws away the driver's own diagnosis, and for the watchdog adapters it
    would abandon a thread the driver could have unwound itself.

    THE INVARIANT, AND WHY IT TAKES TWO CLOCKS
    ------------------------------------------
    What decides the race is not the driver's OPTION against our bound — it
    is the driver's ABORT INSTANT against our reading of a clock. Two things
    have to hold, and each of them was broken:

    * The driver's option must be STRICTLY greater than our bound, so its
      deadline lands after ours instead of on top of it.
      :func:`driver_connect_timeout_seconds` returns ``floor(s) + 1`` for that
      reason; ``ceil`` left a whole-second bound with no separation at all, and
      the default bound is a whole number.

    * The comparison has to be made on the clock the DRIVER used. libpq times
      ``connect_timeout`` with ``gettimeofday()`` — CLOCK_REALTIME — while a
      duration in Python belongs on ``time.monotonic()``. NTP slews and steps
      realtime and never touches monotonic, so a monotonic reading can still
      sit below the bound at the instant the driver has already given up, and
      then the driver's own message — which names no tunable — reaches
      the caller. :func:`bound_was_reached` compares both readings.

    Break either half and a bare driver message reaches the caller instead of
    ours.
    """
    seconds = resolve_connect_timeout()
    started = time.monotonic()
    started_realtime = time.time()
    try:
        yield seconds
    except Exception as failure:
        elapsed_monotonic = time.monotonic() - started
        elapsed_realtime = time.time() - started_realtime
        elapsed = max(elapsed_monotonic, elapsed_realtime)
        if bound_was_reached(elapsed_monotonic, elapsed_realtime, seconds):
            raise DatabaseConnectTimeout(
                f"Database connect to {host}:{port} timed out after {elapsed:.1f}s "
                f"({CONNECT_TIMEOUT_VARIABLE}={seconds:g} seconds). "
                f"Raise {CONNECT_TIMEOUT_VARIABLE} if the server is simply slow, "
                f"or set it to 0 to wait indefinitely."
            ) from failure
        raise


def call_with_deadline(operation, seconds: float | None):
    """Run a blocking connect on a worker thread and give up after `seconds`.

    The fallback for a driver whose own option cannot be trusted to bound a peer
    that accepts the connection and then goes silent. Used by Firebird (no
    connect-timeout parameter exists at all — the work is inside fbclient, a
    ctypes call into C that no Python socket timeout can reach), by MSSQL
    (pymssql's login_timeout was MEASURED not to cover this case) and by ODBC
    (the guarantee would otherwise depend on which ODBC driver is loaded).

    tina4: on expiry the worker is abandoned, still blocked inside the driver.
    It is a daemon thread, so it cannot hold the process open, and it ends the
    moment the peer replies or drops the socket. One leaked thread per timed-out
    connect is the price of not hanging the entire application forever; remove
    this the day every driver grows a real connect timeout.
    """
    if seconds is None:
        return operation()

    outcome = {}
    handover_lock = threading.Lock()
    abandoned = False

    def run_operation():
        try:
            value = operation()
        except BaseException as failure:  # carried across to the caller's thread
            with handover_lock:
                outcome["failure"] = failure
            return
        with handover_lock:
            if not abandoned:
                outcome["value"] = value
                return
        # The caller gave up and already raised. A connection nobody holds is a
        # live server-side session that would never be closed, so close it here
        # rather than leak it — the thread leak is bounded, a session leak is not.
        with contextlib.suppress(Exception):
            value.close()

    worker = threading.Thread(target=run_operation, name="tina4-db-connect", daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        with handover_lock:
            abandoned = True
        raise TimeoutError(f"driver connect did not return within {seconds:g}s")
    if "failure" in outcome:
        raise outcome["failure"]
    return outcome["value"]


@dataclass
class DatabaseResult:
    """Standard result from any database operation."""
    records: list = field(default_factory=list)
    count: int = 0
    limit: int = 0
    offset: int = 0
    affected_rows: int = 0
    last_id: int | str | None = None
    error: str | None = None
    sql: str | None = None
    adapter: object | None = field(default=None, repr=False)
    _column_info: list | None = field(default=None, init=False, repr=False)

    def __iter__(self):
        return iter(self.records)

    def __len__(self):
        return self.count

    def __getitem__(self, index):
        """Index / slice access into the result rows.

        v3.13.16: ``result[0]`` (and slicing) are documented (book ch5 §4
        "Index Access") but used to raise ``TypeError: 'DatabaseResult'
        object is not subscriptable``. Delegate to the materialised rows so
        index and slice access behave like a list.
        """
        return self.records[index]

    def __bool__(self):
        return self.error is None

    def size(self) -> int:
        """Return the total count of records."""
        return self.count

    @property
    def columns(self) -> list[str]:
        """Return the column names of the result set.

        Cheap property — derived from the first row's keys. For richer
        metadata (type, nullable, primary key), call ``column_info()``.

            >>> result = db.fetch("SELECT id, name FROM users LIMIT 1")
            >>> result.columns
            ['id', 'name']

        Returns ``[]`` when no rows.
        """
        if not self.records:
            return []
        return list(self.records[0].keys())

    def to_list(self) -> list:
        return self.records

    def to_array(self) -> list:
        """Return list of row dicts (alias for records)."""
        return self.records

    def to_json(self) -> str:
        """Return JSON string of records."""
        import json
        return json.dumps(self.records)

    def to_csv(self) -> str:
        """Return CSV string with header row."""
        if not self.records:
            return ""
        columns = list(self.records[0].keys())

        def escape(val) -> str:
            if val is None:
                return ""
            s = str(val)
            if "," in s or '"' in s or "\n" in s:
                return f'"{s.replace(chr(34), chr(34)+chr(34))}"'
            return s

        header = ",".join(escape(c) for c in columns)
        rows = [",".join(escape(row.get(c)) for c in columns) for row in self.records]
        return "\n".join([header] + rows)

    def to_paginate(self, *args, **kwargs) -> dict:
        """Describe the page this result already IS, as the canonical envelope.

        Takes NO arguments. Every field is derived from the query that
        produced this result (ADR-0043):

            per_page    = the query's limit
            page        = floor(offset / limit) + 1
            total       = the true total for the filter, the COUNT probe that
                          populates .count, NEVER the number of rows returned
            total_pages = ceil(total / per_page)
            records     = the rows the query returned, VERBATIM, never re-sliced
            limit       = the SQL limit actually applied
            offset      = the SQL offset actually applied

        The envelope is EXACTLY seven snake_case keys (records, total, page,
        per_page, total_pages, limit, offset), identical in all four Tina4
        frameworks. A JSON key is data and does not change spelling by host
        language, so there is no camelCase and no duplicate spelling: the old
        ``data``, ``count`` and ``totalPages`` aliases are gone.

        Passing ANY argument RAISES. The method used to accept (page, per_page)
        and slice the rows in memory (GitHub issue #106), but a DatabaseResult
        holds no connection, so an argument can only re-slice the rows already
        in memory and then report total_pages for pages it can never reach --
        the measured Ruby defect where slicing offset 40 into a 20-row page
        returned NOTHING while still naming a page and a total. To read a
        different page, FETCH that page (limit + offset) and call this with no
        arguments.

        MEASURED 2026-08-05 on a real 250-row table read with limit=20
        offset=40 (page 3 of 13): the envelope shipped the same integer twice
        under two spellings (totalPages and total_pages, count and total, data
        and records) in every API response, so every consumer had to guess
        which spelling was canonical. That, and the silent in-memory slice, are
        what this fixes.
        """
        if args or kwargs:
            raise TypeError(
                "to_paginate() takes no arguments -- it describes the page the "
                "query already returned, derived from the limit and offset that "
                "ran. It used to accept (page, per_page) and slice in memory, but "
                "a DatabaseResult holds no connection, so an argument can only "
                "re-slice the rows already in memory and then report total_pages "
                "for pages it can never reach. To read a different page, FETCH it: "
                "fetch(sql, params, limit=per_page, offset=(page - 1) * per_page), "
                "then call to_paginate() with no arguments. (ADR-0043)"
            )

        per_page = self.limit if self.limit and self.limit > 0 else len(self.records)
        page = (self.offset // per_page) + 1 if per_page > 0 else 1
        total_pages = max(1, -(-self.count // per_page)) if per_page > 0 else 1
        return {
            "records": self.records,     # the rows returned, verbatim (never re-sliced)
            "total": self.count,         # the true COUNT for the filter, not rows returned
            "page": page,                # floor(offset / limit) + 1
            "per_page": per_page,        # the query's limit
            "total_pages": total_pages,  # ceil(total / per_page)
            "limit": per_page,           # the SQL limit actually applied
            "offset": self.offset,       # the SQL offset actually applied
        }

    def column_info(self) -> list[dict]:
        """Return column metadata for the query's table.

        Lazy — only queries the database when explicitly called. Caches the
        result so subsequent calls return immediately without re-querying.

        Returns a list of dicts with keys:
            name, type, size, decimals, nullable, primary_key
        """
        if self._column_info is not None:
            return self._column_info

        # Try to extract table name from the SQL query
        table = self._extract_table_from_sql()

        # If we have an adapter and a table name, query the database for metadata
        if self.adapter is not None and table:
            try:
                self._column_info = self._query_column_metadata(table)
                return self._column_info
            except Exception:
                pass

        # Fallback: derive basic info from record keys
        self._column_info = self._fallback_column_info()
        return self._column_info

    def _extract_table_from_sql(self) -> str | None:
        """Extract table name from a SQL query using simple regex."""
        if not self.sql:
            return None
        # Match FROM tablename (with optional schema prefix)
        m = re.search(r'\bFROM\s+["\']?(\w+)["\']?', self.sql, re.IGNORECASE)
        if m:
            return m.group(1)
        # Match INSERT INTO tablename
        m = re.search(r'\bINSERT\s+INTO\s+["\']?(\w+)["\']?', self.sql, re.IGNORECASE)
        if m:
            return m.group(1)
        # Match UPDATE tablename
        m = re.search(r'\bUPDATE\s+["\']?(\w+)["\']?', self.sql, re.IGNORECASE)
        if m:
            return m.group(1)
        return None

    def _query_column_metadata(self, table: str) -> list[dict]:
        """Query the database adapter for column metadata."""
        adapter = self.adapter
        db_type = ""
        try:
            db_type = adapter.get_database_type().lower()
        except (AttributeError, NotImplementedError):
            pass

        if db_type == "sqlite":
            return self._query_sqlite_columns(table)
        elif db_type in ("postgresql", "postgres"):
            return self._query_pg_columns(table)
        elif db_type == "mysql":
            return self._query_mysql_columns(table)
        else:
            # Try get_columns if the adapter supports it
            try:
                raw_cols = adapter.get_columns(table)
                return self._normalize_adapter_columns(raw_cols)
            except (AttributeError, NotImplementedError):
                pass
            return self._fallback_column_info()

    def _query_sqlite_columns(self, table: str) -> list[dict]:
        """Get column metadata from SQLite PRAGMA."""
        result = self.adapter.fetch(f"PRAGMA table_info({table})")
        columns = []
        for row in result.records:
            col_type = (row.get("type") or "TEXT").upper()
            size, decimals = self._parse_type_size(col_type)
            columns.append({
                "name": row.get("name"),
                "type": col_type.split("(")[0],
                "size": size,
                "decimals": decimals,
                "nullable": not bool(row.get("notnull", 0)),
                "primary_key": bool(row.get("pk", 0)),
            })
        return columns

    def _query_pg_columns(self, table: str) -> list[dict]:
        """Get column metadata from PostgreSQL information_schema."""
        sql = (
            "SELECT column_name, data_type, character_maximum_length, "
            "numeric_precision, numeric_scale, is_nullable "
            "FROM information_schema.columns WHERE table_name = ?"
        )
        result = self.adapter.fetch(sql, [table])
        # Determine primary keys
        pk_sql = (
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = ?::regclass AND i.indisprimary"
        )
        pk_names = set()
        try:
            pk_result = self.adapter.fetch(pk_sql, [table])
            pk_names = {r.get("attname") for r in pk_result.records}
        except Exception:
            pass

        columns = []
        for row in result.records:
            columns.append({
                "name": row.get("column_name"),
                "type": (row.get("data_type") or "UNKNOWN").upper(),
                "size": row.get("character_maximum_length") or row.get("numeric_precision"),
                "decimals": row.get("numeric_scale"),
                "nullable": (row.get("is_nullable") or "YES").upper() == "YES",
                "primary_key": row.get("column_name") in pk_names,
            })
        return columns

    def _query_mysql_columns(self, table: str) -> list[dict]:
        """Get column metadata from MySQL information_schema."""
        sql = (
            "SELECT column_name, data_type, character_maximum_length, "
            "numeric_precision, numeric_scale, is_nullable, column_key "
            "FROM information_schema.columns WHERE table_name = ?"
        )
        result = self.adapter.fetch(sql, [table])
        columns = []
        for row in result.records:
            columns.append({
                "name": row.get("column_name") or row.get("COLUMN_NAME"),
                "type": (row.get("data_type") or row.get("DATA_TYPE") or "UNKNOWN").upper(),
                "size": row.get("character_maximum_length") or row.get("CHARACTER_MAXIMUM_LENGTH") or row.get("numeric_precision") or row.get("NUMERIC_PRECISION"),
                "decimals": row.get("numeric_scale") or row.get("NUMERIC_SCALE"),
                "nullable": (row.get("is_nullable") or row.get("IS_NULLABLE") or "YES").upper() == "YES",
                "primary_key": (row.get("column_key") or row.get("COLUMN_KEY") or "") == "PRI",
            })
        return columns

    @staticmethod
    def _parse_type_size(type_str: str) -> tuple:
        """Parse size and decimals from a type string like VARCHAR(255) or NUMERIC(10,2)."""
        m = re.search(r'\((\d+)(?:\s*,\s*(\d+))?\)', type_str)
        if m:
            size = int(m.group(1))
            decimals = int(m.group(2)) if m.group(2) else None
            return size, decimals
        return None, None

    @staticmethod
    def _normalize_adapter_columns(raw_cols: list[dict]) -> list[dict]:
        """Normalize output from adapter.get_columns() to standard format."""
        columns = []
        for col in raw_cols:
            col_type = (col.get("type") or "UNKNOWN").upper()
            size, decimals = DatabaseResult._parse_type_size(col_type)
            columns.append({
                "name": col.get("name"),
                "type": col_type.split("(")[0],
                "size": size,
                "decimals": decimals,
                "nullable": col.get("nullable", True),
                "primary_key": col.get("primary_key", False),
            })
        return columns

    def _fallback_column_info(self) -> list[dict]:
        """Derive basic column info from record keys and values when no adapter is available."""
        if not self.records:
            return []
        row = self.records[0] if isinstance(self.records[0], dict) else {}
        result = []
        for k, v in row.items():
            if isinstance(v, int):
                col_type = "INTEGER"
            elif isinstance(v, float):
                col_type = "REAL"
            elif isinstance(v, bool):
                col_type = "BOOLEAN"
            elif v is None:
                col_type = "TEXT"
            else:
                col_type = "TEXT"
            result.append({
                "name": k,
                "type": col_type,
                "size": None,
                "decimals": None,
                "nullable": True,
                "primary_key": k.lower() == "id",
            })
        return result


#: ADR-0044 (feature 3, adapter_contract.json): the exact fourteen adapter
#: capabilities. None is optional; a registered adapter missing one of these
#: fails loud at registration (see validate_adapter below), never at the first
#: unlucky call. Kept as data so the shared conformance fixture can check the
#: DECLARED interface against this list instead of re-deriving it.
REQUIRED_CAPABILITIES = (
    "connect", "close", "get_database_type",
    "execute", "execute_many", "fetch", "fetch_one",
    "start_transaction", "commit", "rollback", "autocommit",
    "get_tables", "get_columns", "table_exists",
)

#: ADR-0044: engine-neutral composition that must NOT be part of the adapter
#: boundary — it belongs on the public Database facade (CRUD SQL building) or
#: is not a required capability at all (diagnostics that duplicate an existing
#: channel). See SqlCrudMixin below for where insert/update/delete now live.
NOT_REQUIRED_ON_ADAPTER = (
    "query", "insert", "update", "delete", "truncate", "fetch_all",
    "create_table", "add_column", "last_insert_id", "error", "sql_translation",
)


class AdapterContractError(TypeError):
    """A registered adapter does not satisfy the Tina4 database adapter contract.

    Raised at registration time (DatabaseAdapter.validate / Database._create_adapter),
    naming the adapter and the missing capability, instead of failing later with a
    bare AttributeError on whichever call path happens to touch the gap first
    (DBA-S02: "incomplete adapter registration fails loud").
    """


class UnsupportedAtomicBatchError(RuntimeError):
    """A provider/deployment cannot guarantee an atomic multi-row batch.

    ADR-0044 / DBA-P02: a provider unable to guarantee atomic batch writes must
    reject the operation before the first write rather than silently degrading to
    partial durability (the standalone-MongoDB-without-a-replica-set case). Raised
    by DatabaseAdapter.execute_many before any row is written when the adapter's
    own `supports_atomic_batch` is False and the batch has more than one row.
    """


#: The subset of REQUIRED_CAPABILITIES whose DatabaseAdapter body is PURELY
#: `raise NotImplementedError` — no usable behaviour at all. `execute_many` is
#: deliberately excluded: its base body is a complete, working generic
#: implementation (row-at-a-time inside one owned transaction) that every
#: built-in adapter is free to inherit as-is or override for native batching,
#: so merely existing (inherited or not) is sufficient. `autocommit` is
#: handled separately below (it is a property, not a plain method).
_PURELY_ABSTRACT_CAPABILITIES = frozenset(REQUIRED_CAPABILITIES) - {"execute_many", "autocommit"}


def validate_adapter(adapter_class: type, name: str = "") -> None:
    """Fail loud when a class does not declare every required capability.

    Reflects the CLASS (so a driver author sees the gap before anyone connects).
    For the purely-abstract capabilities this checks the member was actually
    OVERRIDDEN (not left as the raising NotImplementedError stub inherited from
    DatabaseAdapter) — mirrors Ruby's DatabaseAdapter.implemented_by?. For
    `execute_many` (which has a real, usable generic default) and `autocommit`
    (a property), simple presence is sufficient.
    """
    label = name or getattr(adapter_class, "__name__", str(adapter_class))
    missing = []
    for capability in REQUIRED_CAPABILITIES:
        member = getattr(adapter_class, capability, None)
        if member is None or not (callable(member) or isinstance(member, property)):
            missing.append(capability)
            continue
        if capability == "autocommit":
            # A native boolean property, readable AND writable.
            if not isinstance(member, property) or member.fset is None:
                missing.append(capability)
            continue
        if capability in _PURELY_ABSTRACT_CAPABILITIES:
            owner = getattr(member, "__qualname__", "")
            if owner.startswith("DatabaseAdapter.") and not owner.startswith(f"{label}."):
                # Still the raising base-class stub — never overridden.
                missing.append(capability)
    if missing:
        raise AdapterContractError(
            f"adapter '{label}' does not implement the required Tina4 database "
            f"adapter contract capabilities: {', '.join(missing)} "
            f"(ADR-0044 / plan/v3/fixtures/adapter_contract.json)"
        )


class DatabaseAdapter:
    """Base class for all database drivers.

    Every method raises NotImplementedError — drivers must implement all of them.
    The interface is deliberately minimal: fourteen methods cover everything
    (REQUIRED_CAPABILITIES above; ADR-0044). Engine-neutral CRUD composition
    (insert/update/delete) is NOT here — see SqlCrudMixin, which every built-in
    SQL adapter mixes in separately so the DECLARED adapter interface stays exactly
    the fourteen capabilities while every adapter still works identically.

    Autocommit is ON by default: a standalone write (execute/insert/update/delete
    made outside an explicit transaction) commits on its own connection before
    returning. Inside start_transaction()/commit()/rollback() the commit is
    deferred — the per-statement commit branches are gated on `not self._in_transaction`
    so explicit transactions stay atomic. Set TINA4_AUTOCOMMIT=false in .env for
    strict manual mode (every write needs an explicit commit()).
    """

    def __init__(self):
        import os
        self._autocommit = os.environ.get(
            "TINA4_AUTOCOMMIT", "true"
        ).lower() in ("true", "1", "yes")
        # ADR-0044 / DBA-P02: every built-in adapter can guarantee an atomic
        # multi-row batch. A deployment that genuinely cannot (a standalone
        # MongoDB without a replica set is the motivating real case) sets this
        # False so execute_many rejects BEFORE the first write instead of
        # silently providing partial durability.
        self._supports_atomic_batch = True

    @property
    def autocommit(self) -> bool:
        return self._autocommit

    @autocommit.setter
    def autocommit(self, value: bool):
        self._autocommit = value

    @property
    def supports_atomic_batch(self) -> bool:
        return self._supports_atomic_batch

    @supports_atomic_batch.setter
    def supports_atomic_batch(self, value: bool):
        self._supports_atomic_batch = value

    def connect(self, connection_string: str, username: str = "", password: str = "", **kwargs):
        """Establish connection to the database."""
        raise NotImplementedError

    def close(self):
        """Close the database connection."""
        raise NotImplementedError

    def execute(self, sql: str, params: list = None) -> DatabaseResult:
        """Execute a write query (INSERT, UPDATE, DELETE, DDL)."""
        raise NotImplementedError

    def execute_many(self, sql: str, params_list: list[list] = None) -> DatabaseResult:
        """Execute a single SQL statement with multiple parameter sets.

        Like batch insert/update — runs the same SQL for each set of params.

            db.execute_many("INSERT INTO users (name) VALUES (?)", [
                ["Alice"], ["Bob"], ["Eve"]
            ])
        """
        rows = params_list or []
        if not rows:
            return DatabaseResult(affected_rows=0)
        if not self._supports_atomic_batch and len(rows) > 1:
            raise UnsupportedAtomicBatchError(
                f"provider {self.get_database_type()!r} cannot guarantee an atomic "
                f"batch write on this deployment (required deployment capability: "
                f"a transaction-capable configuration) — rejected before the first "
                f"write rather than risking partial durability"
            )
        # Run the whole batch in ONE transaction on ONE connection so it is
        # atomic AND affected_rows/last_id are reliable. In autocommit mode each
        # standalone execute() commits on its own (possibly different, pooled)
        # connection, which scattered the per-row rowcount / last_insert_id and
        # made the aggregate non-deterministic. When already inside an explicit
        # transaction we just join it (never nest).
        owns_txn = self._autocommit and not getattr(self, "_in_transaction", False)
        if owns_txn:
            self.start_transaction()
        total_affected = 0
        last_id = None
        # ONE round-trip per CHUNK instead of one per ROW. Looping execute()
        # here pays a full network round-trip for every row: 500 rows took
        # 9848ms on PostgreSQL against 15.8ms as a single multi-row VALUES
        # (625x), MySQL 216x, MSSQL 121x. build_batch_inserts returns an empty
        # list for anything it cannot collapse safely - RETURNING, upserts,
        # non-INSERT statements, ragged rows, Firebird - and then this falls
        # back to the row-at-a-time loop below, unchanged.
        batched = SQLTranslator.build_batch_inserts(sql, rows, self.get_database_type())
        try:
            if batched:
                for chunk_sql, chunk_params in batched:
                    result = self.execute(chunk_sql, chunk_params)
                    # The collapse must be invisible: affected_rows is the total
                    # ROW count, never the number of statements run.
                    total_affected += result.affected_rows
                    # last_id stays the LAST inserted row's id. MySQL reports the
                    # FIRST id of a multi-row INSERT; its ADAPTER normalises that
                    # at write time (the only place that knows both the first id
                    # and the row count), so get_last_id() and this result always
                    # agree. Normalising here instead would double-apply.
                    if result.last_id is not None:
                        last_id = result.last_id
            else:
                for params in rows:
                    result = self.execute(sql, params)
                    total_affected += result.affected_rows
                    if result.last_id is not None:
                        last_id = result.last_id
            if owns_txn:
                self.commit()
        except Exception:
            if owns_txn:
                self.rollback()
            raise
        return DatabaseResult(
            affected_rows=total_affected,
            last_id=last_id,
        )

    @staticmethod
    def _strip_trailing_semicolons(sql: str) -> str:
        """v3.13.12: normalize user-supplied SQL by stripping trailing
        semicolons and whitespace.

        ``fetch()`` and ``fetch_one()`` wrap the user's SQL — fetch()
        builds a ``SELECT COUNT(*) FROM ({sql}) AS _count_subquery``
        for the pagination probe and appends ``LIMIT/OFFSET`` to the
        real query. A trailing ``;`` in the user's SQL breaks both:

            user input:  "SELECT * FROM users;"
            wrapped:     "SELECT COUNT(*) FROM (SELECT * FROM users;) ..."   ← syntax error
            paginated:   "SELECT * FROM users; LIMIT 100 OFFSET 0"           ← invalid

        Stripping trailing semicolons before any wrapping is the
        single-line defence. Internal semicolons (between meaningful
        SQL statements) are left alone — the driver will reject those
        if multi-statement isn't supported on the engine.
        """
        if not sql:
            return sql
        stripped = sql.rstrip()
        while stripped.endswith(";"):
            stripped = stripped[:-1].rstrip()
        return stripped

    @staticmethod
    def _scrub_sql_text(sql: str) -> str:
        """Blank out string literals, quoted identifiers and comments so a
        keyword search sees only real SQL.

        Blanks are spaces of the SAME LENGTH (newlines preserved), so offsets
        and line structure still line up with the original.

        MEASURED 2026-08-01 on a real 150-row SQLite table with the 100-row cap
        in force. The old test was ``"LIMIT" in sql.upper().split("--")[0]``,
        and each of these returned ALL 150 ROWS instead of 100:

            SELECT * FROM t WHERE label != 'LIMIT' ORDER BY id     literal
            SELECT * FROM t ORDER BY id -- LIMIT 5                 line comment
            SELECT id, label AS rate_limit FROM t                  identifier

        A silently uncapped read of a whole table is the production incident the
        cap exists to prevent, and an ordinary column name was enough to cause it.
        """
        if not sql:
            return sql

        out = []
        i = 0
        n = len(sql)
        while i < n:
            ch = sql[i]
            nxt = sql[i + 1] if i + 1 < n else ""

            if ch in ("'", '"'):
                quote = ch
                out.append(" ")
                i += 1
                while i < n:
                    if sql[i] == quote:
                        if i + 1 < n and sql[i + 1] == quote:
                            out.append("  ")
                            i += 2
                            continue
                        out.append(" ")
                        i += 1
                        break
                    out.append("\n" if sql[i] == "\n" else " ")
                    i += 1
                continue

            if ch == "-" and nxt == "-":
                while i < n and sql[i] != "\n":
                    out.append(" ")
                    i += 1
                continue

            if ch == "/" and nxt == "*":
                out.append("  ")
                i += 2
                while i < n and not (sql[i] == "*" and i + 1 < n and sql[i + 1] == "/"):
                    out.append("\n" if sql[i] == "\n" else " ")
                    i += 1
                if i < n:
                    out.append("  ")
                    i += 2
                continue

            out.append(ch)
            i += 1

        return "".join(out)

    @staticmethod
    def _has_trailing_limit(sql: str) -> bool:
        """True when the statement ENDS with its own LIMIT clause.

        Anchored to the END on purpose: a bare "contains LIMIT" test also matches
        a LIMIT inside a subquery, where the OUTER statement still needs its cap.
        This is tina4-php's ``SqlNormalizerTrait::hasTrailingLimit`` regex, ported
        verbatim so all four frameworks answer identically. It accepts a numeric
        value, ``?``/``$1``/``:name`` placeholders, MySQL's ``LIMIT a, b``, and a
        trailing OFFSET.

        Literals and comments are scrubbed before matching (see _scrub_sql_text).
        """
        val = r"(?:\d+|\?|\$\d+|:\w+|%s)"
        pattern = (
            r"\bLIMIT\s+" + val + r"(?:\s*,\s*" + val + r")?"
            r"(?:\s+OFFSET\s+" + val + r")?\s*;?\s*$"
        )
        return bool(re.search(pattern, DatabaseAdapter._scrub_sql_text(sql or ""), re.IGNORECASE))

    @staticmethod
    def _strip_trailing_order_by(sql: str) -> str:
        """Strip a trailing top-level ``ORDER BY`` so the SQL can be safely
        wrapped in ``SELECT COUNT(*) FROM (<sql>)`` for the row-count probe.

        SQL Server rejects an ``ORDER BY`` inside a derived-table subquery
        unless it carries ``TOP``/``OFFSET``/``FETCH`` (error 20018), which
        silently zeroed the MSSQL count probe for any query ending in
        ``ORDER BY`` (issue #262 -- the bug existed in this master adapter too,
        not only the mirrors). ``ORDER BY`` does not affect ``COUNT(*)``, so
        dropping it for the probe ONLY is safe; the paginated query keeps its
        ``ORDER BY`` for ``OFFSET/FETCH``. An ``ORDER BY`` nested in a subquery,
        or one already legalised by a following ``OFFSET``/``FETCH``/``FOR``, is
        left intact. Parity with PHP ``SqlNormalizerTrait::stripTrailingOrderBy``.
        """
        if not sql or not re.search(r"\bORDER\s+BY\b", sql, re.IGNORECASE):
            return sql
        last_top_level = -1
        for match in re.finditer(r"\bORDER\s+BY\b", sql, re.IGNORECASE):
            pos = match.start()
            before = sql[:pos]
            balanced_before = before.count("(") == before.count(")")
            depth = 0
            balanced_after = True
            for ch in sql[pos:]:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth < 0:
                        balanced_after = False
                        break
            if balanced_before and balanced_after:
                last_top_level = pos
        if last_top_level == -1:
            return sql
        tail = sql[last_top_level:]
        if re.search(r"\b(?:OFFSET|FETCH|FOR)\b", tail, re.IGNORECASE):
            return sql
        return sql[:last_top_level].rstrip()

    @staticmethod
    def _split_schema(name: str) -> tuple[str | None, str]:
        """Split a possibly-qualified table name into (schema, table).

        v3.13.14 (#48): a model whose ``table_name`` is qualified —
        PostgreSQL ``gift_cards.gift_card``, MSSQL ``dbo.widget``,
        MySQL ``otherdb.table``, SQLite ``attached.table`` — lives in
        that schema/catalog, not the default. Each adapter's
        ``table_exists`` / ``get_columns`` use this to query the right
        namespace instead of matching the whole dotted string as one
        flat table name. Returns ``(None, name)`` for a bare name so
        callers default to the engine's current namespace. Splits on the
        first dot; quoted identifiers with embedded dots aren't supported
        (they weren't before either). Firebird has no schemas, so its
        adapter ignores this.
        """
        if "." in name:
            schema, _, table = name.partition(".")
            return schema, table
        return None, name

    def fetch(self, sql: str, params: list = None,
              limit: int = 100, offset: int = 0) -> DatabaseResult:
        """Execute a read query and return multiple rows."""
        raise NotImplementedError

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
        """Execute a read query and return a single row or None."""
        raise NotImplementedError

    #: Identifier quoting for this dialect. ANSI double quotes work on SQLite,
    #: PostgreSQL and Firebird; MySQL and SQL Server override this.
    IDENTIFIER_QUOTE = ('"', '"')

    def quote_identifier(self, name: str) -> str:
        """Quote a table/column name so a SQL reserved word can be used.

        ``CREATE TABLE order (...)`` / ``SELECT * FROM order`` are syntax errors
        on every engine; quoting makes ``order``, ``group``, ``user`` etc. usable
        as names. Idempotent (an already-quoted name is returned unchanged) and
        dot-aware (``schema.table`` quotes each part).

        A raw expression is never quoted — ``*``, ``COUNT(*)`` and anything that
        isn't a plain identifier are passed through untouched, so existing
        hand-written SQL keeps working.
        """
        if not name:
            return name
        open_q, close_q = self.IDENTIFIER_QUOTE
        name = name.strip()
        if name.startswith(open_q) and name.endswith(close_q):
            return name
        if "." in name:
            return ".".join(self.quote_identifier(p) for p in name.split("."))
        # Only quote a plain identifier — leave expressions/wildcards alone.
        if not name.replace("_", "").replace("$", "").isalnum():
            return name
        return f"{open_q}{name.replace(close_q, close_q * 2)}{close_q}"

    #: The engine's parameter marker. Overridden to ``"%s"`` by PostgreSQL,
    #: MySQL and MSSQL; everything else uses the default.
    PARAM_MARKER = "?"

    #: Appended to a single-row INSERT. Only PostgreSQL wants ``RETURNING *``;
    #: it is the one genuinely engine-specific part of building an INSERT.
    INSERT_RETURNING = ""

    def _marked_filter(self, filter_sql: str) -> str:
        """Rewrite a caller's ``?`` placeholders into this engine's marker.

        A caller writes ``"id = ?"`` regardless of engine - that is the
        documented cross-framework filter form. Engines whose marker IS ``?``
        need no rewrite, and running the translator over them anyway would be
        work that can only introduce bugs.
        """
        if self.PARAM_MARKER == "?":
            return filter_sql
        return SQLTranslator.placeholder_style(filter_sql, self.PARAM_MARKER)

    def start_transaction(self):
        """Begin a transaction."""
        raise NotImplementedError

    def commit(self):
        """Commit the current transaction."""
        raise NotImplementedError

    def rollback(self):
        """Roll back the current transaction."""
        raise NotImplementedError

    def table_exists(self, name: str) -> bool:
        """Check if a table exists."""
        raise NotImplementedError

    def get_tables(self) -> list[str]:
        """List all table names in the database."""
        raise NotImplementedError

    def get_columns(self, table: str) -> list[dict]:
        """Get column definitions for a table.

        Returns list of dicts with keys: name, type, nullable, default, primary_key
        """
        raise NotImplementedError

    def get_database_type(self) -> str:
        """Return the driver name (e.g., 'sqlite', 'postgresql')."""
        raise NotImplementedError

    # ── SQL Translation Layer ──────────────────────────────────────
    # Translates portable SQL into engine-specific syntax so users
    # can write one SQL dialect and run on any supported engine.

    def _translate_sql(self, sql: str) -> str:
        """Translate portable SQL to engine-specific syntax.

        Base implementation is a no-op. Drivers override to handle quirks
        like LIMIT→ROWS...TO (Firebird), CONCAT vs ||, etc.
        """
        return sql

    def _supports_returning(self) -> bool:
        """Whether the engine natively supports RETURNING clauses."""
        return False

    @staticmethod
    def _extract_table(sql: str) -> str:
        """Extract the table name from an INSERT/UPDATE/DELETE statement."""
        sql_upper = sql.strip().upper()
        if sql_upper.startswith("INSERT"):
            m = re.search(r"INSERT\s+INTO\s+(\S+)", sql, re.IGNORECASE)
        elif sql_upper.startswith("UPDATE"):
            m = re.search(r"UPDATE\s+(\S+)", sql, re.IGNORECASE)
        elif sql_upper.startswith("DELETE"):
            m = re.search(r"DELETE\s+FROM\s+(\S+)", sql, re.IGNORECASE)
        else:
            m = None
        return m.group(1) if m else "unknown"


class SqlCrudMixin:
    """Engine-neutral INSERT/UPDATE/DELETE composition — NOT part of the
    declared DatabaseAdapter interface (ADR-0044, DBA-S03: adapter-required-
    boundary excludes engine-neutral composition).

    Building ``INSERT INTO x (a, b) VALUES (?, ?)`` from a dict is not
    engine-specific work — it was reimplemented identically in all six SQL
    adapters until this was extracted. Every built-in SQL adapter mixes this
    in ALONGSIDE ``DatabaseAdapter`` (``class SQLiteAdapter(SqlCrudMixin,
    DatabaseAdapter)``), so every adapter still has a fully working
    ``insert``/``update``/``delete`` — reflecting the DECLARED interface
    (``DatabaseAdapter`` alone) no longer shows them, because they were never
    defined there. MongoDB does not mix this in: it does not build SQL at all,
    and keeps its own native insert/update/delete.
    """

    def insert(self, table: str, data: dict | list) -> DatabaseResult:
        """Insert one or more rows.

        Args:
            table: Table name.
            data: A dict (single row) or a list of dicts (multiple rows).
                  List of dicts uses execute_many internally for efficiency.
        """
        if isinstance(data, list):
            if not data:
                return DatabaseResult()
            # All dicts must have the same keys
            keys = list(data[0].keys())
            columns = ", ".join(self.quote_identifier(k) for k in keys)
            placeholders = ", ".join([self.PARAM_MARKER] * len(keys))
            sql = f"INSERT INTO {self.quote_identifier(table)} ({columns}) VALUES ({placeholders})"
            params_list = [list(row[k] for k in keys) for row in data]
            return self.execute_many(sql, params_list)

        columns = ", ".join(self.quote_identifier(c) for c in data.keys())
        placeholders = ", ".join([self.PARAM_MARKER] * len(data))
        sql = (
            f"INSERT INTO {self.quote_identifier(table)} "
            f"({columns}) VALUES ({placeholders}){self.INSERT_RETURNING}"
        )
        return self.execute(sql, list(data.values()))

    def update(self, table: str, data: dict,
               filter_sql: str = "", params: list = None) -> DatabaseResult:
        """Update rows matching the filter.

        The SET column names are QUOTED. SQLite already quoted them while
        PostgreSQL, MySQL and MSSQL did not, so a column named after a reserved
        word worked on one engine and failed on three. Quoting is what every
        INSERT in this file already does.
        """
        set_clause = ", ".join(
            f"{self.quote_identifier(k)} = {self.PARAM_MARKER}" for k in data.keys()
        )
        sql = f"UPDATE {self.quote_identifier(table)} SET {set_clause}"
        all_params = list(data.values())

        if filter_sql:
            sql += f" WHERE {self._marked_filter(filter_sql)}"
            all_params += params or []

        return self.execute(sql, all_params)

    def delete(self, table: str,
               filter_sql: str | dict | list = "", params: list = None) -> DatabaseResult:
        """Delete rows matching the filter.

        Args:
            table: Table name.
            filter_sql: One of:
                - str: SQL WHERE clause (e.g. "age < 18")
                - dict: builds WHERE from dict keys (e.g. {"id": 5} → "id = ?")
                - list of dicts: delete multiple rows by key match
            params: Parameters for the WHERE clause (only with str filter_sql).
        """
        if isinstance(filter_sql, list):
            # List of dicts — delete each row
            total_affected = 0
            for row_filter in filter_sql:
                result = self.delete(table, row_filter)
                total_affected += result.affected_rows
            return DatabaseResult(affected_rows=total_affected)

        if isinstance(filter_sql, dict):
            # Build WHERE from dict. Emits "?" deliberately: the string branch
            # below runs it through _marked_filter, so translating here too
            # would double-translate on a "%s" engine.
            where_parts = [f"{self.quote_identifier(k)} = ?" for k in filter_sql.keys()]
            where_sql = " AND ".join(where_parts)
            return self.delete(table, where_sql, list(filter_sql.values()))

        sql = f"DELETE FROM {self.quote_identifier(table)}"
        if filter_sql:
            sql += f" WHERE {self._marked_filter(filter_sql)}"
        return self.execute(sql, params or [])

    def _returning_pk(self, table: str) -> str | None:
        """The table's single PRIMARY KEY column, for RETURNING emulation.

        MySQL, MSSQL and Firebird have no usable native RETURNING here (Firebird
        has it from 2.1+ but this adapter emulates for cross-engine consistency),
        so after an INSERT they re-select the just-inserted row by its REAL
        primary key -- never a hardcoded ``id`` (the ``*-RETURNING-ID`` fixes: a
        table whose PK is not named ``id`` used to fail or re-select the wrong
        row). Introspected via :meth:`get_columns` and cached per table. Returns
        ``None`` when the table has no single-column PK, so a composite or
        key-less table degrades to no re-select rather than a wrong one.

        Shared by every SQL adapter that emulates RETURNING; engines with native
        RETURNING (PostgreSQL, SQLite) never call it.
        """
        cache = self.__dict__.setdefault("_returning_pk_cache", {})
        if table not in cache:
            try:
                pks = [c["name"] for c in self.get_columns(table) if c.get("primary_key")]
            except Exception:  # noqa: BLE001 - no introspection => no re-select
                pks = []
            cache[table] = pks[0] if len(pks) == 1 else None
        return cache[table]


# ── SQL Translation Rules ──────────────────────────────────────
# Reusable translation functions for common cross-engine quirks.

# SQLTranslator moved to sql_translator.py (feature 3: the adapter module is the
# adapter contract and nothing else). Re-exported here because the sqlite,
# firebird, mssql and odbc adapters import it from this module, and a file move
# is not the place to churn their imports.
from tina4_python.database.sql_translator import (  # noqa: E402,F401
    SQLTranslator, SpatialNotSupportedError,
)
