# Tina4 Python v3.0 — This is not a 4ramework.
# Copyright 2007 - present Tina4
# License: MIT https://opensource.org/licenses/MIT
"""
Inline testing framework — decorate functions with test assertions
that run alongside the code.

Usage:
    from tina4_python.Testing import tests, assert_equal, assert_raises

    @tests(
        assert_equal((5, 3), 8),
        assert_raises(ValueError, (None,))
    )
    def add(a, b=None):
        if b is None:
            raise ValueError("b required")
        return a + b

Run all tests:
    from tina4_python.Testing import run_all_tests
    run_all_tests()
"""

import sys
import traceback

# ── Registry ────────────────────────────────────────────────────────

_registry: list[dict] = []


# ── Assertion builders ──────────────────────────────────────────────

def assert_equal(args: tuple, expected):
    """Assert that calling the decorated function with *args* returns *expected*."""
    return {"type": "equal", "args": args, "expected": expected}


def assert_raises(exception_class: type, args: tuple):
    """Assert that calling the decorated function with *args* raises *exception_class*."""
    return {"type": "raises", "exception": exception_class, "args": args}


def assert_true(args: tuple):
    """Assert that calling the decorated function with *args* returns a truthy value."""
    return {"type": "true", "args": args}


def assert_false(args: tuple):
    """Assert that calling the decorated function with *args* returns a falsy value."""
    return {"type": "false", "args": args}


# ── Decorator ───────────────────────────────────────────────────────

def tests(*assertions):
    """Decorator that attaches inline test assertions to a function.

    The decorated function is returned unchanged; the assertions are
    stored in a global registry and executed by ``run_all_tests()``.
    """
    def decorator(fn):
        _registry.append({
            "fn": fn,
            "name": fn.__qualname__,
            "module": fn.__module__,
            "assertions": list(assertions),
        })
        return fn
    return decorator


# ── Runner ──────────────────────────────────────────────────────────

def run_all_tests(quiet: bool = False, failfast: bool = False) -> dict:
    """Discover and run every ``@tests``-decorated function.

    Returns a dict with keys ``passed``, ``failed``, ``errors``, ``details``.
    """
    results = {"passed": 0, "failed": 0, "errors": 0, "details": []}

    for entry in _registry:
        fn = entry["fn"]
        name = entry["name"]
        module = entry["module"]

        if not quiet:
            print(f"\n  {module}::{name}")

        for assertion in entry["assertions"]:
            label = _assertion_label(assertion, name)
            try:
                _run_assertion(fn, assertion)
                results["passed"] += 1
                results["details"].append({"name": label, "status": "passed"})
                if not quiet:
                    print(f"    \033[32m+\033[0m {label}")
            except AssertionError as exc:
                results["failed"] += 1
                results["details"].append({"name": label, "status": "failed", "message": str(exc)})
                if not quiet:
                    print(f"    \033[31mx\033[0m {label}: {exc}")
                if failfast:
                    _print_summary(results, quiet)
                    return results
            except Exception as exc:
                results["errors"] += 1
                msg = f"{type(exc).__name__}: {exc}"
                results["details"].append({"name": label, "status": "error", "message": msg})
                if not quiet:
                    print(f"    \033[33m!\033[0m {label}: {msg}")
                if failfast:
                    _print_summary(results, quiet)
                    return results

    _print_summary(results, quiet)
    return results


# ── Internals ───────────────────────────────────────────────────────

def _run_assertion(fn, assertion: dict):
    atype = assertion["type"]
    args = assertion["args"]

    if atype == "equal":
        result = fn(*args)
        expected = assertion["expected"]
        if result != expected:
            raise AssertionError(f"expected {expected!r}, got {result!r}")

    elif atype == "raises":
        exc_class = assertion["exception"]
        try:
            fn(*args)
        except exc_class:
            return  # success
        except Exception as other:
            raise AssertionError(
                f"expected {exc_class.__name__}, got {type(other).__name__}: {other}"
            )
        else:
            raise AssertionError(f"expected {exc_class.__name__} to be raised")

    elif atype == "true":
        result = fn(*args)
        if not result:
            raise AssertionError(f"expected truthy, got {result!r}")

    elif atype == "false":
        result = fn(*args)
        if result:
            raise AssertionError(f"expected falsy, got {result!r}")

    else:
        raise ValueError(f"unknown assertion type: {atype!r}")


def _assertion_label(assertion: dict, fn_name: str) -> str:
    atype = assertion["type"]
    args = assertion["args"]
    if atype == "equal":
        return f"{fn_name}{args} == {assertion['expected']!r}"
    elif atype == "raises":
        return f"{fn_name}{args} raises {assertion['exception'].__name__}"
    elif atype == "true":
        return f"{fn_name}{args} is truthy"
    elif atype == "false":
        return f"{fn_name}{args} is falsy"
    return f"{fn_name} [{atype}]"


def _print_summary(results: dict, quiet: bool):
    if quiet:
        return
    total = results["passed"] + results["failed"] + results["errors"]
    print(
        f"\n  {total} tests: "
        f"\033[32m{results['passed']} passed\033[0m, "
        f"\033[31m{results['failed']} failed\033[0m, "
        f"\033[33m{results['errors']} errors\033[0m\n"
    )
