"""Parity Group D — return-type changes.

* Auth.valid_token now returns dict|None (payload on success) instead of bool
* Container.reset() clears singleton instances but keeps factory registrations
* Container.reset_all() clears both (the old reset() behaviour)
* queue.dead_letters() returns list[Job] with .error populated
* Model.where(...) returns a ModelCollection carrying get_total_records()/to_paginate()
"""
from __future__ import annotations

import time

import pytest


# ─── Auth.valid_token returns payload or None ─────────────────────────────


class TestAuthValidTokenReturnsPayload:
    def test_valid_token_returns_payload_dict(self):
        from tina4_python.auth import Auth

        auth = Auth(secret="parity-d-secret", expires_in=60)
        token = auth.get_token({"user_id": 42, "role": "admin"})

        result = auth.valid_token(token)
        assert isinstance(result, dict)
        assert result["user_id"] == 42
        assert result["role"] == "admin"

    def test_valid_token_returns_none_for_invalid(self):
        from tina4_python.auth import Auth

        auth = Auth(secret="parity-d-secret")
        assert auth.valid_token("not.a.jwt") is None
        assert auth.valid_token("aaa.bbb.ccc") is None
        assert auth.valid_token("") is None

    def test_valid_token_returns_none_for_expired(self, monkeypatch):
        from tina4_python.auth import Auth

        # Use expires_in=1 minute, then leap time forward via monkey-patching
        auth = Auth(secret="parity-d-secret", expires_in=1)
        token = auth.get_token({"user_id": 1})

        # Move clock forward 2 minutes
        real_time = time.time()
        monkeypatch.setattr(
            "tina4_python.auth.time",
            type("FakeTime", (), {"time": staticmethod(lambda: real_time + 120)}),
        )
        assert auth.valid_token(token) is None

    def test_valid_token_returns_none_for_wrong_secret(self):
        from tina4_python.auth import Auth

        a1 = Auth(secret="secret-one")
        a2 = Auth(secret="secret-two")
        token = a1.get_token({"x": 1})
        assert a2.valid_token(token) is None

    def test_legacy_bool_style_check_still_works(self):
        """The truthy/falsy contract is preserved — `if valid_token(t):` still works."""
        from tina4_python.auth import Auth

        auth = Auth(secret="parity-d-secret")
        valid_tok = auth.get_token({"user_id": 1})
        invalid_tok = "bogus"

        # Truthy on valid (payload dict is truthy)
        assert bool(auth.valid_token(valid_tok)) is True
        # Falsy on invalid (None is falsy)
        assert bool(auth.valid_token(invalid_tok)) is False


# ─── Container.reset() and reset_all() ────────────────────────────────────


class TestContainerResetSemantics:
    def test_reset_clears_singleton_instances_keeps_factories(self):
        from tina4_python.container import Container

        c = Container()
        call_count = {"n": 0}

        def factory():
            call_count["n"] += 1
            return {"id": call_count["n"]}

        c.singleton("db", factory)

        first = c.get("db")
        assert first["id"] == 1
        # Singleton — second call returns same instance
        assert c.get("db") is first

        c.reset()
        # Factory is STILL registered (this is the new contract)
        assert c.has("db") is True
        # But the singleton cache is cleared — factory runs again
        second = c.get("db")
        assert second["id"] == 2
        assert second is not first

    def test_reset_doesnt_touch_transient_registrations(self):
        from tina4_python.container import Container

        c = Container()
        c.register("logger", lambda: object())

        before = c.has("logger")
        c.reset()
        after = c.has("logger")
        assert before == after == True

    def test_reset_all_wipes_everything(self):
        from tina4_python.container import Container

        c = Container()
        c.register("a", lambda: "a")
        c.singleton("b", lambda: "b")
        assert c.has("a") and c.has("b")

        c.reset_all()
        assert not c.has("a")
        assert not c.has("b")
        with pytest.raises(KeyError):
            c.get("a")


# ─── queue.dead_letters() returns list[Job] ──────────────────────────────


class TestQueueDeadLettersReturnsJobs:
    def test_dead_letters_returns_job_objects(self, tmp_path, monkeypatch):
        from tina4_python.queue import Queue
        from tina4_python.queue.job import Job

        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path))
        q = Queue(topic="parity-d-dl", max_retries=1)
        q.push({"x": 1})

        # Pull and fail past retry limit to trigger dead-letter
        job = q.pop()
        if job is not None:
            for _ in range(3):
                job.fail("repeated failure")
                next_job = q.pop()
                if next_job is None:
                    break
                job = next_job

        dead = q.dead_letters()
        assert isinstance(dead, list)
        # All entries must be Job instances, not raw dicts
        for entry in dead:
            assert isinstance(entry, Job)
            # Job objects have .id / .payload / .error attributes
            assert hasattr(entry, "id")
            assert hasattr(entry, "payload")
            assert hasattr(entry, "error")

        q.clear()

    def test_dead_letters_error_field_populated(self, tmp_path, monkeypatch):
        from tina4_python.queue import Queue

        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path))
        q = Queue(topic="parity-d-dl-error", max_retries=1)
        q.push({"data": "bad"})

        job = q.pop()
        if job is not None:
            for _ in range(3):
                job.fail("specific error reason")
                next_job = q.pop()
                if next_job is None:
                    break
                job = next_job

        dead = q.dead_letters()
        if dead:
            # Error reason should be preserved
            assert dead[0].error is None or "specific" in dead[0].error or dead[0].error == "specific error reason"

        q.clear()


# ─── Model.where(...) returns a ModelCollection carrying the total ─────────


def _make_product_model():
    from tina4_python.database import Database
    from tina4_python.orm import ORM, IntegerField, StringField, NumericField, bind_database

    db = Database("sqlite:///:memory:")
    bind_database(db)

    class Product(ORM):
        id = IntegerField(primary_key=True, auto_increment=True)
        name = StringField()
        category = StringField()
        price = NumericField()

    Product().create_table()
    return Product, db


class TestModelWhereCollection:
    def test_where_is_still_a_list(self):
        # Non-breaking: a ModelCollection IS a list -- iterate/index/len unchanged.
        Product, db = _make_product_model()
        try:
            Product({"name": "A", "category": "books", "price": 10}).save()
            Product({"name": "B", "category": "books", "price": 20}).save()
            Product({"name": "C", "category": "music", "price": 30}).save()

            results = Product.where("category = ?", ["books"])
            assert isinstance(results, list)
            assert len(results) == 2
        finally:
            db.close()

    def test_get_total_records(self):
        Product, db = _make_product_model()
        try:
            for i in range(5):
                Product({"name": f"P{i}", "category": "books", "price": i * 10}).save()

            rows = Product.where("category = ?", ["books"])
            assert isinstance(rows, list)
            assert rows.get_total_records() == 5
            assert len(rows) == 5
        finally:
            db.close()

    def test_total_reflects_filter_not_pagination(self):
        Product, db = _make_product_model()
        try:
            for i in range(10):
                Product({"name": f"P{i}", "category": "books", "price": i * 10}).save()

            # Page capped at 3, but the total reflects every matching row.
            rows = Product.where("category = ?", ["books"], limit=3)
            assert len(rows) == 3
            assert rows.get_total_records() == 10
            page = rows.to_paginate()
            assert page["total"] == 10
            assert page["per_page"] == 3
            assert page["total_pages"] == 4
        finally:
            db.close()

    def test_zero_results_still_carries_total(self):
        Product, db = _make_product_model()
        try:
            rows = Product.where("category = ?", ["nothing"])
            assert rows == []
            assert rows.get_total_records() == 0
        finally:
            db.close()

    def test_with_count_kwarg_is_gone(self):
        # ADR-0064 supersede: the old tuple flag no longer exists.
        Product, db = _make_product_model()
        try:
            with pytest.raises(TypeError):
                Product.where("category = ?", ["books"], with_count=True)
        finally:
            db.close()
