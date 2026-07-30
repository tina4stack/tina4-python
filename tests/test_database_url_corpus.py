"""The shared DATABASE_URL corpus (feature 5 of the feature audit).

``tests/fixtures/database_url_corpus.json`` is byte-identical in all four
frameworks. One answer key, four suites: a case that passes here and fails in
Ruby is a parity bug with a name, not a difference somebody has to notice.

Core Principle 6 says a connection string means literally the same thing in
every framework. Nothing could check that before this fixture, because Python
and Ruby parsed URLs inline inside the Database constructor and could not be
asked what a URL means without opening a connection.

Pure string-to-string. No database, no socket, no driver import.
"""
import json
from pathlib import Path

import pytest

from tina4_python.database.database_url import DatabaseUrl

FIXTURE = Path(__file__).parent / "fixtures" / "database_url_corpus.json"
CORPUS = json.loads(FIXTURE.read_text(encoding="utf-8"))
FIELDS = ("engine", "host", "port", "database", "username", "password")


def _case_id(case):
    return case["name"]


class TestDatabaseUrlCorpus:
    """Every case in the shared answer key."""

    @pytest.mark.parametrize("case", CORPUS["cases"], ids=_case_id)
    def test_parses_to_the_agreed_struct(self, case):
        url = DatabaseUrl(case["url"])
        got = {field: getattr(url, field) for field in FIELDS}
        want = {field: case.get(field) for field in FIELDS}
        assert got == want

    @pytest.mark.parametrize("case", CORPUS["cases"], ids=_case_id)
    def test_to_safe_string_round_trips(self, case):
        assert DatabaseUrl(case["url"]).to_safe_string() == case["safe"]

    @pytest.mark.parametrize("case", CORPUS["cases"], ids=_case_id)
    def test_to_safe_string_never_contains_the_password(self, case):
        """A connection URL in a log is a credential leak.

        The redacted form is the only shape allowed in a log line or an error
        message, which is why __repr__ uses it too.
        """
        if case["password"] is None:
            pytest.skip("no password in this URL")
        url = DatabaseUrl(case["url"])
        assert case["password"] not in url.to_safe_string()
        assert case["password"] not in repr(url)

    @pytest.mark.parametrize("case", CORPUS["errors"], ids=_case_id)
    def test_an_unparseable_url_raises_instead_of_guessing(self, case):
        """A silent fallback to sqlite is the dangerous outcome.

        The app boots, writes to a local file, and nobody learns the real
        database was never reached.
        """
        with pytest.raises(ValueError, match="DatabaseUrl"):
            DatabaseUrl(case["url"])

    def test_every_alias_resolves_to_its_canonical_engine(self):
        for alias, canonical in CORPUS["aliases"].items():
            sample = f"{alias}:///app.db" if alias == "sqlite3" else f"{alias}://localhost/db"
            assert DatabaseUrl(sample).engine == canonical, alias

    def test_a_url_without_a_port_gets_the_engine_default(self):
        """The port is part of our contract, not the driver's business.

        A URL with no port used to yield a different struct per framework, and
        the thing hiding it was a third-party default rather than agreement.
        """
        for engine, port in CORPUS["default_ports"].items():
            if engine == "firebird":
                continue  # firebird needs a path segment; covered by the cases
            assert DatabaseUrl(f"{engine}://localhost/db").port == port, engine

    def test_engine_never_holds_an_adapter_class_name(self):
        """The D4 leak cannot come back.

        PHP used to publish `DataPostgresql` on a public property; the engine is
        a canonical name in all four now.
        """
        canonical = {"sqlite", "postgres", "mysql", "mssql", "firebird", "mongodb", "odbc"}
        for case in CORPUS["cases"]:
            engine = DatabaseUrl(case["url"]).engine
            assert engine in canonical, f"{case['name']} produced {engine!r}"

    def test_parsing_a_url_does_not_require_a_database(self):
        """The whole point of the value type: a parse with nothing to stand up.

        Before this, `tina4 doctor`, the setup wizard, and anything else wanting
        to validate a URL had nothing to call.
        """
        url = DatabaseUrl("postgres://u:p@db.internal:5432/app")
        assert url.engine == "postgres"
        assert url.dsn() == "db.internal:5432/app"
