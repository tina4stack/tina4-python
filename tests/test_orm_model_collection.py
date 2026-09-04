"""ModelCollection — ORM read queries carry the query total (ADR-0064).

Real SQLite, real ORM writes, no mocks. This is the Python reference for the
uniform cross-framework contract: where/select/find/all/with_trashed return a
list-compatible collection that also exposes get_total_records() and the same
seven-key to_paginate() envelope as DatabaseResult.
"""
from __future__ import annotations

import pytest

from tina4_python.database import Database
from tina4_python.orm import (
    ORM, IntegerField, StringField, NumericField, ModelCollection, bind_database,
)


def _seed(n_books=250, n_music=7):
    db = Database("sqlite:///:memory:")
    bind_database(db)

    class Product(ORM):
        id = IntegerField(primary_key=True, auto_increment=True)
        name = StringField()
        category = StringField()
        price = NumericField()

    Product().create_table()
    for i in range(n_books):
        Product({"name": f"book{i}", "category": "books", "price": i}).save()
    for i in range(n_music):
        Product({"name": f"song{i}", "category": "music", "price": i}).save()
    return Product, db


# ── the core promise: page is capped, total is the whole filtered set ──────

def test_where_total_is_outside_pagination():
    Product, db = _seed()
    try:
        rows = Product.where("category = ?", ["books"], limit=20, offset=40)
        assert isinstance(rows, ModelCollection)
        assert isinstance(rows, list)              # non-breaking
        assert len(rows) == 20                       # the page
        assert rows.get_total_records() == 250       # the whole matching set
    finally:
        db.close()


def test_all_carries_table_total():
    Product, db = _seed()
    try:
        rows = Product.all(limit=10)
        assert len(rows) == 10
        assert rows.get_total_records() == 257       # 250 books + 7 music
    finally:
        db.close()


def test_select_carries_total():
    Product, db = _seed()
    try:
        rows = Product.select("SELECT * FROM product WHERE category = ?", ["music"], limit=5)
        assert len(rows) == 5
        assert rows.get_total_records() == 7
    finally:
        db.close()


def test_find_filter_form_carries_total():
    Product, db = _seed()
    try:
        rows = Product.find({"category": "books"}, limit=10)
        assert isinstance(rows, ModelCollection)
        assert len(rows) == 10
        assert rows.get_total_records() == 250
    finally:
        db.close()


def test_find_pk_form_still_returns_single():
    Product, db = _seed()
    try:
        one = Product.find(1)
        assert one is not None
        assert not isinstance(one, ModelCollection)   # PK lookup is a single model
        assert one.id == 1
    finally:
        db.close()


# ── to_paginate() — the uniform seven-key envelope ─────────────────────────

def test_to_paginate_envelope_matches_databaseresult():
    Product, db = _seed()
    try:
        rows = Product.where("category = ?", ["books"], limit=20, offset=40)
        page = rows.to_paginate()
        assert set(page.keys()) == {
            "records", "total", "page", "per_page", "total_pages", "limit", "offset",
        }
        assert page["total"] == 250
        assert page["per_page"] == 20
        assert page["page"] == 3               # offset 40 / 20 + 1
        assert page["total_pages"] == 13       # ceil(250 / 20)
        assert page["offset"] == 40
        assert len(page["records"]) == 20

        # records are dicts, identical shape to db.fetch(...).to_paginate()
        raw = db.fetch("SELECT * FROM product WHERE category = ?", ["books"],
                       limit=20, offset=40).to_paginate()
        assert page["total"] == raw["total"]
        assert page["total_pages"] == raw["total_pages"]
        assert isinstance(page["records"][0], dict)
        assert set(page["records"][0].keys()) == set(raw["records"][0].keys())
    finally:
        db.close()


# ── edge cases ─────────────────────────────────────────────────────────────

def test_empty_page_still_reports_total():
    Product, db = _seed()
    try:
        # Offset past the end: no rows on this page, but the total still stands.
        rows = Product.where("category = ?", ["books"], limit=20, offset=1000)
        assert len(rows) == 0
        assert rows.get_total_records() == 250
        assert rows.to_paginate()["total"] == 250
    finally:
        db.close()


def test_zero_matches_total_is_zero():
    Product, db = _seed()
    try:
        rows = Product.where("category = ?", ["nothing"])
        assert list(rows) == []
        assert rows.get_total_records() == 0
    finally:
        db.close()


def test_soft_delete_excluded_from_total():
    db = Database("sqlite:///:memory:")
    bind_database(db)

    class Note(ORM):
        soft_delete = True
        id = IntegerField(primary_key=True, auto_increment=True)
        body = StringField()

    Note().create_table()
    try:
        for i in range(5):
            Note({"body": f"n{i}"}).save()
        Note.find(1).delete()                       # soft-delete one

        live = Note.where("1=1")
        assert live.get_total_records() == 4         # deleted row excluded

        trashed = Note.with_trashed("1=1")
        assert trashed.get_total_records() == 5      # deleted row included
    finally:
        db.close()


# ── list compatibility (nothing existing breaks) ───────────────────────────

def test_list_operations_unchanged():
    Product, db = _seed(n_books=3, n_music=0)
    try:
        rows = Product.where("category = ?", ["books"])
        assert len(rows) == 3
        assert rows[0].category == "books"           # index -> model instance
        assert [p.category for p in rows] == ["books"] * 3   # iterate
        assert len(rows[1:]) == 2                     # slice
        assert all(isinstance(p, Product) for p in rows)
    finally:
        db.close()
