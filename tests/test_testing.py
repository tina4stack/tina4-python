# Tests for the inline testing framework itself.
import sys
import os

# Ensure the package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tina4_python.Testing import (
    tests, assert_equal, assert_raises, assert_true, assert_false,
    run_all_tests, _registry,
)


# ── Functions under test ────────────────────────────────────────────

@tests(
    assert_equal((5, 3), 8),
    assert_equal((0, 0), 0),
    assert_equal((-1, 1), 0),
)
def add(a, b):
    return a + b


@tests(
    assert_equal(("hello",), "HELLO"),
    assert_equal(("World",), "WORLD"),
)
def upper(s):
    return s.upper()


@tests(
    assert_raises(ValueError, (None,)),
    assert_equal((5, 3), 8),
)
def add_safe(a, b=None):
    if b is None:
        raise ValueError("b is required")
    return a + b


@tests(
    assert_true((10,)),
    assert_true((1,)),
    assert_false((0,)),
    assert_false(("",)),
)
def is_truthy(value):
    return bool(value)


# ── Meta-test: run the inline tests and verify the results ──────────

def test_inline_testing_framework():
    """Run all @tests-decorated functions and assert the summary."""
    results = run_all_tests(quiet=True)

    assert results["passed"] == 11, f"expected 11 passed, got {results['passed']}"
    assert results["failed"] == 0, f"expected 0 failed, got {results['failed']}"
    assert results["errors"] == 0, f"expected 0 errors, got {results['errors']}"
    assert len(results["details"]) == 11, f"expected 11 details, got {len(results['details'])}"

    # Every detail should be "passed"
    for d in results["details"]:
        assert d["status"] == "passed", f"expected passed, got {d}"


def test_failed_assertion_is_reported():
    """A deliberate failure should be counted as failed, not passed."""
    from tina4_python.Testing import _registry

    # Save and clear registry
    saved = list(_registry)
    _registry.clear()

    @tests(assert_equal((1, 1), 999))
    def bad_add(a, b):
        return a + b

    results = run_all_tests(quiet=True)
    assert results["failed"] == 1, f"expected 1 failed, got {results['failed']}"
    assert results["passed"] == 0

    # Restore registry
    _registry.clear()
    _registry.extend(saved)


def test_error_is_reported():
    """A runtime error (not an assertion failure) should be counted as error."""
    from tina4_python.Testing import _registry

    saved = list(_registry)
    _registry.clear()

    @tests(assert_equal((1,), 1))
    def will_crash(a):
        raise RuntimeError("boom")

    results = run_all_tests(quiet=True)
    assert results["errors"] == 1, f"expected 1 error, got {results['errors']}"

    _registry.clear()
    _registry.extend(saved)


if __name__ == "__main__":
    test_inline_testing_framework()
    test_failed_assertion_is_reported()
    test_error_is_reported()
    print("\nAll meta-tests passed.")
