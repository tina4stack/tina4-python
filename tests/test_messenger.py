# Tests for tina4_python.messenger
import pytest
from unittest.mock import patch, MagicMock
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from tina4_python.messenger import Messenger, MessengerError


class TestMessengerInit:
    def test_default_config(self):
        m = Messenger()
        assert m.host == "localhost"
        assert m.port == 587
        assert m.use_tls is True

    def test_custom_config(self):
        m = Messenger(host="smtp.test.com", port=465, username="user", password="pass")
        assert m.host == "smtp.test.com"
        assert m.port == 465

    def test_env_config(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "env.host.com")
        monkeypatch.setenv("SMTP_PORT", "2525")
        monkeypatch.setenv("SMTP_USERNAME", "envuser")
        monkeypatch.setenv("SMTP_FROM", "from@test.com")
        m = Messenger()
        assert m.host == "env.host.com"
        assert m.port == 2525
        assert m.username == "envuser"
        assert m.from_address == "from@test.com"


class TestMessengerHeaders:
    def test_add_default_header(self):
        m = Messenger()
        m.add_header("X-Mailer", "Tina4")
        assert m._default_headers["X-Mailer"] == "Tina4"


class TestMessengerSend:
    @patch("tina4_python.messenger.smtplib.SMTP")
    def test_send_plain_text(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        m = Messenger(host="localhost", port=587, use_tls=True)
        result = m.send(to="user@test.com", subject="Test", body="Hello")

        assert result["success"] is True
        assert result["error"] is None
        mock_server.starttls.assert_called_once()
        mock_server.sendmail.assert_called_once()

    @patch("tina4_python.messenger.smtplib.SMTP")
    def test_send_html(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        m = Messenger(host="localhost", port=587)
        result = m.send(to="user@test.com", subject="Test", body="<h1>Hi</h1>", html=True)
        assert result["success"] is True

        # Verify HTML content type in the sent message
        call_args = mock_server.sendmail.call_args
        msg_str = call_args[0][2]
        assert "text/html" in msg_str

    @patch("tina4_python.messenger.smtplib.SMTP")
    def test_send_with_cc_bcc(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        m = Messenger(host="localhost", port=587)
        result = m.send(
            to="user@test.com",
            subject="Test",
            body="Hello",
            cc="cc@test.com",
            bcc=["bcc1@test.com", "bcc2@test.com"],
        )
        assert result["success"] is True
        recipients = mock_server.sendmail.call_args[0][1]
        assert "user@test.com" in recipients
        assert "cc@test.com" in recipients
        assert "bcc1@test.com" in recipients
        assert "bcc2@test.com" in recipients

    @patch("tina4_python.messenger.smtplib.SMTP")
    def test_send_with_reply_to(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        m = Messenger(host="localhost", port=587)
        result = m.send(to="user@test.com", subject="Test", body="Hi", reply_to="reply@test.com")
        assert result["success"] is True
        msg_str = mock_server.sendmail.call_args[0][2]
        assert "Reply-To: reply@test.com" in msg_str

    @patch("tina4_python.messenger.smtplib.SMTP")
    def test_send_with_multiple_to(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        m = Messenger(host="localhost", port=587)
        result = m.send(to=["a@test.com", "b@test.com"], subject="Test", body="Hi")
        assert result["success"] is True

    @patch("tina4_python.messenger.smtplib.SMTP_SSL")
    def test_send_ssl(self, mock_smtp_ssl_cls):
        mock_server = MagicMock()
        mock_smtp_ssl_cls.return_value = mock_server

        m = Messenger(host="smtp.test.com", port=465)
        result = m.send(to="user@test.com", subject="SSL Test", body="Hi")
        assert result["success"] is True
        mock_smtp_ssl_cls.assert_called_once_with("smtp.test.com", 465, timeout=30)

    @patch("tina4_python.messenger.smtplib.SMTP")
    def test_send_with_auth(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        m = Messenger(host="localhost", port=587, username="user", password="pass")
        m.send(to="user@test.com", subject="Test", body="Hi")
        mock_server.login.assert_called_once_with("user", "pass")

    @patch("tina4_python.messenger.smtplib.SMTP")
    def test_send_failure(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_server.sendmail.side_effect = Exception("Connection refused")
        mock_smtp_cls.return_value = mock_server

        m = Messenger(host="localhost", port=587)
        result = m.send(to="user@test.com", subject="Test", body="Hi")
        assert result["success"] is False
        assert "Connection refused" in result["error"]


class TestMessengerAttachments:
    @patch("tina4_python.messenger.smtplib.SMTP")
    def test_dict_attachment(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        m = Messenger(host="localhost", port=587)
        result = m.send(
            to="user@test.com",
            subject="With attachment",
            body="See attached",
            attachments=[{"filename": "test.txt", "content": b"hello world", "mime": "text/plain"}],
        )
        assert result["success"] is True
        msg_str = mock_server.sendmail.call_args[0][2]
        assert "test.txt" in msg_str

    @patch("tina4_python.messenger.smtplib.SMTP")
    def test_file_attachment(self, mock_smtp_cls, tmp_path):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        f = tmp_path / "report.csv"
        f.write_text("a,b,c\n1,2,3")

        m = Messenger(host="localhost", port=587)
        result = m.send(
            to="user@test.com",
            subject="CSV Report",
            body="See attached",
            attachments=[str(f)],
        )
        assert result["success"] is True

    @patch("tina4_python.messenger.smtplib.SMTP")
    def test_missing_file_skipped(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        m = Messenger(host="localhost", port=587)
        result = m.send(
            to="user@test.com",
            subject="Test",
            body="Hi",
            attachments=["/nonexistent/file.pdf"],
        )
        assert result["success"] is True


# ── IMAP (Read) Tests ─────────────────────────────────────────


class TestIMAPConfig:
    def test_default_imap_config(self):
        m = Messenger()
        assert m.imap_host == ""
        assert m.imap_port == 993

    def test_custom_imap_config(self):
        m = Messenger(imap_host="imap.test.com", imap_port=143)
        assert m.imap_host == "imap.test.com"
        assert m.imap_port == 143

    def test_env_imap_config(self, monkeypatch):
        monkeypatch.setenv("IMAP_HOST", "imap.env.com")
        monkeypatch.setenv("IMAP_PORT", "143")
        m = Messenger()
        assert m.imap_host == "imap.env.com"
        assert m.imap_port == 143

    def test_no_imap_host_raises(self):
        m = Messenger()
        with pytest.raises(MessengerError, match="IMAP host not configured"):
            m._imap_connect()


class TestIMAPInbox:
    def _mock_imap(self):
        mock = MagicMock()
        mock.search.return_value = ("OK", [b"1 2 3 4 5"])
        # Build a minimal email header response
        header = (
            b"Subject: Test Email\r\n"
            b"From: sender@test.com\r\n"
            b"To: me@test.com\r\n"
            b"Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
        )
        mock.fetch.return_value = ("OK", [
            (b"1 (FLAGS (\\Seen) BODY[HEADER] {100}", header),
            (b"1 BODY[TEXT]<0.200> {5}", b"Hello"),
            b")",
        ])
        return mock

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_inbox_returns_messages(self, mock_imap_cls):
        mock_conn = self._mock_imap()
        mock_imap_cls.return_value = mock_conn

        m = Messenger(imap_host="imap.test.com", username="user", password="pass")
        messages = m.inbox(limit=3)
        assert isinstance(messages, list)
        mock_conn.select.assert_called_once()

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_inbox_empty_folder(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_conn.search.return_value = ("OK", [b""])
        mock_imap_cls.return_value = mock_conn

        m = Messenger(imap_host="imap.test.com", username="user", password="pass")
        messages = m.inbox()
        assert messages == []

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_unread_count(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_conn.search.return_value = ("OK", [b"1 2 3"])
        mock_imap_cls.return_value = mock_conn

        m = Messenger(imap_host="imap.test.com", username="user", password="pass")
        count = m.unread()
        assert count == 3
        mock_conn.search.assert_called_with(None, "UNSEEN")

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_unread_zero(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_conn.search.return_value = ("OK", [b""])
        mock_imap_cls.return_value = mock_conn

        m = Messenger(imap_host="imap.test.com", username="user", password="pass")
        assert m.unread() == 0


class TestIMAPRead:
    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_read_message(self, mock_imap_cls):
        mock_conn = MagicMock()
        raw_email = (
            b"Subject: Hello World\r\n"
            b"From: alice@test.com\r\n"
            b"To: bob@test.com\r\n"
            b"Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
            b"Content-Type: text/plain\r\n"
            b"\r\n"
            b"This is the body."
        )
        mock_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {100}", raw_email), b")"])
        mock_imap_cls.return_value = mock_conn

        m = Messenger(imap_host="imap.test.com", username="user", password="pass")
        msg = m.read("1")
        assert msg["subject"] == "Hello World"
        assert msg["from"] == "alice@test.com"
        assert "This is the body" in msg["body_text"]

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_read_html_message(self, mock_imap_cls):
        mock_conn = MagicMock()
        raw_email = (
            b"Subject: HTML Test\r\n"
            b"From: alice@test.com\r\n"
            b"To: bob@test.com\r\n"
            b"Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
            b"Content-Type: text/html\r\n"
            b"\r\n"
            b"<h1>Hello</h1>"
        )
        mock_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {100}", raw_email), b")"])
        mock_imap_cls.return_value = mock_conn

        m = Messenger(imap_host="imap.test.com", username="user", password="pass")
        msg = m.read("1")
        assert "<h1>Hello</h1>" in msg["body_html"]

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_read_not_found(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_conn.fetch.return_value = ("NO", [None])
        mock_imap_cls.return_value = mock_conn

        m = Messenger(imap_host="imap.test.com", username="user", password="pass")
        msg = m.read("999")
        assert msg == {}


class TestIMAPSearch:
    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_search_by_subject(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_conn.search.return_value = ("OK", [b"1 2"])
        header = b"Subject: Invoice\r\nFrom: a@t.com\r\nTo: b@t.com\r\nDate: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
        mock_conn.fetch.return_value = ("OK", [
            (b"1 (FLAGS () BODY[HEADER] {50}", header),
            (b"1 BODY[TEXT]<0.200> {3}", b"Hi"),
            b")",
        ])
        mock_imap_cls.return_value = mock_conn

        m = Messenger(imap_host="imap.test.com", username="user", password="pass")
        results = m.search(subject="Invoice")
        mock_conn.search.assert_called_with(None, 'SUBJECT "Invoice"')

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_search_unseen(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_conn.search.return_value = ("OK", [b""])
        mock_imap_cls.return_value = mock_conn

        m = Messenger(imap_host="imap.test.com", username="user", password="pass")
        results = m.search(unseen_only=True)
        mock_conn.search.assert_called_with(None, "UNSEEN")


class TestIMAPActions:
    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_mark_read(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn

        m = Messenger(imap_host="imap.test.com", username="user", password="pass")
        m.mark_read("1")
        mock_conn.store.assert_called_with(b"1", "+FLAGS", "\\Seen")

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_mark_unread(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn

        m = Messenger(imap_host="imap.test.com", username="user", password="pass")
        m.mark_unread("1")
        mock_conn.store.assert_called_with(b"1", "-FLAGS", "\\Seen")

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_delete(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn

        m = Messenger(imap_host="imap.test.com", username="user", password="pass")
        m.delete("1")
        mock_conn.store.assert_called_with(b"1", "+FLAGS", "\\Deleted")
        mock_conn.expunge.assert_called_once()

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_folders(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_conn.list.return_value = ("OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren) "/" "Sent"',
            b'(\\HasNoChildren) "/" "Trash"',
        ])
        mock_imap_cls.return_value = mock_conn

        m = Messenger(imap_host="imap.test.com", username="user", password="pass")
        folders = m.folders()
        assert "INBOX" in folders
        assert "Sent" in folders
        assert "Trash" in folders


class TestTestConnection:
    @patch("tina4_python.messenger.smtplib.SMTP")
    def test_success(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        m = Messenger(host="localhost", port=587)
        result = m.test_connection()
        assert result["success"] is True

    @patch("tina4_python.messenger.smtplib.SMTP")
    def test_failure(self, mock_smtp_cls):
        mock_smtp_cls.side_effect = Exception("Connection refused")

        m = Messenger(host="localhost", port=587)
        result = m.test_connection()
        assert result["success"] is False
        assert "Connection refused" in result["error"]
