#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""
Zero-dependency GraphQL engine for Tina4 Python.

Provides a recursive-descent parser, schema builder, query executor,
ORM auto-generation, and one-line route registration — matching the
feature set of the PHP and Ruby Tina4 GraphQL implementations.

Usage:
    from tina4_python.GraphQL import GraphQL, GraphQLSchema

    gql = GraphQL()
    gql.schema.from_orm(User)
    gql.register_route("/graphql")
"""

import json
import re
from tina4_python.Debug import Debug

__all__ = [
    "GraphQL",
    "GraphQLSchema",
    "GraphQLType",
]

# ─── Lexer ──────────────────────────────────────────────────────────

_TOKEN_PATTERN = re.compile(
    r"""
      (?P<NAME>[_A-Za-z][_0-9A-Za-z]*)
    | (?P<FLOAT_VALUE>-?(?:0|[1-9]\d*)\.(?:\d+)(?:[eE][+-]?\d+)?)
    | (?P<INT_VALUE>-?(?:0|[1-9]\d*))
    | (?P<STRING>"(?:[^"\\]|\\.)*")
    | (?P<SPREAD>\.\.\.)
    | (?P<COLON>:)
    | (?P<PUNCT>[!$()=@\[\]{}|])
    | (?P<COMMA>,)
    | (?P<WS>\s+)
    | (?P<COMMENT>\#[^\n]*)
    """,
    re.VERBOSE,
)


def _tokenize(source):
    tokens = []
    for m in _TOKEN_PATTERN.finditer(source):
        kind = m.lastgroup
        value = m.group()
        if kind in ("WS", "COMMENT", "COMMA"):
            continue
        if kind == "STRING":
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n").replace("\\t", "\t")
            kind = "STRING"
        elif kind == "FLOAT_VALUE":
            value = float(value)
            kind = "FLOAT"
        elif kind == "INT_VALUE":
            value = int(value)
            kind = "INT"
        tokens.append((kind, value))
    return tokens


# ─── Parser ─────────────────────────────────────────────────────────

class _Parser:
    """Recursive-descent GraphQL parser.

    Supports queries, mutations, variables, fragments, aliases,
    inline fragments, and directives (@skip, @include).
    """

    def __init__(self, source):
        self.tokens = _tokenize(source)
        self.pos = 0

    def _peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return (None, None)

    def _advance(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _expect(self, kind, value=None):
        tok = self._peek()
        if tok[0] != kind or (value is not None and tok[1] != value):
            raise GraphQLError(f"Expected {kind} {value!r}, got {tok}")
        return self._advance()

    def _expect_punct(self, ch):
        return self._expect("PUNCT", ch)

    def _at(self, kind, value=None):
        tok = self._peek()
        if tok[0] != kind:
            return False
        if value is not None and tok[1] != value:
            return False
        return True

    def _at_punct(self, ch):
        return self._at("PUNCT", ch)

    # ── Document ──

    def parse(self):
        """Parse a full GraphQL document → list of definitions."""
        definitions = []
        while self._peek()[0] is not None:
            definitions.append(self._parse_definition())
        return {"kind": "Document", "definitions": definitions}

    def _parse_definition(self):
        tok = self._peek()
        if tok[0] == "NAME" and tok[1] == "fragment":
            return self._parse_fragment_definition()
        return self._parse_operation_definition()

    # ── Operations ──

    def _parse_operation_definition(self):
        tok = self._peek()
        if tok[0] == "NAME" and tok[1] in ("query", "mutation", "subscription"):
            operation = self._advance()[1]
            name = None
            if self._peek()[0] == "NAME":
                name = self._advance()[1]
            variables = self._parse_variable_definitions() if self._at_punct("(") else []
            directives = self._parse_directives()
            selections = self._parse_selection_set()
            return {
                "kind": "OperationDefinition",
                "operation": operation,
                "name": name,
                "variableDefinitions": variables,
                "directives": directives,
                "selectionSet": selections,
            }
        # Shorthand query
        selections = self._parse_selection_set()
        return {
            "kind": "OperationDefinition",
            "operation": "query",
            "name": None,
            "variableDefinitions": [],
            "directives": [],
            "selectionSet": selections,
        }

    def _parse_variable_definitions(self):
        self._expect_punct("(")
        defs = []
        while not self._at_punct(")"):
            defs.append(self._parse_variable_definition())
        self._expect_punct(")")
        return defs

    def _parse_variable_definition(self):
        self._expect("PUNCT", "$")
        name = self._expect("NAME")[1]
        self._expect("COLON")
        var_type = self._parse_type_ref()
        default = None
        if self._at_punct("="):
            self._advance()
            default = self._parse_value_literal(const=True)
        return {"kind": "VariableDefinition", "name": name, "type": var_type, "defaultValue": default}

    # ── Fragments ──

    def _parse_fragment_definition(self):
        self._expect("NAME", "fragment")
        name = self._expect("NAME")[1]
        self._expect("NAME", "on")
        type_condition = self._expect("NAME")[1]
        directives = self._parse_directives()
        selections = self._parse_selection_set()
        return {
            "kind": "FragmentDefinition",
            "name": name,
            "typeCondition": type_condition,
            "directives": directives,
            "selectionSet": selections,
        }

    # ── Selection set ──

    def _parse_selection_set(self):
        self._expect_punct("{")
        selections = []
        while not self._at_punct("}"):
            selections.append(self._parse_selection())
        self._expect_punct("}")
        return selections

    def _parse_selection(self):
        if self._at("SPREAD"):
            return self._parse_fragment_spread_or_inline()
        return self._parse_field()

    def _parse_field(self):
        name_or_alias = self._expect("NAME")[1]
        alias = None
        if self._at("COLON"):
            self._advance()
            alias = name_or_alias
            name_or_alias = self._expect("NAME")[1]
        name = name_or_alias
        arguments = self._parse_arguments() if self._at_punct("(") else []
        directives = self._parse_directives()
        selection_set = self._parse_selection_set() if self._at_punct("{") else []
        return {
            "kind": "Field",
            "alias": alias,
            "name": name,
            "arguments": arguments,
            "directives": directives,
            "selectionSet": selection_set,
        }

    def _parse_fragment_spread_or_inline(self):
        self._expect("SPREAD")
        if self._at("NAME") and self._peek()[1] != "on":
            name = self._expect("NAME")[1]
            directives = self._parse_directives()
            return {"kind": "FragmentSpread", "name": name, "directives": directives}
        # Inline fragment
        type_condition = None
        if self._at("NAME") and self._peek()[1] == "on":
            self._advance()
            type_condition = self._expect("NAME")[1]
        directives = self._parse_directives()
        selections = self._parse_selection_set()
        return {
            "kind": "InlineFragment",
            "typeCondition": type_condition,
            "directives": directives,
            "selectionSet": selections,
        }

    # ── Arguments ──

    def _parse_arguments(self):
        self._expect_punct("(")
        args = []
        while not self._at_punct(")"):
            name = self._expect("NAME")[1]
            self._expect("COLON")
            value = self._parse_value_literal(const=False)
            args.append({"name": name, "value": value})
        self._expect_punct(")")
        return args

    # ── Directives ──

    def _parse_directives(self):
        directives = []
        while self._at_punct("@"):
            self._advance()
            name = self._expect("NAME")[1]
            arguments = self._parse_arguments() if self._at_punct("(") else []
            directives.append({"kind": "Directive", "name": name, "arguments": arguments})
        return directives

    # ── Type references ──

    def _parse_type_ref(self):
        if self._at_punct("["):
            self._advance()
            inner = self._parse_type_ref()
            self._expect_punct("]")
            non_null = False
            if self._at_punct("!"):
                self._advance()
                non_null = True
            return {"kind": "ListType", "type": inner, "nonNull": non_null}
        name = self._expect("NAME")[1]
        non_null = False
        if self._at_punct("!"):
            self._advance()
            non_null = True
        return {"kind": "NamedType", "name": name, "nonNull": non_null}

    # ── Values ──

    def _parse_value_literal(self, const=False):
        tok = self._peek()

        if not const and tok[0] == "PUNCT" and tok[1] == "$":
            self._advance()
            name = self._expect("NAME")[1]
            return {"kind": "Variable", "name": name}

        if tok[0] == "INT":
            self._advance()
            return {"kind": "IntValue", "value": tok[1]}

        if tok[0] == "FLOAT":
            self._advance()
            return {"kind": "FloatValue", "value": tok[1]}

        if tok[0] == "STRING":
            self._advance()
            return {"kind": "StringValue", "value": tok[1]}

        if tok[0] == "NAME":
            self._advance()
            val = tok[1]
            if val == "true":
                return {"kind": "BooleanValue", "value": True}
            if val == "false":
                return {"kind": "BooleanValue", "value": False}
            if val == "null":
                return {"kind": "NullValue", "value": None}
            return {"kind": "EnumValue", "value": val}

        if self._at_punct("["):
            self._advance()
            values = []
            while not self._at_punct("]"):
                values.append(self._parse_value_literal(const=const))
            self._expect_punct("]")
            return {"kind": "ListValue", "values": values}

        if self._at_punct("{"):
            self._advance()
            fields = {}
            while not self._at_punct("}"):
                name = self._expect("NAME")[1]
                self._expect("COLON")
                value = self._parse_value_literal(const=const)
                fields[name] = value
            self._expect_punct("}")
            return {"kind": "ObjectValue", "fields": fields}

        raise GraphQLError(f"Unexpected token in value: {tok}")


# ─── Error ──────────────────────────────────────────────────────────

class GraphQLError(Exception):
    """Represents a GraphQL execution or parse error."""

    def __init__(self, message, path=None):
        super().__init__(message)
        self.path = path or []


# ─── Type System ────────────────────────────────────────────────────

# Built-in scalar names
_BUILTIN_SCALARS = {"String", "Int", "Float", "Boolean", "ID"}


class GraphQLType:
    """Represents a GraphQL type (OBJECT, SCALAR, LIST, NON_NULL, INPUT_OBJECT)."""

    def __init__(self, name, kind="OBJECT", fields=None):
        self.name = name
        self.kind = kind
        self.fields = fields or {}

    @staticmethod
    def scalar(name):
        return GraphQLType(name, "SCALAR")

    @staticmethod
    def list_of(inner_type_name):
        return f"[{inner_type_name}]"

    @staticmethod
    def non_null(type_name):
        return f"{type_name}!"


# ─── Schema ─────────────────────────────────────────────────────────

class GraphQLSchema:
    """Holds types, queries, and mutations.

    Supports manual registration and auto-generation from ORM classes.
    """

    def __init__(self):
        self.types = {}
        self.queries = {}
        self.mutations = {}

    def add_type(self, name, fields):
        """Register an object type.

        Args:
            name: Type name (e.g. "Product")
            fields: dict mapping field names to type strings
                    e.g. {"id": "ID", "name": "String", "price": "Float"}
                    or {"id": {"type": "ID"}, ...}
        """
        normalised = {}
        for k, v in fields.items():
            if isinstance(v, dict):
                normalised[k] = v.get("type", "String")
            else:
                normalised[k] = v
        self.types[name] = GraphQLType(name, "OBJECT", normalised)

    def add_query(self, name, definition):
        """Register a query field.

        Args:
            name: Query name (e.g. "user", "users")
            definition: dict with keys:
                type: Return type string (e.g. "User", "[User]")
                args: dict of argument name → type string
                resolve: callable(root, args, context) → result
        """
        self.queries[name] = definition

    def add_mutation(self, name, definition):
        """Register a mutation field.

        Args:
            name: Mutation name (e.g. "createUser")
            definition: dict with keys:
                type: Return type string
                args: dict of argument name → type string
                resolve: callable(root, args, context) → result
        """
        self.mutations[name] = definition

    # ── ORM auto-generation ──

    _FIELD_TYPE_MAP = {
        "IntegerField": "Int",
        "NumericField": "Float",
        "StringField": "String",
        "TextField": "String",
        "DateTimeField": "String",
        "BlobField": "String",
        "JSONBField": "String",
        "ForeignKeyField": "Int",
    }

    def from_orm(self, orm_class):
        """Auto-generate types, queries, and mutations from a Tina4 ORM class.

        Creates:
            - Object type with fields from ORM field definitions
            - Query: <name>(id: ID) — fetch single record
            - Query: <names>(limit: Int, offset: Int) — paginated list
            - Mutation: create<Name>(input: <Name>Input) — insert
            - Mutation: update<Name>(id: ID!, input: <Name>Input) — update
            - Mutation: delete<Name>(id: ID!) — delete, returns Boolean

        Args:
            orm_class: A Tina4 ORM subclass (the class itself, not an instance)
        """
        from tina4_python.FieldTypes import BaseField, ForeignKeyField

        # Support both real ORM classes and classes with explicit __name__
        type_name = getattr(orm_class, "__type_name__", None) or orm_class.__name__

        # Introspect field definitions from the class
        gql_fields = {}
        primary_key_field = None

        # Get field definitions from a temporary instance
        instance = orm_class()
        field_defs = getattr(instance, "__field_definitions__", {})

        if not field_defs:
            # Fallback: inspect class attributes directly
            for attr_name in dir(orm_class):
                if attr_name.startswith("_"):
                    continue
                attr = getattr(orm_class, attr_name, None)
                if isinstance(attr, (BaseField, ForeignKeyField)):
                    field_defs[attr_name] = attr

        for field_name, field_obj in field_defs.items():
            field_class_name = type(field_obj).__name__
            gql_type = self._FIELD_TYPE_MAP.get(field_class_name, "String")

            if getattr(field_obj, "primary_key", False):
                gql_type = "ID"
                primary_key_field = field_name

            if getattr(field_obj, "protected_field", False):
                continue

            gql_fields[field_name] = gql_type

        if not gql_fields:
            Debug.warning(f"GraphQL: No fields found on ORM class {type_name}")
            return

        # Register the type
        self.add_type(type_name, gql_fields)

        # Determine names
        lower_name = type_name[0].lower() + type_name[1:]
        plural_name = lower_name + "s"
        pk = primary_key_field or "id"

        # Query: single record by ID
        def _make_single_resolver(_cls, _pk):
            def resolve(root, args, context):
                instance = _cls()
                pk_val = args.get("id")
                if pk_val is not None:
                    if instance.load(f"{_pk} = ?", [pk_val]):
                        return instance.to_dict()
                return None
            return resolve

        self.add_query(lower_name, {
            "type": type_name,
            "args": {"id": "ID"},
            "resolve": _make_single_resolver(orm_class, pk),
        })

        # Query: paginated list
        def _make_list_resolver(_cls):
            def resolve(root, args, context):
                limit = args.get("limit", 10)
                offset = args.get("offset", 0)
                result = _cls().select(limit=limit, skip=offset)
                if hasattr(result, "records"):
                    return result.records
                return list(result)
            return resolve

        self.add_query(plural_name, {
            "type": f"[{type_name}]",
            "args": {"limit": "Int", "offset": "Int"},
            "resolve": _make_list_resolver(orm_class),
        })

        # Mutation: create
        def _make_create_resolver(_cls):
            def resolve(root, args, context):
                input_data = args.get("input", {})
                instance = _cls(input_data)
                instance.save()
                return instance.to_dict()
            return resolve

        input_fields = {k: v for k, v in gql_fields.items() if k != pk}
        self.add_mutation(f"create{type_name}", {
            "type": type_name,
            "args": {"input": f"{type_name}Input"},
            "resolve": _make_create_resolver(orm_class),
        })

        # Mutation: update
        def _make_update_resolver(_cls, _pk):
            def resolve(root, args, context):
                pk_val = args.get("id")
                input_data = args.get("input", {})
                instance = _cls()
                if instance.load(f"{_pk} = ?", [pk_val]):
                    for k, v in input_data.items():
                        if hasattr(instance, k):
                            setattr(instance, k, v)
                    instance.save()
                    return instance.to_dict()
                return None
            return resolve

        self.add_mutation(f"update{type_name}", {
            "type": type_name,
            "args": {"id": "ID!", "input": f"{type_name}Input"},
            "resolve": _make_update_resolver(orm_class, pk),
        })

        # Mutation: delete
        def _make_delete_resolver(_cls, _pk):
            def resolve(root, args, context):
                pk_val = args.get("id")
                instance = _cls()
                if instance.load(f"{_pk} = ?", [pk_val]):
                    instance.delete()
                    return True
                return False
            return resolve

        self.add_mutation(f"delete{type_name}", {
            "type": "Boolean",
            "args": {"id": "ID!"},
            "resolve": _make_delete_resolver(orm_class, pk),
        })

        Debug.info(f"GraphQL: Registered ORM type '{type_name}' with {len(gql_fields)} fields")


# ─── Executor ───────────────────────────────────────────────────────

class _Executor:
    """Executes a parsed GraphQL document against a schema."""

    def __init__(self, schema, variables=None, context=None):
        self.schema = schema
        self.variables = variables or {}
        self.context = context
        self.errors = []
        self.fragments = {}

    def execute(self, document):
        # Collect fragments first
        for defn in document["definitions"]:
            if defn["kind"] == "FragmentDefinition":
                self.fragments[defn["name"]] = defn

        # Find the operation
        operation = None
        for defn in document["definitions"]:
            if defn["kind"] == "OperationDefinition":
                operation = defn
                break

        if operation is None:
            return {"data": None, "errors": [{"message": "No operation found"}]}

        # Resolve default variable values
        for var_def in operation.get("variableDefinitions", []):
            name = var_def["name"]
            if name not in self.variables and var_def.get("defaultValue") is not None:
                self.variables[name] = self._resolve_value(var_def["defaultValue"])

        op_type = operation.get("operation", "query")
        if op_type == "query":
            fields = self.schema.queries
        elif op_type == "mutation":
            fields = self.schema.mutations
        else:
            return {"data": None, "errors": [{"message": f"Unsupported operation: {op_type}"}]}

        data = self._execute_selection_set(operation["selectionSet"], fields, None, [])

        result = {"data": data}
        if self.errors:
            result["errors"] = [{"message": str(e), "path": e.path} if isinstance(e, GraphQLError) else {"message": str(e)} for e in self.errors]
        return result

    def _execute_selection_set(self, selections, field_defs, parent_value, path):
        result = {}
        for selection in selections:
            if selection["kind"] == "Field":
                if not self._should_include(selection.get("directives", [])):
                    continue
                self._execute_field(selection, field_defs, parent_value, path, result)
            elif selection["kind"] == "FragmentSpread":
                if not self._should_include(selection.get("directives", [])):
                    continue
                frag = self.fragments.get(selection["name"])
                if frag:
                    for sel in frag["selectionSet"]:
                        if sel["kind"] == "Field":
                            if not self._should_include(sel.get("directives", [])):
                                continue
                            self._execute_field(sel, field_defs, parent_value, path, result)
                        elif sel["kind"] == "FragmentSpread":
                            sub = self._execute_selection_set([sel], field_defs, parent_value, path)
                            result.update(sub)
                else:
                    self.errors.append(GraphQLError(f"Fragment '{selection['name']}' not found", path))
            elif selection["kind"] == "InlineFragment":
                if not self._should_include(selection.get("directives", [])):
                    continue
                for sel in selection["selectionSet"]:
                    if sel["kind"] == "Field":
                        self._execute_field(sel, field_defs, parent_value, path, result)
        return result

    def _execute_field(self, field, field_defs, parent_value, path, result):
        name = field["name"]
        alias = field.get("alias") or name
        field_path = path + [alias]

        # Resolve arguments
        args = {}
        for arg in field.get("arguments", []):
            args[arg["name"]] = self._resolve_value(arg["value"])

        # Handle __typename
        if name == "__typename":
            result[alias] = "Query" if parent_value is None else type(parent_value).__name__
            return

        try:
            if parent_value is not None:
                # Nested field — resolve from parent
                if isinstance(parent_value, dict):
                    value = parent_value.get(name)
                elif hasattr(parent_value, name):
                    value = getattr(parent_value, name)
                else:
                    value = None
            else:
                # Root field — use resolver
                field_def = field_defs.get(name)
                if field_def is None:
                    self.errors.append(GraphQLError(f"Field '{name}' not found", field_path))
                    result[alias] = None
                    return
                resolver = field_def.get("resolve")
                if resolver is None:
                    self.errors.append(GraphQLError(f"No resolver for field '{name}'", field_path))
                    result[alias] = None
                    return
                value = resolver(None, args, self.context)

            # If the field has sub-selections, resolve them
            if field.get("selectionSet") and value is not None:
                if isinstance(value, list):
                    resolved = []
                    for i, item in enumerate(value):
                        sub_result = self._execute_selection_set(
                            field["selectionSet"], {}, item, field_path + [i]
                        )
                        resolved.append(sub_result)
                    value = resolved
                elif isinstance(value, dict) or hasattr(value, "__dict__"):
                    value = self._execute_selection_set(
                        field["selectionSet"], {}, value, field_path
                    )

            result[alias] = value

        except Exception as e:
            self.errors.append(GraphQLError(str(e), field_path))
            result[alias] = None

    def _resolve_value(self, node):
        """Resolve a parsed value node to a Python value."""
        if node is None:
            return None
        kind = node.get("kind")
        if kind == "Variable":
            return self.variables.get(node["name"])
        if kind in ("IntValue", "FloatValue", "BooleanValue", "NullValue", "EnumValue", "StringValue"):
            return node["value"]
        if kind == "ListValue":
            return [self._resolve_value(v) for v in node["values"]]
        if kind == "ObjectValue":
            return {k: self._resolve_value(v) for k, v in node["fields"].items()}
        return None

    def _should_include(self, directives):
        """Evaluate @skip and @include directives."""
        for d in directives:
            args = {a["name"]: self._resolve_value(a["value"]) for a in d.get("arguments", [])}
            if d["name"] == "skip" and args.get("if") is True:
                return False
            if d["name"] == "include" and args.get("if") is False:
                return False
        return True


# ─── GraphQL Engine ─────────────────────────────────────────────────

# Inline GraphiQL HTML template
_GRAPHIQL_HTML = """<!DOCTYPE html>
<html>
<head>
  <title>GraphiQL — Tina4</title>
  <style>
    body { height: 100vh; margin: 0; width: 100%; overflow: hidden; }
    #graphiql { height: 100vh; }
  </style>
  <link rel="stylesheet" href="https://unpkg.com/graphiql/graphiql.min.css" />
</head>
<body>
  <div id="graphiql">Loading...</div>
  <script crossorigin src="https://unpkg.com/react/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom/umd/react-dom.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/graphiql/graphiql.min.js"></script>
  <script>
    const fetcher = GraphiQL.createFetcher({ url: '{{ENDPOINT}}' });
    ReactDOM.render(
      React.createElement(GraphiQL, { fetcher: fetcher }),
      document.getElementById('graphiql')
    );
  </script>
</body>
</html>"""


class GraphQL:
    """Main GraphQL engine — ties together schema, parser, and executor.

    Example:
        gql = GraphQL()
        gql.schema.from_orm(User)
        gql.schema.from_orm(Product)
        gql.register_route("/graphql")
    """

    def __init__(self, schema=None):
        self.schema = schema or GraphQLSchema()

    def execute(self, query, variables=None, context=None):
        """Parse and execute a GraphQL query string.

        Args:
            query: GraphQL query string
            variables: dict of variable values
            context: arbitrary context passed to all resolvers

        Returns:
            dict with "data" and optionally "errors"
        """
        try:
            parser = _Parser(query)
            document = parser.parse()
        except (GraphQLError, Exception) as e:
            return {"data": None, "errors": [{"message": f"Parse error: {e}"}]}

        executor = _Executor(self.schema, variables=variables, context=context)
        return executor.execute(document)

    def handle_request(self, body, context=None):
        """Handle an HTTP request body (JSON string or dict).

        Args:
            body: JSON string or dict with "query", optional "variables", optional "operationName"
            context: arbitrary context passed to resolvers

        Returns:
            dict with "data" and optionally "errors"
        """
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError as e:
                return {"data": None, "errors": [{"message": f"Invalid JSON: {e}"}]}

        if not isinstance(body, dict):
            return {"data": None, "errors": [{"message": "Request body must be a JSON object"}]}

        query = body.get("query")
        if not query:
            return {"data": None, "errors": [{"message": "No query provided"}]}

        variables = body.get("variables") or {}
        return self.execute(query, variables=variables, context=context)

    def register_route(self, path="/graphql"):
        """Register POST and GET routes for the GraphQL endpoint.

        POST <path> — execute GraphQL queries
        GET  <path> — serve GraphiQL interactive IDE

        Args:
            path: URL path (default: "/graphql")
        """
        from tina4_python.Router import get as route_get, post as route_post, noauth as route_noauth

        gql_instance = self
        graphiql_html = _GRAPHIQL_HTML.replace("{{ENDPOINT}}", path)

        @route_noauth()
        @route_post(path)
        async def _graphql_post(request, response):
            body = request.body
            context = {"request": request}
            result = gql_instance.handle_request(body, context=context)
            return response(result)

        @route_noauth()
        @route_get(path)
        async def _graphql_get(request, response):
            # Check if it's a query via query params
            if request.params and request.params.get("query"):
                variables = {}
                if request.params.get("variables"):
                    try:
                        variables = json.loads(request.params["variables"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                context = {"request": request}
                result = gql_instance.execute(request.params["query"], variables=variables, context=context)
                return response(result)
            # Serve GraphiQL IDE
            return response(graphiql_html)
