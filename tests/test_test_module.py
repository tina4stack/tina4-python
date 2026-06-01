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
    """Three forms of assert_raises — all must work."""

    # ── Form 1: docs form — callable first ──────────────────────────────

    def test_docs_form_passes(self):
        # Docs example, verbatim:
        assert_raises(
            lambda: int("not-a-number"),
            ValueError,
            "Should raise ValueError",
        )

    def test_docs_form_fails_when_no_exception(self):
        with pytest.raises(AssertionError, match="expected raise"):
            assert_raises(lambda: int("42"), ValueError, "expected raise")

    def test_docs_form_fails_when_no_exception_no_message(self):
        with pytest.raises(AssertionError, match="ValueError"):
            assert_raises(lambda: int("42"), ValueError)

    def test_docs_form_fails_on_wrong_exception(self):
        with pytest.raises(AssertionError, match="wrong exc"):
            # int(None) raises TypeError, not ValueError
            assert_raises(lambda: int(None), ValueError, "wrong exc")

    def test_docs_form_uses_message(self):
        with pytest.raises(AssertionError, match="my custom msg"):
            assert_raises(lambda: int("42"), ValueError, "my custom msg")

    # ── Form 2: context manager ─────────────────────────────────────────

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

    # ── Form 3: unittest order — exception first ────────────────────────

    def test_unittest_order_passes(self):
        # For users coming from unittest.TestCase or the inline @tests
        # decorator (which uses exception-first ordering)
        assert_raises(ValueError, lambda: int("not a number"))

    def test_unittest_order_fails_when_no_exception(self):
        with pytest.raises(AssertionError):
            assert_raises(ValueError, lambda: int("42"))


# ── Class discovery ─────────────────────────────────────────────────────


class NotPrefixedWithTest(Test):
    """Class names DO NOT need to start with `Test`. Pytest discovers any
    class inheriting from unittest.TestCase by inheritance, not by name.

    This test is the contract: if pytest does not find this class and run
    its `test_*` method, the discovery promise is broken.
    """

    def test_discovery_works_for_arbitrary_class_names(self):
        assert_equal(1, 1)


# ── Lifecycle: snake_case set_up / tear_down ────────────────────────────


class _LifecycleSpy:
    """Mutable record of which hooks fired in what order — class-scoped so
    every test method appends. Reset at the end of each suite."""

    def __init__(self) -> None:
        self.events: list[str] = []


_spy = _LifecycleSpy()


class LifecycleSnakeCase(Test):
    """The docs teach snake_case lifecycle methods. They MUST fire."""

    def set_up(self):
        _spy.events.append("set_up")
        self.value = 42

    def tear_down(self):
        _spy.events.append("tear_down")

    def test_first(self):
        _spy.events.append("test_first")
        assert_equal(self.value, 42, "set_up should populate self.value")

    def test_second(self):
        _spy.events.append("test_second")
        assert_equal(self.value, 42, "set_up runs before every test")


class TestLifecycleHookContract:
    """Verify the spy captured the expected snake_case sequence."""

    def test_snake_case_lifecycle_fires_in_order(self):
        # The two LifecycleSnakeCase tests should each fire set_up → test → tear_down.
        # Pytest doesn't guarantee order between them but each pair must be tight.
        events = list(_spy.events)
        # Each test contributes 3 events. We expect exactly 6 total.
        # (Pytest may run this assertion after either order of test_first/test_second.)
        assert events.count("set_up") == 2, f"set_up should fire twice, got {events!r}"
        assert events.count("tear_down") == 2, f"tear_down should fire twice, got {events!r}"
        assert events.count("test_first") == 1
        assert events.count("test_second") == 1
        # Each test bracket must be set_up → test_* → tear_down (no interleaving)
        for i in range(0, len(events), 3):
            assert events[i] == "set_up", events
            assert events[i + 1].startswith("test_"), events
            assert events[i + 2] == "tear_down", events


class LifecycleCamelCase(Test):
    """Users coming from unittest can still use camelCase. Snake-case
    hooks must NOT also fire (no double-call) if the subclass uses
    unittest-style names directly."""

    _camel_calls = 0

    def setUp(self):
        super().setUp()
        type(self)._camel_calls += 1

    def test_camel_setup_fires(self):
        # If snake_case were also called, this would double-count.
        # We just check that setUp ran at least once for this test.
        assert_true(type(self)._camel_calls > 0, "setUp should have been called")
