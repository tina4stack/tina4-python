"""
tina4_python.docs — Live API RAG test corpus.

Mirrors tina4-php/tests/DocsTest.php. Same test names, same
assertions, different language. Both files live RED until the
corresponding `Docs` module is implemented in each framework.

Spec: plan/v3/22-LIVE-API-RAG.md
"""
from __future__ import annotations

import os
import secrets
import shutil
import tempfile
import time
from pathlib import Path

import pytest

# These imports will FAIL until tina4_python.docs is implemented.
# That's the point of test-first — we know exactly what to build.
from tina4_python.docs import Docs  # noqa: E402


# ── Fixture project ────────────────────────────────────────────────


@pytest.fixture(scope="module")
def fixture_project() -> Path:
    """Build a deterministic fixture project under tempdir.

    Has a known shape (one user model, one user route, one user
    template) so user-code tests can assert without leaning on
    a real /tmp project.
    """
    root = Path(tempfile.gettempdir()) / f"tina4-docs-fixture-{secrets.token_hex(4)}"
    (root / "src" / "orm").mkdir(parents=True, exist_ok=True)
    (root / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (root / "src" / "templates").mkdir(parents=True, exist_ok=True)

    (root / "src" / "orm" / "User.py").write_text(
        '''"""User ORM model."""
from tina4_python.orm import ORM


class User(ORM):
    table_name = "users"
    primary_key = "id"

    @classmethod
    def find_by_email(cls, email: str):
        """Find a user by email — returns None if not found."""
        return None

    def _hash_password(self, plain: str) -> str:
        """Internal: hash a plaintext password."""
        return plain
''',
        encoding="utf-8",
    )

    (root / "src" / "routes" / "contact.py").write_text(
        '''from tina4_python.core.router import post


@post("/contact")
async def contact(request, response):
    return response({"ok": True})
''',
        encoding="utf-8",
    )

    (root / "src" / "templates" / "home.twig").write_text(
        """{% extends 'base.twig' %}
{% block content %}
  <h1>{{ title }}</h1>
{% endblock %}
""",
        encoding="utf-8",
    )

    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def docs(fixture_project: Path) -> Docs:
    return Docs(project_root=str(fixture_project))


# ── 1 ──────────────────────────────────────────────────────────────


def test_search_finds_framework_render(docs: Docs) -> None:
    hits = docs.search("render template", k=5)
    assert hits, "search returned zero results"
    top3 = [h["fqn"] for h in hits[:3]]
    assert "tina4_python.core.response.Response.render" in top3, (
        f"Response.render should rank in top 3 for 'render template'; got {top3}"
    )


# ── 2 ──────────────────────────────────────────────────────────────


def test_search_finds_user_model(docs: Docs) -> None:
    hits = docs.search("User", k=5)
    user_hits = [h for h in hits if h["source"] == "user"]
    assert user_hits, "expected at least one user-source hit for 'User'"
    found = any("User" in h["fqn"] and h["source"] == "user" for h in hits[:3])
    assert found, "user's User class should rank in top 3"


# ── 3 ──────────────────────────────────────────────────────────────


def test_search_source_filter(docs: Docs) -> None:
    fw_only = docs.search("User", k=10, source="framework")
    for h in fw_only:
        assert h["source"] == "framework", "source=framework leaked a non-framework hit"
    user_only = docs.search("User", k=10, source="user")
    for h in user_only:
        assert h["source"] == "user", "source=user leaked a non-user hit"


# ── 4 ──────────────────────────────────────────────────────────────


def test_class_endpoint_returns_full_method_list(docs: Docs) -> None:
    spec = docs.class_spec("tina4_python.core.response.Response")
    assert spec is not None, "Response should be reflectable"
    assert "methods" in spec
    assert len(spec["methods"]) >= 5
    for m in spec["methods"]:
        assert "signature" in m
        assert "file" in m
        assert "line" in m


# ── 5 ──────────────────────────────────────────────────────────────


def test_class_endpoint_missing_class(docs: Docs) -> None:
    spec = docs.class_spec("tina4_python.NotARealClass")
    assert spec is None, "unknown class should return None (404 path on HTTP)"


# ── 6 ──────────────────────────────────────────────────────────────


def test_method_endpoint_returns_signature(docs: Docs) -> None:
    spec = docs.method_spec("tina4_python.core.response.Response", "render")
    assert spec is not None
    assert spec["name"] == "render"
    assert spec["signature"]
    assert spec["visibility"] == "public"
    assert spec["source"] == "framework"


# ── 7 ──────────────────────────────────────────────────────────────


def test_user_class_appears_in_class_endpoint(docs: Docs) -> None:
    spec = docs.class_spec("src.orm.User.User")
    assert spec is not None, "user model should be reflectable"
    assert spec["source"] == "user"
    method_names = [m["name"] for m in spec["methods"]]
    assert "find_by_email" in method_names


# ── 8 ──────────────────────────────────────────────────────────────


def test_index_endpoint_lists_all(docs: Docs) -> None:
    idx = docs.index()
    assert len(idx) >= 50, "expected at least 50 entities (framework + user)"
    sources = {e["source"] for e in idx}
    assert "framework" in sources
    assert "user" in sources


# ── 9 ──────────────────────────────────────────────────────────────


def test_mcp_docs_search_matches_http(docs: Docs) -> None:
    direct = docs.search("render", k=3)
    via_mcp = Docs.mcp_search("render", k=3, project_root=str(docs.project_root))
    assert [h["fqn"] for h in direct] == [h["fqn"] for h in via_mcp], (
        "MCP and direct call must return the same ranked hits"
    )


# ── 10 ─────────────────────────────────────────────────────────────


def test_mcp_docs_method_matches_http(docs: Docs) -> None:
    direct = docs.method_spec("tina4_python.core.response.Response", "render")
    via_mcp = Docs.mcp_method(
        "tina4_python.core.response.Response", "render",
        project_root=str(docs.project_root),
    )
    assert direct == via_mcp


# ── 11 ─────────────────────────────────────────────────────────────


def test_index_refreshes_on_user_file_change(docs: Docs, fixture_project: Path) -> None:
    before = docs.method_spec("src.orm.User.User", "find_active")
    assert before is None, "precondition: find_active does not exist yet"

    user_py = fixture_project / "src" / "orm" / "User.py"
    src = user_py.read_text(encoding="utf-8")
    patched = src.replace(
        "primary_key = \"id\"",
        "primary_key = \"id\"\n\n    @classmethod\n    def find_active(cls):\n        return []\n",
    )
    user_py.write_text(patched, encoding="utf-8")
    # mtime resolution is 1s on some FS — bump explicitly.
    new_mtime = time.time() + 2
    os.utime(user_py, (new_mtime, new_mtime))

    after = docs.method_spec("src.orm.User.User", "find_active")
    assert after is not None, "index should pick up newly-added method on next query"


# ── 12 ─────────────────────────────────────────────────────────────


def test_drift_detector_finds_doc_inconsistency(docs: Docs, fixture_project: Path) -> None:
    tmp = fixture_project / "CLAUDE.md"
    tmp.write_text(
        "```python\nresponse.fake_method_that_does_not_exist()\n```\n",
        encoding="utf-8",
    )
    report = Docs.check_docs(str(tmp))
    assert report["drift"], "drift detector should flag fake_method_that_does_not_exist"


# ── 13 ─────────────────────────────────────────────────────────────


def test_sync_overwrites_marked_section(docs: Docs, fixture_project: Path) -> None:
    tmp = fixture_project / "CLAUDE.md"
    original = (
        "Prose above\n<!-- BEGIN GENERATED API -->\nold content\n"
        "<!-- END GENERATED API -->\nProse below\n"
    )
    tmp.write_text(original, encoding="utf-8")
    Docs.sync_docs(str(tmp))
    updated = tmp.read_text(encoding="utf-8")
    assert "Prose above" in updated, "prose above must be preserved"
    assert "Prose below" in updated, "prose below must be preserved"
    assert "old content" not in updated, "old generated content must be replaced"
    assert "Response" in updated, "fresh content must include real classes"


# ── 14 ─────────────────────────────────────────────────────────────


def test_search_response_under_50ms(docs: Docs) -> None:
    docs.search("warm-up", k=1)  # build the index once
    start = time.perf_counter()
    docs.search("render", k=5)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 50.0, f"search took {elapsed_ms:.1f}ms (budget 50ms)"


# ── 15 ─────────────────────────────────────────────────────────────


def test_no_private_methods_in_default_search(docs: Docs) -> None:
    hits = docs.search("hash_password", k=10)
    for h in hits:
        assert h.get("fqn") != "src.orm.User.User._hash_password", (
            "private/internal methods must be excluded from default search"
        )
    opt_in = docs.search("hash_password", k=10, include_private=True)
    fqns = [h["fqn"] for h in opt_in]
    assert "src.orm.User.User._hash_password" in fqns, (
        "include_private=True must surface private methods"
    )


# ── 16 ─────────────────────────────────────────────────────────────


def test_no_vendor_third_party_in_results(docs: Docs) -> None:
    hits = docs.search("pytest", k=20)
    for h in hits:
        assert h.get("source") != "vendor", "vendor results leaked into default search"
        file_path = h.get("file", "")
        assert not file_path.startswith(".venv/"), (
            ".venv/ paths leaked into default search"
        )
        assert "site-packages" not in file_path, (
            "site-packages paths leaked into default search"
        )


# ── 17 ─────────────────────────────────────────────────────────────


def test_descriptor_defined_methods_are_indexed(docs: Docs) -> None:
    """Frond's add_filter/add_global/add_test use a custom dual class/instance
    descriptor. They must still be reflected (the old __qualname__ owner check
    dropped them), with receiver params (self/cls/instance) stripped."""
    frond = "tina4_python.frond.engine.Frond"
    for name in ("add_filter", "add_global", "add_test"):
        spec = docs.method_spec(frond, name)
        assert spec is not None, f"Frond.{name} must be indexed"
        sig = spec["signature"]
        assert sig.startswith(f"{name}("), f"signature should lead with the name: {sig}"
        assert "self" not in sig and "cls" not in sig and "instance" not in sig, (
            f"receiver params must be stripped from the public signature: {sig}"
        )


# ── 18 ─────────────────────────────────────────────────────────────


def test_class_qualified_search_ranks_the_owning_method(docs: Docs) -> None:
    """A 'Class.method' / 'Class method' query must rank that class's method
    first — the class qualifier has to steer ranking, not be dead weight."""
    for query in ("Frond.add_test", "Frond add_test"):
        hits = docs.search(query, k=3)
        assert hits, f"no hits for {query!r}"
        assert hits[0]["fqn"] == "tina4_python.frond.engine.Frond.add_test", (
            f"{query!r} should rank Frond.add_test #1; got {[h['fqn'] for h in hits]}"
        )


# ── 19 ─────────────────────────────────────────────────────────────


def test_lookup_resolves_public_import_path(docs: Docs) -> None:
    """The documented import path (tina4_python.database.Database) resolves even
    though the index stores the deep defining-module FQN (…connection.Database)."""
    deep = "tina4_python.database.connection.Database"
    public = "tina4_python.database.Database"
    assert docs.class_spec(deep) is not None, "precondition: deep FQN resolves"
    assert docs.class_spec(public) is not None, "public import path must resolve"
    assert docs.method_spec(public, "execute") is not None, (
        "method_spec must resolve via the public import path"
    )
    # Both paths point at the same class.
    assert docs.class_spec(public)["fqn"] == docs.class_spec(deep)["fqn"]


# ── 20 ─────────────────────────────────────────────────────────────


def test_lookup_resolves_bare_class_name(docs: Docs) -> None:
    """A bare class name (Database) resolves to the one matching class."""
    spec = docs.class_spec("Database")
    assert spec is not None, "bare class name must resolve"
    assert spec["fqn"].endswith(".Database")
    assert docs.method_spec("Database", "execute") is not None
    # A truly unknown name still returns None (no false positives).
    assert docs.class_spec("DefinitelyNotAClass") is None
