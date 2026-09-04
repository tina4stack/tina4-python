# Tina4 ModelCollection — a list of ORM models that also carries the query total.
"""
ModelCollection is what the ORM read queries (``where`` / ``select`` / ``find`` /
``all`` / ``with_trashed``) return. It IS a ``list`` -- iterate it, index it,
slice it, call ``len()`` on it, serialise it -- so every existing caller keeps
working unchanged. It adds one thing: the TOTAL number of rows matching the
query's filter, independent of ``limit`` / ``offset``.

The total is free. Every one of those methods already runs ``db.fetch()``, which
computes a ``SELECT COUNT(*)`` probe and hands it back on ``DatabaseResult.count``;
the ORM used to hydrate the page of models and throw that count away. This class
carries it instead, so a caller with 20 models on the page can still learn there
are 250 rows in the set.

Uniform across all four Tina4 frameworks (ADR-0064). Same concept, language-
idiomatic accessor name:

    Python / Ruby : get_total_records()   to_paginate()
    PHP / Node    : getTotalRecords()     toPaginate()

The accessor is a METHOD, not a ``.total`` attribute, on purpose: ``list.count()``
(Python) and ``Array#count`` (Ruby) already exist, so a ``.count`` would shadow a
built-in. ``DatabaseResult`` keeps its ``.count`` property (it is not a list); both
expose the identical seven-key ``to_paginate()`` envelope.
"""


class ModelCollection(list):
    """A ``list`` of ORM model instances plus the total for the query.

    Args:
        items:  the page of hydrated model instances.
        total:  total rows matching the query's filter (ignores limit/offset).
        limit:  the SQL limit that produced this page.
        offset: the SQL offset that produced this page.
    """

    def __init__(self, items=None, total=0, limit=0, offset=0):
        super().__init__(items or [])
        self._total = int(total or 0)
        self._limit = int(limit or 0)
        self._offset = int(offset or 0)

    def get_total_records(self) -> int:
        """Total rows matching the query's filter, ignoring limit/offset.

        This is the whole point of the collection: the page slice you are
        iterating is capped by ``limit``, but this number is the full count of
        matching rows -- what a pager needs to render "page 3 of 13".
        """
        return self._total

    def to_paginate(self) -> dict:
        """The canonical pagination envelope -- seven snake_case keys, identical
        to ``DatabaseResult.to_paginate()`` (ADR-0043) and to the other three
        frameworks' ``toPaginate()``.

            records     the page's rows as dicts (never re-sliced)
            total       get_total_records() -- the true total for the filter
            page        floor(offset / per_page) + 1
            per_page    the query's limit
            total_pages ceil(total / per_page)
            limit       the SQL limit actually applied
            offset      the SQL offset actually applied

        ``records`` are model dicts (via ``to_dict()``) so the JSON a client sees
        matches ``DatabaseResult`` exactly -- the result is uniform whether the
        route returned a raw ``db.fetch()`` or an ORM query.
        """
        per_page = self._limit if self._limit and self._limit > 0 else len(self)
        page = (self._offset // per_page) + 1 if per_page > 0 else 1
        total_pages = max(1, -(-self._total // per_page)) if per_page > 0 else 1
        records = [m.to_dict() if hasattr(m, "to_dict") else m for m in self]
        return {
            "records": records,
            "total": self._total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "limit": per_page,
            "offset": self._offset,
        }
