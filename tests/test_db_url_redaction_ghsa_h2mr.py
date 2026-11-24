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
the REAL connect/error paths (live drivers dialling a 127.0.0.1 listener that
hangs up, or a closed port). Nothing is mocked. Every output a human could see is
checked: the return value, ``str``/``repr`` of the exception AND of every
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


@pytest.fixture
def hangup_port():
    """A real 127.0.0.1 listener that accepts and immediately hangs up.

    A CLOSED port costs ~2s per attempt on Windows (SYN retries after RST); a
    listener that hangs up makes every driver take its own error path at once.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(64)
    stop = threading.Event()

    def serve():
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
                conn.close()
            except OSError:
                continue

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield server.getsockname()[1]
    stop.set()
    thread.join(timeout=2)
    server.close()


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


def _connect_matrix():
    return [(t, p) for t, p in MATRIX if not (t == HOSTLESS_TEMPLATE and "@" in p)]


CONNECT_MATRIX = _connect_matrix()
CONNECT_IDS = [f"t{TEMPLATES.index(t) + 1}-{p}" for t, p in CONNECT_MATRIX]


def _run(action) -> list[str]:
    try:
        action()
    except Exception as exc:  # noqa: BLE001 - every failure is inspected
        return _chain(exc)
    return []


@pytest.mark.parametrize("template, password", CONNECT_MATRIX, ids=CONNECT_IDS)
def test_database_connect_failure_never_shows_the_password(template, password, hangup_port, captured):
    from tina4_python.database import Database

    secrets = _secrets(template, password)
    leaks = []
    for scheme, module in (("postgres", "psycopg2"), ("mysql", "mysql.connector"),
                           ("mssql", "pymssql"), ("firebird", "firebird.driver"),
                           ("mongodb", "pymongo")):
        pytest.importorskip(module)
        url = _local_url(template, scheme, password, hangup_port)
        shown = _run(lambda: Database(url).close())
        leaks += [f"{scheme}: {leak}" for leak in _leaks(shown + captured(), secrets)]
    _assert_clean(leaks)


@pytest.mark.parametrize("template, password", CONNECT_MATRIX, ids=CONNECT_IDS)
def test_cache_backends_never_show_the_password(template, password, hangup_port, captured, tmp_path):
    from tina4_python.cache import _create_backend

    secrets = _secrets(template, password)
    leaks = []
    for scheme in CACHE_SCHEMES:
        backend = "redis" if scheme == "rediss" else scheme
        url = _local_url(template, scheme, password, hangup_port)
        shown = _run(lambda: _create_backend(backend, url, cache_dir=str(tmp_path)))
        leaks += [f"{scheme}: {leak}" for leak in _leaks(shown + captured(), secrets)]
    _assert_clean(leaks)


@pytest.mark.parametrize("template, password", CONNECT_MATRIX, ids=CONNECT_IDS)
def test_queue_backends_never_show_the_password(template, password, hangup_port, captured, monkeypatch):
    pytest.importorskip("pika")
    from tina4_python.queue.kafka_backend import KafkaBackend
    from tina4_python.queue.rabbitmq_backend import RabbitMQBackend

    secrets = _secrets(template, password)
    leaks = []
    for scheme in AMQP_SCHEMES:
        url = _local_url(template, scheme, password, hangup_port)
        monkeypatch.setenv("TINA4_QUEUE_URL", url)

        def rabbit():
            backend = RabbitMQBackend("ghsa_topic", 1)
            try:
                backend._backend.connect()
            finally:
                backend._backend.close()

        leaks += [f"{scheme}: {leak}" for leak in _leaks(_run(rabbit) + captured(), secrets)]

    url = _local_url(template, "kafka", password, hangup_port)
    monkeypatch.setenv("TINA4_QUEUE_URL", url)
    monkeypatch.delenv("TINA4_KAFKA_BROKERS", raising=False)
    shown_brokers = []

    def kafka():
        backend = KafkaBackend("ghsa_topic", 1)
        # The broker list is what librdkafka logs and every Kafka error quotes.
        shown_brokers.append(backend._backend._brokers)
        backend._backend._connect_raw()
        backend._backend._close_raw()

    shown = _run(kafka) + shown_brokers + captured()
    leaks += [f"kafka: {leak}" for leak in _leaks(shown, secrets)]
    _assert_clean(leaks)


@pytest.mark.parametrize("template, password", CONNECT_MATRIX, ids=CONNECT_IDS)
def test_mqtt_graph_backplane_and_session_never_show_the_password(template, password, hangup_port, captured):
    pytest.importorskip("redis")
    pytest.importorskip("pymongo")
    from tina4_python.graph import GraphDatabase
    from tina4_python.mqtt import Mqtt
    from tina4_python.session_handlers.mongodb_handler import MongoDBSessionHandler
    from tina4_python.websocket.backplane import RedisBackplane

    secrets = _secrets(template, password)
    leaks = []

    for scheme in MQTT_SCHEMES:
        url = _local_url(template, scheme, password, hangup_port)
        shown = _run(lambda: Mqtt(url, timeout=1).disconnect())
        leaks += [f"{scheme}: {leak}" for leak in _leaks(shown + captured(), secrets)]

    for scheme in GRAPH_SCHEMES:
        url = _local_url(template, scheme, password, hangup_port)
        shown = _run(lambda: GraphDatabase.create(url))
        leaks += [f"{scheme}: {leak}" for leak in _leaks(shown + captured(), secrets)]

    for scheme in ("redis", "rediss"):
        url = _local_url(template, scheme, password, hangup_port)
        shown = _run(lambda: RedisBackplane(url).close())
        leaks += [f"backplane {scheme}: {leak}" for leak in _leaks(shown + captured(), secrets)]

    url = _local_url(template, "mongodb", password, hangup_port)
    handler_host = []

    def session():
        handler = MongoDBSessionHandler(url=url)
        handler_host.append(f"{handler._host}:{handler._port}")
        try:
            handler._collection  # builds the pymongo client from the URL
        finally:
            handler.close()

    shown = _run(session) + handler_host + captured()
    leaks += [f"mongodb session: {leak}" for leak in _leaks(shown, secrets)]
    _assert_clean(leaks)
