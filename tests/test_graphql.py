#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
"""Tests for tina4_python.GraphQL — parser, schema, executor, ORM integration."""

import pytest
from tina4_python.GraphQL import (
    GraphQL,
    GraphQLSchema,
    GraphQLType,
    GraphQLError,
    _Parser,
    _tokenize,
)


# ─── Lexer Tests ────────────────────────────────────────────────────

class TestLexer:
    def test_simple_query(self):
        tokens = _tokenize("{ user { id name } }")
        kinds = [t[0] for t in tokens]
        assert kinds == ["PUNCT", "NAME", "PUNCT", "NAME", "NAME", "PUNCT", "PUNCT"]

    def test_string_token(self):
        tokens = _tokenize('{ user(name: "Alice") { id } }')
        string_tokens = [t for t in tokens if t[0] == "STRING"]
        assert len(string_tokens) == 1
        assert string_tokens[0][1] == "Alice"

    def test_int_and_float(self):
        tokens = _tokenize("{ items(limit: 10, price: 9.99) { id } }")
        int_tokens = [t for t in tokens if t[0] == "INT"]
        float_tokens = [t for t in tokens if t[0] == "FLOAT"]
        assert len(int_tokens) == 1
        assert int_tokens[0][1] == 10
        assert len(float_tokens) == 1
        assert float_tokens[0][1] == 9.99

    def test_spread_token(self):
        tokens = _tokenize("{ ...UserFields }")
        spread_tokens = [t for t in tokens if t[0] == "SPREAD"]
        assert len(spread_tokens) == 1

    def test_comments_ignored(self):
        tokens = _tokenize("{ user # this is a comment\n{ id } }")
        kinds = [t[0] for t in tokens]
        assert "COMMENT" not in kinds

    def test_variable_dollar_sign(self):
        tokens = _tokenize("query ($id: ID) { user(id: $id) { name } }")
        dollar_tokens = [t for t in tokens if t[1] == "$"]
        assert len(dollar_tokens) == 2

    def test_negative_int(self):
        tokens = _tokenize("{ items(offset: -5) { id } }")
        int_tokens = [t for t in tokens if t[0] == "INT"]
        assert int_tokens[0][1] == -5

    def test_escaped_string(self):
        tokens = _tokenize(r'{ user(name: "Alice \"Bob\" Charlie") { id } }')
        string_tokens = [t for t in tokens if t[0] == "STRING"]
        assert string_tokens[0][1] == 'Alice "Bob" Charlie'


# ─── Parser Tests ───────────────────────────────────────────────────

class TestParser:
    def test_shorthand_query(self):
        doc = _Parser("{ user { id name } }").parse()
        assert doc["kind"] == "Document"
        assert len(doc["definitions"]) == 1
        op = doc["definitions"][0]
        assert op["kind"] == "OperationDefinition"
        assert op["operation"] == "query"
        assert op["name"] is None
        assert len(op["selectionSet"]) == 1

    def test_named_query(self):
        doc = _Parser("query GetUser { user { id } }").parse()
        op = doc["definitions"][0]
        assert op["name"] == "GetUser"
        assert op["operation"] == "query"

    def test_mutation(self):
        doc = _Parser("mutation { createUser(input: {name: \"Alice\"}) { id } }").parse()
        op = doc["definitions"][0]
        assert op["operation"] == "mutation"

    def test_variables(self):
        doc = _Parser("query ($id: ID!, $limit: Int = 10) { user(id: $id) { name } }").parse()
        op = doc["definitions"][0]
        assert len(op["variableDefinitions"]) == 2
        assert op["variableDefinitions"][0]["name"] == "id"
        assert op["variableDefinitions"][0]["type"]["nonNull"] is True
        assert op["variableDefinitions"][1]["name"] == "limit"
        assert op["variableDefinitions"][1]["defaultValue"]["value"] == 10

    def test_alias(self):
        doc = _Parser("{ first: user(id: \"1\") { name } second: user(id: \"2\") { name } }").parse()
        selections = doc["definitions"][0]["selectionSet"]
        assert len(selections) == 2
        assert selections[0]["alias"] == "first"
        assert selections[1]["alias"] == "second"

    def test_fragment(self):
        doc = _Parser("""
            fragment UserFields on User { id name email }
            query { user { ...UserFields } }
        """).parse()
        assert len(doc["definitions"]) == 2
        frag = doc["definitions"][0]
        assert frag["kind"] == "FragmentDefinition"
        assert frag["name"] == "UserFields"
        assert frag["typeCondition"] == "User"

    def test_inline_fragment(self):
        doc = _Parser("{ node { ... on User { name } ... on Product { title } } }").parse()
        node_field = doc["definitions"][0]["selectionSet"][0]
        subs = node_field["selectionSet"]
        assert subs[0]["kind"] == "InlineFragment"
        assert subs[0]["typeCondition"] == "User"
        assert subs[1]["typeCondition"] == "Product"

    def test_directives(self):
        doc = _Parser('{ user { id name @skip(if: true) email @include(if: false) } }').parse()
        fields = doc["definitions"][0]["selectionSet"][0]["selectionSet"]
        assert fields[1]["directives"][0]["name"] == "skip"
        assert fields[2]["directives"][0]["name"] == "include"

    def test_nested_object_argument(self):
        doc = _Parser('mutation { create(input: {name: "Alice", age: 30}) { id } }').parse()
        field = doc["definitions"][0]["selectionSet"][0]
        arg = field["arguments"][0]
        assert arg["name"] == "input"
        assert arg["value"]["kind"] == "ObjectValue"
        assert "name" in arg["value"]["fields"]
        assert "age" in arg["value"]["fields"]

    def test_list_argument(self):
        doc = _Parser("{ items(ids: [1, 2, 3]) { name } }").parse()
        arg = doc["definitions"][0]["selectionSet"][0]["arguments"][0]
        assert arg["value"]["kind"] == "ListValue"
        assert len(arg["value"]["values"]) == 3

    def test_boolean_and_null(self):
        doc = _Parser("{ item(active: true, deleted: false, note: null) { id } }").parse()
        args = doc["definitions"][0]["selectionSet"][0]["arguments"]
        assert args[0]["value"]["value"] is True
        assert args[1]["value"]["value"] is False
        assert args[2]["value"]["value"] is None

    def test_list_type(self):
        doc = _Parser("query ($ids: [ID!]!) { users(ids: $ids) { name } }").parse()
        var_type = doc["definitions"][0]["variableDefinitions"][0]["type"]
        assert var_type["kind"] == "ListType"
        assert var_type["nonNull"] is True
        assert var_type["type"]["kind"] == "NamedType"
        assert var_type["type"]["nonNull"] is True


# ─── Schema Tests ───────────────────────────────────────────────────

class TestSchema:
    def test_add_type(self):
        schema = GraphQLSchema()
        schema.add_type("User", {"id": "ID", "name": "String"})
        assert "User" in schema.types
        assert schema.types["User"].fields["id"] == "ID"

    def test_add_type_dict_format(self):
        schema = GraphQLSchema()
        schema.add_type("User", {"id": {"type": "ID"}, "name": {"type": "String"}})
        assert schema.types["User"].fields["id"] == "ID"

    def test_add_query(self):
        schema = GraphQLSchema()
        schema.add_query("user", {
            "type": "User",
            "args": {"id": "ID"},
            "resolve": lambda root, args, ctx: {"id": args["id"], "name": "Alice"},
        })
        assert "user" in schema.queries

    def test_add_mutation(self):
        schema = GraphQLSchema()
        schema.add_mutation("createUser", {
            "type": "User",
            "args": {"input": "UserInput"},
            "resolve": lambda root, args, ctx: {"id": "1", "name": args["input"]["name"]},
        })
        assert "createUser" in schema.mutations


# ─── Executor Tests ─────────────────────────────────────────────────

class TestExecutor:
    @staticmethod
    def _make_gql():
        gql = GraphQL()
        gql.schema.add_type("User", {"id": "ID", "name": "String", "age": "Int", "email": "String"})
        gql.schema.add_query("user", {
            "type": "User",
            "args": {"id": "ID"},
            "resolve": lambda root, args, ctx: {"id": args.get("id", "1"), "name": "Alice", "age": 30, "email": "alice@test.com"},
        })
        gql.schema.add_query("users", {
            "type": "[User]",
            "args": {"limit": "Int"},
            "resolve": lambda root, args, ctx: [
                {"id": "1", "name": "Alice", "age": 30, "email": "alice@test.com"},
                {"id": "2", "name": "Bob", "age": 25, "email": "bob@test.com"},
            ][:args.get("limit", 10)],
        })
        gql.schema.add_mutation("createUser", {
            "type": "User",
            "args": {"input": "UserInput"},
            "resolve": lambda root, args, ctx: {"id": "3", **args.get("input", {})},
        })
        gql.schema.add_mutation("deleteUser", {
            "type": "Boolean",
            "args": {"id": "ID!"},
            "resolve": lambda root, args, ctx: True,
        })
        return gql

    def test_simple_query(self):
        gql = self._make_gql()
        result = gql.execute('{ user(id: "1") { id name } }')
        assert result["data"]["user"]["id"] == "1"
        assert result["data"]["user"]["name"] == "Alice"
        assert "age" not in result["data"]["user"]

    def test_all_fields(self):
        gql = self._make_gql()
        result = gql.execute('{ user { id name age email } }')
        assert result["data"]["user"]["age"] == 30
        assert result["data"]["user"]["email"] == "alice@test.com"

    def test_list_query(self):
        gql = self._make_gql()
        result = gql.execute("{ users { id name } }")
        assert len(result["data"]["users"]) == 2
        assert result["data"]["users"][0]["name"] == "Alice"
        assert result["data"]["users"][1]["name"] == "Bob"

    def test_list_with_limit(self):
        gql = self._make_gql()
        result = gql.execute("{ users(limit: 1) { id name } }")
        assert len(result["data"]["users"]) == 1

    def test_alias(self):
        gql = self._make_gql()
        result = gql.execute('{ first: user(id: "1") { name } second: user(id: "2") { name } }')
        assert "first" in result["data"]
        assert "second" in result["data"]

    def test_mutation(self):
        gql = self._make_gql()
        result = gql.execute('mutation { createUser(input: {name: "Charlie", age: 35}) { id name age } }')
        assert result["data"]["createUser"]["name"] == "Charlie"
        assert result["data"]["createUser"]["age"] == 35
        assert result["data"]["createUser"]["id"] == "3"

    def test_delete_mutation(self):
        gql = self._make_gql()
        result = gql.execute('mutation { deleteUser(id: "1") }')
        assert result["data"]["deleteUser"] is True

    def test_variables(self):
        gql = self._make_gql()
        result = gql.execute(
            'query ($userId: ID) { user(id: $userId) { id name } }',
            variables={"userId": "42"},
        )
        assert result["data"]["user"]["id"] == "42"

    def test_default_variable(self):
        gql = self._make_gql()
        result = gql.execute(
            'query ($userId: ID = "99") { user(id: $userId) { id } }',
        )
        assert result["data"]["user"]["id"] == "99"

    def test_fragment(self):
        gql = self._make_gql()
        result = gql.execute("""
            fragment UserFields on User { id name email }
            query { user { ...UserFields } }
        """)
        assert result["data"]["user"]["id"] == "1"
        assert result["data"]["user"]["name"] == "Alice"
        assert result["data"]["user"]["email"] == "alice@test.com"

    def test_skip_directive(self):
        gql = self._make_gql()
        result = gql.execute('{ user { id name @skip(if: true) } }')
        assert "name" not in result["data"]["user"]
        assert "id" in result["data"]["user"]

    def test_include_directive(self):
        gql = self._make_gql()
        result = gql.execute('{ user { id name @include(if: false) } }')
        assert "name" not in result["data"]["user"]

    def test_include_true(self):
        gql = self._make_gql()
        result = gql.execute('{ user { id name @include(if: true) } }')
        assert "name" in result["data"]["user"]

    def test_skip_with_variable(self):
        gql = self._make_gql()
        result = gql.execute(
            'query ($skip: Boolean!) { user { id name @skip(if: $skip) } }',
            variables={"skip": True},
        )
        assert "name" not in result["data"]["user"]

    def test_unknown_field_error(self):
        gql = self._make_gql()
        result = gql.execute("{ unknown { id } }")
        assert result["data"]["unknown"] is None
        assert len(result["errors"]) == 1
        assert "not found" in result["errors"][0]["message"]

    def test_parse_error(self):
        gql = self._make_gql()
        result = gql.execute("{ user { id }")  # Missing closing brace
        assert result["data"] is None
        assert "errors" in result

    def test_invalid_json_handle_request(self):
        gql = self._make_gql()
        result = gql.handle_request("not json")
        assert result["data"] is None
        assert "Invalid JSON" in result["errors"][0]["message"]

    def test_missing_query_handle_request(self):
        gql = self._make_gql()
        result = gql.handle_request({"variables": {}})
        assert result["data"] is None
        assert "No query" in result["errors"][0]["message"]

    def test_handle_request_string(self):
        gql = self._make_gql()
        import json
        body = json.dumps({"query": '{ user(id: "1") { id name } }'})
        result = gql.handle_request(body)
        assert result["data"]["user"]["name"] == "Alice"

    def test_handle_request_dict(self):
        gql = self._make_gql()
        result = gql.handle_request({"query": "{ users(limit: 1) { name } }"})
        assert len(result["data"]["users"]) == 1

    def test_context_passed_to_resolver(self):
        gql = GraphQL()
        gql.schema.add_query("me", {
            "type": "User",
            "args": {},
            "resolve": lambda root, args, ctx: {"id": "1", "name": ctx.get("user_name", "Unknown")},
        })
        result = gql.execute("{ me { name } }", context={"user_name": "Andre"})
        assert result["data"]["me"]["name"] == "Andre"

    def test_nested_object_input(self):
        gql = self._make_gql()
        result = gql.execute("""
            mutation {
                createUser(input: {name: "Dave", age: 40, email: "dave@test.com"}) {
                    id name age email
                }
            }
        """)
        assert result["data"]["createUser"]["name"] == "Dave"
        assert result["data"]["createUser"]["age"] == 40
        assert result["data"]["createUser"]["email"] == "dave@test.com"

    def test_multiple_queries(self):
        gql = self._make_gql()
        result = gql.execute('{ user(id: "1") { name } users(limit: 2) { id } }')
        assert result["data"]["user"]["name"] == "Alice"
        assert len(result["data"]["users"]) == 2


# ─── GraphQLType Tests ──────────────────────────────────────────────

class TestGraphQLType:
    def test_scalar(self):
        t = GraphQLType.scalar("String")
        assert t.kind == "SCALAR"
        assert t.name == "String"

    def test_list_of(self):
        assert GraphQLType.list_of("User") == "[User]"

    def test_non_null(self):
        assert GraphQLType.non_null("String") == "String!"

    def test_object_type(self):
        t = GraphQLType("Product", "OBJECT", {"id": "ID", "name": "String"})
        assert t.name == "Product"
        assert t.kind == "OBJECT"
        assert t.fields["id"] == "ID"


# ─── ORM Integration Tests ─────────────────────────────────────────

class TestORMIntegration:
    """Test from_orm() with a mock ORM class (no real database)."""

    @staticmethod
    def _make_mock_orm():
        """Create a minimal mock ORM class that looks like a Tina4 ORM."""
        from tina4_python.FieldTypes import IntegerField, StringField, NumericField

        class MockProduct:
            __type_name__ = "Product"

            def __init__(self, data=None):
                self.__field_definitions__ = {}
                # Simulate field definitions
                id_field = IntegerField(column_name="id", primary_key=True, auto_increment=True)
                name_field = StringField(column_name="name")
                price_field = NumericField(column_name="price")
                self.__field_definitions__["id"] = id_field
                self.__field_definitions__["name"] = name_field
                self.__field_definitions__["price"] = price_field
                self.id = None
                self.name = None
                self.price = None
                if data:
                    for k, v in data.items():
                        setattr(self, k, v)

            def to_dict(self):
                return {"id": self.id, "name": self.name, "price": self.price}

            def load(self, filter_str, params):
                self.id = params[0]
                self.name = "Test Product"
                self.price = 9.99
                return True

            def save(self):
                if self.id is None:
                    self.id = 1
                return True

            def delete(self, query=None, params=None):
                return True

            def select(self, filter=None, params=None, limit=10, skip=0):
                class MockResult:
                    records = [
                        {"id": 1, "name": "Widget", "price": 9.99},
                        {"id": 2, "name": "Gadget", "price": 19.99},
                    ]
                return MockResult()

        return MockProduct

    def test_from_orm_registers_type(self):
        schema = GraphQLSchema()
        MockProduct = self._make_mock_orm()
        schema.from_orm(MockProduct)
        assert "Product" in schema.types
        assert schema.types["Product"].fields["id"] == "ID"
        assert schema.types["Product"].fields["name"] == "String"
        assert schema.types["Product"].fields["price"] == "Float"

    def test_from_orm_registers_queries(self):
        schema = GraphQLSchema()
        MockProduct = self._make_mock_orm()
        schema.from_orm(MockProduct)
        assert "product" in schema.queries
        assert "products" in schema.queries

    def test_from_orm_registers_mutations(self):
        schema = GraphQLSchema()
        MockProduct = self._make_mock_orm()
        schema.from_orm(MockProduct)
        assert "createProduct" in schema.mutations
        assert "updateProduct" in schema.mutations
        assert "deleteProduct" in schema.mutations

    def test_from_orm_single_query(self):
        gql = GraphQL()
        MockProduct = self._make_mock_orm()
        gql.schema.from_orm(MockProduct)
        result = gql.execute('{ product(id: "1") { id name price } }')
        assert result["data"]["product"]["id"] == "1"
        assert result["data"]["product"]["name"] == "Test Product"

    def test_from_orm_list_query(self):
        gql = GraphQL()
        MockProduct = self._make_mock_orm()
        gql.schema.from_orm(MockProduct)
        result = gql.execute("{ products(limit: 10) { id name price } }")
        assert len(result["data"]["products"]) == 2
        assert result["data"]["products"][0]["name"] == "Widget"

    def test_from_orm_create_mutation(self):
        gql = GraphQL()
        MockProduct = self._make_mock_orm()
        gql.schema.from_orm(MockProduct)
        result = gql.execute("""
            mutation {
                createProduct(input: {name: "New Item", price: 29.99}) {
                    id name price
                }
            }
        """)
        assert result["data"]["createProduct"]["id"] == 1
        assert result["data"]["createProduct"]["name"] == "New Item"

    def test_from_orm_update_mutation(self):
        gql = GraphQL()
        MockProduct = self._make_mock_orm()
        gql.schema.from_orm(MockProduct)
        result = gql.execute("""
            mutation {
                updateProduct(id: "1", input: {name: "Updated Widget"}) {
                    id name
                }
            }
        """)
        assert result["data"]["updateProduct"]["name"] == "Updated Widget"

    def test_from_orm_delete_mutation(self):
        gql = GraphQL()
        MockProduct = self._make_mock_orm()
        gql.schema.from_orm(MockProduct)
        result = gql.execute('mutation { deleteProduct(id: "1") }')
        assert result["data"]["deleteProduct"] is True

    def test_multiple_orm_classes(self):
        """Test registering multiple ORM classes on the same schema."""
        from tina4_python.FieldTypes import IntegerField, StringField

        class MockCategory:
            __type_name__ = "Category"

            def __init__(self, data=None):
                self.__field_definitions__ = {}
                self.__field_definitions__["id"] = IntegerField(column_name="id", primary_key=True)
                self.__field_definitions__["name"] = StringField(column_name="name")
                self.id = None
                self.name = None

            def to_dict(self):
                return {"id": self.id, "name": self.name}

            def load(self, f, p):
                self.id = p[0]
                self.name = "Electronics"
                return True

            def save(self):
                return True

            def delete(self, q=None, p=None):
                return True

            def select(self, **kwargs):
                class R:
                    records = [{"id": 1, "name": "Electronics"}]
                return R()

        gql = GraphQL()
        MockProduct = self._make_mock_orm()
        gql.schema.from_orm(MockProduct)
        gql.schema.from_orm(MockCategory)

        assert "Product" in gql.schema.types
        assert "Category" in gql.schema.types
        assert "product" in gql.schema.queries
        assert "category" in gql.schema.queries

        result = gql.execute('{ product(id: "1") { name } category(id: "1") { name } }')
        assert result["data"]["product"]["name"] == "Test Product"
        assert result["data"]["category"]["name"] == "Electronics"


# ─── Edge Cases ─────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_query(self):
        gql = GraphQL()
        result = gql.execute("")
        assert result["data"] is None

    def test_query_with_only_comments(self):
        gql = GraphQL()
        result = gql.execute("# just a comment")
        assert result["data"] is None

    def test_deeply_nested_selection(self):
        gql = GraphQL()
        gql.schema.add_query("company", {
            "type": "Company",
            "args": {},
            "resolve": lambda r, a, c: {
                "name": "Acme",
                "ceo": {
                    "name": "Alice",
                    "address": {
                        "city": "London",
                        "country": "UK",
                    },
                },
            },
        })
        result = gql.execute("{ company { name ceo { name address { city country } } } }")
        assert result["data"]["company"]["name"] == "Acme"
        assert result["data"]["company"]["ceo"]["name"] == "Alice"
        assert result["data"]["company"]["ceo"]["address"]["city"] == "London"

    def test_resolver_exception_captured(self):
        gql = GraphQL()
        gql.schema.add_query("fail", {
            "type": "String",
            "args": {},
            "resolve": lambda r, a, c: 1 / 0,
        })
        result = gql.execute("{ fail }")
        assert result["data"]["fail"] is None
        assert len(result["errors"]) == 1
        assert "division by zero" in result["errors"][0]["message"]

    def test_null_resolver_result(self):
        gql = GraphQL()
        gql.schema.add_query("nothing", {
            "type": "User",
            "args": {},
            "resolve": lambda r, a, c: None,
        })
        result = gql.execute("{ nothing { id } }")
        assert result["data"]["nothing"] is None

    def test_enum_value(self):
        gql = GraphQL()
        gql.schema.add_query("status", {
            "type": "String",
            "args": {"state": "Status"},
            "resolve": lambda r, a, c: a.get("state"),
        })
        result = gql.execute("{ status(state: ACTIVE) }")
        assert result["data"]["status"] == "ACTIVE"

    def test_named_mutation(self):
        gql = GraphQL()
        gql.schema.add_mutation("ping", {
            "type": "String",
            "args": {},
            "resolve": lambda r, a, c: "pong",
        })
        result = gql.execute("mutation Ping { ping }")
        assert result["data"]["ping"] == "pong"

    def test_multiple_fragments(self):
        gql = GraphQL()
        gql.schema.add_query("user", {
            "type": "User",
            "args": {},
            "resolve": lambda r, a, c: {"id": "1", "name": "Alice", "email": "a@b.com", "age": 30},
        })
        result = gql.execute("""
            fragment Basic on User { id name }
            fragment Contact on User { email }
            query { user { ...Basic ...Contact } }
        """)
        assert result["data"]["user"]["id"] == "1"
        assert result["data"]["user"]["name"] == "Alice"
        assert result["data"]["user"]["email"] == "a@b.com"
        assert "age" not in result["data"]["user"]
