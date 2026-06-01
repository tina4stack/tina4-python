# Tina4 xUnit-Style Testing Surface
"""
Class-based testing with positional assertions. This module exists so the
following pattern — used throughout the testing documentation — actually
runs::

    from tina4_python.test import Test, assert_equal, assert_true

    class BasicTest(Test):

        def test_addition(self):
            assert_equal(2 + 2, 4, "Basic addition should work")

        def test_string_contains(self):
            greeting = "Hello, World!"
            assert_true("World" in greeting, "Greeting should contain 'World'")

The `Test` base class inherits from ``unittest.TestCase``. Pytest discovers
any class that inherits from ``TestCase`` regardless of the class-name
convention, so class names do NOT need to start with ``Test``. ``BasicTest``,
``UserCRUDTest``, anything works.

The assertion functions take **positional** arguments: ``(actual, expected,
message)``. This is deliberately different from the inline ``@tests``
decorator in ``tina4_python.Testing``, which uses a tuple form
``assert_equal((args,), expected)``. The two surfaces serve different
purposes:

- ``tina4_python.test`` — class-based suites, run with ``tina4 test`` or pytest
- ``tina4_python.Testing`` — inline assertions next to the function under test

Run any test with ``tina4 test`` or ``.venv/bin/python -m pytest tests/``.
"""
from __future__ import annotations

import unittest
from typing import Any, Callable


class Test(unittest.TestCase):
    """Base class for Tina4 xUnit-style test suites.

    Inherits from ``unittest.TestCase`` so pytest discovers any subclass by
    inheritance — class names do not need to start with ``Test``.

    **Lifecycle hooks** — Tina4 prefers snake_case names that match Python
    style. Override either form; both are called for you::

        class UserTest(Test):
            def set_up(self):     # snake_case — Tina4 idiom
                self.user = User.create({...})

            def tear_down(self):  # snake_case — Tina4 idiom
                self.user.delete()

    The classic ``unittest`` ``setUp`` / ``tearDown`` still works for users
    coming from ``unittest.TestCase``; you may use either, but do not mix
    the two on the same class.
    """

    # ── Lifecycle adapters ──────────────────────────────────────────────
    #
    # unittest.TestCase only calls setUp / tearDown (camelCase). Tina4
    # documents set_up / tear_down (snake_case). Bridge here so the
    # snake_case methods get called when subclasses override them.

    def setUp(self) -> None:  # noqa: N802 — unittest convention
        super().setUp()
        # Only call set_up if a subclass defined it (avoids double-calling
        # if the user uses unittest-style setUp instead).
        if type(self).set_up is not Test.set_up:
            self.set_up()

    def tearDown(self) -> None:  # noqa: N802 — unittest convention
        if type(self).tear_down is not Test.tear_down:
            self.tear_down()
        super().tearDown()

    def set_up(self) -> None:
        """Snake-case lifecycle hook — runs before each test method.

        Default no-op. Override to set up per-test fixtures.
        """

    def tear_down(self) -> None:
        """Snake-case lifecycle hook — runs after each test method,
        regardless of pass or fail.

        Default no-op. Override to clean up per-test state.
        """


# ── Assertions ──────────────────────────────────────────────────────────
#
# Each assertion follows the same shape: positional value(s) + optional
# message. They raise ``AssertionError`` on failure, which pytest and the
# ``tina4 test`` CLI both render with the trailing message.


def assert_equal(actual: Any, expected: Any, message: str = "") -> None:
    """Assert two values are equal."""
    if actual != expected:
        raise AssertionError(
            message or f"Expected {expected!r}, got {actual!r}"
        )


def assert_not_equal(actual: Any, expected: Any, message: str = "") -> None:
    """Assert two values are not equal."""
    if actual == expected:
        raise AssertionError(
            message or f"Expected {actual!r} != {expected!r}, but they are equal"
        )


def assert_true(condition: Any, message: str = "") -> None:
    """Assert the value is truthy."""
    if not condition:
        raise AssertionError(message or f"Expected truthy, got {condition!r}")


def assert_false(condition: Any, message: str = "") -> None:
    """Assert the value is falsy."""
    if condition:
        raise AssertionError(message or f"Expected falsy, got {condition!r}")


def assert_none(value: Any, message: str = "") -> None:
    """Assert the value is ``None``."""
    if value is not None:
        raise AssertionError(message or f"Expected None, got {value!r}")


def assert_not_none(value: Any, message: str = "") -> None:
    """Assert the value is not ``None``."""
    if value is None:
        raise AssertionError(message or "Expected not None, got None")


def assert_in(item: Any, container: Any, message: str = "") -> None:
    """Assert ``item`` is contained in ``container``."""
    if item not in container:
        raise AssertionError(
            message or f"Expected {item!r} in {container!r}"
        )


def assert_not_in(item: Any, container: Any, message: str = "") -> None:
    """Assert ``item`` is not in ``container``."""
    if item in container:
        raise AssertionError(
            message or f"Expected {item!r} not in {container!r}"
        )


def assert_is_instance(value: Any, expected_type: type, message: str = "") -> None:
    """Assert ``value`` is an instance of ``expected_type``."""
    if not isinstance(value, expected_type):
        raise AssertionError(
            message
            or f"Expected instance of {expected_type.__name__}, got {type(value).__name__}"
        )


def assert_greater(a: Any, b: Any, message: str = "") -> None:
    """Assert ``a > b``."""
    if not (a > b):
        raise AssertionError(message or f"Expected {a!r} > {b!r}")


def assert_less(a: Any, b: Any, message: str = "") -> None:
    """Assert ``a < b``."""
    if not (a < b):
        raise AssertionError(message or f"Expected {a!r} < {b!r}")


def assert_almost_equal(
    actual: float, expected: float, places: int = 7, message: str = ""
) -> None:
    """Assert two floats are equal to the given number of decimal places.

    Useful for floating-point comparisons where exact equality is unreliable.
    """
    if round(abs(actual - expected), places) != 0:
        raise AssertionError(
            message
            or f"Expected {expected!r} ≈ {actual!r} (within {places} places)"
        )


def assert_raises(
    callable_or_exception: Callable | type,
    exception_class: type | None = None,
    message: str = "",
):
    """Assert that a callable raises a specific exception.

    Three forms, all supported::

        # 1. Docs form — callable first, exception second, optional message
        assert_raises(lambda: int("not a number"), ValueError, "must raise")

        # 2. Context manager — useful when the body is more than one line
        with assert_raises(ValueError):
            value = parse(input)
            process(value)

        # 3. unittest.TestCase compatibility — exception first form
        assert_raises(ValueError, lambda: int("not a number"))

    Raises ``AssertionError`` if no exception is raised, or if a different
    exception type is raised.
    """
    # Form 2: context manager — caller passed just the exception class
    if exception_class is None:
        if not isinstance(callable_or_exception, type) or not issubclass(
            callable_or_exception, BaseException
        ):
            raise TypeError(
                "assert_raises with one argument requires an exception class"
            )
        return _RaisesContext(callable_or_exception)

    # Determine which argument is the callable and which is the exception
    # by type — supports docs form AND unittest order without ambiguity.
    if isinstance(callable_or_exception, type) and issubclass(
        callable_or_exception, BaseException
    ):
        # Form 3: assert_raises(ExceptionType, callable)
        exc_type = callable_or_exception
        fn = exception_class
    else:
        # Form 1: assert_raises(callable, ExceptionType, message)
        fn = callable_or_exception
        exc_type = exception_class

    if not callable(fn):
        raise TypeError("assert_raises requires a callable")

    try:
        fn()
    except exc_type:
        return
    except Exception as e:
        raise AssertionError(
            message
            or f"Expected {exc_type.__name__}, got {type(e).__name__}: {e}"
        )
    raise AssertionError(
        message
        or f"Expected {exc_type.__name__} to be raised, but nothing was"
    )


class _RaisesContext:
    """Context-manager form of ``assert_raises``."""

    def __init__(self, exception_class: type) -> None:
        self.exception_class = exception_class
        self.exception: BaseException | None = None

    def __enter__(self) -> "_RaisesContext":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is None:
            raise AssertionError(
                f"Expected {self.exception_class.__name__} to be raised, but nothing was"
            )
        if not issubclass(exc_type, self.exception_class):
            return False  # let it propagate — wrong exception type
        self.exception = exc_val
        return True  # swallow the expected exception


__all__ = [
    # Base class
    "Test",
    # Assertions — positional (actual, expected, message)
    "assert_equal",
    "assert_not_equal",
    "assert_true",
    "assert_false",
    "assert_none",
    "assert_not_none",
    "assert_in",
    "assert_not_in",
    "assert_is_instance",
    "assert_greater",
    "assert_less",
    "assert_almost_equal",
    "assert_raises",
]
