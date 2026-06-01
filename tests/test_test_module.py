"""Tests for the xUnit-style tina4_python.test module.

Two layers:

1. The user's exact example from the docs MUST run as-written. No edits,
   no shim, no special config. This is the contract — if a developer
   types it the way the chapter shows, it works.
2. Every assertion fails when it should and passes when it should.
"""
from __future__ import annotations

import pytest

from tina4_python.test import (
    Test,
    assert_equal,
    assert_not_equal,
    assert_true,
    assert_false,
    assert_none,
    assert_not_none,
    assert_in,
    assert_not_in,
    assert_is_instance,
    assert_greater,
    assert_less,
    assert_almost_equal,
    assert_raises,
)


# ── Contract: the chapter's example runs as written ─────────────────────


class BasicTest(Test):
    """Verbatim from docs/python/18-testing.md — must keep working."""

    def test_addition(self):
        assert_equal(2 + 2, 4, "Basic addition should work")

    def test_string_contains(self):
        greeting = "Hello, World!"
        assert_true("World" in greeting, "Greeting should contain 'World'")

    def test_array_length(self):
        items = [1, 2, 3, 4, 5]
        assert_equal(len(items), 5, "List should have 5 items")


# ── Assertion correctness ───────────────────────────────────────────────


class TestAssertEqual:
    def test_passes_on_equal(self):
        assert_equal(1, 1)
        assert_equal("a", "a")
        assert_equal([1, 2], [1, 2])

    def test_fails_on_not_equal(self):
        with pytest.raises(AssertionError, match="Expected 2, got 1"):
            assert_equal(1, 2)

    def test_uses_custom_message(self):
        with pytest.raises(AssertionError, match="wrong total"):
            assert_equal(1, 2, "wrong total")


class TestAssertNotEqual:
    def test_passes_on_different(self):
        assert_not_equal(1, 2)

    def test_fails_on_equal(self):
        with pytest.raises(AssertionError):
            assert_not_equal(1, 1)


class TestAssertTrue:
    def test_passes_on_truthy(self):
        assert_true(True)
        assert_true(1)
        assert_true("non-empty")
        assert_true([0])  # non-empty list — truthy

    def test_fails_on_falsy(self):
        with pytest.raises(AssertionError):
            assert_true(False)
        with pytest.raises(AssertionError):
            assert_true(0)
        with pytest.raises(AssertionError):
            assert_true("")

    def test_uses_custom_message(self):
        with pytest.raises(AssertionError, match="cart not empty"):
            assert_true(False, "cart not empty")


class TestAssertFalse:
    def test_passes_on_falsy(self):
        assert_false(False)
        assert_false(0)
        assert_false("")

    def test_fails_on_truthy(self):
        with pytest.raises(AssertionError):
            assert_false(True)


class TestAssertNoneNotNone:
    def test_assert_none_passes(self):
        assert_none(None)

    def test_assert_none_fails(self):
        with pytest.raises(AssertionError):
            assert_none(0)

    def test_assert_not_none_passes(self):
        assert_not_none(0)
        assert_not_none("")
        assert_not_none(False)

    def test_assert_not_none_fails(self):
        with pytest.raises(AssertionError):
            assert_not_none(None)


class TestAssertInNotIn:
    def test_assert_in_string(self):
        assert_in("World", "Hello, World!")

    def test_assert_in_list(self):
        assert_in(3, [1, 2, 3])

    def test_assert_in_fails(self):
        with pytest.raises(AssertionError):
            assert_in("missing", "Hello, World!")

    def test_assert_not_in(self):
        assert_not_in("missing", "Hello, World!")
        with pytest.raises(AssertionError):
            assert_not_in("World", "Hello, World!")


class TestAssertIsInstance:
    def test_passes_for_correct_type(self):
        assert_is_instance("hi", str)
        assert_is_instance(1, int)

    def test_fails_for_wrong_type(self):
        with pytest.raises(AssertionError):
            assert_is_instance("hi", int)


class TestAssertGreaterLess:
    def test_greater(self):
        assert_greater(5, 3)
        with pytest.raises(AssertionError):
            assert_greater(3, 5)
        with pytest.raises(AssertionError):
            assert_greater(5, 5)

    def test_less(self):
        assert_less(3, 5)
        with pytest.raises(AssertionError):
            assert_less(5, 3)


class TestAssertAlmostEqual:
    def test_passes_within_places(self):
        assert_almost_equal(0.1 + 0.2, 0.3)

    def test_fails_outside_places(self):
        with pytest.raises(AssertionError):
            assert_almost_equal(0.1, 0.2)


class TestAssertRaises:
    def test_callable_form_passes(self):
        assert_raises(ValueError, int, "not a number")

    def test_callable_form_fails_when_no_exception(self):
        with pytest.raises(AssertionError, match="ValueError"):
            assert_raises(ValueError, int, "42")

    def test_callable_form_fails_on_wrong_exception(self):
        with pytest.raises(AssertionError, match="ValueError, got TypeError"):
            assert_raises(ValueError, int, None)  # raises TypeError

    def test_context_manager_form_passes(self):
        with assert_raises(ValueError):
            int("not a number")

    def test_context_manager_form_captures_exception(self):
        with assert_raises(ValueError) as ctx:
            int("not a number")
        assert isinstance(ctx.exception, ValueError)

    def test_context_manager_form_fails_when_no_exception(self):
        with pytest.raises(AssertionError, match="ValueError"):
            with assert_raises(ValueError):
                int("42")


# ── Class discovery ─────────────────────────────────────────────────────


class NotPrefixedWithTest(Test):
    """Class names DO NOT need to start with `Test`. Pytest discovers any
    class inheriting from unittest.TestCase by inheritance, not by name.

    This test is the contract: if pytest does not find this class and run
    its `test_*` method, the discovery promise is broken.
    """

    def test_discovery_works_for_arbitrary_class_names(self):
        assert_equal(1, 1)
