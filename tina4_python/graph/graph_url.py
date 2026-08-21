# Graph connection URL parser — the DatabaseUrl sibling for graph engines.
"""Parse a graph connection URL into its parts, the same way DatabaseUrl does
for SQL. Engine is the CANONICAL name the factory selects an adapter by; a
scheme alias (bolt -> neo4j is NOT assumed — bolt stays bolt so Memgraph can
share it) resolves to its engine here.
"""
from urllib.parse import urlparse, parse_qs, unquote


# scheme -> canonical engine. bolt/neo4j/memgraph all speak Bolt/Cypher and share
# ONE adapter ("bolt"); the engine label only tunes per-engine defaults.
_SCHEME_ENGINE = {
    "ultipa": "ultipa",
    "ultipas": "ultipa",      # TLS variant
    "neo4j": "bolt",
    "neo4j+s": "bolt",
    "bolt": "bolt",
    "bolt+s": "bolt",
    "memgraph": "bolt",
    "arango": "arango",
    "arangodb": "arango",
}

# Default port per engine when the URL omits one.
_ENGINE_DEFAULT_PORT = {
    "ultipa": 60061,
    "bolt": 7687,
    "arango": 8529,
}


class GraphUrl:
    """A parsed graph URL: engine, host, port, graph, credentials, params."""

    def __init__(self, url: str):
        self.raw = url
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        engine = _SCHEME_ENGINE.get(scheme)
        if engine is None:
            raise ValueError(
                f"Unsupported graph URL scheme {scheme!r}. Supported: "
                f"{', '.join(sorted(_SCHEME_ENGINE))} "
                f"(e.g. ultipa://host:60061/mygraph)."
            )
        self.scheme = scheme
        self.engine = engine
        self.host = parsed.hostname or "localhost"
        self.port = parsed.port or _ENGINE_DEFAULT_PORT.get(engine)
        # path is the graph/database name (leading slash stripped).
        self.graph = (parsed.path or "").lstrip("/") or None
        self.username = unquote(parsed.username) if parsed.username else None
        self.password = unquote(parsed.password) if parsed.password else None
        self.params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        # TLS if the scheme says so (…s) or ?tls=1.
        self.use_tls = scheme.endswith("s") or self.params.get("tls") in ("1", "true")

    def get_dsn(self) -> str:
        """host:port/graph — for messages, never carrying credentials."""
        target = f"{self.host}:{self.port}" if self.port else self.host
        return f"{target}/{self.graph}" if self.graph else target

    @staticmethod
    def from_env(env_key: str = "TINA4_GRAPH_URL") -> "GraphUrl | None":
        import os
        url = os.environ.get(env_key)
        return GraphUrl(url) if url else None
