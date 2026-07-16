"""Regression suite for background() task scheduling (tina4-python#93 -> #94).

The bug (#94): `background(fn, interval=N)` ran a SYNC callback concurrently with
itself whenever a run took longer than the loop's timeout. `asyncio.wait_for`
around `loop.run_in_executor(...)` cannot cancel a thread that has already
started - `concurrent.futures.Future.cancel()` returns False once the callable is
running - so on timeout it abandoned the wrapper future, the thread kept running,
and the next tick started a SECOND copy alongside it. It also logged "was
interrupted" for a task that was not interrupted, which hid the cause. In a real
app this double-sent customer emails from an outbox drainer, in ONE process.

These drive the REAL `background_tick_loop` coroutine the server runs, with a real
ThreadPoolExecutor, real threads and real asyncio. No mocks: the callbacks are the
actual unit under test (a slow sweep), not stand-ins for a collaborator.
"""
import asyncio
import concurrent.futures
import threading
import pytest

from tina4_python.core.server import background_tick_loop


class _ConcurrencyProbe:
    """Counts how many copies of the callback are in flight at once."""

    def __init__(self, work_seconds: float):
        self.work_seconds = work_seconds
        self.lock = threading.Lock()
        self.in_flight = 0
        self.peak = 0
        self.runs = 0

    def __call__(self):
        with self.lock:
            self.in_flight += 1
            self.runs += 1
            self.peak = max(self.peak, self.in_flight)
        try:
            # Real blocking work, deliberately longer than the loop's timeout.
            threading.Event().wait(self.work_seconds)
        finally:
            with self.lock:
                self.in_flight -= 1


async def _drive(callback, interval, seconds, workers=2):
    """Run the real tick loop for `seconds`, then shut it down."""
    shutdown = asyncio.Event()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    task = asyncio.create_task(background_tick_loop(callback, interval, executor, shutdown))
    await asyncio.sleep(seconds)
    shutdown.set()
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    executor.shutdown(wait=False)


@pytest.mark.slow
async def test_slow_sync_task_never_runs_concurrently_with_itself():
    """THE regression test for #94: a run longer than the timeout must not overlap.

    The overlap only triggers once a run EXCEEDS the loop's timeout, and that
    timeout has a 5s floor (`max(interval * 2, 5.0)`). So this deliberately uses a
    6.5s callback and runs for ~14s - a faster callback never crosses the floor and
    would pass against the OLD code too, proving nothing. Measured on the pre-fix
    code this reports PEAK=2; the invariant is PEAK=1.
    """
    probe = _ConcurrencyProbe(work_seconds=6.5)

    await _drive(probe, interval=0.1, seconds=14.0)

    assert probe.runs >= 2, f"the loop must have ticked more than once; got {probe.runs}"
    assert probe.peak == 1, (
        f"background() must never run a task concurrently with itself "
        f"(peak concurrency was {probe.peak} - a run outlasting the timeout was "
        f"abandoned and the next tick started alongside it)"
    )


@pytest.mark.slow
async def test_slow_sync_task_defers_rather_than_piling_up():
    """Runs are serialised, so the count is bounded by wall-clock / run-time.

    ~14s of driving with a 6.5s callback can complete at most ~2-3 runs when they
    are serialised. Overlapping execution inflates this.
    """
    probe = _ConcurrencyProbe(work_seconds=6.5)

    await _drive(probe, interval=0.1, seconds=14.0)

    assert probe.runs <= 3, (
        f"serialised runs are bounded by wall-clock/run-time; got {probe.runs} "
        f"(overlap would inflate this)"
    )


async def test_fast_sync_task_runs_every_interval():
    """Control: the no-overlap rule must not stall a well-behaved fast task."""
    probe = _ConcurrencyProbe(work_seconds=0.0)

    await _drive(probe, interval=0.05, seconds=0.6)

    assert probe.runs >= 3, f"a fast task must keep ticking; got {probe.runs}"
    assert probe.peak == 1


async def test_async_callback_still_runs_and_does_not_overlap():
    """Control: async callbacks keep working (their branch is cancellable)."""
    state = {"in_flight": 0, "peak": 0, "runs": 0}

    async def _cb():
        state["in_flight"] += 1
        state["runs"] += 1
        state["peak"] = max(state["peak"], state["in_flight"])
        await asyncio.sleep(0.05)
        state["in_flight"] -= 1

    await _drive(_cb, interval=0.05, seconds=0.6)

    assert state["runs"] >= 3, f"async task must keep ticking; got {state['runs']}"
    assert state["peak"] == 1, "async tasks must not overlap either"


async def test_callback_error_does_not_kill_the_loop():
    """Control: a raising callback is logged and the next interval still fires."""
    calls = {"n": 0}

    def _boom():
        calls["n"] += 1
        raise RuntimeError("intentional")

    await _drive(_boom, interval=0.05, seconds=0.4)

    assert calls["n"] >= 2, f"the loop must survive a callback error; got {calls['n']} calls"
