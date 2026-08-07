"""Feature 18 (paginated results) - the ADR-0043 wire contract.

Gate for /Users/andrevanzuydam/IdeaProjects/tina4-documentation/plan/v3/fixtures/pagination_contract.json
(5 invariants) and the settled decision in
/Users/andrevanzuydam/IdeaProjects/tina4-documentation/plan/v3/decisions/ADR-0043.md.

The canonical `DatabaseResult.to_paginate()` takes NO arguments and derives every
field from the query that ran. The envelope is EXACTLY seven snake_case keys:
records, total, page, per_page, total_pages, limit, offset. No `data`/`count`
aliases, no camelCase `totalPages`, no duplicate spellings.

Every test drives a REAL SQLite database (no mocks, no doubles) with a 250-row
table, so page 3 of 13 (limit=20 offset=40) is observable end to end: the rows
come back from the engine, .count is the engine's own COUNT probe, and the
envelope is asserted against that live read.

Each test name normalises (lowercase, strip non-alphanumerics, strip a leading
"test") to contain its invariant id from the fixture verbatim.
"""
import pytest

from tina4_python.database import Database

# The whole contract, in one place: the exact seven snake_case keys the envelope
# must carry in all four frameworks, and the spellings that ADR-0043 removed.
CANONICAL_KEYS = {"records", "total", "page", "per_page", "total_pages", "limit", "offset"}
REMOVED_ALIASES = {"data", "count", "totalPages", "perPage", "has_next", "has_prev"}

ROW_COUNT = 250          # so page 3 of 13 is a real page in the middle of the set
PER_PAGE = 20            # limit
PAGE_3_OFFSET = 40       # floor(40 / 20) + 1 == page 3


@pytest.fixture
def db(tmp_path):
    """A real SQLite database holding 250 rows (ids 1..250), ordered.

    tmp_path gives a real file per test; nothing here is mocked. Rows are
    inserted 1..250 so a page-3 read (offset 40, limit 20) returns ids 41..60
    and the assertions can pin the exact rows, not just their count.
    """
    database = Database(f"sqlite:///{tmp_path / 'pagination.db'}")
    database.execute("CREATE TABLE widgets (id INTEGER PRIMARY KEY, label TEXT NOT NULL)")
    for row_id in range(1, ROW_COUNT + 1):
        database.execute("INSERT INTO widgets (id, label) VALUES (?, ?)", [row_id, f"widget-{row_id}"])
    database.commit()
    yield database
    database.close()


def _page_3(database):
    """Fetch page 3 for real: limit 20, offset 40, over the whole 250-row set."""
    return database.fetch("SELECT * FROM widgets ORDER BY id", limit=PER_PAGE, offset=PAGE_3_OFFSET)


def _whole_set(database):
    """Fetch the entire 250-row set (records == count), for the no-arguments test.

    A whole-set result is the case the old code sliced in memory WITHOUT raising,
    so it is the honest proof that an argument is now rejected outright rather
    than silently reinterpreted.
    """
    return database.fetch("SELECT * FROM widgets ORDER BY id", limit=ROW_COUNT + 10, offset=0)


# ── invariant: paginate-takes-no-arguments ───────────────────────────────────
def test_paginate_takes_no_arguments(db):
    """to_paginate() takes no arguments; passing one RAISES, never silently slices.

    Exercised on a WHOLE-set result: the old (page, per_page) form sliced this in
    memory and returned an envelope with no error, so a raise here is a real
    behaviour change, not the old partial-result guard firing.
    """
    result = _whole_set(db)
    assert len(result.records) == ROW_COUNT and result.count == ROW_COUNT

    # No-argument call is the only valid call, and it works.
    assert result.to_paginate()["total"] == ROW_COUNT

    # Every argument shape is rejected: keyword, positional, and a single kwarg.
    with pytest.raises(TypeError):
        result.to_paginate(page=2, per_page=10)
    with pytest.raises(TypeError):
        result.to_paginate(2)
    with pytest.raises(TypeError):
        result.to_paginate(per_page=10)


# ── invariant: paginate-page-is-derived-from-the-offset ───────────────────────
def test_paginate_page_is_derived_from_the_offset(db):
    """page = floor(offset / limit) + 1. A limit=20 offset=40 fetch reports page 3."""
    envelope = _page_3(db).to_paginate()
    assert envelope["page"] == 3, "offset 40 / limit 20 is page 3, not page 1"
    assert envelope["per_page"] == PER_PAGE
    assert envelope["limit"] == PER_PAGE
    assert envelope["offset"] == PAGE_3_OFFSET
    assert envelope["total_pages"] == 13, "ceil(250 / 20) == 13"


# ── invariant: paginate-total-is-the-true-total ───────────────────────────────
def test_paginate_total_is_the_true_total(db):
    """total is the true COUNT for the filter (250), never the rows returned (20)."""
    envelope = _page_3(db).to_paginate()
    assert envelope["total"] == ROW_COUNT
    assert envelope["total"] != len(envelope["records"]), (
        "total must be the whole-set count, not this page's row count"
    )


# ── invariant: paginate-records-are-the-rows-the-query-returned ───────────────
def test_paginate_records_are_the_rows_the_query_returned(db):
    """records are the 20 rows the query returned, VERBATIM, never re-sliced.

    A re-slice by the absolute offset (40) into this 20-row page would return
    NOTHING - the measured Ruby defect. All 20 rows, ids 41..60, must be present.
    """
    envelope = _page_3(db).to_paginate()
    assert len(envelope["records"]) == PER_PAGE
    assert [row["id"] for row in envelope["records"]] == list(range(41, 61))


# ── invariant: paginate-key-set-is-identical-in-all-four ──────────────────────
def test_paginate_key_set_is_identical_in_all_four(db):
    """The envelope is EXACTLY the seven snake_case keys, no aliases, no camelCase."""
    envelope = _page_3(db).to_paginate()

    assert set(envelope.keys()) == CANONICAL_KEYS
    assert len(envelope) == 7, "no extra keys, and no duplicate spelling of any concept"

    # Every removed alias is gone: no data/count/totalPages/perPage/has_next/has_prev.
    assert REMOVED_ALIASES.isdisjoint(envelope.keys())

    # Every key is snake_case (lowercase, no camelCase carried over).
    assert all(key == key.lower() for key in envelope), envelope.keys()
