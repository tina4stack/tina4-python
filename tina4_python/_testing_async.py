# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Awaiting async inline tests for :mod:`tina4_python.Testing`.

One event loop per ``run_all()``; every test's awaitable runs as a task the
runner watches from outside the loop, so nothing a test does can cancel, hang
or abort the runner itself.
"""
import asyncio
import inspect
import numbers

# How long a cancelled test task gets to finish before the runner moves on.
_CANCEL_GRACE = 1.0


class _AsyncRunnerError(RuntimeError):
    """The runner could not run a test, which is never the test's own exception."""


class _RunAborted(BaseException):
    """A SystemExit / KeyboardInterrupt that did not come from the test being
    judged (a Ctrl-C, or a task an earlier test left running). It ends the run,
    as it would from a sync test, and no assertion can catch it as its own."""


def _check_timeout(timeout):
    """Seconds as a float (infinity allowed), or None for no limit."""
    if timeout is None:
        return None
    if isinstance(timeout, bool) or not isinstance(timeout, numbers.Real):
        raise TypeError(f"timeout must be a number of seconds or None, got {timeout!r}")
    try:
        seconds = float(timeout)
    except OverflowError:
        return None  # larger than any float: no limit
    if seconds != seconds or seconds < 0:
        raise ValueError(f"timeout must be zero or more seconds, got {timeout!r}")
    return seconds


def _run_for(loop, tasks, timeout) -> None:
    """Run ``loop`` until every task in ``tasks`` is done or ``timeout`` passes.

    It waits on a plain future, not a task, so nothing a test does through
    ``asyncio.all_tasks()`` (a "cancel every other task" teardown) can reach the
    runner itself. An ordinary exception out of the loop (a test stopped it) is
    the runner's failure, never the test's own exception.
    """
    pending = [t for t in tasks if not t.done()]
    if not pending:
        return
    waiter = loop.create_future()

    def wake(_=None, expired=False):
        if not waiter.done() and (expired or all(t.done() for t in pending)):
            waiter.set_result(None)

    for t in pending:
        t.add_done_callback(wake)
    handle = loop.call_later(timeout, wake, None, True) if timeout is not None else None
    try:
        loop.run_until_complete(waiter)
    except (Exception, asyncio.CancelledError) as exc:
        raise _AsyncRunnerError(f"the test runner's event loop failed: {exc!r}") from exc
    finally:
        if handle is not None:
            handle.cancel()
        for t in pending:
            t.remove_done_callback(wake)


def _settle(loop, tasks) -> None:
    """Give ``tasks`` the cancel grace while the run is closing. Results are
    already in: a SystemExit from a task an earlier test abandoned must not turn
    a failed run into exit status 0, nor skip the cleanup of the others."""
    try:
        _run_for(loop, tasks, _CANCEL_GRACE)
    except (_AsyncRunnerError, SystemExit):
        pass


class _AsyncRunner:
    """Runs awaitable test results to completion on one loop per run_all()."""

    def __init__(self, timeout: float | None = 30.0):
        self._timeout = _check_timeout(timeout)
        self._loop = None

    def call(self, fn, args):
        """Call ``fn(*args)``; an awaitable result is awaited and its value returned."""
        result = fn(*args)
        if not inspect.isawaitable(result):
            return result
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            if inspect.iscoroutine(result):
                result.close()  # never started: no "was never awaited" warning
            raise _AsyncRunnerError(
                "async test function: run_all() was called from inside a running "
                "event loop and cannot await it; call run_all() from synchronous code"
            )
        return self._await(result)

    def _await(self, result):
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        # A task watched from outside, not wait_for: a TimeoutError the test
        # raises itself must reach the assertion as the test's own exception.
        try:
            task = asyncio.ensure_future(result, loop=self._loop)
        except Exception as exc:  # a foreign-loop future, a broken task factory
            raise _AsyncRunnerError(f"could not schedule the async test: {exc!r}") from exc
        try:
            _run_for(self._loop, [task], self._timeout)
        except _AsyncRunnerError:
            self._stop(task)  # e.g. the test stopped the loop: it must not run on
            raise
        except BaseException as exc:
            # A SystemExit / KeyboardInterrupt out of the loop is the test's own
            # only when its task finished with exactly that exception.
            if task.done() and not task.cancelled() and task.exception() is exc:
                raise
            self._stop(task)
            raise _RunAborted(exc) from None
        return self._judge(task)

    def _stop(self, task):
        if not task.done():
            task.cancel()
            try:
                _run_for(self._loop, [task], _CANCEL_GRACE)
            except _AsyncRunnerError:
                pass

    def _judge(self, task):
        if not task.done():
            # Bounded: a test that swallows CancelledError must not hang the run.
            self._stop(task)
            raise _AsyncRunnerError(f"async test function did not finish within {self._timeout}s")
        if task.cancelled():
            # The test cancelled itself (raised CancelledError). That is a
            # BaseException and would abort the whole run; report it instead.
            raise _AsyncRunnerError("async test function was cancelled")
        return task.result()

    def close(self):
        if self._loop is None:
            return
        loop, self._loop = self._loop, None
        try:
            loop.set_task_factory(None)  # a test may have installed a broken one
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            # Twice: a SystemExit from one abandoned task stops the loop before
            # the others have run their cleanup.
            _settle(loop, pending)
            _settle(loop, pending)
            # Bounded the same way: a generator whose cleanup swallows
            # CancelledError must not hang the run.
            shutdown = loop.create_task(loop.shutdown_asyncgens())
            _settle(loop, [shutdown])
            shutdown.cancel()
            _settle(loop, [shutdown])
        finally:
            loop.close()
