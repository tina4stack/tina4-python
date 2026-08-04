"""CACHE CONTRACT - a TTL means seconds, on every provider.

Pins ``a-ttl-is-expressed-in-one-unit-by-the-caller`` from
``plan/v3/fixtures/cache_contract.json`` (ADR-0024).

    The caller expresses a TTL in ONE unit - seconds - on every provider. A
    backend converts to whatever its wire protocol needs, and never silently
    shortens or discards the lifetime the caller asked for.

MEASURED: memcached's ``set`` exptime field is RELATIVE seconds at or below
2592000 (30 days) and an ABSOLUTE UNIX TIMESTAMP above it. All four cache
backends interpolated the caller's ttl RAW. So a ``TINA4_CACHE_TTL`` above 30
days made every cache write vanish INSTANTLY: the caller wrote a number of
seconds, the server read a date in 1970. memcached still answers ``STORED``, so
it presents as a 100% miss rate with nothing logged anywhere - the cache looks
like it is working and never returns a single hit.

CONVERT, NEVER CLAMP. Clamping to 2592000 also makes the entry survive, and is
also wrong: it silently shortens a lifetime the operator explicitly asked to
lengthen. That is the same class of silent-wrong-answer this whole contract
exists to stop.

WHY SURVIVAL ALONE IS NOT A TEST. A case that only checks "the value is still
there" passes under a CLAMP as easily as under a CONVERT, so it cannot tell the
right fix from the wrong one. These tests read the server's OWN reported
remaining lifetime with meta-get (``mg <key> t v`` -> ``t<seconds>``, memcached
1.6+) and require it to match what was asked for. That is the server answering,
not us.

Every assertion runs against a REAL memcached. Nothing is simulated.
"""
import os
import socket
import time
import uuid
from urllib.parse import urlparse

import pytest

from tina4_python.cache import _MemcachedBackend

MEMCACHED_URL = os.environ.get("TINA4_TEST_CACHE_MEMCACHED_URL", "memcached://localhost:11211")

# memcached's own boundary: at or below this, exptime is RELATIVE seconds;
# above it, exptime is an ABSOLUTE unix timestamp.
THIRTY_DAYS = 2592000
SIXTY_DAYS = 5184000


def _reachable() -> bool:
    parsed = urlparse(MEMCACHED_URL if "://" in MEMCACHED_URL else "//" + MEMCACHED_URL)
    try:
        sock = socket.create_connection(
            (parsed.hostname or "localhost", parsed.port or 11211), timeout=2)
        sock.close()
        return True
    except OSError:
        return False


memcached_up = pytest.mark.skipif(not _reachable(), reason="memcached service not reachable")


def _server_remaining_ttl(backend, key: str) -> int | None:
    """Ask the SERVER how much longer it intends to keep the entry.

    ``mg <key> t v`` returns ``VA <len> t<seconds>``; ``t-1`` means no expiry.
    Reading this rather than merely reading the value back is the whole point:
    survival cannot distinguish a CONVERT from a CLAMP, and the remaining
    lifetime can.
    """
    resp = backend._command(f"mg {backend._mc_key(key)} t v\r\n".encode(), b"\r\n")
    for token in resp.split(b"\r\n")[0].split():
        if token.startswith(b"t"):
            try:
                return int(token[1:])
            except ValueError:
                return None
    return None


@memcached_up
def test_a_ttl_beyond_the_thirty_day_cliff_survives():
    """The measured defect: a 60-day TTL made the write vanish instantly."""
    backend = _MemcachedBackend(MEMCACHED_URL)
    key = f"cliff-{uuid.uuid4().hex}"

    backend.set(key, {"v": "sixty days"}, SIXTY_DAYS)

    assert backend.get(key) == {"v": "sixty days"}, (
        "a TTL above memcached's 30-day boundary was written as a RELATIVE "
        "duration, so the server read it as a 1970 timestamp and expired the "
        "entry immediately - a 100% miss rate with STORED returned and nothing "
        "logged"
    )


@memcached_up
def test_a_ttl_beyond_the_cliff_keeps_its_full_lifetime():
    """CONVERT, not CLAMP - and only the server can settle which happened.

    This is the case that makes the suite a real gate. A clamp to 2592000 also
    survives, so it passes the test above; only the server's own reported
    remaining lifetime shows that the requested 60 days was honoured.
    """
    backend = _MemcachedBackend(MEMCACHED_URL)
    key = f"cliff-{uuid.uuid4().hex}"

    backend.set(key, {"v": "sixty days"}, SIXTY_DAYS)

    remaining = _server_remaining_ttl(backend, key)
    assert remaining is not None, "memcached did not report a remaining TTL (needs 1.6+)"
    assert abs(remaining - SIXTY_DAYS) <= 60, (
        f"the server intends to keep this entry {remaining}s, not the "
        f"{SIXTY_DAYS}s that was asked for. A CLAMP to {THIRTY_DAYS} looks like "
        "a working cache and silently discards more than half the lifetime the "
        "operator configured."
    )


@memcached_up
def test_the_thirty_day_boundary_itself_stays_relative():
    """Boundary control: 2592000 is still RELATIVE, so it must not convert.

    Converting AT the boundary rather than above it would push the value to
    now+2592000 as an absolute stamp, which memcached also accepts - so this
    catches an off-by-one in the comparison that nothing else would.
    """
    backend = _MemcachedBackend(MEMCACHED_URL)
    key = f"boundary-{uuid.uuid4().hex}"

    backend.set(key, {"v": "exactly thirty days"}, THIRTY_DAYS)

    assert backend.get(key) == {"v": "exactly thirty days"}
    remaining = _server_remaining_ttl(backend, key)
    assert remaining is not None and abs(remaining - THIRTY_DAYS) <= 60, (
        f"at exactly {THIRTY_DAYS}s the server reports {remaining}s remaining"
    )


@memcached_up
def test_a_short_ttl_still_expires():
    """NEGATIVE: the conversion must not turn every TTL into forever.

    A fix that sent an absolute stamp for EVERY ttl, or dropped expiry
    altogether, passes every case above. This one waits on a real wall clock and
    requires the entry to actually be gone.
    """
    backend = _MemcachedBackend(MEMCACHED_URL)
    key = f"short-{uuid.uuid4().hex}"

    backend.set(key, {"v": "brief"}, 1)
    assert backend.get(key) == {"v": "brief"}, "precondition: a short TTL is readable"

    time.sleep(2.2)

    assert backend.get(key) is None, (
        "a 1-second entry outlived its TTL - the conversion made a short "
        "lifetime permanent"
    )


@memcached_up
def test_the_local_write_log_uses_the_raw_ttl():
    """The trap sitting on the line AFTER the fix.

    The backend keeps a local map of the keys it wrote and the moment each
    expires, and it computed that deadline from the SAME variable sent to
    memcached. Convert that variable to an absolute stamp and leave this line
    alone, and the map's deadline becomes ``now + <a unix timestamp>`` - a date
    about 166 years out, so stats() reports expired entries as live forever.

    The map must be built from the RAW ttl.
    """
    backend = _MemcachedBackend(MEMCACHED_URL)
    key = f"shadow-{uuid.uuid4().hex}"

    before = time.time()
    backend.set(key, {"v": "sixty days"}, SIXTY_DAYS)

    deadlines = [expires for expires in backend._own.values() if expires]
    assert deadlines, "the write log recorded no deadline at all"
    recorded = max(deadlines)
    expected = before + SIXTY_DAYS
    assert abs(recorded - expected) <= 60, (
        f"the local write log expires this entry at {recorded}, expected about "
        f"{expected}. It was built from the CONVERTED exptime, so the deadline "
        "is now + a unix timestamp - roughly 166 years out."
    )
