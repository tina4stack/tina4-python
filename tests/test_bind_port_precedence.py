"""TINA4_PORT MUST BEAT BARE PORT, ON THE PATH THAT BINDS THE SOCKET.

The CLI documents the contract as
``CLI flag > TINA4_PORT > PORT > framework default`` and labels bare PORT
"Legacy bare server port (prefer TINA4_PORT)". Four frameworks implemented four
different things, and two ignored the canonical name entirely on the ONE path
that binds:

    PHP    run()               read no port env var at all
    Python resolve_config      read PORT only
    Node   resolvePortAndHost  read PORT only
    Ruby   tina4.rb            read PORT first, TINA4_PORT second (inverted)
    Ruby   webserver.rb        correct - and disagreed with tina4.rb

So setting TINA4_PORT did nothing, silently, in most of the stack. It cost two
benchmark runs in one afternoon, each misread as a harness error, which is
exactly how a user experiences it.

Bare PORT is DEPRECATED, not removed: it is still honoured so no deployment
breaks, and it warns so the migration happens. Removal is 3.14.

Identical case names in all four frameworks:
  tina4-php/tests/BindPortPrecedenceTest.php
  tina4-ruby/spec/bind_port_precedence_spec.rb
  tina4-nodejs/test/bindPortPrecedence.test.ts
"""
import os

import pytest

from tina4_python.core import server as server_mod
from tina4_python.core.server import resolve_config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("TINA4_PORT", "PORT", "TINA4_HOST", "HOST"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(server_mod, "_PORT_DEPRECATION_WARNED", False, raising=False)


def test_tina4_port_wins_over_bare_port(monkeypatch):
    monkeypatch.setenv("TINA4_PORT", "45001")
    monkeypatch.setenv("PORT", "9999")
    assert resolve_config()[1] == 45001, (
        "bare PORT outranked TINA4_PORT - a stray OS-level PORT can hijack the "
        "bind address"
    )


def test_bare_port_is_still_honoured(monkeypatch):
    """Deprecated, not removed. Breaking this breaks every PaaS deploy."""
    monkeypatch.setenv("PORT", "9999")
    assert resolve_config()[1] == 9999


def test_an_explicit_argument_beats_both(monkeypatch):
    monkeypatch.setenv("TINA4_PORT", "45001")
    monkeypatch.setenv("PORT", "9999")
    assert resolve_config(cli_port=6000)[1] == 6000


def test_the_default_applies_when_nothing_is_set():
    assert resolve_config()[1] == 7146


def test_a_non_numeric_value_falls_through(monkeypatch):
    """A typo must not bind port 0 or crash - it falls to the next source."""
    monkeypatch.setenv("TINA4_PORT", "not-a-port")
    monkeypatch.setenv("PORT", "9999")
    assert resolve_config()[1] == 9999


def test_tina4_host_wins_over_bare_host(monkeypatch):
    monkeypatch.setenv("TINA4_HOST", "127.0.0.1")
    monkeypatch.setenv("HOST", "0.0.0.0")
    assert resolve_config()[0] == "127.0.0.1"
