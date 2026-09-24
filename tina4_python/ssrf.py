# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Outbound SSRF guard (ADR-0084).

The Api client and Web Push refuse, by default, to connect to a private or
internal address. Before each connection - the initial URL and every redirect
hop the Api client follows - the host is resolved to its IP address(es) and the
request is refused if any resolved address is loopback, private, link-local
(including the cloud metadata address 169.254.169.254), unspecified or CGNAT.
A non-http(s) scheme is refused.

The operator opt-out is ``TINA4_ALLOW_PRIVATE_REQUESTS`` (truthy = allow), off by
default; an app may also pass an explicit allow-list of hosts, ``host:port`` or
CIDRs. Zero external dependencies - Python stdlib ``ipaddress`` + ``socket``.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler

ALLOW_PRIVATE_ENV = "TINA4_ALLOW_PRIVATE_REQUESTS"

# Truthiness identical to ADR-0070's set (trimmed, lower-cased).
_TRUTHY = frozenset({"1", "true", "yes", "on"})

# The blocked address space. Kept as an explicit list (not ``ipaddress``'s own
# ``is_private`` etc.) so the four frameworks share one definition that matches
# the contract fixture exactly. 0.0.0.0/8 covers the unspecified address and the
# "this network" block.
_BLOCKED_V4 = tuple(ipaddress.ip_network(cidr) for cidr in (
    "0.0.0.0/8", "10.0.0.0/8", "127.0.0.0/8", "169.254.0.0/16",
    "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",
))
_BLOCKED_V6 = tuple(ipaddress.ip_network(cidr) for cidr in (
    "::1/128", "::/128", "fc00::/7", "fe80::/10",
))


class SsrfError(RuntimeError):
    """Raised when the guard refuses an outbound request."""


def allow_private_requests() -> bool:
    """True when TINA4_ALLOW_PRIVATE_REQUESTS opts out of the guard."""
    return os.environ.get(ALLOW_PRIVATE_ENV, "").strip().lower() in _TRUTHY


def is_blocked_address(ip_text: str) -> bool:
    """Classify one IP string: True = private/internal, refuse it.

    An IPv4-mapped IPv6 address (``::ffff:a.b.c.d``) is classified by its
    embedded IPv4 address. An unparseable value is treated as blocked - the
    guard refuses what it cannot classify.
    """
    try:
        address = ipaddress.ip_address(ip_text.split("%", 1)[0])
    except ValueError:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    networks = _BLOCKED_V4 if address.version == 4 else _BLOCKED_V6
    return any(address in network for network in networks)


def _matches_allow_list(host: str, port: int, resolved: list[str],
                        allow_hosts) -> bool:
    """True when the target is on the caller's explicit allow-list.

    An entry matches when it equals the host, equals ``host:port``, or is a CIDR
    that contains one of the resolved addresses.
    """
    host_lower = host.lower()
    for raw in allow_hosts or []:
        entry = str(raw).strip().lower()
        if not entry:
            continue
        if entry in (host_lower, f"{host_lower}:{port}"):
            return True
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            continue
        for ip_text in resolved:
            try:
                if ipaddress.ip_address(ip_text.split("%", 1)[0]) in network:
                    return True
            except ValueError:
                continue
    return False


def _log_block(host: str, ip_text: str) -> None:
    """Log the blocked attempt (host + IP only, never headers or the body)."""
    try:
        from tina4_python.debug import Log
        Log.warning(f"SSRF guard blocked outbound request to {host} ({ip_text})")
    except Exception:
        pass


def guard_url(url: str, allow_hosts=None) -> None:
    """Refuse ``url`` when it targets a private/internal address.

    Raises ``SsrfError`` for a non-http(s) scheme, a host that will not resolve,
    or any resolved address in the blocked space. A truthy
    ``TINA4_ALLOW_PRIVATE_REQUESTS`` or an allow-list match returns without error.
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise SsrfError(
            f"Blocked request: URL scheme '{scheme or '(none)'}' is not http or https")
    host = parsed.hostname
    if not host:
        raise SsrfError("Blocked request: URL has no host")
    port = parsed.port or (443 if scheme == "https" else 80)

    if allow_private_requests():
        return

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SsrfError(
            f"Blocked request to {host}: cannot resolve host ({exc})") from None
    resolved = [info[4][0] for info in infos]

    if _matches_allow_list(host, port, resolved, allow_hosts):
        return

    for ip_text in resolved:
        if is_blocked_address(ip_text):
            _log_block(host, ip_text)
            raise SsrfError(
                f"Blocked request to private/internal address {ip_text} "
                f"(host {host}): set {ALLOW_PRIVATE_ENV}=true to allow, "
                f"or pass an allow-list.")


class NoFollowRedirectHandler(HTTPRedirectHandler):
    """A urllib redirect handler that does not follow redirects.

    Returning ``None`` from ``redirect_request`` tells urllib to return the 3xx
    response as-is instead of following it. Web Push uses this: a real push
    service answers the POST directly, so a redirect from a push endpoint is
    never followed to a private address (ADR-0084)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


__all__ = [
    "SsrfError", "ALLOW_PRIVATE_ENV", "allow_private_requests",
    "is_blocked_address", "guard_url", "NoFollowRedirectHandler",
]
