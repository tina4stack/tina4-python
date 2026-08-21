# ArangoDB graph adapter — the document/AQL engine behind the same surface.
"""Wraps the community `python-arango` driver (an OPTIONAL dependency — imported
here, so `import tina4_python.graph` stays driver-free). Arango is a document
store, not a labelled-property graph, so the portable core maps onto ONE vertex
collection + ONE edge collection: a node's `labels` and an edge's `type` are
stored as document fields, ids are Arango `_id` handles (e.g. `tina4_nodes/123`),
and traversal uses AQL `FOR v IN 1..N OUTBOUND ...`. Raw query()/execute() take
AQL directly.
"""
from arango import ArangoClient
from arango.exceptions import ArangoError, ArangoClientError, ArangoServerError

from tina4_python.graph import (
    GraphNode, GraphEdge, GraphResult, resolve_graph_connect_timeout,
)
from tina4_python.graph.adapter import GraphAdapter, GraphError, GraphConnectTimeout

VERTEX_COLLECTION = "tina4_nodes"
EDGE_COLLECTION = "tina4_edges"
_RESERVED = {"_id", "_key", "_rev", "_from", "_to", "_labels", "_type"}


def _clean_props(doc):
    return {k: v for k, v in doc.items() if k not in _RESERVED}


class ArangoGraphAdapter(GraphAdapter):
    def __init__(self, graph_url, username="", password=""):
        self._url = graph_url
        self._last_error = None
        timeout = resolve_graph_connect_timeout()
        scheme = "https" if graph_url.use_tls else "http"
        self._client = ArangoClient(
            hosts=f"{scheme}://{graph_url.host}:{graph_url.port}",
            request_timeout=timeout,
        )
        user = graph_url.username or username or "root"
        pwd = graph_url.password or password or ""
        database = graph_url.graph or "_system"
        try:
            self._db = self._client.db(database, username=user, password=pwd)
            if not self._db.has_collection(VERTEX_COLLECTION):
                self._db.create_collection(VERTEX_COLLECTION)
            if not self._db.has_collection(EDGE_COLLECTION):
                self._db.create_collection(EDGE_COLLECTION, edge=True)
        except (ArangoClientError, ArangoServerError) as exc:
            self._last_error = str(exc)
            raise self._connect_or_error(exc)

    def _connect_or_error(self, exc):
        text = str(exc).lower()
        if "timed out" in text or "connection" in text or "max retries" in text:
            return GraphConnectTimeout(
                f"Graph connect to {self._url.host}:{self._url.port} timed out "
                f"(TINA4_GRAPH_CONNECT_TIMEOUT). Raise it if the server is simply "
                f"slow, or set it to 0 to wait indefinitely."
            )
        return GraphError(str(exc))

    def _aql(self, query, bind=None):
        try:
            return list(self._db.aql.execute(query, bind_vars=bind or {}))
        except (ArangoClientError, ArangoServerError) as exc:
            self._last_error = str(exc)
            err = self._connect_or_error(exc)
            raise err
        except ArangoError as exc:
            self._last_error = str(exc)
            raise GraphError(str(exc)) from exc

    def query(self, text, params=None):
        rows = self._aql(text, params)
        columns = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []
        return GraphResult(records=rows, columns=columns)

    def execute(self, text, params=None):
        return self.query(text, params)

    def _node(self, doc):
        if doc is None:
            return None
        return GraphNode(id=doc.get("_id"), labels=doc.get("_labels") or [],
                         properties=_clean_props(doc))

    def add_node(self, label, properties=None):
        doc = dict(properties or {})
        doc["_labels"] = [label]
        rows = self._aql(
            f"INSERT @doc INTO {VERTEX_COLLECTION} RETURN NEW", {"doc": doc})
        return self._node(rows[0]) if rows else None

    def add_edge(self, from_id, to_id, type, properties=None):
        doc = dict(properties or {})
        doc.update({"_from": from_id, "_to": to_id, "_type": type})
        rows = self._aql(
            f"INSERT @doc INTO {EDGE_COLLECTION} RETURN NEW", {"doc": doc})
        if not rows:
            return None
        r = rows[0]
        return GraphEdge(id=r.get("_id"), type=r.get("_type"), from_id=r.get("_from"),
                         to_id=r.get("_to"), properties=_clean_props(r))

    def get_node(self, node_id):
        rows = self._aql("RETURN DOCUMENT(@id)", {"id": node_id})
        return self._node(rows[0]) if rows and rows[0] else None

    def update_node(self, node_id, properties):
        rows = self._aql(
            f"UPDATE PARSE_IDENTIFIER(@id).key WITH @props IN {VERTEX_COLLECTION} RETURN NEW",
            {"id": node_id, "props": properties or {}})
        return self._node(rows[0]) if rows else None

    def delete_node(self, node_id):
        # remove the node and any edges touching it, so a re-read is a clean miss.
        self._aql(
            f"FOR e IN {EDGE_COLLECTION} FILTER e._from == @id OR e._to == @id "
            f"REMOVE e IN {EDGE_COLLECTION}", {"id": node_id})
        self._aql(
            f"REMOVE PARSE_IDENTIFIER(@id).key IN {VERTEX_COLLECTION}", {"id": node_id})
        return True

    def neighbors(self, node_id, direction="both", edge_type=None, limit=100):
        arango_dir = {"out": "OUTBOUND", "in": "INBOUND", "both": "ANY"}.get(direction, "ANY")
        type_filter = "FILTER e._type == @etype " if edge_type else ""
        bind = {"start": node_id, "limit": int(limit)}
        if edge_type:
            bind["etype"] = edge_type
        rows = self._aql(
            f"FOR v, e IN 1..1 {arango_dir} @start {EDGE_COLLECTION} "
            f"{type_filter}LIMIT @limit RETURN DISTINCT v", bind)
        return [self._node(v) for v in rows]

    def traverse(self, start_id, depth=1, direction="both", edge_type=None, limit=1000):
        arango_dir = {"out": "OUTBOUND", "in": "INBOUND", "both": "ANY"}.get(direction, "ANY")
        type_filter = "FILTER e._type == @etype " if edge_type else ""
        bind = {"start": start_id, "limit": int(limit)}
        if edge_type:
            bind["etype"] = edge_type
        rows = self._aql(
            f"FOR v, e IN 1..{int(depth)} {arango_dir} @start {EDGE_COLLECTION} "
            f"{type_filter}LIMIT @limit RETURN DISTINCT v", bind)
        return [self._node(v) for v in rows]

    def close(self):
        self._client.close()
