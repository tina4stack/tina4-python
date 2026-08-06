"""migration_contract :: create_migration validates its `kind`

MEASURED 2026-08-06 across all four frameworks: the accepted value for a CODE
migration differed in every one, and NOT ONE of them validated it.

    python  "python"     php  "php"     ruby  "ruby" or "python"     node  "class"

So `create_migration("add users", kind="python")` produced a code migration in
Python and Ruby and a SILENT .sql FILE in PHP and Node. The same call, four
artefacts, no error anywhere - the caller finds out when the migration does
nothing they wrote.

"code" is now the canonical spelling in all four; each keeps its own language
name as a legacy alias; anything else raises.

Pure filesystem work - no service, no double.
"""
import tempfile
from pathlib import Path

import pytest

from tina4_python.migration import create_migration


class TestMigrationKindContract:
    def test_code_is_the_canonical_kind(self):
        with tempfile.TemporaryDirectory() as d:
            assert Path(create_migration("add users", d, "code")).suffix == ".py"

    def test_the_language_name_still_works_as_a_legacy_alias(self):
        with tempfile.TemporaryDirectory() as d:
            assert Path(create_migration("add users", d, "python")).suffix == ".py"

    def test_sql_is_the_default_and_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            assert Path(create_migration("add users", d)).suffix == ".sql"
            assert Path(create_migration("add more", d, "sql")).suffix == ".sql"

    def test_an_unknown_kind_raises_instead_of_silently_writing_sql(self):
        # The whole point. Another framework's spelling is the most likely typo,
        # and it used to produce a .sql file with no complaint.
        with tempfile.TemporaryDirectory() as d:
            for bogus in ("php", "ruby", "class", "typo"):
                with pytest.raises(ValueError, match="Unknown migration kind"):
                    create_migration("add users", d, bogus)
