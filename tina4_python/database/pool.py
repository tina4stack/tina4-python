# Tina4 Database Pool — every connection is lent to ONE borrower at a time.
"""
A bounded pool of adapter connections (ADR-0074).

    pool = ConnectionPool(pool_size=10, factory=make_adapter, connect_path=url)
    adapter = pool.checkout()          # blocks until a connection is free
    try:
        adapter.fetch(...)
    finally:
        pool.checkin(adapter)           # back to the pool for the next borrower

``checkout_async()`` is the same checkout for a coroutine: it waits on the event
loop, never on a thread, so a burst of async requests cannot tie up the worker
threads while they queue for a connection.

A checkout that waits longer than TINA4_DB_POOL_TIMEOUT raises
DatabasePoolExhausted, which names TINA4_DB_POOL so the fix is in the message.
"""
import asyncio
import os
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

#: ADR-0074. Big enough that ordinary concurrent requests never queue, small
#: enough that a few workers stay well under PostgreSQL's default
#: max_connections=100. Connections open lazily, so an idle app holds one.
DEFAULT_POOL_SIZE = 10
DEFAULT_POOL_TIMEOUT_SECONDS = 30.0


class DatabasePoolExhausted(TimeoutError):
    """Every pooled connection stayed checked out for longer than the timeout.

    A TimeoutError subclass, so ``except TimeoutError`` catches it without an
    import from Tina4.
    """


def resolve_pool_size(pool: int | None) -> int:
    """The pool size: explicit argument, else TINA4_DB_POOL, else the default.

    ``0`` keeps its documented meaning, "a single connection" - it is now LENT
    exclusively like any other pool, so it serialises instead of being shared.
    """
    if pool is None:
        raw = os.environ.get("TINA4_DB_POOL", "").strip()
        if not raw:
            return DEFAULT_POOL_SIZE
        try:
            pool = int(raw)
        except ValueError:
            from tina4_python.debug import Log
            Log.warning(f"TINA4_DB_POOL={raw!r} is not a whole number - using {DEFAULT_POOL_SIZE}")
            return DEFAULT_POOL_SIZE
    return max(1, int(pool))


def resolve_pool_timeout() -> float | None:
    """Seconds a checkout may wait. ``None`` (TINA4_DB_POOL_TIMEOUT <= 0) waits forever."""
    raw = os.environ.get("TINA4_DB_POOL_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_POOL_TIMEOUT_SECONDS
    try:
        seconds = float(raw)
    except ValueError:
        from tina4_python.debug import Log
        Log.warning(f"TINA4_DB_POOL_TIMEOUT={raw!r} is not a number of seconds - "
                    f"using {DEFAULT_POOL_TIMEOUT_SECONDS:g}")
        return DEFAULT_POOL_TIMEOUT_SECONDS
    return None if seconds <= 0 else seconds


class ConnectionPool:
    """A bounded pool that lends each adapter to exactly one borrower.

    Adapters are created lazily up to ``pool_size``. ``checkout()`` hands out an
    idle adapter, creates one while under the bound, and otherwise waits for a
    ``checkin()``. Blocked threads are served before waiting coroutines: a
    blocked thread may be the event loop itself, and every coroutine waits on it.
    """

    def __init__(self, pool_size: int, factory: callable, connect_path: str,
                 username: str = "", password: str = "", **kwargs):
        self._pool_size = max(1, int(pool_size))
        self._factory = factory
        self._connect_path = connect_path
        self._username = username
        self._password = password
        self._connect_kwargs = kwargs
        #: Every live adapter this pool opened, lent or idle.
        self._adapters: list = []
        self._idle: list = []
        self._lent: set[int] = set()
        self._creating = 0
        self._lock = threading.Lock()
        self._available = threading.Condition(self._lock)
        self._threads_waiting = 0
        self._coroutines_waiting: deque = deque()
        self._connect_hooks: list = []
        self._executor: ThreadPoolExecutor | None = None
        self.timeout = resolve_pool_timeout()

    # ── Introspection ──────────────────────────────────────────────

    @property
    def size(self) -> int:
        return self._pool_size

    @property
    def active_count(self) -> int:
        """Connections opened so far (lent or idle)."""
        with self._lock:
            return len(self._adapters)

    @property
    def in_use_count(self) -> int:
        """Connections lent out right now."""
        with self._lock:
            return len(self._lent)

    @property
    def idle_count(self) -> int:
        with self._lock:
            return len(self._idle)

    def peek(self):
        """An adapter WITHOUT lending it - for driver-specific setup and
        introspection only. Opens the first connection if none exists yet."""
        with self._lock:
            if self._idle:
                return self._idle[-1]
            if self._adapters:
                return self._adapters[0]
        self.checkin(self.checkout())
        return self.peek()

    def add_connect_hook(self, hook: callable) -> None:
        """Run ``hook(adapter)`` on every open connection and on each new one."""
        with self._lock:
            self._connect_hooks.append(hook)
            existing = list(self._adapters)
        for adapter in existing:
            hook(adapter)

    def executor(self) -> ThreadPoolExecutor:
        """The worker threads the async API runs statements on.

        One thread per connection: a statement only reaches a worker once it
        holds a connection, so this never runs out of threads and never shares
        them with the server's own sync-route threads.
        """
        if self._executor is None:
            with self._lock:
                if self._executor is None:
                    self._executor = ThreadPoolExecutor(
                        max_workers=self._pool_size, thread_name_prefix="tina4-db")
        return self._executor

    # ── Lending ────────────────────────────────────────────────────

    def _exhausted(self, waited: float, timeout: float) -> DatabasePoolExhausted:
        return DatabasePoolExhausted(
            f"Database pool exhausted: all {self._pool_size} connection(s) stayed in use "
            f"for {waited:.1f}s (TINA4_DB_POOL={self._pool_size}, "
            f"TINA4_DB_POOL_TIMEOUT={timeout:g}s). Raise TINA4_DB_POOL, commit or "
            f"roll back long transactions sooner, or raise TINA4_DB_POOL_TIMEOUT."
        )

    def _take_locked(self):
        """(adapter, may_create). Caller holds the lock."""
        if self._idle:
            adapter = self._idle.pop()
            self._lent.add(id(adapter))
            return adapter, False
        if len(self._adapters) + self._creating < self._pool_size:
            self._creating += 1
            return None, True
        return None, False

    def _create(self):
        """Open a connection for a slot already reserved by _take_locked."""
        from tina4_python.database.connection import _connect_or_explain
        try:
            adapter = self._factory()
            _connect_or_explain(adapter, self._connect_path, username=self._username,
                                password=self._password, **self._connect_kwargs)
            for hook in list(self._connect_hooks):
                hook(adapter)
        except BaseException:
            with self._lock:
                self._creating -= 1
                self._signal_capacity_locked()
            raise
        with self._lock:
            self._creating -= 1
            self._adapters.append(adapter)
            self._lent.add(id(adapter))
        return adapter

    def checkout(self, timeout: float | None = ...):
        """Lend an adapter to the caller, waiting for one if all are in use."""
        timeout = self.timeout if timeout is ... else timeout
        started = time.monotonic()
        with self._lock:
            while True:
                adapter, may_create = self._take_locked()
                if adapter is not None:
                    return adapter
                if may_create:
                    break
                remaining = None if timeout is None else timeout - (time.monotonic() - started)
                if remaining is not None and remaining <= 0:
                    raise self._exhausted(time.monotonic() - started, timeout)
                self._threads_waiting += 1
                try:
                    self._available.wait(remaining)
                finally:
                    self._threads_waiting -= 1
        return self._create()

    async def checkout_async(self, timeout: float | None = ...):
        """``checkout()`` for a coroutine: waits on the loop, never on a thread."""
        timeout = self.timeout if timeout is ... else timeout
        loop = asyncio.get_running_loop()
        started = loop.time()
        while True:
            with self._lock:
                adapter, may_create = self._take_locked()
                waiter = None
                if adapter is None and not may_create:
                    waiter = loop.create_future()
                    self._coroutines_waiting.append((loop, waiter))
            if adapter is not None:
                return adapter
            if may_create:
                return await self._create_async(loop)
            remaining = None if timeout is None else timeout - (loop.time() - started)
            try:
                if remaining is not None and remaining <= 0:
                    raise asyncio.TimeoutError
                handed = await asyncio.wait_for(asyncio.shield(waiter), remaining)
            except asyncio.TimeoutError:
                if not waiter.cancel() and waiter.result() is not None:
                    return waiter.result()  # handed over as the clock ran out
                raise self._exhausted(loop.time() - started, timeout) from None
            except asyncio.CancelledError:
                if not waiter.cancel() and waiter.result() is not None:
                    self.checkin(waiter.result())
                raise
            if handed is not None:
                return handed
            # None means "a slot opened up" - go round and take it.

    async def _create_async(self, loop):
        future = self.executor().submit(self._create)
        try:
            return await asyncio.wrap_future(future, loop=loop)
        except asyncio.CancelledError:
            # The connect finishes on its thread; hand the result back.
            future.add_done_callback(
                lambda done: done.cancelled() or done.exception() is not None
                or self.checkin(done.result()))
            raise

    def checkin(self, adapter) -> None:
        """Return a lent adapter. A transaction left open on it is rolled back
        first: a connection never goes back to the pool mid-transaction."""
        if adapter is None:
            return
        healthy = True
        if getattr(adapter, "_in_transaction", False):
            try:
                adapter.rollback()
            except Exception:  # noqa: BLE001 - a connection that cannot roll back is retired
                healthy = False
        with self._lock:
            if id(adapter) not in self._lent:
                return  # not ours, already returned, or the pool was closed
            self._lent.discard(id(adapter))
            if not healthy:
                self._retire_locked(adapter)
                return
            self._hand_over_locked(adapter)

    def _hand_over_locked(self, adapter) -> None:
        if self._threads_waiting:
            self._idle.append(adapter)
            self._available.notify()
            return
        while self._coroutines_waiting:
            loop, waiter = self._coroutines_waiting.popleft()
            if waiter.done() or loop.is_closed():
                continue
            self._lent.add(id(adapter))
            loop.call_soon_threadsafe(self._deliver, waiter, adapter)
            return
        self._idle.append(adapter)

    def _deliver(self, waiter, adapter) -> None:
        """Runs on the waiter's loop."""
        if waiter.done():
            if adapter is not None:
                self.checkin(adapter)
            else:
                with self._lock:
                    self._signal_capacity_locked()
            return
        waiter.set_result(adapter)

    def _signal_capacity_locked(self) -> None:
        """A slot opened without an adapter to hand over: wake one waiter to create."""
        if self._threads_waiting:
            self._available.notify()
            return
        while self._coroutines_waiting:
            loop, waiter = self._coroutines_waiting.popleft()
            if not waiter.done() and not loop.is_closed():
                loop.call_soon_threadsafe(self._deliver, waiter, None)
                return

    def _retire_locked(self, adapter) -> None:
        self._adapters = [a for a in self._adapters if a is not adapter]
        try:
            adapter.close()
        except Exception:  # noqa: BLE001 - it is being thrown away
            pass
        self._signal_capacity_locked()

    def close_all(self) -> None:
        """Close every connection. The pool reopens lazily if used again."""
        with self._lock:
            adapters, self._adapters, self._idle = self._adapters, [], []
            self._lent.clear()
            executor, self._executor = self._executor, None
            self._signal_capacity_locked()
        for adapter in adapters:
            try:
                adapter.close()
            except Exception:  # noqa: BLE001 - closing is best effort
                pass
        if executor is not None:
            executor.shutdown(wait=False)
