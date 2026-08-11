# Tina4 Python v3.0 — The Intelligent Native Application 4ramework.
# Copyright 2007 - present Tina4
# License: MIT https://opensource.org/licenses/MIT
"""
Inline testing framework — decorate functions with test assertions
that run alongside the code, and run them with ``tina4 test``.

Usage:
    from tina4_python.Testing import tests, expect_equal, expect_raises

    @tests(
        expect_equal((5, 3), 8),
        expect_raises(ValueError, (None,))
    )
    def add(a, b=None):
        if b is None:
            raise ValueError("b required")
        return a + b

Run all tests:
    from tina4_python.Testing import run_all
    run_all()

The builders are named ``expect_*`` — deliberately distinct from the xUnit
``assert_*`` assertions in ``tina4_python.test`` (which take positional
``(actual, expected, message)`` and assert immediately). ``expect_*`` are
DESCRIPTORS: ``expect_equal((args,), expected)`` records "call the decorated
function with ``args`` and check the result equals ``expected``" for the
runner to execute later. Keeping the two surfaces' names apart means importing
the wrong one is a loud ``ImportError``/``AttributeError``, never a silent
change of call semantics.
"""

import sys
import traceback

# ── Registry ────────────────────────────────────────────────────────

_registry: list[dict] = []


# ── Assertion builders ──────────────────────────────────────────────

def expect_equal(args: tuple, expected):
    """Expect that calling the decorated function with *args* returns *expected*."""
    return {"type": "equal", "args": args, "expected": expected}


def expect_raises(exception_class: type, args: tuple):
    """Expect that calling the decorated function with *args* raises *exception_class*."""
    return {"type": "raises", "exception": exception_class, "args": args}


def expect_true(args: tuple):
    """Expect that calling the decorated function with *args* returns a truthy value."""
    return {"type": "true", "args": args}


def expect_false(args: tuple):
    """Expect that calling the decorated function with *args* returns a falsy value."""
    return {"type": "false", "args": args}


# ── Decorator ───────────────────────────────────────────────────────

def tests(*assertions):
    """Decorator that attaches inline test assertions to a function.

    The decorated function is returned unchanged; the assertions are
    stored in a global registry and executed by ``run_all()``.
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

def run_all(quiet: bool = False, failfast: bool = False) -> dict:
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


def reset():
    """Reset the test registry (useful between test runs)."""
    _registry.clear()


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
