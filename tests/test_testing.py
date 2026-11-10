# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# Tests for the inline testing framework itself.
#
# The @tests registry is process-global. These meta-tests therefore SNAPSHOT it,
# clear it for the duration of the test, register their OWN functions, assert on
# that isolated subset, then restore the snapshot (INLINE-GLOBAL-REGISTRY). No
# test asserts on the global total, so a different module registering @tests can
# never break this file's counts.
import os
import sys
from contextlib import contextmanager

# Ensure the package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tina4_python.Testing import (
    tests, expect_equal, expect_raises, expect_true, expect_false,
    run_all, reset, _registry,
)


@contextmanager
def isolated_registry():
    """Snapshot the process-global @tests registry, clear it for the block, and
    restore it afterwards, so a meta-test asserts only on what it registered."""
    saved = list(_registry)
    reset()
    try:
        yield
    finally:
        reset()
        _registry.extend(saved)


# ── Meta-test: run a known inline set and verify the results ────────

def test_inline_testing_framework():
    """Register a known set inside an isolated registry and assert the summary."""
    with isolated_registry():
        @tests(
            expect_equal((5, 3), 8),
            expect_equal((0, 0), 0),
            expect_equal((-1, 1), 0),
        )
        def add(a, b):
            return a + b

        @tests(
            expect_equal(("hello",), "HELLO"),
            expect_equal(("World",), "WORLD"),
        )
        def upper(s):
            return s.upper()

        @tests(
            expect_raises(ValueError, (None,)),
            expect_equal((5, 3), 8),
        )
        def add_safe(a, b=None):
            if b is None:
                raise ValueError("b is required")
            return a + b

        @tests(
            expect_true((10,)),
            expect_true((1,)),
            expect_false((0,)),
            expect_false(("",)),
        )
        def is_truthy(value):
            return bool(value)

        results = run_all(quiet=True)

    assert results["passed"] == 11, f"expected 11 passed, got {results['passed']}"
    assert results["failed"] == 0, f"expected 0 failed, got {results['failed']}"
    assert results["errors"] == 0, f"expected 0 errors, got {results['errors']}"
    assert len(results["details"]) == 11, f"expected 11 details, got {len(results['details'])}"

    # Every detail should be "passed"
    for d in results["details"]:
        assert d["status"] == "passed", f"expected passed, got {d}"


def test_failed_assertion_is_reported():
    """A deliberate failure should be counted as failed, not passed."""
    with isolated_registry():
        @tests(expect_equal((1, 1), 999))
        def bad_add(a, b):
            return a + b

        results = run_all(quiet=True)

    assert results["failed"] == 1, f"expected 1 failed, got {results['failed']}"
    assert results["passed"] == 0, f"expected 0 passed, got {results['passed']}"


def test_error_is_reported():
    """A runtime error (not an assertion failure) should be counted as error."""
    with isolated_registry():
        @tests(expect_equal((1,), 1))
        def will_crash(a):
            raise RuntimeError("boom")

        results = run_all(quiet=True)

    assert results["errors"] == 1, f"expected 1 error, got {results['errors']}"


if __name__ == "__main__":
    test_inline_testing_framework()
    test_failed_assertion_is_reported()
    test_error_is_reported()
    print("\nAll meta-tests passed.")


# ── Async test functions are judged on what they return, not on the coroutine ──

def _run_isolated(register):
    with isolated_registry():
        register()
        return run_all(quiet=True)


def test_async_expect_true_fails_when_the_coroutine_returns_false():
    def register():
        @tests(expect_true([]))
        async def saved():
            return False
    results = _run_isolated(register)
    assert results["failed"] == 1 and results["passed"] == 0


def test_async_expect_equal_compares_the_returned_value():
    def register():
        @tests(expect_equal([2], 3), expect_equal([2], 5))
        async def add_one(n):
            return n + 1
    results = _run_isolated(register)
    assert results["passed"] == 1 and results["failed"] == 1


def test_async_expect_false_and_raises():
    def register():
        @tests(expect_false([0]), expect_raises(ValueError, [-1]))
        async def check(n):
            if n < 0:
                raise ValueError("negative")
            return n
    results = _run_isolated(register)
    assert results["passed"] == 2


def test_async_unexpected_exception_is_an_error_not_a_pass():
    def register():
        @tests(expect_true([]))
        async def broken():
            raise TypeError("db gone")
    results = _run_isolated(register)
    assert results["errors"] == 1 and results["passed"] == 0


def test_async_tests_run_when_run_all_is_called_inside_an_event_loop():
    """run_all() from inside a running loop (an async caller) still awaits them."""
    import asyncio

    def register():
        @tests(expect_true([]))
        async def saved():
            await asyncio.sleep(0)
            return False

    async def caller():
        return _run_isolated(register)

    results = asyncio.run(caller())
    assert results["failed"] == 1 and results["passed"] == 0
