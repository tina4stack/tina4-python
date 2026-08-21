# Tina4 graph data layer — a URL-selected graph database, shaped like Database.
"""One factory (`GraphDatabase.create` / `.from_env`), one portable
node/edge/traverse surface plus a raw `query`/`execute` pass-through, and neutral
`GraphNode` / `GraphEdge` / `GraphResult` shapes — the exact mirror of the
relational `Database` layer, for graph engines (Ultipa first). Engine drivers are
OPTIONAL and imported only on first use, so the zero-dependency core is preserved.

See ADR-0059 and tina4-documentation/plan/v3/features/139-graph-databases.md.
"""
import os

from .graph_url import GraphUrl
from .adapter import GraphDatabase, GraphAdapter, GraphError, GraphConnectTimeout

# The graph connect bound — sibling of TINA4_DATABASE_CONNECT_TIMEOUT.
GRAPH_CONNECT_TIMEOUT_VARIABLE = "TINA4_GRAPH_CONNECT_TIMEOUT"
DEFAULT_GRAPH_CONNECT_TIMEOUT_SECONDS = 10.0


def resolve_graph_connect_timeout() -> float | None:
    """Seconds a graph connect may block; None means unbounded (<= 0).

    Mirrors resolve_connect_timeout: a value <= 0 disables the bound, a
    non-number warns and falls back to the default rather than waiting forever.
    """
    raw = os.environ.get(GRAPH_CONNECT_TIMEOUT_VARIABLE, "").strip()
    if not raw:
        return DEFAULT_GRAPH_CONNECT_TIMEOUT_SECONDS
    try:
        seconds = float(raw)
    except ValueError:
        from tina4_python.debug import Log
        Log.warning(
            f"{GRAPH_CONNECT_TIMEOUT_VARIABLE}={raw!r} is not a number of seconds — "
            f"bounding graph connects at the {DEFAULT_GRAPH_CONNECT_TIMEOUT_SECONDS:g}s default instead"
        )
        return DEFAULT_GRAPH_CONNECT_TIMEOUT_SECONDS
    return None if seconds <= 0 else seconds


class GraphNode:
    """Engine-neutral vertex: id, labels, properties."""

    __slots__ = ("id", "labels", "properties")

    def __init__(self, id, labels=None, properties=None):
        self.id = id
        self.labels = list(labels or [])
        self.properties = dict(properties or {})

    def to_dict(self) -> dict:
        return {"id": self.id, "labels": self.labels, "properties": self.properties}

    def __repr__(self):
        return f"GraphNode(id={self.id!r}, labels={self.labels!r})"


class GraphEdge:
    """Engine-neutral edge: id, type, from/to node ids, properties."""

    __slots__ = ("id", "type", "from_id", "to_id", "properties")

    def __init__(self, id, type, from_id, to_id, properties=None):
        self.id = id
        self.type = type
        self.from_id = from_id
        self.to_id = to_id
        self.properties = dict(properties or {})

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type,
            "from": self.from_id, "to": self.to_id,
            "properties": self.properties,
        }

    def __repr__(self):
        return f"GraphEdge(id={self.id!r}, type={self.type!r}, {self.from_id!r}->{self.to_id!r})"


class GraphResult:
    """A raw-query result — records + columns, same shape as DatabaseResult."""

    __slots__ = ("records", "columns")

    def __init__(self, records=None, columns=None):
        self.records = list(records or [])
        self.columns = list(columns or [])

    def to_array(self) -> list:
        return self.records

    def scalar(self):
        if not self.records:
            return None
        first = self.records[0]
        if isinstance(first, dict):
            return next(iter(first.values()), None)
        return first[0] if first else None

    def __iter__(self):
        return iter(self.records)

    def __len__(self):
        return len(self.records)


__all__ = [
    "GraphDatabase", "GraphAdapter", "GraphUrl",
    "GraphNode", "GraphEdge", "GraphResult",
    "GraphError", "GraphConnectTimeout",
    "resolve_graph_connect_timeout",
    "GRAPH_CONNECT_TIMEOUT_VARIABLE", "DEFAULT_GRAPH_CONNECT_TIMEOUT_SECONDS",
]
