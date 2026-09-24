# Tina4 Database async API — the sync API, awaited, on a borrowed connection.
"""
Every Database operation has an awaitable twin named ``<operation>_async``
(ADR-0074). Use it in ``async def`` routes so a slow query never blocks the
event loop - and with it every other request:

    @get("/users/{id}")
    async def get_user(id, request, response):
        user = await db.fetch_one_async("SELECT * FROM users WHERE id = ?", [id])
        return response(user)

    async with db.transaction_async():
        await db.insert_async("orders", {"id": 1, "total": 10})
        await db.update_async("stock", {"qty": 4}, "sku = ?", ["A1"])

How it works, in one sentence: the async twin borrows a connection on the event
loop (waiting there, never on a thread), then runs the SAME sync method on the
pool's own worker thread. So results, return types and errors are the sync
API's, on every engine, with no new dependency and no driver-specific code.

A plain ``def`` route may keep using the sync API: Tina4 runs it in a worker
thread already.
"""
import asyncio
import contextlib
import contextvars
import functools


class DatabaseAsyncMixin:
    """The ``*_async`` half of :class:`~tina4_python.database.Database`."""

    # ── The one primitive ──────────────────────────────────────────

    async def run_async(self, operation, *args, **kwargs):
        """Run ANY sync callable on a borrowed connection, off the event loop.

        Everything the callable does through this Database - several queries,
        an ORM save, a QueryBuilder - uses that one connection, which goes back
        to the pool when it returns. Inside ``transaction_async()`` it runs on
        the transaction's connection.

            report = await db.run_async(build_report, month)
        """
        loop = asyncio.get_running_loop()
        borrow = self._borrowed.get()
        if borrow is not None:
            # This task holds a connection (a transaction): run on it, one
            # statement at a time, and never let it go back to anyone while a
            # statement is still running on it - hence the wait-through below.
            async with borrow.async_lock():
                return await self._finish(self._pool.executor().submit(
                    contextvars.copy_context().run, functools.partial(operation, *args, **kwargs)))
        adapter = await self._pool.checkout_async()
        job = functools.partial(self._run_on_borrowed, adapter, operation, args, kwargs)
        future = self._pool.executor().submit(contextvars.copy_context().run, job)
        # Cancelled before a worker picked it up: the job never runs, so the
        # connection is returned here. Once running, the job returns it itself.
        future.add_done_callback(lambda done: done.cancelled() and self._pool.checkin(adapter))
        return await asyncio.wrap_future(future, loop=loop)

    def _run_on_borrowed(self, adapter, operation, args, kwargs):
        """Worker side of run_async: hold ``adapter`` for exactly this call."""
        from tina4_python.database.connection import _Borrow
        token = self._borrowed.set(_Borrow(adapter))
        try:
            return operation(*args, **kwargs)
        finally:
            self._borrowed.reset(token)
            self._pool.checkin(adapter)

    @staticmethod
    async def _finish(future):
        """Await a worker future to COMPLETION even if this task is cancelled.

        Used where the connection stays with the task (a transaction): letting
        the task move on while a statement still runs would put two statements
        on one connection. The cancellation is re-raised once the worker is done.
        """
        wrapped = asyncio.wrap_future(future)
        cancelled = False
        while not wrapped.done():
            try:
                await asyncio.shield(wrapped)
            except asyncio.CancelledError:
                if not wrapped.done():
                    cancelled = True
            except BaseException:  # noqa: BLE001 - re-raised below via result()
                break
        if cancelled:
            raise asyncio.CancelledError
        return wrapped.result()

    # ── Transactions ───────────────────────────────────────────────

    async def start_transaction_async(self):
        """Begin a transaction that stays with THIS task until commit/rollback."""
        borrow = self._borrowed.get()
        if borrow is not None:
            # Nested begin, or a manual-commit write already holds a connection:
            # the sync method handles both on the held connection.
            await self._adopting(self.start_transaction)
            return
        adapter = await self._pool.checkout_async()
        await self._adopting(self._begin_on, adapter, on_abandon=adapter)

    async def commit_async(self):
        """Commit this task's transaction and return its connection."""
        await self._adopting(self.commit)

    async def rollback_async(self):
        """Roll back this task's transaction and return its connection."""
        await self._adopting(self.rollback)

    async def _adopting(self, operation, *args, on_abandon=None):
        """Run a transaction-boundary sync method on a worker, then adopt the
        connection it pinned (or released) into THIS task's context.

        A worker runs in a COPY of the task's context, so a pin it sets would
        otherwise be invisible to the task. Boundary statements are short
        (BEGIN/COMMIT/ROLLBACK), so a cancelled task waits for them to finish
        rather than orphan a connection mid-transaction.
        """
        context = contextvars.copy_context()
        borrow = self._borrowed.get()
        lock = borrow.async_lock() if borrow is not None else contextlib.nullcontext()
        async with lock:
            future = self._pool.executor().submit(
                context.run, functools.partial(operation, *args))
            if on_abandon is not None:
                future.add_done_callback(
                    lambda done: done.cancelled() and self._pool.checkin(on_abandon))
            try:
                result = await self._finish(future)
            finally:
                self._borrowed.set(context.get(self._borrowed))
        return result

    @contextlib.asynccontextmanager
    async def transaction_async(self):
        """``async with db.transaction_async():`` - commit on success, roll back on error."""
        await self.start_transaction_async()
        try:
            yield self
        except BaseException:
            await self.rollback_async()
            raise
        await self.commit_async()

    # ── Awaitable twins of the sync API ────────────────────────────

    async def execute_async(self, sql: str, params: list = None):
        return await self._write_async(self.execute, sql, params)

    async def execute_many_async(self, sql: str, params_list: list[list] = None):
        return await self._write_async(self.execute_many, sql, params_list)

    async def fetch_async(self, sql: str, params: list = None, limit: int = 100,
                          offset: int = 0, no_cache: bool = False):
        return await self.run_async(self.fetch, sql, params, limit, offset, no_cache=no_cache)

    async def fetch_all_async(self, sql: str, params: list = None, limit: int = 0,
                              offset: int = 0, no_cache: bool = False):
        return await self.run_async(self.fetch_all, sql, params, limit, offset, no_cache=no_cache)

    async def fetch_one_async(self, sql: str, params: list = None, no_cache: bool = False):
        return await self.run_async(self.fetch_one, sql, params, no_cache=no_cache)

    async def insert_async(self, table: str, data: dict | list):
        return await self._write_async(self.insert, table, data)

    async def update_async(self, table: str, data: dict, filter_sql: str | dict = "",
                           params: list = None):
        return await self._write_async(self.update, table, data, filter_sql, params)

    async def delete_async(self, table: str, filter_sql: str | dict | list = "",
                           params: list = None):
        return await self._write_async(self.delete, table, filter_sql, params)

    async def truncate_async(self, table: str):
        return await self._write_async(self.truncate, table)

    async def get_next_id_async(self, table: str, pk_column: str = "id",
                                generator_name: str = None) -> int:
        return await self.run_async(self.get_next_id, table, pk_column, generator_name)

    async def primary_key_async(self, table: str) -> list[str]:
        return await self.run_async(self.primary_key, table)

    async def table_exists_async(self, name: str) -> bool:
        return await self.run_async(self.table_exists, name)

    async def get_tables_async(self) -> list[str]:
        return await self.run_async(self.get_tables)

    async def get_columns_async(self, table: str) -> list[dict]:
        return await self.run_async(self.get_columns, table)

    async def _write_async(self, operation, *args):
        """A write. In manual-commit mode (TINA4_AUTOCOMMIT=false) an
        uncommitted write keeps its connection for this task until
        commit_async()/rollback_async(), exactly like the sync API."""
        if self._manual_commit and self._borrowed.get() is None:
            from tina4_python.database.connection import _Borrow
            adapter = await self._pool.checkout_async()
            self._borrowed.set(_Borrow(adapter, sticky=True, pool=self._pool))
        return await self.run_async(operation, *args)
