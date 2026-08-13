"""Shared contract suite for feature 47 — background tasks.

Fixture: tina4-documentation/plan/v3/fixtures/backgroundtasks_contract.json
Decisions: BG-DEC-01 (run under the production runtime, not just the dev loop) +
BG-DEC-02 (ONE surface: a stop-handle + a count).

NO MOCKS. Every case exercises the REAL runtime with a REAL side effect:

  * "runs under the production runtime" boots a REAL uvicorn (the production ASGI
    server) running the framework's own `app`, and asserts a task scheduled via
    `background()` wrote a REAL file — the direct proof of the BG-PY-PROD-NOOP
    fix (before it, uvicorn's lifespan started nothing and the task never ran).
  * "guarded, not a silent drop" drives the REAL ASGI lifespan protocol in
    process: lifespan.startup must START the task (it ticks and writes a real
    file) and lifespan.shutdown must STOP it. Mutation-proof: unwire the lifespan
    startup and this goes RED (the file never grows).
  * count / stop-handle cases use the real registry and a real ticking runner.
"""
import asyncio
import concurrent.futures
import os
import socket
import subprocess
import sys
import time

from tina4_python.core.server import (
    app,
    background,
    background_task_count,
    stop_all_background_tasks,
    _start_background_tasks,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port() -> int:
    """A port free right now — the child binds it a moment later (small race, fine for a test)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# The child app: registers a background task that appends one byte per tick to a
# real file, then serves the framework's real ASGI `app` under real uvicorn.
_CHILD_APP = '''\
import os
from tina4_python.core.server import app, background

_counter = os.environ["BG_COUNTER_FILE"]


def _tick():
    with open(_counter, "a") as handle:
        handle.write("x")


background(_tick, interval=0.1)

import uvicorn
uvicorn.run(app, host="127.0.0.1", port=int(os.environ["BG_PORT"]), log_level="warning")
'''


def test_a_scheduled_task_runs_under_the_production_runtime(tmp_path):
    """A task scheduled via background() RUNS under a real uvicorn (production ASGI).

    This is the BG-PY-PROD-NOOP regression: the tasks are started from the ASGI
    lifespan startup. Break that wiring and this child writes nothing -> RED.
    """
    counter = tmp_path / "ticks.txt"
    script = tmp_path / "prod_app.py"
    script.write_text(_CHILD_APP)
    port = _free_port()

    env = {
        **os.environ,
        "BG_COUNTER_FILE": str(counter),
        "BG_PORT": str(port),
        "TINA4_SUPPRESS": "true",
        "TINA4_NO_BROWSER": "true",
    }
    proc = subprocess.Popen([sys.executable, str(script)], cwd=REPO_ROOT, env=env)
    try:
        deadline = time.time() + 20
        ticks = 0
        while time.time() < deadline:
            if counter.exists():
                ticks = len(counter.read_text())
                if ticks >= 2:
                    break
            time.sleep(0.1)
        assert ticks >= 2, (
            f"background() task never ran under uvicorn (ticks={ticks}); "
            f"the production ASGI lifespan did not start it (BG-PY-PROD-NOOP)"
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


async def test_a_non_persistent_runtime_is_guarded_not_a_silent_drop(tmp_path):
    """Driving the REAL ASGI lifespan starts the task on startup and stops it on shutdown.

    This is the deterministic half of the same fix and the mutation gate: remove
    the `_spin_up_background_tasks` call from the lifespan.startup branch and
    `ticks_during` stays 0 (the production entry point is a silent no-op again).
    """
    stop_all_background_tasks()
    counter = tmp_path / "life.txt"

    def _tick():
        with open(counter, "a") as handle:
            handle.write("x")

    background(_tick, interval=0.05)

    inbound = asyncio.Queue()
    await inbound.put({"type": "lifespan.startup"})
    sent: list[str] = []
    startup_done = asyncio.Event()
    shutdown_done = asyncio.Event()

    async def receive():
        return await inbound.get()

    async def send(message):
        sent.append(message["type"])
        if message["type"] == "lifespan.startup.complete":
            startup_done.set()
        elif message["type"] == "lifespan.shutdown.complete":
            shutdown_done.set()

    lifespan = asyncio.create_task(app({"type": "lifespan"}, receive, send))
    try:
        await asyncio.wait_for(startup_done.wait(), timeout=5)
        await asyncio.sleep(0.35)  # let the real runner tick on the real loop
        ticks_during = len(counter.read_text()) if counter.exists() else 0

        await inbound.put({"type": "lifespan.shutdown"})
        await asyncio.wait_for(shutdown_done.wait(), timeout=5)
        await asyncio.wait_for(lifespan, timeout=5)
        ticks_at_shutdown = len(counter.read_text()) if counter.exists() else 0
        await asyncio.sleep(0.3)
        ticks_after = len(counter.read_text()) if counter.exists() else 0

        assert "lifespan.startup.complete" in sent
        assert "lifespan.shutdown.complete" in sent
        assert ticks_during >= 2, (
            "lifespan.startup must START background tasks under the production "
            "server; it ran 0-1 times (a silent no-op)"
        )
        # One in-flight tick may land between shutdown and the check; no more.
        assert ticks_after - ticks_at_shutdown <= 1, (
            "lifespan.shutdown must STOP the background tasks"
        )
    finally:
        if not lifespan.done():
            lifespan.cancel()
        stop_all_background_tasks()


def test_count_reflects_pending_and_running_tasks():
    """count() climbs by one per registration (BG-DEC-02 count surface)."""
    stop_all_background_tasks()
    assert background_task_count() == 0
    first = background(lambda: None, interval=1.0)
    assert background_task_count() == 1
    second = background(lambda: None, interval=1.0)
    assert background_task_count() == 2
    first.stop()
    second.stop()


def test_count_returns_to_zero_when_a_task_is_stopped():
    """A stopped task leaves the registry, so count() returns to 0."""
    stop_all_background_tasks()
    handle = background(lambda: None, interval=1.0)
    assert background_task_count() == 1
    handle.stop()
    assert background_task_count() == 0


async def test_the_stop_handle_cancels_a_running_task(tmp_path):
    """The handle's stop() cancels a task that is actually ticking (BG-DEC-02 handle)."""
    stop_all_background_tasks()
    counter = tmp_path / "stop.txt"

    def _tick():
        with open(counter, "a") as handle_file:
            handle_file.write("x")

    handle = background(_tick, interval=0.05)
    shutdown = asyncio.Event()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    runners = _start_background_tasks(executor, shutdown)  # binds handle._runner
    try:
        await asyncio.sleep(0.3)
        during = len(counter.read_text()) if counter.exists() else 0
        assert during >= 2, f"the task must tick before we stop it; got {during}"

        assert handle.stop() is True  # removed a live, running task
        await asyncio.sleep(0.3)
        after = len(counter.read_text()) if counter.exists() else 0
        assert after - during <= 1, (
            f"stop() must cancel the running task; it kept ticking "
            f"({during} -> {after})"
        )
    finally:
        shutdown.set()
        for runner in runners:
            runner.cancel()
        stop_all_background_tasks()
        executor.shutdown(wait=False, cancel_futures=True)


def test_a_second_stop_is_a_safe_no_op():
    """stop() is idempotent: True the first time, False thereafter — never raises."""
    stop_all_background_tasks()
    handle = background(lambda: None, interval=1.0)
    assert handle.stop() is True
    assert handle.stop() is False
    assert handle.stop() is False
    assert background_task_count() == 0
