# Tina4 Migration Runner — Execute, create, and rollback SQL migrations.
"""
Migrations are .sql files in a migrations/ folder, named with either pattern:
    000001_create_users_table.sql       (sequential)
    20260324153045_add_email_column.sql  (timestamp — YYYYMMDDHHMMSS)

Both naming patterns are supported. New migrations use timestamp format by default.
Each file is executed once. State tracked in tina4_migration table.
Rollback uses matching .down.sql files.
"""
import os
import re
from pathlib import Path
from datetime import datetime, timezone


def _ensure_tracking_table(db):
    """Create the migration tracking table if it doesn't exist."""
    if not db.table_exists("tina4_migration"):
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


def _get_executed(db) -> set[str]:
    """Get set of already-executed migration IDs."""
    result = db.fetch(
        "SELECT migration_id FROM tina4_migration WHERE passed = 1",
        limit=10000,
    )
    return {row["migration_id"] for row in result.records}


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
                db.execute(stmt)

            # Record as passed
            now = datetime.now(timezone.utc).isoformat()
            # Extract description from filename (supports both 000001_ and YYYYMMDDHHMMSS_ prefixes)
            desc = re.sub(r"^\d+_", "", migration_id, count=1).replace("_", " ")
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
                db.execute(stmt)
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
