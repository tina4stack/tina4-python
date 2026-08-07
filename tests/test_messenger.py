# Tests for tina4_python.messenger — REAL SMTP + IMAP, no mocks.
"""
These tests exercise the Messenger against a LIVE GreenMail server (the same
container CI provisions). NO MOCKS: every send goes out over a real SMTP socket
on GreenMail's PLAIN port (3025) and is read back over a real IMAP connection on
GreenMail's PLAIN port (3143), asserting the subject/body/cc/attachments survive
the full round-trip. The earlier @patch(smtplib.SMTP/SMTP_SSL) / @patch(imaplib.
IMAP4_SSL) + MagicMock classes were deleted on purpose: a mock-passing mail test
is exactly the gap the project's no-mock rule closes (a faked sendmail/fetch
proves nothing about the wire).

The live tests are gated on GreenMail being REACHABLE, using the same pattern as
the other real-service suites (tests/test_queue_backends.py,
tests/test_session_handlers.py): a _reachable(host, port) helper + the conftest
TINA4_REQUIRE_SERVICES gate, so they RUN BY DEFAULT when the infra is up and
SKIP (never silently mock) when it is absent.

Plain ports are used deliberately so encryption="none" selects the plain
smtplib.SMTP (NOT SMTP_SSL) and imap_encryption="none" selects the plain
imaplib.IMAP4 (NOT IMAP4_SSL) — confirmed in tina4_python/messenger/__init__.py
(_smtp_send uses smtplib.SMTP when port != 465 and use_tls is False;
_imap_connect uses imaplib.IMAP4 when imap_encryption == "none").

The failure-path tests point at a closed port (127.0.0.1:59999) for a REAL
connection refusal — no simulated exception.
"""
import os
import socket
import time
import imaplib
import uuid

import pytest

from tina4_python.messenger import Messenger, MessengerError


# ── Live GreenMail targets ───────────────────────────────────────
# Plain (unencrypted) GreenMail ports. SMTP 3025 + IMAP 3143. Override via env
# for CI, default to the local docker infra.
_SMTP_HOST, _SMTP_PORT = (
    os.environ.get("TINA4_TEST_SMTP_HOST", "127.0.0.1"),
    int(os.environ.get("TINA4_TEST_SMTP_PORT", "3025")),
)
_IMAP_HOST, _IMAP_PORT = (
    os.environ.get("TINA4_TEST_IMAP_HOST", "127.0.0.1"),
    int(os.environ.get("TINA4_TEST_IMAP_PORT", "3143")),
)
# A port nothing listens on — used for the REAL connection-refused failure paths.
_CLOSED_HOST, _CLOSED_PORT = "127.0.0.1", 59999


def _reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_greenmail_up = _reachable(_SMTP_HOST, _SMTP_PORT) and _reachable(_IMAP_HOST, _IMAP_PORT)

# Matches the keyword the conftest TINA4_REQUIRE_SERVICES gate scans for, so a
# "GreenMail SMTP/IMAP not reachable" skip is upgraded to a hard failure in CI
# (where the service IS provisioned) and stays a benign skip locally.
_requires_greenmail = pytest.mark.skipif(
    not _greenmail_up,
    reason="GreenMail SMTP/IMAP not reachable",
)


def _plain_messenger(address: str) -> Messenger:
    """A Messenger wired for plain SMTP send + plain IMAP read against GreenMail.

    encryption="none" -> plain smtplib.SMTP (no STARTTLS, no SMTP_SSL).
    imap_encryption="none" -> plain imaplib.IMAP4 (no IMAP4_SSL).
    GreenMail auto-provisions a mailbox on first delivery/login, and the IMAP
    login reads the mailbox for `address`, so each test isolates itself with a
    fresh, unique recipient address.
    """
    m = Messenger(
        host=_SMTP_HOST,
        port=_SMTP_PORT,
        encryption="none",
        from_address="sender@greenmail.local",
        imap_host=_IMAP_HOST,
        imap_port=_IMAP_PORT,
        username=address,
        password="greenmail-password",  # GreenMail accepts any password
    )
    # IMAP encryption is read from env at construction; force plain explicitly so
    # the test does not depend on TINA4_MAIL_IMAP_ENCRYPTION being unset.
    m.imap_encryption = "none"
    return m


def _unique_address(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}@greenmail.local"


def _wait_for_message(m: Messenger, subject: str, attempts: int = 60,
                      delay: float = 0.25) -> dict:
    """Poll the live IMAP mailbox until a message with `subject` arrives.

    SMTP->IMAP delivery in GreenMail is asynchronous, so we poll rather than
    assume instant availability. Returns the fully-read message dict; fails the
    test if it never shows up (a real delivery failure, not a flaky skip).
    """
    for _ in range(attempts):
        results = m.search(subject=subject)
        if results:
            return m.read(results[0]["uid"])
        time.sleep(delay)
    raise AssertionError(
        f"message with subject {subject!r} never arrived in GreenMail for "
        f"{m.username} after {attempts * delay:.1f}s"
    )


# ── Config / pure-state tests (no dependency, no doubles) ────────


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
        monkeypatch.setenv("TINA4_MAIL_HOST", "env.host.com")
        monkeypatch.setenv("TINA4_MAIL_PORT", "2525")
        monkeypatch.setenv("TINA4_MAIL_USERNAME", "envuser")
        monkeypatch.setenv("TINA4_MAIL_FROM", "from@test.com")
        m = Messenger()
        assert m.host == "env.host.com"
        assert m.port == 2525
        assert m.username == "envuser"
        assert m.from_address == "from@test.com"

    def test_encryption_none_selects_plain_smtp(self):
        # The contract the live tests rely on: encryption="none" => use_tls False,
        # so _smtp_send picks plain smtplib.SMTP (port != 465, no STARTTLS).
        m = Messenger(host="localhost", port=587, encryption="none")
        assert m.use_tls is False


class TestMessengerHeaders:
    def test_add_default_header(self):
        m = Messenger()
        m.add_header("X-Mailer", "Tina4")
        assert m._default_headers["X-Mailer"] == "Tina4"


# ── Live SMTP send + IMAP read-back (real GreenMail, no mocks) ───


@_requires_greenmail
class TestMessengerSendLive:
    """Send over the REAL SMTP socket on GreenMail's plain port and read it back
    over the REAL IMAP connection, asserting the round-trip preserves content."""

    def test_send_plain_text_round_trips(self):
        addr = _unique_address("plain")
        m = _plain_messenger(addr)
        subject = f"plain-{uuid.uuid4().hex[:8]}"

        result = m.send(to=addr, subject=subject, body="Hello from a real SMTP send")
        assert result["success"] is True
        assert result["message"] is None

        msg = _wait_for_message(m, subject)
        assert msg["subject"] == subject
        assert "Hello from a real SMTP send" in msg["body_text"]
        assert addr in msg["to"]

    def test_send_html_round_trips(self):
        addr = _unique_address("html")
        m = _plain_messenger(addr)
        subject = f"html-{uuid.uuid4().hex[:8]}"

        result = m.send(to=addr, subject=subject, body="<h1>Hi</h1>", html=True)
        assert result["success"] is True

        msg = _wait_for_message(m, subject)
        assert "<h1>Hi</h1>" in msg["body_html"]

    def test_send_with_text_alternative_round_trips(self):
        addr = _unique_address("alt")
        m = _plain_messenger(addr)
        subject = f"alt-{uuid.uuid4().hex[:8]}"

        result = m.send(
            to=addr, subject=subject,
            body="<p>HTML body</p>", html=True, text="Plain alternative",
        )
        assert result["success"] is True

        msg = _wait_for_message(m, subject)
        assert "<p>HTML body</p>" in msg["body_html"]
        assert "Plain alternative" in msg["body_text"]

    def test_send_with_cc_round_trips(self):
        addr = _unique_address("cc")
        cc_addr = _unique_address("ccdest")
        m = _plain_messenger(addr)
        subject = f"cc-{uuid.uuid4().hex[:8]}"

        result = m.send(to=addr, subject=subject, body="Body with cc", cc=cc_addr)
        assert result["success"] is True

        # The recipient sees the Cc header round-trip.
        msg = _wait_for_message(m, subject)
        assert cc_addr in msg["cc"]

        # And the cc'd address actually received the message (real second mailbox).
        cc_messenger = _plain_messenger(cc_addr)
        cc_msg = _wait_for_message(cc_messenger, subject)
        assert cc_msg["subject"] == subject

    def test_send_with_bcc_delivers_without_header(self):
        addr = _unique_address("bccto")
        bcc_addr = _unique_address("bccdest")
        m = _plain_messenger(addr)
        subject = f"bcc-{uuid.uuid4().hex[:8]}"

        result = m.send(to=addr, subject=subject, body="Body with bcc", bcc=[bcc_addr])
        assert result["success"] is True

        # The bcc recipient receives the mail (real delivery)...
        bcc_messenger = _plain_messenger(bcc_addr)
        bcc_msg = _wait_for_message(bcc_messenger, subject)
        assert bcc_msg["subject"] == subject
        # ...but the bcc address is NOT exposed in the visible headers.
        assert bcc_addr not in bcc_msg["to"]
        assert bcc_addr not in bcc_msg["cc"]

    def test_send_with_reply_to_round_trips(self):
        addr = _unique_address("reply")
        m = _plain_messenger(addr)
        subject = f"reply-{uuid.uuid4().hex[:8]}"

        result = m.send(
            to=addr, subject=subject, body="Body", reply_to="reply@greenmail.local"
        )
        assert result["success"] is True

        msg = _wait_for_message(m, subject)
        assert "reply@greenmail.local" in str(msg["headers"].get("Reply-To", ""))

    def test_send_with_multiple_to_delivers_to_all(self):
        addr_a = _unique_address("multi_a")
        addr_b = _unique_address("multi_b")
        m = _plain_messenger(addr_a)
        subject = f"multi-{uuid.uuid4().hex[:8]}"

        result = m.send(to=[addr_a, addr_b], subject=subject, body="To many")
        assert result["success"] is True

        msg_a = _wait_for_message(_plain_messenger(addr_a), subject)
        msg_b = _wait_for_message(_plain_messenger(addr_b), subject)
        assert msg_a["subject"] == subject
        assert msg_b["subject"] == subject

    def test_send_with_auth_logs_in_and_delivers(self):
        # Real SMTP AUTH against GreenMail (it accepts any credentials and creates
        # the user). A failed login would raise inside _smtp_send and surface as
        # success=False, so a successful delivery proves the real login path ran.
        addr = _unique_address("auth")
        m = _plain_messenger(addr)
        subject = f"auth-{uuid.uuid4().hex[:8]}"

        result = m.send(to=addr, subject=subject, body="Authenticated send")
        assert result["success"] is True
        assert result["message"] is None

        msg = _wait_for_message(m, subject)
        assert msg["subject"] == subject

    def test_send_failure_on_closed_port(self):
        # REAL connection refusal: point SMTP at a port nothing listens on. No
        # mock side_effect — the OS refuses the connection for real.
        m = Messenger(host=_CLOSED_HOST, port=_CLOSED_PORT, encryption="none")
        result = m.send(to="user@greenmail.local", subject="Nope", body="Hi")
        assert result["success"] is False
        assert result["message"]


@_requires_greenmail
class TestMessengerAttachmentsLive:
    """Attachments must survive the real SMTP->IMAP round-trip with content intact."""

    def test_dict_attachment_round_trips(self):
        addr = _unique_address("attach_dict")
        m = _plain_messenger(addr)
        subject = f"attach-dict-{uuid.uuid4().hex[:8]}"

        result = m.send(
            to=addr,
            subject=subject,
            body="See attached",
            attachments=[{"filename": "test.txt", "content": b"hello world", "mime": "text/plain"}],
        )
        assert result["success"] is True

        msg = _wait_for_message(m, subject)
        names = [a["filename"] for a in msg["attachments"]]
        assert "test.txt" in names
        # Content survives intact (real base64 transfer-encoding round-trip),
        # carried inside attachments[i]["content"] as raw decoded bytes.
        data = next(a for a in msg["attachments"] if a["filename"] == "test.txt")
        assert data["content"] == b"hello world"

    def test_file_attachment_round_trips(self, tmp_path):
        addr = _unique_address("attach_file")
        m = _plain_messenger(addr)
        subject = f"attach-file-{uuid.uuid4().hex[:8]}"

        f = tmp_path / "report.csv"
        f.write_text("a,b,c\n1,2,3")

        result = m.send(
            to=addr, subject=subject, body="See attached", attachments=[str(f)]
        )
        assert result["success"] is True

        msg = _wait_for_message(m, subject)
        names = [a["filename"] for a in msg["attachments"]]
        assert "report.csv" in names
        # Content lives inside attachments[i]["content"] as raw decoded bytes.
        data = next(a for a in msg["attachments"] if a["filename"] == "report.csv")
        assert data["content"] == b"a,b,c\n1,2,3"

    def test_missing_file_is_skipped_send_still_succeeds(self):
        addr = _unique_address("attach_missing")
        m = _plain_messenger(addr)
        subject = f"attach-missing-{uuid.uuid4().hex[:8]}"

        result = m.send(
            to=addr, subject=subject, body="Hi", attachments=["/nonexistent/file.pdf"],
        )
        assert result["success"] is True

        msg = _wait_for_message(m, subject)
        assert msg["subject"] == subject
        assert msg["attachments"] == []


# ── IMAP config (no dependency, no doubles) ─────────────────────


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
        monkeypatch.setenv("TINA4_MAIL_IMAP_HOST", "imap.env.com")
        monkeypatch.setenv("TINA4_MAIL_IMAP_PORT", "143")
        m = Messenger()
        assert m.imap_host == "imap.env.com"
        assert m.imap_port == 143

    def test_no_imap_host_raises(self):
        m = Messenger()
        with pytest.raises(MessengerError, match="IMAP host not configured"):
            m._imap_connect()


# ── Live IMAP inbox / read / search / actions (real GreenMail) ───


@_requires_greenmail
class TestUidIsARealUidLive:
    """The `uid` field must be an IMAP UID, not a sequence number.

    MEASURED 2026-08-06 against live GreenMail, all four frameworks, same
    mailbox. Before any expunge the two numberings are IDENTICAL, which is
    exactly why this survived every existing contract suite:

        send P1 P2 P3     by sequence {1:P1, 2:P2, 3:P3}   by UID {1:P1, 2:P2, 3:P3}
        expunge P1        by sequence {1:P2, 2:P3}         by UID {2:P2, 3:P3}

    So after a real expunge, P3 is sequence number 2 and UID 3. What each
    framework reported for that same message:

        python  '2'   <- sequence number
        node    '2'   <- sequence number
        php     '3'   real UID
        ruby     3    real UID

    imaplib's ``search``/``fetch``/``store`` are the SEQUENCE-NUMBER commands;
    the UID forms are ``conn.uid("SEARCH", ...)`` and friends.

    Why it matters: a sequence number renumbers whenever ANY client expunges,
    so an id stored today addresses a different message tomorrow. No error, no
    crash - just the wrong message. Each framework was internally consistent
    (reading back by its own reported id worked), which is why four
    independently-written contract suites all passed while two were wrong.

    No mocks: real SMTP delivery, a real expunge by a second IMAP client, and
    the framework asked over a real connection.
    """

    def _real_uids_by_subject(self, address: str) -> dict:
        """Ground truth from a plain imaplib client - a second observer, not a
        double. It stands in for nothing; it speaks the protocol directly."""
        conn = imaplib.IMAP4(_IMAP_HOST, _IMAP_PORT)
        conn.login(address, "greenmail-password")
        conn.select("INBOX")
        _status, data = conn.uid("SEARCH", None, "ALL")
        out = {}
        for raw_uid in (data[0] or b"").split():
            _s, d = conn.uid("FETCH", raw_uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT)])")
            for part in d:
                if isinstance(part, tuple) and part[1]:
                    for line in part[1].decode(errors="replace").splitlines():
                        if line.lower().startswith("subject:"):
                            out[line.split(":", 1)[1].strip()] = int(raw_uid)
        conn.logout()
        return out

    def _expunge_first(self, address: str) -> None:
        conn = imaplib.IMAP4(_IMAP_HOST, _IMAP_PORT)
        conn.login(address, "greenmail-password")
        conn.select("INBOX")
        conn.store("1", "+FLAGS", "\\Deleted")
        conn.expunge()
        conn.logout()

    def test_uid_survives_an_expunge_by_another_client(self):
        addr = _unique_address("uidstable")
        m = _plain_messenger(addr)

        subjects = [f"uid{i}-{uuid.uuid4().hex[:6]}" for i in range(3)]
        for subject in subjects:
            m.send(to=addr, subject=subject, body=f"body of {subject}")
        for subject in subjects:
            _wait_for_message(m, subject)

        self._expunge_first(addr)

        truth = self._real_uids_by_subject(addr)
        # The instrument must be able to fail: if sequence and UID still agree
        # the expunge did not take, and the assertion below proves nothing.
        surviving = [s for s in subjects[1:] if s in truth]
        assert len(surviving) == 2, f"fixture did not build: {truth}"
        assert min(truth[s] for s in surviving) == 2, (
            f"expunge did not shift the UIDs, so this cannot discriminate: {truth}"
        )

        reported = {item["subject"]: item["uid"] for item in m.inbox(limit=20)}
        for subject in surviving:
            assert str(reported.get(subject)) == str(truth[subject]), (
                f"{subject}: framework reported uid={reported.get(subject)!r} but the "
                f"real IMAP UID is {truth[subject]} - that is a SEQUENCE NUMBER"
            )

    def test_a_uid_still_reads_the_message_it_names(self):
        # The pair. Switching to UID commands must not break the ordinary path:
        # the uid handed out has to fetch back the same message.
        addr = _unique_address("uidread")
        m = _plain_messenger(addr)
        subject = f"uidread-{uuid.uuid4().hex[:8]}"
        m.send(to=addr, subject=subject, body="read me by uid")
        _wait_for_message(m, subject)

        item = next(i for i in m.inbox(limit=20) if i["subject"] == subject)
        full = m.read(item["uid"])
        assert full, f"read({item['uid']!r}) returned nothing for a message that exists"
        assert full.get("subject") == subject


@_requires_greenmail
class TestIMAPInboxLive:
    def test_inbox_returns_delivered_messages(self):
        addr = _unique_address("inbox")
        m = _plain_messenger(addr)
        subject = f"inbox-{uuid.uuid4().hex[:8]}"

        m.send(to=addr, subject=subject, body="Inbox body")
        _wait_for_message(m, subject)  # ensure delivered

        messages = m.inbox(limit=10)
        assert isinstance(messages, list)
        assert any(item["subject"] == subject for item in messages)

    def test_inbox_empty_folder_returns_empty_list(self):
        # A brand-new GreenMail user with no mail: a real, successful IMAP fetch
        # of an empty mailbox returns [] (not an error).
        addr = _unique_address("emptybox")
        m = _plain_messenger(addr)
        assert m.inbox() == []

    def test_unread_counts_unseen_messages(self):
        addr = _unique_address("unread")
        m = _plain_messenger(addr)
        subject = f"unread-{uuid.uuid4().hex[:8]}"

        m.send(to=addr, subject=subject, body="Unseen body")
        # Poll the real UNSEEN count until the delivery shows up.
        count = 0
        for _ in range(60):
            count = m.unread()
            if count >= 1:
                break
            time.sleep(0.25)
        assert count >= 1

    def test_unread_zero_on_empty_mailbox(self):
        addr = _unique_address("unread_zero")
        m = _plain_messenger(addr)
        assert m.unread() == 0


@_requires_greenmail
class TestIMAPReadLive:
    def test_read_plain_message(self):
        addr = _unique_address("read_plain")
        m = _plain_messenger(addr)
        subject = f"read-{uuid.uuid4().hex[:8]}"

        m.send(to=addr, subject=subject, body="This is the body.")
        results = []
        for _ in range(60):
            results = m.search(subject=subject)
            if results:
                break
            time.sleep(0.25)
        assert results, "message never arrived"

        msg = m.read(results[0]["uid"])
        assert msg["subject"] == subject
        assert "sender@greenmail.local" in msg["from"]
        assert "This is the body." in msg["body_text"]

    def test_read_html_message(self):
        addr = _unique_address("read_html")
        m = _plain_messenger(addr)
        subject = f"read-html-{uuid.uuid4().hex[:8]}"

        m.send(to=addr, subject=subject, body="<h1>Hello</h1>", html=True)
        msg = _wait_for_message(m, subject)
        assert "<h1>Hello</h1>" in msg["body_html"]

    def test_read_not_found_returns_none(self):
        # A non-existent UID on a real server returns an empty fetch -> None (G2).
        # NOT {}: an empty dict is falsy but `result is None` gets it wrong, and it
        # serialises to `{}` where php/ruby/node all carry `null`.
        addr = _unique_address("read_missing")
        m = _plain_messenger(addr)
        assert m.read("999999") is None


@_requires_greenmail
class TestIMAPSearchLive:
    def test_search_by_subject(self):
        addr = _unique_address("search_subj")
        m = _plain_messenger(addr)
        token = uuid.uuid4().hex[:8]
        subject = f"Invoice {token}"

        m.send(to=addr, subject=subject, body="Hi")
        _wait_for_message(m, subject)

        results = m.search(subject=f"Invoice {token}")
        assert results
        assert any(token in r["subject"] for r in results)

    def test_search_unseen_only(self):
        addr = _unique_address("search_unseen")
        m = _plain_messenger(addr)
        subject = f"unseen-{uuid.uuid4().hex[:8]}"

        m.send(to=addr, subject=subject, body="Hi")
        # Wait for the message to be deliverable, then search UNSEEN.
        for _ in range(60):
            if m.unread() >= 1:
                break
            time.sleep(0.25)
        results = m.search(unseen_only=True)
        assert any(r["subject"] == subject for r in results)


@_requires_greenmail
class TestIMAPActionsLive:
    def test_mark_read_and_unread(self):
        addr = _unique_address("mark")
        m = _plain_messenger(addr)
        subject = f"mark-{uuid.uuid4().hex[:8]}"

        m.send(to=addr, subject=subject, body="Hi")
        # search() uses BODY.PEEK so it does NOT change the seen flag.
        results = []
        for _ in range(60):
            results = m.search(subject=subject)
            if results:
                break
            time.sleep(0.25)
        assert results
        uid = results[0]["uid"]
        assert m.unread() >= 1  # delivered as unseen

        m.mark_read(uid)
        # The message we marked is now seen — it should not be in UNSEEN search.
        seen_results = m.search(unseen_only=True)
        assert all(r["uid"] != uid for r in seen_results)

        m.mark_unread(uid)
        unseen_again = m.search(unseen_only=True)
        assert any(r["uid"] == uid for r in unseen_again)

    def test_delete_removes_message(self):
        addr = _unique_address("delete")
        m = _plain_messenger(addr)
        subject = f"delete-{uuid.uuid4().hex[:8]}"

        m.send(to=addr, subject=subject, body="Delete me")
        results = []
        for _ in range(60):
            results = m.search(subject=subject)
            if results:
                break
            time.sleep(0.25)
        assert results
        uid = results[0]["uid"]

        m.delete(uid)
        # After expunge, the message is gone from the live mailbox.
        assert m.search(subject=subject) == []

    def test_folders_lists_inbox(self):
        addr = _unique_address("folders")
        m = _plain_messenger(addr)
        folders = m.folders()
        assert "INBOX" in folders


# ── Live SMTP/IMAP connectivity checks (real GreenMail) ──────────


@_requires_greenmail
class TestConnectionLive:
    def test_smtp_connection_success(self):
        addr = _unique_address("conn_smtp")
        m = _plain_messenger(addr)
        result = m.test_connection()
        assert result["success"] is True
        assert result["error"] is None

    def test_smtp_connection_failure_on_closed_port(self):
        # REAL refusal against a closed port (no mock side_effect).
        m = Messenger(host=_CLOSED_HOST, port=_CLOSED_PORT, encryption="none")
        result = m.test_connection()
        assert result["success"] is False
        assert result["error"]

    def test_imap_connection_success(self):
        addr = _unique_address("conn_imap")
        m = _plain_messenger(addr)
        result = m.test_imap_connection()
        assert result["success"] is True
        assert result["error"] is None

    def test_imap_connection_failure_on_closed_port(self):
        m = Messenger(
            imap_host=_CLOSED_HOST, imap_port=_CLOSED_PORT,
            username="user", password="pass",
        )
        m.imap_encryption = "none"
        result = m.test_imap_connection()
        assert result["success"] is False
        assert result["error"]
