# Tests for tina4_python.graphql
import pytest
from tina4_python.graphql import GraphQL, Schema, Parser, ParseError, tokenize


# ── Lexer Tests ───────────────────────────────────────────────


class TestLexer:
    def test_simple_query(self):
        tokens = tokenize("{ user { name } }")
        types = [t.type for t in tokens]
        assert types == ["LBRACE", "NAME", "LBRACE", "NAME", "RBRACE", "RBRACE"]

    def test_string_value(self):
        tokens = tokenize('{ user(id: "123") { name } }')
        assert any(t.type == "STRING" and t.value == '"123"' for t in tokens)

    def test_number_value(self):
        tokens = tokenize("{ users(limit: 10) { name } }")
        assert any(t.type == "NUMBER" and t.value == "10" for t in tokens)

    def test_boolean(self):
        tokens = tokenize("{ user @skip(if: true) { name } }")
        assert any(t.type == "BOOL" and t.value == "true" for t in tokens)

    def test_comments_stripped(self):
        tokens = tokenize("# comment\n{ user { name } }")
        assert not any(t.type == "COMMENT" for t in tokens)

    def test_variable_tokens(self):
        tokens = tokenize("query ($id: ID!) { user(id: $id) { name } }")
        types = [t.type for t in tokens]
        assert "DOLLAR" in types
        assert "BANG" in types


# ── Parser Tests ──────────────────────────────────────────────


class TestParser:
    def test_simple_query(self):
        tokens = tokenize("{ user { name email } }")
        doc = Parser(tokens).parse()
        assert len(doc["definitions"]) == 1
        op = doc["definitions"][0]
        assert op["kind"] == "operation"
        assert op["operation"] == "query"
        assert len(op["selections"]) == 1

    def test_named_query(self):
        tokens = tokenize("query GetUser { user { name } }")
        doc = Parser(tokens).parse()
        assert doc["definitions"][0]["name"] == "GetUser"

    def test_mutation(self):
        tokens = tokenize('mutation { createUser(name: "Alice") { id } }')
        doc = Parser(tokens).parse()
        assert doc["definitions"][0]["operation"] == "mutation"

    def test_alias(self):
        tokens = tokenize("{ admin: user(role: \"admin\") { name } }")
        doc = Parser(tokens).parse()
        field = doc["definitions"][0]["selections"][0]
        assert field["alias"] == "admin"
        assert field["name"] == "user"

    def test_fragment(self):
        tokens = tokenize("fragment UserFields on User { name email }")
        doc = Parser(tokens).parse()
        frag = doc["definitions"][0]
        assert frag["kind"] == "fragment"
        assert frag["name"] == "UserFields"
        assert frag["on"] == "User"

    def test_variables(self):
        tokens = tokenize("query ($id: ID!, $limit: Int = 10) { users { name } }")
        doc = Parser(tokens).parse()
        variables = doc["definitions"][0]["variables"]
        assert len(variables) == 2
        assert variables[0]["name"] == "id"
        assert variables[0]["type"] == "ID!"
        assert variables[1]["default"] == 10

    def test_directives(self):
        tokens = tokenize("{ user { name @skip(if: true) email } }")
        doc = Parser(tokens).parse()
        fields = doc["definitions"][0]["selections"][0]["selections"]
        name_field = fields[0]
        assert len(name_field["directives"]) == 1
        assert name_field["directives"][0]["name"] == "skip"

    def test_nested_objects(self):
        tokens = tokenize("{ user { address { city country } } }")
        doc = Parser(tokens).parse()
        user = doc["definitions"][0]["selections"][0]
        assert user["selections"] is not None
        address = user["selections"][0]
        assert address["name"] == "address"
        assert len(address["selections"]) == 2


# ── Executor Tests ────────────────────────────────────────────


class TestExecutor:
    def _make_gql(self):
        gql = GraphQL()
        gql.schema.add_type("User", {"id": "ID", "name": "String", "email": "String"})
        gql.schema.add_query("user", {
            "type": "User",
            "args": {"id": "ID!"},
            "resolve": lambda root, args, ctx: {
                "id": args["id"], "name": "Alice", "email": "alice@test.com"
            },
        })
        gql.schema.add_query("users", {
            "type": "[User]",
            "args": {"limit": "Int"},
            "resolve": lambda root, args, ctx: [
                {"id": "1", "name": "Alice", "email": "alice@test.com"},
                {"id": "2", "name": "Bob", "email": "bob@test.com"},
            ][:args.get("limit", 10)],
        })
        gql.schema.add_mutation("createUser", {
            "type": "User",
            "args": {"name": "String!", "email": "String!"},
            "resolve": lambda root, args, ctx: {
                "id": "3", "name": args["name"], "email": args["email"]
            },
        })
        return gql

    def test_simple_query(self):
        gql = self._make_gql()
        result = gql.execute('{ user(id: "1") { name email } }')
        assert result["data"]["user"]["name"] == "Alice"
        assert result["data"]["user"]["email"] == "alice@test.com"
        assert "errors" not in result

    def test_list_query(self):
        gql = self._make_gql()
        result = gql.execute("{ users(limit: 1) { name } }")
        assert len(result["data"]["users"]) == 1
        assert result["data"]["users"][0]["name"] == "Alice"

    def test_alias(self):
        gql = self._make_gql()
        result = gql.execute('{ admin: user(id: "1") { name } }')
        assert "admin" in result["data"]
        assert result["data"]["admin"]["name"] == "Alice"

    def test_mutation(self):
        gql = self._make_gql()
        result = gql.execute('mutation { createUser(name: "Eve", email: "eve@test.com") { name email } }')
        assert result["data"]["createUser"]["name"] == "Eve"

    def test_variables(self):
        gql = self._make_gql()
        result = gql.execute(
            'query ($id: ID!) { user(id: $id) { name } }',
            variables={"id": "1"},
        )
        assert result["data"]["user"]["name"] == "Alice"

    def test_variable_defaults(self):
        gql = self._make_gql()
        result = gql.execute(
            'query ($limit: Int = 1) { users(limit: $limit) { name } }',
        )
        assert len(result["data"]["users"]) == 1

    def test_skip_directive(self):
        gql = self._make_gql()
        result = gql.execute(
            'query ($skip: Boolean!) { user(id: "1") { name @skip(if: $skip) email } }',
            variables={"skip": True},
        )
        user = result["data"]["user"]
        assert "name" not in user
        assert "email" in user

    def test_include_directive(self):
        gql = self._make_gql()
        result = gql.execute(
            'query ($show: Boolean!) { user(id: "1") { name @include(if: $show) email } }',
            variables={"show": False},
        )
        assert "name" not in result["data"]["user"]

    def test_fragment(self):
        gql = self._make_gql()
        result = gql.execute('''
            query { user(id: "1") { ...UserInfo } }
            fragment UserInfo on User { name email }
        ''')
        assert result["data"]["user"]["name"] == "Alice"
        assert result["data"]["user"]["email"] == "alice@test.com"

    def test_resolver_error(self):
        gql = GraphQL()
        gql.schema.add_query("broken", {
            "type": "String",
            "resolve": lambda r, a, c: 1 / 0,
        })
        result = gql.execute("{ broken }")
        assert result["errors"]
        assert "division by zero" in result["errors"][0]["message"]

    def test_parse_error(self):
        gql = GraphQL()
        result = gql.execute("{ invalid {{")
        assert result["errors"]
        assert result["data"] is None

    def test_introspect(self):
        gql = self._make_gql()
        schema = gql.introspect()
        assert "User" in schema["types"]
        assert "user" in schema["queries"]
        assert "createUser" in schema["mutations"]

    def test_nested_selection(self):
        gql = GraphQL()
        gql.schema.add_query("company", {
            "type": "Company",
            "resolve": lambda r, a, c: {
                "name": "Acme",
                "ceo": {"name": "Alice", "title": "CEO"},
            },
        })
        result = gql.execute("{ company { name ceo { name title } } }")
        assert result["data"]["company"]["name"] == "Acme"
        assert result["data"]["company"]["ceo"]["name"] == "Alice"

    def test_execute_json(self):
        gql = self._make_gql()
        json_str = gql.execute_json('{ user(id: "1") { name } }')
        import json
        data = json.loads(json_str)
        assert data["data"]["user"]["name"] == "Alice"

    def test_context_passed(self):
        gql = GraphQL()
        gql.schema.add_query("whoami", {
            "type": "String",
            "resolve": lambda r, a, ctx: ctx.get("user", "anon"),
        })
        result = gql.execute("{ whoami }", context={"user": "admin"})
        assert result["data"]["whoami"] == "admin"
