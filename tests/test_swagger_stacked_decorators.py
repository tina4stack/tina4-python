"""#59 — stacked Swagger metadata decorators must ALL survive on the handler.

Reported bug: ``@summary`` / ``@description`` / ``@tags`` each return a fresh
wrapper setting only its own ``_swagger_*`` attribute; stacked, only the one
nearest ``@get`` survives on the registered handler and the rest are dropped.

Current Python behaviour (verified by these tests): each decorator annotates the
handler IN PLACE and returns the SAME object (no wrapper) — see the explicit
comment in ``tina4_python/swagger/__init__.py`` ``description()``. ``@get`` is
innermost and registers that exact object, so every stacked decorator lands its
metadata on the handler the generator reads. Python is therefore already
correct; these tests LOCK IT IN (and are the contract PHP/Ruby/Node must match).

Pure-logic: builds an OpenAPI spec from decorated in-process handlers — no DB,
no network, no doubles.
"""
from tina4_python.swagger import Swagger, summary, description, tags


def _route(method, path, handler):
    return {"method": method, "path": path, "handler": handler, "auth_required": False}


def test_all_three_stacked_decorators_survive():
    @summary("List widgets")
    @description("Returns every widget in the catalogue.")
    @tags(["widgets", "catalogue"])
    def handler(request, response):
        return response

    op = Swagger().generate([_route("get", "/widgets", handler)])["paths"]["/widgets"]["get"]
    assert op["summary"] == "List widgets"
    assert op["description"] == "Returns every widget in the catalogue."
    assert op["tags"] == ["widgets", "catalogue"]


def test_stack_order_does_not_matter():
    """Swapping the decorator order keeps ALL THREE — no decorator wins by
    being nearest the route, none is dropped."""

    @tags(["orders"])
    @summary("Create order")
    @description("Creates a new order.")
    def handler(request, response):
        return response

    op = Swagger().generate([_route("post", "/orders", handler)])["paths"]["/orders"]["post"]
    assert op["summary"] == "Create order"
    assert op["description"] == "Creates a new order."
    assert op["tags"] == ["orders"]


def test_decorators_share_one_handler_object():
    """The decorators must not wrap — a wrapper would be registered by nothing
    (the outer decorators never reach the router) and silently drop siblings.
    All three attributes must live on the one object the decorators returned."""

    @summary("A")
    @description("B")
    @tags(["C"])
    def handler(request, response):
        return response

    assert handler._swagger_summary == "A"
    assert handler._swagger_description == "B"
    assert handler._swagger_tags == ["C"]
