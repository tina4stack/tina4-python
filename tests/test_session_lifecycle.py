# Tests for session-file lifecycle edge cases (issue #36).
#
# A session file must NOT be created for requests that never write to the
# session (anonymous GET, WebSocket upgrades, etc.).  Creating empty session
# files for every unauthenticated hit wastes disk space and leaks timing
# information about anonymous traffic.
import glob
import os
import tempfile
import pytest
from tina4_python.session import Session, FileSessionHandler


# ── Helpers ──────────────────────────────────────────────────────────────────


def _session_files(session_dir: str) -> set[str]:
    """Return the set of .json files currently in *session_dir*."""
    return set(glob.glob(os.path.join(session_dir, "*.json")))


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestNoSessionFileForAnonymousRequest:
    """A request that never calls session.set() must not create a file."""

    def test_no_file_created_when_session_is_never_written(self, tmp_path):
        """Start + read (no write) + save should NOT create a session file."""
        session_dir = str(tmp_path / "sessions")
        os.makedirs(session_dir, exist_ok=True)

        before = _session_files(session_dir)

        handler = FileSessionHandler(session_dir)
        session = Session(handler=handler, ttl=300)
        # Simulate what the router does on every request:
        # start the session (reads from disk — nothing there yet) …
        session.start()
        # … route handler never writes to session …
        _ = session.get("user_id")  # read-only access, _dirty stays False
        # … save at end of request (lazy — should be a no-op when not dirty)
        session.save()

        after = _session_files(session_dir)
        new_files = after - before

        assert len(new_files) == 0, (
            f"No session file should be created for a read-only anonymous request, "
            f"but these files appeared: {new_files}"
        )

    def test_file_is_created_once_session_is_written(self, tmp_path):
        """Sanity check: a file IS created as soon as the session is written."""
        session_dir = str(tmp_path / "sessions")
        os.makedirs(session_dir, exist_ok=True)

        before = _session_files(session_dir)

        handler = FileSessionHandler(session_dir)
        session = Session(handler=handler, ttl=300)
        session.start()
        session.set("user_id", 42)  # write — _dirty becomes True
        session.save()

        after = _session_files(session_dir)
        new_files = after - before

        assert len(new_files) == 1, (
            f"Exactly one session file should be created after a write, "
            f"but found: {new_files}"
        )

    def test_no_file_created_for_multiple_read_only_requests(self, tmp_path):
        """Multiple back-to-back read-only requests should produce no files."""
        session_dir = str(tmp_path / "sessions")
        os.makedirs(session_dir, exist_ok=True)

        before = _session_files(session_dir)

        for _ in range(5):
            handler = FileSessionHandler(session_dir)
            session = Session(handler=handler, ttl=300)
            session.start()
            _ = session.get("cart")  # read-only
            session.save()

        after = _session_files(session_dir)
        new_files = after - before

        assert len(new_files) == 0, (
            f"No session files should be created across multiple read-only "
            f"requests, but found: {new_files}"
        )


class TestNoSessionFileForWebSocketUpgrade:
    """WebSocket upgrade requests must not create session files.

    WebSocket connections do not follow the normal request/response lifecycle.
    The server upgrades the connection immediately without executing route
    handlers, so the session layer should never be touched.  Even if the
    server does start a session for the handshake, a session that is never
    written must not leave a file on disk.
    """

    def test_no_file_for_simulated_websocket_upgrade_request(self, tmp_path):
        """A WebSocket-upgrade-style request (read-only session) must not create a file."""
        session_dir = str(tmp_path / "sessions")
        os.makedirs(session_dir, exist_ok=True)

        before = _session_files(session_dir)

        # Simulate the session behaviour during a WebSocket upgrade handshake:
        # the framework starts the session to check auth, but the upgrade path
        # never writes to it — so no file should be persisted.
        handler = FileSessionHandler(session_dir)
        session = Session(handler=handler, ttl=300)
        session.start()

        # WebSocket upgrade — only reads (e.g. checking auth token from session)
        _ = session.get("auth_token")
        # Connection is upgraded; session is NOT written

        session.save()  # lazy save — must be a no-op since _dirty is False

        after = _session_files(session_dir)
        new_files = after - before

        assert len(new_files) == 0, (
            f"No session file should be created for a WebSocket upgrade request "
            f"that never writes to the session, but found: {new_files}"
        )

    def test_dirty_flag_is_false_after_read_only_access(self, tmp_path):
        """_dirty must remain False when only get() is called."""
        session_dir = str(tmp_path / "sessions")
        handler = FileSessionHandler(session_dir)
        session = Session(handler=handler, ttl=300)
        session.start()

        assert session._dirty is False, "Session should not be dirty before any writes"

        _ = session.get("anything")

        assert session._dirty is False, (
            "_dirty must remain False after a read-only get() call"
        )

    def test_dirty_flag_is_true_after_write(self, tmp_path):
        """Sanity check: _dirty must become True as soon as set() is called."""
        session_dir = str(tmp_path / "sessions")
        handler = FileSessionHandler(session_dir)
        session = Session(handler=handler, ttl=300)
        session.start()

        session.set("key", "value")

        assert session._dirty is True, "_dirty must be True after set()"


class TestDestroyDoesNotResurrect:
    """destroy() ENDS the session — a later set()+save() must NOT resurrect it.

    The master nulls ``_session_id`` in destroy(), so a subsequent set()/save()
    with NO new start() has no id to persist under and writes nothing. A fresh
    session is only ever started by a new start() that MINTS a new id. This is
    the cross-framework contract; Python is the reference and tina4-php /
    tina4-ruby were re-persisting under the just-destroyed id.
    """

    def test_set_and_save_after_destroy_creates_no_record(self, tmp_path):
        session_dir = str(tmp_path / "sessions")
        os.makedirs(session_dir, exist_ok=True)
        handler = FileSessionHandler(session_dir)

        session = Session(handler=handler, ttl=300)
        old_id = session.start()
        session.set("user_id", 42)
        session.save()
        assert len(_session_files(session_dir)) == 1, (
            "a record must exist after the first write"
        )

        # End the session: the record is removed and the id is cleared.
        session.destroy()
        assert _session_files(session_dir) == set(), (
            "destroy() must remove the stored record"
        )
        assert session.get_session_id() is None, (
            "destroy() must clear the session id so a later save() has no id"
        )

        # A set()+save() with NO new start() must write NO record — the session
        # was ended, and this is exactly the resurrection the PHP/Ruby bug caused.
        session.set("user_id", 99)
        session.save()
        assert _session_files(session_dir) == set(), (
            "set()+save() after destroy() must NOT re-create a record"
        )

        # A FRESH handler reading the OLD id from the SAME backend finds NO data.
        fresh = FileSessionHandler(session_dir)
        assert fresh.read(old_id) == {}, (
            "the destroyed session id must not be readable again — nothing was re-created"
        )

    def test_new_start_after_destroy_mints_a_fresh_id_and_persists(self, tmp_path):
        """Negative control: destroy() is not a permanent gag.

        A NEW start() after destroy() mints a fresh id and that session
        persists normally — proving the no-resurrect rule targets the ENDED
        session, not the Session object.
        """
        session_dir = str(tmp_path / "sessions")
        os.makedirs(session_dir, exist_ok=True)
        handler = FileSessionHandler(session_dir)

        session = Session(handler=handler, ttl=300)
        old_id = session.start()
        session.set("k", "v")
        session.save()
        session.destroy()

        new_id = session.start()
        assert new_id != old_id, "a fresh start() after destroy() mints a NEW id"

        session.set("k", "v2")
        session.save()
        assert len(_session_files(session_dir)) == 1, (
            "the freshly started session persists normally"
        )
        fresh = FileSessionHandler(session_dir)
        assert fresh.read(new_id).get("k") == "v2", (
            "the fresh session is readable under its NEW id"
        )


class TestFlashNoneReadsNotStores:
    """flash(key, None) is the GET sentinel — it READS-and-CLEARS, never STORES None.

    The master keys the mode off ``value is not None`` (SET) vs the None default
    (GET), so flash(key, None) returns the pending value and removes it. This is
    the cross-framework contract; tina4-nodejs used ``value !== undefined`` and so
    STORED null. Python is the reference.
    """

    def test_flash_none_reads_and_clears_and_does_not_store_none(self, tmp_path):
        session_dir = str(tmp_path / "sessions")
        os.makedirs(session_dir, exist_ok=True)
        handler = FileSessionHandler(session_dir)

        session = Session(handler=handler, ttl=300)
        session.start()

        session.flash("message", "Saved!")  # set (value is not None)
        assert session.has("_flash_message"), "flash set must store the value"

        # GET sentinel: None reads the pending value AND clears it.
        first = session.flash("message", None)
        assert first == "Saved!", "flash(key, None) must READ the pending value"
        assert not session.has("_flash_message"), (
            "flash(key, None) must CLEAR the key — it must never STORE None"
        )

        # A second read is empty — the value was consumed, not re-stored as None.
        second = session.flash("message", None)
        assert second is None, "a second flash read is empty"
