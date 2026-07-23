"""Regression suite for stopping and DEREGISTERING a background task.

The bug this locks in was found in Ruby (`Tina4::Background.stop_task` killed the
thread but left the descriptor in the `tasks` array), so the registry grew for the
whole process lifetime for any subsystem that starts and stops a task repeatedly,
and introspection reported stopped tasks as if they were still running.

Python had no per-task stop at all, so the leak could not occur here — the parity
gap was the missing capability. `background()` now returns a `BackgroundTask`
handle whose `.stop()` ends the task AND removes it from the registry, matching
Ruby's `stop_task` and Node's `handle.stop()`.

These drive the REAL registry and the REAL `_start_background_tasks` wiring the
server uses, with a real asyncio loop, a real ThreadPoolExecutor and real
callbacks. No mocks: nothing here stands in for a collaborator — the scheduler
under test is the one that ships.
"""
import asyncio
import concurrent.futures
import threading

import pytest

from tina4_python.core.server import (
    BackgroundTask,
    _start_background_tasks,
    background,
    background_task_count,
    stop_all_background_tasks,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """The registry is module-global — leave it empty on both sides of a test."""
    stop_all_background_tasks()
    yield
    stop_all_background_tasks()


class _Counter:
    """Counts real invocations. Thread-safe: sync callbacks run in the pool."""

    def __init__(self):
        self.lock = threading.Lock()
        self.runs = 0

    def __call__(self):
        with self.lock:
            self.runs += 1

    @property
    def count(self):
        with self.lock:
            return self.runs


# ── Registry semantics ───────────────────────────────────────────────────

def test_register_puts_a_live_handle_in_the_registry():
    """POSITIVE: a registered task is present and not stopped."""
    assert background_task_count() == 0

    counter = _Counter()
    task = background(counter, 0.05)

    assert isinstance(task, BackgroundTask)
    assert background_task_count() == 1
    assert task.stopped is False
    assert task.callback is counter
    assert task.interval == 0.05


def test_stop_removes_the_task_from_the_registry():
    """THE REGRESSION: a stopped task must not stay registered."""
    task = background(_Counter(), 0.05)
    assert background_task_count() == 1

    assert task.stop() is True

    assert background_task_count() == 0
    assert task.stopped is True


def test_stop_is_idempotent_and_does_not_raise():
    """A second stop is a safe no-op and reports that it removed nothing."""
    task = background(_Counter(), 0.05)
    assert task.stop() is True

    assert task.stop() is False  # already gone
    assert task.stop() is False
    assert background_task_count() == 0


def test_stop_removes_only_that_task_and_leaves_siblings_registered():
    """NEGATIVE: stopping one task must not deregister another.

    Both are registered with the SAME callable and the SAME interval, so an
    equality-based removal would be tempted to take out both.
    """
    shared = _Counter()
    first = background(shared, 0.05)
    second = background(shared, 0.05)
    assert background_task_count() == 2

    first.stop()

    assert background_task_count() == 1
    assert first.stopped is True
    assert second.stopped is False


def test_repeated_register_stop_cycles_do_not_grow_the_registry():
    """The leak itself: N start/stop cycles must end at zero, not N."""
    for _ in range(10):
        task = background(_Counter(), 0.05)
        task.stop()
        assert background_task_count() == 0

    assert background_task_count() == 0


def test_stop_all_background_tasks_clears_everything():
    """stop_all must empty the registry and report how many it stopped."""
    background(_Counter(), 0.05)
    background(_Counter(), 0.05)
    background(_Counter(), 0.05)
    assert background_task_count() == 3

    assert stop_all_background_tasks() == 3

    assert background_task_count() == 0
    # Already-empty is not an error, and stops nothing.
    assert stop_all_background_tasks() == 0


def test_stop_all_copes_with_an_already_stopped_task():
    """A partly-drained registry must still empty cleanly."""
    first = background(_Counter(), 0.05)
    background(_Counter(), 0.05)
    first.stop()
    assert background_task_count() == 1

    assert stop_all_background_tasks() == 1
    assert background_task_count() == 0


# ── Runtime behaviour: stop() really halts a TICKING task ────────────────

async def _run_started_tasks(seconds: float, workers: int = 4):
    """Start the registered tasks exactly as the server does, and tick them."""
    shutdown = asyncio.Event()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    runners = _start_background_tasks(executor, shutdown)
    try:
        await asyncio.sleep(seconds)
    finally:
        shutdown.set()
        for runner in runners:
            runner.cancel()
        await asyncio.gather(*runners, return_exceptions=True)
        executor.shutdown(wait=False)
    return runners


@pytest.mark.slow
async def test_stop_halts_a_task_that_is_already_ticking():
    """A running task stops firing after stop(), and its runner is cancelled."""
    counter = _Counter()
    task = background(counter, 0.05)

    shutdown = asyncio.Event()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    runners = _start_background_tasks(executor, shutdown)
    assert len(runners) == 1
    assert task._runner is runners[0]

    try:
        await asyncio.sleep(0.4)
        assert counter.count >= 2, f"task must have ticked; got {counter.count}"

        task.stop()
        assert background_task_count() == 0
        # Give the cancellation a moment to take effect, then confirm it froze.
        await asyncio.sleep(0.1)
        settled = counter.count
        await asyncio.sleep(0.4)

        assert counter.count == settled, (
            f"stop() must halt the callback; it ran {counter.count - settled} "
            f"more times after stopping"
        )
        assert runners[0].cancelled() or runners[0].done()
    finally:
        shutdown.set()
        for runner in runners:
            runner.cancel()
        await asyncio.gather(*runners, return_exceptions=True)
        executor.shutdown(wait=False)


@pytest.mark.slow
async def test_stopping_one_running_task_leaves_the_other_ticking():
    """NEGATIVE at runtime: the surviving task must keep firing."""
    stopped_counter = _Counter()
    live_counter = _Counter()
    doomed = background(stopped_counter, 0.05)
    background(live_counter, 0.05)

    shutdown = asyncio.Event()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    runners = _start_background_tasks(executor, shutdown)

    try:
        await asyncio.sleep(0.4)
        doomed.stop()
        await asyncio.sleep(0.1)

        frozen = stopped_counter.count
        live_before = live_counter.count
        await asyncio.sleep(0.4)

        assert stopped_counter.count == frozen, "the stopped task must be frozen"
        assert live_counter.count > live_before, (
            "the surviving task must keep ticking after its sibling was stopped"
        )
        assert background_task_count() == 1
    finally:
        shutdown.set()
        for runner in runners:
            runner.cancel()
        await asyncio.gather(*runners, return_exceptions=True)
        executor.shutdown(wait=False)


@pytest.mark.slow
async def test_a_task_stopped_before_the_server_starts_never_runs():
    """Stopping before start must deregister AND never schedule a runner."""
    counter = _Counter()
    task = background(counter, 0.05)
    task.stop()

    runners = await _run_started_tasks(0.3)

    assert runners == [], "a stopped task must not be started"
    assert counter.count == 0, "a task stopped before start must never fire"
