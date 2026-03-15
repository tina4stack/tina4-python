#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# Tests for Firebird migration idempotency (GitHub Issue #34).
# Verifies that ALTER TABLE ... ADD <column> is safely skipped when
# the column already exists — Firebird has no IF NOT EXISTS support.
#
# Requires: Firebird Docker on localhost:33053
#   docker run -d --name sleek-database -p 33053:3050 \
#     -e FIREBIRD_DATABASE=ACCOUNTING.FDB \
#     -e FIREBIRD_USER=sysdba -e FIREBIRD_PASSWORD=masterkey \
#     jacobalberty/firebird:v3.0

import pytest

from tina4_python.Database import Database
from tina4_python.DatabaseTypes import FIREBIRD
from tina4_python.Migration import _firebird_column_exists, _is_idempotent_skip


def _connect_firebird():
    try:
        db = Database(
            "firebird.driver:localhost/33053:/var/lib/firebird/data/ACCOUNTING.FDB",
            "sysdba", "masterkey",
        )
        if db.dba is None:
            return None
        return db
    except Exception:
        return None


@pytest.fixture(scope="module")
def fb():
    """Provide a Firebird connection or skip the entire module."""
    db = _connect_firebird()
    if db is None:
        pytest.skip("Firebird not available on localhost:33053")
    # Create test table
    db.execute("CREATE TABLE TEST_MIG_IDM (ID INTEGER NOT NULL PRIMARY KEY, NAME VARCHAR(50), EMAIL VARCHAR(100))")
    db.commit()
    yield db
    # Cleanup
    db.execute("DROP TABLE TEST_MIG_IDM")
    db.commit()


class TestFirebirdColumnExists:
    """Tests for _firebird_column_exists using raw cursor."""

    def test_existing_column(self, fb):
        assert _firebird_column_exists(fb, "TEST_MIG_IDM", "NAME") is True

    def test_existing_column_id(self, fb):
        assert _firebird_column_exists(fb, "TEST_MIG_IDM", "ID") is True

    def test_existing_column_email(self, fb):
        assert _firebird_column_exists(fb, "TEST_MIG_IDM", "EMAIL") is True

    def test_nonexistent_column(self, fb):
        assert _firebird_column_exists(fb, "TEST_MIG_IDM", "PHONE") is False

    def test_nonexistent_table(self, fb):
        assert _firebird_column_exists(fb, "NO_SUCH_TABLE", "ID") is False

    def test_case_insensitive(self, fb):
        """Firebird stores identifiers in uppercase; our function should handle lowercase input."""
        assert _firebird_column_exists(fb, "test_mig_idm", "name") is True

    def test_mixed_case(self, fb):
        assert _firebird_column_exists(fb, "Test_Mig_Idm", "Name") is True


class TestIsIdempotentSkip:
    """Tests for _is_idempotent_skip — full ALTER TABLE ... ADD detection."""

    def test_skip_existing_column(self, fb):
        assert _is_idempotent_skip(fb, "ALTER TABLE TEST_MIG_IDM ADD NAME VARCHAR(50)") is True

    def test_no_skip_new_column(self, fb):
        assert _is_idempotent_skip(fb, "ALTER TABLE TEST_MIG_IDM ADD PHONE VARCHAR(20)") is False

    def test_skip_quoted_identifiers(self, fb):
        assert _is_idempotent_skip(fb, 'ALTER TABLE "TEST_MIG_IDM" ADD "EMAIL" VARCHAR(100)') is True

    def test_no_skip_non_alter(self, fb):
        """Non-ALTER statements should never be skipped."""
        assert _is_idempotent_skip(fb, "CREATE TABLE FOO (ID INTEGER)") is False

    def test_no_skip_non_firebird(self, fb):
        """Only applies to Firebird engine."""
        # Temporarily fake a different engine
        original = fb.database_engine
        fb.database_engine = "sqlite3"
        try:
            assert _is_idempotent_skip(fb, "ALTER TABLE TEST_MIG_IDM ADD NAME VARCHAR(50)") is False
        finally:
            fb.database_engine = original

    def test_skip_case_insensitive_sql(self, fb):
        assert _is_idempotent_skip(fb, "alter table test_mig_idm add name varchar(50)") is True

    def test_no_skip_alter_drop(self, fb):
        """ALTER TABLE ... DROP should not be caught by the ADD pattern."""
        assert _is_idempotent_skip(fb, "ALTER TABLE TEST_MIG_IDM DROP NAME") is False

    def test_actual_alter_add_succeeds_for_new_column(self, fb):
        """Verify that a new column can actually be added after _is_idempotent_skip returns False."""
        assert _is_idempotent_skip(fb, "ALTER TABLE TEST_MIG_IDM ADD PHONE VARCHAR(20)") is False
        fb.execute("ALTER TABLE TEST_MIG_IDM ADD PHONE VARCHAR(20)")
        fb.commit()
        assert _firebird_column_exists(fb, "TEST_MIG_IDM", "PHONE") is True
        # Now it should skip
        assert _is_idempotent_skip(fb, "ALTER TABLE TEST_MIG_IDM ADD PHONE VARCHAR(20)") is True
