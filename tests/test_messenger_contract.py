# Messenger IMAP read-path CONTRACT — the 14 invariants of messenger_contract.json.
"""Pins every invariant in plan/v3/fixtures/messenger_contract.json (ADR-0004),
so the fixture can move from "owed" to "proven" for tina4-python.

EXACTLY 14 tests, one per invariant. Each test's name contains the invariant id
verbatim (``test_msg_uid_is_a_real_uid`` -> normalises to ``msguidisarealuid``),
so the shared cross-framework auditor that matches normalised test names against
invariant ids credits each one. Python is the REFERENCE implementation; the
shapes asserted here are the canonical ones the other three frameworks move to.

NO MOCKS, EVER. Three kinds of real dependency, exactly as the sibling suites use:

  * a live GreenMail (plain SMTP 3025 / IMAP 3143) for the read path, gated on
    reachability with the SAME skip reason ("GreenMail SMTP/IMAP not reachable")
    that tests/conftest.py's TINA4_REQUIRE_SERVICES gate upgrades to a hard
    failure on the lab -- so these RUN on the lab and only skip on a laptop with
    no GreenMail;
  * a genuinely closed port (127.0.0.1:59999) for the fail-loud / failed-send
    paths -- a real connection refusal, never a simulated exception;
  * the real filesystem (a tmp DevMailbox) for the capture path.

Where an invariant can be proven without a server it runs LOCALLY too, by driving
the SAME code path read()/inbox() use with a REAL email object parsed from real
bytes (``Messenger._parse_message`` / ``_extract_bodies`` / ``_make_snippet`` are
pure over a parsed ``email.message`` -- a real message, not a double). Those tests
add a live end-to-end leg under ``if _greenmail_up:`` so the lab proves the IMAP
transport too. The four invariants that CANNOT be proven without a real server
(a real expunge, real newest-first arrival order, a real successful fetch of a
missing uid, and the live listing shape) are gated with @_requires_greenmail and
skip on a laptop -- reported honestly, never mocked.

Measured 2026-08-07 against the shipping feature/release3.13.96 code: Python
already satisfies all 14 (the 3.13.96 parity commits 3237383 / 5e912ca / 75c2578
landed the fixes), so this suite PROVES the shipped behaviour rather than driving
a new change. The one nuance is invariant 8: read() carries the 10 canonical keys
PLUS a documented ``attachments_data`` key holding the raw attachment bytes that
``attachments`` strips for JSON-safety (used by tests/test_messenger.py). The
contract locks the 10 canonical keys and permits ONLY that one master-internal
extra; it never permits a stray key.
"""
import os
import socket
import time
import uuid
import base64
import inspect
from datetime import datetime
from email.message import EmailMessage
from email.parser import BytesParser
from email import policy

import pytest

from tina4_python.messenger import (
    Messenger, MessengerConnectionError, create_messenger,
)


# ── GreenMail gating (mirrors tests/test_messenger.py exactly) ────────────
_SMTP_HOST, _SMTP_PORT = (
    os.environ.get("TINA4_TEST_SMTP_HOST", "127.0.0.1"),
    int(os.environ.get("TINA4_TEST_SMTP_PORT", "3025")),
)
_IMAP_HOST, _IMAP_PORT = (
    os.environ.get("TINA4_TEST_IMAP_HOST", "127.0.0.1"),
    int(os.environ.get("TINA4_TEST_IMAP_PORT", "3143")),
)
# A port nothing listens on — a REAL connection refusal for the fail-loud paths.
_CLOSED_HOST, _CLOSED_PORT = "127.0.0.1", 59999


def _reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_greenmail_up = _reachable(_SMTP_HOST, _SMTP_PORT) and _reachable(_IMAP_HOST, _IMAP_PORT)
# Same reason string the conftest gate keys on: on the lab (TINA4_REQUIRE_SERVICES)
# a GreenMail-absent skip becomes a hard failure, so these are not ghost tests.
_requires_greenmail = pytest.mark.skipif(
    not _greenmail_up, reason="GreenMail SMTP/IMAP not reachable"
)


# ── The canonical shapes (Python is the reference) ────────────────────────
_INBOX_ITEM_KEYS = {"uid", "subject", "from", "to", "date", "snippet", "seen"}
_READ_ITEM_KEYS = {
    "uid", "subject", "from", "to", "cc", "date",
    "body_text", "body_html", "attachments", "headers",
}
# The only extra key read() is permitted to carry: the raw attachment bytes that
# `attachments` deliberately strips so read() stays JSON-serialisable.
_READ_PERMITTED_EXTRA = {"attachments_data"}
# The public concept methods every Messenger must expose under ONE name.
_CONCEPT_METHODS = (
    "inbox", "read", "unread", "search", "folders",
    "send", "send_template", "mark_read", "mark_unread", "delete",
)


# ── Real-dependency helpers (no doubles) ──────────────────────────────────
def _plain_messenger(address: str, imap_username: str = None,
                     imap_password: str = None) -> Messenger:
    """Messenger wired for plain SMTP send + plain IMAP read against GreenMail."""
    m = Messenger(
        host=_SMTP_HOST, port=_SMTP_PORT, encryption="none",
        from_address="sender@greenmail.local",
        imap_host=_IMAP_HOST, imap_port=_IMAP_PORT,
        username=address, password="greenmail-password",
        imap_username=imap_username, imap_password=imap_password,
    )
    m.imap_encryption = "none"
    return m


def _closed_reader() -> Messenger:
    """A messenger whose IMAP points at a port nothing listens on — every read
    hits a REAL connection refusal (no simulated exception)."""
    m = Messenger(imap_host=_CLOSED_HOST, imap_port=_CLOSED_PORT,
                  username="user", password="pass")
    m.imap_encryption = "none"
    return m


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}@greenmail.local"


def _wait_item(m: Messenger, subject: str, attempts: int = 60,
               delay: float = 0.25) -> dict:
    """Poll the live IMAP mailbox until the message is LISTED; return its
    inbox() item (not the full read)."""
    for _ in range(attempts):
        for item in m.inbox(limit=50):
            if item["subject"] == subject:
                return item
        time.sleep(delay)
    raise AssertionError(f"{subject!r} never listed for {m.imap_username}")


def _wait_read(m: Messenger, subject: str, attempts: int = 60,
               delay: float = 0.25) -> dict:
    """Poll until the message arrives; return the full read() dict."""
    for _ in range(attempts):
        results = m.search(subject=subject)
        if results:
            return m.read(results[0]["uid"])
        time.sleep(delay)
    raise AssertionError(f"{subject!r} never arrived for {m.imap_username}")


def _uid_for(m: Messenger, subject: str, attempts: int = 60,
             delay: float = 0.25) -> str:
    """The IMAP uid of the message with `subject`, once it is listed."""
    return _wait_item(m, subject, attempts, delay)["uid"]


def _real_read_message(with_attachment: bool = True) -> EmailMessage:
    """A REAL email.message parsed from REAL bytes — the exact object read()
    parses off the wire, built locally so the read() SHAPE can be proven with no
    server. Not a mock: it is a genuine parsed MIME message."""
    m = EmailMessage()
    m["Subject"] = "Contract Subject"
    m["From"] = "Alice <alice@example.com>"
    m["To"] = "Bob <bob@example.com>"
    m["Cc"] = "carol@example.com"
    m["Date"] = "Fri, 07 Aug 2026 07:15:51 +0200"
    m["Message-ID"] = "<contract-abc123@example.com>"
    m.set_content("the quick brown fox jumps over the lazy dog")
    if with_attachment:
        m.add_attachment(b"real-file-bytes", maintype="text", subtype="plain",
                         filename="a.txt")
    return BytesParser(policy=policy.default).parsebytes(m.as_bytes())


# ══════════════════════════════════════════════════════════════════════════
# 1. msg-uid-is-a-real-uid — LIVE (a real expunge is the only proof)
# ══════════════════════════════════════════════════════════════════════════
@_requires_greenmail
def test_msg_uid_is_a_real_uid():
    """The reported id is the IMAP UID, not a sequence number. Proven the only
    way it can be: with a REAL expunge. Send P1,P2,P3; the id for P3 must stay
    stable and keep addressing P3 after P1 is expunged (its SEQUENCE number
    drops 3->2, its UID does not)."""
    addr = _unique("realuid")
    m = _plain_messenger(addr)
    token = uuid.uuid4().hex[:8]
    p1, p2, p3 = (f"ruid-{token}-{n}" for n in (1, 2, 3))
    for subject in (p1, p2, p3):
        m.send(to=addr, subject=subject, body=f"body of {subject}")
        _wait_item(m, subject)              # deterministic arrival order

    uid_p1, uid_p3 = _uid_for(m, p1), _uid_for(m, p3)
    # P3 addressable by its uid BEFORE the expunge.
    assert m.read(uid_p3)["subject"] == p3

    m.delete(uid_p1)                        # REAL IMAP STORE \Deleted + EXPUNGE

    # Positive: the SAME uid still returns P3 after the expunge renumbered
    # sequence numbers. A sequence-number id would now miss or mis-address.
    after = m.read(uid_p3)
    assert after is not None and after["subject"] == p3, (
        f"uid {uid_p3!r} stopped addressing P3 after an expunge — it was a "
        "sequence number, not a UID"
    )
    # Negative: the expunged message's uid is gone, never silently recycled.
    assert m.read(uid_p1) is None
    # The listing still reports P3 under the unchanged uid.
    assert _uid_for(m, p3) == uid_p3


# ══════════════════════════════════════════════════════════════════════════
# 2. msg-uid-is-a-string — LOCAL core (real parsed msg) + LIVE leg
# ══════════════════════════════════════════════════════════════════════════
def test_msg_uid_is_a_string():
    """uid is a str on every method that returns or accepts one."""
    msg = _real_read_message()
    # Accepts a bytes uid AND a str uid; returns a str either way.
    assert isinstance(Messenger()._parse_message(b"7", msg)["uid"], str)
    assert isinstance(Messenger()._parse_message("7", msg)["uid"], str)
    # Negative: it is not left as bytes/int.
    assert not isinstance(Messenger()._parse_message(b"7", msg)["uid"], (bytes, int))

    if _greenmail_up:
        addr = _unique("uidstr")
        m = _plain_messenger(addr)
        subject = f"uidstr-{uuid.uuid4().hex[:8]}"
        m.send(to=addr, subject=subject, body="hi")
        item = _wait_item(m, subject)
        assert isinstance(item["uid"], str)                    # inbox()
        assert isinstance(m.search(subject=subject)[0]["uid"], str)  # search()
        assert isinstance(m.read(item["uid"])["uid"], str)     # read()


# ══════════════════════════════════════════════════════════════════════════
# 3. msg-inbox-is-newest-first — LIVE (needs real arrival order)
# ══════════════════════════════════════════════════════════════════════════
@_requires_greenmail
def test_msg_inbox_is_newest_first():
    """inbox()/search() return newest-first: page[0] is the newest, and
    inbox(limit=1) returns THE newest (the most common inbox call)."""
    addr = _unique("order")
    m = _plain_messenger(addr)
    token = uuid.uuid4().hex[:8]
    p1, p2, p3 = (f"ord-{token}-{n}" for n in (1, 2, 3))
    for subject in (p1, p2, p3):
        m.send(to=addr, subject=subject, body=subject)
        _wait_item(m, subject)              # send strictly in order

    subjects = [it["subject"] for it in m.inbox(limit=50)]
    # Positive: newest first — P3 before P2 before P1.
    assert subjects.index(p3) < subjects.index(p2) < subjects.index(p1), (
        f"inbox not newest-first: {subjects}"
    )
    # inbox(limit=1) is the NEWEST, not the oldest (the Ruby divergence).
    assert m.inbox(limit=1)[0]["subject"] == p3
    # search() pages newest-first too.
    found = [it["subject"] for it in m.search(subject=f"ord-{token}-")]
    assert found.index(p3) < found.index(p1)


# ══════════════════════════════════════════════════════════════════════════
# 4. msg-folder-is-first-and-positional — LOCAL (signature + real closed port)
# ══════════════════════════════════════════════════════════════════════════
def test_msg_folder_is_first_and_positional():
    """inbox(folder, limit, offset) and read(uid, folder) are callable
    POSITIONALLY, folder first. Keyword args may be added, never substituted."""
    inbox_params = list(inspect.signature(Messenger.inbox).parameters.values())[1:]
    read_params = list(inspect.signature(Messenger.read).parameters.values())[1:]

    # Positive: the positional ORDER is folder-first (inbox) / uid-then-folder
    # (read), and each is POSITIONAL_OR_KEYWORD (not keyword-only, the Ruby bug).
    assert [p.name for p in inbox_params][:3] == ["folder", "limit", "offset"]
    assert [p.name for p in read_params][:2] == ["uid", "folder"]
    for p in inbox_params[:3] + read_params[:2]:
        assert p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD, (
            f"{p.name} is {p.kind.name}, so there is no positional slot for it"
        )

    # Behavioural proof against a REAL closed port: a positional call binds and
    # reaches the connection layer (MessengerConnectionError), it does NOT fail
    # at argument binding (TypeError/ArgumentError). Negative case folded in.
    reader = _closed_reader()
    with pytest.raises(MessengerConnectionError):
        reader.inbox("INBOX", 1, 0)         # folder, limit, offset — positional
    with pytest.raises(MessengerConnectionError):
        reader.read("1", "INBOX")           # uid, folder — positional


# ══════════════════════════════════════════════════════════════════════════
# 5. msg-missing-uid-is-null-not-empty — LIVE (needs a real successful fetch)
# ══════════════════════════════════════════════════════════════════════════
@_requires_greenmail
def test_msg_missing_uid_is_null_not_empty():
    """A successful fetch for a non-existent UID returns None (not {}), and never
    raises. Needs a REAL connection: a closed port would RAISE (invariant 6), so
    None can only be proven against a live server with an empty result."""
    addr = _unique("missing")
    m = _plain_messenger(addr)
    result = m.read("999999")               # nothing at this uid in a fresh box
    # Positive: exactly None.
    assert result is None
    # Negative: NOT the empty dict — `result is None` must get the right answer,
    # and JSON must carry null, not {}.
    assert result != {}
    assert not isinstance(result, dict)


# ══════════════════════════════════════════════════════════════════════════
# 6. msg-read-methods-fail-loud — LOCAL (real closed port)
# ══════════════════════════════════════════════════════════════════════════
def test_msg_read_methods_fail_loud():
    """inbox/read/unread/search/folders RAISE MessengerConnectionError on a real
    connection failure; send() returns a result and never raises."""
    reader = _closed_reader()
    # Positive: every read raises on a REAL connection refusal.
    with pytest.raises(MessengerConnectionError):
        reader.inbox()
    with pytest.raises(MessengerConnectionError):
        reader.read("1")
    with pytest.raises(MessengerConnectionError):
        reader.unread()
    with pytest.raises(MessengerConnectionError):
        reader.search(subject="x")
    with pytest.raises(MessengerConnectionError):
        reader.folders()

    # Negative (the deliberate asymmetry): send() to a closed port RETURNS a
    # failure result instead of raising.
    result = Messenger(host=_CLOSED_HOST, port=_CLOSED_PORT, encryption="none").send(
        to="a@b.com", subject="s", body="b"
    )
    assert result["success"] is False


# ══════════════════════════════════════════════════════════════════════════
# 7. msg-inbox-item-shape — LIVE (the listing shape is built during FETCH)
# ══════════════════════════════════════════════════════════════════════════
@_requires_greenmail
def test_msg_inbox_item_shape():
    """An inbox() item is EXACTLY {uid, subject, from, to, date, snippet, seen}.
    from/to are strings; date is ISO-8601."""
    addr = _unique("shape")
    m = _plain_messenger(addr)
    subject = f"shape-{uuid.uuid4().hex[:8]}"
    m.send(to=addr, subject=subject, body="hi")

    item = _wait_item(m, subject)
    # Positive: exactly the seven keys, nothing more, nothing fewer.
    assert set(item.keys()) == _INBOX_ITEM_KEYS, f"got {sorted(item.keys())}"
    assert isinstance(item["from"], str) and isinstance(item["to"], str)
    assert isinstance(item["uid"], str) and isinstance(item["seen"], bool)
    assert isinstance(item["snippet"], str)
    # date is ISO-8601 — fromisoformat parses it without raising.
    datetime.fromisoformat(item["date"])
    # Negative: the PHP/Ruby-only fields must not appear.
    for foreign in ("msgno", "flagged", "size", "flags", "read"):
        assert foreign not in item


# ══════════════════════════════════════════════════════════════════════════
# 8. msg-read-item-shape — LOCAL core (real parsed msg) + LIVE leg
# ══════════════════════════════════════════════════════════════════════════
def _assert_read_shape(result: dict):
    # The 10 canonical keys are all present...
    assert _READ_ITEM_KEYS <= set(result), (
        f"missing {sorted(_READ_ITEM_KEYS - set(result))}"
    )
    # ...and the ONLY permitted extra is the documented bytes carrier.
    assert set(result) <= _READ_ITEM_KEYS | _READ_PERMITTED_EXTRA, (
        f"stray key(s): {sorted(set(result) - _READ_ITEM_KEYS - _READ_PERMITTED_EXTRA)}"
    )
    assert isinstance(result["from"], str) and isinstance(result["to"], str)
    assert isinstance(result["cc"], str)
    assert isinstance(result["attachments"], list)
    assert isinstance(result["headers"], dict)
    datetime.fromisoformat(result["date"])          # ISO-8601
    # Message-ID lives in headers, not as a top-level key.
    assert "Message-ID" in result["headers"]
    # Negative: the other frameworks' body namings must NOT appear — body_text/
    # body_html is the one canonical (idiomatic-Python) convention.
    for foreign in ("bodyText", "bodyHtml", "body", "html"):
        assert foreign not in result


def test_msg_read_item_shape():
    """read() returns {uid, subject, from, to, cc, date, body_text, body_html,
    attachments, headers} (+ the documented attachments_data bytes carrier);
    Message-ID lives in headers; body_text/body_html is the canonical naming."""
    msg = _real_read_message(with_attachment=True)
    result = Messenger()._parse_message(b"11", msg)
    _assert_read_shape(result)
    assert "the quick brown fox" in result["body_text"]
    assert any(a["filename"] == "a.txt" for a in result["attachments"])
    # `attachments` carries metadata only (JSON-safe); the raw bytes live in the
    # permitted extra.
    assert all("content" not in a for a in result["attachments"])

    if _greenmail_up:
        addr = _unique("readshape")
        m = _plain_messenger(addr)
        subject = f"readshape-{uuid.uuid4().hex[:8]}"
        m.send(to=addr, subject=subject, body="the body text",
               attachments=[{"filename": "a.txt", "content": b"data",
                             "mime": "text/plain"}])
        live = _wait_read(m, subject)
        _assert_read_shape(live)
        assert "the body text" in live["body_text"]
        assert live["headers"].get("Subject")


# ══════════════════════════════════════════════════════════════════════════
# 9. msg-snippet-is-decoded-text — LOCAL core (real base64 msg) + LIVE leg
# ══════════════════════════════════════════════════════════════════════════
def test_msg_snippet_is_decoded_text():
    """snippet is decoded, transfer-decoded, tag-stripped plain text — never the
    raw base64 the wire carries, never unconditionally empty."""
    phrase = "the quick brown fox jumps"
    m = EmailMessage()
    m["Subject"] = "snip"
    m.set_content(phrase, cte="base64")             # force base64 on the wire
    parsed = BytesParser(policy=policy.default).parsebytes(m.as_bytes())
    body_text, body_html, _ = Messenger._extract_bodies(parsed)
    snippet = Messenger._make_snippet(body_text, body_html)
    # Positive: decoded, readable.
    assert phrase in snippet
    # Negative: NOT the raw base64 of the body.
    assert base64.b64encode(phrase.encode()).decode() not in snippet

    # HTML tags are stripped — an HTML-ONLY message, so _make_snippet falls back
    # to the HTML body and the tag-strip path actually runs. (A text/plain
    # alternative would win and leave the strip path unexercised — a ghost.)
    h = EmailMessage()
    h["Subject"] = "sniph"
    h.set_content("<h1>Hello</h1><p>World</p>", subtype="html")
    parsed_h = BytesParser(policy=policy.default).parsebytes(h.as_bytes())
    bt, bh, _ = Messenger._extract_bodies(parsed_h)
    snip_h = Messenger._make_snippet(bt, bh)
    assert "Hello" in snip_h and "World" in snip_h        # decoded content kept
    assert "<h1>" not in snip_h and "<p>" not in snip_h   # tags gone
    # Truncated to 200 chars.
    assert len(Messenger._make_snippet("A" * 500, "")) <= 200

    if _greenmail_up:
        addr = _unique("snippet")
        mm = _plain_messenger(addr)
        subject = f"snip-{uuid.uuid4().hex[:8]}"
        mm.send(to=addr, subject=subject, body=phrase)
        item = _wait_item(mm, subject)
        assert "quick brown fox" in item["snippet"]
        assert base64.b64encode(phrase.encode()).decode() not in item["snippet"]
        # HTML body, end to end: tags stripped in the listed snippet.
        hsubject = f"sniph-{uuid.uuid4().hex[:8]}"
        mm.send(to=addr, subject=hsubject, body="<h1>Hi</h1><p>There</p>", html=True)
        hitem = _wait_item(mm, hsubject)
        assert "Hi" in hitem["snippet"] and "There" in hitem["snippet"]
        assert "<h1>" not in hitem["snippet"] and "<p>" not in hitem["snippet"]


# ══════════════════════════════════════════════════════════════════════════
# 10. msg-send-result-shape — LOCAL (real capture + real closed port)
# ══════════════════════════════════════════════════════════════════════════
def test_msg_send_result_shape(monkeypatch, tmp_path):
    """send() returns {success, message, id} on BOTH the capture and delivery
    paths; id is the real Message-ID on success, None on failure; no
    path-specific extra keys (no dev:true, no error/message_id)."""
    # Capture path — real DevMailbox on the real filesystem.
    monkeypatch.delenv("TINA4_MAIL_HOST", raising=False)
    monkeypatch.delenv("TINA4_MAIL_CAPTURE", raising=False)
    monkeypatch.setenv("TINA4_MAILBOX_DIR", str(tmp_path / "mailbox"))
    captured = create_messenger().send(to="a@b.com", subject="hi", body="body")
    assert set(captured.keys()) == {"success", "message", "id"}
    assert captured["success"] is True
    assert captured["message"] is None
    assert captured["id"]                            # the local capture id
    # Negative: the renamed/capture-only keys are gone.
    for stray in ("error", "message_id", "dev"):
        assert stray not in captured

    # Failure path — a REAL connection refusal on a closed port.
    failed = Messenger(host=_CLOSED_HOST, port=_CLOSED_PORT, encryption="none").send(
        to="a@b.com", subject="Nope", body="Hi"
    )
    assert set(failed.keys()) == {"success", "message", "id"}
    assert failed["success"] is False
    assert failed["message"]                         # the error text
    assert failed["id"] is None
    for stray in ("error", "message_id", "dev"):
        assert stray not in failed


# ══════════════════════════════════════════════════════════════════════════
# 11. msg-every-method-exists-everywhere — LOCAL (attribute contract)
# ══════════════════════════════════════════════════════════════════════════
def test_msg_every_method_exists_everywhere():
    """Every public Messenger method exists under one concept name: inbox, read,
    unread, search, folders, send, send_template, mark_read, mark_unread,
    delete — all present and callable."""
    m = Messenger()
    for name in _CONCEPT_METHODS:
        assert callable(getattr(m, name, None)), f"Messenger.{name} missing"
    # Negative: delete carries ONE name — not the camelCase second spelling the
    # fixture measured in another framework.
    assert hasattr(m, "delete")
    assert not hasattr(m, "deleteMessage")


# ══════════════════════════════════════════════════════════════════════════
# 12. msg-env-vars-are-honoured-everywhere — LOCAL core + LIVE acted-on leg
# ══════════════════════════════════════════════════════════════════════════
def test_msg_env_vars_are_honoured_everywhere(monkeypatch):
    """TINA4_MAIL_IMAP_USERNAME/_PASSWORD are READ, falling back to
    TINA4_MAIL_USERNAME/_PASSWORD. The constructor reads and acts on them."""
    # Positive: the IMAP-specific vars win.
    monkeypatch.setenv("TINA4_MAIL_USERNAME", "smtp_user")
    monkeypatch.setenv("TINA4_MAIL_PASSWORD", "smtp_pw")
    monkeypatch.setenv("TINA4_MAIL_IMAP_USERNAME", "imap_user")
    monkeypatch.setenv("TINA4_MAIL_IMAP_PASSWORD", "imap_pw")
    read = Messenger()
    assert read.imap_username == "imap_user"
    assert read.imap_password == "imap_pw"

    # Fallback: with the IMAP vars unset, the SMTP creds are used (a single-
    # account setup keeps working).
    monkeypatch.delenv("TINA4_MAIL_IMAP_USERNAME", raising=False)
    monkeypatch.delenv("TINA4_MAIL_IMAP_PASSWORD", raising=False)
    fell_back = Messenger()
    assert fell_back.imap_username == "smtp_user"
    assert fell_back.imap_password == "smtp_pw"

    # Acted-on end to end: a message delivered to a SEPARATE imap account is only
    # found if the IMAP login used imap_username (not the SMTP one).
    if _greenmail_up:
        smtp_acct = _unique("smtp_acct")
        imap_acct = _unique("imap_acct")
        m = _plain_messenger(smtp_acct, imap_username=imap_acct,
                             imap_password="greenmail-password")
        subject = f"envacct-{uuid.uuid4().hex[:8]}"
        m.send(to=imap_acct, subject=subject, body="lands in the imap account")
        assert _wait_item(m, subject)["subject"] == subject


# ══════════════════════════════════════════════════════════════════════════
# 13. msg-explicit-beats-env — LOCAL (constructor wins over env)
# ══════════════════════════════════════════════════════════════════════════
def test_msg_explicit_beats_env(monkeypatch):
    """Every env-read configurable is also constructor-settable, and the
    constructor wins — including imap_encryption (the one the fixture flagged as
    env-only in Python)."""
    monkeypatch.setenv("TINA4_MAIL_IMAP_ENCRYPTION", "tls")
    monkeypatch.setenv("TINA4_MAIL_IMAP_USERNAME", "env_user")
    monkeypatch.setenv("TINA4_MAIL_HOST", "env.smtp.example.com")
    monkeypatch.setenv("TINA4_MAIL_IMAP_HOST", "env.imap.example.com")

    # Positive: explicit constructor args beat every env value...
    m = Messenger(
        host="explicit.smtp", imap_host="explicit.imap",
        imap_username="explicit_user", imap_encryption=" STARTTLS ",
    )
    assert m.host == "explicit.smtp"
    assert m.imap_host == "explicit.imap"
    assert m.imap_username == "explicit_user"
    # ...and imap_encryption is normalised (trim + lowercase) and still wins.
    assert m.imap_encryption == "starttls"

    # Negative: with no explicit arg, the env value is what is used (proving the
    # slot exists and is wired, not ignored).
    assert Messenger().imap_encryption == "tls"
    # And the documented default holds when neither is set.
    monkeypatch.delenv("TINA4_MAIL_IMAP_ENCRYPTION", raising=False)
    assert Messenger().imap_encryption == "tls"


# ══════════════════════════════════════════════════════════════════════════
# 14. msg-capture-gate — LOCAL core (real FS) + LIVE send leg
# ══════════════════════════════════════════════════════════════════════════
def test_msg_capture_gate(monkeypatch, tmp_path):
    """Capture when no SMTP host is configured; send when one is. TINA4_DEBUG
    does NOT suppress sending; TINA4_MAIL_CAPTURE=true forces capture. The
    factory returns ONE concrete type — interception is a branch, never a swap."""
    monkeypatch.delenv("TINA4_MAIL_CAPTURE", raising=False)
    monkeypatch.delenv("TINA4_MAIL_HOST", raising=False)

    # The gate truth table (decided on the real config, not a return value).
    assert Messenger()._should_capture() is True                       # no host
    assert Messenger(host="smtp.example.com")._should_capture() is False  # host set
    monkeypatch.setenv("TINA4_DEBUG", "true")
    assert Messenger(host="smtp.example.com")._should_capture() is False  # DEBUG != capture
    monkeypatch.delenv("TINA4_DEBUG", raising=False)
    monkeypatch.setenv("TINA4_MAIL_CAPTURE", "true")
    assert Messenger(host="smtp.example.com")._should_capture() is True   # forced

    # The factory returns ONE concrete type with a real callable send().
    monkeypatch.delenv("TINA4_MAIL_CAPTURE", raising=False)
    monkeypatch.setenv("TINA4_MAILBOX_DIR", str(tmp_path / "mailbox"))
    factory = create_messenger()
    assert isinstance(factory, Messenger)
    assert callable(getattr(factory, "send", None))
    # Capture actually writes a real file to the real filesystem.
    factory.send(to="a@b.com", subject="captured", body="body")
    assert list((tmp_path / "mailbox").rglob("*.json")), "capture wrote no file"

    # The SEND branch: with a host configured it does NOT capture, and the
    # message really goes out over SMTP and arrives over IMAP.
    if _greenmail_up:
        addr = _unique("sendbranch")
        sender = _plain_messenger(addr)
        assert sender._should_capture() is False
        subject = f"sendbranch-{uuid.uuid4().hex[:8]}"
        box = tmp_path / "sendbox"
        monkeypatch.setenv("TINA4_MAILBOX_DIR", str(box))
        result = sender.send(to=addr, subject=subject, body="goes to greenmail")
        assert result["success"] is True
        # It SENT — nothing was captured to the local mailbox.
        assert not (box.exists() and list(box.rglob("*.json")))
        # And it is really in the mailbox.
        assert _wait_item(sender, subject)["subject"] == subject
