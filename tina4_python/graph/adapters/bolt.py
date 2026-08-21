# Bolt graph adapter — Neo4j AND Memgraph (both speak Bolt + Cypher).
"""Wraps the community `neo4j` Python driver (an OPTIONAL dependency — imported
here, so `import tina4_python.graph` stays driver-free). Neo4j and Memgraph share
this ONE adapter; the URL scheme only picks the engine label and default port.

Cypher note (verified against live Neo4j + Memgraph): `id(n)` is the portable
node/edge id (an integer on both — Neo4j's `elementId` is Neo4j-only, Memgraph
has no `elementId`); variable-length traversal is Cypher's `[*1..N]` (the
opposite of Ultipa's GQL `{1,N}`); `SET n += $props` merges.
"""
from neo4j import GraphDatabase as _Neo4jDriver
from neo4j.exceptions import Neo4jError, ServiceUnavailable, DriverError

from tina4_python.graph import (
    GraphNode, GraphEdge, GraphResult, resolve_graph_connect_timeout,
)
from tina4_python.graph.adapter import GraphAdapter, GraphError, GraphConnectTimeout


class BoltGraphAdapter(GraphAdapter):
    def __init__(self, graph_url, username="", password=""):
        self._url = graph_url
        self._database = graph_url.graph or None
        self._last_error = None
        user = graph_url.username or username or "neo4j"
        pwd = graph_url.password or password or ""
        scheme = "bolt+s" if graph_url.use_tls else "bolt"
        uri = f"{scheme}://{graph_url.host}:{graph_url.port}"
        timeout = resolve_graph_connect_timeout()
        cfg = {}
        if timeout is not None:
            cfg["connection_timeout"] = timeout
            cfg["connection_acquisition_timeout"] = timeout
            cfg["max_transaction_retry_time"] = timeout
        self._driver = _Neo4jDriver.driver(uri, auth=(user, pwd), **cfg)

    def _run(self, cypher, params=None):
        try:
            with self._driver.session(database=self._database) as session:
                result = session.run(cypher, parameters=params or {})
                return [record.data() for record in result]
        except (ServiceUnavailable, DriverError) as exc:
            self._last_error = str(exc)
            # An unreachable host surfaces here as a service-unavailable/timeout.
            if "timed out" in str(exc).lower() or isinstance(exc, ServiceUnavailable):
                raise GraphConnectTimeout(
                    f"Graph connect to {self._url.host}:{self._url.port} timed out "
                    f"(TINA4_GRAPH_CONNECT_TIMEOUT). Raise it if the server is simply "
                    f"slow, or set it to 0 to wait indefinitely."
                ) from exc
            raise GraphError(str(exc)) from exc
        except Neo4jError as exc:
            self._last_error = str(exc)
            raise GraphError(str(exc)) from exc

    def query(self, text, params=None):
        rows = self._run(text, params)
        columns = list(rows[0].keys()) if rows else []
        return GraphResult(records=rows, columns=columns)

    def execute(self, text, params=None):
        return self.query(text, params)

    def _node(self, row):
        if row is None:
            return None
        return GraphNode(id=row.get("id"), labels=row.get("labels"),
                         properties=row.get("props") or {})

    def add_node(self, label, properties=None):
        cypher = (f"CREATE (n:`{label}` $props) "
                  f"RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props")
        rows = self._run(cypher, {"props": properties or {}})
        return self._node(rows[0]) if rows else None

    def add_edge(self, from_id, to_id, type, properties=None):
        cypher = (f"MATCH (a), (b) WHERE id(a) = $from_id AND id(b) = $to_id "
                  f"CREATE (a)-[e:`{type}` $props]->(b) "
                  f"RETURN id(e) AS id, type(e) AS type, id(a) AS f, id(b) AS t, "
                  f"properties(e) AS props")
        rows = self._run(cypher, {"from_id": from_id, "to_id": to_id, "props": properties or {}})
        if not rows:
            return None
        r = rows[0]
        return GraphEdge(id=r.get("id"), type=r.get("type"), from_id=r.get("f"),
                         to_id=r.get("t"), properties=r.get("props") or {})

    def get_node(self, node_id):
        cypher = ("MATCH (n) WHERE id(n) = $id "
                  "RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props")
        rows = self._run(cypher, {"id": node_id})
        return self._node(rows[0]) if rows else None

    def update_node(self, node_id, properties):
        cypher = ("MATCH (n) WHERE id(n) = $id SET n += $props "
                  "RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props")
        rows = self._run(cypher, {"id": node_id, "props": properties or {}})
        return self._node(rows[0]) if rows else None

    def delete_node(self, node_id):
        self._run("MATCH (n) WHERE id(n) = $id DETACH DELETE n", {"id": node_id})
        return True

    def neighbors(self, node_id, direction="both", edge_type=None, limit=100):
        edge = f":`{edge_type}`" if edge_type else ""
        pattern = {
            "out": f"(n)-[{edge}]->(m)",
            "in": f"(n)<-[{edge}]-(m)",
            "both": f"(n)-[{edge}]-(m)",
        }.get(direction, f"(n)-[{edge}]-(m)")
        cypher = (f"MATCH {pattern} WHERE id(n) = $id "
                  f"RETURN DISTINCT id(m) AS id, labels(m) AS labels, properties(m) AS props "
                  f"LIMIT {int(limit)}")
        return [self._node(r) for r in self._run(cypher, {"id": node_id})]

    def traverse(self, start_id, depth=1, direction="both", edge_type=None, limit=1000):
        # Cypher variable-length path `[*1..N]` — Neo4j AND Memgraph.
        edge = f":`{edge_type}`" if edge_type else ""
        arrow = {"out": f"-[{edge}*1..{int(depth)}]->", "in": f"<-[{edge}*1..{int(depth)}]-",
                 "both": f"-[{edge}*1..{int(depth)}]-"}.get(direction, f"-[{edge}*1..{int(depth)}]-")
        cypher = (f"MATCH (n){arrow}(m) WHERE id(n) = $start "
                  f"RETURN DISTINCT id(m) AS id, labels(m) AS labels, properties(m) AS props "
                  f"LIMIT {int(limit)}")
        return [self._node(r) for r in self._run(cypher, {"start": start_id})]

    def close(self):
        self._driver.close()
