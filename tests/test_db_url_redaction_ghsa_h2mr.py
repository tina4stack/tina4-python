# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""GHSA-h2mr-m3v3-cq8c: a connection URL never prints its password.

THE BUG, MEASURED on v3 (461cdb44): ``redact_url``'s pattern
``(://[^/@\\s:]*:)[^/\\r\\n]*@`` could not cross a ``/``, never matched
``scheme:/`` or ``scheme//``, and never matched a URL without a host - so
``postgres://u:Pq1/Rs2@dbhost/appdb`` came back verbatim. Worse, the parsers
behind every connect path (``urlparse``, the AMQP/Kafka/memcached splitters,
redis-py's ``from_url``) read ``u:Pq1`` as ``host:port`` and raised the stdlib's
"Port could not be cast to integer value as 'Pq1'", which the connect wrapper
then quoted into the logged ConnectionError.

THE CASES are the shared four-framework list in
``tests/fixtures/db_url_redaction_cases.json``: every password x every template
x every scheme the path supports, fed to the REAL redactor, the REAL parsers and
the REAL connect/error paths (live drivers dialling a loopback listener that
refuses them at once - on the scheme's default port for a host-less URL).
Nothing is mocked. Every output a human could see is checked: the return value, ``str``/``repr`` of the exception AND of every
exception in its ``__cause__``/``__context__`` chain, captured log records, and
everything written to stdout/stderr at the file-descriptor level (which also
catches C drivers that log on their own).

ONE SHAPE IS NOT A LEAK BY CONSTRUCTION, and is checked for the part that IS the
password: ``scheme://u:Pq1@Rs2`` is a well-formed URL whose password is ``Pq1``
and whose HOST is ``Rs2``. The host is shown on purpose (logs must stay useful),
so for that one template x password only ``Pq1`` must be hidden, and the connect
paths skip it (they would resolve the host ``Rs2``). The other known limit - a
host-less all-digit password, ``postgres://u:123/x`` - is not in the case list.
"""
import json
import logging
import os
import socket
import threading
from pathlib import Path

import pytest

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "db_url_redaction_cases.json").read_text(encoding="utf-8")
)
FRAGMENTS = CASES["secret_fragments"]
PASSWORDS = CASES["passwords"]
TEMPLATES = CASES["templates"]
MATRIX = [(t, p) for t in TEMPLATES for p in PASSWORDS]
IDS = [f"t{TEMPLATES.index(t) + 1}-{p}" for t, p in MATRIX]

HOSTLESS_TEMPLATE = "{scheme}://u:{pw}"

DB_SCHEMES = ["postgres", "postgresql", "pgsql", "mysql", "mssql", "sqlserver", "firebird", "mongodb"]
GRAPH_SCHEMES = ["ultipa", "ultipas", "neo4j", "neo4j+s", "bolt", "bolt+s", "memgraph", "arango", "arangodb"]
AMQP_SCHEMES = ["amqp", "amqps"]
MQTT_SCHEMES = ["mqtt", "mqtts", "tcp"]
CACHE_SCHEMES = ["redis", "rediss", "valkey", "memcached"]
REDACT_SCHEMES = (DB_SCHEMES + ["sqlite", "sqlite3", "odbc"] + GRAPH_SCHEMES + AMQP_SCHEMES
                  + ["kafka", "nats"] + MQTT_SCHEMES + CACHE_SCHEMES)


def _secrets(template: str, password: str) -> list[str]:
    """The fragments that must never appear for this case.

    ``scheme://u:Pq1@Rs2`` says host=Rs2 - see the module docstring.
    """
    if template == HOSTLESS_TEMPLATE and "@" in password:
        return [password.split("@")[0]]
    return FRAGMENTS


def _url(template: str, scheme: str, password: str) -> str:
    return template.format(scheme=scheme, pw=password)


def _local_url(template: str, scheme: str, password: str, port: int) -> str:
    """The same shape aimed at a local port, so the live driver fails fast."""
    url = _url(template, scheme, password)
    url = url.replace("dbhost:5432", f"127.0.0.1:{port}")
    url = url.replace("dbhost:notaport", "127.0.0.1:notaport")
    return url.replace("dbhost", f"127.0.0.1:{port}")


def _chain(exc: BaseException | None) -> list[str]:
    """str() and repr() of the exception and of everything chained to it."""
    seen, out = set(), []
    stack = [exc]
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        out.append(str(current))
        out.append(repr(current))
        stack.append(current.__cause__)
        stack.append(current.__context__)
    return out


def _leaks(texts, secrets) -> list[str]:
    return [f"{s!r} in {t!r}" for t in texts for s in secrets if t and s in t]


def _assert_clean(leaks: list[str]):
    assert not leaks, f"{len(leaks)} leak(s):\n" + "\n".join(leaks[:8])


class _RefusingListener:
    """A real loopback listener that refuses every client at once.

    It hangs up as soon as a client connects, so every live driver takes its
    OWN error path immediately (a CLOSED port costs ~2s per attempt on Windows:
    SYN retries after RST). With ``reply=True`` it first reads the client's
    command and answers one generic RESP error line: redis-py retries a dropped
    connection for seconds but does not retry an error reply. Nothing in the
    framework is patched.
    """

    def __init__(self, port: int = 0, reply: bool = False):
        self.reply = reply
        self.sockets = []
        self._stop = threading.Event()
        families = [(socket.AF_INET, "127.0.0.1")]
        if port and socket.has_ipv6:
            families.append((socket.AF_INET6, "::1"))  # `localhost` may resolve to ::1 first
        for family, host in families:
            server = socket.socket(family, socket.SOCK_STREAM)
            try:
                server.bind((host, port))
            except OSError as error:
                server.close()
                if family == socket.AF_INET6 and getattr(error, "winerror", None) != 10048 \
                        and error.errno not in (98, 48):
                    continue  # no IPv6 loopback here: the IPv4 listener still serves
                self.close()
                raise
            server.listen(64)
            server.settimeout(0.2)
            self.sockets.append(server)
            port = port or server.getsockname()[1]
            threading.Thread(target=self._serve, args=(server,), daemon=True).start()
        self.port = port

    def _serve(self, server):
        while not self._stop.is_set():
            try:
                conn, _ = server.accept()
            except OSError:
                continue
            if not self.reply:
                conn.close()
                continue
            threading.Thread(target=self._refuse, args=(conn,), daemon=True).start()

    @staticmethod
    def _refuse(conn):
        try:
            conn.settimeout(0.2)
            try:
                conn.recv(4096)
            except OSError:
                pass
            conn.sendall(b"-ERR refused\r\n")
        except OSError:
            pass
        finally:
            conn.close()

    def close(self):
        self._stop.set()
        for server in self.sockets:
            server.close()


@pytest.fixture(scope="module")
def listeners():
    """An ephemeral-port listener, plus one per DEFAULT port on demand.

    A host-less URL (`scheme://u:pw@/appdb`) dials the scheme's default port
    on localhost, so that port gets a refusing listener too. If the machine
    already uses it, only the cases that need it are skipped, with a
    machine-readable reason - never a silent pass.
    """
    opened = {}
    busy = set()

    def get(port: int = 0, reply: bool = False) -> int:
        if port in busy:
            pytest.skip(f"[needs:free-port={port}]")
        if (port, reply) not in opened:
            try:
                opened[(port, reply)] = _RefusingListener(port, reply)
            except OSError:
                if not port:
                    raise
                busy.add(port)
                pytest.skip(f"[needs:free-port={port}]")
        return opened[(port, reply)].port

    yield get
    for listener in opened.values():
        listener.close()


@pytest.fixture
def captured(caplog, capfd):
    """Everything a human could see: log records and fd-level stdout/stderr."""
    caplog.set_level(logging.DEBUG)

    def read() -> list[str]:
        out, err = capfd.readouterr()
        return [caplog.text, out, err]

    return read


# ── 1. The redactor ───────────────────────────────────────────────────────


@pytest.mark.parametrize("template, password", MATRIX, ids=IDS)
def test_redact_url_hides_the_password(template, password):
    from tina4_python.core.server import _strip_url_credentials
    from tina4_python.database.database_url import redact_url

    secrets = _secrets(template, password)
    leaks = []
    for scheme in REDACT_SCHEMES:
        url = _url(template, scheme, password)
        redacted = redact_url(url)
        in_a_line = redact_url(f"Database: could not connect to {url}: connection refused")
        leaks += _leaks([redacted, in_a_line, _strip_url_credentials(url)], secrets)
        if not _leaks([redacted], secrets):
            # Still useful: scheme, user and host stay visible.
            assert redacted.startswith(scheme), (url, redacted)
            assert "u:***" in redacted, (url, redacted)
            if "dbhost" in template:
                assert "dbhost" in redacted, (url, redacted)
    _assert_clean(leaks)


def test_redact_url_leaves_values_without_a_credential_alone():
    from tina4_python.database.database_url import redact_url

    for harmless in ("sqlite:///data/app.db", "postgres://localhost:5432/mydb",
                     "https://example.com:8080/path", "/usr/local/bin:/usr/bin",
                     "mqtt://[::1]:1883", "postgres://dbhost/appdb?sslmode=require",
                     "redis://cache down: retrying at 12:30", "C:/Users/app.db",
                     "postgres://u@dbhost:5432/appdb"):
        assert redact_url(harmless) == harmless


def test_redact_url_keeps_a_query_after_a_masked_hostless_password():
    from tina4_python.database.database_url import redact_url

    assert redact_url("postgres://u:Pq1Rs2?sslmode=require") == "postgres://u:***?sslmode=require"


# ── 2. The parsers ────────────────────────────────────────────────────────


def _parse_outputs(parse, url):
    """Run a parser; return what it shows (exception chain, or display fields)."""
    try:
        shown = parse(url)
    except Exception as exc:  # noqa: BLE001 - every failure is inspected
        return _chain(exc)
    return [str(x) for x in shown if x is not None]


def _database_url(url):
    from tina4_python.database.database_url import DatabaseUrl
    parsed = DatabaseUrl(url)
    return [repr(parsed), str(parsed), parsed.to_safe_string(), parsed.host, parsed.dsn()]


def _graph_url(url):
    from tina4_python.graph.graph_url import GraphUrl
    parsed = GraphUrl(url)
    return [parsed.get_dsn(), parsed.host, repr(parsed)]


def _amqp_url(url):
    from tina4_python.queue.amqp_url import parse_amqp_url
    cfg = parse_amqp_url(url)
    return [cfg.get("host"), cfg.get("port"), cfg.get("vhost")]


def _mqtt_url(url):
    from tina4_python.mqtt import Mqtt
    cfg = Mqtt.parse_url(url)
    return [cfg["host"], cfg["port"]]


PARSERS = [
    ("DatabaseUrl", _database_url, DB_SCHEMES),
    ("GraphUrl", _graph_url, GRAPH_SCHEMES),
    ("parse_amqp_url", _amqp_url, AMQP_SCHEMES),
    ("Mqtt.parse_url", _mqtt_url, MQTT_SCHEMES),
]


@pytest.mark.parametrize("template, password", MATRIX, ids=IDS)
def test_parsers_never_show_the_password(template, password):
    secrets = _secrets(template, password)
    leaks = []
    for name, parse, schemes in PARSERS:
        for scheme in schemes:
            url = _url(template, scheme, password)
            leaks += [f"{name}: {leak}" for leak in _leaks(_parse_outputs(parse, url), secrets)]
    _assert_clean(leaks)


@pytest.mark.parametrize("case", CASES["must_still_parse"], ids=lambda c: c["url"])
def test_must_still_parse(case):
    from tina4_python.database.database_url import DatabaseUrl, url_credentials

    parsed = DatabaseUrl(case["url"])
    assert parsed.host == case["host"]
    assert parsed.port == case.get("port", 5432)
    assert parsed.username == case["user"]
    assert parsed.password == case["password"]
    assert parsed.database == case["database"]
    assert url_credentials(case["url"]) == (case["user"], case["password"])
    assert case["password"] not in parsed.to_safe_string()


@pytest.mark.parametrize("password", PASSWORDS)
def test_round_trip_every_parser_reads_the_whole_password_and_the_real_host(password):
    """Masking is half the rule; the other half is reading the SAME password.

    A parser that split at the first `@`, or kept userinfo in a broker list,
    shows nothing extra - it just connects with the wrong password or refuses a
    valid URL. So every parser must give back the case password whole and the
    host after the LAST `@`.
    """
    from tina4_python.database.database_url import DatabaseUrl, url_credentials
    from tina4_python.graph.graph_url import GraphUrl
    from tina4_python.mqtt import Mqtt
    from tina4_python.queue.amqp_url import parse_amqp_url
    from tina4_python.queue_backends.kafka_backend import kafka_broker_list

    for template in ("{scheme}://u:{pw}@dbhost:5432/appdb", "{scheme}://u:{pw}@dbhost/appdb?sslmode=require"):
        db = DatabaseUrl(_url(template, "postgres", password))
        assert (db.username, db.password, db.host) == ("u", password, "dbhost")
        assert url_credentials(_url(template, "mysql", password)) == ("u", password)
        graph = GraphUrl(_url(template, "neo4j", password))
        assert (graph.username, graph.password, graph.host) == ("u", password, "dbhost")
        amqp = parse_amqp_url(_url(template, "amqp", password))
        assert (amqp["username"], amqp["password"], amqp["host"]) == ("u", password, "dbhost")
        mqtt = Mqtt.parse_url(_url(template, "mqtt", password))
        assert (mqtt["username"], mqtt["password"], mqtt["host"]) == ("u", password, "dbhost")
    assert kafka_broker_list(f"kafka://u:{password}@dbhost:9092,dbhost2:9093") == "dbhost:9092,dbhost2:9093"


@pytest.mark.parametrize("password", [p for p in PASSWORDS if "@" not in p])
def test_hostless_a_url_the_redactor_masks_is_refused_by_the_parser(password):
    """Parser and redactor agree: `driver://u:12?Pq1Rs2` is not host `u`, port 12."""
    from tina4_python.database.database_url import DatabaseUrl, redact_url

    url = f"postgres://u:{password}"
    assert redact_url(url) != url
    with pytest.raises(ValueError) as raised:
        DatabaseUrl(url)
    assert not _leaks(_chain(raised.value), FRAGMENTS)


def test_firebird_charset_is_never_read_out_of_the_password(monkeypatch):
    from tina4_python.database.firebird import _resolve_firebird_charset

    monkeypatch.delenv("TINA4_DATABASE_CHARSET", raising=False)
    assert _resolve_firebird_charset("firebird://u:p?charset=NONE@dbhost/db.fdb") == "UTF8"
    assert _resolve_firebird_charset("firebird://u:p@dbhost/db.fdb?charset=NONE") == "NONE"


def test_a_parse_error_never_chains_a_stdlib_error_that_quotes_the_url():
    from tina4_python.database.database_url import DatabaseUrl

    # `from None` alone is not enough: it suppresses the context in a printed
    # traceback but still attaches it as __context__.
    for url in ("postgres://u:Pq1Rs2@dbhost:notaport/appdb", "postgres://dbhost:Pq1Rs2/appdb"):
        with pytest.raises(ValueError) as raised:
            DatabaseUrl(url)
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None


def test_a_url_without_scheme_slashes_is_refused_generically():
    from tina4_python.database.database_url import DatabaseUrl

    for url in ("postgres:/u:Pq1Rs2@dbhost/appdb", "postgres//u:Pq1Rs2@dbhost/appdb"):
        with pytest.raises(ValueError) as raised:
            DatabaseUrl(url)
        assert not _leaks(_chain(raised.value), FRAGMENTS)


def test_an_unencoded_at_in_the_query_is_refused():
    from tina4_python.database.database_url import DatabaseUrl

    with pytest.raises(ValueError, match="%40"):
        DatabaseUrl("postgres://dbhost/appdb?owner=a@b")
    assert DatabaseUrl("postgres://dbhost/appdb?owner=a%40b").host == "dbhost"


# ── 3. The real connect / error paths ─────────────────────────────────────


# The port a host-less URL dials: the scheme's default (the adapter's or the
# client library's), on localhost.
DEFAULT_PORT = {
    "postgres": 5432, "mysql": 3306, "mssql": 1433, "firebird": 3050, "mongodb": 27017,
    "redis": 6379, "rediss": 6379, "valkey": 6379, "memcached": 11211,
    "amqp": 5672, "amqps": 5672, "kafka": 9092, "mqtt": 1883, "tcp": 1883, "mqtts": 8883,
    "ultipa": 60061, "ultipas": 60061, "neo4j": 7687, "neo4j+s": 7687, "bolt": 7687,
    "bolt+s": 7687, "memgraph": 7687, "arango": 8529, "arangodb": 8529,
}
# Only the template with NO host part dials localhost. `scheme://u:pw` reads as
# host `u` (and is refused at parse), so it needs no default-port listener.
HOSTLESS = {"{scheme}://u:{pw}@/appdb"}
# Clients that retry a dropped connection (redis-py) get an error reply instead.
REPLY_SCHEMES = {"redis", "rediss", "valkey"}

# `scheme://u:Pq1@Rs2` names the host Rs2 (see the module docstring): not dialled.
CONNECT_MATRIX = [(t, p) for t, p in MATRIX if not (t == HOSTLESS_TEMPLATE and "@" in p)]


def _connect_cases(schemes):
    cases = [(s, t, p) for s in schemes for t, p in CONNECT_MATRIX]
    ids = [f"{s}-t{TEMPLATES.index(t) + 1}-{p}" for s, t, p in cases]
    return pytest.mark.parametrize("scheme, template, password", cases, ids=ids)


def _target(listeners, template, scheme, password) -> str:
    """The case URL aimed at a refusing listener: the ephemeral one, or for a
    host-less template the scheme's default port (skipped if that is busy)."""
    if template in HOSTLESS:
        listeners(DEFAULT_PORT[scheme], scheme in REPLY_SCHEMES)
        return _url(template, scheme, password)
    return _local_url(template, scheme, password, listeners(0, scheme in REPLY_SCHEMES))


def _run(action) -> list[str]:
    try:
        action()
    except Exception as exc:  # noqa: BLE001 - every failure is inspected
        return _chain(exc)
    return []


DB_DRIVERS = {"postgres": "psycopg2", "mysql": "mysql.connector", "mssql": "pymssql",
              "firebird": "firebird.driver", "mongodb": "pymongo"}


@_connect_cases(list(DB_DRIVERS))
def test_database_connect_failure_never_shows_the_password(scheme, template, password, listeners,
                                                           captured, monkeypatch):
    pytest.importorskip(DB_DRIVERS[scheme])
    from tina4_python.database import Database

    # The framework's own connect bound, so no driver can stall a case.
    monkeypatch.setenv("TINA4_DATABASE_CONNECT_TIMEOUT", "3")
    url = _target(listeners, template, scheme, password)
    shown = _run(lambda: Database(url).close())
    _assert_clean(_leaks(shown + captured(), _secrets(template, password)))


@_connect_cases(CACHE_SCHEMES)
def test_cache_backends_never_show_the_password(scheme, template, password, listeners, captured, tmp_path):
    from tina4_python.cache import _create_backend

    backend = "redis" if scheme == "rediss" else scheme
    url = _target(listeners, template, scheme, password)
    shown = _run(lambda: _create_backend(backend, url, cache_dir=str(tmp_path)))
    _assert_clean(_leaks(shown + captured(), _secrets(template, password)))


@_connect_cases(AMQP_SCHEMES)
def test_rabbitmq_queue_never_shows_the_password(scheme, template, password, listeners, captured, monkeypatch):
    pytest.importorskip("pika")
    from tina4_python.queue.rabbitmq_backend import RabbitMQBackend

    monkeypatch.setenv("TINA4_QUEUE_URL", _target(listeners, template, scheme, password))

    def rabbit():
        backend = RabbitMQBackend("ghsa_topic", 1)
        try:
            backend._backend.connect()
        finally:
            backend._backend.close()

    _assert_clean(_leaks(_run(rabbit) + captured(), _secrets(template, password)))


@_connect_cases(["kafka"])
def test_kafka_queue_never_shows_the_password(scheme, template, password, listeners, captured, monkeypatch):
    from tina4_python.queue.kafka_backend import KafkaBackend

    monkeypatch.setenv("TINA4_QUEUE_URL", _target(listeners, template, scheme, password))
    monkeypatch.delenv("TINA4_KAFKA_BROKERS", raising=False)
    shown_brokers = []

    def kafka():
        backend = KafkaBackend("ghsa_topic", 1)
        # The broker list is what librdkafka logs and every Kafka error quotes.
        shown_brokers.append(backend._backend._brokers)
        if backend._backend._brokers:
            # An EMPTY list (host-less URL) names no broker to dial; the raw
            # connector would resolve "" to every interface, not loopback.
            backend._backend._connect_raw()
            backend._backend._close_raw()

    shown = _run(kafka) + shown_brokers + captured()
    _assert_clean(_leaks(shown, _secrets(template, password)))


@_connect_cases(MQTT_SCHEMES)
def test_mqtt_never_shows_the_password(scheme, template, password, listeners, captured):
    from tina4_python.mqtt import Mqtt

    url = _target(listeners, template, scheme, password)
    shown = _run(lambda: Mqtt(url, timeout=1).disconnect())
    _assert_clean(_leaks(shown + captured(), _secrets(template, password)))


@_connect_cases(GRAPH_SCHEMES)
def test_graph_factory_never_shows_the_password(scheme, template, password, listeners, captured):
    from tina4_python.graph import GraphDatabase

    url = _target(listeners, template, scheme, password)
    shown = _run(lambda: GraphDatabase.create(url))
    _assert_clean(_leaks(shown + captured(), _secrets(template, password)))


@_connect_cases(["redis", "rediss"])
def test_websocket_backplane_never_shows_the_password(scheme, template, password, listeners, captured):
    pytest.importorskip("redis")
    from tina4_python.websocket.backplane import RedisBackplane

    url = _target(listeners, template, scheme, password)
    shown = _run(lambda: RedisBackplane(url).close())
    _assert_clean(_leaks(shown + captured(), _secrets(template, password)))


@_connect_cases(["mongodb"])
def test_mongodb_session_handler_never_shows_the_password(scheme, template, password, listeners, captured):
    pytest.importorskip("pymongo")
    from tina4_python.session_handlers.mongodb_handler import MongoDBSessionHandler

    url = _target(listeners, template, scheme, password)
    handler_host = []

    def session():
        handler = MongoDBSessionHandler(url=url)
        handler_host.append(f"{handler._host}:{handler._port}")
        try:
            handler._collection  # builds the pymongo client from the URL
        finally:
            handler.close()

    shown = _run(session) + handler_host + captured()
    _assert_clean(_leaks(shown, _secrets(template, password)))
