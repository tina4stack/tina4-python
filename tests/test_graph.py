# Contract suite for the graph data layer (Feature 139) — against REAL engines.
"""No mocks. Every live case runs a real connection and real round-trips, and is
PARAMETERISED over every provisioned engine (provider substitutability, exactly
like the relational engine matrix): Ultipa, Neo4j, Memgraph, ArangoDB. Each
engine's URL comes from its own TINA4_TEST_<ENGINE>_URL; an engine whose URL is
unset/unreachable is skipped. Case names match fixtures/graph_contract.json.

Only the raw-query dialect and the cleanup differ per engine (GQL vs Cypher vs
AQL) — the portable node/edge/traverse surface is identical everywhere, which is
the whole point of the layer.
"""
import os
import socket
import time
from urllib.parse import urlparse

import pytest

from tina4_python.graph import GraphDatabase, GraphNode, GraphEdge, GraphResult
from tina4_python.graph.adapter import GraphError, GraphConnectTimeout

LABEL = "T4GraphContractTest"

# Per-engine: env var for the URL, the raw read query (native dialect) that finds
# a node by name, and the cleanup statement for the test label.
_CYPHER_RAW = f"MATCH (n:`{LABEL}`) WHERE n.name = $nm RETURN n.name AS name"
_CYPHER_CLEAN = f"MATCH (n:`{LABEL}`) DETACH DELETE n"
ENGINES = {
    "ultipa": {"env": "TINA4_TEST_ULTIPA_URL", "raw": _CYPHER_RAW, "clean": _CYPHER_CLEAN},
    "neo4j": {"env": "TINA4_TEST_NEO4J_URL", "raw": _CYPHER_RAW, "clean": _CYPHER_CLEAN},
    "memgraph": {"env": "TINA4_TEST_MEMGRAPH_URL", "raw": _CYPHER_RAW, "clean": _CYPHER_CLEAN},
    "arango": {
        "env": "TINA4_TEST_ARANGO_URL",
        "raw": "FOR n IN tina4_nodes FILTER n.name == @nm RETURN {name: n.name}",
        "clean": f"FOR n IN tina4_nodes FILTER '{LABEL}' IN n._labels REMOVE n IN tina4_nodes",
    },
}


def _reachable(url) -> bool:
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname, parsed.port), timeout=2.0):
            return True
    except OSError:
        return False


def _live_engines():
    live = []
    for name, cfg in ENGINES.items():
        url = os.environ.get(cfg["env"])
        if url and _reachable(url):
            live.append(pytest.param(name, id=name))
        else:
            live.append(pytest.param(name, marks=pytest.mark.skip(
                reason=f"{name} not configured/reachable ({cfg['env']})"), id=name))
    return live


@pytest.fixture
def graph(request):
    """A connected adapter for the parametrised engine, on a clean slate."""
    cfg = ENGINES[request.param]
    db = GraphDatabase.create(os.environ[cfg["env"]])
    db.execute(cfg["clean"])
    db._t4_raw = cfg["raw"]  # stash the engine's raw read for the raw-query case
    try:
        yield db
    finally:
        db.execute(cfg["clean"])
        db.close()


live = pytest.mark.parametrize("graph", _live_engines(), indirect=True)


# ── driver-optional + URL routing run WITHOUT any live engine ───────────────

def test_graph_driver_optional():
    """The core imports with no engine driver; a missing driver raises an
    actionable install error naming the package and command."""
    import importlib
    importlib.import_module("tina4_python.graph")  # pulls in no engine driver
    from tina4_python.graph import adapter as adapter_module
    saved = adapter_module._ENGINE_ADAPTERS["ultipa"]
    adapter_module._ENGINE_ADAPTERS["ultipa"] = (
        "tina4_python.graph.adapters._absent", "X", "tina4-ultipa", "uv add tina4-ultipa")
    try:
        with pytest.raises(GraphError) as excinfo:
            GraphDatabase.create("ultipa://h:60061/g")
        assert "tina4-ultipa" in str(excinfo.value)
    finally:
        adapter_module._ENGINE_ADAPTERS["ultipa"] = saved


def test_graph_connect_by_url_selects_adapter():
    from tina4_python.graph import GraphUrl
    assert GraphUrl("ultipa://h:60061/g").engine == "ultipa"
    assert GraphUrl("neo4j://h/db").engine == "bolt"
    assert GraphUrl("memgraph://h/db").engine == "bolt"
    assert GraphUrl("arango://h/db").engine == "arango"
    with pytest.raises(ValueError):
        GraphUrl("mysql://h/db")


# ── the portable core + raw pass-through, per LIVE engine ───────────────────

@live
def test_graph_connect_by_url_live(graph):
    assert graph is not None


@live
def test_graph_add_node(graph):
    node = graph.add_node(LABEL, {"name": "Ada", "age": 36})
    assert isinstance(node, GraphNode)
    assert node.id is not None and LABEL in node.labels
    assert node.properties["name"] == "Ada" and node.properties["age"] == 36


@live
def test_graph_add_edge(graph):
    a = graph.add_node(LABEL, {"name": "Ada"})
    b = graph.add_node(LABEL, {"name": "Bob"})
    edge = graph.add_edge(a.id, b.id, "KNOWS", {"since": 2020})
    assert isinstance(edge, GraphEdge)
    assert edge.id is not None and edge.type == "KNOWS"
    assert edge.from_id == a.id and edge.to_id == b.id
    assert edge.properties["since"] == 2020


@live
def test_graph_get_node_roundtrip_and_miss(graph):
    a = graph.add_node(LABEL, {"name": "Ada", "age": 36})
    got = graph.get_node(a.id)
    assert got.properties["name"] == "Ada" and got.properties["age"] == 36
    tmp = graph.add_node(LABEL, {"x": 1})
    graph.delete_node(tmp.id)
    assert graph.get_node(tmp.id) is None  # a miss is not an error


@live
def test_graph_update_delete_node(graph):
    a = graph.add_node(LABEL, {"name": "Ada", "age": 36})
    graph.update_node(a.id, {"name": "Ada Lovelace", "city": "London"})
    updated = graph.get_node(a.id)
    assert updated.properties["name"] == "Ada Lovelace"
    assert updated.properties["city"] == "London"
    assert updated.properties["age"] == 36  # merge, not replace
    graph.delete_node(a.id)
    assert graph.get_node(a.id) is None


@live
def test_graph_neighbors(graph):
    a = graph.add_node(LABEL, {"name": "Ada"})
    b = graph.add_node(LABEL, {"name": "Bob"})
    graph.add_edge(a.id, b.id, "KNOWS", {})
    out = {n.id for n in graph.neighbors(a.id, direction="out", edge_type="KNOWS")}
    assert b.id in out and a.id not in out
    assert graph.neighbors(a.id, edge_type="NOPE") == []  # unmatched → empty


@live
def test_graph_traverse_depth(graph):
    a = graph.add_node(LABEL, {"name": "A"})
    b = graph.add_node(LABEL, {"name": "B"})
    c = graph.add_node(LABEL, {"name": "C"})
    graph.add_edge(a.id, b.id, "KNOWS", {})
    graph.add_edge(b.id, c.id, "KNOWS", {})
    reached = {n.id for n in graph.traverse(a.id, depth=2, direction="out", edge_type="KNOWS")}
    assert b.id in reached and c.id in reached  # 2 hops reach both


@live
def test_graph_raw_query_bound_params(graph):
    graph.add_node(LABEL, {"name": "Bob"})
    result = graph.query(graph._t4_raw, {"nm": "Bob"})
    assert isinstance(result, GraphResult)
    assert len(result) >= 1 and result.records[0]["name"] == "Bob"


@live
def test_graph_write_fails_loud(graph):
    with pytest.raises(GraphError):
        graph.execute("THIS IS NOT A VALID STATEMENT")
    assert graph.get_error() is not None


@pytest.mark.skipif(not os.environ.get("TINA4_TEST_ULTIPA_URL"),
                    reason="needs a graph engine port to point the black hole at")
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
