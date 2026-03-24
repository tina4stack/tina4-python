# Tina4 Migrations — Run, create, and rollback database migrations.
"""
SQL-file-based migrations with tracking table.

    from tina4_python.migration import migrate, create_migration, rollback

    migrate(db)                          # Run all pending
    create_migration("add users table")  # Create new .sql file
    rollback(db)                         # Rollback last batch
"""
from tina4_python.migration.runner import migrate, create_migration, rollback, status

__all__ = ["migrate", "create_migration", "rollback", "status"]
