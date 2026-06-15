"""ORM constructor accepts a dict, kwargs, or a JSON object string (one record),
and rejects a list/array with a clear TypeError (not a cryptic AttributeError)."""
import pytest

from tina4_python.orm import ORM
from tina4_python.orm.fields import IntegerField, StringField, BooleanField


class _CtorWidget(ORM):
    id = IntegerField(primary_key=True)
    name = StringField()
    active = BooleanField()


def test_from_dict():
    w = _CtorWidget({"id": 1, "name": "alpha", "active": True})
    assert w.id == 1 and w.name == "alpha" and w.active is True


def test_from_kwargs():
    w = _CtorWidget(id=2, name="beta")
    assert w.id == 2 and w.name == "beta"


def test_from_json_object_string():
    w = _CtorWidget('{"id": 3, "name": "gamma", "active": false}')
    assert w.id == 3 and w.name == "gamma" and w.active is False


def test_list_raises_clear_error():
    with pytest.raises(TypeError, match="one record"):
        _CtorWidget(["a", "b"])


def test_json_array_string_raises_clear_error():
    with pytest.raises(TypeError, match="one record"):
        _CtorWidget('[{"id": 4}]')
