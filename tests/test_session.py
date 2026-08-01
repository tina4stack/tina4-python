# Tests for tina4_python.session
import time
import pytest
from tina4_python.session import Session, FileSessionHandler, DatabaseSessionHandler
from tina4_python.database import Database


@pytest.fixture
def session(tmp_path):
    handler = FileSessionHandler(str(tmp_path / "sessions"))
    return Session(handler=handler, ttl=300)


# ── File Session Tests ─────────────────────────────────────────


class TestFileSession:
    def test_start_generates_id(self, session):
        sid = session.start()
        assert sid is not None
        assert len(sid) > 10

    def test_start_with_id(self, session):
        # 3.13.95 (ADR-0021): strict mode. start() adopts a supplied id only
        # when the store already holds that session -- adopting an unknown id is
        # session fixation. A KNOWN id still resumes under its own id.
        session._handler.write("my-session-id", {"seeded": 1}, 300)
        sid = session.start("my-session-id")
        assert sid == "my-session-id"
        assert session.get("seeded") == 1

    def test_start_with_unknown_id_mints_a_fresh_one(self, session):
        # The negative half: an id the store has never seen is never adopted.
        sid = session.start("never-issued-by-us")
        assert sid != "never-issued-by-us"

    def test_set_and_get(self, session):
        session.start()
        session.set("user_id", 42)
        assert session.get("user_id") == 42

    def test_get_missing_key(self, session):
        session.start()
        assert session.get("nope") is None
        assert session.get("nope", "default") == "default"

    def test_has(self, session):
        session.start()
        session.set("key", "val")
        assert session.has("key") is True
        assert session.has("nope") is False

    def test_unset(self, session):
        session.start()
        session.set("key", "val")
        session.unset("key")
        assert session.get("key") is None

    def test_all(self, session):
        session.start()
        session.set("a", 1)
        session.set("b", 2)
        assert session.all() == {"a": 1, "b": 2}

    def test_clear(self, session):
        session.start()
        session.set("a", 1)
        session.clear()
        assert session.all() == {}

    def test_save_and_resume(self, tmp_path):
        handler = FileSessionHandler(str(tmp_path / "sessions"))
        s1 = Session(handler=handler, ttl=300)
        sid = s1.start()
        s1.set("name", "Alice")
        s1.save()

        s2 = Session(handler=handler, ttl=300)
        s2.start(sid)
        assert s2.get("name") == "Alice"

    def test_destroy(self, tmp_path):
        handler = FileSessionHandler(str(tmp_path / "sessions"))
        s = Session(handler=handler, ttl=300)
        sid = s.start()
        s.set("key", "val")
        s.save()
        s.destroy()

        s2 = Session(handler=handler, ttl=300)
        s2.start(sid)
        assert s2.get("key") is None

    def test_regenerate(self, session):
        old_id = session.start()
        session.set("key", "val")
        new_id = session.regenerate()
        assert new_id != old_id
        assert session.get("key") == "val"

    def test_flash(self, session):
        session.start()
        session.flash("message", "Hello!")
        assert session.flash("message") == "Hello!"
        assert session.flash("message") is None  # Gone after first read

    def test_expired_session(self, tmp_path):
        handler = FileSessionHandler(str(tmp_path / "sessions"))
        s = Session(handler=handler, ttl=1)
        sid = s.start()
        s.set("key", "val")
        s.save()

        time.sleep(1.1)

        s2 = Session(handler=handler, ttl=1)
        s2.start(sid)
        assert s2.get("key") is None  # Expired


class TestFileSessionNegative:
    def test_empty_session(self, session):
        session.start()
        assert session.all() == {}

    def test_save_without_changes(self, session):
        session.start()
        session.save()  # Should not error


# ── Database Session Tests ─────────────────────────────────────


class TestDatabaseSession:
    @pytest.fixture
    def db_session(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'session.db'}")
        handler = DatabaseSessionHandler(db)
        s = Session(handler=handler, ttl=300)
        yield s
        db.close()

    def test_set_and_get(self, db_session):
        db_session.start()
        db_session.set("user_id", 1)
        db_session.save()
        assert db_session.get("user_id") == 1

    def test_persist_and_resume(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'session.db'}")
        handler = DatabaseSessionHandler(db)

        s1 = Session(handler=handler, ttl=300)
        sid = s1.start()
        s1.set("role", "admin")
        s1.save()

        s2 = Session(handler=handler, ttl=300)
        s2.start(sid)
        assert s2.get("role") == "admin"
        db.close()

    def test_destroy(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'session.db'}")
        handler = DatabaseSessionHandler(db)
        s = Session(handler=handler, ttl=300)
        sid = s.start()
        s.set("key", "val")
        s.save()
        s.destroy()

        s2 = Session(handler=handler, ttl=300)
        s2.start(sid)
        assert s2.get("key") is None
        db.close()

    def test_update_existing(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'session.db'}")
        handler = DatabaseSessionHandler(db)
        s = Session(handler=handler, ttl=300)
        sid = s.start()
        s.set("count", 1)
        s.save()

        s.set("count", 2)
        s.save()

        s2 = Session(handler=handler, ttl=300)
        s2.start(sid)
        assert s2.get("count") == 2
        db.close()


# ── Session ID Tests ──────────────────────────────────────────


class TestSessionId:
    def test_session_id_property(self, session):
        sid = session.start()
        assert session.session_id == sid

    def test_session_id_none_before_start(self, tmp_path):
        handler = FileSessionHandler(str(tmp_path / "sessions"))
        s = Session(handler=handler, ttl=300)
        assert s.session_id is None

    def test_session_id_none_after_destroy(self, session):
        session.start()
        session.destroy()
        assert session.session_id is None

    def test_start_generates_unique_ids(self, tmp_path):
        handler = FileSessionHandler(str(tmp_path / "sessions"))
        ids = set()
        for _ in range(20):
            s = Session(handler=handler, ttl=300)
            sid = s.start()
            ids.add(sid)
        assert len(ids) == 20


# ── Data Type Tests ───────────────────────────────────────────


class TestSessionDataTypes:
    def test_string_value(self, session):
        session.start()
        session.set("key", "hello")
        assert session.get("key") == "hello"

    def test_integer_value(self, session):
        session.start()
        session.set("count", 42)
        assert session.get("count") == 42

    def test_float_value(self, session):
        session.start()
        session.set("price", 19.99)
        assert session.get("price") == 19.99

    def test_boolean_value(self, session):
        session.start()
        session.set("active", True)
        assert session.get("active") is True
        session.set("active", False)
        assert session.get("active") is False

    def test_list_value(self, session):
        session.start()
        session.set("items", [1, 2, 3])
        assert session.get("items") == [1, 2, 3]

    def test_dict_value(self, session):
        session.start()
        session.set("user", {"name": "Alice", "age": 30})
        assert session.get("user") == {"name": "Alice", "age": 30}

    def test_none_value(self, session):
        session.start()
        session.set("empty", None)
        assert session.get("empty") is None


# ── Multiple Key Operations ───────────────────────────────────


class TestSessionMultipleKeys:
    def test_set_multiple_keys(self, session):
        session.start()
        session.set("a", 1)
        session.set("b", 2)
        session.set("c", 3)
        assert session.get("a") == 1
        assert session.get("b") == 2
        assert session.get("c") == 3

    def test_overwrite_key(self, session):
        session.start()
        session.set("key", "original")
        session.set("key", "updated")
        assert session.get("key") == "updated"

    def test_unset_leaves_other_keys(self, session):
        session.start()
        session.set("keep", "yes")
        session.set("remove", "no")
        session.unset("remove")
        assert session.get("keep") == "yes"
        assert session.get("remove") is None

    def test_clear_removes_all(self, session):
        session.start()
        session.set("a", 1)
        session.set("b", 2)
        session.set("c", 3)
        session.clear()
        assert session.all() == {}
        assert session.get("a") is None
        assert session.get("b") is None


# ── Flash Advanced ────────────────────────────────────────────


class TestFlashAdvanced:
    def test_flash_multiple_keys(self, session):
        session.start()
        session.flash("msg1", "Hello")
        session.flash("msg2", "World")
        assert session.flash("msg1") == "Hello"
        assert session.flash("msg2") == "World"

    def test_flash_does_not_appear_in_all(self, session):
        session.start()
        session.flash("notice", "test")
        data = session.all()
        # Flash keys use _flash_ prefix internally
        public_keys = [k for k in data if not k.startswith("_flash_")]
        assert len(public_keys) == 0 or "notice" not in public_keys

    def test_flash_returns_none_when_not_set(self, session):
        session.start()
        assert session.flash("nonexistent") is None


# ── Garbage Collection ────────────────────────────────────────


class TestGarbageCollection:
    def test_gc_file_handler(self, tmp_path):
        handler = FileSessionHandler(str(tmp_path / "gc_sessions"))
        s = Session(handler=handler, ttl=1)
        sid = s.start()
        s.set("key", "val")
        s.save()

        time.sleep(1.1)

        # GC should clean up expired sessions
        s.gc()
        s2 = Session(handler=handler, ttl=1)
        s2.start(sid)
        assert s2.get("key") is None

    def test_gc_db_handler(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'gc.db'}")
        handler = DatabaseSessionHandler(db)
        s = Session(handler=handler, ttl=1)
        sid = s.start()
        s.set("temp", "data")
        s.save()

        time.sleep(1.1)

        s.gc()
        s2 = Session(handler=handler, ttl=1)
        s2.start(sid)
        assert s2.get("temp") is None
        db.close()


# ── Database Session Advanced ─────────────────────────────────


class TestDatabaseSessionAdvanced:
    def test_db_has_key(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'has.db'}")
        handler = DatabaseSessionHandler(db)
        s = Session(handler=handler, ttl=300)
        s.start()
        s.set("exists", True)
        s.save()
        assert s.has("exists") is True
        assert s.has("nope") is False
        db.close()

    def test_db_unset(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'unset.db'}")
        handler = DatabaseSessionHandler(db)
        s = Session(handler=handler, ttl=300)
        s.start()
        s.set("remove_me", "value")
        s.save()
        s.unset("remove_me")
        s.save()
        assert s.get("remove_me") is None
        db.close()

    def test_db_clear(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'clear.db'}")
        handler = DatabaseSessionHandler(db)
        s = Session(handler=handler, ttl=300)
        s.start()
        s.set("a", 1)
        s.set("b", 2)
        s.save()
        s.clear()
        s.save()
        assert s.all() == {}
        db.close()

    def test_db_regenerate(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'regen.db'}")
        handler = DatabaseSessionHandler(db)
        s = Session(handler=handler, ttl=300)
        old_id = s.start()
        s.set("data", "keep")
        s.save()
        new_id = s.regenerate()
        assert new_id != old_id
        assert s.get("data") == "keep"
        db.close()

    def test_db_flash(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'flash.db'}")
        handler = DatabaseSessionHandler(db)
        s = Session(handler=handler, ttl=300)
        s.start()
        s.flash("notice", "Saved!")
        assert s.flash("notice") == "Saved!"
        assert s.flash("notice") is None
        db.close()

    def test_db_all(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'all.db'}")
        handler = DatabaseSessionHandler(db)
        s = Session(handler=handler, ttl=300)
        s.start()
        s.set("x", 10)
        s.set("y", 20)
        s.save()
        data = s.all()
        assert data["x"] == 10
        assert data["y"] == 20
        db.close()


# ── Dirty Flag / Save Behavior ────────────────────────────────


class TestSessionDirtyFlag:
    def test_save_only_writes_when_dirty(self, session):
        session.start()
        # Save without changes should be a no-op (no error)
        session.save()

    def test_set_marks_dirty(self, session):
        session.start()
        assert session._dirty is False
        session.set("key", "val")
        assert session._dirty is True

    def test_save_clears_dirty(self, session):
        session.start()
        session.set("key", "val")
        session.save()
        assert session._dirty is False

    def test_unset_marks_dirty(self, session):
        session.start()
        session.set("key", "val")
        session.save()
        session.unset("key")
        assert session._dirty is True

    def test_clear_marks_dirty(self, session):
        session.start()
        session.set("key", "val")
        session.save()
        session.clear()
        assert session._dirty is True


# ── Falsy-value read contract (cross-framework) ───────────────


class TestSessionGetFalsyContract:
    """``get(key, default)`` must tell a STORED falsy value apart from an ABSENT key.

    This is the shared cross-framework contract test. The same wording is used
    in tina4-python, tina4-php, tina4-ruby and tina4-nodejs so the contract is
    greppable across all four repos:

        "session get returns a stored false instead of the default"

    Ruby's ``Session#get`` used ``@data[key.to_s] || default``, and ``||``
    yields the caller's default for ANY falsy stored value — so a legitimately
    stored ``false`` read back as ``true`` whenever the caller passed ``true``
    as the default, even though the key really was set. Python already uses
    ``dict.get(key, default)``, which keys off PRESENCE rather than truthiness
    and is correct. This test pins that, so the ``or default`` shape can never
    creep in here.

    Real ``FileSessionHandler``, real temp directory, real JSON on disk, real
    save/resume round-trip through the handler. No doubles.
    """

    def test_session_get_returns_a_stored_false_instead_of_the_default(self, tmp_path):
        store = tmp_path / "falsy_sessions"
        handler = FileSessionHandler(str(store))

        s = Session(handler=handler, ttl=300)
        sid = s.start("falsy-contract")
        s.set("flag", False)

        # POSITIVE — a stored False reads back as False, not as the default.
        assert s.get("flag", True) is False
        assert s.get("flag", "fallback") is False
        assert s.get("flag") is False
        assert s.has("flag") is True

        # ...and it survives a real write to disk and a real resume.
        assert s.save() is True
        assert list(store.glob("*.json")), "handler wrote no session file"

        resumed = Session(handler=handler, ttl=300)
        resumed.start(sid)
        assert resumed.get("flag", True) is False
        assert resumed.has("flag") is True

        # NEGATIVE CONTROL — an ABSENT key STILL returns the default. Without
        # this half, a "fix" that simply never returns the default would pass,
        # which would be a worse bug than the one being closed.
        assert resumed.get("absent", True) is True
        assert resumed.get("absent", "fallback") == "fallback"
        assert resumed.get("absent") is None
        assert resumed.has("absent") is False
