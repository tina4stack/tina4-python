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
    inheritance — class names do not need to start with ``Test``. Provides
    nothing on top of ``TestCase``: use the module-level ``assert_*``
    functions for assertions (their positional ``message`` argument is
    cleaner than ``self.assertEqual``'s keyword form).

    Override ``setUp``/``tearDown`` for per-test fixtures, or ``setUpClass``
    for once-per-class setup. Standard ``unittest.TestCase`` lifecycle
    applies.
    """

    # The pass-through is intentional. Anything we add here ships to every
    # test class forever; keeping it empty lets users compose freely.
    pass


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
    exception_class: type,
    callable_or_none: Callable | None = None,
    *args: Any,
    **kwargs: Any,
):
    """Assert ``exception_class`` is raised.

    Two forms — context manager and callable::

        # Context manager
        with assert_raises(ValueError):
            int("not a number")

        # Callable form
        assert_raises(ValueError, int, "not a number")

    Raises ``AssertionError`` if no exception is raised, or if a different
    exception type is raised.
    """
    if callable_or_none is None:
        return _RaisesContext(exception_class)

    try:
        callable_or_none(*args, **kwargs)
    except exception_class:
        return
    except Exception as e:
        raise AssertionError(
            f"Expected {exception_class.__name__}, got {type(e).__name__}: {e}"
        )
    raise AssertionError(
        f"Expected {exception_class.__name__} to be raised, but nothing was"
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
