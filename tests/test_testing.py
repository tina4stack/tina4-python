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

import pytest
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


def _run_capped(register, cap=10.0, **kwargs):
    """Run an isolated set in a daemon thread and fail, by name, if run_all()
    has not returned within ``cap`` seconds: a hang in the runner is a test
    failure here, never a wedged suite."""
    import threading

    box = {}

    def target():
        try:
            with isolated_registry():
                register()
                box["results"] = run_all(quiet=True, **kwargs)
        except BaseException as exc:  # surfaced below
            box["error"] = exc

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(cap)
    assert not worker.is_alive(), f"run_all() did not return within {cap}s (hung)"
    if "error" in box:
        raise box["error"]
    return box["results"]


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


def test_async_test_inside_a_running_loop_is_an_error_not_a_pass_or_a_hang():
    """run_all() from inside a running loop cannot await without blocking it.

    The async test is reported as an error naming the fix, never passed, and
    the coroutine is closed rather than left un-awaited.
    """
    import asyncio
    import warnings

    def register():
        @tests(expect_true([]))
        async def saved():
            return True

    async def caller():
        return _run_isolated(register)

    import gc
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        results = asyncio.run(caller())
        gc.collect()
    assert results["errors"] == 1 and results["passed"] == 0
    assert not [w for w in caught if "never awaited" in str(w.message)], "coroutine left un-awaited"
    assert "synchronous" in results["details"][0]["message"]


def test_async_tests_in_one_run_share_one_event_loop():
    """Every async test in a run gets the same loop, so loop-bound objects
    (a queue someone waits on, a pooled connection) survive across assertions."""
    import asyncio
    loops = []
    queue = asyncio.Queue()

    def register():
        @tests(expect_equal([1], 1), expect_equal([2], 2))
        async def round_trip(n):
            loops.append(asyncio.get_running_loop())
            # get() before put() makes get wait, which binds the queue to this loop.
            waiter = asyncio.ensure_future(queue.get())
            await asyncio.sleep(0)
            await queue.put(n)
            return await waiter

    results = _run_isolated(register)
    assert results["passed"] == 2, results["details"]
    assert len(loops) == 2 and loops[0] is loops[1]


def test_async_test_sees_the_callers_context_variables():
    import contextvars
    marker = contextvars.ContextVar("marker", default="unset")

    def register():
        @tests(expect_equal([], "set"))
        async def read_marker():
            return marker.get()

    token = marker.set("set")
    try:
        results = _run_isolated(register)
    finally:
        marker.reset(token)
    assert results["passed"] == 1, results["details"]


def test_sync_tests_are_unchanged_by_the_async_support():
    def register():
        @tests(expect_equal([2, 3], 5), expect_raises(ValueError, [None, 1]))
        def add(a, b):
            if a is None:
                raise ValueError("a required")
            return a + b
    results = _run_isolated(register)
    assert results["passed"] == 2 and results["failed"] == 0 and results["errors"] == 0


def test_expect_raises_cannot_pass_on_the_runners_own_refusal():
    """Inside a running loop the runner refuses an async test. That refusal is
    not the test's exception, so expect_raises(RuntimeError / Exception) must
    report an error, not a pass for a body that never ran."""
    import asyncio

    def register():
        @tests(expect_raises(RuntimeError, []), expect_raises(Exception, []))
        async def never_runs():
            raise RuntimeError("the body")

    async def caller():
        return _run_isolated(register)

    results = asyncio.run(caller())
    assert results["errors"] == 2 and results["passed"] == 0


def test_an_async_test_that_never_finishes_is_an_error_after_the_timeout():
    import asyncio
    from tina4_python.Testing import run_all as _run

    with isolated_registry():
        @tests(expect_true([]))
        async def hangs():
            await asyncio.Event().wait()
        results = _run(quiet=True, timeout=0.2)
    assert results["errors"] == 1 and results["passed"] == 0
    assert "did not finish" in results["details"][0]["message"]


def test_a_timeout_error_the_test_raises_itself_is_its_own_exception():
    import asyncio

    def register():
        @tests(expect_raises(asyncio.TimeoutError, []))
        async def times_out_inside():
            await asyncio.wait_for(asyncio.Event().wait(), 0.01)

    assert _run_isolated(register)["passed"] == 1


def test_a_task_left_running_is_cancelled_when_the_run_ends(recwarn):
    import asyncio, gc

    started = []

    def register():
        @tests(expect_true([]))
        async def leaves_a_task():
            started.append(asyncio.get_running_loop().create_task(asyncio.Event().wait()))
            return True

    assert _run_isolated(register)["passed"] == 1
    gc.collect()
    assert started and started[0].cancelled()


def test_a_test_that_swallows_cancellation_still_times_out():
    """Cancelling a timed-out test is bounded too: a body that catches
    CancelledError and carries on must not hang the run."""
    import asyncio
    from tina4_python.Testing import run_all as _run

    def register():
        @tests(expect_true([]))
        async def stubborn():
            while True:
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    pass

    results = _run_capped(register, timeout=0.2)
    assert results["errors"] == 1 and results["passed"] == 0


def test_an_async_test_that_cancels_itself_is_an_error_and_the_run_goes_on():
    import asyncio

    def register():
        @tests(expect_true([]))
        async def cancels_itself():
            raise asyncio.CancelledError()

        @tests(expect_true([]))
        async def after():
            return True

    results = _run_isolated(register)
    assert results["errors"] == 1 and results["passed"] == 1


def test_the_default_timeout_applies():
    import inspect as _inspect
    from tina4_python.Testing import run_all as _run
    assert _inspect.signature(_run).parameters["timeout"].default == 30.0


def test_an_async_generator_left_open_is_finalised_and_cannot_hang_the_run():
    """Async generators still open when the run ends are closed (their
    ``finally`` runs), and one whose cleanup never finishes is abandoned
    after the grace period instead of hanging run_all()."""
    import asyncio, time

    finalised, held = [], []

    async def tidy():
        try:
            yield 1
        finally:
            finalised.append(True)

    async def stuck():
        try:
            yield 1
        finally:
            await asyncio.Event().wait()

    def register():
        @tests(expect_true([]))
        async def opens_generators():
            for gen in (tidy(), stuck()):
                await gen.__anext__()
                held.append(gen)
            return True

    started = time.monotonic()
    results = _run_capped(register)
    assert results["passed"] == 1
    assert finalised == [True]
    assert time.monotonic() - started < 10


def test_an_async_generator_whose_cleanup_swallows_cancellation_cannot_hang_the_run():
    """A generator whose ``finally`` catches CancelledError in a loop never lets
    a cancelled shutdown finish. The run must still end, after the grace period."""
    import asyncio, time

    held = []

    async def swallows():
        try:
            yield 1
        finally:
            while True:
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    pass

    def register():
        @tests(expect_true([]))
        async def opens_generator():
            gen = swallows()
            await gen.__anext__()
            held.append(gen)
            return True

    started = time.monotonic()
    results = _run_capped(register)
    assert results["passed"] == 1
    assert time.monotonic() - started < 10


def test_the_runs_event_loop_is_closed_when_the_run_ends():
    import asyncio

    loops = []

    def register():
        @tests(expect_true([]))
        async def grab_loop():
            loops.append(asyncio.get_running_loop())
            return True

    results = _run_capped(register)
    assert results["passed"] == 1
    assert loops and loops[0].is_closed()


def test_the_run_leaves_no_current_event_loop_behind():
    """run_all() must not install its loop as the caller's current loop. Checked
    in a fresh thread, where no loop is set to begin with."""
    import asyncio, threading

    seen = {}

    def register():
        @tests(expect_true([]))
        async def uses_the_loop():
            await asyncio.sleep(0)
            return True

    def target():
        with isolated_registry():
            register()
            seen["results"] = run_all(quiet=True)
        try:
            asyncio.get_event_loop()
            seen["current"] = True
        except RuntimeError:
            seen["current"] = False

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(10)
    assert not worker.is_alive(), "run_all() did not return within 10s (hung)"
    assert seen["results"]["passed"] == 1
    assert seen["current"] is False, "run_all() left its event loop set as current"


def test_any_awaitable_a_test_returns_is_awaited_not_only_coroutines():
    """A sync function returning an object with ``__await__`` is judged on what
    awaiting it produces, the same as an ``async def``."""
    import asyncio

    class Answer:
        def __await__(self):
            yield from asyncio.sleep(0).__await__()
            return 7

    def register():
        @tests(expect_equal([], 7))
        def returns_awaitable():
            return Answer()

    results = _run_capped(register)
    assert results["passed"] == 1, results["details"]


def test_a_system_exit_from_an_async_test_does_not_leak_into_the_next_test():
    def register():
        @tests(expect_raises(SystemExit, []))
        async def exits():
            raise SystemExit(3)

        @tests(expect_raises(SystemExit, []), expect_equal([], 1))
        async def returns_one():
            return 1
    results = _run_capped(register)
    # exits: pass; returns_one: the raises check fails, the equal check passes
    assert results["passed"] == 2 and results["failed"] == 1, results


def test_a_timed_out_tests_cleanup_finishes_before_the_next_test_starts():
    import asyncio
    order = []

    def register():
        @tests(expect_true([]))
        async def a_hangs():
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.05)
                order.append("a cleaned up")

        @tests(expect_true([]))
        async def b_next():
            order.append("b started")
            return True
    results = _run_capped(register, timeout=0.2)
    assert results["errors"] == 1 and results["passed"] == 1
    assert order == ["a cleaned up", "b started"], order


def test_a_test_that_cancels_every_other_task_does_not_abort_the_run():
    import asyncio

    def register():
        @tests(expect_true([]))
        async def tears_down():
            for t in asyncio.all_tasks():
                if t is not asyncio.current_task():
                    t.cancel()
            return True

        @tests(expect_equal([], 2))
        def after():
            return 1
    results = _run_capped(register)
    assert results["passed"] == 1 and results["failed"] == 1, results


def test_a_hang_under_expect_raises_timeout_error_is_an_error_not_a_pass():
    import asyncio

    def register():
        @tests(expect_raises(TimeoutError, []))
        async def hangs():
            await asyncio.Event().wait()
    results = _run_capped(register, timeout=0.2)
    assert results["errors"] == 1 and results["passed"] == 0, results


@pytest.mark.parametrize("unlimited", [None, float("inf")])
def test_timeout_none_or_infinity_means_no_limit(unlimited):
    import asyncio

    def register():
        @tests(expect_true([]))
        async def slow():
            await asyncio.sleep(0.05)
            return True
    results = _run_capped(register, timeout=unlimited)
    assert results["passed"] == 1, results


def test_every_task_left_running_finishes_its_cleanup_before_the_run_ends():
    import asyncio
    cleaned = []

    async def background(name, delay):
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(delay)
            cleaned.append(name)

    def register():
        @tests(expect_true([]))
        async def starts_two():
            asyncio.ensure_future(background("fast", 0))
            asyncio.ensure_future(background("slow", 0.1))
            await asyncio.sleep(0)
            return True
    results = _run_capped(register)
    assert results["passed"] == 1 and sorted(cleaned) == ["fast", "slow"], (results, cleaned)


@pytest.mark.parametrize("bad", [True, float("nan"), "5", -1, float("-inf")])
def test_a_timeout_that_is_not_zero_or_more_seconds_is_refused(bad):
    with pytest.raises((TypeError, ValueError)):
        run_all(quiet=True, timeout=bad)


@pytest.mark.parametrize("unlimited", [None, float("inf"), 10 ** 400])
def test_an_unbounded_timeout_is_no_limit_not_a_runner_error(unlimited):
    import asyncio

    def register():
        @tests(expect_raises(OverflowError, []), expect_true([]))
        async def waits_once():
            await asyncio.sleep(0)
            return True
    results = _run_capped(register, timeout=unlimited)
    # the raises check fails (nothing raised); the truthy check passes
    assert results["failed"] == 1 and results["passed"] == 1, results


def test_a_test_that_cancels_every_other_task_repeatedly_cannot_abort_the_run():
    import asyncio

    def register():
        @tests(expect_true([]))
        async def keeps_cancelling():
            for _ in range(20):
                for t in asyncio.all_tasks():
                    if t is not asyncio.current_task():
                        t.cancel()
                await asyncio.sleep(0)
            return True

        @tests(expect_true([]))
        async def hangs_and_cancels_in_cleanup():
            try:
                await asyncio.Event().wait()
            finally:
                for t in asyncio.all_tasks():
                    if t is not asyncio.current_task():
                        t.cancel()

        @tests(expect_equal([], 2))
        def after():
            return 1
    results = _run_capped(register, timeout=0.2)
    assert (results["passed"], results["errors"], results["failed"]) == (1, 1, 1), results


def test_a_test_that_stops_the_loop_cannot_pass_expect_raises_runtime_error():
    import asyncio

    def register():
        @tests(expect_raises(RuntimeError, []))
        async def stops():
            asyncio.get_running_loop().stop()
            await asyncio.sleep(0)
            raise ValueError("the body")
    results = _run_capped(register)
    assert results["passed"] == 0, results


def test_a_test_that_stops_the_loop_is_stopped_and_cannot_leak_into_the_next():
    import asyncio
    seen = []

    def register():
        @tests(expect_true([]))
        async def a_stops_then_exits():
            asyncio.get_running_loop().stop()
            await asyncio.sleep(0.05)
            seen.append("a ran on")
            raise SystemExit(7)

        @tests(expect_raises(SystemExit, []))
        async def b_never_exits():
            await asyncio.sleep(0.3)
            return "b never exits"
    results = _run_capped(register)
    assert (results["errors"], results["failed"], results["passed"]) == (1, 1, 0), results
    assert seen == [], seen


def test_a_system_exit_from_a_task_left_running_is_never_a_later_tests_own():
    import asyncio

    def register():
        @tests(expect_true([]))
        async def a_spawns():
            async def bg():
                await asyncio.sleep(0.05)
                raise SystemExit(8)
            asyncio.ensure_future(bg())
            return True

        @tests(expect_raises(SystemExit, []))
        async def b_never_exits():
            await asyncio.sleep(0.3)
            return "b never exits"
    with pytest.raises(SystemExit):
        _run_capped(register)


def test_a_broken_task_factory_cannot_abort_the_run_or_pass_a_later_test():
    import asyncio

    def register():
        @tests(expect_true([]))
        async def installs():
            def factory(loop, coro, **kw):
                coro.close()
                raise ValueError("factory")
            asyncio.get_running_loop().set_task_factory(factory)
            return True

        @tests(expect_raises(ValueError, []))
        async def b():
            return "b does not raise"
    results = _run_capped(register)
    assert (results["passed"], results["errors"]) == (1, 1), results


def test_a_test_that_cancels_every_pending_future_cannot_abort_the_run():
    import asyncio
    import gc

    def register():
        @tests(expect_true([]))
        async def cancels_futures():
            loop = asyncio.get_running_loop()
            for obj in gc.get_objects():
                if (isinstance(obj, asyncio.Future) and not isinstance(obj, asyncio.Task)
                        and not obj.done() and obj.get_loop() is loop):
                    obj.cancel()
            await asyncio.sleep(0)
            return True

        @tests(expect_equal([], 1))
        def after():
            return 1
    results = _run_capped(register)
    assert results["passed"] >= 1 and results["errors"] <= 1, results
    assert "after" in results["details"][-1]["name"], results


def test_check_timeout_normalises_the_timeout():
    from tina4_python._testing_async import _check_timeout

    assert _check_timeout(None) is None
    assert _check_timeout(2) == 2.0
    assert _check_timeout(10 ** 400) is None


def test_expect_raises_base_exception_cannot_catch_the_run_ending():
    import asyncio

    def register():
        @tests(expect_true([]))
        async def a_spawns():
            async def bg():
                await asyncio.sleep(0.05)
                raise SystemExit(8)
            asyncio.ensure_future(bg())
            return True

        @tests(expect_raises(BaseException, []))
        async def b_sleeps():
            await asyncio.sleep(0.3)
    with pytest.raises(SystemExit):
        _run_capped(register)


def test_a_system_exit_while_closing_cannot_hide_the_results():
    import asyncio

    def register():
        @tests(expect_true([]))
        async def leaves_a_task():
            async def bg():
                try:
                    await asyncio.Event().wait()
                finally:
                    raise SystemExit(0)
            asyncio.ensure_future(bg())
            return True

        @tests(expect_equal([], 2))
        def fails():
            return 1
    results = _run_capped(register)
    assert (results["passed"], results["failed"]) == (1, 1), results


def test_a_system_exit_while_closing_does_not_skip_the_other_tasks_cleanup():
    import asyncio
    cleaned = []

    def register():
        @tests(expect_true([]))
        async def leaves_two():
            async def exits():
                try:
                    await asyncio.Event().wait()
                finally:
                    raise SystemExit(0)

            async def cleans():
                try:
                    await asyncio.Event().wait()
                finally:
                    await asyncio.sleep(0.05)
                    cleaned.append("cleaned")
            asyncio.ensure_future(exits())
            asyncio.ensure_future(cleans())
            await asyncio.sleep(0)
            return True
    results = _run_capped(register)
    assert results["passed"] == 1 and cleaned == ["cleaned"], (results, cleaned)
