# Tina4 — SQLite DateTimeField adapter regression tests.
"""
Lock in that the SQLite adapter owns datetime/date -> TEXT serialization with
its OWN explicit adapters, instead of relying on Python's built-in default
sqlite3 datetime adapter (deprecated in 3.12, removed in a future release).

Everything here runs against a REAL SQLite database (temp file / :memory:) — no
mocks. Two complementary guards:

  * A record-based assertion around ORM.save(): the specific
    "default datetime adapter is deprecated" DeprecationWarning must NOT be
    emitted, and the value must round-trip. (save() fails loud and swallows a
    promoted-to-error warning into last_error, so we assert on a recorded list
    rather than expecting an exception here.)
  * An error-promotion assertion on the lower-level db.insert / db.execute
    write path, which fails loud and genuinely RAISES when the deprecated
    default adapter fires — so this test truly fails against the old behaviour.
"""
import datetime
import sqlite3
import tempfile
import warnings
from pathlib import Path

import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, DateTimeField, IntegerField, StringField, bind_database


_DEPRECATION_NEEDLE = "default datetime adapter is deprecated"


def _has_adapter_deprecation(records) -> bool:
    """True if any recorded warning is the sqlite datetime-adapter deprecation."""
    return any(
        issubclass(record.category, DeprecationWarning)
        and _DEPRECATION_NEEDLE in str(record.message)
        for record in records
    )


@pytest.fixture()
def db(tmp_path):
    """A real, file-backed SQLite database bound to the ORM for the test."""
    database = Database("sqlite:///" + str(tmp_path / "dt_adapter.db"))
    bind_database(database)
    yield database
    database.close()


class Reading(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    label = StringField()
    recorded_at = DateTimeField()


def test_explicit_adapters_are_registered():
    """The adapters are installed at module import, not the deprecated defaults.

    `sqlite3.adapters` always holds a (datetime, PrepareProtocol) entry — the
    deprecated built-in is there too — and it emits the same ISO string, so the
    discriminator is not "is there an entry" but "does invoking it warn". Our
    explicit adapter is silent; the deprecated default warns.
    """
    import tina4_python.database.sqlite  # noqa: F401  (ensures the module is imported)

    # Python keys the adapter registry on (type, PrepareProtocol).
    assert (datetime.datetime, sqlite3.PrepareProtocol) in sqlite3.adapters
    assert (datetime.date, sqlite3.PrepareProtocol) in sqlite3.adapters

    now = datetime.datetime(2026, 7, 10, 12, 34, 56, 789000)
    today = datetime.date(2026, 7, 10)
    datetime_adapter = sqlite3.adapters[(datetime.datetime, sqlite3.PrepareProtocol)]
    date_adapter = sqlite3.adapters[(datetime.date, sqlite3.PrepareProtocol)]

    with warnings.catch_warnings():
        # The deprecated default adapter warns on invocation; ours must not.
        warnings.simplefilter("error", DeprecationWarning)
        # Our adapters produce a space-separated ISO datetime and plain ISO date.
        assert datetime_adapter(now) == "2026-07-10 12:34:56.789000"
        assert date_adapter(today) == "2026-07-10"


def test_orm_save_emits_no_datetime_adapter_deprecation(db):
    """Saving a DateTimeField row must not trip the deprecated default adapter."""
    Reading.create_table()
    when = datetime.datetime(2026, 7, 10, 12, 34, 56, 789000)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        saved = Reading({"label": "boot", "recorded_at": when}).save()

    # save() returns self (truthy) on success — a swallowed warning-as-error
    # would have made it return False, so this doubles as a "did it actually
    # write" check.
    assert saved is not False, "ORM.save() failed — the write path did not complete"
    assert not _has_adapter_deprecation(caught), (
        "SQLite datetime-adapter DeprecationWarning was emitted on the save path"
    )


def test_datetime_round_trips_through_real_sqlite(db):
    """The stored datetime reads back equal to what was written."""
    Reading.create_table()
    when = datetime.datetime(2026, 7, 10, 12, 34, 56, 789000)
    saved = Reading({"label": "roundtrip", "recorded_at": when}).save()
    assert saved is not False

    loaded = Reading.find(saved.id)
    assert loaded is not None
    # DateTimeField.validate parses the ISO string back to a datetime.
    assert isinstance(loaded.recorded_at, datetime.datetime)
    assert loaded.recorded_at == when

    # And the column is stored as ISO TEXT (no detect_types converter path).
    raw = db.fetch_one("SELECT recorded_at FROM reading WHERE id = ?", [saved.id])
    assert raw["recorded_at"] == "2026-07-10 12:34:56.789000"


def test_low_level_insert_datetime_fails_loud_without_adapter(db):
    """
    Strong negative lock-in: binding a real datetime through the fail-loud
    write path (db.insert) must NOT raise a datetime-adapter DeprecationWarning.

    Under `simplefilter("error", DeprecationWarning)` the deprecated default
    adapter would raise here on the OLD behaviour (db.insert does not swallow),
    so this genuinely fails without the explicit adapter fix.
    """
    db.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, at DATETIME)"
    )
    when = datetime.datetime(2026, 1, 2, 3, 4, 5, 600000)

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        db.insert("events", {"at": when})
        # Read back on the same fail-loud path — still no warning.
        row = db.fetch_one("SELECT at FROM events WHERE id = 1")

    assert row["at"] == "2026-01-02 03:04:05.600000"


def test_date_object_also_serialises_without_deprecation(db):
    """A plain datetime.date binds via our adapter, not the deprecated default."""
    db.execute("CREATE TABLE days (id INTEGER PRIMARY KEY AUTOINCREMENT, d DATE)")
    day = datetime.date(2026, 7, 10)

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        db.insert("days", {"d": day})
        row = db.fetch_one("SELECT d FROM days WHERE id = 1")

    assert row["d"] == "2026-07-10"
