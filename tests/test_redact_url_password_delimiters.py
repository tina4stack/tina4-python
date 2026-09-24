"""redact_url hides the WHOLE password, even when it contains ':' or '@'.

THE BUG, MEASURED on v3 (958377c): the userinfo pattern let the USER part run
up to the LAST ':' before the '@', so a password containing a colon was cut in
two and only the tail was hidden:

    postgresql://tina4:s3:cret@127.0.0.1/db  ->  postgresql://tina4:s3:***@127.0.0.1/db

The head of the password ("s3") stayed in every log line, exception and API
dump that goes through the primitive - including the "Database: could not
connect to ..." error the server logs at boot. RFC 3986 userinfo is
``user ":" password`` and the user cannot contain a ':', so the password starts
at the FIRST ':'.

Driven two ways: the primitive itself (pure logic), and the REAL connect-failure
path - a real Database() with a real PostgreSQL driver dialling a real closed
port, whose ConnectionError message is what gets logged.
"""
import socket

import pytest

from tina4_python.database.database_url import DatabaseUrl, redact_url

CASES = [
    ("postgresql://tina4:s3:cret@127.0.0.1:5432/db", "postgresql://tina4:***@127.0.0.1:5432/db", "s3:cret"),
    ("postgresql://tina4:s3@cret@127.0.0.1:5432/db", "postgresql://tina4:***@127.0.0.1:5432/db", "s3@cret"),
    ("redis://:s3:cret@127.0.0.1:6381/3", "redis://:***@127.0.0.1:6381/3", "s3:cret"),
    ("mysql://tina4:x9:y8:z7@127.0.0.1/db", "mysql://tina4:***@127.0.0.1/db", "x9:y8:z7"),
    ("odbc:///DRIVER={PostgreSQL};SERVER=h;UID=tina4;PWD=s3:cret;", "odbc:///DRIVER={PostgreSQL};SERVER=h;UID=tina4;PWD=***;", "s3:cret"),
]


@pytest.mark.parametrize("url, expected, password", CASES, ids=[c[2] + "-" + c[0].split(":")[0] for c in CASES])
def test_the_whole_password_is_redacted(url, expected, password):
    redacted = redact_url(url)
    assert redacted == expected
    # Not even the part before the password's own ':' or '@' survives.
    assert password.replace("@", ":").split(":")[0] not in redacted


def test_a_url_without_credentials_is_unchanged():
    for url in ("postgresql://127.0.0.1:5432/db", "redis://localhost:6379/0", "sqlite:///data/app.db"):
        assert redact_url(url) == url


def test_safe_string_hides_a_colon_password():
    assert "s3" not in DatabaseUrl("postgresql://tina4:s3:cret@127.0.0.1:5432/db").to_safe_string()


def _closed_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.parametrize("password", ["s3:cret", "s3@cret"])
def test_the_connect_failure_that_gets_logged_hides_the_password(password):
    pytest.importorskip("psycopg2", reason="psycopg2 not installed (uv sync --extra test)")
    from tina4_python.database import Database

    port = _closed_port()
    with pytest.raises(ConnectionError) as raised:
        Database(f"postgresql://tina4:{password}@127.0.0.1:{port}/tina4_py")
    message = str(raised.value)
    assert message.startswith(f"Database: could not connect to postgresql://tina4:***@127.0.0.1:{port}/tina4_py"), message
    assert "s3" not in message and "cret" not in message, message
