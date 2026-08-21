# GraphAdapter contract + the GraphDatabase URL-selected factory.
"""Every engine adapter implements GraphAdapter; GraphDatabase.create picks one
by URL scheme and imports its driver lazily — a missing driver raises an
actionable install error, never a bare ImportError, and the core imports with no
driver present (the zero-dependency-core rule).
"""
import os

from .graph_url import GraphUrl


class GraphError(Exception):
    """A graph operation failed (bad statement, engine error)."""


class GraphConnectTimeout(TimeoutError):
    """A graph connect exceeded TINA4_GRAPH_CONNECT_TIMEOUT.

    A subclass of the builtin TimeoutError, so ``except TimeoutError`` catches it
    without importing anything from Tina4 — same as DatabaseConnectTimeout.
    """


# engine -> (module, class, install-package, install-command). Selected lazily so
# importing tina4_python.graph pulls in NO engine driver.
_ENGINE_ADAPTERS = {
    "ultipa": ("tina4_python.graph.adapters.ultipa", "UltipaGraphAdapter",
               "tina4-ultipa", "uv add tina4-ultipa   # or: pip install tina4-ultipa"),
    "bolt": ("tina4_python.graph.adapters.bolt", "BoltGraphAdapter",
             "neo4j", "uv add neo4j   # or: pip install neo4j"),
    "arango": ("tina4_python.graph.adapters.arango", "ArangoGraphAdapter",
               "python-arango", "uv add python-arango   # or: pip install python-arango"),
}


class GraphAdapter:
    """The one surface every graph engine implements. Raising stubs — a driver
    that does not override a method fails LOUDLY, naming itself and the method.
    """

    # -- portable node/edge/traverse core ----------------------------------
    def add_node(self, label, properties=None):
        raise NotImplementedError(f"{type(self).__name__} does not implement add_node")

    def add_edge(self, from_id, to_id, type, properties=None):
        raise NotImplementedError(f"{type(self).__name__} does not implement add_edge")

    def get_node(self, node_id):
        raise NotImplementedError(f"{type(self).__name__} does not implement get_node")

    def update_node(self, node_id, properties):
        raise NotImplementedError(f"{type(self).__name__} does not implement update_node")

    def delete_node(self, node_id):
        raise NotImplementedError(f"{type(self).__name__} does not implement delete_node")

    def neighbors(self, node_id, direction="both", edge_type=None, limit=100):
        raise NotImplementedError(f"{type(self).__name__} does not implement neighbors")

    def traverse(self, start_id, depth=1, direction="both", edge_type=None, limit=1000):
        raise NotImplementedError(f"{type(self).__name__} does not implement traverse")

    # -- raw pass-through (engine-native dialect) --------------------------
    def query(self, text, params=None):
        raise NotImplementedError(f"{type(self).__name__} does not implement query")

    def execute(self, text, params=None):
        raise NotImplementedError(f"{type(self).__name__} does not implement execute")

    # -- lifecycle ---------------------------------------------------------
    def close(self):
        raise NotImplementedError(f"{type(self).__name__} does not implement close")

    def get_error(self):
        """Cause of the last failed operation, or None."""
        return getattr(self, "_last_error", None)


class GraphDatabase:
    """URL-selected graph factory — the GraphDatabase sibling of Database."""

    @staticmethod
    def create(url: str, username: str = "", password: str = "") -> GraphAdapter:
        """Parse the URL, pick the engine adapter, connect lazily.

        The engine driver is imported only here (first use of that engine); if it
        is absent the error names the package and the install command.
        """
        graph_url = GraphUrl(url)
        registration = _ENGINE_ADAPTERS.get(graph_url.engine)
        if registration is None:
            raise GraphError(
                f"No graph adapter for engine {graph_url.engine!r} yet "
                f"(scheme {graph_url.scheme!r}). Available: "
                f"{', '.join(sorted(_ENGINE_ADAPTERS))}."
            )
        module_path, class_name, package, install_cmd = registration
        try:
            import importlib
            module = importlib.import_module(module_path)
        except ImportError as exc:
            # The adapter module imports its driver at module top; a missing
            # driver surfaces here as an actionable install error.
            raise GraphError(
                f"The graph driver for {graph_url.engine!r} is not installed "
                f"({package}). Install it with:\n    {install_cmd}"
            ) from exc
        adapter_class = getattr(module, class_name)
        return adapter_class(graph_url, username=username, password=password)

    @staticmethod
    def from_env(env_key: str = "TINA4_GRAPH_URL") -> "GraphAdapter | None":
        """Build from TINA4_GRAPH_URL (+ TINA4_GRAPH_USERNAME/_PASSWORD)."""
        url = os.environ.get(env_key)
        if not url:
            return None
        username = os.environ.get("TINA4_GRAPH_USERNAME", "")
        password = os.environ.get("TINA4_GRAPH_PASSWORD", "")
        return GraphDatabase.create(url, username=username, password=password)
