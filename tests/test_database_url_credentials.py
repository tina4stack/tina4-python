# A percent-encoded password in a DATABASE_URL must reach the driver DECODED.
"""
`urlparse().username` and `.password` return the RAW userinfo - Python's stdlib
does not decode them. Five adapters (mysql, mssql, postgres, mongodb, firebird)
read those attributes directly, so a password containing any character that MUST
be escaped in a URL (`!`, `@`, `:`, `/`, `#`) was handed to the driver still
encoded.

The failure mode is what made this expensive: the driver reports a plain "login
failed for user X". Nothing mentions the URL, the password looks right in the
config, and the same credentials work when passed as separate arguments. It cost
four separate investigations before the cause was found.

Ruby, PHP and Node all decode on this path already - Python was the only one that
did not, and Python is the master.

NO MOCKS: the decode cases are a pure function over a string, and the live case
connects to a REAL PostgreSQL when one is configured.

Identical case names in all four frameworks:
  tina4-php/tests/DatabaseUrlCredentialsTest.php
  tina4-ruby/spec/database_url_credentials_spec.rb
  tina4-nodejs/test/databaseUrlCredentials.test.ts
"""
import os

import pytest

from tina4_python.database.database_url import DatabaseUrl, url_credentials


def test_a_percent_encoded_password_is_decoded():
    """NEGATIVE: the actual bug. This returned the raw 'TinaSQL123%21Secure'."""
    _, password = url_credentials("mssql://sa:TinaSQL123%21Secure@h:1433/db")
    assert password == "TinaSQL123!Secure"


def test_every_reserved_character_survives_a_round_trip():
    """
    These are exactly the characters that FORCE encoding in a URL, so they are
    the only ones that can expose the bug. A password with none of them works
    either way, which is why this went unnoticed.
    """
    user, password = url_credentials("postgres://us%3Aer:p%40ss%21w%3Ard%2Fx%23y@h:5432/db")
    assert user == "us:er"
    assert password == "p@ss!w:rd/x#y"


def test_an_unencoded_password_is_unchanged():
    """POSITIVE: decoding must not corrupt a password that needed no encoding."""
    _, password = url_credentials("postgres://tina4:tina4@h:5432/db")
    assert password == "tina4"


def test_a_literal_percent_in_a_password_survives():
    """
    A password containing a real '%' encodes to '%25'. Decoding once yields the
    single '%' - decoding twice would silently corrupt it.
    """
    _, password = url_credentials("postgres://u:100%25sure@h:5432/db")
    assert password == "100%sure"


def test_separate_credentials_are_used_when_the_url_has_none():
    """POSITIVE: the fallback path must keep working, and must NOT be decoded."""
    user, password = url_credentials("postgres://h:5432/db", "sa", "raw!pass")
    assert user == "sa"
    assert password == "raw!pass"


def test_the_url_wins_over_separate_credentials():
    """The documented precedence: URL > explicit arguments."""
    user, password = url_credentials("postgres://urluser:url%21pass@h:5432/db", "argu", "argp")
    assert user == "urluser"
    assert password == "url!pass"


def test_the_url_parser_and_the_adapter_helper_agree():
    """
    DatabaseUrl always decoded; the adapters did not. Two spellings of the same
    question must not give two answers - that divergence IS the bug.
    """
    url = "postgres://us%3Aer:p%40ss@h:5432/db"
    parsed = DatabaseUrl(url)
    user, password = url_credentials(url)
    assert (user, password) == (parsed.username, parsed.password)


@pytest.mark.skipif(
    not (os.environ.get("TINA4_TEST_PG_URL") or "").strip(),
    reason="live PostgreSQL not configured (TINA4_TEST_PG_URL)",
)
def test_an_encoded_password_connects_to_a_live_database():
    """
    The end-to-end proof, against a REAL server. '%61' decodes to 'a', so the
    encoded form spells the same password as the plain one: it connects only if
    the credential path decodes.
    """
    from tina4_python.database import Database

    raw = (os.environ.get("TINA4_TEST_PG_PASSWORD") or "tina4").strip()
    if "a" not in raw:
        pytest.skip("password has no 'a' to encode as %61")

    url = (os.environ["TINA4_TEST_PG_URL"] or "").strip()
    user = (os.environ.get("TINA4_TEST_PG_USERNAME") or "tina4").strip()
    # Rebuild the URL with credentials embedded, the password partly encoded.
    tail = url.split("://", 1)[1].split("@")[-1]
    encoded = raw.replace("a", "%61", 1)
    db = Database(f"{url.split('://', 1)[0]}://{user}:{encoded}@{tail}")

    assert db.table_exists("tina4_write_contract") in (True, False)
