"""GraphQL commas are insignificant (GraphQL spec, section 2.1.7).

Commas may separate arguments, selected fields, list values and object fields,
or be left out, and the document means the same thing either way. Ruby's
tokenizer made ',' a token no parse loop consumed, so ``pair(a: 1, b: 2)`` was a
parse error there; this pins the behaviour in Python.

In-process: the real tokenizer, parser and executor. No doubles.
"""
from tina4_python.graphql import GraphQL


def _schema() -> GraphQL:
    gql = GraphQL()
    gql.schema.add_type("Pair", {"sum": "Int", "first": "Int", "second": "Int", "tags": "[String]"})
    gql.schema.add_query(
        "pair", {"a": "Int", "b": "Int", "tags": "[String]", "point": "String"}, "Pair",
        lambda root, args, ctx: {
            "sum": args["a"] + args["b"], "first": args["a"], "second": args["b"],
            "tags": args.get("tags") or [],
        },
    )
    return gql


def test_commas_are_insignificant_between_arguments_and_fields():
    gql = _schema()
    expected = {"sum": 3, "first": 1, "second": 2, "tags": ["x", "y"]}

    with_commas = gql.execute('{ pair(a: 1, b: 2, tags: ["x", "y"]) { sum, first, second, tags } }')
    assert with_commas.get("errors") is None, with_commas
    assert with_commas["data"]["pair"] == expected, with_commas

    without_commas = gql.execute('{ pair(a: 1 b: 2 tags: ["x" "y"]) { sum first second tags } }')
    assert without_commas["data"]["pair"] == expected, without_commas

    # A trailing comma and repeated commas are still insignificant.
    extra = gql.execute('{ pair(a: 1,, b: 2,) { sum,, first, second, tags, } }')
    assert extra.get("errors") is None, extra
    assert extra["data"]["pair"]["sum"] == 3, extra

    # A comma inside a string value is data, not a separator.
    quoted = gql.execute('{ pair(a: 1, b: 2, tags: ["a,b", "c"]) { tags } }')
    assert quoted["data"]["pair"]["tags"] == ["a,b", "c"], quoted

    # Commas between top-level fields, with aliases and variables.
    aliased = gql.execute(
        'query Q($x: Int, $y: Int) { left: pair(a: $x, b: $y) { sum }, right: pair(a: 5, b: 6) { sum } }',
        variables={"x": 10, "y": 20},
    )
    assert aliased.get("errors") is None, aliased
    assert aliased["data"] == {"left": {"sum": 30}, "right": {"sum": 11}}, aliased
