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
