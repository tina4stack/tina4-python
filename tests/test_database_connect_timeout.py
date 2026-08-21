# Regression tests for TINA4_DATABASE_CONNECT_TIMEOUT — the bounded connect.
"""
A database connect that can block forever hangs the application with no log, no
error and no signal: the worker just sits there at 0% CPU. Measured in the Node
sibling, a Firebird driver that never called back sat for 16 MINUTES.

WHAT MAKES THESE TESTS REAL
---------------------------
No mocks, stubs, fakes, spies or monkeypatching. The blocking peer is
:class:`BlackHoleServer` — an ordinary listening socket that accepts the TCP
connection and then never writes a byte. That is not a test double for a
database; it is what a wedged server actually looks like on the wire, and it is
the ONLY way to reproduce this failure locally.

A closed port is NOT a substitute: it answers instantly with ECONNREFUSED, so a
test pointed at one passes with or without the fix and proves nothing. There is
a named test below that pins exactly that distinction.

Env vars are set on the real ``os.environ`` the framework reads (via
:func:`connect_timeout_env`), never via monkeypatch — the framework's own
configuration path is exercised, not replaced.
"""
import contextlib
import os
import re
import socket
import threading
import time

import pytest

from tina4_python.database.adapter import (
    CONNECT_TIMEOUT_VARIABLE,
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DatabaseConnectTimeout,
    bound_was_reached,
    call_with_deadline,
    driver_connect_timeout_seconds,
    resolve_connect_timeout,
)
from tina4_python.database.firebird import FirebirdAdapter
from tina4_python.database.mssql import MSSQLAdapter
from tina4_python.database.mysql import MySQLAdapter
from tina4_python.database.postgres import PostgreSQLAdapter

# Short enough to keep the suite quick, long enough that a healthy loopback
# connect could never be mistaken for an expiry.
TEST_BOUND_SECONDS = 2

# How long a bounded connect is allowed to overshoot before we call it unbounded.
# Generous: a loaded CI box schedules threads late, and the point of the
# assertion is "seconds, not minutes".
OVERSHOOT_ALLOWANCE_SECONDS = 10


class BlackHoleServer:
    """A REAL TCP server that accepts a connection and then never replies.

    Nothing here stands in for a driver or a database — it is a listening
    socket. Clients complete the TCP handshake and then block forever waiting
    for a protocol greeting that never comes, which is precisely the hang this
    feature exists to bound.

    :meth:`close` shuts the accepted sockets first. That FIN releases any client
    still blocked inside a driver, so an intentionally-unbounded connect started
    by a test gets reaped instead of leaked.
    """

    def __init__(self):
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(16)
        self.host, self.port = self._listener.getsockname()
        self._accepted: list[socket.socket] = []
        self._accepted_lock = threading.Lock()
        self._accept_thread = threading.Thread(
            target=self._accept_forever, name="black-hole-accept", daemon=True
        )
        self._accept_thread.start()

    def _accept_forever(self):
        while True:
            try:
                connection, _ = self._listener.accept()
            except OSError:  # listener closed — the loop's exit signal
                return
            with self._accepted_lock:
                self._accepted.append(connection)  # hold it open, say nothing

    def close(self):
        with self._accepted_lock:
            for connection in self._accepted:
                with contextlib.suppress(OSError):
                    connection.close()
            self._accepted.clear()
        with contextlib.suppress(OSError):
            self._listener.close()
        self._accept_thread.join(timeout=5)


@pytest.fixture
def black_hole():
    """A live accept-and-never-reply server, torn down (and its clients freed)."""
    server = BlackHoleServer()
    try:
        yield server
    finally:
        server.close()


@contextlib.contextmanager
def connect_timeout_env(value):
    """Set the REAL env var the framework reads, then restore it exactly.

    Not a mock: this configures the genuine configuration path. ``None`` means
    unset the variable.
    """
    previous = os.environ.get(CONNECT_TIMEOUT_VARIABLE)
    if value is None:
        os.environ.pop(CONNECT_TIMEOUT_VARIABLE, None)
    else:
        os.environ[CONNECT_TIMEOUT_VARIABLE] = str(value)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(CONNECT_TIMEOUT_VARIABLE, None)
        else:
            os.environ[CONNECT_TIMEOUT_VARIABLE] = previous


def assert_bound_fired(excinfo, elapsed, host, port):
    """The contract for an expiry: host, port, elapsed seconds, and the variable.

    A bare driver timeout message names none of these, which is why the wrapper
    exists -- an operator has to be able to tell "our bound fired" apart from
    "the database rejected us" from the message alone.
    """
    message = str(excinfo.value)
    assert str(host) in message, message
    assert str(port) in message, message
    assert CONNECT_TIMEOUT_VARIABLE in message, message
    assert "timed out after" in message, message

    # The elapsed seconds are real, not a hardcoded zero and not a restatement
    # of the configured bound label. Extract the wrapper's OWN reported elapsed
    # from the message (formatted "N.Ns") and hold IT to the bounds -- comparing
    # the OUTER clock to the message drifts on drivers whose error propagation
    # adds cleanup time (mysql-connector adds ~0.7s after aborting), and that
    # gap is not a framework bug: the wrapper's clock stops the moment the
    # driver raises, before Python-level exception unwinding.
    match = re.search(r"timed out after (\d+\.\d+)s", message)
    assert match, f"message must format the reported elapsed as 'N.Ns': {message}"
    reported = float(match.group(1))
    assert reported >= TEST_BOUND_SECONDS, (
        f"reported elapsed {reported}s < configured bound {TEST_BOUND_SECONDS}s "
        f"-- the wrapper fired EARLY: {message}"
    )
    assert reported <= elapsed + 0.05, (
        f"reported elapsed {reported}s > outer clock {elapsed:.2f}s + 0.05 -- "
        f"the wrapper cannot report a time that is later than the test's own "
        f"stopwatch: {message}"
    )
    assert elapsed >= TEST_BOUND_SECONDS, f"outer clock fired EARLY at {elapsed:.2f}s"
    assert elapsed < TEST_BOUND_SECONDS + OVERSHOOT_ALLOWANCE_SECONDS, (
        f"outer clock took {elapsed:.2f}s -- the bound did not fire"
    )


def connect_and_time(adapter, url):
    """Run a connect that is expected to raise; return (excinfo, elapsed)."""
    started = time.monotonic()
    with pytest.raises(DatabaseConnectTimeout) as excinfo:
        adapter.connect(url)
    return excinfo, time.monotonic() - started


# ── The bound fires: every blocking adapter, against a real wedged server ──


def test_postgres_connect_is_bounded_against_a_black_hole_server(black_hole):
    """psycopg2/libpq connect_timeout — bounded, and the error names the bound."""
    with connect_timeout_env(TEST_BOUND_SECONDS):
        excinfo, elapsed = connect_and_time(
            PostgreSQLAdapter(),
            f"postgresql://u:p@{black_hole.host}:{black_hole.port}/d",
        )
    assert_bound_fired(excinfo, elapsed, black_hole.host, black_hole.port)


def test_mysql_connect_is_bounded_against_a_black_hole_server(black_hole):
    """mysql-connector connection_timeout — bounded through the handshake read."""
    with connect_timeout_env(TEST_BOUND_SECONDS):
        excinfo, elapsed = connect_and_time(
            MySQLAdapter(),
            f"mysql://u:p@{black_hole.host}:{black_hole.port}/d",
        )
    assert_bound_fired(excinfo, elapsed, black_hole.host, black_hole.port)


def test_mssql_connect_is_bounded_against_a_black_hole_server(black_hole):
    """pymssql needs the watchdog: its own login_timeout does NOT cover this.

    MEASURED (Ubuntu 24.04, pymssql 2.3.13): against this same accept-and-never-
    reply server, login_timeout=2, timeout=2 and both together all failed to
    return and were killed at 25s. If this test is ever "simplified" back to
    login_timeout alone it will hang, not fail.
    """
    with connect_timeout_env(TEST_BOUND_SECONDS):
        excinfo, elapsed = connect_and_time(
            MSSQLAdapter(),
            f"mssql://u:p@{black_hole.host}:{black_hole.port}/d",
        )
    assert_bound_fired(excinfo, elapsed, black_hole.host, black_hole.port)


def test_firebird_connect_is_bounded_against_a_black_hole_server(black_hole):
    """Firebird has NO native connect timeout — the watchdog thread is the bound.

    This is the adapter the whole feature exists for: the measured 16-minute
    hang in the Node sibling was a Firebird driver that never called back.
    """
    with connect_timeout_env(TEST_BOUND_SECONDS):
        excinfo, elapsed = connect_and_time(
            FirebirdAdapter(),
            f"firebird://SYSDBA:masterkey@{black_hole.host}:{black_hole.port}//tmp/nope.fdb",
        )
    assert_bound_fired(excinfo, elapsed, black_hole.host, black_hole.port)


# ── The framework's message must win, not the driver's ──


@pytest.mark.parametrize("adapter_class,scheme", [
    (PostgreSQLAdapter, "postgresql"),
    (MySQLAdapter, "mysql"),
], ids=["postgres", "mysql"])
def test_framework_message_wins_over_the_drivers_own_timeout_message(
    black_hole, adapter_class, scheme
):
    """These two adapters rely on the DRIVER's own timer, set to the SAME value.

    That means the driver reaches its deadline and raises first — by design.
    The bound is useless to an operator if what surfaces is libpq's "timeout
    expired" or mysql-connector's "Lost connection", because neither names
    TINA4_DATABASE_CONNECT_TIMEOUT and neither tells them what to change.

    So this asserts on the MESSAGE, not on the timing: a test that only checks
    "it failed within N seconds" passes happily while the operator gets the
    driver's message.

    It also asserts the driver's own error survives as __cause__. Nothing is
    hidden — the framework adds the tuning knob on top of the real diagnosis.
    """
    url = f"{scheme}://u:p@{black_hole.host}:{black_hole.port}/d"
    with connect_timeout_env(TEST_BOUND_SECONDS):
        with pytest.raises(DatabaseConnectTimeout) as excinfo:
            adapter_class().connect(url)

    message = str(excinfo.value)
    assert CONNECT_TIMEOUT_VARIABLE in message, message
    assert str(black_hole.host) in message and str(black_hole.port) in message, message
    assert excinfo.value.__cause__ is not None, (
        "the driver's own error was discarded — keep it as __cause__"
    )
    assert not isinstance(excinfo.value.__cause__, DatabaseConnectTimeout)


def test_driver_option_is_strictly_longer_than_the_configured_bound():
    """The invariant that makes the wrapper work — and it has to be STRICT.

    This wrapper runs no competing countdown. It waits for the driver to abort
    at the DRIVER's deadline and then restates that failure in the framework's
    words. For that to happen the driver's deadline has to land AFTER ours,
    which means its option must be strictly greater than our bound — not merely
    not-shorter.

    ``ceil`` gave equality for every whole-second bound, and the shipped
    default is whole. Equality is not separation: both deadlines sat on the
    same instant, and which message reached the caller came down to which clock
    moved first. An assertion of ``>=`` passes with that bug still in place,
    which is exactly why this one asserts ``>``.
    """
    for configured in (0.2, 0.5, 1.0, 1.4, 2.0, 2.5, 9.99, 10.0, 30.0):
        option = driver_connect_timeout_seconds(configured)
        assert option > configured, (
            f"a bound of {configured}s got a driver option of {option}s — the "
            f"driver can abort at or before our own deadline"
        )


# ── The bound counts as reached on EITHER clock, because the driver uses the other ──


def test_bound_reached_on_the_monotonic_reading_is_a_timeout():
    """The ordinary case: the clocks agree and monotonic alone settles it."""
    assert bound_was_reached(2.0, 2.0, 2.0)
    assert bound_was_reached(2.5, 2.5, 2.0)


def test_bound_reached_on_the_realtime_reading_alone_is_still_a_timeout():
    """The case that was leaking the driver's own message to operators.

    libpq measures its ``connect_timeout`` with ``gettimeofday`` —
    CLOCK_REALTIME — while a duration in Python belongs on
    ``time.monotonic()``. NTP slews and steps realtime and never touches
    monotonic, so realtime can reach the bound while a monotonic reading over
    the very same connect is still short of it. By then the driver has already
    aborted; returning False here hands the caller libpq's "timeout expired",
    which names nothing they can tune.

    The numbers are the ones measured against a real wedged PostgreSQL socket
    with the two clocks made to diverge: the driver gave up 1.56s into a 2s
    bound, by which time realtime had run on to 2.03s.
    """
    assert bound_was_reached(1.56, 2.03, 2.0)


def test_a_backward_realtime_step_cannot_hide_a_real_timeout():
    """Why the monotonic reading stays in the comparison.

    A backward step leaves the realtime reading small, or negative. Trusting
    realtime alone would then swallow an expiry that really did take the whole
    bound — so the comparison keeps both and takes the larger.
    """
    assert bound_was_reached(2.01, -30.0, 2.0)


def test_a_failure_faster_than_the_bound_is_a_timeout_on_neither_clock():
    """A refusal, bad credentials, an unknown database.

    These arrive in milliseconds on both clocks and have to be re-raised
    untouched: dressing one up as an expiry sends an operator hunting a network
    stall that never happened.
    """
    assert not bound_was_reached(0.001, 0.001, 2.0)
    assert not bound_was_reached(1.999, 1.999, 2.0)


def test_an_unbounded_connect_is_never_reported_as_a_timeout():
    """``TINA4_DATABASE_CONNECT_TIMEOUT=0`` means wait forever.

    With no bound there is nothing a failure can have exceeded, however long it
    took, so the driver's own error must survive untranslated.
    """
    assert not bound_was_reached(9999.0, 9999.0, None)


# ── NEGATIVE: a fast failure must NOT be dressed up as a timeout ──


def test_connection_refused_is_not_reported_as_a_timeout():
    """A closed port fails instantly — that is a refusal, not an expiry.

    The distinction matters twice over. Operationally, reporting ECONNREFUSED as
    a timeout would send an operator hunting a network stall that never
    happened. And methodologically, a closed port is what a careless version of
    these tests would point at — it would "pass" with the bound removed. This
    test pins the difference.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    # `probe` is closed here: nothing is listening on closed_port.

    with connect_timeout_env(TEST_BOUND_SECONDS):
        started = time.monotonic()
        with pytest.raises(Exception) as excinfo:
            PostgreSQLAdapter().connect(f"postgresql://u:p@127.0.0.1:{closed_port}/d")
        elapsed = time.monotonic() - started

    assert not isinstance(excinfo.value, DatabaseConnectTimeout), (
        f"a refused connection was mis-reported as a timeout: {excinfo.value}"
    )
    assert elapsed < TEST_BOUND_SECONDS, (
        f"a closed port took {elapsed:.2f}s — it should refuse instantly"
    )


# ── NEGATIVE: <= 0 really restores the old unbounded behaviour ──


def test_zero_restores_an_unbounded_connect(black_hole):
    """``0`` means wait forever — the documented escape hatch, proven behaviourally.

    The wait MUST outlast the DEFAULT bound, not merely the short bound the other
    tests use. If it only waited ~8s, a regression that made ``0`` fall back to
    the 10s default would leave the connect raising at 10s — after the deadline
    had already passed — and this test would still go green. That is a ghost:
    it would look like coverage while being unable to fail. Waiting past 10s is
    what makes it a real gate.

    Deliberately BEHAVIOURAL only — it makes no assertion about
    ``resolve_connect_timeout`` (that is
    :func:`test_zero_disables_the_bound_in_the_resolver`'s job). Keeping the two
    apart is what lets a mutation prove this one: with a resolver assertion here
    as well, breaking the resolver would fail at the first line and the timing
    half would never run, so its gate would stay unproven.

    Closing the black hole afterwards frees the worker, so the test reaps what
    it started.
    """
    unbounded_proof_wait = DEFAULT_CONNECT_TIMEOUT_SECONDS + 3

    finished = threading.Event()

    def connect_until_released():
        try:
            PostgreSQLAdapter().connect(
                f"postgresql://u:p@{black_hole.host}:{black_hole.port}/d"
            )
        except Exception:
            pass  # we care WHEN it returns, not how
        finished.set()

    with connect_timeout_env(0):
        worker = threading.Thread(target=connect_until_released, daemon=True)
        worker.start()
        still_blocked = not finished.wait(unbounded_proof_wait)

    assert still_blocked, (
        f"the connect returned within {unbounded_proof_wait:g}s even though the bound "
        f"was disabled — <= 0 no longer restores the old unbounded behaviour "
        f"(a fall back to the {DEFAULT_CONNECT_TIMEOUT_SECONDS:g}s default looks exactly like this)"
    )

    # Reap it: the FIN from closing the accepted socket unblocks the driver.
    black_hole.close()
    assert finished.wait(30), "the unbounded connect did not unblock when the peer closed"
    worker.join(timeout=5)
    assert not worker.is_alive()


def test_zero_disables_the_bound_in_the_resolver():
    """The resolver half of the <= 0 contract, separate from the behavioural half."""
    with connect_timeout_env(0):
        assert resolve_connect_timeout() is None


def test_negative_value_restores_an_unbounded_connect():
    """Any value <= 0 disables the bound, not just exactly zero."""
    with connect_timeout_env(-5):
        assert resolve_connect_timeout() is None


# ── Resolver contract: default, garbage, rounding ──


def test_default_bound_is_ten_seconds_when_unset():
    with connect_timeout_env(None):
        assert resolve_connect_timeout() == DEFAULT_CONNECT_TIMEOUT_SECONDS == 10.0


def test_blank_value_uses_the_default():
    with connect_timeout_env("   "):
        assert resolve_connect_timeout() == DEFAULT_CONNECT_TIMEOUT_SECONDS


def test_garbage_value_falls_back_to_the_default_rather_than_waiting_forever():
    """A typo is not a choice.

    ``<= 0`` is the deliberate way to ask for unbounded; ``"ten"`` is a mistake.
    Treating garbage as unbounded would hand an operator who fat-fingered the
    value the exact hang they configured the variable to prevent.
    """
    for garbage in ("ten", "10s", "abc", "1,5"):
        with connect_timeout_env(garbage):
            assert resolve_connect_timeout() == DEFAULT_CONNECT_TIMEOUT_SECONDS, garbage


def test_fractional_bound_is_rounded_up_for_whole_second_driver_options():
    """Rounding DOWN would let a driver fire before our own bound was reached,
    surfacing a bare driver error instead of one naming the variable."""
    with connect_timeout_env("2.5"):
        assert resolve_connect_timeout() == 2.5
        assert driver_connect_timeout_seconds(2.5) == 3
    assert driver_connect_timeout_seconds(None) is None
    # Never round a positive bound down to a zero option, which most drivers
    # read as "no timeout".
    assert driver_connect_timeout_seconds(0.2) == 1


def test_an_abandoned_connect_closes_the_connection_it_eventually_opened():
    """A watchdog expiry must not leak a live database session.

    When the bound fires, the worker thread is abandoned mid-connect. If that
    worker later SUCCEEDS, nobody is holding the result — and an unheld database
    connection is a server-side session that never gets closed. The thread leak
    is bounded (one per expiry, and it ends when the peer answers); a session
    leak is not, so the abandoned worker has to close what it opened.

    The resource here is a REAL socket to a REAL listening server, opened after
    the bound has already expired.
    """
    server = BlackHoleServer()
    try:
        opened = []

        def slow_connect():
            time.sleep(1.5)  # outlive the bound below, then succeed anyway
            connection = socket.create_connection((server.host, server.port))
            opened.append(connection)
            return connection

        with pytest.raises(TimeoutError):
            call_with_deadline(slow_connect, 0.5)

        deadline = time.monotonic() + 15
        while not opened and time.monotonic() < deadline:
            time.sleep(0.05)
        assert opened, "the abandoned worker never completed"

        # socket.close() sets fileno() to -1.
        while opened[0].fileno() != -1 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert opened[0].fileno() == -1, (
            "the abandoned connection was left open — that is a leaked session"
        )
    finally:
        server.close()


# ── ODBC endpoint parsing ──
#
# The ODBC adapter's connect IS bounded (SQL_ATTR_LOGIN_TIMEOUT plus the same
# watchdog mssql needs), but it cannot be exercised live here: this project
# deliberately provisions no ODBC service, and pyodbc cannot even import without
# the system unixODBC library (see the note in tests/conftest.py). What IS
# testable without any dependency is the pure function that decides what an
# expiry message may say — and it is security-relevant, because an ODBC
# connection string carries UID= and PWD= that must never reach an exception.

def test_odbc_endpoint_is_read_from_the_connection_string():
    from tina4_python.database.odbc import _odbc_server_and_port

    assert _odbc_server_and_port("DRIVER={x};SERVER=db.example.com,1433;DATABASE=d") == \
        ("db.example.com", "1433")
    assert _odbc_server_and_port("SERVER=db.example.com:5432;DATABASE=d") == \
        ("db.example.com", "5432")
    assert _odbc_server_and_port("SERVER=plainhost;DATABASE=d") == ("plainhost", "(default)")
    assert _odbc_server_and_port("DSN=MyDSN;UID=u") == ("DSN=MyDSN", "(dsn)")
    assert _odbc_server_and_port("DATABASE=d") == ("(odbc)", "(unknown)")
    # Case-insensitive, as ODBC connection-string keywords are.
    assert _odbc_server_and_port("server=Host,99")[0] == "Host"


def test_odbc_endpoint_never_exposes_credentials():
    """A timeout message must not become a credential leak.

    The parser only ever reads SERVER= / DSN=. If it is ever "improved" to echo
    the connection string, this fails.
    """
    from tina4_python.database.odbc import _odbc_server_and_port

    secret_connection_string = (
        "DRIVER={ODBC Driver 18};SERVER=db.internal,1433;"
        "DATABASE=payroll;UID=admin;PWD=hunter2;Trusted_Connection=no"
    )
    host, port = _odbc_server_and_port(secret_connection_string)
    for secret in ("hunter2", "PWD", "admin", "UID", "payroll"):
        assert secret not in host and secret not in str(port), (secret, host, port)


# ── NEGATIVE: a healthy connect against the live services still succeeds ──
#
# The whole risk of this feature is a bound that fires too eagerly and breaks
# every slow-but-healthy connect. These run against the REAL provisioned
# databases at the REAL default bound.

def _reachable(host, port) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


LIVE_DATABASES = [
    # TINA4_TEST_PG_URL is the canonical spelling (tests/fixtures/test_env_contract.json);
    # TINA4_TEST_POSTGRES_URL is a lab-only alias and the env-contract gate rejects it.
    ("postgres", PostgreSQLAdapter, os.environ.get("TINA4_TEST_PG_URL")),
    ("mysql", MySQLAdapter, os.environ.get("TINA4_TEST_MYSQL_URL")),
    ("mssql", MSSQLAdapter, os.environ.get("TINA4_TEST_MSSQL_URL")),
    ("firebird", FirebirdAdapter, os.environ.get("TINA4_TEST_FIREBIRD_URL")),
]


@pytest.mark.parametrize("engine,adapter_class,url", LIVE_DATABASES,
                         ids=[row[0] for row in LIVE_DATABASES])
def test_healthy_connect_still_succeeds_under_the_default_bound(engine, adapter_class, url):
    """A live, healthy database connects fine at the shipped 10s default."""
    if not url:
        pytest.skip(f"live {engine} URL not configured")
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if not _reachable(parsed.hostname, parsed.port):
        pytest.skip(f"live {engine} server not reachable")

    adapter = adapter_class()
    with connect_timeout_env(None):  # the shipped default, not a test value
        started = time.monotonic()
        adapter.connect(url)
        elapsed = time.monotonic() - started
    try:
        assert elapsed < DEFAULT_CONNECT_TIMEOUT_SECONDS, (
            f"{engine} took {elapsed:.2f}s — healthy connect is too close to the bound"
        )
        assert adapter.fetch_one("SELECT 1 AS one" if engine != "firebird"
                                 else "SELECT 1 AS one FROM RDB$DATABASE") is not None
    finally:
        adapter.close()
