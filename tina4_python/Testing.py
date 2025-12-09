#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501

from pathlib import Path
import importlib
import sys

# ANSI colors — pure Tina4 style
class Colors:
    GREEN   = "\033[92m"
    RED     = "\033[91m"
    YELLOW  = "\033[93m"
    CYAN    = "\033[96m"
    GRAY    = "\033[90m"
    BOLD    = "\033[1m"
    RESET   = "\033[0m"

_TESTS = []

def tests(*cases):
    def decorator(func):
        _TESTS.append((func, cases))
        return func
    return decorator

class _Current:
    func = None

def _call(func, args):
    if func is None:
        raise RuntimeError("No function under test")
    code = func.__code__
    params = code.co_varnames[:code.co_argcount]

    if params and params[0] == "self":
        return func(object(), *args)
    elif params and params[0] == "cls":
        module = sys.modules[func.__module__]
        cls_name = func.__qualname__.split('.')[0]
        cls = getattr(module, cls_name)
        return func(cls, *args)
    else:
        return func(*args)

def assert_equal(args: tuple, expected, msg=""):
    def test():
        return _call(_Current.func, args)
    name = getattr(_Current.func, "__qualname__", getattr(_Current.func, "__name__", "unknown"))
    message = msg or f"{name}{args} == {expected}"
    return test, expected, message  # ← return actual expected value

def assert_raises(exc, args: tuple, msg=""):
    def test():
        try:
            _call(_Current.func, args)
            return False
        except exc:
            return True
        except:
            return False
    name = getattr(_Current.func, "__qualname__", getattr(_Current.func, "__name__", "unknown"))
    message = msg or f"{name}{args} raises {exc.__name__}"
    return test, True, message

def run_all_tests(quiet=False, failfast=False):
    if not quiet:
        print(f"{Colors.CYAN}Running Tina4 tests...{Colors.RESET}\n")

    src = Path("src")
    if src.exists():
        for py in src.rglob("*.py"):
            if py.name.startswith("_") or any(p in py.parts for p in {"public", "templates", "scss"}):
                continue
            mod_name = ".".join(py.with_suffix("").parts)
            try:
                importlib.import_module(mod_name)
            except Exception as e:
                if not quiet:
                    print(f"{Colors.GRAY}Skipped {mod_name}: {e}{Colors.RESET}")

    passed = failed = 0
    for func, cases in _TESTS:
        if not quiet:
            name = getattr(func, "__qualname__", func.__name__)
            print(f"{Colors.BOLD}{Colors.CYAN}{name}:{Colors.RESET}")

        _Current.func = func

        for case in cases:
            test_callable, expected_value, message = case

            try:
                actual_value = test_callable()  # ← actual return value from your function

                if actual_value == expected_value:
                    passed += 1
                    if not quiet:
                        print(f"  {Colors.GREEN}Success: {Colors.RESET}{message}")
                else:
                    failed += 1
                    if not quiet:
                        print(f"  {Colors.RED}Failed: {Colors.RESET}{message} {Colors.YELLOW}→ got {actual_value!r}{Colors.RESET}")
            except Exception as e:
                failed += 1
                if not quiet:
                    print(f"  {Colors.RED}Error: {Colors.RESET}{message} {Colors.YELLOW}→ {e}{Colors.RESET}")

        _Current.func = None

    if not quiet:
        if failed == 0:
            print(f"\n{Colors.GREEN}{Colors.BOLD}All {passed} tests passed!{Colors.RESET}")
        else:
            print(f"\n{Colors.RED}{Colors.BOLD}{failed} failed, {passed} passed{Colors.RESET}")
    sys.exit(failed)