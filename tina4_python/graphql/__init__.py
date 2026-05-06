# Tina4 GraphQL — Zero-dependency GraphQL engine.
"""
Recursive-descent parser, schema builder, and query executor.

    from tina4_python.graphql import GraphQL

    gql = GraphQL()
    gql.schema.add_type("User", {"id": "ID", "name": "String", "email": "String"})
    gql.schema.add_query("user", {"id": "ID!"}, "User",
                          lambda root, args, ctx: get_user(args["id"]))
    result = gql.execute('{ user(id: "1") { name email } }')

Supported:
    - Queries, mutations
    - Variables, default values
    - Fragments (named and inline)
    - Aliases
    - @skip / @include directives
    - Nested selections
    - List types ([Type])
    - Non-null types (Type!)
    - ORM auto-generation
    - Error capture (resolver exceptions become GraphQL errors)
"""
import json
import os
import re
from typing import Any


# ── Lexer ─────────────────────────────────────────────────────

class Token:
    __slots__ = ("type", "value", "pos")

    def __init__(self, type: str, value: str, pos: int = 0):
        self.type = type
        self.value = value
        self.pos = pos

    def __repr__(self):
        return f"Token({self.type}, {self.value!r})"


_TOKENS = [
    ("SPREAD", r"\.\.\."),
    ("LBRACE", r"\{"),
    ("RBRACE", r"\}"),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("LBRACKET", r"\["),
    ("RBRACKET", r"\]"),
    ("COLON", r":"),
    ("BANG", r"!"),
    ("EQUALS", r"="),
    ("AT", r"@"),
    ("DOLLAR", r"\$"),
    ("COMMA", r","),
    ("STRING", r'"(?:[^"\\]|\\.)*"'),
    ("NUMBER", r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?"),
    ("BOOL", r"\b(?:true|false)\b"),
    ("NULL", r"\bnull\b"),
    ("NAME", r"[_a-zA-Z]\w*"),
    ("SKIP", r"[\s,]+"),
    ("COMMENT", r"#[^\n]*"),
]
_PATTERN = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in _TOKENS))


def tokenize(source: str) -> list[Token]:
    tokens = []
    for m in _PATTERN.finditer(source):
        kind = m.lastgroup
        if kind in ("SKIP", "COMMENT"):
            continue
        tokens.append(Token(kind, m.group(), m.start()))
    return tokens


# ── Parser ────────────────────────────────────────────────────

class ParseError(Exception):
    pass


class Parser:
    """Recursive-descent GraphQL parser."""

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def advance(self) -> Token:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def expect(self, type: str, value: str = None) -> Token:
        t = self.peek()
        if not t or t.type != type or (value and t.value != value):
            expected = f"{type}({value})" if value else type
            got = f"{t.type}({t.value})" if t else "EOF"
            raise ParseError(f"Expected {expected}, got {got}")
        return self.advance()

    def match(self, type: str, value: str = None) -> Token | None:
        t = self.peek()
        if t and t.type == type and (value is None or t.value == value):
            return self.advance()
        return None

    def parse(self) -> dict:
        """Parse a full document."""
        doc = {"definitions": []}
        while self.pos < len(self.tokens):
            doc["definitions"].append(self._parse_definition())
        return doc

    def _parse_definition(self) -> dict:
        t = self.peek()
        if t and t.type == "NAME" and t.value == "fragment":
            return self._parse_fragment()
        return self._parse_operation()

    def _parse_operation(self) -> dict:
        t = self.peek()
        op_type = "query"
        name = None
        variables = []

        if t and t.type == "NAME" and t.value in ("query", "mutation", "subscription"):
            op_type = self.advance().value
            if self.peek() and self.peek().type == "NAME":
                name = self.advance().value
            if self.match("LPAREN"):
                variables = self._parse_variable_defs()
                self.expect("RPAREN")

        directives = self._parse_directives()
        selections = self._parse_selection_set()

        return {
            "kind": "operation",
            "operation": op_type,
            "name": name,
            "variables": variables,
            "directives": directives,
            "selections": selections,
        }

    def _parse_fragment(self) -> dict:
        self.expect("NAME", "fragment")
        name = self.expect("NAME").value
        self.expect("NAME", "on")
        type_name = self.expect("NAME").value
        directives = self._parse_directives()
        selections = self._parse_selection_set()
        return {
            "kind": "fragment",
            "name": name,
            "on": type_name,
            "directives": directives,
            "selections": selections,
        }

    def _parse_selection_set(self) -> list:
        self.expect("LBRACE")
        selections = []
        while not self.match("RBRACE"):
            if self.match("SPREAD"):
                if self.peek() and self.peek().type == "NAME" and self.peek().value == "on":
                    self.advance()
                    type_name = self.expect("NAME").value
                    directives = self._parse_directives()
                    sels = self._parse_selection_set()
                    selections.append({
                        "kind": "inline_fragment",
                        "on": type_name,
                        "directives": directives,
                        "selections": sels,
                    })
                elif self.peek() and self.peek().type == "LBRACE":
                    directives = self._parse_directives()
                    sels = self._parse_selection_set()
                    selections.append({
                        "kind": "inline_fragment",
                        "on": None,
                        "directives": directives,
                        "selections": sels,
                    })
                else:
                    name = self.expect("NAME").value
                    directives = self._parse_directives()
                    selections.append({
                        "kind": "fragment_spread",
                        "name": name,
                        "directives": directives,
                    })
            else:
                selections.append(self._parse_field())
        return selections

    def _parse_field(self) -> dict:
        name = self.expect("NAME").value
        alias = None

        if self.match("COLON"):
            alias = name
            name = self.expect("NAME").value

        args = {}
        if self.match("LPAREN"):
            args = self._parse_arguments()
            self.expect("RPAREN")

        directives = self._parse_directives()

        selections = None
        if self.peek() and self.peek().type == "LBRACE":
            selections = self._parse_selection_set()

        return {
            "kind": "field",
            "name": name,
            "alias": alias,
            "args": args,
            "directives": directives,
            "selections": selections,
        }

    def _parse_arguments(self) -> dict:
        args = {}
        while self.peek() and self.peek().type != "RPAREN":
            name = self.expect("NAME").value
            self.expect("COLON")
            args[name] = self._parse_value()
            self.match("COMMA")  # optional comma between arguments
        return args

    def _parse_value(self) -> Any:
        t = self.peek()
        if not t:
            raise ParseError("Unexpected EOF in value")

        if t.type == "STRING":
            self.advance()
            return t.value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        if t.type == "NUMBER":
            self.advance()
            return float(t.value) if "." in t.value or "e" in t.value.lower() else int(t.value)
        if t.type == "BOOL":
            self.advance()
            return t.value == "true"
        if t.type == "NULL":
            self.advance()
            return None
        if t.type == "NAME":
            self.advance()
            return t.value
        if t.type == "DOLLAR":
            self.advance()
            name = self.expect("NAME").value
            return {"$var": name}
        if t.type == "LBRACKET":
            self.advance()
            items = []
            while not self.match("RBRACKET"):
                items.append(self._parse_value())
            return items
        if t.type == "LBRACE":
            self.advance()
            obj = {}
            while not self.match("RBRACE"):
                key = self.expect("NAME").value
                self.expect("COLON")
                obj[key] = self._parse_value()
            return obj

        raise ParseError(f"Unexpected token: {t}")

    def _parse_directives(self) -> list:
        directives = []
        while self.peek() and self.peek().type == "AT":
            self.advance()
            name = self.expect("NAME").value
            args = {}
            if self.match("LPAREN"):
                args = self._parse_arguments()
                self.expect("RPAREN")
            directives.append({"name": name, "args": args})
        return directives

    def _parse_variable_defs(self) -> list:
        defs = []
        while self.peek() and self.peek().type == "DOLLAR":
            self.advance()
            name = self.expect("NAME").value
            self.expect("COLON")
            type_name = self._parse_type_ref()
            default = None
            if self.match("EQUALS"):
                default = self._parse_value()
            defs.append({"name": name, "type": type_name, "default": default})
            self.match("COMMA")  # optional comma between variable defs
        return defs

    def _parse_type_ref(self) -> str:
        if self.match("LBRACKET"):
            inner = self._parse_type_ref()
            self.expect("RBRACKET")
            t = f"[{inner}]"
        else:
            t = self.expect("NAME").value
        if self.match("BANG"):
            t += "!"
        return t


# ── Type System ───────────────────────────────────────────────

class GraphQLType:
    """Lightweight type wrapper matching Ruby's GraphQLType."""

    SCALARS = ("String", "Int", "Float", "Boolean", "ID")

    __slots__ = ("name", "kind", "of_type")

    def __init__(self, name: str, kind: str = "object", of_type: "GraphQLType | None" = None):
        self.name = name
        self.kind = kind
        self.of_type = of_type

    @staticmethod
    def parse(type_str: str) -> "GraphQLType":
        """Parse a GraphQL type string like ``"String"``, ``"String!"``, ``"[Int!]!"``."""
        s = str(type_str).strip()
        if s.endswith("!"):
            inner = GraphQLType.parse(s[:-1])
            return GraphQLType(s, "non_null", of_type=inner)
        if s.startswith("[") and s.endswith("]"):
            inner = GraphQLType.parse(s[1:-1])
            return GraphQLType(s, "list", of_type=inner)
        if s in GraphQLType.SCALARS:
            return GraphQLType(s, "scalar")
        return GraphQLType(s, "object")


# ── Schema ────────────────────────────────────────────────────

class Schema:
    """GraphQL schema builder."""

    def __init__(self):
        self.types: dict[str, dict] = {}
        self.queries: dict[str, dict] = {}
        self.mutations: dict[str, dict] = {}

    def add_type(self, name: str, fields: dict[str, str]):
        self.types[name] = fields

    def add_query(self, name: str, args: dict, return_type: str, resolver: callable):
        self.queries[name] = {"args": args, "type": return_type, "resolve": resolver}

    def add_mutation(self, name: str, args: dict, return_type: str, resolver: callable):
        self.mutations[name] = {"args": args, "type": return_type, "resolve": resolver}

    def from_orm(self, orm_class):
        """Auto-generate type, queries, and CRUD mutations from an ORM class."""
        class_name = orm_class.__name__
        fields_meta = getattr(orm_class, "_fields", {})

        gql_fields = {}
        pk_field = None
        for fname, fobj in fields_meta.items():
            ftype = getattr(fobj, "kind", type(fobj).__name__)
            if ftype == "IntegerField":
                gql_type = "Int"
            elif ftype in ("FloatField", "NumericField"):
                gql_type = "Float"
            elif ftype == "BooleanField":
                gql_type = "Boolean"
            elif ftype in ("StringField", "TextField", "DateTimeField"):
                gql_type = "String"
            else:
                gql_type = "String"
            if getattr(fobj, "primary_key", False):
                gql_type = "ID"
                pk_field = fname
            gql_fields[fname] = gql_type

        self.add_type(class_name, gql_fields)

        singular = class_name.lower()
        self.add_query(singular, {"id": "ID!"}, class_name,
                       _make_orm_single_resolver(orm_class, pk_field))

        plural = singular + "s"
        self.add_query(plural, {"limit": "Int", "offset": "Int"}, f"[{class_name}]",
                       _make_orm_list_resolver(orm_class))

        self.add_mutation(f"create{class_name}",
                          {f: "String" for f in gql_fields if f != pk_field},
                          class_name, _make_orm_create_resolver(orm_class))

        self.add_mutation(f"update{class_name}",
                          {"id": "ID!", **{f: "String" for f in gql_fields if f != pk_field}},
                          class_name, _make_orm_update_resolver(orm_class, pk_field))

        self.add_mutation(f"delete{class_name}", {"id": "ID!"}, "Boolean",
                          _make_orm_delete_resolver(orm_class, pk_field))


def _make_orm_single_resolver(orm_class, pk_field):
    def resolve(root, args, ctx):
        obj = orm_class()
        if obj.load(f"{pk_field} = ?", [args["id"]]):
            return obj.to_dict()
        return None
    return resolve


def _make_orm_list_resolver(orm_class):
    def resolve(root, args, ctx):
        limit = args.get("limit", 10)
        offset = args.get("offset", 0)
        records = orm_class.all(limit=limit, offset=offset)
        return [r.to_dict() for r in records]
    return resolve


def _make_orm_create_resolver(orm_class):
    def resolve(root, args, ctx):
        obj = orm_class(args)
        obj.save()
        return obj.to_dict()
    return resolve


def _make_orm_update_resolver(orm_class, pk_field):
    def resolve(root, args, ctx):
        obj = orm_class()
        if obj.load(f"{pk_field} = ?", [args["id"]]):
            for k, v in args.items():
                if k != "id":
                    setattr(obj, k, v)
            obj.save()
            return obj.to_dict()
        return None
    return resolve


def _make_orm_delete_resolver(orm_class, pk_field):
    def resolve(root, args, ctx):
        obj = orm_class()
        if obj.load(f"{pk_field} = ?", [args["id"]]):
            obj.delete()
            return True
        return False
    return resolve


# ── Executor ──────────────────────────────────────────────────

class GraphQL:
    """GraphQL engine — parse, validate, execute.

    Env vars (cross-framework parity v3.12.4):
        TINA4_GRAPHQL_AUTO_SCHEMA  When truthy (default), discovered ORM
                                   subclasses passed via auto_register()
                                   are wired into the schema. Set to false
                                   to opt out and build the schema manually.
        TINA4_GRAPHQL_ENDPOINT     Default URL path for the HTTP endpoint
                                   (default: "/graphql"). Read by .endpoint.
    """

    def __init__(self):
        self.schema = Schema()
        # Default endpoint URL — env-overridable so deployments can mount
        # GraphQL at e.g. /api/graphql without changing app code.
        self.endpoint: str = os.environ.get("TINA4_GRAPHQL_ENDPOINT", "/graphql")
        # Auto-schema toggle. The flag is stored on the instance so the
        # outer app can introspect it (e.g. dev_admin shows "auto-schema:
        # off" in the GraphQL panel) and so test fixtures can flip it
        # without monkey-patching env.
        self.auto_schema: bool = str(
            os.environ.get("TINA4_GRAPHQL_AUTO_SCHEMA", "true")
        ).strip().lower() in ("true", "1", "yes", "on")

    def auto_register(self, *orm_classes) -> int:
        """Wire each ORM class into the schema via from_orm().

        No-op when TINA4_GRAPHQL_AUTO_SCHEMA is falsy. Returns the number
        of classes actually registered. Callers (dev_admin, app bootstrap)
        use this instead of looping themselves so the env-var gate is
        honoured in one place.
        """
        if not self.auto_schema:
            return 0
        count = 0
        for cls in orm_classes:
            self.schema.from_orm(cls)
            count += 1
        return count

    def execute(self, query: str, variables: dict = None, context: dict = None) -> dict:
        """Execute a GraphQL query string. Returns {"data": ..., "errors": [...]}."""
        variables = variables or {}
        context = context or {}
        errors = []

        try:
            tokens = tokenize(query)
            parser = Parser(tokens)
            doc = parser.parse()
        except (ParseError, Exception) as e:
            return {"data": None, "errors": [{"message": str(e)}]}

        fragments = {}
        operations = []
        for defn in doc["definitions"]:
            if defn["kind"] == "fragment":
                fragments[defn["name"]] = defn
            else:
                operations.append(defn)

        if not operations:
            return {"data": None, "errors": [{"message": "No operation found"}]}

        op = operations[0]
        resolvers = self.schema.queries if op["operation"] == "query" else self.schema.mutations

        for vdef in op.get("variables", []):
            if vdef["name"] not in variables and vdef["default"] is not None:
                variables[vdef["name"]] = vdef["default"]

        data = {}
        errs = self._resolve_selections_into(op["selections"], resolvers, None, variables, context, fragments, data)
        errors.extend(errs)

        response = {"data": data}
        if errors:
            response["errors"] = errors
        return response

    def execute_json(self, query: str, variables: dict = None, context: dict = None) -> str:
        """Execute and return JSON string."""
        return json.dumps(self.execute(query, variables, context))

    def _resolve_selections_into(self, selections: list, resolvers: dict, parent: Any,
                                 variables: dict, context: dict, fragments: dict,
                                 target: dict) -> list:
        """Resolve a list of selections and merge results into target dict.

        Fragment spreads and inline fragments are merged (not nested).
        """
        errors = []
        for sel in selections:
            if not self._check_directives(sel.get("directives", []), variables, context):
                continue

            if sel["kind"] == "fragment_spread":
                frag = fragments.get(sel["name"])
                if not frag:
                    errors.append({"message": f"Fragment not found: {sel['name']}"})
                    continue
                errs = self._resolve_selections_into(
                    frag["selections"], resolvers, parent, variables, context, fragments, target
                )
                errors.extend(errs)
                continue

            if sel["kind"] == "inline_fragment":
                errs = self._resolve_selections_into(
                    sel["selections"], resolvers, parent, variables, context, fragments, target
                )
                errors.extend(errs)
                continue

            val, errs = self._resolve_field(sel, resolvers, parent, variables, context, fragments)
            errors.extend(errs)
            key = sel.get("alias") or sel["name"]
            target[key] = val

        return errors

    def _resolve_field(self, sel: dict, resolvers: dict, parent: Any,
                       variables: dict, context: dict, fragments: dict) -> tuple:
        """Resolve a single field selection."""
        errors = []
        name = sel["name"]
        args = self._resolve_args(sel.get("args", {}), variables)

        value = None
        if parent is not None:
            if isinstance(parent, dict):
                value = parent.get(name)
            else:
                value = getattr(parent, name, None)
        elif name in resolvers:
            config = resolvers[name]

            # Input validation
            validation_errors = self._validate_args(args, config.get("args", {}), name)
            if validation_errors:
                return None, validation_errors

            resolver = config.get("resolve")
            if resolver:
                # Inject sub-selections into context for DataLoader/eager-loading
                ctx = dict(context)
                ctx["__selections"] = sel.get("selections", [])
                try:
                    value = resolver(None, args, ctx)
                except Exception as e:
                    errors.append({"message": str(e), "path": [name]})
                    return None, errors

        if not sel.get("selections"):
            return value, errors

        if isinstance(value, list):
            result = []
            for item in value:
                obj = {}
                errs = self._resolve_selections_into(
                    sel["selections"], {}, item, variables, context, fragments, obj
                )
                errors.extend(errs)
                result.append(obj)
            return result, errors

        if value is not None:
            obj = {}
            errs = self._resolve_selections_into(
                sel["selections"], {}, value, variables, context, fragments, obj
            )
            errors.extend(errs)
            return obj, errors

        return None, errors

    def _resolve_args(self, args: dict, variables: dict) -> dict:
        resolved = {}
        for k, v in args.items():
            if isinstance(v, dict) and "$var" in v:
                resolved[k] = variables.get(v["$var"])
            elif isinstance(v, list):
                resolved[k] = [
                    variables.get(i["$var"]) if isinstance(i, dict) and "$var" in i else i
                    for i in v
                ]
            else:
                resolved[k] = v
        return resolved

    def _check_directives(self, directives: list, variables: dict, context: dict = None) -> bool:
        context = context or {}
        for d in directives:
            val = d["args"].get("if")
            if isinstance(val, dict) and "$var" in val:
                val = variables.get(val["$var"], False)

            # Built-in: @skip and @include
            if d["name"] == "skip" and val:
                return False
            if d["name"] == "include" and not val:
                return False

            # Auth: @auth — requires any authenticated user
            if d["name"] == "auth" and not context.get("user"):
                return False

            # Auth: @role(role: "admin") — requires specific role
            if d["name"] == "role":
                required = d["args"].get("role")
                user = context.get("user") or {}
                actual = user.get("role") if isinstance(user, dict) else getattr(user, "role", None)
                if actual is None:
                    actual = context.get("role")
                if required is None or actual != required:
                    return False

            # Auth: @guest — only for unauthenticated
            if d["name"] == "guest" and context.get("user"):
                return False

        return True

    def _validate_args(self, args: dict, arg_configs: dict, field_name: str) -> list:
        """Validate resolved args against declared types. Returns list of errors."""
        errors = []
        for arg_name, declared_type in arg_configs.items():
            value = args.get(arg_name)
            is_non_null = declared_type.endswith("!")
            base_type = declared_type.rstrip("!").strip("[]")

            if is_non_null and (value is None or value == ""):
                errors.append({
                    "message": f"Argument '{arg_name}' on field '{field_name}' is required (type: {declared_type})",
                    "path": [field_name],
                })
                continue

            if value is None:
                continue

            # List validation
            if declared_type.lstrip("!").startswith("[") and isinstance(value, list):
                for i, item in enumerate(value):
                    if not self._coerce_value(item, base_type):
                        errors.append({
                            "message": f"Argument '{arg_name}[{i}]' on field '{field_name}' expected {base_type}, got {type(item).__name__}",
                            "path": [field_name],
                        })
                continue

            # Scalar validation
            if base_type in ("Int", "Float", "Boolean", "String", "ID"):
                if not self._coerce_value(value, base_type):
                    errors.append({
                        "message": f"Argument '{arg_name}' on field '{field_name}' expected type {base_type}, got {type(value).__name__}",
                        "path": [field_name],
                    })

        return errors

    @staticmethod
    def _coerce_value(value, type_name: str) -> bool:
        """Check if a value can be coerced to the given GraphQL scalar type."""
        if type_name in ("String", "ID"):
            return isinstance(value, (str, int, float))
        if type_name == "Int":
            if isinstance(value, bool):
                return False
            if isinstance(value, int):
                return True
            if isinstance(value, str):
                try:
                    int(value)
                    return True
                except ValueError:
                    return False
            return False
        if type_name == "Float":
            if isinstance(value, bool):
                return False
            if isinstance(value, (int, float)):
                return True
            if isinstance(value, str):
                try:
                    float(value)
                    return True
                except ValueError:
                    return False
            return False
        if type_name == "Boolean":
            return isinstance(value, (bool, int)) or value in ("true", "false", "0", "1")
        return True  # Custom types pass through


    def schema_sdl(self) -> str:
        """Return the schema as a GraphQL SDL string."""
        parts = []
        brace_open = "{"
        brace_close = "}"
        for name, fields in self.schema.types.items():
            lines = ["  " + field + ": " + ftype for field, ftype in fields.items()]
            parts.append("type " + name + " " + brace_open + "\n" + "\n".join(lines) + "\n" + brace_close + "\n")
        if self.schema.queries:
            lines = []
            for name, config in self.schema.queries.items():
                args = config.get("args", {})
                arg_parts = [k + ": " + v for k, v in args.items()]
                arg_str = "(" + ", ".join(arg_parts) + ")" if args else ""
                lines.append("  " + name + arg_str + ": " + config["type"])
            parts.append("type Query " + brace_open + "\n" + "\n".join(lines) + "\n" + brace_close + "\n")
        if self.schema.mutations:
            lines = []
            for name, config in self.schema.mutations.items():
                args = config.get("args", {})
                arg_parts = [k + ": " + v for k, v in args.items()]
                arg_str = "(" + ", ".join(arg_parts) + ")" if args else ""
                lines.append("  " + name + arg_str + ": " + config["type"])
            parts.append("type Mutation " + brace_open + "\n" + "\n".join(lines) + "\n" + brace_close + "\n")
        return "\n".join(parts)

    def introspect(self) -> dict:
        return {
            "types": self.schema.types,
            "queries": {k: {"type": v["type"], "args": v.get("args", {})}
                        for k, v in self.schema.queries.items()},
            "mutations": {k: {"type": v["type"], "args": v.get("args", {})}
                          for k, v in self.schema.mutations.items()},
        }


__all__ = ["GraphQL", "Schema", "Parser", "ParseError", "tokenize"]
