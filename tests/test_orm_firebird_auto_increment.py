"""Regression: an ORM model with an auto_increment PK can INSERT on Firebird.

Bug 6 (book review). Firebird has no auto-increment column type. save()
skipped the auto_increment PK on every engine (``if field.auto_increment and
pk_value is None: continue``), so on Firebird the id went in as NULL and the
engine rejected the row ("validation error for column ID, value *** null
***"). save() drew the id from the table's generator (GEN_<TABLE>_ID) before
the insert — the same generator Firebird's insert-id emulation reads back.

NO MOCK: live Firebird. Needs TINA4_TEST_FIREBIRD_URL; the lab provisions
Firebird 5 on :3050 and runs this under TINA4_REQUIRE_SERVICES=1.
"""
from __future__ import annotations

import os
import socket
import uuid

import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, IntegerField, StringField, bind_database


_URL = os.environ.get("TINA4_TEST_FIREBIRD_URL")


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


# Firebird is an OPTIONAL engine; the main `test` job intentionally does not
# provision it (Firebird runs in the dedicated `firebird` job). Gate with a
# per-test skipif carrying the excusable [needs:firebird] tag -- the
# require-services gate passes that here, and the dedicated job (where
# TINA4_TEST_FIREBIRD_URL is set) runs it for real. A module-level
# pytest.skip/raise would instead become a COLLECTION ERROR under the gate
# (see tests/conftest.py), which failed this job for the whole release branch.
pytestmark = pytest.mark.skipif(
    not _URL,
    reason="[needs:firebird] TINA4_TEST_FIREBIRD_URL not set (needs a live Firebird)",
)


_SUFFIX = uuid.uuid4().hex[:8]


class FbWidget(ORM):
    table_name = f"fbw_{_SUFFIX}"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()


@pytest.fixture
def fb_db():
    db = Database(_URL)
    bind_database(db)
    FbWidget.create_table()
    yield db
    try:
        db.execute(f"DROP TABLE {FbWidget.table_name}")
        db.commit()
    except Exception:
        pass
    db.close()


class TestFirebirdAutoIncrementInsert:
    def test_positive_save_assigns_generator_id(self, fb_db):
        """save() on a fresh auto_increment model INSERTs and assigns the id
        from the generator — it must not fail with a null-ID validation error."""
        w = FbWidget({"name": "alpha"})
        result = w.save()

        assert result is not False, (
            f"save() must succeed on Firebird auto_increment; last_error={w.last_error!r}"
        )
        assert w.id is not None and w.id >= 1, "the generator id must be assigned onto the model"
        assert w.last_error is None

    def test_positive_ids_are_monotonic(self, fb_db):
        """Two saves draw consecutive generator ids and both rows persist."""
        a = FbWidget({"name": "one"}); a.save()
        b = FbWidget({"name": "two"}); b.save()
        assert a.id is not None and b.id is not None
        assert b.id > a.id, "the second insert must draw a higher generator id"

        found = FbWidget.find(b.id)
        assert found is not None and found.name == "two", "the row must be readable by its assigned id"
