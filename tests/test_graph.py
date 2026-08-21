# Contract suite for the graph data layer (Feature 139) — against a REAL engine.
"""No mocks. Every case runs a real connection and real round-trips against a
provisioned graph engine. Ultipa community edition is the first engine; the URL
comes from TINA4_TEST_ULTIPA_URL (the suite skips when it is unset, exactly like
the relational live-database tests). Case names match fixtures/graph_contract.json.

Ultipa note: edge ids need EDGE_ID enabled on the graph
(`ALTER GRAPH <g> SET EDGE_ID ENABLED`) — a one-time per-graph setting the lab
provisions.
"""
import os
import socket
import time
from urllib.parse import urlparse

import pytest

from tina4_python.graph import GraphDatabase, GraphNode, GraphEdge, GraphResult
from tina4_python.graph.adapter import GraphError, GraphConnectTimeout

ULTIPA_URL = os.environ.get("TINA4_TEST_ULTIPA_URL")
LABEL = "T4GraphContractTest"


def _reachable(url) -> bool:
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 60061), timeout=2.0):
            return True
    except OSError:
        return False


requires_ultipa = pytest.mark.skipif(
    not ULTIPA_URL or not _reachable(ULTIPA_URL),
    reason="live Ultipa not configured/reachable (set TINA4_TEST_ULTIPA_URL)",
)


@pytest.fixture
def graph():
    """A connected Ultipa adapter on a clean slate for the test label."""
    db = GraphDatabase.create(ULTIPA_URL)
    db.execute(f"MATCH (n:`{LABEL}`) DETACH DELETE n")
    try:
        yield db
    finally:
        db.execute(f"MATCH (n:`{LABEL}`) DETACH DELETE n")
        db.close()


# ── driver-optional runs WITHOUT a live engine ──────────────────────────────

def test_graph_driver_optional():
    """The core imports with no engine driver; a missing driver raises an
    actionable install error naming the package and command."""
    import importlib
    importlib.import_module("tina4_python.graph")  # no driver pulled in
    # A scheme whose driver is absent surfaces the install error. We cannot
    # uninstall tina4-ultipa mid-suite, so assert the message shape the factory
    # builds for an absent driver via a monkeypatched missing module.
    from tina4_python.graph import adapter as adapter_module
    saved = adapter_module._ENGINE_ADAPTERS["ultipa"]
    adapter_module._ENGINE_ADAPTERS["ultipa"] = (
        "tina4_python.graph.adapters._definitely_absent", "X", "tina4-ultipa",
        "uv add tina4-ultipa",
    )
    try:
        with pytest.raises(GraphError) as excinfo:
            GraphDatabase.create("ultipa://h:60061/g")
        assert "tina4-ultipa" in str(excinfo.value)
    finally:
        adapter_module._ENGINE_ADAPTERS["ultipa"] = saved


def test_graph_connect_by_url_selects_adapter():
    """The URL scheme picks the adapter; an unknown scheme is rejected."""
    from tina4_python.graph import GraphUrl
    assert GraphUrl("ultipa://h:60061/g").engine == "ultipa"
    assert GraphUrl("neo4j://h/db").engine == "bolt"
    with pytest.raises(ValueError):
        GraphUrl("mysql://h/db")


# ── the portable core + raw pass-through, against LIVE Ultipa ────────────────

@requires_ultipa
def test_graph_connect_by_url_live(graph):
    assert type(graph).__name__ == "UltipaGraphAdapter"


@requires_ultipa
def test_graph_add_node(graph):
    node = graph.add_node(LABEL, {"name": "Ada", "age": 36})
    assert isinstance(node, GraphNode)
    assert node.id and LABEL in node.labels and node.properties["name"] == "Ada"


@requires_ultipa
def test_graph_add_edge(graph):
    a = graph.add_node(LABEL, {"name": "Ada"})
    b = graph.add_node(LABEL, {"name": "Bob"})
    edge = graph.add_edge(a.id, b.id, "KNOWS", {"since": 2020})
    assert isinstance(edge, GraphEdge)
    assert edge.id and edge.type == "KNOWS"
    assert edge.from_id == a.id and edge.to_id == b.id
    assert edge.properties["since"] == 2020


@requires_ultipa
def test_graph_get_node_roundtrip_and_miss(graph):
    a = graph.add_node(LABEL, {"name": "Ada", "age": 36})
    got = graph.get_node(a.id)
    assert got.properties["name"] == "Ada" and got.properties["age"] == 36
    assert graph.get_node("no-such-id") is None  # a miss is not an error


@requires_ultipa
def test_graph_update_delete_node(graph):
    a = graph.add_node(LABEL, {"name": "Ada", "age": 36})
    graph.update_node(a.id, {"name": "Ada Lovelace", "city": "London"})
    updated = graph.get_node(a.id)
    assert updated.properties["name"] == "Ada Lovelace"
    assert updated.properties["city"] == "London"
    assert updated.properties["age"] == 36  # merge, not replace
    graph.delete_node(a.id)
    assert graph.get_node(a.id) is None


@requires_ultipa
def test_graph_neighbors(graph):
    a = graph.add_node(LABEL, {"name": "Ada"})
    b = graph.add_node(LABEL, {"name": "Bob"})
    graph.add_edge(a.id, b.id, "KNOWS", {})
    out = {n.id for n in graph.neighbors(a.id, direction="out", edge_type="KNOWS")}
    assert b.id in out and a.id not in out
    assert graph.neighbors(a.id, edge_type="NOPE") == []  # unmatched → empty


@requires_ultipa
def test_graph_traverse_depth(graph):
    a = graph.add_node(LABEL, {"name": "A"})
    b = graph.add_node(LABEL, {"name": "B"})
    c = graph.add_node(LABEL, {"name": "C"})
    graph.add_edge(a.id, b.id, "KNOWS", {})
    graph.add_edge(b.id, c.id, "KNOWS", {})
    reached = {n.id for n in graph.traverse(a.id, depth=2, direction="out", edge_type="KNOWS")}
    assert b.id in reached and c.id in reached  # 2 hops reach both


@requires_ultipa
def test_graph_raw_query_bound_params(graph):
    graph.add_node(LABEL, {"name": "Bob"})
    result = graph.query(f"MATCH (n:`{LABEL}`) WHERE n.name = $nm RETURN n.name AS name",
                         {"nm": "Bob"})
    assert isinstance(result, GraphResult)
    assert len(result) >= 1 and result.records[0]["name"] == "Bob"


@requires_ultipa
def test_graph_write_fails_loud(graph):
    with pytest.raises(GraphError):
        graph.execute("THIS IS NOT GQL")
    assert graph.get_error() is not None


@requires_ultipa
def test_graph_connect_timeout(monkeypatch):
    """An unreachable host throws GraphConnectTimeout within the bound, naming
    host and port (mirrors the relational connect-timeout contract)."""
    monkeypatch.setenv("TINA4_GRAPH_CONNECT_TIMEOUT", "2")
    started = time.monotonic()
    with pytest.raises(GraphConnectTimeout) as excinfo:
        # 10.255.255.1 completes no handshake — a real black hole, not a refusal.
        GraphDatabase.create("ultipa://admin:x@10.255.255.1:60071/default").get_node("x")
    elapsed = time.monotonic() - started
    assert elapsed < 6
    assert "10.255.255.1" in str(excinfo.value) and "60071" in str(excinfo.value)
