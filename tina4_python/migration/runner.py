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


def _ensure_tracking_table(db):
    """Create or upgrade the migration tracking table.

    Handles v2→v3 upgrade: v2 tables have `description` but no `migration_id`.
    When detected, adds the missing column and backfills from `description`.
    """
    if not db.table_exists("tina4_migration"):
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
            db.execute("""
                CREATE TABLE tina4_migration (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    migration_id TEXT NOT NULL UNIQUE,
                    description TEXT,
                    batch INTEGER NOT NULL DEFAULT 1,
                    executed_at TEXT NOT NULL,
                    passed INTEGER NOT NULL DEFAULT 1
                )
            """)
        db.commit()
        return

    # Check if this is a v2 table (has description but no migration_id column)
    try:
        db.fetch_one("SELECT migration_id FROM tina4_migration WHERE 1=0")
    except Exception:
        # migration_id column doesn't exist — v2 schema, upgrade it
        try:
            col_type = "VARCHAR(500)" if _is_firebird(db) else "TEXT"
            db.execute(f"ALTER TABLE tina4_migration ADD migration_id {col_type}")
            db.commit()
        except Exception:
            pass  # Column may already exist on some engines

        # Backfill migration_id from description (v2 used description as the identifier)
        try:
            db.execute("UPDATE tina4_migration SET migration_id = description WHERE migration_id IS NULL")
            db.commit()
        except Exception:
            pass

        # Add batch column if missing (v2 didn't have it)
        try:
            db.fetch_one("SELECT batch FROM tina4_migration WHERE 1=0")
        except Exception:
            try:
                db.execute("ALTER TABLE tina4_migration ADD batch INTEGER DEFAULT 1")
                db.commit()
            except Exception:
                pass

        # Add executed_at column if missing
        try:
            db.fetch_one("SELECT executed_at FROM tina4_migration WHERE 1=0")
        except Exception:
            try:
                col_type = "VARCHAR(50)" if _is_firebird(db) else "TEXT"
                db.execute(f"ALTER TABLE tina4_migration ADD executed_at {col_type} DEFAULT ''")
                db.commit()
            except Exception:
                pass


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


def _split_statements(sql: str, delimiter: str = ";") -> list[str]:
    """Split SQL into individual statements.

    Handles:
    - Line comments (-- ...)
    - Block comments (/* ... */)
    - Empty statements
    - Stored procedure blocks delimited by $$ or //
      Example:
          CREATE TRIGGER foo $$ BEGIN ... END $$;
          CREATE PROCEDURE bar // BEGIN ... END //;
    """
    # Extract blocks delimited by $$ or // first, replacing them with placeholders
    blocks: list[str] = []

    def _save_block(m):
        blocks.append(m.group(0))
        return f"__BLOCK_{len(blocks) - 1}__"

    # Match $$ ... $$ or // ... // blocks (stored procedures, triggers, etc.)
    processed = re.sub(r"\$\$(.*?)\$\$", _save_block, sql, flags=re.DOTALL)
    processed = re.sub(r"//(.*?)//", _save_block, processed, flags=re.DOTALL)

    # Remove block comments (but not inside stored proc blocks)
    clean = re.sub(r"/\*.*?\*/", "", processed, flags=re.DOTALL)

    statements = []
    for stmt in clean.split(delimiter):
        # Remove line comments and blank lines
        lines = []
        for line in stmt.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("--"):
                # Remove inline comments (-- after SQL)
                comment_pos = line.find("--")
                if comment_pos >= 0:
                    line = line[:comment_pos]
                lines.append(line)
        cleaned = "\n".join(lines).strip()

        # Restore block placeholders
        for i, block in enumerate(blocks):
            cleaned = cleaned.replace(f"__BLOCK_{i}__", block)

        if cleaned:
            statements.append(cleaned)
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


def migrate(db, migration_folder: str = "migrations", delimiter: str = ";") -> list[str]:
    """Run all pending migrations.

    Returns list of executed migration filenames.
    """
    _ensure_tracking_table(db)

    folder = Path(migration_folder)
    if not folder.is_dir():
        return []

    executed = _get_executed(db)
    batch = _get_next_batch(db)
    ran = []

    # Get all .sql files sorted by name (excluding .down.sql)
    sql_files = sorted(
        f for f in folder.glob("*.sql")
        if not f.name.endswith(".down.sql")
    )

    for sql_file in sql_files:
        migration_id = sql_file.stem  # e.g., "000001_create_users_table"

        if migration_id in executed:
            continue

        sql = sql_file.read_text(encoding="utf-8")
        statements = _split_statements(sql, delimiter)

        try:
            db.start_transaction()
            for stmt in statements:
                # Firebird lacks IF NOT EXISTS for ALTER TABLE ADD.
                # Pre-check the system catalogue so duplicate columns are
                # silently skipped instead of raising an error.
                skip_reason = _should_skip_for_firebird(db, stmt)
                if skip_reason:
                    logger.info(f"Migration {sql_file.name}: {skip_reason}")
                    continue
                if db.execute(stmt) is False:
                    raise RuntimeError(f"Migration failed: {db.get_error() or stmt[:80]}")

            # Record as passed
            now = datetime.now(timezone.utc).isoformat()
            # Extract description from filename (supports both 000001_ and YYYYMMDDHHMMSS_ prefixes)
            desc = re.sub(r"^\d+_", "", migration_id, count=1).replace("_", " ")
            if _is_firebird(db):
                # Firebird: generate ID from sequence
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
            ran.append(sql_file.name)

        except Exception as e:
            db.rollback()
            raise RuntimeError(
                f"Migration failed: {sql_file.name} — {e}"
            ) from e

    return ran


def rollback(db, migration_folder: str = "migrations", delimiter: str = ";") -> list[str]:
    """Rollback the last batch of migrations.

    Looks for matching .down.sql files and executes them in reverse order.
    Returns list of rolled-back migration filenames.
    """
    _ensure_tracking_table(db)

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
        down_file = folder / f"{mid}.down.sql"

        if not down_file.exists():
            raise RuntimeError(
                f"Cannot rollback {mid}: no .down.sql file found at {down_file}"
            )

        sql = down_file.read_text(encoding="utf-8")
        statements = _split_statements(sql, delimiter)

        try:
            db.start_transaction()
            for stmt in statements:
                if db.execute(stmt) is False:
                    raise RuntimeError(f"Rollback failed: {db.get_error() or stmt[:80]}")
            db.execute(
                "DELETE FROM tina4_migration WHERE migration_id = ?",
                [mid],
            )
            db.commit()
            rolled_back.append(f"{mid}.down.sql")

        except Exception as e:
            db.rollback()
            raise RuntimeError(
                f"Rollback failed: {mid} — {e}"
            ) from e

    return rolled_back


def create_migration(description: str, migration_folder: str = "migrations") -> str:
    """Create a new migration .sql file with a YYYYMMDDHHMMSS timestamp prefix.

    Also creates a matching .down.sql rollback template.
    Returns the path to the created file.
    """
    folder = Path(migration_folder)
    folder.mkdir(parents=True, exist_ok=True)

    # Use timestamp format (matches PHP/Ruby/Node.js convention)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    # Clean description for filename
    clean = re.sub(r"[^a-z0-9]+", "_", description.lower()).strip("_")
    filename = f"{timestamp}_{clean}.sql"
    filepath = folder / filename

    created_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    filepath.write_text(
        f"-- Migration: {description}\n"
        f"-- Created: {created_at}\n\n",
        encoding="utf-8",
    )

    # Also create .down.sql
    down_path = folder / f"{timestamp}_{clean}.down.sql"
    down_path.write_text(
        f"-- Rollback: {description}\n"
        f"-- Created: {created_at}\n\n",
        encoding="utf-8",
    )

    return str(filepath)


def status(db, migration_folder: str = "migrations") -> dict:
    """Get migration status: which are completed and which are pending.

    Returns {"completed": [...], "pending": [...]}, where each entry is
    a dict with 'migration_id', 'description', and (for completed)
    'executed_at' and 'batch'.
    """
    _ensure_tracking_table(db)

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
