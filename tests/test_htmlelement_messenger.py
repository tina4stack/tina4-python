"""Behavioural tests for:

  H1 — HTMLElement rendering: nesting, attributes, void tags, and the XSS
       contract — string/scalar children are HTML-escaped by default;
       Raw()/SafeString children render unescaped; attribute values are escaped.
  M1 — DevMailbox capture -> read round-trip: a message "sent" in dev mode is
       captured to the local mailbox and is retrievable with its fields intact.

NOTE: this file used to mock imaplib.IMAP4_SSL to exercise the Messenger IMAP
fail-loud paths (e.g. ConnectionRefusedError -> MessengerConnectionError).
Those were pure mock tests (no real IMAP server) and are banned under the
no-mock policy. There is no IMAP service in the test infra, so the IMAP
connection/protocol fail-loud path cannot be exercised against a real
dependency and has been removed here rather than faked. The real, observable
messenger behaviour that runs WITHOUT a network service is the dev-mode
capture -> read round-trip (real filesystem), which is what M1 now covers;
the no-IMAP-host configuration raise stays covered mock-free by
tests/test_messenger.py::test_no_imap_host_raises. The exception-hierarchy
contract that the deleted tests leaned on is preserved below as a real
(dependency-free) assertion.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tina4_python.HtmlElement import HTMLElement, Raw, SafeString
from tina4_python.messenger import (
    Messenger,
    MessengerError,
    MessengerConnectionError,
    DevMailbox,
    create_messenger,
)


# ──────────────────────────────────────────────────────────────
# H1 — HTMLElement rendering + XSS lock-in
# ──────────────────────────────────────────────────────────────

class TestHtmlElementRendering:
    def test_string_child_is_escaped(self):
        """A plain string child must be HTML-escaped — no live tag in output."""
        el = HTMLElement("div")("<script>alert(1)</script>")
        out = str(el)
        assert "&lt;script&gt;" in out
        assert "<script>" not in out
        assert "</script>" not in out
        assert out == "<div>&lt;script&gt;alert(1)&lt;/script&gt;</div>"

    def test_string_child_via_children_kwarg_is_escaped(self):
        el = HTMLElement("p", children=["<b>x</b>"])
        out = str(el)
        assert out == "<p>&lt;b&gt;x&lt;/b&gt;</p>"
        assert "<b>" not in out

    def test_raw_child_renders_unescaped(self):
        """Raw() opt-in renders trusted markup verbatim."""
        el = HTMLElement("div")(Raw("<b>x</b>"))
        out = str(el)
        assert out == "<div><b>x</b></div>"
        assert "&lt;" not in out

    def test_safestring_alias_renders_unescaped(self):
        """SafeString is an alias for Raw and behaves identically."""
        assert SafeString is Raw
        el = HTMLElement("div")(SafeString("<i>ok</i>"))
        assert str(el) == "<div><i>ok</i></div>"

    def test_nested_element_renders_as_is_no_double_escape(self):
        """A nested HTMLElement renders its own (already-safe) output — no double-escape."""
        inner = HTMLElement("span")("<hi>")
        el = HTMLElement("div")(inner)
        out = str(el)
        # The inner element escaped its own text exactly once
        assert out == "<div><span>&lt;hi&gt;</span></div>"
        assert "&amp;lt;" not in out  # not double-escaped

    def test_mixed_children(self):
        el = HTMLElement("div")(
            "<plain>",
            Raw("<b>raw</b>"),
            HTMLElement("em")("<nested>"),
        )
        out = str(el)
        assert out == (
            "<div>&lt;plain&gt;<b>raw</b><em>&lt;nested&gt;</em></div>"
        )

    def test_attribute_value_with_quote_is_escaped(self):
        el = HTMLElement("input", {"value": '"><script>'})
        out = str(el)
        assert "&quot;&gt;&lt;script&gt;" in out
        assert '"><script>' not in out

    def test_attribute_value_with_lt_is_escaped(self):
        el = HTMLElement("a", {"title": "a < b & c"})
        out = str(el)
        assert "a &lt; b &amp; c" in out

    def test_deeply_nested_tree_renders_full_structure(self):
        """A multi-level tree renders every level with attributes in order."""
        tree = HTMLElement("ul", {"class": "list"})(
            HTMLElement("li")(HTMLElement("a", {"href": "/one"})("One")),
            HTMLElement("li")(HTMLElement("a", {"href": "/two"})("Two")),
        )
        assert str(tree) == (
            '<ul class="list">'
            '<li><a href="/one">One</a></li>'
            '<li><a href="/two">Two</a></li>'
            "</ul>"
        )

    def test_void_tags_render_self_closing_no_children(self):
        """Void elements emit no closing tag and ignore children."""
        assert str(HTMLElement("br")) == "<br>"
        assert str(HTMLElement("hr")) == "<hr>"
        # An <img> keeps its (escaped) attributes but never closes
        img = HTMLElement("img", {"src": "/logo.png", "alt": 'a "quote"'})
        out = str(img)
        assert out == '<img src="/logo.png" alt="a &quot;quote&quot;">'
        assert "</img>" not in out

    def test_void_tag_with_children_still_does_not_close(self):
        """Even if children are supplied, a void tag never produces </tag>."""
        el = HTMLElement("input", {"name": "q"})("ignored")
        out = str(el)
        assert out == '<input name="q">'
        assert "ignored" not in out
        assert "</input>" not in out

    def test_boolean_attribute_renders_bare(self):
        """value=True renders the bare attribute; value=False is omitted."""
        el = HTMLElement("input", {"type": "checkbox", "checked": True, "disabled": False})
        out = str(el)
        assert "checked" in out
        assert ' checked="' not in out  # bare, not key="value"
        assert "disabled" not in out


# ──────────────────────────────────────────────────────────────
# M1 — DevMailbox capture -> read round-trip (real filesystem, no mocks)
# ──────────────────────────────────────────────────────────────

class TestDevMailboxRoundTrip:
    @pytest.fixture
    def mailbox(self, tmp_path):
        return DevMailbox(mailbox_dir=str(tmp_path / "mailbox"))

    def test_capture_then_read_returns_same_message_with_fields(self, mailbox):
        """A captured message is retrievable by id with every field preserved."""
        result = mailbox.capture(
            to="alice@example.com",
            subject="Welcome aboard",
            body="<p>Hello Alice</p>",
            html=True,
            cc=["cc@example.com"],
            bcc=["bcc@example.com"],
            reply_to="support@example.com",
            from_address="noreply@example.com",
            from_name="Acme Support",
        )
        assert result["success"] is True
        msg_id = result["message_id"]
        assert msg_id

        msg = mailbox.read(msg_id)
        # Round-trip integrity: the read-back carries the captured fields.
        assert msg["id"] == msg_id
        assert msg["subject"] == "Welcome aboard"
        assert msg["body"] == "<p>Hello Alice</p>"
        assert msg["html"] is True
        assert msg["to"] == ["alice@example.com"]
        assert msg["cc"] == ["cc@example.com"]
        assert msg["bcc"] == ["bcc@example.com"]
        assert msg["reply_to"] == "support@example.com"
        assert msg["from"] == "Acme Support <noreply@example.com>"
        assert msg["type"] == "outbox"

    def test_read_marks_message_read_and_persists(self, mailbox):
        """read() flips the unread flag and the change survives a re-read."""
        msg_id = mailbox.capture(
            to="u@example.com", subject="S", body="B", from_address="d@example.com"
        )["message_id"]
        # Freshly captured mail is unread.
        assert mailbox.unread_count() == 1
        first = mailbox.read(msg_id)
        assert first["read"] is True
        # The flag is durable: counted unread is now zero and a second read agrees.
        assert mailbox.unread_count() == 0
        assert mailbox.read(msg_id)["read"] is True

    def test_read_unknown_id_returns_empty_dict(self, mailbox):
        """A missing id is a clean empty result, never an error."""
        assert mailbox.read("does-not-exist") == {}

    def test_create_messenger_dev_mode_send_captures_to_mailbox(self, tmp_path, monkeypatch):
        """In dev mode, Messenger.send() is intercepted and captured locally,
        and the captured mail round-trips back through the mailbox by id —
        the real production dev-mode path, no SMTP and no mock."""
        monkeypatch.setenv("TINA4_DEBUG", "true")
        monkeypatch.setenv("TINA4_MAILBOX_DIR", str(tmp_path / "mailbox"))

        messenger = create_messenger(
            from_address="bot@example.com", from_name="Bot"
        )
        # Dev mode swaps send() for a local capture and exposes the mailbox.
        assert isinstance(messenger.dev_mailbox, DevMailbox)

        send_result = messenger.send(
            to="dest@example.com",
            subject="Captured in dev",
            body="No SMTP was contacted",
            html=False,
        )
        assert send_result["success"] is True
        assert send_result["dev"] is True
        msg_id = send_result["message_id"]

        # The "sent" message is sitting in the local outbox and reads back intact.
        captured = messenger.dev_mailbox.read(msg_id)
        assert captured["subject"] == "Captured in dev"
        assert captured["body"] == "No SMTP was contacted"
        assert captured["to"] == ["dest@example.com"]
        assert captured["from"] == "Bot <bot@example.com>"

        # And it is the same single message the inbox listing exposes.
        listing = messenger.dev_mailbox.inbox()
        assert len(listing) == 1
        assert listing[0]["id"] == msg_id

    def test_prod_mode_does_not_intercept_send(self, monkeypatch):
        """Outside dev mode there is no DevMailbox and send() is the real SMTP path."""
        monkeypatch.setenv("TINA4_DEBUG", "false")
        messenger = create_messenger()
        # No local mailbox attached, and send is the bound method, not dev_send.
        assert not hasattr(messenger, "dev_mailbox")
        assert messenger.send.__func__ is Messenger.send


# ──────────────────────────────────────────────────────────────
# Messenger exception hierarchy contract (pure — no dependency, no mock)
# ──────────────────────────────────────────────────────────────

class TestMessengerErrorHierarchy:
    def test_connection_error_is_messenger_error(self):
        """MessengerConnectionError is a MessengerError so callers can catch the base."""
        assert issubclass(MessengerConnectionError, MessengerError)
        # And a constructed instance satisfies both isinstance checks.
        exc = MessengerConnectionError("boom")
        assert isinstance(exc, MessengerError)
        assert str(exc) == "boom"
