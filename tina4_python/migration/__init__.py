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

__all__ = ["create_migration", "Migration", "MigrationBase"]
