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
        sid = session.start("my-session-id")
        assert sid == "my-session-id"

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
