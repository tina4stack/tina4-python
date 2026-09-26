"""Medium security finding F2 — GraphQL fan-out limits.

The depth guard bounds NESTING but not WIDTH. This pins the two controls that
close the gap, at parity with the sibling regressions in
tina4-nodejs/test/graphqlFanoutLimits.test.ts,
tina4-php/tests/GraphQLFanoutLimitsTest.php and
tina4-ruby/spec/graphql_fanout_limits_spec.rb:

  * a total expanded-node (complexity) budget, TINA4_GRAPHQL_MAX_NODES, which
    rejects a fragment bomb (fragments spreading fragments) and an alias
    explosion before any resolver runs; and
  * a parser recursion bound, so a deeply nested query fails with a clean parse
    error instead of overflowing the parser stack.
"""
import pytest
from tina4_python.graphql import GraphQL


def _gql():
    gql = GraphQL()
    gql.schema.add_query("ping", {}, "String", lambda root, args, ctx: "pong")
    return gql


class TestGraphQLFanoutLimits:
    def test_fragment_bomb_is_rejected(self, monkeypatch):
        monkeypatch.setenv("TINA4_GRAPHQL_MAX_NODES", "100")
        gql = _gql()
        frags = "fragment f0 on Query { ping }\n"
        prev = "f0"
        for i in range(1, 8):
            frags += f"fragment f{i} on Query {{ ...{prev} ...{prev} }}\n"
            prev = f"f{i}"
        result = gql.execute(frags + "{ ...f7 }")
        errs = " ".join(e["message"] for e in (result.get("errors") or []))
        assert "complexity" in errs.lower(), f"fragment bomb not bounded: {result}"

    def test_alias_explosion_is_rejected(self, monkeypatch):
        monkeypatch.setenv("TINA4_GRAPHQL_MAX_NODES", "100")
        gql = _gql()
        aliases = " ".join(f"a{i}: ping" for i in range(200))
        result = gql.execute("{ " + aliases + " }")
        errs = " ".join(e["message"] for e in (result.get("errors") or []))
        assert "complexity" in errs.lower(), f"alias explosion not bounded: {result}"

    def test_deeply_nested_query_fails_gracefully(self, monkeypatch):
        monkeypatch.setenv("TINA4_GRAPHQL_MAX_DEPTH", "20")
        gql = _gql()
        inner = "x"
        for _ in range(3000):
            inner = "ping { " + inner + " }"
        result = gql.execute("{ " + inner + " }")
        errs = " ".join(e["message"] for e in (result.get("errors") or []))
        # A clean bounded error, never a crash / 500.
        assert "exceeds maximum depth" in errs.lower(), f"deep nesting not bounded by the parser: {result}"

    def test_ordinary_query_still_works(self, monkeypatch):
        # Positive twin: a small query under the budget resolves normally.
        monkeypatch.setenv("TINA4_GRAPHQL_MAX_NODES", "100")
        gql = _gql()
        result = gql.execute("{ ping }")
        assert (result.get("data") or {}).get("ping") == "pong", result
