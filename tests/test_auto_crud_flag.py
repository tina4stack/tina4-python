"""Test that auto_crud = True on an ORM model auto-registers CRUD routes."""
import pytest
from tina4_python.orm.model import ORM, orm_bind
from tina4_python.orm.fields import IntegerField, StringField
from tina4_python.crud import AutoCrud
from tina4_python.database import Database


def test_auto_crud_flag_registers_model():
    """Setting auto_crud = True should auto-register the model with AutoCrud."""
    # Clear any prior registrations
    AutoCrud.clear()

    # Create a model with auto_crud = True
    class Widget(ORM):
        table_name = "widgets"
        auto_crud = True
        id = IntegerField(primary_key=True, auto_increment=True)
        name = StringField()

    # The model should be registered
    assert "widgets" in AutoCrud.models()
    assert AutoCrud.models()["widgets"] is Widget

    AutoCrud.clear()


def test_auto_crud_false_does_not_register():
    """auto_crud = False (default) should NOT register the model."""
    AutoCrud.clear()

    class Gadget(ORM):
        table_name = "gadgets"
        id = IntegerField(primary_key=True, auto_increment=True)

    assert "gadgets" not in AutoCrud.models()

    AutoCrud.clear()
