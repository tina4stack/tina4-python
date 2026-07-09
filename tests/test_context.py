"""Real, no-mock tests for the native ``Context`` code/doc grounding subsystem.

Every test uses a REAL temp SQLite file (``tmp_path``) and REAL temp source
files — there is nothing to mock. They pin the four behaviours the MVP promises:

1. ranking: a definition out-ranks a test that merely mentions the symbol
   (source-over-tests + definition-first reorder over ``bm25()``);
2. reindex-on-change: ``index_path`` is an UPSERT — new content is found and
   the file's old chunks are gone, with no row duplication;
3. FTS5 availability guard: detected for real, and a Context that finds FTS5
   absent degrades to safe no-ops instead of crashing;
4. result shape + the dev-MCP ``code_search`` tool over a real temp project.
"""

import json
import os

import pytest

from tina4_python.context import Context


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _write(root, rel, body):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# 1. ranking — definition above a test that mentions the symbol
# --------------------------------------------------------------------------- #
def test_definition_outranks_test_that_mentions_symbol(tmp_path):
    src_root = tmp_path / "app"
    _write(src_root, "src/auth.py",
           "def get_token(user):\n"
           "    '''issue an auth token for a user'''\n"
           "    return _sign(user)\n")
    # a test file that MENTIONS get_token many times (BM25 loves this) but
    # does not DEFINE it — it must not out-rank the definition.
    _write(src_root, "tests/test_auth.py",
           "def test_get_token():\n"
           "    assert get_token(1)\n"
           "    assert get_token(2)\n"
           "    assert get_token(3)\n"
           "    assert get_token(4)\n")

    ctx = Context(tmp_path / ".tina4" / "context.db")
    n = ctx.index_root(src_root)
    assert n > 0

    res = ctx.search("get_token", k=5)
    paths = [r["path"] for r in res]
    # both files surface
    assert any(p.endswith("auth.py") and "test" not in p for p in paths), paths
    assert any("test_auth" in p for p in paths), paths
    # the definition (non-test source) ranks ABOVE the test file
    src_idx = next(i for i, r in enumerate(res)
                   if r["path"].endswith("auth.py") and "test" not in r["path"])
    test_idx = next(i for i, r in enumerate(res) if "test_auth" in r["path"])
    assert src_idx < test_idx, f"definition should out-rank the test: {paths}"
    # and the very top hit is the definition, not the test
    assert "test" not in res[0]["path"], paths
    ctx.close()


# --------------------------------------------------------------------------- #
# 2. reindex-on-change — UPSERT: new found, old gone, no duplication
# --------------------------------------------------------------------------- #
def test_reindex_on_change_is_upsert(tmp_path):
    src_root = tmp_path / "app"
    f = _write(src_root, "src/mod.py", "def alpha():\n    return 1\n")

    ctx = Context(tmp_path / ".tina4" / "context.db")
    ctx.index_path(f, label="src/mod.py")

    assert any(r["path"] == "src/mod.py" for r in ctx.search("alpha")), "alpha should be found first"
    rows_before = ctx.count()

    # edit the file: alpha -> beta, then re-index just this file
    f.write_text("def beta():\n    return 2\n", encoding="utf-8")
    ctx.index_path(f, label="src/mod.py")

    # new content retrievable
    assert any(r["path"] == "src/mod.py" for r in ctx.search("beta")), "beta should be found after reindex"
    # OLD content for this file is gone (upsert deleted the stale chunks)
    assert not any(r["path"] == "src/mod.py" for r in ctx.search("alpha")), "alpha chunks must be gone"
    # no duplication — same file, same chunk count => same total rows
    assert ctx.count() == rows_before, "UPSERT must delete-then-insert, not append"
    ctx.close()


def test_index_path_second_call_replaces_not_appends(tmp_path):
    """Indexing the SAME unchanged file twice must not double its rows."""
    src_root = tmp_path / "app"
    f = _write(src_root, "src/dup.py", "def only_one():\n    return 42\n")
    ctx = Context(tmp_path / ".tina4" / "context.db")
    ctx.index_path(f, label="src/dup.py")
    n1 = ctx.count()
    ctx.index_path(f, label="src/dup.py")
    assert ctx.count() == n1, "re-indexing an unchanged file must not append duplicates"
    ctx.close()


# --------------------------------------------------------------------------- #
# 3. FTS5 availability guard
# --------------------------------------------------------------------------- #
def test_fts5_available_on_this_interpreter():
    # real detector — this build of sqlite ships FTS5, so it must report True
    assert Context.fts5_available() is True


def test_context_degrades_gracefully_without_fts5(tmp_path):
    src_root = tmp_path / "app"
    _write(src_root, "src/x.py", "def y():\n    return 1\n")

    # inject a predicate that reports FTS5 as ABSENT — exercises the real
    # graceful-degradation branch (no mocking of sqlite or files).
    ctx = Context(tmp_path / ".tina4" / "context.db", fts5_check=lambda: False)
    assert ctx.available is False
    assert ctx.index_root(src_root) == 0
    assert ctx.index_path(src_root / "src" / "x.py", label="src/x.py") == 0
    assert ctx.search("anything") == []
    ctx.close()

    # a normal Context on this interpreter IS available
    ok = Context(tmp_path / ".tina4" / "ok.db")
    assert ok.available is True
    ok.close()


# --------------------------------------------------------------------------- #
# 4. result shape, score ordering, doc chunking, dir skipping
# --------------------------------------------------------------------------- #
def test_search_result_shape_and_score_ordering(tmp_path):
    src_root = tmp_path / "app"
    _write(src_root, "src/widget.py",
           "def build_widget(spec):\n    return Widget(spec)\n\n"
           "class Widget:\n    pass\n")
    ctx = Context(tmp_path / ".tina4" / "context.db")
    ctx.index_root(src_root)

    res = ctx.search("build_widget", k=5)
    assert res, "expected at least one hit"
    for r in res:
        assert set(r) >= {"path", "score", "snippet"}, r
        assert isinstance(r["score"], float)
        assert isinstance(r["snippet"], str) and r["snippet"]
    # higher score = better; results are sorted descending
    scores = [r["score"] for r in res]
    assert scores == sorted(scores, reverse=True), scores
    ctx.close()


def test_indexes_docs_as_prose_and_skips_vendor_dirs(tmp_path):
    src_root = tmp_path / "app"
    _write(src_root, "docs/guide.md",
           "# Overview\n\nThe whirligig subsystem manages the flux capacitor "
           "and its temporal bindings.\n")
    # these live under dirs neemee skips — they must NOT be indexed
    _write(src_root, "__pycache__/junk.py", "def whirligig_flux_capacitor(): pass\n")
    _write(src_root, "node_modules/lib.js", "function whirligigFluxCapacitor(){}\n")

    ctx = Context(tmp_path / ".tina4" / "context.db")
    ctx.index_root(src_root)

    res = ctx.search("whirligig flux capacitor", k=5)
    paths = [r["path"] for r in res]
    assert any(p.endswith("guide.md") for p in paths), paths
    assert not any("__pycache__" in p for p in paths), paths
    assert not any("node_modules" in p for p in paths), paths
    ctx.close()


def test_empty_or_stopword_query_returns_empty(tmp_path):
    src_root = tmp_path / "app"
    _write(src_root, "src/a.py", "def a():\n    return 1\n")
    ctx = Context(tmp_path / ".tina4" / "context.db")
    ctx.index_root(src_root)
    assert ctx.search("") == []
    assert ctx.search("   ") == []
    ctx.close()


# --------------------------------------------------------------------------- #
# 5. dev-MCP `code_search` tool — real registration over a temp project
# --------------------------------------------------------------------------- #
class TestCodeSearchTool:
    def _server_in(self, project_dir):
        from tina4_python.mcp import McpServer
        from tina4_python.mcp.tools import register_dev_tools
        server = McpServer("/test-code-search", name="code_search test")
        register_dev_tools(server)
        return server

    def _call(self, server, name, arguments=None):
        return json.loads(server.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }))

    def test_code_search_registered_and_finds_symbol(self, tmp_path):
        # real temp Tina4-ish project
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "service.py").write_text(
            "def widget_factory(name):\n"
            "    '''create a configured widget'''\n"
            "    return {'name': name}\n",
            encoding="utf-8",
        )
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            server = self._server_in(tmp_path)
            # tool is registered (sibling of api_search)
            listed = json.loads(server.handle_message({
                "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
            }))
            names = {t["name"] for t in listed["result"]["tools"]}
            assert "code_search" in names, names

            resp = self._call(server, "code_search", {"query": "widget_factory"})
            assert "result" in resp, resp
            payload = json.loads(resp["result"]["content"][0]["text"])
            assert isinstance(payload, list), payload
            paths = [r["path"] for r in payload]
            assert any(p.endswith("service.py") for p in paths), payload
        finally:
            os.chdir(old_cwd)
