# Ultipa graph adapter — the portable core built in GQL over tina4_ultipa.
"""Wraps the standalone tina4-ultipa driver (an OPTIONAL dependency — imported
here, so `import tina4_python.graph` stays driver-free). The portable
node/edge/traverse surface is expressed in Ultipa GQL on top of the driver's
query()/execute(); raw query()/execute() send GQL straight through.

GQL note: the exact statements are verified against the live Ultipa community
edition on the lab (no mocks). Ultipa node/edge ids are the engine's own; we echo
back whatever id(n)/id(e) returns without assuming a type.
"""
import time

# The driver is optional: this import is what makes a missing driver surface as
# the actionable install error in GraphDatabase.create.
from tina4_ultipa import UltipaClient
from tina4_ultipa.errors import UltipaError, UltipaConnectError

from tina4_python.graph import (
    GraphNode, GraphEdge, GraphResult, resolve_graph_connect_timeout,
)
from tina4_python.graph.adapter import GraphAdapter, GraphError, GraphConnectTimeout


def _prop_clause(properties):
    """Build a GQL property map `{k1: $p_k1, ...}` + the param dict for it.

    Params are BOUND (never interpolated), matching the relational ?-placeholder
    rule. Keys are namespaced (`p_`) so they never collide with an id param.
    """
    properties = properties or {}
    if not properties:
        return "{}", {}
    pairs = ", ".join(f"{key}: $p_{key}" for key in properties)
    params = {f"p_{key}": value for key, value in properties.items()}
    return "{" + pairs + "}", params


class UltipaGraphAdapter(GraphAdapter):
    def __init__(self, graph_url, username="", password=""):
        self._url = graph_url
        self._last_error = None
        self._client = UltipaClient(
            host=graph_url.host,
            port=graph_url.port,
            username=graph_url.username or username or None,
            password=graph_url.password or password or None,
            graph=graph_url.graph,
            connect_timeout=resolve_graph_connect_timeout() or 0,
            use_tls=graph_url.use_tls,
        )

    # -- connection + raw pass-through -------------------------------------
    def _run(self, gql, params=None, read_only=True):
        try:
            self._client.connect()
        except UltipaConnectError as exc:
            self._last_error = str(exc)
            raise GraphConnectTimeout(
                f"Graph connect to {self._url.host}:{self._url.port} timed out after "
                f"{getattr(exc, 'elapsed', 0):.1f}s (TINA4_GRAPH_CONNECT_TIMEOUT). "
                f"Raise TINA4_GRAPH_CONNECT_TIMEOUT if the server is simply slow, "
                f"or set it to 0 to wait indefinitely."
            ) from exc
        try:
            return self._client.query(gql, params=params, read_only=read_only)
        except UltipaError as exc:
            self._last_error = str(exc)
            raise GraphError(str(exc)) from exc

    def query(self, text, params=None):
        result = self._run(text, params=params, read_only=True)
        return GraphResult(records=result.dicts(), columns=result.columns)

    def execute(self, text, params=None):
        result = self._run(text, params=params, read_only=False)
        return GraphResult(records=result.dicts(), columns=result.columns)

    # -- portable node/edge/traverse core (GQL) ----------------------------
    def _node_from_row(self, row):
        if row is None:
            return None
        return GraphNode(id=row.get("id"), labels=row.get("labels"),
                         properties=row.get("props") or {})

    def add_node(self, label, properties=None):
        prop_map, params = _prop_clause(properties)
        gql = (f"INSERT (n:`{label}` {prop_map}) "
               f"RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props")
        rows = self._run(gql, params=params, read_only=False).dicts()
        return self._node_from_row(rows[0]) if rows else None

    def add_edge(self, from_id, to_id, type, properties=None):
        # id(e) requires EDGE_ID enabled on the Ultipa graph
        # (`ALTER GRAPH <g> SET EDGE_ID ENABLED`), a one-time per-graph setting.
        prop_map, params = _prop_clause(properties)
        params.update({"from_id": from_id, "to_id": to_id})
        gql = (f"MATCH (a), (b) WHERE id(a) = $from_id AND id(b) = $to_id "
               f"INSERT (a)-[e:`{type}` {prop_map}]->(b) "
               f"RETURN id(e) AS id, type(e) AS type, id(a) AS f, id(b) AS t, "
               f"properties(e) AS props")
        rows = self._run(gql, params=params, read_only=False).dicts()
        if not rows:
            return None
        r = rows[0]
        return GraphEdge(id=r.get("id"), type=r.get("type"), from_id=r.get("f"),
                         to_id=r.get("t"), properties=r.get("props") or {})

    def get_node(self, node_id):
        gql = ("MATCH (n) WHERE id(n) = $id "
               "RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props")
        rows = self._run(gql, params={"id": node_id}, read_only=True).dicts()
        return self._node_from_row(rows[0]) if rows else None

    def update_node(self, node_id, properties):
        sets = ", ".join(f"n.{key} = $p_{key}" for key in (properties or {}))
        params = {f"p_{key}": value for key, value in (properties or {}).items()}
        params["id"] = node_id
        gql = (f"MATCH (n) WHERE id(n) = $id SET {sets} "
               f"RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props")
        rows = self._run(gql, params=params, read_only=False).dicts()
        return self._node_from_row(rows[0]) if rows else None

    def delete_node(self, node_id):
        gql = "MATCH (n) WHERE id(n) = $id DETACH DELETE n"
        self._run(gql, params={"id": node_id}, read_only=False)
        return True

    def neighbors(self, node_id, direction="both", edge_type=None, limit=100):
        edge = f":`{edge_type}`" if edge_type else ""
        pattern = {
            "out": f"(n)-[{edge}]->(m)",
            "in": f"(n)<-[{edge}]-(m)",
            "both": f"(n)-[{edge}]-(m)",
        }.get(direction, f"(n)-[{edge}]-(m)")
        gql = (f"MATCH {pattern} WHERE id(n) = $id "
               f"RETURN DISTINCT id(m) AS id, labels(m) AS labels, properties(m) AS props "
               f"LIMIT {int(limit)}")
        rows = self._run(gql, params={"id": node_id}, read_only=True).dicts()
        return [self._node_from_row(r) for r in rows]

    def traverse(self, start_id, depth=1, direction="both", edge_type=None, limit=1000):
        # Ultipa GQL uses the ISO quantified-path form `-[]->{1,N}`, NOT Cypher's
        # `-[*1..N]->` (which is a parse error on gqldb).
        edge = f":`{edge_type}`" if edge_type else ""
        quant = "{1," + str(int(depth)) + "}"
        pattern = {
            "out": f"(n)-[{edge}]->{quant}(m)",
            "in": f"(n)<-[{edge}]-{quant}(m)",
            "both": f"(n)-[{edge}]-{quant}(m)",
        }.get(direction, f"(n)-[{edge}]-{quant}(m)")
        gql = (f"MATCH {pattern} WHERE id(n) = $start "
               f"RETURN DISTINCT id(m) AS id, labels(m) AS labels, properties(m) AS props "
               f"LIMIT {int(limit)}")
        rows = self._run(gql, params={"start": start_id}, read_only=True).dicts()
        return [self._node_from_row(r) for r in rows]

    def close(self):
        self._client.close()
