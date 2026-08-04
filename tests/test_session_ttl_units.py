"""SESSION CONTRACT: a TTL is expressed in ONE unit by the caller, whatever the provider.

ADR-0024: the developer writes against the CONTRACT, never the PROVIDER. A ttl is
a number of SECONDS. Each backend converts that to whatever its own wire protocol
needs. Providers differ; the contract must not.

WHY THIS FILE EXISTS - the memcached 30-day cliff, MEASURED, not read.

memcached's `set` command takes an `exptime` field with a documented dual
meaning: a value up to 2592000 (30 days) is RELATIVE seconds, and ANY LARGER
VALUE IS AN ABSOLUTE UNIX TIMESTAMP. Tina4 interpolated the caller's ttl into
that field raw, in all four frameworks, with no conversion anywhere - grep for
2592000 across python, php, ruby and nodejs returned ZERO hits on 2026-08-04.

So TINA4_SESSION_TTL=2592001 - "about a month", an entirely ordinary remember-me
setting - was sent as the absolute timestamp 2592001, which is 1970-01-31. The
item was already expired at the moment it was stored. memcached still answers
STORED, so the write looks successful and the very next read is a miss. Measured
against real memcached 1.6.45 on this project:

    ttl=60        read -> {'seeded': True}     SURVIVES
    ttl=2592000   read -> {'seeded': True}     SURVIVES
    ttl=2592001   read -> {}                   VANISHED INSTANTLY
    ttl=4000000   read -> {}                   VANISHED INSTANTLY

That is a silent logout on every request, from a config value that looks
perfectly reasonable, and nothing anywhere reports it.

THE FIX under test converts a ttl past the boundary into the absolute stamp the
protocol is asking for (now + ttl), rather than CLAMPING to 2592000 - clamping
would silently shorten a session the operator explicitly asked to be longer,
which is the same class of lie in the other direction.

NO MOCKS. Every assertion here runs against a real memcached, and the
out-of-band check opens its own socket rather than asking the code under test.
"""
import os
import socket
import time
import uuid

import pytest

from tina4_python.session_handlers import MemcachedSessionHandler

MEMCACHED_HOST = os.environ.get("TINA4_TEST_MEMCACHED_HOST", "127.0.0.1")
MEMCACHED_PORT = int(os.environ.get("TINA4_TEST_MEMCACHED_PORT", "11211"))

# The protocol boundary itself. Anything at or below this is relative seconds;
# anything above it is read as an absolute unix timestamp.
MEMCACHED_RELATIVE_TTL_CEILING = 2592000


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


@pytest.fixture
def handler():
    if not _reachable(MEMCACHED_HOST, MEMCACHED_PORT):
        message = f"memcached is not reachable at {MEMCACHED_HOST}:{MEMCACHED_PORT}"
        if os.environ.get("TINA4_REQUIRE_SERVICES"):
            pytest.fail(f"TINA4_REQUIRE_SERVICES is set but {message}")
        pytest.skip(message)
    return MemcachedSessionHandler(host=MEMCACHED_HOST, port=MEMCACHED_PORT)


def _raw_get(key: str) -> bytes:
    """Read the key over a socket THIS TEST owns, not the handler's.

    A handler that lied about what it stored could not be caught by asking that
    same handler to read it back.
    """
    with socket.create_connection((MEMCACHED_HOST, MEMCACHED_PORT), timeout=3) as sock:
        sock.sendall(f"get {key}\r\n".encode())
        buf = b""
        while b"END\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        return buf


def _raw_remaining_ttl(key: str) -> int:
    """Ask the SERVER how long it thinks the key has left, over our own socket.

    memcached 1.6's meta-get reports the remaining ttl: `mg <key> t` answers
    `VA <size> t<seconds>`. This is what makes the difference between CONVERTING
    a long ttl and CLAMPING it visible - both survive a round-trip, but only one
    of them still has the lifetime the caller asked for.
    """
    with socket.create_connection((MEMCACHED_HOST, MEMCACHED_PORT), timeout=3) as sock:
        sock.sendall(f"mg {key} t v\r\n".encode())
        time.sleep(0.15)
        reply = sock.recv(4096).decode(errors="replace")
    for token in reply.split():
        if token.startswith("t") and token[1:].lstrip("-").isdigit():
            return int(token[1:])
    raise AssertionError(f"no ttl in meta-get reply for {key}: {reply!r}")


def test_session_ttl_above_the_memcached_thirty_day_boundary_survives(handler):
    """A ttl past 30 days must still mean "that many SECONDS from now".

    This is the headline gate. Before the fix the record vanished the instant it
    was written, because 2592001 was read as a moment in 1970.

    The 60-day case is what stops a CLAMP being mistaken for a fix. Clamping to
    2592000 also survives the round-trip, so a survival-only assertion cannot
    tell the two apart - but a clamp silently turns the 60-day session the
    operator asked for into a 30-day one. Asking the server for the remaining
    ttl makes that visible: convert reports ~5184000, clamp reports 2592000.
    """
    for over_the_boundary in (MEMCACHED_RELATIVE_TTL_CEILING + 1, 5184000):
        session_id = f"units-over-{uuid.uuid4().hex[:8]}"
        handler.write(session_id, {"seeded": True}, over_the_boundary)
        try:
            assert handler.read(session_id) == {"seeded": True}, (
                f"a ttl of {over_the_boundary}s expired the session instantly - "
                "memcached read it as an absolute timestamp in 1970"
            )
            # Out of band: the server really holds it, on a socket we opened.
            assert _raw_get(handler._key(session_id)).startswith(b"VALUE"), (
                "the handler claimed the session was stored but the server does not have it"
            )
            remaining = _raw_remaining_ttl(handler._key(session_id))
            assert abs(remaining - over_the_boundary) < 60, (
                f"asked for a {over_the_boundary}s session; the server says {remaining}s "
                "remain. A clamp to the 30-day ceiling silently shortens a lifetime the "
                "operator explicitly asked to be longer."
            )
        finally:
            handler.destroy(session_id)


def test_session_ttl_at_the_memcached_thirty_day_boundary_survives(handler):
    """BOUNDARY CONTROL: exactly 2592000 is still legal relative seconds.

    Pins which side of the cliff the conversion starts on. A fix that converted
    at or below the boundary would still be wrong, just less obviously.
    """
    session_id = f"units-at-{uuid.uuid4().hex[:8]}"

    handler.write(session_id, {"seeded": True}, MEMCACHED_RELATIVE_TTL_CEILING)
    try:
        assert handler.read(session_id) == {"seeded": True}, (
            f"a ttl of exactly {MEMCACHED_RELATIVE_TTL_CEILING}s is the largest legal "
            "RELATIVE exptime and must round-trip untouched"
        )
    finally:
        handler.destroy(session_id)


def test_session_ttl_below_the_boundary_still_really_expires(handler):
    """NEGATIVE CONTROL: a short ttl must still expire, for real.

    Without this, "never send an expiry at all" passes both cases above and
    ships a session store where nothing ever expires - which on a session store
    is a security defect, not a convenience.
    """
    session_id = f"units-short-{uuid.uuid4().hex[:8]}"

    handler.write(session_id, {"seeded": True}, 1)
    assert handler.read(session_id) == {"seeded": True}, "the record was never stored"

    time.sleep(3)  # REAL wall clock, past the 1s ttl. No clock patching.

    assert handler.read(session_id) == {}, (
        "a 1-second ttl did not expire - the conversion turned every ttl into "
        "'never expires'"
    )
    assert _raw_get(handler._key(session_id)) == b"END\r\n", (
        "the server still holds the key after it should have expired"
    )
