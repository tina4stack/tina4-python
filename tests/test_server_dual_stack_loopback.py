"""The built-in dev server must be reachable on BOTH loopback families.

Windows resolves ``localhost`` to ``::1`` (IPv6) FIRST, so a server bound only
to 127.0.0.1 — or the IPv4 wildcard 0.0.0.0, which does NOT cover IPv6 — refused
the browser with ERR_CONNECTION_REFUSED even though it was serving. Binding both
loopback families closes that gap.

These are real sockets: the server binds through the framework's own
``_bind_loopback_siblings`` (the exact code path ``_serve`` runs after the
primary bind), and a real TCP client connects on each family. No subprocess is
spawned, so it runs on Windows too (where the bug lives) as well as on Linux CI
and macOS.

Ports the PHP reference ``tests/ServerDualStackLoopbackTest.php`` (PR #206) —
same two cases, same intent. The one deliberate difference: Python's socket
layer takes a bare ``"::1"`` where PHP's stream_socket_server needs ``"[::1]"``,
so this framework's ``loopback_bind_hosts`` returns UNbracketed addresses.
"""
import asyncio
import socket

import pytest

from conftest import free_port
from tina4_python.core.server import loopback_bind_hosts, _bind_loopback_siblings


# ── 1. The mapping (pure function — no dependency, no double) ────────────────

def test_loopback_bind_hosts_names_the_sibling_family():
    """loopback_bind_hosts() names the sibling family a direct bind of the host
    would miss, and leaves an explicit LAN address untouched."""
    assert loopback_bind_hosts("127.0.0.1") == ["::1"], (
        "an IPv4-loopback host needs the IPv6 sibling"
    )
    assert loopback_bind_hosts("0.0.0.0") == ["::1"], (
        "the IPv4 wildcard still misses IPv6 loopback"
    )
    assert loopback_bind_hosts("::1") == ["127.0.0.1"], (
        "an IPv6-loopback host needs the IPv4 sibling"
    )
    assert loopback_bind_hosts("::") == ["127.0.0.1"], (
        "the IPv6 wildcard still misses IPv4 loopback"
    )
    assert loopback_bind_hosts("localhost") == ["127.0.0.1", "::1"], (
        "localhost resolves per-OS, so bind both explicitly"
    )
    assert loopback_bind_hosts("192.168.1.10") == [], (
        "an explicit LAN address is bound exactly as asked"
    )


def test_loopback_bind_hosts_returns_unbracketed_ipv6():
    """Python's asyncio/socket layer takes a bare ``::1`` — never ``[::1]``."""
    for value in loopback_bind_hosts("localhost") + loopback_bind_hosts("127.0.0.1"):
        assert "[" not in value and "]" not in value, (
            f"{value!r} must be an unbracketed address for Python sockets"
        )


def test_loopback_bind_hosts_normalises_host():
    """Whitespace and IPv6 brackets are stripped and the host is lower-cased,
    so the bracketed/padded forms map the same as the bare ones."""
    assert loopback_bind_hosts(" [::1] ") == ["127.0.0.1"]
    assert loopback_bind_hosts("LOCALHOST") == ["127.0.0.1", "::1"]
    assert loopback_bind_hosts("[::]") == ["127.0.0.1"]


# ── 2. Real dual-stack bind — a client connects on BOTH families ─────────────

def _ipv6_loopback_available() -> bool:
    """True when this host can bind IPv6 loopback at all."""
    try:
        probe = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:
        return False
    try:
        probe.bind(("::1", 0))
        return True
    except OSError:
        return False
    finally:
        probe.close()


async def _accepts(host: str, port: int) -> bool:
    """True when a real TCP client can connect to host:port."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=1.0
        )
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


async def test_server_bound_to_ipv4_loopback_also_answers_on_ipv6():
    """A server bound to IPv4 loopback also answers on IPv6 loopback — the
    dual-stack behaviour a Windows ``localhost`` browser depends on."""
    if not _ipv6_loopback_available():
        pytest.skip("IPv6 loopback (::1) is unavailable here")

    port = free_port()

    async def _handler(reader, writer):
        writer.close()

    # Mirror _serve(): the primary bind is unchanged, then best-effort siblings.
    primary = await asyncio.start_server(_handler, "127.0.0.1", port)
    siblings = await _bind_loopback_siblings(_handler, "127.0.0.1", port)

    try:
        assert siblings, (
            "binding 127.0.0.1 must yield an ::1 sibling listener — the "
            "dual-stack fix is missing if this is empty"
        )
        assert await _accepts("127.0.0.1", port), (
            "the primary IPv4 loopback listener must accept"
        )
        assert await _accepts("::1", port), (
            "IPv6 loopback must ALSO accept after the dual-stack fix"
        )
    finally:
        primary.close()
        for sibling in siblings:
            sibling.close()
        await primary.wait_closed()
        for sibling in siblings:
            await sibling.wait_closed()


async def test_explicit_lan_host_binds_no_siblings():
    """An explicit host that is neither loopback nor a wildcard gets NO extra
    listeners — the server binds exactly what was asked, nothing more."""
    async def _handler(reader, writer):
        writer.close()

    siblings = await _bind_loopback_siblings(_handler, "192.168.1.10", free_port())
    try:
        assert siblings == [], "a LAN host must not spawn loopback siblings"
    finally:
        for sibling in siblings:
            sibling.close()
            await sibling.wait_closed()
