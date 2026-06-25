# Tina4 Migration Runner — Execute, create, and rollback SQL migrations.
"""
Migrations are .sql files in a migrations/ folder, named with either pattern:
    000001_create_users_table.sql       (sequential)
    20260324153045_add_email_column.sql  (timestamp — YYYYMMDDHHMMSS)

Both naming patterns are supported. New migrations use timestamp format by default.
Each file is executed once. State tracked in tina4_migration table.
Rollback uses matching .down.sql files.
"""
import logging
import os
import re
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class MigrationBase:
    """Base class for programmatic Python migrations.

    Subclass this and implement up(db) and down(db).

    Example migration file (20240101000000_create_users.py)::

        from tina4_python.migration import MigrationBase

        class CreateUsers(MigrationBase):
            def up(self, db):
                db.execute(\"\"\"
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        email TEXT NOT NULL
                    )
                \"\"\")

            def down(self, db):
                db.execute("DROP TABLE IF EXISTS users")
    """

    def up(self, db=None) -> None:
        """Apply the migration. Override in subclass."""
        raise NotImplementedError("Migration subclass must implement up(db)")

    def down(self, db=None) -> None:
        """Reverse the migration. Override in subclass."""
        raise NotImplementedError("Migration subclass must implement down(db)")


def _execute_python_migration(db, filepath: Path, direction: str) -> None:
    """Load a .py migration file and call its up() or down() method."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_tina4_migration", filepath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Find the MigrationBase subclass defined in the module
    klass = None
    for attr in dir(module):
        obj = getattr(module, attr)
        if (
            isinstance(obj, type)
            and issubclass(obj, MigrationBase)
            and obj is not MigrationBase
        ):
            klass = obj
            break

    if klass is None:
        raise RuntimeError(f"No MigrationBase subclass found in {filepath}")

    instance = klass()
    getattr(instance, direction)(db)


def _create_v3_table(db) -> None:
    """Create the v3 tina4_migration table from scratch."""
    if _is_firebird(db):
        # Firebird: no AUTOINCREMENT, no TEXT type, use generator for IDs
        try:
            db.execute("CREATE GENERATOR GEN_TINA4_MIGRATION_ID")
            db.commit()
        except Exception:
            pass  # Generator may already exist
        db.execute("""
            CREATE TABLE tina4_migration (
                id INTEGER NOT NULL PRIMARY KEY,
                migration_id VARCHAR(500) NOT NULL UNIQUE,
                description VARCHAR(500),
                batch INTEGER DEFAULT 1 NOT NULL,
                executed_at VARCHAR(50) NOT NULL,
                passed INTEGER DEFAULT 1 NOT NULL
            )
        """)
    else:
        # Engine-aware bookkeeping DDL. Each engine spells an auto-increment
        # integer PK differently (SQLite AUTOINCREMENT, PostgreSQL SERIAL, MySQL
        # AUTO_INCREMENT, MSSQL IDENTITY), and a TEXT column cannot carry a UNIQUE
        # constraint on MySQL -- so migration_id is VARCHAR. (SQLite gives VARCHAR
        # TEXT affinity, so this stays behaviour-identical there.) Mirrors the
        # engine-aware DDL in ORM.create_table; without it `migrate()` died with
        # "syntax error at AUTOINCREMENT" on PostgreSQL/MySQL/MSSQL.
        engine = (db.get_database_type() or "sqlite").lower()
        id_column = {
            "postgresql": "id SERIAL PRIMARY KEY",
            "mysql": "id INTEGER PRIMARY KEY AUTO_INCREMENT",
            "mssql": "id INTEGER IDENTITY(1,1) PRIMARY KEY",
        }.get(engine, "id INTEGER PRIMARY KEY AUTOINCREMENT")
        db.execute(f"""
            CREATE TABLE tina4_migration (
                {id_column},
                migration_id VARCHAR(500) NOT NULL UNIQUE,
                description VARCHAR(500),
                batch INTEGER NOT NULL DEFAULT 1,
                executed_at VARCHAR(50) NOT NULL,
                passed INTEGER NOT NULL DEFAULT 1
            )
        """)
    db.commit()


def _column_names(db) -> set[str]:
    """Return the lowercased set of column names on tina4_migration."""
    try:
        return {
            (c.get("name") or "").lower()
            for c in db.get_columns("tina4_migration")
        }
    except Exception:
        return set()


def _build_stem_map(migration_folder: str | None) -> list[str]:
    """Scan the migrations folder and return a list of file stems.

    Used by the v2→v3 backfill to match a v2 row's `description` to the
    actual file on disk, so the resulting `migration_id` matches what
    `migrate()` will compare against next.
    """
    if not migration_folder:
        return []
    folder = Path(migration_folder)
    if not folder.is_dir():
        return []
    stems: list[str] = []
    for pattern in ("*.sql", "*.py"):
        for f in folder.glob(pattern):
            if f.name.endswith(".down.sql"):
                continue
            stems.append(f.stem)
    return stems


def _resolve_migration_id(description: str, stems: list[str]) -> str:
    """Find the file stem that corresponds to a v2 description, or fall back.

    Match strategy, in order:
      1. Exact stem match.
      2. A stem ending in "_" + description (e.g. "000001_create_users"
         resolves a v2 description of "create_users").
      3. A stem containing description as a substring.
      4. Keep the description verbatim. The row still appears in
         getAppliedMigrations() but migrate() may re-run if a real file
         exists with a different name.
    """
    if description in stems:
        return description
    for stem in stems:
        if stem.endswith("_" + description):
            return stem
    for stem in stems:
        if description in stem:
            return stem
    return description


def _upgrade_v2_to_v3(db, migration_folder: str | None) -> None:
    """In-place upgrade of a Python-v2 tina4_migration table to v3.

    1. ALTER TABLE ADD the v3 columns (migration_id, batch, executed_at)
       alongside the existing v2 columns. v2 columns stay in place so a
       manual rollback path remains open; they are simply ignored from
       now on.
    2. Backfill every v2 row's migration_id by matching `description`
       against the on-disk file stems. Falls back to the description
       verbatim when no file matches. All legacy rows get batch=1 and
       executed_at='legacy'.
    """
    logger.warning(
        "Detected legacy v2 tina4_migration schema — performing in-place upgrade to v3"
    )

    cols = _column_names(db)

    if "migration_id" not in cols:
        col_type = "VARCHAR(500)" if _is_firebird(db) else "TEXT"
        try:
            db.execute(f"ALTER TABLE tina4_migration ADD migration_id {col_type}")
            db.commit()
        except Exception as e:
            logger.debug(f"v2→v3 upgrade: ALTER ADD migration_id skipped: {e}")

    if "batch" not in cols:
        try:
            db.execute("ALTER TABLE tina4_migration ADD batch INTEGER DEFAULT 1")
            db.commit()
        except Exception as e:
            logger.debug(f"v2→v3 upgrade: ALTER ADD batch skipped: {e}")

    if "executed_at" not in cols:
        try:
            col_type = "VARCHAR(50)" if _is_firebird(db) else "TEXT"
            db.execute(
                f"ALTER TABLE tina4_migration ADD executed_at {col_type} DEFAULT 'legacy'"
            )
            db.commit()
        except Exception as e:
            logger.debug(f"v2→v3 upgrade: ALTER ADD executed_at skipped: {e}")

    # Backfill — best-effort match descriptions to files on disk
    stems = _build_stem_map(migration_folder)

    try:
        rows = db.fetch(
            "SELECT description, passed FROM tina4_migration WHERE migration_id IS NULL",
            limit=100000,
        ).records
    except Exception as e:
        logger.error(f"v2→v3 upgrade: failed to read legacy rows: {e}")
        return

    backfilled = 0
    failed_in_v2 = 0

    for row in rows:
        desc = (row.get("description") or "").strip()
        if not desc:
            continue

        migration_id = _resolve_migration_id(desc, stems)

        try:
            db.execute(
                "UPDATE tina4_migration SET migration_id = ?, batch = 1 "
                "WHERE description = ? AND migration_id IS NULL",
                [migration_id, desc],
            )
            db.commit()
            backfilled += 1
            if int(row.get("passed") or 0) == 0:
                failed_in_v2 += 1
        except Exception as e:
            logger.error(f"v2→v3 upgrade: failed to backfill {desc!r}: {e}")

    note = (
        f" ({failed_in_v2} were marked passed=0 in v2 — review manually)"
        if failed_in_v2
        else ""
    )
    logger.info(
        f"v2→v3 tina4_migration upgrade complete: {backfilled} rows backfilled{note}"
    )


def _ensure_tracking_table(db, migration_folder: str | None = None):
    """Create or upgrade the migration tracking table.

    Handles v2→v3 upgrade: v2 tables have `description` but no `migration_id`.
    When detected, adds the missing v3 columns and backfills `migration_id`
    by matching `description` against the on-disk file stems so subsequent
    `migrate()` calls do not re-apply already-applied migrations.

    See tests/test_issue_115_v2_upgrade.py for the contract.
    """
    if not db.table_exists("tina4_migration"):
        _create_v3_table(db)
        return

    cols = _column_names(db)
    has_v3_shape = (
        "migration_id" in cols
        and "batch" in cols
        and "executed_at" in cols
    )
    if not has_v3_shape:
        _upgrade_v2_to_v3(db, migration_folder)


def _get_executed(db) -> set[str]:
    """Get set of already-executed migration IDs."""
    try:
        result = db.fetch(
            "SELECT migration_id FROM tina4_migration WHERE passed = 1",
            limit=10000,
        )
        return {row["migration_id"] for row in result.records if row.get("migration_id")}
    except Exception:
        # Fallback for v2 tables where migration_id may not exist yet
        result = db.fetch(
            "SELECT description FROM tina4_migration WHERE passed = 1",
            limit=10000,
        )
        return {row["description"] for row in result.records if row.get("description")}


def _get_next_batch(db) -> int:
    """Get next batch number."""
    row = db.fetch_one("SELECT MAX(batch) as max_batch FROM tina4_migration")
    return (row["max_batch"] or 0) + 1 if row else 1


# Smart/curly quotes — editors, word processors, docs and chat apps silently
# convert a straight " to “ ” and a straight ' to ‘ ’ (plus primes ′ ″). Those
# characters are NOT valid SQL string/identifier delimiters, so a pasted-in
# migration fails to run ("syntax error near …"). Map them back to straight
# ASCII quotes. (Real string CONTENTS are unaffected by intent — we only swap
# the lookalike code points for their ASCII equivalents.)
_SMART_QUOTES = {
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',  # “ ” „ ‟ ″
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",  # ‘ ’ ‚ ‛ ′
}
_SMART_QUOTE_RE = re.compile("|".join(re.escape(c) for c in _SMART_QUOTES))


def _normalize_quotes(sql: str) -> str:
    """Replace smart/curly quotes with straight ASCII quotes so migration SQL
    authored or pasted from an editor/doc actually runs (those code points are
    not valid SQL delimiters)."""
    return _SMART_QUOTE_RE.sub(lambda m: _SMART_QUOTES[m.group(0)], sql)


def _split_statements(sql: str, delimiter: str = ";") -> list[str]:
    """Split SQL into individual statements with a single-pass, quote- and
    comment-aware scanner.

    The split decision is made character by character so the delimiter only ever
    fires in real statement position. This is the fix for issue #54: the old
    implementation split on ``delimiter`` BEFORE stripping ``-- …`` line comments,
    so a ``;`` *inside* a line comment fragmented one statement into several
    broken pieces. A scanner that knows where it is — code, comment, or string —
    cannot make that mistake.

    Handled, in priority order, only when NOT already inside a stored-proc block:

    - **Stored-procedure blocks** delimited by ``$$`` or ``//`` are kept intact
      (their inner ``;`` never splits). A ``//`` preceded by ``:`` is a URL
      scheme (``https://…``), not a block delimiter, so it is left alone.
    - **Block comments** ``/* … */`` are stripped.
    - **Line comments** ``-- …`` are stripped to end of line (the newline is
      kept, so line structure survives). A ``;`` here never splits.
    - **String literals** — single-quoted ``'…'`` and double-quoted identifiers
      ``"…"`` — are copied verbatim, honouring the SQL doubled-quote escape
      (``''`` / ``""``). A ``;``, ``--`` or ``/*`` inside a literal is data, not
      a delimiter or comment, so it is preserved untouched.
    - The **delimiter** ends a statement only when reached outside all of the
      above. Empty statements are dropped; each kept statement is trimmed.

    Smart/curly quotes are normalized to straight ASCII first. Mirrors the
    tina4-php ``Migration::splitStatements`` scanner for cross-framework parity.
    """
    # Normalize smart/curly quotes to straight ASCII first, so SQL pasted from
    # an editor/doc (which converts " → “ ” and ' → ‘ ’) actually runs.
    sql = _normalize_quotes(sql)

    statements: list[str] = []
    current: list[str] = []
    n = len(sql)
    dlen = len(delimiter)
    i = 0
    in_dollar_block = False
    in_slash_block = False

    while i < n:
        ch = sql[i]

        # $$ … $$ stored-proc block (toggle in/out).
        if not in_slash_block and ch == "$" and i + 1 < n and sql[i + 1] == "$":
            current.append("$$")
            i += 2
            in_dollar_block = not in_dollar_block
            continue

        # // … // stored-proc block (toggle). The `//` must NOT be preceded by a
        # colon, so a URL scheme (`https://…`) or any `://` literal is never
        # treated as a block delimiter (it would otherwise swallow everything
        # between two `//` occurrences and skip statement splitting).
        if (not in_dollar_block and ch == "/" and i + 1 < n and sql[i + 1] == "/"
                and not (i > 0 and sql[i - 1] == ":")):
            current.append("//")
            i += 2
            in_slash_block = not in_slash_block
            continue

        # Inside a stored-proc block: consume verbatim (inner ; never splits).
        if in_dollar_block or in_slash_block:
            current.append(ch)
            i += 1
            continue

        # Block comment /* … */ — stripped.
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            end = sql.find("*/", i + 2)
            i = (end + 2) if end != -1 else n
            continue

        # Line comment -- … — stripped to end of line; the newline is left for
        # the next iteration so line structure (and statement boundaries on the
        # NEXT line) survive. A ';' inside the comment is NOT a delimiter.
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            end = sql.find("\n", i + 2)
            i = end if end != -1 else n
            continue

        # Single-quoted string literal — '' escapes a quote. Copied verbatim so a
        # ';' / '--' / '/*' inside the value is data, not a delimiter/comment.
        if ch == "'":
            current.append("'")
            i += 1
            while i < n:
                if sql[i] == "'" and i + 1 < n and sql[i + 1] == "'":
                    current.append("''")
                    i += 2
                elif sql[i] == "'":
                    current.append("'")
                    i += 1
                    break
                else:
                    current.append(sql[i])
                    i += 1
            continue

        # Double-quoted identifier — "" escapes a quote. Same verbatim handling.
        if ch == '"':
            current.append('"')
            i += 1
            while i < n:
                if sql[i] == '"' and i + 1 < n and sql[i + 1] == '"':
                    current.append('""')
                    i += 2
                elif sql[i] == '"':
                    current.append('"')
                    i += 1
                    break
                else:
                    current.append(sql[i])
                    i += 1
            continue

        # Statement delimiter — only reached outside blocks/comments/strings.
        if delimiter and sql.startswith(delimiter, i):
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += dlen
            continue

        current.append(ch)
        i += 1

    stmt = "".join(current).strip()
    if stmt:
        statements.append(stmt)
    return statements


def _is_firebird(db) -> bool:
    """Check if the database connection is Firebird."""
    try:
        return db.get_database_type() == "firebird"
    except (AttributeError, Exception):
        return False


# Regex to match ALTER TABLE <table> ADD <column> ...
# Captures the table name and column name from the SQL statement.
_ALTER_ADD_RE = re.compile(
    r"^\s*ALTER\s+TABLE\s+"
    r"(?:\"([^\"]+)\"|(\S+))"       # table name (quoted or unquoted)
    r"\s+ADD\s+"
    r"(?:\"([^\"]+)\"|(\S+))",       # column name (quoted or unquoted)
    re.IGNORECASE,
)


def _firebird_column_exists(db, table: str, column: str) -> bool:
    """Check if a column already exists in a Firebird table via RDB$RELATION_FIELDS.

    Firebird does not support IF NOT EXISTS for ALTER TABLE ADD, so we query
    the system catalogue directly. Column and table names are compared in
    upper-case because Firebird stores unquoted identifiers that way.
    """
    row = db.fetch_one(
        "SELECT 1 FROM RDB$RELATION_FIELDS "
        "WHERE RDB$RELATION_NAME = ? AND TRIM(RDB$FIELD_NAME) = ?",
        [table.upper(), column.upper()],
    )
    return row is not None


def _should_skip_for_firebird(db, stmt: str) -> str | None:
    """If stmt is an ALTER TABLE ... ADD on Firebird and the column already exists, return a skip reason.

    Returns None if the statement should be executed normally.
    This makes ALTER TABLE ADD idempotent on Firebird, which lacks IF NOT EXISTS
    for column additions. Only genuine duplicates are skipped — other errors
    (bad syntax, wrong data type, etc.) will still raise normally on execute().
    """
    if not _is_firebird(db):
        return None

    m = _ALTER_ADD_RE.match(stmt)
    if not m:
        return None

    table = m.group(1) or m.group(2)
    column = m.group(3) or m.group(4)

    if _firebird_column_exists(db, table, column):
        return f"Column {column} already exists in {table}, skipping"

    return None


def _migration_sort_key(name: str):
    """Numeric-aware sort key for migration filenames so `9_*` sorts before
    `10_*` (plain lexical sort puts "10" before "9"). Files with a leading
    numeric/timestamp prefix sort first by that number; the rest sort after,
    lexically."""
    m = re.match(r"^(\d+)", name)
    return (0, int(m.group(1)), name) if m else (1, 0, name)


# CREATE TABLE <name> — name may be quoted ("x"), bracketed ([x] MSSQL), or bare.
_CREATE_TABLE_RE = re.compile(
    r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:\"([^\"]+)\"|\[([^\]]+)\]|(\w+))",
    re.IGNORECASE,
)


def _should_skip_create_table(db, stmt: str) -> str | None:
    """Make CREATE TABLE idempotent on engines lacking IF NOT EXISTS.

    Firebird and MSSQL do not support `CREATE TABLE IF NOT EXISTS`, so a raw
    CREATE in a re-run migration raises "object already exists". When the target
    table already exists on those engines, return a skip reason so the statement
    is skipped (mirrors the Firebird ALTER-TABLE-ADD idempotency guard).
    SQLite/MySQL/PostgreSQL support IF NOT EXISTS and are left to the engine.
    Only a genuine already-exists is skipped — every other error still raises.
    """
    try:
        engine = db.get_database_type()
    except Exception:
        return None
    if engine not in ("firebird", "mssql"):
        return None
    m = _CREATE_TABLE_RE.match(stmt)
    if not m:
        return None
    table = m.group(1) or m.group(2) or m.group(3)
    try:
        if db.table_exists(table):
            return f"Table {table} already exists, skipping CREATE TABLE"
    except Exception:
        return None
    return None


def _migrate(db, migration_folder: str = "migrations", delimiter: str = ";") -> list[str]:
    """Run all pending migrations (internal implementation).

    Returns list of executed migration filenames.
    Use Migration class for the public API.
    """
    _ensure_tracking_table(db, migration_folder)

    folder = Path(migration_folder)
    if not folder.is_dir():
        return []

    executed = _get_executed(db)
    batch = _get_next_batch(db)
    ran = []

    # Collect both .sql and .py migration files. Sort by a leading numeric /
    # timestamp prefix (numeric-aware) so `9_*` applies before `10_*` — a plain
    # lexical sort misorders unpadded prefixes ("10" < "9"). Files with no numeric
    # prefix sort after the numbered ones, then lexically.
    migration_files = sorted(
        [f for f in folder.glob("*.sql") if not f.name.endswith(".down.sql")]
        + [f for f in folder.glob("*.py") if not f.name.startswith("__")],
        key=lambda f: _migration_sort_key(f.name),
    )
    # Warn (once) about filenames without a recognized NNNNNN_/timestamp prefix —
    # their ordering relative to numbered migrations is undefined, a silent
    # out-of-order-apply footgun.
    unprefixed = [f.name for f in migration_files if not re.match(r"^\d+[_-]", f.name)]
    if unprefixed:
        logger.warning(
            "Migration file(s) without a numeric/timestamp prefix may apply out of order: "
            + ", ".join(unprefixed)
        )

    for mig_file in migration_files:
        migration_id = mig_file.stem  # e.g., "000001_create_users_table"

        if migration_id in executed:
            continue

        try:
            db.start_transaction()

            if mig_file.suffix == ".py":
                _execute_python_migration(db, mig_file, "up")
            else:
                sql = mig_file.read_text(encoding="utf-8")
                statements = _split_statements(sql, delimiter)
                for stmt in statements:
                    # Idempotency on engines lacking IF NOT EXISTS: Firebird
                    # ALTER-TABLE-ADD, and CREATE TABLE on Firebird/MSSQL.
                    skip_reason = _should_skip_for_firebird(db, stmt) or _should_skip_create_table(db, stmt)
                    if skip_reason:
                        logger.info(f"Migration {mig_file.name}: {skip_reason}")
                        continue
                    if db.execute(stmt) is False:
                        raise RuntimeError(f"Migration failed: {db.get_error() or stmt[:80]}")

            # Record as passed
            now = datetime.now(timezone.utc).isoformat()
            desc = re.sub(r"^\d+_", "", migration_id, count=1).replace("_", " ")
            if _is_firebird(db):
                row = db.fetch_one("SELECT GEN_ID(GEN_TINA4_MIGRATION_ID, 1) AS next_id FROM RDB$DATABASE")
                next_id = row["next_id"] if row else 1
                db.execute(
                    "INSERT INTO tina4_migration (id, migration_id, description, batch, executed_at, passed) VALUES (?, ?, ?, ?, ?, 1)",
                    [next_id, migration_id, desc, batch, now],
                )
            else:
                db.execute(
                    "INSERT INTO tina4_migration (migration_id, description, batch, executed_at, passed) VALUES (?, ?, ?, ?, 1)",
                    [migration_id, desc, batch, now],
                )
            db.commit()
            ran.append(mig_file.name)

        except Exception as e:
            db.rollback()
            raise RuntimeError(
                f"Migration failed: {mig_file.name} — {e}"
            ) from e

    return ran


def _rollback(db, migration_folder: str = "migrations", delimiter: str = ";") -> list[str]:
    """Rollback the last batch of migrations (internal implementation).

    Looks for matching .down.sql files and executes them in reverse order.
    Returns list of rolled-back migration filenames.
    Use Migration class for the public API.
    """
    _ensure_tracking_table(db, migration_folder)

    # Get last batch
    row = db.fetch_one("SELECT MAX(batch) as max_batch FROM tina4_migration WHERE passed = 1")
    if not row or not row["max_batch"]:
        return []

    last_batch = row["max_batch"]
    result = db.fetch(
        "SELECT migration_id FROM tina4_migration WHERE batch = ? AND passed = 1 ORDER BY migration_id DESC",
        [last_batch],
        limit=10000,
    )

    folder = Path(migration_folder)
    rolled_back = []

    for migration in result.records:
        mid = migration["migration_id"]
        py_file = folder / f"{mid}.py"
        down_file = folder / f"{mid}.down.sql"

        try:
            db.start_transaction()

            if py_file.exists():
                _execute_python_migration(db, py_file, "down")
                rolled_back_name = f"{mid}.py"
            elif down_file.exists():
                sql = down_file.read_text(encoding="utf-8")
                statements = _split_statements(sql, delimiter)
                for stmt in statements:
                    if db.execute(stmt) is False:
                        raise RuntimeError(f"Rollback failed: {db.get_error() or stmt[:80]}")
                rolled_back_name = f"{mid}.down.sql"
            else:
                raise RuntimeError(
                    f"Cannot rollback {mid}: no .py or .down.sql file found"
                )

            db.execute(
                "DELETE FROM tina4_migration WHERE migration_id = ?",
                [mid],
            )
            db.commit()
            rolled_back.append(rolled_back_name)

        except Exception as e:
            db.rollback()
            raise RuntimeError(
                f"Rollback failed: {mid} — {e}"
            ) from e

    return rolled_back


def create_migration(description: str, migration_folder: str = "migrations", kind: str = "sql") -> str:
    """Create a new migration file with a YYYYMMDDHHMMSS timestamp prefix.

    kind="sql"    — creates {timestamp}_{description}.sql + .down.sql (default)
    kind="python" — creates {timestamp}_{description}.py with MigrationBase subclass

    Returns the path to the created file.
    """
    folder = Path(migration_folder)
    folder.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    clean = re.sub(r"[^a-z0-9]+", "_", description.lower()).strip("_")
    created_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    if kind == "python":
        # Derive a CamelCase class name from description
        class_name = "".join(word.capitalize() for word in re.split(r"[^a-z0-9]+", description.lower()) if word)
        filename = f"{timestamp}_{clean}.py"
        filepath = folder / filename
        filepath.write_text(
            f"# Migration: {description}\n"
            f"# Created: {created_at}\n\n"
            f"from tina4_python.migration import MigrationBase\n\n\n"
            f"class {class_name}(MigrationBase):\n"
            f"    def up(self, db) -> None:\n"
            f"        pass  # db.execute(\"CREATE TABLE ...\")\n\n"
            f"    def down(self, db) -> None:\n"
            f"        pass  # db.execute(\"DROP TABLE IF EXISTS ...\")\n",
            encoding="utf-8",
        )
        return str(filepath)

    filename = f"{timestamp}_{clean}.sql"
    filepath = folder / filename

    filepath.write_text(
        f"-- Migration: {description}\n"
        f"-- Created: {created_at}\n\n",
        encoding="utf-8",
    )

    down_path = folder / f"{timestamp}_{clean}.down.sql"
    down_path.write_text(
        f"-- Rollback: {description}\n"
        f"-- Created: {created_at}\n\n",
        encoding="utf-8",
    )

    return str(filepath)


class Migration:
    """Object-oriented wrapper around the migration runner functions.

    Provides the canonical Tina4 Migration API with parity across all 4 frameworks:
        - migrate()          Run all pending migrations
        - rollback(steps=1)  Roll back last N batches
        - status()           Show completed/pending
        - create(description) Scaffold new .sql + .down.sql files
        - get_applied()      List applied migrations
        - get_pending()      List pending migrations
        - get_files()        List all migration files on disk

    Example::

        from tina4_python.migration import Migration

        m = Migration(db, "migrations")
        m.migrate()
        m.rollback(steps=2)
        m.status()
        m.create("add users table")
    """

    def __init__(self, db, migrations_dir: str = "migrations", delimiter: str = ";"):
        self._db = db
        self._dir = migrations_dir
        self._delim = delimiter
        # Eagerly create or upgrade the tracking table. Matches PHP/Ruby/Node
        # parity and triggers the v2→v3 auto-upgrade on construction so a
        # newly-instantiated Migration immediately reflects v3 shape.
        _ensure_tracking_table(self._db, self._dir)

    def migrate(self) -> list[str]:
        """Run all pending migrations. Returns list of applied filenames."""
        return _migrate(self._db, self._dir, self._delim)

    def rollback(self, steps: int = 1) -> list[str]:
        """Roll back the last N batches. Returns list of rolled-back filenames."""
        rolled: list[str] = []
        for _ in range(steps):
            batch = _rollback(self._db, self._dir, self._delim)
            if not batch:
                break
            rolled.extend(batch)
        return rolled

    def status(self) -> dict:
        """Return {"completed": [...], "pending": [...]} migration status."""
        return _status(self._db, self._dir)

    def create(self, description: str, kind: str = "sql") -> str:
        """Scaffold a new migration file. Returns the up-file path."""
        return create_migration(description, self._dir, kind=kind)

    def get_applied(self) -> list[dict]:
        """Return list of applied migration records."""
        return self.status()["completed"]

    def get_applied_migrations(self) -> list[dict]:
        """Alias for get_applied() — parity with PHP/Node."""
        return self.get_applied()

    def get_pending(self) -> list[dict]:
        """Return list of pending migration records."""
        return self.status()["pending"]

    def get_files(self) -> list[str]:
        """Return sorted list of all migration filenames on disk (excludes .down.sql)."""
        folder = Path(self._dir)
        if not folder.is_dir():
            return []
        return sorted(f.name for f in folder.glob("*.sql") if not f.name.endswith(".down.sql"))

    def record_migration(self, name: str, batch: int, passed: int = 1) -> None:
        """Insert a record into the migration tracking table.

        Args:
            name: Migration ID (stem of the filename, e.g. "20240101000000_create_users").
            batch: Batch number this migration belongs to.
            passed: 1 if the migration succeeded (default), 0 if it failed.
        """
        _ensure_tracking_table(self._db, self._dir)
        now = datetime.now(timezone.utc).isoformat()
        desc = re.sub(r"^\d+_", "", name, count=1).replace("_", " ")
        if _is_firebird(self._db):
            row = self._db.fetch_one("SELECT GEN_ID(GEN_TINA4_MIGRATION_ID, 1) AS next_id FROM RDB$DATABASE")
            next_id = row["next_id"] if row else 1
            self._db.execute(
                "INSERT INTO tina4_migration (id, migration_id, description, batch, executed_at, passed) VALUES (?, ?, ?, ?, ?, ?)",
                [next_id, name, desc, batch, now, passed],
            )
        else:
            self._db.execute(
                "INSERT INTO tina4_migration (migration_id, description, batch, executed_at, passed) VALUES (?, ?, ?, ?, ?)",
                [name, desc, batch, now, passed],
            )

    def remove_migration_record(self, name: str) -> None:
        """Delete a migration record from the tracking table by migration ID.

        Args:
            name: Migration ID to remove (stem of the filename).
        """
        self._db.execute(
            "DELETE FROM tina4_migration WHERE migration_id = ?",
            [name],
        )


def _status(db, migration_folder: str = "migrations") -> dict:
    """Get migration status (internal implementation).

    Returns {"completed": [...], "pending": [...]}, where each entry is
    a dict with 'migration_id', 'description', and (for completed)
    'executed_at' and 'batch'.
    """
    _ensure_tracking_table(db, migration_folder)

    folder = Path(migration_folder)
    if not folder.is_dir():
        return {"completed": [], "pending": []}

    executed = _get_executed(db)

    # Get all .sql files sorted by name (excluding .down.sql)
    sql_files = sorted(
        f for f in folder.glob("*.sql")
        if not f.name.endswith(".down.sql")
    )

    # Build completed list from the database with execution metadata
    result = db.fetch(
        "SELECT migration_id, description, batch, executed_at FROM tina4_migration WHERE passed = 1 ORDER BY migration_id",
        limit=10000,
    )
    completed = [
        {
            "migration_id": row["migration_id"],
            "description": row["description"],
            "batch": row["batch"],
            "executed_at": row["executed_at"],
        }
        for row in result.records
    ]

    # Build pending list from files not yet executed
    pending = []
    for sql_file in sql_files:
        migration_id = sql_file.stem
        if migration_id not in executed:
            desc = re.sub(r"^\d+_", "", migration_id, count=1).replace("_", " ")
            pending.append({
                "migration_id": migration_id,
                "description": desc,
            })

    return {"completed": completed, "pending": pending}
