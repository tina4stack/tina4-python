# Tests for tina4_python.messenger.DevMailbox
import pytest
import json
import os
from tina4_python.messenger import DevMailbox, Messenger, create_messenger


class TestDevMailbox:
    @pytest.fixture
    def mailbox(self, tmp_path):
        return DevMailbox(mailbox_dir=str(tmp_path / "mailbox"))

    def test_init_creates_dirs(self, mailbox):
        assert mailbox._outbox_dir.is_dir()
        assert mailbox._inbox_dir.is_dir()

    def test_capture_saves_message(self, mailbox):
        result = mailbox.capture(
            to="user@test.com", subject="Test", body="Hello",
            from_address="dev@test.com"
        )
        assert result["success"] is True
        assert result["dev"] is True
        assert result["message_id"]

        messages = mailbox.inbox()
        assert len(messages) == 1
        assert messages[0]["subject"] == "Test"
        assert messages[0]["type"] == "outbox"

    def test_capture_multiple_recipients(self, mailbox):
        mailbox.capture(
            to=["a@test.com", "b@test.com"], subject="Multi",
            body="Hi", cc=["c@test.com"], bcc=["d@test.com"],
            from_address="dev@test.com"
        )
        msg = mailbox.inbox()[0]
        assert len(msg["to"]) == 2
        assert len(msg["cc"]) == 1

    def test_inbox_sorted_newest_first(self, mailbox):
        import time
        mailbox.capture(to="a@test.com", subject="First", body="1", from_address="dev@test.com")
        time.sleep(0.01)
        mailbox.capture(to="a@test.com", subject="Second", body="2", from_address="dev@test.com")
        messages = mailbox.inbox()
        assert messages[0]["subject"] == "Second"

    def test_inbox_filter_by_folder(self, mailbox):
        mailbox.capture(to="a@test.com", subject="Sent", body="out", from_address="dev@test.com")
        mailbox.seed(2)
        assert len(mailbox.inbox(folder="outbox")) == 1
        assert len(mailbox.inbox(folder="inbox")) == 2
        assert len(mailbox.inbox()) == 3

    def test_read_marks_as_read(self, mailbox):
        result = mailbox.capture(to="a@test.com", subject="Unread", body="test", from_address="dev@test.com")
        msg_id = result["message_id"]
        msg = mailbox.read(msg_id)
        assert msg["read"] is True

    def test_read_nonexistent(self, mailbox):
        assert mailbox.read("nonexistent") == {}

    def test_unread_count(self, mailbox):
        mailbox.capture(to="a@test.com", subject="A", body="1", from_address="dev@test.com")
        mailbox.capture(to="a@test.com", subject="B", body="2", from_address="dev@test.com")
        assert mailbox.unread_count() == 2
        # Read one
        msg_id = mailbox.inbox()[0]["id"]
        mailbox.read(msg_id)
        assert mailbox.unread_count() == 1

    def test_delete(self, mailbox):
        result = mailbox.capture(to="a@test.com", subject="Delete me", body="bye", from_address="dev@test.com")
        assert mailbox.delete(result["message_id"]) is True
        assert len(mailbox.inbox()) == 0

    def test_delete_nonexistent(self, mailbox):
        assert mailbox.delete("nope") is False

    def test_clear_all(self, mailbox):
        mailbox.capture(to="a@test.com", subject="A", body="1", from_address="dev@test.com")
        mailbox.seed(3)
        mailbox.clear()
        assert len(mailbox.inbox()) == 0

    def test_clear_by_folder(self, mailbox):
        mailbox.capture(to="a@test.com", subject="Outbox", body="1", from_address="dev@test.com")
        mailbox.seed(2)
        mailbox.clear(folder="inbox")
        assert len(mailbox.inbox(folder="inbox")) == 0
        assert len(mailbox.inbox(folder="outbox")) == 1

    def test_seed_creates_messages(self, mailbox):
        created = mailbox.seed(5, seed=42)
        assert created == 5
        messages = mailbox.inbox(folder="inbox")
        assert len(messages) == 5
        # Check structure
        msg = messages[0]
        assert "subject" in msg
        assert "from" in msg
        assert msg["type"] == "inbox"

    def test_seed_deterministic(self, tmp_path):
        m1 = DevMailbox(mailbox_dir=str(tmp_path / "m1"))
        m2 = DevMailbox(mailbox_dir=str(tmp_path / "m2"))
        m1.seed(3, seed=42)
        m2.seed(3, seed=42)
        msgs1 = m1.inbox(folder="inbox")
        msgs2 = m2.inbox(folder="inbox")
        # Same subjects (from same seed)
        for a, b in zip(msgs1, msgs2):
            assert a["from"] == b["from"]

    def test_count(self, mailbox):
        mailbox.capture(to="a@test.com", subject="A", body="1", from_address="dev@test.com")
        mailbox.seed(3)
        counts = mailbox.count()
        assert counts["inbox"] == 3
        assert counts["outbox"] == 1
        assert counts["total"] == 4


class TestCreateMessenger:
    def test_dev_mode_intercepts_send(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        monkeypatch.setenv("TINA4_MAILBOX_DIR", str(tmp_path / "mailbox"))
        messenger = create_messenger()
        result = messenger.send(to="user@test.com", subject="Dev Test", body="Hello")
        assert result["success"] is True
        assert result["dev"] is True
        # No SMTP connection was attempted
        assert messenger.dev_mailbox.count()["outbox"] == 1

    def test_prod_mode_uses_real_send(self, monkeypatch):
        monkeypatch.delenv("TINA4_DEBUG", raising=False)
        messenger = create_messenger()
        assert not hasattr(messenger, "dev_mailbox")

    def test_dev_mailbox_html_capture(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        monkeypatch.setenv("TINA4_MAILBOX_DIR", str(tmp_path / "mailbox"))
        messenger = create_messenger()
        messenger.send(
            to="user@test.com", subject="HTML Test",
            body="<h1>Hello</h1>", html=True
        )
        msg = messenger.dev_mailbox.inbox()[0]
        assert msg["html"] is True
        assert "<h1>" in msg["body"]
