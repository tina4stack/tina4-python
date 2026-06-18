"""Lock-in regression tests for:

  H1 — HTMLElement XSS: string/scalar children are HTML-escaped by default;
       Raw()/SafeString children render unescaped; attribute values are escaped.
  M1 — Messenger IMAP fail-loud: inbox()/read()/unread()/search()/folders()
       RAISE on a connection/protocol failure instead of returning empty;
       a successful empty fetch still returns empty (NOT an error).
"""

import os
import sys
import socket

import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tina4_python.HtmlElement import HTMLElement, Raw, SafeString
from tina4_python.messenger import Messenger, MessengerError, MessengerConnectionError


# ──────────────────────────────────────────────────────────────
# H1 — HTMLElement XSS lock-in
# ──────────────────────────────────────────────────────────────

class TestHtmlElementEscaping:
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


# ──────────────────────────────────────────────────────────────
# M1 — Messenger IMAP fail-loud lock-in
# ──────────────────────────────────────────────────────────────

class TestMessengerImapFailLoud:
    def _messenger(self):
        return Messenger(imap_host="imap.test.com", username="u", password="p")

    # --- Connection failure must RAISE, not return empty ---

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_inbox_raises_on_connection_failure(self, mock_imap_cls):
        mock_imap_cls.side_effect = ConnectionRefusedError("connection refused")
        with pytest.raises(MessengerConnectionError):
            self._messenger().inbox()

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_read_raises_on_connection_failure(self, mock_imap_cls):
        mock_imap_cls.side_effect = socket.gaierror("name resolution failed")
        with pytest.raises(MessengerConnectionError):
            self._messenger().read("1")

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_unread_raises_on_connection_failure(self, mock_imap_cls):
        mock_imap_cls.side_effect = TimeoutError("timed out")
        with pytest.raises(MessengerConnectionError):
            self._messenger().unread()

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_search_raises_on_connection_failure(self, mock_imap_cls):
        mock_imap_cls.side_effect = OSError("network unreachable")
        with pytest.raises(MessengerConnectionError):
            self._messenger().search()

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_folders_raises_on_connection_failure(self, mock_imap_cls):
        mock_imap_cls.side_effect = ConnectionResetError("reset by peer")
        with pytest.raises(MessengerConnectionError):
            self._messenger().folders()

    # --- Auth / protocol failure mid-session must RAISE ---

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_inbox_raises_on_imap_protocol_error(self, mock_imap_cls):
        import imaplib
        mock_conn = MagicMock()
        mock_conn.search.side_effect = imaplib.IMAP4.error("SEARCH command error")
        mock_imap_cls.return_value = mock_conn
        with pytest.raises(MessengerConnectionError):
            self._messenger().inbox()

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_inbox_raises_on_non_ok_status(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_conn.search.return_value = ("NO", [b"command failed"])
        mock_imap_cls.return_value = mock_conn
        with pytest.raises(MessengerConnectionError):
            self._messenger().inbox()

    # --- A SUCCESSFUL empty fetch still returns empty (NOT an error) ---

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_inbox_empty_mailbox_returns_empty(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_conn.search.return_value = ("OK", [b""])
        mock_imap_cls.return_value = mock_conn
        assert self._messenger().inbox() == []

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_unread_zero_returns_zero(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_conn.search.return_value = ("OK", [b""])
        mock_imap_cls.return_value = mock_conn
        assert self._messenger().unread() == 0

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_search_no_matches_returns_empty(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_conn.search.return_value = ("OK", [b""])
        mock_imap_cls.return_value = mock_conn
        assert self._messenger().search(subject="nope") == []

    @patch("tina4_python.messenger.imaplib.IMAP4_SSL")
    def test_read_missing_uid_returns_empty_dict(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_conn.fetch.return_value = ("OK", [None])
        mock_imap_cls.return_value = mock_conn
        assert self._messenger().read("999") == {}

    # --- MessengerConnectionError is a MessengerError subtype ---

    def test_connection_error_is_messenger_error(self):
        assert issubclass(MessengerConnectionError, MessengerError)
