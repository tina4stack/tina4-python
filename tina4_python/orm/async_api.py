# Tina4 ORM async API — every model operation, awaitable (ADR-0074).
"""
Each ORM operation has an awaitable twin named ``<operation>_async``. It runs the
sync operation on ONE borrowed connection, on the database's worker pool, so an
``async def`` route never blocks the event loop:

    @get("/users/{id}")
    async def show(id, request, response):
        user = await User.find_by_id_async(id)
        return response(user.to_dict() if user else {}, 200 if user else 404)

    user = User({"name": "Alice"})
    await user.save_async()
    page = await User.where_async("active = ?", [1], limit=20)

Return values and errors are the sync method's - it IS the sync method, run off
the loop (``Database.run_async``). Inside ``async with db.transaction_async():``
it runs on the transaction's connection.
"""


class ORMAsyncMixin:
    """The ``*_async`` half of :class:`~tina4_python.orm.ORM`."""

    # ── Instance operations ────────────────────────────────────────

    async def save_async(self):
        return await self._get_db().run_async(self.save)

    async def load_async(self, filter: str = None, params: list = None, include: list[str] = None) -> bool:
        return await self._get_db().run_async(self.load, filter, params, include)

    async def delete_async(self) -> bool:
        return await self._get_db().run_async(self.delete)

    async def force_delete_async(self) -> bool:
        return await self._get_db().run_async(self.force_delete)

    async def restore_async(self) -> bool:
        return await self._get_db().run_async(self.restore)

    async def has_one_async(self, related_class, foreign_key: str = None):
        return await self._get_db().run_async(self.has_one, related_class, foreign_key)

    async def has_many_async(self, related_class, foreign_key: str = None,
                             limit: int = None, offset: int = 0):
        return await self._get_db().run_async(self.has_many, related_class, foreign_key, limit, offset)

    async def belongs_to_async(self, related_class, foreign_key: str = None):
        return await self._get_db().run_async(self.belongs_to, related_class, foreign_key)

    # ── Class operations ───────────────────────────────────────────

    @classmethod
    async def create_async(cls, data: dict = None, **kwargs):
        return await cls._get_db().run_async(cls.create, data, **kwargs)

    @classmethod
    async def find_by_id_async(cls, pk_value, include: list[str] = None):
        return await cls._get_db().run_async(cls.find_by_id, pk_value, include)

    @classmethod
    async def find_async(cls, filter=None, limit: int = 100, offset: int = 0,
                         order_by: str = None, include: list[str] = None):
        return await cls._get_db().run_async(cls.find, filter, limit, offset, order_by, include)

    @classmethod
    async def find_or_fail_async(cls, pk_value):
        return await cls._get_db().run_async(cls.find_or_fail, pk_value)

    @classmethod
    async def exists_async(cls, pk_value) -> bool:
        return await cls._get_db().run_async(cls.exists, pk_value)

    @classmethod
    async def all_async(cls, limit: int = 100, offset: int = 0, include: list[str] = None,
                        order_by: str = None):
        return await cls._get_db().run_async(cls.all, limit, offset, include, order_by)

    @classmethod
    async def select_async(cls, *args, **kwargs):
        return await cls._get_db().run_async(cls.select, *args, **kwargs)

    @classmethod
    async def select_one_async(cls, sql: str, params: list = None, include: list[str] = None):
        return await cls._get_db().run_async(cls.select_one, sql, params, include)

    @classmethod
    async def where_async(cls, *args, **kwargs):
        return await cls._get_db().run_async(cls.where, *args, **kwargs)

    @classmethod
    async def with_trashed_async(cls, filter_sql: str = "1=1", params: list = None,
                                 limit: int = 100, offset: int = 0):
        return await cls._get_db().run_async(cls.with_trashed, filter_sql, params, limit, offset)

    @classmethod
    async def count_async(cls, conditions: str = None, params: list = None) -> int:
        return await cls._get_db().run_async(cls.count, conditions, params)

    @classmethod
    async def create_table_async(cls) -> bool:
        return await cls._get_db().run_async(cls.create_table)
