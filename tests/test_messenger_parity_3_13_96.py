# Messenger parity locks for 3.13.96 — decisions G2-G10. REAL SMTP/IMAP, no mocks.
"""
Pins the Messenger IMAP-read/SMTP-send parity decisions
(plan/v3/parity-3.13.96-decisions.md):

  G2  read() of a missing UID returns None (not {})           [live: test_messenger.py]
  G3  snippet is decoded, transfer-decoded, tag-stripped, 200-char plain text  [live]
  G4  inbox() item is EXACTLY {uid, subject, from, to, date(ISO-8601), snippet, seen}  [live]
  G5  read() carries body_text/body_html + attachments + headers               [live]
  G6  send() result is {success, message, id} on BOTH paths     [local + live]
  G7  mark_unread / send_template / delete exist under one name  [local + live]
  G8  IMAP uses TINA4_MAIL_IMAP_USERNAME/_PASSWORD, falling back to the SMTP creds  [local + live]
  G9  imap_encryption is a constructor param; explicit beats env (ADR-0041)   [local]
  G10 read methods RAISE on a real connection failure; the capture gate         [local]

Local tests need no service (pure state, a real DevMailbox on the filesystem, or a
REAL connection refusal on a closed port). Live tests hit the same GreenMail the
other real-service suites use and SKIP (never mock) when it is absent.
"""
import os
import socket
import time
import imaplib
import uuid
from datetime import datetime

import pytest

from tina4_python.messenger import (
    Messenger, MessengerConnectionError, create_messenger,
)


# ── GreenMail gating (mirrors tests/test_messenger.py) ───────────
_SMTP_HOST, _SMTP_PORT = (
    os.environ.get("TINA4_TEST_SMTP_HOST", "127.0.0.1"),
    int(os.environ.get("TINA4_TEST_SMTP_PORT", "3025")),
)
_IMAP_HOST, _IMAP_PORT = (
    os.environ.get("TINA4_TEST_IMAP_HOST", "127.0.0.1"),
    int(os.environ.get("TINA4_TEST_IMAP_PORT", "3143")),
)
_CLOSED_HOST, _CLOSED_PORT = "127.0.0.1", 59999


def _reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_greenmail_up = _reachable(_SMTP_HOST, _SMTP_PORT) and _reachable(_IMAP_HOST, _IMAP_PORT)
_requires_greenmail = pytest.mark.skipif(
    not _greenmail_up, reason="GreenMail SMTP/IMAP not reachable"
)


def _plain_messenger(address: str, imap_username: str = None,
                     imap_password: str = None) -> Messenger:
    m = Messenger(
        host=_SMTP_HOST, port=_SMTP_PORT, encryption="none",
        from_address="sender@greenmail.local",
        imap_host=_IMAP_HOST, imap_port=_IMAP_PORT,
        username=address, password="greenmail-password",
        imap_username=imap_username, imap_password=imap_password,
    )
    m.imap_encryption = "none"
    return m


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}@greenmail.local"


def _closed_reader() -> Messenger:
    """A messenger whose IMAP points at a port nothing listens on — every read
    hits a REAL connection refusal (no simulated exception)."""
    m = Messenger(
        imap_host=_CLOSED_HOST, imap_port=_CLOSED_PORT,
        username="user", password="pass",
    )
    m.imap_encryption = "none"
    return m


def _wait_for(m: Messenger, subject: str, attempts: int = 60, delay: float = 0.25) -> dict:
    for _ in range(attempts):
        results = m.search(subject=subject)
        if results:
            return m.read(results[0]["uid"])
        time.sleep(delay)
    raise AssertionError(f"{subject!r} never arrived for {m.imap_username}")


def _wait_item(m: Messenger, subject: str, attempts: int = 60, delay: float = 0.25) -> dict:
    """Wait for the message and return its inbox() LISTING item (not the full read)."""
    for _ in range(attempts):
        for item in m.inbox(limit=50):
            if item["subject"] == subject:
                return item
        time.sleep(delay)
    raise AssertionError(f"{subject!r} never listed for {m.imap_username}")


# ══════════════════════════════════════════════════════════════════
# LOCAL — no live service
# ══════════════════════════════════════════════════════════════════


class TestG6SendResultShapeLocal:
    """G6 — {success, message, id} on BOTH paths; no error/message_id/dev keys."""

    def test_capture_path_shape(self, monkeypatch, tmp_path):
        # No SMTP host configured -> the send is captured to a DevMailbox.
        monkeypatch.delenv("TINA4_MAIL_HOST", raising=False)
        monkeypatch.delenv("TINA4_MAIL_CAPTURE", raising=False)
        monkeypatch.setenv("TINA4_MAILBOX_DIR", str(tmp_path / "mailbox"))
        m = create_messenger()
        result = m.send(to="a@b.com", subject="hi", body="body")
        assert set(result.keys()) == {"success", "message", "id"}
        assert result["success"] is True
        assert result["message"] is None
        assert result["id"]                       # local capture id
        # The renamed/removed keys must be gone.
        assert "error" not in result
        assert "message_id" not in result
        assert "dev" not in result

    def test_failure_path_shape_real_closed_port(self):
        # REAL connection refusal on send (no mock side_effect).
        m = Messenger(host=_CLOSED_HOST, port=_CLOSED_PORT, encryption="none")
        result = m.send(to="user@greenmail.local", subject="Nope", body="Hi")
        assert set(result.keys()) == {"success", "message", "id"}
        assert result["success"] is False
        assert result["message"]                  # the error text
        assert result["id"] is None
        assert "error" not in result and "message_id" not in result


class TestG8ImapCredentialResolutionLocal:
    """G8 — IMAP creds: explicit > TINA4_MAIL_IMAP_* > SMTP creds (TINA4_MAIL_*)."""

    def test_falls_back_to_smtp_creds_when_no_imap_creds(self, monkeypatch):
        for v in ("TINA4_MAIL_IMAP_USERNAME", "TINA4_MAIL_IMAP_PASSWORD"):
            monkeypatch.delenv(v, raising=False)
        m = Messenger(username="smtp_user", password="smtp_pw")
        assert m.imap_username == "smtp_user"
        assert m.imap_password == "smtp_pw"

    def test_imap_env_used_over_smtp_creds(self, monkeypatch):
        monkeypatch.setenv("TINA4_MAIL_USERNAME", "smtp_user")
        monkeypatch.setenv("TINA4_MAIL_PASSWORD", "smtp_pw")
        monkeypatch.setenv("TINA4_MAIL_IMAP_USERNAME", "imap_user")
        monkeypatch.setenv("TINA4_MAIL_IMAP_PASSWORD", "imap_pw")
        m = Messenger()
        assert m.imap_username == "imap_user"
        assert m.imap_password == "imap_pw"

    def test_explicit_constructor_beats_env(self, monkeypatch):
        monkeypatch.setenv("TINA4_MAIL_IMAP_USERNAME", "imap_env")
        monkeypatch.setenv("TINA4_MAIL_IMAP_PASSWORD", "imap_env_pw")
        m = Messenger(imap_username="imap_explicit", imap_password="imap_explicit_pw")
        assert m.imap_username == "imap_explicit"
        assert m.imap_password == "imap_explicit_pw"


class TestG9ImapEncryptionParamLocal:
    """G9 — imap_encryption is constructor-settable; explicit beats env."""

    def test_constructor_param_sets_it(self, monkeypatch):
        monkeypatch.delenv("TINA4_MAIL_IMAP_ENCRYPTION", raising=False)
        assert Messenger(imap_encryption="starttls").imap_encryption == "starttls"

    def test_explicit_beats_env(self, monkeypatch):
        monkeypatch.setenv("TINA4_MAIL_IMAP_ENCRYPTION", "tls")
        # normalised (trim + lowercase) and still wins over the env value.
        assert Messenger(imap_encryption=" STARTTLS ").imap_encryption == "starttls"

    def test_env_default_is_tls(self, monkeypatch):
        monkeypatch.delenv("TINA4_MAIL_IMAP_ENCRYPTION", raising=False)
        assert Messenger().imap_encryption == "tls"


class TestG10CaptureGateLocal:
    """G10 — the capture gate: availability decides, TINA4_DEBUG never suppresses."""

    def test_captures_with_no_smtp_host(self, monkeypatch):
        monkeypatch.delenv("TINA4_MAIL_HOST", raising=False)
        monkeypatch.delenv("TINA4_MAIL_CAPTURE", raising=False)
        assert Messenger()._should_capture() is True

    def test_does_not_capture_when_host_configured(self, monkeypatch):
        monkeypatch.delenv("TINA4_MAIL_CAPTURE", raising=False)
        assert Messenger(host="smtp.example.com")._should_capture() is False

    def test_debug_does_not_suppress_sending(self, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        monkeypatch.delenv("TINA4_MAIL_CAPTURE", raising=False)
        # A configured host + debug must STILL send (not capture).
        assert Messenger(host="smtp.example.com")._should_capture() is False

    def test_mail_capture_forces_capture_even_with_host(self, monkeypatch):
        monkeypatch.setenv("TINA4_MAIL_CAPTURE", "true")
        assert Messenger(host="smtp.example.com")._should_capture() is True


class TestG10ReadMethodsRaiseLocal:
    """G10 — every read RAISES MessengerConnectionError on a real connection
    failure; send() returns a result instead."""

    def test_inbox_raises(self):
        with pytest.raises(MessengerConnectionError):
            _closed_reader().inbox()

    def test_read_raises(self):
        with pytest.raises(MessengerConnectionError):
            _closed_reader().read("1")

    def test_search_raises(self):
        with pytest.raises(MessengerConnectionError):
            _closed_reader().search(subject="x")

    def test_unread_raises(self):
        with pytest.raises(MessengerConnectionError):
            _closed_reader().unread()

    def test_folders_raises(self):
        with pytest.raises(MessengerConnectionError):
            _closed_reader().folders()

    def test_send_returns_result_not_raises(self):
        # The asymmetry is deliberate: a failed send is a result, a failed read
        # is an exception.
        result = Messenger(host=_CLOSED_HOST, port=_CLOSED_PORT, encryption="none").send(
            to="a@b.com", subject="s", body="b"
        )
        assert result["success"] is False


class TestG7MethodsExistLocal:
    """G7 — the method set exists under one name; delete is `delete`."""

    def test_required_methods_present_and_callable(self):
        m = Messenger()
        for name in ("mark_read", "mark_unread", "delete", "send_template", "read", "inbox"):
            assert callable(getattr(m, name, None)), f"Messenger.{name} missing"

    def test_delete_is_named_delete_not_delete_message(self):
        m = Messenger()
        assert hasattr(m, "delete")
        assert not hasattr(m, "deleteMessage")

    def test_send_template_returns_send_shape_via_capture(self, monkeypatch, tmp_path):
        # Real render (Frond if present, else raw template) + real capture path.
        monkeypatch.delenv("TINA4_MAIL_HOST", raising=False)
        monkeypatch.delenv("TINA4_MAIL_CAPTURE", raising=False)
        monkeypatch.setenv("TINA4_MAILBOX_DIR", str(tmp_path / "mailbox"))
        m = create_messenger()
        result = m.send_template(
            to="a@b.com", subject="s", template="Hello {{ name }}", data={"name": "Al"}
        )
        assert set(result.keys()) == {"success", "message", "id"}
        assert result["success"] is True


# ══════════════════════════════════════════════════════════════════
# LIVE — real GreenMail round-trip
# ══════════════════════════════════════════════════════════════════


@_requires_greenmail
class TestG3SnippetDecodedLive:
    def test_snippet_is_decoded_not_base64(self):
        addr = _unique("snippet_plain")
        m = _plain_messenger(addr)
        subject = f"snip-{uuid.uuid4().hex[:8]}"
        body = "the quick brown fox jumps over the lazy dog"
        m.send(to=addr, subject=subject, body=body)

        item = _wait_item(m, subject)
        # Decoded, readable text — NOT the base64 the wire carried.
        assert "quick brown fox" in item["snippet"]
        import base64
        b64 = base64.b64encode(body.encode()).decode()
        assert b64 not in item["snippet"]

    def test_snippet_strips_html_tags(self):
        addr = _unique("snippet_html")
        m = _plain_messenger(addr)
        subject = f"sniph-{uuid.uuid4().hex[:8]}"
        m.send(to=addr, subject=subject, body="<h1>Hello</h1><p>World</p>", html=True)

        item = _wait_item(m, subject)
        assert "Hello" in item["snippet"] and "World" in item["snippet"]
        assert "<h1>" not in item["snippet"] and "<p>" not in item["snippet"]

    def test_snippet_truncated_to_200(self):
        addr = _unique("snippet_long")
        m = _plain_messenger(addr)
        subject = f"snipl-{uuid.uuid4().hex[:8]}"
        m.send(to=addr, subject=subject, body="A" * 500)

        item = _wait_item(m, subject)
        assert len(item["snippet"]) <= 200


@_requires_greenmail
class TestG4InboxItemShapeLive:
    _KEYS = {"uid", "subject", "from", "to", "date", "snippet", "seen"}

    def test_inbox_item_has_exactly_seven_keys(self):
        addr = _unique("shape")
        m = _plain_messenger(addr)
        subject = f"shape-{uuid.uuid4().hex[:8]}"
        m.send(to=addr, subject=subject, body="hi")

        item = _wait_item(m, subject)
        assert set(item.keys()) == self._KEYS, f"got {sorted(item.keys())}"

    def test_inbox_field_types(self):
        addr = _unique("types")
        m = _plain_messenger(addr)
        subject = f"types-{uuid.uuid4().hex[:8]}"
        m.send(to=addr, subject=subject, body="hi")

        item = _wait_item(m, subject)
        assert isinstance(item["uid"], str)
        assert isinstance(item["seen"], bool)
        assert isinstance(item["snippet"], str)
        # date is ISO-8601 — datetime.fromisoformat parses it without raising.
        datetime.fromisoformat(item["date"])


@_requires_greenmail
class TestG5ReadItemShapeLive:
    def test_read_has_bodies_attachments_headers(self):
        addr = _unique("readshape")
        m = _plain_messenger(addr)
        subject = f"readshape-{uuid.uuid4().hex[:8]}"
        m.send(
            to=addr, subject=subject, body="the body text",
            attachments=[{"filename": "a.txt", "content": b"data", "mime": "text/plain"}],
        )
        msg = _wait_for(m, subject)
        # python's idiomatic casing (ADR-0008): body_text / body_html.
        assert "body_text" in msg and "body_html" in msg
        assert "the body text" in msg["body_text"]
        assert isinstance(msg["attachments"], list)
        assert any(a["filename"] == "a.txt" for a in msg["attachments"])
        assert isinstance(msg["headers"], dict)
        assert "Subject" in msg["headers"]


@_requires_greenmail
class TestG6SendIdIsRealMessageIdLive:
    def test_success_id_round_trips_as_message_id(self):
        addr = _unique("realid")
        m = _plain_messenger(addr)
        subject = f"realid-{uuid.uuid4().hex[:8]}"

        result = m.send(to=addr, subject=subject, body="body")
        assert set(result.keys()) == {"success", "message", "id"}
        assert result["success"] is True
        assert result["message"] is None
        assert result["id"]                         # a real, non-empty Message-ID

        # It is the ACTUAL Message-ID the server carries, not an invented token.
        msg = _wait_for(m, subject)
        assert msg["headers"].get("Message-ID") == result["id"]


@_requires_greenmail
class TestG7SendTemplateLive:
    def test_send_template_renders_and_delivers(self):
        addr = _unique("tmpl")
        m = _plain_messenger(addr)
        token = uuid.uuid4().hex[:8]
        subject = f"tmpl-{token}"
        m.send_template(
            to=addr, subject=subject,
            template="<p>Hi {{ name }} {{ token }}</p>",
            data={"name": "Al", "token": token},
        )
        msg = _wait_for(m, subject)
        assert "Al" in msg["body_html"]
        assert token in msg["body_html"]


@_requires_greenmail
class TestG8ImapUsesImapAccountLive:
    def test_imap_login_uses_imap_username_not_smtp_username(self):
        # Two separate GreenMail accounts. SMTP authenticates as smtp_acct; IMAP
        # is told to read imap_acct. The message is delivered to imap_acct, so it
        # can ONLY be found if the IMAP login used imap_username. If it fell back
        # to the SMTP username (the pre-G8 bug), inbox() would read smtp_acct's
        # empty mailbox and find nothing.
        smtp_acct = _unique("smtp_acct")
        imap_acct = _unique("imap_acct")
        m = _plain_messenger(smtp_acct, imap_username=imap_acct,
                             imap_password="greenmail-password")
        subject = f"g8-{uuid.uuid4().hex[:8]}"
        m.send(to=imap_acct, subject=subject, body="lands in the imap account")

        # Ground truth: a plain client confirms it really is in imap_acct's box.
        found = False
        for _ in range(60):
            conn = imaplib.IMAP4(_IMAP_HOST, _IMAP_PORT)
            conn.login(imap_acct, "greenmail-password")
            conn.select("INBOX")
            _s, data = conn.uid("SEARCH", None, "ALL")
            conn.logout()
            if (data[0] or b"").split():
                found = True
                break
            time.sleep(0.25)
        assert found, "message never delivered to the imap account"

        item = _wait_item(m, subject)
        assert item["subject"] == subject   # inbox() read the imap account
