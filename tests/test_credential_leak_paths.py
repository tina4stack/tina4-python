"""Named regression gates for the credential-exposure cluster (2026-08-02).

Every case here was REPRODUCED on this tree before the fix, not inferred from
reading the source. The defect ids match the cross-framework audit:

* C2 - a malformed TINA4_DATABASE_URL wrote the password into the exception.
* C3 - ``to_safe_string()`` existed but nothing on a real path called it: the
       invalid-URL message, the connect failure, ``/__dev/api/status`` and
       ``tina4 console`` all handled the raw URL.
* C5 - ``to_safe_string()`` returned an ODBC connection string VERBATIM, PWD=
       and all, while the negative test was green because the shared corpus had
       no odbc row.
* C6 - a dump/serialize of the value printing the password (Python already
       guarded this via __slots__ + __repr__; pinned here so it stays true).
* C7 - an EMPTY URL password meant two different things in the four frameworks,
       and the env fallback then authenticated with a different credential.

TWO HALVES, ALWAYS. For a redaction fix the negative half (the secret is gone)
is worthless on its own - a function returning "" would pass it. Every test here
also asserts the message still carries what an operator needs to FIX the fault:
the scheme, the host, the driver, the reason.

The sentinel contains a SPACE on purpose. A space is what defeated tina4-php's
``\\bpassword=\\S*`` redaction (C4) and what let a password inject extra libpq
DSN parameters (C1), so a sentinel without one would let those shapes hide.

No mocks anywhere: the connect assertions run against the real PostgreSQL, the
dev-admin assertion runs against a real child server over real HTTP, and the MCP
assertion goes through the real JSON-RPC dispatch.
"""
from __future__ import annotations

import json
import re
import pickle
import pathlib
from urllib.parse import quote
import os
import socket

import pytest

from conftest import boot_child_server
from tina4_python.database.database_url import (
    DatabaseUrl,
    redact_url,
    url_credentials,
)

# A space, so a C1/C4-shaped "stops at the first whitespace" bug cannot hide.
SENTINEL = "s3ntinel-Pa55 word"

# The live PostgreSQL. Same env-var names the rest of the suite uses so the lab
# host can repoint it; the defaults are the shared test server.
PG_HOST = os.environ.get("TINA4_TEST_PG_HOST", "192.168.88.99")
PG_PORT = int(os.environ.get("TINA4_TEST_PG_PORT", "55432"))
PG_USER = os.environ.get("TINA4_TEST_PG_USERNAME", "tina4")
PG_PASS = os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4")
PG_DB = os.environ.get("TINA4_TEST_PG_DB", "tina4_py")


def _pg_reachable() -> bool:
    try:
        with socket.create_connection((PG_HOST, PG_PORT), timeout=2.0):
            return True
    except OSError:
        return False


needs_postgres = pytest.mark.skipif(
    not _pg_reachable(),
    reason=f"PostgreSQL not reachable at {PG_HOST}:{PG_PORT}",
)


# ── C2: a malformed URL never writes the password into the exception ────────

class TestC2MalformedUrlNeverCarriesThePassword:
    """Measured before the fix::

        DatabaseUrl("notaurl-with-s3ntinel-Pa55 word")
        ValueError: DatabaseUrl: Invalid URL format 'notaurl-with-s3ntinel-Pa55 word'

    That string reaches the boot log, the crash report, the dev error overlay
    (which renders ``str(exception)``) and the CI log.
    """

    def test_a_url_with_no_scheme_does_not_echo_the_value(self):
        with pytest.raises(ValueError) as caught:
            DatabaseUrl(f"notaurl-with-{SENTINEL}")
        message = str(caught.value)

        # NEGATIVE - the credential is gone. Checked in pieces too, so a
        # partial echo ("s3ntinel-Pa55" without the tail) cannot slip through.
        assert SENTINEL not in message
        assert "s3ntinel" not in message
        assert "Pa55" not in message

        # POSITIVE - still diagnosable. It names the failure, the expected
        # shape, and itself; a redaction that says nothing is useless.
        assert "DatabaseUrl" in message
        assert "driver://" in message
        assert "scheme" in message

    def test_a_url_whose_port_is_not_a_number_reports_the_reason_not_the_url(self):
        """The stdlib raises this one lazily off ``parsed.port``.

        Its own text is safe (it names the port token only), but it does not
        identify itself as a Tina4 error, so it used to surface as a bare
        ``ValueError: Port could not be cast...`` with no clue which layer
        produced it.
        """
        with pytest.raises(ValueError) as caught:
            DatabaseUrl(f"postgres://user:{SENTINEL}@localhost:notaport/db")
        message = str(caught.value)

        assert SENTINEL not in message          # NEGATIVE
        assert "s3ntinel" not in message
        assert "DatabaseUrl" in message         # POSITIVE - ours, and it says why
        assert "notaport" in message

    def test_an_unsupported_scheme_names_the_scheme_and_the_supported_set(self):
        with pytest.raises(ValueError) as caught:
            DatabaseUrl(f"cassandra://user:{SENTINEL}@localhost:9042/keyspace")
        message = str(caught.value)

        assert SENTINEL not in message          # NEGATIVE
        assert "cassandra" in message           # POSITIVE - the exact bad scheme
        assert "postgres" in message            # ... and what it could have been

    def test_the_message_is_the_same_whatever_the_password_is(self):
        """The error must not vary with the secret.

        A message that changes shape with the credential (length, a prefix, a
        hash) leaks it by oracle even when the literal is absent.
        """
        first = str(pytest.raises(
            ValueError, DatabaseUrl, f"notaurl-{SENTINEL}").value)
        second = str(pytest.raises(
            ValueError, DatabaseUrl, "notaurl-a").value)
        assert first == second


# ── C5: to_safe_string() must redact an ODBC DSN ────────────────────────────

class TestC5OdbcConnectionStringIsRedacted:
    """Measured before the fix: ``to_safe_string()`` returned the DSN verbatim.

    The corpus negative test passed the whole time because it had no odbc row -
    the same trap as the dotenv corpus: the guard exists, the test is green, and
    the fixture has no row for the case that matters.
    """

    def test_a_pwd_keyword_is_redacted_and_the_rest_survives(self):
        url = DatabaseUrl(
            "odbc:///DRIVER={PostgreSQL};SERVER=h;DATABASE=d;UID=u;"
            f"PWD={SENTINEL};"
        )
        safe = url.to_safe_string()

        assert SENTINEL not in safe             # NEGATIVE
        assert "s3ntinel" not in safe
        assert SENTINEL not in repr(url)

        # POSITIVE - everything needed to diagnose a failed ODBC connect is
        # still there. Redacting the whole DSN would pass the negative half and
        # leave an operator with nothing.
        assert "PWD=***" in safe
        assert "DRIVER={PostgreSQL}" in safe
        assert "SERVER=h" in safe
        assert "DATABASE=d" in safe
        assert "UID=u" in safe

    def test_a_brace_quoted_password_containing_the_delimiter_is_redacted_whole(self):
        """The C1/C4 shape. Braces are what let an ODBC value hold a ``;``.

        A redactor that stops at the first ``;`` (or at the first space, which
        is exactly PHP's ``\\bpassword=\\S*``) leaves the TAIL of the password
        in the "redacted" message.
        """
        secret = "s3ntinel;Pa55 word"
        safe = DatabaseUrl(
            "odbc:///DRIVER={PostgreSQL};UID=u;"
            f"PWD={{{secret}}};DATABASE=d"
        ).to_safe_string()

        assert secret not in safe               # NEGATIVE
        assert "Pa55 word" not in safe          # ... and no tail survived
        assert "s3ntinel" not in safe
        assert "PWD=***" in safe                # POSITIVE
        assert "DATABASE=d" in safe             # the keyword AFTER it survived

    def test_a_doubled_brace_escape_inside_the_password_is_consumed(self):
        """ODBC spells a literal ``}`` as ``}}`` inside a brace-quoted value."""
        safe = redact_url("DRIVER={x};PWD={pa}}ss};DATABASE=d")

        assert "pa}}ss" not in safe             # NEGATIVE
        assert "ss}" not in safe
        assert "PWD=***" in safe                # POSITIVE
        assert "DATABASE=d" in safe

    def test_the_keyword_matches_case_insensitively_and_around_spaces(self):
        for dsn in (f"uid=u;pwd={SENTINEL};",
                    f"UID=u;Password = {SENTINEL};",
                    f"UID=u;PWD={SENTINEL}"):
            safe = redact_url(dsn)
            assert SENTINEL not in safe, dsn    # NEGATIVE
            assert "UID=u" in safe or "uid=u" in safe   # POSITIVE

    def test_a_value_with_no_credential_is_returned_unchanged(self):
        """The redactor must not mangle what it does not need to touch."""
        for harmless in ("sqlite:///data/app.db",
                         "postgres://localhost:5432/mydb",
                         "https://example.com:8080/path",
                         "/usr/local/bin:/usr/bin"):
            assert redact_url(harmless) == harmless


# ── C3: the primitive is actually ON the real paths ─────────────────────────

class TestC3TheRedactionPrimitiveIsOnTheRealPaths:
    """Before the fix ``to_safe_string`` had ZERO callers outside __repr__.

    Its own docblock called it "the ONLY form allowed in a log line" while every
    real path - the connect failure, the status dump, the console print - handled
    the raw URL.
    """

    def test_a_url_password_is_redacted_wherever_it_is_spelled(self):
        cases = {
            f"postgres://user:{SENTINEL}@h:5432/db":
                "postgres://user:***@h:5432/db",
            f"redis://:{SENTINEL}@cache:6379/0":
                "redis://:***@cache:6379/0",
            # An un-encoded '@' inside the password must not leave a tail.
            "mysql://u:p@ss@h:3306/db":
                "mysql://u:***@h:3306/db",
        }
        for raw, expected in cases.items():
            assert redact_url(raw) == expected

    @needs_postgres
    def test_a_connect_failure_names_the_target_in_its_redacted_form(self):
        """REAL PostgreSQL, real rejected authentication.

        Before the fix the driver's own error propagated untouched: correct, but
        it never said WHICH configured URL failed. The context we add is exactly
        the thing that must not carry the credential.
        """
        from tina4_python.database import Database

        with pytest.raises(ConnectionError) as caught:
            Database(f"postgres://{PG_USER}:{SENTINEL}@{PG_HOST}:{PG_PORT}/{PG_DB}")
        message = str(caught.value)

        assert SENTINEL not in message          # NEGATIVE
        assert "s3ntinel" not in message
        assert "Pa55" not in message

        # POSITIVE - host, port, database, user and the driver's own reason are
        # all still there, which is what makes the failure actionable.
        assert PG_HOST in message
        assert str(PG_PORT) in message
        assert PG_DB in message
        assert f"{PG_USER}:***@" in message
        assert "password authentication failed" in message.lower()

    def test_the_dev_admin_status_endpoint_no_longer_returns_the_raw_url(
            self, tmp_path):
        """A REAL child server, hit over REAL HTTP.

        ``GET /__dev/api/status`` returned ``os.environ["TINA4_DATABASE_URL"]``
        verbatim, so anyone who could reach the dev dashboard could read the
        production database password out of a JSON response body.

        The configured URL points at a closed port so the status handler's own
        best-effort ``Database()`` fails instantly instead of hanging on a
        connect timeout; the leak is in the env echo, not in the connection.
        """
        leaky_url = f"postgres://dbuser:{SENTINEL}@127.0.0.1:1/leakcheck"

        def write_app(project_dir, port):
            (project_dir / "app.py").write_text(
                "from tina4_python.core import run\n"
                "if __name__ == '__main__':\n"
                "    run()\n",
                encoding="utf-8",
            )

        proc, port = boot_child_server(
            tmp_path,
            write_app,
            extra_env={
                "TINA4_DEBUG": "true",
                "TINA4_DATABASE_URL": leaky_url,
                "TINA4_AUTO_MIGRATE": "false",
            },
        )
        try:
            import http.client
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
            conn.request("GET", "/__dev/api/status")
            reply = conn.getresponse()
            body = reply.read().decode("utf-8", errors="replace")
            conn.close()
        finally:
            proc.terminate()
            proc.wait(timeout=15)

        assert reply.status == 200, body

        assert SENTINEL not in body             # NEGATIVE
        assert "s3ntinel" not in body
        assert "Pa55" not in body

        # POSITIVE - the panel still tells you what it is connected to.
        payload = json.loads(body)
        assert payload["database"] == "postgres://dbuser:***@127.0.0.1:1/leakcheck"

    def test_mcp_env_list_redacts_a_password_embedded_in_a_url_valued_variable(
            self, monkeypatch):
        """Through the REAL JSON-RPC dispatch, not by calling the closure.

        ``_redact_env`` matched on the NAME only, and ``TINA4_DATABASE_URL``
        contains none of "secret/password/token/key/credential" - so its
        embedded password went over MCP in clear text.
        """
        from tina4_python.mcp import McpServer
        from tina4_python.mcp.tools import register_dev_tools

        monkeypatch.setenv("TINA4_DATABASE_URL",
                           f"postgres://dbuser:{SENTINEL}@dbhost:5432/appdb")
        monkeypatch.setenv("TINA4_CACHE_URL", f"redis://:{SENTINEL}@cache:6379/0")

        server = McpServer("/__dev/mcp-leakcheck")
        register_dev_tools(server)
        raw_reply = server.handle_message(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "env_list", "arguments": {}},
        }))

        assert SENTINEL not in raw_reply        # NEGATIVE
        assert "s3ntinel" not in raw_reply

        # POSITIVE - the variables are still listed and still readable.
        listed = json.loads(json.loads(raw_reply)["result"]["content"][0]["text"])
        assert listed["TINA4_DATABASE_URL"] == "postgres://dbuser:***@dbhost:5432/appdb"
        assert listed["TINA4_CACHE_URL"] == "redis://:***@cache:6379/0"


# ── C6: a dump of the value cannot print the password ───────────────────────

class TestC6DumpingTheValueCannotPrintThePassword:
    """Python already guarded this; the point of these is that it STAYS guarded.

    PHP prints ``[password] => pass`` from print_r/var_dump and Node emits
    ``"password":"pass"`` from JSON.stringify. Python is correct because of two
    decisions that are easy to undo by accident: ``__slots__`` (so there is no
    ``__dict__`` for a naive serializer to walk) and a ``__repr__`` built on the
    safe form.
    """

    def test_repr_str_format_and_pprint_all_use_the_safe_form(self):
        import pprint
        url = DatabaseUrl(f"postgres://user:{SENTINEL}@h:5432/db")

        for rendered in (repr(url), str(url), f"{url}", format(url),
                         pprint.pformat(url)):
            assert SENTINEL not in rendered     # NEGATIVE
            assert "user:***@h:5432/db" in rendered  # POSITIVE

    def test_there_is_no_instance_dict_for_a_naive_serializer_to_walk(self):
        """``json.dumps(vars(url))`` is the shape that leaks in Node.

        With ``__slots__`` there is no ``__dict__``, so that call raises instead
        of quietly emitting the password. Deleting ``__slots__`` would silently
        reopen it, which is why this is a test and not a comment.
        """
        url = DatabaseUrl(f"postgres://user:{SENTINEL}@h:5432/db")

        assert not hasattr(url, "__dict__")
        with pytest.raises(TypeError):
            vars(url)

    def test_an_odbc_value_is_safe_under_the_same_dump(self):
        url = DatabaseUrl(f"odbc:///DSN=Prod;UID=u;PWD={SENTINEL};")
        assert SENTINEL not in repr(url)        # NEGATIVE
        assert "DSN=Prod" in repr(url)          # POSITIVE


# ── C7: an empty password is EXPLICITLY empty, never absent ─────────────────

class TestC7EmptyPasswordIsExplicitNotAbsent:
    """Settled 2026-08-02: ``user:@host`` means an explicitly-empty password.

    Every framework's docblock already said absent and blank differ; python and
    node parsed null anyway, so the env fallback fired and the SAME .env
    authenticated with two different passwords depending on the framework.
    """

    def test_an_empty_url_password_parses_as_empty_not_none(self):
        url = DatabaseUrl("postgres://user:@localhost:5432/db")
        assert url.password == ""               # POSITIVE - explicitly empty
        assert url.password is not None         # NEGATIVE - not "absent"
        assert url.username == "user"

    def test_no_password_at_all_still_parses_as_absent(self):
        """The other half of the distinction - it must not collapse the other way."""
        url = DatabaseUrl("postgres://readonly@localhost:5432/db")
        assert url.password is None

    def test_the_env_fallback_does_not_fire_for_an_empty_url_password(
            self, monkeypatch):
        monkeypatch.setenv("TINA4_DATABASE_URL", "postgres://user:@localhost:5432/db")
        monkeypatch.setenv("TINA4_DATABASE_PASSWORD", SENTINEL)

        url = DatabaseUrl.from_env()
        assert url.password == ""               # NEGATIVE - env did NOT win

    def test_the_env_fallback_still_fires_when_the_url_has_no_password(
            self, monkeypatch):
        monkeypatch.setenv("TINA4_DATABASE_URL", "postgres://user@localhost:5432/db")
        monkeypatch.setenv("TINA4_DATABASE_PASSWORD", SENTINEL)

        url = DatabaseUrl.from_env()
        assert url.password == SENTINEL         # POSITIVE - documented fallback intact

    def test_url_credentials_keeps_an_empty_url_password_over_the_argument(self):
        """``url_credentials`` is the CONNECT path - five adapters call it."""
        _, password = url_credentials("postgres://user:@h:5432/db", "u", SENTINEL)
        assert password == ""                   # NEGATIVE - argument did not win

        _, fallback = url_credentials("postgres://user@h:5432/db", "u", SENTINEL)
        assert fallback == SENTINEL             # POSITIVE - fallback still works

    @needs_postgres
    def test_live_an_empty_url_password_does_not_authenticate_with_the_env_one(
            self, monkeypatch):
        """The code path that actually authenticates, against real PostgreSQL.

        The two outcomes are distinguishable on the wire, which is what makes
        this a gate rather than a smoke test:

          * BUG   - the empty URL password is treated as absent, the fallback
                    fires, psycopg2 sends the sentinel, and the server answers
                    "password authentication failed for user".
          * FIXED - the empty URL password is sent as-is and the server answers
                    "fe_sendauth: no password supplied".
        """
        from tina4_python.database import Database

        monkeypatch.setenv("TINA4_DATABASE_PASSWORD", SENTINEL)

        with pytest.raises(ConnectionError) as caught:
            Database(f"postgres://{PG_USER}:@{PG_HOST}:{PG_PORT}/{PG_DB}",
                     password=SENTINEL)
        message = str(caught.value)

        # POSITIVE - the EMPTY password reached the server, not the fallback.
        assert "no password supplied" in message.lower()
        assert "password authentication failed" not in message.lower()
        # NEGATIVE - and the fallback credential is nowhere in the message.
        assert SENTINEL not in message
        assert "s3ntinel" not in message
        assert PG_HOST in message               # still names the target

    @needs_postgres
    def test_live_a_real_url_password_still_connects_with_a_wrong_env_password(self):
        """POSITIVE half: "the URL wins" precedence is intact, on a real server."""
        from tina4_python.database import Database

        db = Database(f"postgres://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{PG_DB}",
                      password=SENTINEL)
        try:
            row = db.fetch_one("SELECT 1 AS ok")
            assert row["ok"] == 1
        finally:
            db.close()


class TestTheFidelityBoundaryIsEnforced:
    """DISPLAY REDACTS, FIDELITY DOES NOT - and nothing may persist the object.

    MEASURED 2026-08-03 with two sentinels (one containing a SPACE, one a quote,
    a double quote, a backslash and a percent): repr(), str(), to_safe_string(),
    the exception message, traceback.format_exc() and repr(exception) are ALL
    clean, and a connect failure reports
    ``postgres://tina4:***@host:5432/db`` - redacted but still naming the exact
    connection that refused, which is the point.

    ``pickle.dumps()`` still emits the password in full, and that is deliberate.
    Its contract is a faithful round trip; a masked pickle would restore an
    object whose password is the literal "***", which is a worse bug than the
    disclosure. tina4-php reaches the identical boundary with serialize() and
    var_export(), so this is PARITY rather than a divergence.

    That rule is only safe while nothing PERSISTS one of these objects - a
    DatabaseUrl pickled into a cache, a session, a queue payload or a
    multiprocessing hand-off puts a cleartext credential on disk or on a wire.
    This is the guard that keeps it true, ported from tina4-php's
    DatabaseCredentialLeakTest so the protection exists in both, not just the
    behaviour.
    """

    #: Persistence calls that would carry the secret out of the process.
    _PERSIST = re.compile(r"\b(pickle\.dumps?|pickle\.dump|copyreg|__reduce__)\s*\(")
    #: ...applied to something that looks like a connection URL.
    _URLISH = re.compile(r"\b(db_?url|database_?url|conn_?url|dsn)\b", re.IGNORECASE)

    def _offenders(self) -> list[str]:
        root = pathlib.Path(__file__).resolve().parent.parent / "tina4_python"
        found = []
        for path in sorted(root.rglob("*.py")):
            try:
                src = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for n, line in enumerate(src.splitlines(), 1):
                if self._PERSIST.search(line) and self._URLISH.search(line):
                    found.append(f"{path.relative_to(root)}:{n}  {line.strip()}")
        return found

    def test_no_framework_code_pickles_a_database_url(self):
        offenders = self._offenders()
        assert offenders == [], (
            "pickling a DatabaseUrl writes the PASSWORD verbatim - pickle keeps the "
            "secret on purpose so the round trip stays faithful. Persisting one puts a "
            "credential on disk or on a wire. Record to_safe_string() instead:\n  - "
            + "\n  - ".join(offenders)
        )

    def test_the_scanner_detects_an_offending_line(self):
        """Negative case - proves the guard has TEETH.

        A regex that silently stopped matching would leave the test above green
        and guarding nothing. tina4-php's ClassCollection guard passed VACUOUSLY
        this week for exactly that reason, so the scanner is fed the shape it
        must catch and a shape it must not.
        """
        offending = "        blob = pickle.dumps(db_url)"
        innocent = "        blob = json.dumps(db_url.to_safe_string())"

        def matches(line: str) -> bool:
            return bool(self._PERSIST.search(line) and self._URLISH.search(line))

        assert matches(offending), "the scanner must flag pickle.dumps(db_url)"
        assert not matches(innocent), "the scanner must not flag a redacted render"

    def test_pickle_really_does_carry_the_password(self):
        """The premise the guard rests on, measured rather than assumed.

        If a future change made pickle redact, this fails and the guard above
        becomes unnecessary - better to be told than to keep enforcing a rule
        whose reason has gone.
        """
        secret = "s3ntinel-Pa55 word"
        url = DatabaseUrl("postgres://user:" + quote(secret, safe="") + "@h:5432/db")

        assert "s3nt" in str(pickle.dumps(url)), (
            "pickle no longer carries the password - re-read the boundary rule, "
            "the persistence guard may no longer be needed"
        )
        # ...while every DISPLAY surface stays clean.
        for rendered in (repr(url), str(url), url.to_safe_string()):
            assert "s3nt" not in rendered

