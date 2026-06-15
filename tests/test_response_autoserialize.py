"""response() auto-serializes ORM models, lists of models, and query results.

A route can hand a domain object straight to ``response(...)`` /
``response.json(...)`` without calling ``.to_dict()``/``.to_json()`` by hand.
Plain dict / str values must still behave exactly as before.
"""
import json

from tina4_python.core.response import Response


class _Model:
    """Duck-typed ORM model — exposes a callable to_dict()."""

    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return self._data


class _Result:
    """Duck-typed DatabaseResult — records list + to_array()."""

    def __init__(self, rows):
        self.records = rows

    def to_array(self):
        return self.records


def _body(resp):
    return resp.content.decode()


def test_response_serializes_model():
    r = Response()(_Model({"id": 1, "name": "alpha", "active": True}))
    assert r.content_type == "application/json"
    assert json.loads(_body(r)) == {"id": 1, "name": "alpha", "active": True}


def test_response_serializes_list_of_models():
    r = Response()([_Model({"id": 1}), _Model({"id": 2})])
    assert r.content_type == "application/json"
    assert json.loads(_body(r)) == [{"id": 1}, {"id": 2}]


def test_response_serializes_database_result():
    r = Response()(_Result([{"id": 1}, {"id": 2}]))
    assert r.content_type == "application/json"
    assert json.loads(_body(r)) == [{"id": 1}, {"id": 2}]


def test_json_method_serializes_model():
    r = Response().json(_Model({"id": 9, "name": "z"}))
    assert r.content_type == "application/json"
    assert json.loads(_body(r)) == {"id": 9, "name": "z"}


def test_plain_dict_unchanged():
    r = Response()({"ok": True})
    assert r.content_type == "application/json"
    assert json.loads(_body(r)) == {"ok": True}


def test_string_unchanged():
    r = Response()("<h1>hi</h1>")
    assert r.content_type.startswith("text/html")
    assert _body(r) == "<h1>hi</h1>"


def test_nested_model_in_dict():
    # A model nested inside a returned dict is left to json.dumps(default=str);
    # the top-level dict path is unchanged. The explicit win is the bare model.
    r = Response()({"count": 1})
    assert json.loads(_body(r)) == {"count": 1}
