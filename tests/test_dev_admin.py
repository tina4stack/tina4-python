# Tests for tina4_python.dev_admin
import pytest
import json
import tempfile
import os
from tina4_python.dev_admin import (
    MessageLog, RequestInspector, BrokenTracker,
    get_api_handlers,
)


class TestMessageLog:
    def setup_method(self):
        MessageLog.clear()

    def test_log_and_get(self):
        MessageLog.log("queue", "Job processed", {"job_id": 1})
        msgs = MessageLog.get()
        assert len(msgs) == 1
        assert msgs[0]["category"] == "queue"
        assert msgs[0]["message"] == "Job processed"
        assert msgs[0]["data"]["job_id"] == 1

    def test_log_levels(self):
        MessageLog.log("auth", "Login failed", level="error")
        MessageLog.log("auth", "Login success", level="info")
        errors = MessageLog.get(level="error")
        assert len(errors) == 1
        assert errors[0]["level"] == "error"

    def test_filter_by_category(self):
        MessageLog.log("queue", "Job 1")
        MessageLog.log("email", "Sent")
        MessageLog.log("queue", "Job 2")
        queue_msgs = MessageLog.get(category="queue")
        assert len(queue_msgs) == 2
        email_msgs = MessageLog.get(category="email")
        assert len(email_msgs) == 1

    def test_newest_first(self):
        MessageLog.log("test", "First")
        MessageLog.log("test", "Second")
        msgs = MessageLog.get()
        assert msgs[0]["message"] == "Second"

    def test_limit(self):
        for i in range(20):
            MessageLog.log("test", f"Message {i}")
        msgs = MessageLog.get(limit=5)
        assert len(msgs) == 5

    def test_clear_all(self):
        MessageLog.log("a", "One")
        MessageLog.log("b", "Two")
        MessageLog.clear()
        assert len(MessageLog.get()) == 0

    def test_clear_by_category(self):
        MessageLog.log("keep", "Stay")
        MessageLog.log("remove", "Go")
        MessageLog.clear(category="remove")
        msgs = MessageLog.get()
        assert len(msgs) == 1
        assert msgs[0]["category"] == "keep"

    def test_count(self):
        MessageLog.log("queue", "A")
        MessageLog.log("queue", "B")
        MessageLog.log("email", "C")
        counts = MessageLog.count()
        assert counts["queue"] == 2
        assert counts["email"] == 1
        assert counts["total"] == 3

    def test_max_messages_trimmed(self):
        MessageLog._max_messages = 10
        for i in range(20):
            MessageLog.log("test", f"Msg {i}")
        assert len(MessageLog._messages) <= 10
        MessageLog._max_messages = 500  # Reset

    def test_message_structure(self):
        MessageLog.log("test", "Hello", {"key": "val"}, level="warn")
        msg = MessageLog.get()[0]
        assert "id" in msg
        assert "timestamp" in msg
        assert msg["category"] == "test"
        assert msg["level"] == "warn"
        assert msg["message"] == "Hello"
        assert msg["data"] == {"key": "val"}


class TestRequestInspector:
    def setup_method(self):
        RequestInspector.clear()

    def test_capture_and_get(self):
        RequestInspector.capture("GET", "/api/test", 200, 12.5)
        reqs = RequestInspector.get()
        assert len(reqs) == 1
        assert reqs[0]["method"] == "GET"
        assert reqs[0]["path"] == "/api/test"
        assert reqs[0]["status"] == 200
        assert reqs[0]["duration_ms"] == 12.5

    def test_newest_first(self):
        RequestInspector.capture("GET", "/first", 200, 1.0)
        RequestInspector.capture("POST", "/second", 201, 2.0)
        reqs = RequestInspector.get()
        assert reqs[0]["path"] == "/second"

    def test_filter_by_method(self):
        RequestInspector.capture("GET", "/a", 200, 1.0)
        RequestInspector.capture("POST", "/b", 201, 1.0)
        RequestInspector.capture("GET", "/c", 200, 1.0)
        reqs = RequestInspector.get(method="GET")
        assert len(reqs) == 2

    def test_filter_by_status(self):
        RequestInspector.capture("GET", "/ok", 200, 1.0)
        RequestInspector.capture("GET", "/err", 500, 1.0)
        reqs = RequestInspector.get(status_min=400)
        assert len(reqs) == 1
        assert reqs[0]["status"] == 500

    def test_stats(self):
        RequestInspector.capture("GET", "/a", 200, 10.0)
        RequestInspector.capture("GET", "/b", 500, 20.0)
        stats = RequestInspector.stats()
        assert stats["total"] == 2
        assert stats["avg_ms"] == 15.0
        assert stats["errors"] == 1
        assert stats["slowest_ms"] == 20.0

    def test_stats_empty(self):
        stats = RequestInspector.stats()
        assert stats["total"] == 0
        assert stats["avg_ms"] == 0

    def test_limit(self):
        for i in range(10):
            RequestInspector.capture("GET", f"/p{i}", 200, 1.0)
        reqs = RequestInspector.get(limit=3)
        assert len(reqs) == 3

    def test_clear(self):
        RequestInspector.capture("GET", "/test", 200, 1.0)
        RequestInspector.clear()
        assert len(RequestInspector.get()) == 0

    def test_max_trimmed(self):
        RequestInspector._max_requests = 5
        for i in range(10):
            RequestInspector.capture("GET", f"/p{i}", 200, 1.0)
        assert len(RequestInspector._requests) <= 5
        RequestInspector._max_requests = 200  # Reset


class TestBrokenTracker:
    def setup_method(self):
        self._tmp = tempfile.mkdtemp()
        BrokenTracker._broken_dir = self._tmp

    def teardown_method(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_record_and_get(self):
        BrokenTracker.record("ValueError", "bad input")
        entries = BrokenTracker.get_all()
        assert len(entries) == 1
        assert entries[0]["error_type"] == "ValueError"
        assert entries[0]["message"] == "bad input"
        assert entries[0]["count"] == 1

    def test_dedup_increments_count(self):
        BrokenTracker.record("ValueError", "bad input")
        BrokenTracker.record("ValueError", "bad input")
        entries = BrokenTracker.get_all()
        assert len(entries) == 1
        assert entries[0]["count"] == 2

    def test_different_errors_separate(self):
        BrokenTracker.record("ValueError", "error A")
        BrokenTracker.record("TypeError", "error B")
        entries = BrokenTracker.get_all()
        assert len(entries) == 2

    def test_resolve(self):
        sig = BrokenTracker.record("RuntimeError", "crash")
        result = BrokenTracker.resolve(sig)
        assert result is True
        entries = BrokenTracker.get_all()
        assert entries[0]["resolved"] is True

    def test_resolve_nonexistent(self):
        assert BrokenTracker.resolve("nonexistent") is False

    def test_clear_resolved(self):
        sig1 = BrokenTracker.record("Error", "fixed")
        BrokenTracker.record("Error", "still broken")
        BrokenTracker.resolve(sig1)
        BrokenTracker.clear_resolved()
        entries = BrokenTracker.get_all()
        # Only unresolved remains (the second one has a different sig)
        assert all(not e["resolved"] for e in entries)

    def test_health(self):
        BrokenTracker.record("Error", "one")
        sig = BrokenTracker.record("Error", "two")
        BrokenTracker.resolve(sig)
        health = BrokenTracker.health()
        assert health["total"] == 2
        assert health["unresolved"] == 1
        assert health["resolved"] == 1
        assert health["healthy"] is False

    def test_health_empty(self):
        health = BrokenTracker.health()
        assert health["healthy"] is True
        assert health["total"] == 0

    def test_traceback_stored(self):
        BrokenTracker.record("Error", "msg", traceback_str="line 42\nline 43")
        entry = BrokenTracker.get_all()[0]
        assert "line 42" in entry["traceback"]

    def test_unresolved_count(self):
        BrokenTracker.record("Error", "one")
        sig = BrokenTracker.record("Error", "two")
        BrokenTracker.resolve(sig)
        assert BrokenTracker.unresolved_count() == 1

    def test_unresolved_count_empty(self):
        assert BrokenTracker.unresolved_count() == 0

    def test_clear_all(self):
        BrokenTracker.record("Error", "one")
        BrokenTracker.record("Error", "two")
        BrokenTracker.clear_all()
        assert len(BrokenTracker.get_all()) == 0

    def test_reset(self):
        BrokenTracker.record("Error", "one")
        BrokenTracker.reset()
        assert len(BrokenTracker.get_all()) == 0

    def test_capture_alias(self):
        """capture() delegates to record() with file/line in context."""
        sig = BrokenTracker.capture("TypeError", "bad type", "traceback here", "app.py", 42)
        entries = BrokenTracker.get_all()
        assert len(entries) == 1
        assert entries[0]["error_type"] == "TypeError"
        assert entries[0]["context"]["file"] == "app.py"
        assert entries[0]["context"]["line"] == 42


class TestGetAPIHandlers:
    def test_returns_handlers(self):
        handlers = get_api_handlers()
        assert "/__dev/api/status" in handlers
        assert "/__dev/api/routes" in handlers
        assert "/__dev/api/queue" in handlers
        assert "/__dev/api/mailbox" in handlers
        assert "/__dev/api/messages" in handlers

    def test_new_handlers_present(self):
        handlers = get_api_handlers()
        assert "/__dev/api/queue/replay" in handlers
        assert "/__dev/api/messages/search" in handlers
        assert "/__dev/api/seed" in handlers
        assert "/__dev/api/requests" in handlers
        assert "/__dev/api/broken" in handlers
        assert "/__dev/api/websockets" in handlers
        assert "/__dev/api/system" in handlers
        assert "/__dev/api/chat" in handlers

    def test_handler_methods(self):
        handlers = get_api_handlers()
        method, handler = handlers["/__dev/api/status"]
        assert method == "GET"
        assert callable(handler)

    def test_all_handlers_callable(self):
        handlers = get_api_handlers()
        for path, (method, handler) in handlers.items():
            assert method in ("GET", "POST")
            assert callable(handler)

    def test_post_handlers(self):
        handlers = get_api_handlers()
        post_paths = [p for p, (m, h) in handlers.items() if m == "POST"]
        assert "/__dev/api/queue/retry" in post_paths
        assert "/__dev/api/queue/purge" in post_paths
        assert "/__dev/api/queue/replay" in post_paths
        assert "/__dev/api/mailbox/seed" in post_paths
        assert "/__dev/api/mailbox/clear" in post_paths
        assert "/__dev/api/messages/clear" in post_paths
        assert "/__dev/api/seed" in post_paths
        assert "/__dev/api/chat" in post_paths

    def test_handler_count(self):
        # Sanity check against accidental endpoint additions. Bump
        # this number intentionally when a new /__dev/api route
        # lands so review catches silent growth.
        #
        # Current: 41 base + 13 (file I/O × 6, deps × 2, git × 1,
        #          mcp × 2, scaffold × 2) + 7 (ollama proxy alias,
        #          5 service-health probes, thoughts stub) + 6 (5
        #          supervise/* proxies + /execute) + 5 (docs/search,
        #          docs/class, docs/method, docs/index,
        #          docs/.well-known.json — Live API RAG endpoints
        #          per plan/v3/22-LIVE-API-RAG.md) = 72.
        handlers = get_api_handlers()
        assert len(handlers) == 72

    def test_tables_handler_registered(self):
        handlers = get_api_handlers()
        assert "/__dev/api/tables" in handlers
        method, handler = handlers["/__dev/api/tables"]
        assert method == "GET"

    def test_mtime_handler_registered(self):
        handlers = get_api_handlers()
        assert "/__dev/api/mtime" in handlers
        method, handler = handlers["/__dev/api/mtime"]
        assert method == "GET"

    def test_connections_handler_registered(self):
        handlers = get_api_handlers()
        assert "/__dev/api/connections" in handlers
        method, handler = handlers["/__dev/api/connections"]
        assert method == "GET"

    def test_version_check_handler_registered(self):
        handlers = get_api_handlers()
        assert "/__dev/api/version-check" in handlers
        method, handler = handlers["/__dev/api/version-check"]
        assert method == "GET"


class TestAPIHandlers:
    """Test API handler functions with mock request/response."""

    @pytest.fixture
    def mock_req(self):
        return type("Req", (), {"params": {}, "body": {}})()

    @pytest.fixture
    def mock_resp(self):
        captured = []
        def resp(data, code=200):
            captured.append((data, code))
            return data
        resp.captured = captured
        return resp

    @pytest.mark.asyncio
    async def test_status_handler(self, mock_req, mock_resp, monkeypatch):
        monkeypatch.setenv("TINA4_MAILBOX_DIR", "/tmp/test_mailbox_status")
        from tina4_python.dev_admin import _api_status
        result = await _api_status(mock_req, mock_resp)
        assert "python_version" in result
        assert result["framework"] == "tina4-python v3"
        assert "requests" in result
        assert "health" in result

    @pytest.mark.asyncio
    async def test_messages_handler(self, mock_req, mock_resp):
        MessageLog.clear()
        MessageLog.log("test", "Hello from test")
        from tina4_python.dev_admin import _api_messages
        result = await _api_messages(mock_req, mock_resp)
        assert len(result["messages"]) >= 1

    @pytest.mark.asyncio
    async def test_messages_clear_handler(self, mock_req, mock_resp):
        MessageLog.log("test", "To be cleared")
        from tina4_python.dev_admin import _api_messages_clear
        mock_req.body = {}
        result = await _api_messages_clear(mock_req, mock_resp)
        assert result["cleared"] is True
        assert len(MessageLog.get()) == 0

    @pytest.mark.asyncio
    async def test_messages_search_handler(self, mock_req, mock_resp):
        MessageLog.clear()
        MessageLog.log("test", "Hello world")
        MessageLog.log("test", "Goodbye moon")
        from tina4_python.dev_admin import _api_messages_search
        mock_req.params = {"q": "hello"}
        result = await _api_messages_search(mock_req, mock_resp)
        assert result["count"] == 1
        assert "Hello" in result["messages"][0]["message"]

    @pytest.mark.asyncio
    async def test_messages_search_empty_query(self, mock_req, mock_resp):
        from tina4_python.dev_admin import _api_messages_search
        mock_req.params = {"q": ""}
        result = await _api_messages_search(mock_req, mock_resp)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_requests_handler(self, mock_req, mock_resp):
        RequestInspector.clear()
        RequestInspector.capture("GET", "/test", 200, 5.0)
        from tina4_python.dev_admin import _api_requests
        result = await _api_requests(mock_req, mock_resp)
        assert len(result["requests"]) == 1
        assert result["stats"]["total"] == 1

    @pytest.mark.asyncio
    async def test_requests_clear_handler(self, mock_req, mock_resp):
        RequestInspector.capture("GET", "/test", 200, 5.0)
        from tina4_python.dev_admin import _api_requests_clear
        result = await _api_requests_clear(mock_req, mock_resp)
        assert result["cleared"] is True
        assert len(RequestInspector.get()) == 0

    @pytest.mark.asyncio
    async def test_broken_handler(self, mock_req, mock_resp, tmp_path):
        BrokenTracker._broken_dir = str(tmp_path)
        BrokenTracker.record("TestError", "test message")
        from tina4_python.dev_admin import _api_broken
        result = await _api_broken(mock_req, mock_resp)
        assert len(result["errors"]) == 1
        assert result["health"]["unresolved"] == 1

    @pytest.mark.asyncio
    async def test_broken_resolve_handler(self, mock_req, mock_resp, tmp_path):
        BrokenTracker._broken_dir = str(tmp_path)
        sig = BrokenTracker.record("TestError", "to resolve")
        from tina4_python.dev_admin import _api_broken_resolve
        mock_req.body = {"id": sig}
        result = await _api_broken_resolve(mock_req, mock_resp)
        assert result["resolved"] is True

    @pytest.mark.asyncio
    async def test_system_handler(self, mock_req, mock_resp):
        from tina4_python.dev_admin import _api_system
        result = await _api_system(mock_req, mock_resp)
        assert "python_version" in result
        assert "platform" in result
        assert "uptime_seconds" in result
        assert "pid" in result
        assert result["framework"] == "tina4-python v3"

    @pytest.mark.asyncio
    async def test_chat_handler_empty_message(self, mock_req, mock_resp):
        from tina4_python.dev_admin import _api_chat
        mock_req.body = {"message": ""}
        result = await _api_chat(mock_req, mock_resp)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_chat_backend_unreachable_returns_error_source(self, mock_req, mock_resp, monkeypatch):
        """When the qwen/RAG stack is unreachable, /chat returns source=error
        with a clear message. There is no local / fallback provider — Tina4 is
        the only supported backend (Anthropic/OpenAI branches were removed)."""
        # Point at an unroutable address so urlopen fails fast.
        monkeypatch.setenv("TINA4_AI_URL", "http://127.0.0.1:1/api/chat")
        monkeypatch.setenv("TINA4_RAG_URL", "")
        from tina4_python.dev_admin import _api_chat
        mock_req.body = {"message": "ping"}
        result = await _api_chat(mock_req, mock_resp)
        assert result.get("source") == "error"
        assert "reply" in result
        assert result.get("model") == "qwen2.5-coder:14b"
        assert result.get("rag_hits") == 0

    @pytest.mark.asyncio
    async def test_websockets_handler(self, mock_req, mock_resp):
        from tina4_python.dev_admin import _api_websockets
        result = await _api_websockets(mock_req, mock_resp)
        assert "connections" in result
        assert "count" in result

    @pytest.mark.asyncio
    async def test_status_includes_db_tables(self, mock_req, mock_resp, monkeypatch):
        monkeypatch.setenv("TINA4_MAILBOX_DIR", "/tmp/test_mailbox_db")
        from tina4_python.dev_admin import _api_status
        result = await _api_status(mock_req, mock_resp)
        assert "db_tables" in result
        assert isinstance(result["db_tables"], int)

    @pytest.mark.asyncio
    async def test_query_multi_statement(self, mock_req, mock_resp, tmp_path, monkeypatch):
        """Multi-statement SQL execution runs as a batch."""
        db_path = str(tmp_path / "test.db")
        monkeypatch.setenv("TINA4_DATABASE_URL", f"sqlite:///{db_path}")
        from tina4_python.dev_admin import _api_query
        mock_req.body = {
            "query": "CREATE TABLE test_multi (id INTEGER PRIMARY KEY, name TEXT); INSERT INTO test_multi (id, name) VALUES (1, 'Alice'); INSERT INTO test_multi (id, name) VALUES (2, 'Bob')",
            "type": "sql",
        }
        result = await _api_query(mock_req, mock_resp)
        assert result.get("success") is True
        # Verify data was inserted
        mock_req.body = {"query": "SELECT * FROM test_multi", "type": "sql"}
        result = await _api_query(mock_req, mock_resp)
        assert len(result["rows"]) == 2

    @pytest.mark.asyncio
    async def test_tables_handler(self, mock_req, mock_resp, tmp_path, monkeypatch):
        db_path = str(tmp_path / "test_tables.db")
        monkeypatch.setenv("TINA4_DATABASE_URL", f"sqlite:///{db_path}")
        from tina4_python.database import Database
        db = Database(f"sqlite:///{db_path}")
        db.execute("CREATE TABLE test_tbl (id INTEGER PRIMARY KEY, name TEXT)")
        db.commit()
        db.close()
        from tina4_python.dev_admin import _api_tables
        result = await _api_tables(mock_req, mock_resp)
        assert "tables" in result
        assert isinstance(result["tables"], list)
        assert "test_tbl" in result["tables"]

    @pytest.mark.asyncio
    async def test_tables_handler_no_db(self, mock_req, mock_resp, tmp_path, monkeypatch):
        # Use tmp_path so the (possibly-created) bogus DB lands in a sandboxed
        # tempdir, not in the repo root. The handler should still return an
        # empty/safe result for an un-initialised database.
        db_path = tmp_path / "no_such_dir" / "no_db.db"
        monkeypatch.setenv("TINA4_DATABASE_URL", f"sqlite:///{db_path}")
        from tina4_python.dev_admin import _api_tables
        result = await _api_tables(mock_req, mock_resp)
        assert "tables" in result
        assert isinstance(result["tables"], list)

    @pytest.mark.asyncio
    async def test_mtime_handler(self, mock_req, mock_resp):
        from tina4_python.dev_admin import _api_mtime
        result = await _api_mtime(mock_req, mock_resp)
        assert "mtime" in result
        assert isinstance(result["mtime"], (int, float))

    # ── Hot-reload parity tests ────────────────────────────────────
    # Mirrors tina4-php/tests/DevAdminTest.php, tina4-ruby/spec/dev_admin_spec.rb,
    # tina4-nodejs/test/devAdmin.test.ts. The mtime counter must only
    # advance when POST /__dev/api/reload is called. No filesystem scan.

    @pytest.mark.asyncio
    async def test_hot_reload_mtime_starts_at_zero(self, mock_req, mock_resp):
        from tina4_python import dev_admin
        dev_admin._reload_mtime[0] = 0
        dev_admin._reload_file[0] = ""
        result = await dev_admin._api_mtime(mock_req, mock_resp)
        assert result["mtime"] == 0
        assert result["file"] == ""

    @pytest.mark.asyncio
    async def test_hot_reload_post_bumps_mtime(self, mock_resp):
        import time as _time
        from tina4_python import dev_admin
        dev_admin._reload_mtime[0] = 0
        dev_admin._reload_file[0] = ""

        req = type("Req", (), {"params": {}, "body": {"file": "src/routes/home.py", "type": "reload"}})()
        before = int(_time.time())
        await dev_admin._api_reload(req, mock_resp)
        after = int(_time.time())

        got = await dev_admin._api_mtime(req, mock_resp)
        assert before <= got["mtime"] <= after
        assert got["file"] == "src/routes/home.py"

    @pytest.mark.asyncio
    async def test_hot_reload_does_not_touch_filesystem(self, mock_resp, tmp_path, monkeypatch):
        """Regression: no sentinel file under src/ or .tina4/."""
        from tina4_python import dev_admin
        monkeypatch.chdir(tmp_path)
        (tmp_path / "src").mkdir()
        dev_admin._reload_mtime[0] = 0

        req = type("Req", (), {"params": {}, "body": {"file": "whatever.py"}})()
        await dev_admin._api_reload(req, mock_resp)

        assert not (tmp_path / "src" / ".reload_sentinel").exists()
        assert not (tmp_path / ".tina4" / ".reload_sentinel").exists()

    @pytest.mark.asyncio
    async def test_hot_reload_mtime_is_monotonic(self, mock_resp):
        import time as _time
        from tina4_python import dev_admin
        dev_admin._reload_mtime[0] = 0

        req1 = type("Req", (), {"params": {}, "body": {"file": "a.py"}})()
        req2 = type("Req", (), {"params": {}, "body": {"file": "b.py"}})()

        await dev_admin._api_reload(req1, mock_resp)
        m1 = (await dev_admin._api_mtime(req1, mock_resp))["mtime"]
        _time.sleep(1)
        await dev_admin._api_reload(req2, mock_resp)
        m2 = (await dev_admin._api_mtime(req2, mock_resp))["mtime"]

        assert m2 > m1
        assert (await dev_admin._api_mtime(req2, mock_resp))["file"] == "b.py"

    @pytest.mark.asyncio
    async def test_connections_handler(self, mock_req, mock_resp):
        from tina4_python.dev_admin import _api_connections
        result = await _api_connections(mock_req, mock_resp)
        assert "url" in result
        assert "username" in result
        assert "password" in result

    @pytest.mark.asyncio
    async def test_version_check_handler(self, mock_req, mock_resp):
        from tina4_python.dev_admin import _api_version_check
        result = await _api_version_check(mock_req, mock_resp)
        assert "current" in result
        assert "latest" in result
        assert isinstance(result["current"], str)
        assert isinstance(result["latest"], str)

    @pytest.mark.asyncio
    async def test_query_multi_statement_rollback(self, mock_req, mock_resp, tmp_path, monkeypatch):
        """Failed multi-statement batch rolls back all changes."""
        db_path = str(tmp_path / "test_rollback.db")
        monkeypatch.setenv("TINA4_DATABASE_URL", f"sqlite:///{db_path}")
        from tina4_python.dev_admin import _api_query
        # Create table first
        mock_req.body = {"query": "CREATE TABLE test_rb (id INTEGER PRIMARY KEY, name TEXT)", "type": "sql"}
        await _api_query(mock_req, mock_resp)
        # Try batch with a bad statement — should rollback
        mock_req.body = {
            "query": "INSERT INTO test_rb (id, name) VALUES (1, 'Alice'); INSERT INTO nonexistent (x) VALUES (1)",
            "type": "sql",
        }
        result = await _api_query(mock_req, mock_resp)
        assert "error" in result


class TestSQLiteLimitDedup:
    """SQLite adapter skips LIMIT when SQL already has one."""

    def test_fetch_with_existing_limit(self, tmp_path):
        from tina4_python.database import Database
        db_path = str(tmp_path / "limit_test.db")
        db = Database(f"sqlite:///{db_path}")
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        for i in range(10):
            db.execute(f"INSERT INTO items (id, name) VALUES ({i}, 'item{i}')")
        db.commit()
        # SQL already has LIMIT — should NOT double it
        result = db.fetch("SELECT * FROM items LIMIT 3")
        assert len(result.records) == 3
        db.close()

    def test_fetch_without_limit_adds_default(self, tmp_path):
        from tina4_python.database import Database
        db_path = str(tmp_path / "limit_test2.db")
        db = Database(f"sqlite:///{db_path}")
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        for i in range(30):
            db.execute(f"INSERT INTO items (id, name) VALUES ({i}, 'item{i}')")
        db.commit()
        # No LIMIT in SQL — adapter adds default (100)
        result = db.fetch("SELECT * FROM items")
        assert len(result.records) == 30  # 30 items, all returned (under 100 limit)
        db.close()
