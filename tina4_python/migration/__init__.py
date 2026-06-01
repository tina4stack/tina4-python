# Tina4 Migrations — Run, create, and rollback database migrations.
"""
SQL-file-based migrations with tracking table.

    from tina4_python.migration import Migration, create_migration

    m = Migration(db)
    m.migrate()                          # Run all pending
    m.rollback()                         # Rollback last batch
    m.status()                           # Show completed/pending
    create_migration("add users table")  # Create new .sql file
"""
from tina4_python.migration.runner import create_migration, Migration, MigrationBase


def migrate(db) -> list[str]:
    """Module-level convenience: run pending migrations against ``db``.

    Equivalent to ``Migration(db).migrate()``. Matches the CLI shape
    (``tina4 migrate``) and the function-level API the documentation
    uses across every framework chapter.

        from tina4_python.migration import migrate
        from tina4_python.database import Database

        migrate(Database())   # runs all pending; returns list of applied names
    """
    return Migration(db).migrate()


def rollback(db, steps: int = 1) -> list[str]:
    """Module-level convenience: roll back the last ``steps`` migrations.

    Equivalent to ``Migration(db).rollback(steps)``.
    """
    return Migration(db).rollback(steps)


def status(db) -> dict:
    """Module-level convenience: report migration state.

    Equivalent to ``Migration(db).status()``.
    """
    return Migration(db).status()


__all__ = ["create_migration", "Migration", "MigrationBase", "migrate", "rollback", "status"]
