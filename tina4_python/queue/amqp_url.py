# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# Tina4 Queue - AMQP URL parsing. Zero dependencies.
"""
Parse an AMQP URL into connection config, per the RabbitMQ URI spec.

THE VHOST IS THE PATH SEGMENT, URL-DECODED, WITH NO LEADING SLASH.
That single rule is the whole reason this module exists as its own file: all
four Tina4 frameworks used to prepend a "/" to whatever followed the host, so

    amqp://guest:guest@rabbit:5672/orders

asked the broker for a virtual host literally named "/orders". No broker has
that - the vhost is named "orders" - so every publish failed against a named
vhost, which is the ordinary multi-tenant RabbitMQ setup and the exact form
every RabbitMQ tutorial shows. MEASURED against a real broker: 4 of 5 URL
shapes resolved to the wrong name, and the only one that worked was the one
carrying no vhost at all. That is why four green suites never noticed - every
test and every dev box used the default vhost.

Percent-decoding matters for the same reason: the DEFAULT vhost is named "/",
which cannot be written literally in a path, so the spec spells it "%2f".
Without decoding, "amqp://host/%2f" asks for a vhost named "%2f".

  amqp://host              -> vhost unset, caller's default ("/")
  amqp://host/             -> vhost unset, caller's default ("/")   [see below]
  amqp://host/orders       -> "orders"
  amqp://host/%2f          -> "/"
  amqp://host/a%2Fb        -> "a/b"

DELIBERATE DEVIATION, one shape: the spec's own table reads a bare trailing
slash as the EMPTY vhost name "". Tina4 treats it as "no vhost given" and
leaves the caller's default in place. Nobody writes a trailing slash intending
a vhost whose name is the empty string, no broker ships one, and reading it
literally would turn a working "amqp://host:5672/" into a connection failure
for no benefit. Every other shape follows the spec exactly.
"""
from urllib.parse import unquote

from tina4_python.database.database_url import parse_url


def parse_amqp_url(url: str) -> dict:
    """Parse amqp://user:pass@host:port/vhost into a config dict.

    Only keys actually present in the URL are set, so a caller's own defaults
    survive for everything the URL does not mention.

    GHSA-h2mr-m3v3-cq8c: this split the userinfo at the FIRST `@` (so a
    password `Pq1@Rs2` made `Rs2@host` the host name) and ran ``int()`` on
    whatever followed the first `:` (``amqp://u:Pq1Rs2`` raised "invalid
    literal for int() with base 10: 'Pq1Rs2'"). It now uses the framework's
    one URL rule - userinfo ends at the LAST `@` - and refuses a malformed URL
    without echoing it. Credentials are percent-decoded, as the RabbitMQ URI
    spec requires (``p%40ss`` is the password ``p@ss``).
    """
    parsed = parse_url(url, "AMQP URL")
    config = {}
    if parsed.username is not None:
        config["username"] = parsed.username
    if parsed.password is not None:
        config["password"] = parsed.password

    # An empty segment means "not specified" - see the deviation note above.
    vhost = parsed.path[1:] if parsed.path.startswith("/") else parsed.path
    if vhost:
        config["vhost"] = unquote(vhost)

    if parsed.hostname:
        config["host"] = parsed.hostname
    if parsed.port is not None:
        config["port"] = parsed.port
    return config
