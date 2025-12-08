from tina4_python import get, template, wsdl
from ..app.Calculator import Calculator

@get("/test")
async def test(request):
    pass

@get("/test")
async def test(request):
    pass


@get("/hello/world/{id}")
@template("index.twig")
async def get_twig_something (id, request, response):
    return {"id": id}


@wsdl("/calculator")
async def wsdl_cis(request, response):

    return response.wsdl(Calculator(request))


# src/math.py
from tina4_python import tests, assert_equal, assert_raises

from tina4_python import tests, assert_equal, assert_raises

@tests(
    assert_equal((2, 2), 4),
    assert_equal((-5, 10), 5),
    assert_equal((0, 0), 0),

    assert_raises(TypeError, ("hello", 5), "cannot add str + int"),
    assert_raises(TypeError, (5, "world"), "cannot add int + str"),
    assert_raises(TypeError, (None, 1), "cannot add None + int"),
    assert_raises(ValueError, (1001, 1001), "Moo")   # ← 1001 > 1000 → triggers!
)
def add(a: int, b: int):
    if not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        raise TypeError("add() only works only with numbers")
    if abs(a) > 1000 or abs(b) > 1000:
        raise ValueError("numbers too big")
    return a + b

# src/routes/test.py  ←  works perfectly with classes, static methods, regular functions

from tina4_python import tests, assert_equal, assert_raises


class Moo:
    """This class is fully supported — no dummy self, no errors, pure Tina4 magic """

    @tests(
        assert_equal((2, 2), 4, "2 + 2 = 4"),
        assert_equal((-5, 10), 5, "-5 + 10 = 5"),
        assert_equal((0, 0), 0, "0 + 0 = 0"),
        assert_raises(TypeError, ("hello", 5), "cannot add str + int"),
        assert_raises(TypeError, (5, "world"), "cannot add int + str"),
        assert_raises(TypeError, (None, 1), "cannot add None + int"),
        assert_raises(ValueError, (9999, 1), "numbers too big"),
    )
    def add(self, a: int, b: int) -> int:
        """Instance method — receives self automatically"""
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            raise TypeError("add() only works with numbers")
        if abs(a) > 1000 or abs(b) > 1000:
            raise ValueError("numbers too big")
        return a + b

    @tests(
        assert_equal((10, 20), 30),
        assert_equal((0, 0), 0),
        assert_raises(TypeError, ("x", 1)),
    )
    @staticmethod
    def static_add(a: int, b: int) -> int:
        """Static method — works exactly the same"""
        return a + b

    @tests(
        assert_equal((3, 3), 9),
        assert_equal((2, 2), 4),
    )
    def multiply(cls, a: int, b: int) -> int:
        """Class method — also works perfectly"""
        return a * b


# Regular function outside any class — still works exactly the same
@tests(
  assert_equal((7, 7), 1),
    assert_equal((-1, 1), -1),
    assert_raises(ZeroDivisionError, (5, 0)),
)
def divide(a: int, b: int) -> float:
    if b == 0:
        raise ZeroDivisionError("division by zero")
    return a / b

@get("/session/set")
async def get_session_set(request, response):
    request.session.set("name", "Joe")
    request.session.set("info", {"info": ["one", "two", "three"]})
    return response("Session Set!")

@get("/session/get")
async def get_session_set(request, response):
    name = request.session.get("name")
    info = request.session.get("info")

    return response({"name": name, "info": info})