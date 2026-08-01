# The two halves of the raw-fetch row cap: the DETECTOR and the APPEND SITE.
#
# WHY THIS FILE EXISTS
#
# tests/test_row_cap_contract.py pins the CAP ITSELF -- 150 rows in, 100 rows
# back, an explicit limit overriding in both directions. The fix that landed on
# 2026-08-01 ("the row cap can no longer be defeated by a literal, an identifier
# or a comment") went in WITHOUT a dedicated test of its own, and it is two
# independent bugs wearing one coat. Each needs its own gate, because each can
# be reintroduced alone:
#
#   DETECTOR -- "does the caller's SQL already carry its own LIMIT?" used to be
#   the substring test `"LIMIT" in sql.upper().split("--")[0]`. Any identifier or
#   literal containing those five letters read as "the caller supplied their own
#   LIMIT" and NO cap was appended. MEASURED on a real 150-row SQLite table with
#   the 100-row default in force, every one of these returned ALL 150 ROWS:
#
#       SELECT * FROM t WHERE label != 'LIMIT' ORDER BY id      literal
#       SELECT * FROM t ORDER BY id -- LIMIT 5                  line comment
#       SELECT * FROM t ORDER BY id /* LIMIT 5 */               block comment
#       SELECT id, label AS rate_limit FROM t                   identifier
#
#   A column named `rate_limit` silently returning a whole table is the exact
#   production incident the cap exists to prevent.
#
#   APPEND SITE -- the `--` was stripped for DETECTION only and the clause was
#   appended to the ORIGINAL sql, so the cap landed INSIDE a trailing line
#   comment and never reached the engine. That is a bug even with a perfect
#   detector, so it is proven separately here by SQL whose trailing comment
#   contains no LIMIT at all -- the detector cannot be involved.
#
# THE NEGATIVE HALF MATTERS AS MUCH AS THE POSITIVE ONE
#
# "Fix the detector" could just mean "always append", which would break every
# caller who wrote their own LIMIT. So every positive case below is paired with
# a negative one: a REAL trailing LIMIT is still honoured (numeric, placeholder,
# OFFSET and MySQL comma forms), and a LIMIT that lives only in a SUBQUERY still
# lets the OUTER statement get its cap.
#
# NO DOUBLES. The detector cases run the pure static helpers over their inputs
# (no dependency, no stand-in). The end-to-end cases run a REAL SQLite file on
# disk through the REAL SQLiteAdapter -- `db._get_adapter()` hands back the very
# object `Database.fetch` delegates to.
import pytest

from tina4_python.database import Database
from tina4_python.database.adapter import DatabaseAdapter

ROWS = 150          # MORE than the cap, on purpose -- see test_row_cap_contract.py.
CAP = 100


# ── The detector, as a pure function over its input ──────────────────────


class TestScrubSqlTextBlanksEverythingThatIsNotSql:
    """`_scrub_sql_text` blanks literals, quoted identifiers and both comment
    forms to spaces of the SAME LENGTH, keeping newlines, so a later keyword
    search sees only real SQL at the original offsets."""

    def test_a_string_literal_is_blanked(self):
        scrubbed = DatabaseAdapter._scrub_sql_text(
            "SELECT * FROM t WHERE label != 'LIMIT' ORDER BY id"
        )
        assert "LIMIT" not in scrubbed.upper()
        assert "ORDER BY id" in scrubbed

    def test_a_quoted_identifier_is_blanked(self):
        scrubbed = DatabaseAdapter._scrub_sql_text('SELECT "rate LIMIT" FROM t')
        assert "LIMIT" not in scrubbed.upper()

    def test_a_line_comment_is_blanked(self):
        scrubbed = DatabaseAdapter._scrub_sql_text("SELECT * FROM t -- LIMIT 5")
        assert "LIMIT" not in scrubbed.upper()

    def test_a_block_comment_is_blanked(self):
        scrubbed = DatabaseAdapter._scrub_sql_text("SELECT * FROM t /* LIMIT 5 */")
        assert "LIMIT" not in scrubbed.upper()

    def test_scrubbing_preserves_length_and_newlines(self):
        # Offsets and line structure must still line up with the original,
        # otherwise an end-anchored match reads the wrong end of the statement.
        sql = "SELECT *\nFROM t -- LIMIT 5\nWHERE label != 'LIMIT'\n"
        scrubbed = DatabaseAdapter._scrub_sql_text(sql)
        assert len(scrubbed) == len(sql)
        assert scrubbed.count("\n") == sql.count("\n")

    def test_real_sql_keywords_survive_scrubbing(self):
        # The negative half of the scrubber: it must not eat actual SQL.
        sql = "SELECT * FROM t ORDER BY id LIMIT 5"
        assert DatabaseAdapter._scrub_sql_text(sql) == sql


class TestHasTrailingLimitIsNotDefeatedByTextThatMerelyContainsLimit:
    """The POSITIVE half -- every one of these MEASURED cases returned all 150
    rows before the fix, because the naive substring test said "the caller
    already has a LIMIT"."""

    @pytest.mark.parametrize("sql", [
        "SELECT * FROM t WHERE label != 'LIMIT' ORDER BY id",
        "SELECT * FROM t ORDER BY id -- LIMIT 5",
        "SELECT * FROM t ORDER BY id /* LIMIT 5 */",
        "SELECT id, label AS rate_limit FROM t",
        'SELECT id, "rate LIMIT" FROM t',
        "SELECT * FROM t WHERE note = 'ends with LIMIT 5'",
    ])
    def test_no_trailing_limit_is_detected(self, sql):
        assert DatabaseAdapter._has_trailing_limit(sql) is False, (
            f"{sql!r} has no LIMIT of its own -- the cap must still be appended"
        )

    def test_a_limit_only_in_a_subquery_is_not_a_trailing_limit(self):
        # Anchoring matters on its own, independently of scrubbing: a bare
        # "contains LIMIT" also matches a LIMIT nested in a subquery, where the
        # OUTER statement still needs its cap.
        sql = "SELECT * FROM (SELECT * FROM t ORDER BY id LIMIT 140)"
        assert DatabaseAdapter._has_trailing_limit(sql) is False


class TestHasTrailingLimitStillHonoursARealLimit:
    """The NEGATIVE half -- without it, "fixing" the detector could just mean
    always appending, which double-LIMITs every caller who wrote their own."""

    @pytest.mark.parametrize("sql", [
        "SELECT * FROM t LIMIT 5",
        "SELECT * FROM t limit 5",                 # case-insensitive
        "SELECT * FROM t LIMIT 5 OFFSET 10",
        "SELECT * FROM t LIMIT 10, 5",             # MySQL comma form
        "SELECT * FROM t LIMIT ?",                 # sqlite / mysql placeholder
        "SELECT * FROM t LIMIT $1",                # postgres numbered
        "SELECT * FROM t LIMIT :count",            # named
        "SELECT * FROM t LIMIT %s OFFSET %s",      # psycopg / mysql-connector
        "SELECT * FROM t LIMIT 5;",                # trailing semicolon
        "SELECT * FROM t LIMIT 5\n",               # trailing newline
    ])
    def test_a_real_trailing_limit_is_detected(self, sql):
        assert DatabaseAdapter._has_trailing_limit(sql) is True, (
            f"{sql!r} carries its own LIMIT -- a second one must NOT be appended"
        )

    def test_a_real_limit_followed_by_a_comment_is_still_detected(self):
        # The comment is scrubbed to spaces, so the LIMIT is still the last
        # thing in the statement.
        assert DatabaseAdapter._has_trailing_limit(
            "SELECT * FROM t LIMIT 5 -- deliberate"
        ) is True

    def test_empty_and_none_are_safe(self):
        assert DatabaseAdapter._has_trailing_limit("") is False
        assert DatabaseAdapter._has_trailing_limit(None) is False


# ── End to end, on a real SQLite file bigger than the cap ────────────────


@pytest.fixture
def db(tmp_path):
    """A real SQLite database file holding MORE rows than the cap.

    A fixture SMALLER than the cap proves nothing: 30 rows asserting 30 is what
    you get whether the cap is 100, 1000, or absent entirely.
    """
    d = Database(f"sqlite:///{tmp_path / 'row_cap_detector.db'}")
    d.execute("CREATE TABLE cap_rows (id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT)")
    d.execute_many(
        "INSERT INTO cap_rows (label) VALUES (?)",
        [[f"row{i}"] for i in range(ROWS)],
    )
    d.commit()
    assert d.fetch_one("SELECT COUNT(*) AS c FROM cap_rows")["c"] == ROWS
    yield d
    d.close()


@pytest.fixture(params=["wrapper", "adapter"])
def layer(request, db):
    """The same contract at BOTH layers that cap: Database.fetch and the REAL
    SQLiteAdapter underneath it. The layer name appears in the test id, so a red
    run says which one drifted."""
    return db.fetch if request.param == "wrapper" else db._get_adapter().fetch


def rows(result):
    """Row COUNT of what came back. `.records`, never `.count` -- count is the
    total matching rows and stays 150 whatever the cap does."""
    return len(result.records)


class TestTheCapSurvivesSqlThatMerelyMentionsLimit:
    """The four MEASURED defects, end to end. Each returned 150 before the fix."""

    def test_a_string_literal_spelling_limit_does_not_defeat_the_cap(self, layer):
        assert rows(layer(
            "SELECT * FROM cap_rows WHERE label != 'LIMIT' ORDER BY id"
        )) == CAP

    def test_a_line_comment_spelling_limit_does_not_defeat_the_cap(self, layer):
        assert rows(layer("SELECT * FROM cap_rows ORDER BY id -- LIMIT 5")) == CAP

    def test_a_block_comment_spelling_limit_does_not_defeat_the_cap(self, layer):
        assert rows(layer("SELECT * FROM cap_rows ORDER BY id /* LIMIT 5 */")) == CAP

    def test_a_column_named_rate_limit_does_not_defeat_the_cap(self, layer):
        # The production incident: an ordinary column name was enough to make
        # fetch() return an entire table.
        assert rows(layer("SELECT id, label AS rate_limit FROM cap_rows")) == CAP

    def test_the_count_probe_still_reports_the_true_total(self, layer):
        # The trailing `--` also commented out the closing paren of the COUNT
        # probe wrapper, so the probe failed, was swallowed, and the result said
        # count=0 ALONGSIDE real records. Truncated rows AND an honest total is
        # the pair a broken cap cannot fake.
        result = layer("SELECT * FROM cap_rows ORDER BY id -- LIMIT 5")
        assert rows(result) == CAP
        assert result.count == ROWS


class TestTheAppendSiteIsNotSwallowedByATrailingComment:
    """The SECOND bug, isolated. None of this SQL mentions LIMIT anywhere, so
    the detector cannot be involved -- only where the clause is written can
    fail these."""

    def test_a_trailing_line_comment_does_not_swallow_the_cap(self, layer):
        # Appended INLINE this becomes `... -- rows in id order LIMIT ? OFFSET ?`
        # and the whole clause lives inside the comment. On a NEW LINE nothing
        # can swallow it.
        assert rows(layer("SELECT * FROM cap_rows ORDER BY id -- rows in id order")) == CAP

    def test_a_bare_trailing_comment_line_does_not_swallow_the_cap(self, layer):
        assert rows(layer("SELECT * FROM cap_rows\n-- listing every row")) == CAP

    def test_a_trailing_semicolon_does_not_produce_a_cap_after_it(self, layer):
        # `SELECT ... ; LIMIT 100 OFFSET 0` is invalid on every engine. The
        # semicolon is stripped before the clause is written.
        assert rows(layer("SELECT * FROM cap_rows ORDER BY id;")) == CAP


class TestARealLimitIsStillLeftAlone:
    """The end-to-end NEGATIVE half. If the fix were "always append", every one
    of these would truncate or raise a syntax error."""

    def test_a_real_trailing_limit_above_the_cap_survives(self, layer):
        # 130 is ABOVE the default cap, so appending `LIMIT 100` would truncate
        # to 100 and appending anything at all would be a SQLite syntax error.
        assert rows(layer("SELECT * FROM cap_rows LIMIT 130")) == 130

    def test_a_real_trailing_limit_with_offset_survives(self, layer):
        assert rows(layer("SELECT * FROM cap_rows ORDER BY id LIMIT 130 OFFSET 5")) == 130

    def test_a_real_trailing_limit_in_the_mysql_comma_form_survives(self, layer):
        # SQLite accepts `LIMIT <offset>, <count>` too, so this really runs.
        assert rows(layer("SELECT * FROM cap_rows ORDER BY id LIMIT 5, 130")) == 130

    def test_a_limit_only_in_a_subquery_still_lets_the_outer_query_cap(self, layer):
        # The inner LIMIT is the caller's; the OUTER statement is uncapped and
        # must still get one. A "contains LIMIT" detector returns 140 here.
        result = layer("SELECT * FROM (SELECT * FROM cap_rows ORDER BY id LIMIT 140)")
        assert rows(result) == CAP
        assert result.count == 140
