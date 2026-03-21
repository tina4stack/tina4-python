# Tests for tina4_python.dev_admin
import pytest
import json
import tempfile
import os
from tina4_python.dev_admin import (
    MessageLog, RequestInspector, BrokenTracker,
    get_api_handlers, render_dashboard, render_dev_toolbar,
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
        handlers = get_api_handlers()
        assert len(handlers) == 30


class TestRenderDashboard:
    def test_returns_html(self):
        html = render_dashboard()
        assert "<!DOCTYPE html>" in html
        assert "Tina4 Dev Admin" in html

    def test_contains_all_tabs(self):
        html = render_dashboard()
        for tab in ["Routes", "Queue", "Mailbox", "Messages", "Database",
                     "Requests", "Errors", "WS", "System", "Tools", "Tina4"]:
            assert tab in html

    def test_contains_api_calls(self):
        """API calls are now in the external tina4-dev-admin.js file."""
        from pathlib import Path
        js_path = Path(__file__).parent.parent / "tina4_python" / "public" / "js" / "tina4-dev-admin.js"
        js_content = js_path.read_text()
        for api_path in ["/__dev/api/routes", "/__dev/api/queue",
                         "/__dev/api/mailbox", "/__dev/api/messages",
                         "/__dev/api/requests", "/__dev/api/broken",
                         "/__dev/api/websockets", "/__dev/api/system",
                         "/__dev/api/chat", "/__dev/api/seed"]:
            assert api_path in js_content

    def test_no_external_dependencies(self):
        html = render_dashboard()
        assert "cdn." not in html.lower()
        assert "unpkg" not in html.lower()
        assert "jsdelivr" not in html.lower()

    def test_uses_css_variables(self):
        html = render_dashboard()
        assert "<style>" in html
        assert "var(--bg)" in html
        assert "var(--primary)" in html
        assert "var(--surface)" in html
        assert "var(--border)" in html
        assert "var(--text)" in html
        assert "var(--muted)" in html
        assert "var(--success)" in html
        assert "var(--danger)" in html
        assert "var(--warn)" in html

    def test_chat_panel(self):
        html = render_dashboard()
        assert "chat-container" in html
        assert "Tina4" in html
        assert "sendChat" in html

    def test_seed_from_admin(self):
        html = render_dashboard()
        assert "seed-table" in html
        assert "seedTable" in html

    def test_request_inspector(self):
        html = render_dashboard()
        assert "loadRequests" in html
        assert "req-body" in html

    def test_error_tracker(self):
        html = render_dashboard()
        assert "loadErrors" in html
        # resolveError is in the external JS file (dynamic template)
        from pathlib import Path
        js = (Path(__file__).parent.parent / "tina4_python" / "public" / "js" / "tina4-dev-admin.js").read_text()
        assert "resolveError" in js

    def test_system_overview(self):
        html = render_dashboard()
        assert "sys-grid" in html
        # loadSystem is in the external JS file
        from pathlib import Path
        js = (Path(__file__).parent.parent / "tina4_python" / "public" / "js" / "tina4-dev-admin.js").read_text()
        assert "loadSystem" in js

    def test_queue_replay(self):
        """replayJob and queue/replay API are in the external JS file."""
        from pathlib import Path
        js = (Path(__file__).parent.parent / "tina4_python" / "public" / "js" / "tina4-dev-admin.js").read_text()
        assert "replayJob" in js
        assert "/__dev/api/queue/replay" in js

    def test_message_search(self):
        html = render_dashboard()
        assert "searchMessages" in html
        assert "msg-search" in html


class TestDevToolbar:
    def test_returns_toolbar(self):
        toolbar = render_dev_toolbar("GET", "/", "-", "-", 0)
        assert "tina4-dev-toolbar" in toolbar
        assert "/__dev" in toolbar

    def test_no_external_deps(self):
        toolbar = render_dev_toolbar("GET", "/", "-", "-", 0)
        assert "cdn." not in toolbar.lower()

    def test_dev_toolbar_with_context(self):
        toolbar = render_dev_toolbar("POST", "/api/users", "/api/users/{id:int}", "abc123", 5)
        assert "tina4-dev-toolbar" in toolbar
        assert "POST" in toolbar
        assert "/api/users" in toolbar
        assert "abc123" in toolbar
        assert "5 routes" in toolbar
        assert "Python" in toolbar
        assert "/__dev" in toolbar


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
    async def test_chat_handler_no_api_key(self, mock_req, mock_resp, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from tina4_python.dev_admin import _api_chat
        mock_req.body = {"message": "what is a route?"}
        result = await _api_chat(mock_req, mock_resp)
        assert "reply" in result
        assert result["source"] == "local"
        assert "route" in result["reply"].lower()

    @pytest.mark.asyncio
    async def test_chat_handler_empty_message(self, mock_req, mock_resp):
        from tina4_python.dev_admin import _api_chat
        mock_req.body = {"message": ""}
        result = await _api_chat(mock_req, mock_resp)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_chat_fallback_topics(self, mock_req, mock_resp, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from tina4_python.dev_admin import _api_chat
        topics = {
            "how do I use ORM?": "orm",
            "database setup": "database",
            "queue processing": "queue",
            "twig templates": "template",
            "authentication": "auth",
            "write tests": "test",
            "create migration": "migration",
            "seed data": "seed",
            "random question": "tina4",
        }
        for question, expected_word in topics.items():
            mock_req.body = {"message": question}
            result = await _api_chat(mock_req, mock_resp)
            assert expected_word.lower() in result["reply"].lower(), f"Expected '{expected_word}' in response to '{question}'"

    @pytest.mark.asyncio
    async def test_websockets_handler(self, mock_req, mock_resp):
        from tina4_python.dev_admin import _api_websockets
        result = await _api_websockets(mock_req, mock_resp)
        assert "connections" in result
        assert "count" in result
