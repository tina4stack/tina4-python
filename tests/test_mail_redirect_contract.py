# MAIL REDIRECT CONTRACT -- TINA4_MAIL_REDIRECT_TO (MAIL-DEC-01).
"""Pins plan/v3/fixtures/mail_redirect_contract.json.

TINA4_MAIL_REDIRECT_TO is a SECOND, independent knob on the real-SMTP path:
when a redirect list is configured and send() is actually talking to SMTP (not
capturing), every recipient is REPLACED by the redirect list and the original
recipients are preserved in an X-Tina4-Original-To header. Capture
(TINA4_MAIL_CAPTURE / no SMTP host) always wins -- redirect never applies on
the capture path.

Real GreenMail SMTP :3025 / IMAP :3143 (TINA4_TEST_SMTP_* / TINA4_TEST_IMAP_*
to relocate -- the SAME live server tests/test_messenger_contract.py and
tests/test_messenger.py use). NO MOCKS EVER: every case sends real SMTP and
proves delivery or non-delivery with a real IMAP fetch. Skips (with the
wording tests/conftest.py's TINA4_REQUIRE_SERVICES gate recognises) upgrade to
a hard failure on the lab, so these are never ghost tests there.
"""
import os
import socket
import time
import uuid

import pytest

from tina4_python.messenger import Messenger


# ── GreenMail gating (mirrors tests/test_messenger_contract.py exactly) ────
_SMTP_HOST, _SMTP_PORT = (
    os.environ.get("TINA4_TEST_SMTP_HOST", "127.0.0.1"),
    int(os.environ.get("TINA4_TEST_SMTP_PORT", "3025")),
)
_IMAP_HOST, _IMAP_PORT = (
    os.environ.get("TINA4_TEST_IMAP_HOST", "127.0.0.1"),
    int(os.environ.get("TINA4_TEST_IMAP_PORT", "3143")),
)


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


# ── Real-dependency helpers (no doubles) ────────────────────────────────────
def _unique(prefix: str, domain: str) -> str:
    """A unique address -> an isolated, first-access-created GreenMail mailbox
    (GreenMail's auth is disabled on the lab, so LOGIN as any never-used
    address succeeds and SELECT INBOX reports 0 messages -- verified live)."""
    return f"mailredirect-{prefix}-{uuid.uuid4().hex[:10]}@{domain}"


def _sender_messenger() -> Messenger:
    """A messenger wired for a real SMTP send only (no IMAP creds needed)."""
    return Messenger(
        host=_SMTP_HOST, port=_SMTP_PORT, encryption="none",
        from_address="sender@tina4.test",
    )


def _reader_messenger(address: str) -> Messenger:
    """A messenger wired to poll ONE mailbox's real IMAP. The address IS the
    mailbox identity (GreenMail auth disabled -- any password is accepted)."""
    m = Messenger(
        imap_host=_IMAP_HOST, imap_port=_IMAP_PORT,
        imap_username=address, imap_password="secret",
    )
    m.imap_encryption = "none"
    return m


def _wait_present(address: str, subject: str, attempts: int = 40,
                  delay: float = 0.25) -> dict:
    """Poll until `subject` is listed in `address`'s real IMAP inbox."""
    reader = _reader_messenger(address)
    for _ in range(attempts):
        for item in reader.inbox(limit=50):
            if item["subject"] == subject:
                return item
        time.sleep(delay)
    raise AssertionError(f"{subject!r} never arrived in {address}'s real IMAP mailbox")


def _stays_absent(address: str, subject: str, attempts: int = 40,
                  delay: float = 0.25) -> bool:
    """Poll for `subject` to confirm it NEVER arrives within a real bounded
    window. Mutation-proof: if the recipient-rewrite is disabled the message
    DOES land here and this returns False well before the budget is spent."""
    reader = _reader_messenger(address)
    for _ in range(attempts):
        for item in reader.inbox(limit=50):
            if item["subject"] == subject:
                return False
        time.sleep(delay)
    return True


def _outbox_count(mailbox_dir) -> int:
    """Count of .json messages captured to the real DevMailbox outbox on disk."""
    outbox = mailbox_dir / "outbox"
    if not outbox.exists():
        return 0
    return len(list(outbox.rglob("*.json")))


# ══════════════════════════════════════════════════════════════════════════
# redirect_delivers_to_every_address_on_the_list
# ══════════════════════════════════════════════════════════════════════════
@_requires_greenmail
def test_redirect_delivers_to_every_address_on_the_list(monkeypatch):
    """TINA4_MAIL_REDIRECT_TO delivers to every dev address and NOT the real
    one, carrying X-Tina4-Original-To on the received message."""
    dev1 = _unique("dev1", "x.test")
    dev2 = _unique("dev2", "x.test")
    real = _unique("real", "y.test")
    subject = f"mailredirect-{uuid.uuid4().hex[:8]}"

    # A deliberate space after the comma proves the parse rule really trims.
    monkeypatch.setenv("TINA4_MAIL_REDIRECT_TO", f"{dev1}, {dev2}")

    sender = _sender_messenger()
    result = sender.send(to=real, subject=subject, body="the real message body")
    assert result["success"] is True, result["message"]

    # Positive: BOTH dev addresses received it.
    item1 = _wait_present(dev1, subject)
    item2 = _wait_present(dev2, subject)
    assert item1["subject"] == subject
    assert item2["subject"] == subject

    # Negative: the real recipient never did.
    assert _stays_absent(real, subject), (
        f"the real recipient {real} received the redirected mail"
    )

    # The received message carries the original recipient in the header.
    full = _reader_messenger(dev1).read(item1["uid"])
    assert full is not None
    assert full["headers"].get("X-Tina4-Original-To") == real


# ══════════════════════════════════════════════════════════════════════════
# redirect_unset_delivers_normally
# ══════════════════════════════════════════════════════════════════════════
@_requires_greenmail
def test_redirect_unset_delivers_normally(monkeypatch):
    """With TINA4_MAIL_REDIRECT_TO unset, mail arrives at the real recipient
    (negative/control)."""
    real = _unique("realctrl", "y.test")
    subject = f"mailredirect-ctrl-{uuid.uuid4().hex[:8]}"
    monkeypatch.delenv("TINA4_MAIL_REDIRECT_TO", raising=False)

    sender = _sender_messenger()
    result = sender.send(to=real, subject=subject, body="normal delivery")
    assert result["success"] is True, result["message"]

    item = _wait_present(real, subject)
    assert item["subject"] == subject


# ══════════════════════════════════════════════════════════════════════════
# capture_takes_precedence_over_redirect
# ══════════════════════════════════════════════════════════════════════════
@_requires_greenmail
def test_capture_takes_precedence_over_redirect(monkeypatch, tmp_path):
    """TINA4_MAIL_CAPTURE wins over TINA4_MAIL_REDIRECT_TO -- nothing reaches
    GreenMail, the DevMailbox gets exactly 1 message."""
    dev1 = _unique("capdev1", "x.test")
    dev2 = _unique("capdev2", "x.test")
    real = _unique("capreal", "y.test")
    subject = f"mailredirect-capture-{uuid.uuid4().hex[:8]}"
    mailbox_dir = tmp_path / "mailbox"

    monkeypatch.setenv("TINA4_MAIL_CAPTURE", "true")
    monkeypatch.setenv("TINA4_MAIL_REDIRECT_TO", f"{dev1},{dev2}")
    monkeypatch.setenv("TINA4_MAILBOX_DIR", str(mailbox_dir))

    # A REAL SMTP host is configured too, so capture wins on the MERITS of
    # TINA4_MAIL_CAPTURE, not merely because sending was unavailable.
    messenger = Messenger(
        host=_SMTP_HOST, port=_SMTP_PORT, encryption="none",
        from_address="sender@tina4.test",
    )
    result = messenger.send(to=real, subject=subject, body="must never leave this box")
    assert result["success"] is True, result["message"]

    # Nothing reached GreenMail at all -- dev list AND the real recipient stay
    # empty (a shorter budget suffices: capture short-circuits before any
    # socket is opened, so a mutation would surface fast).
    assert _stays_absent(dev1, subject, attempts=16, delay=0.25), (
        f"dev1 ({dev1}) received mail despite TINA4_MAIL_CAPTURE"
    )
    assert _stays_absent(dev2, subject, attempts=16, delay=0.25), (
        f"dev2 ({dev2}) received mail despite TINA4_MAIL_CAPTURE"
    )
    assert _stays_absent(real, subject, attempts=16, delay=0.25), (
        f"the real recipient ({real}) received mail despite TINA4_MAIL_CAPTURE"
    )

    # Exactly one message landed in the local DevMailbox.
    assert _outbox_count(mailbox_dir) == 1
