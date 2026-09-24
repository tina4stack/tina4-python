"""ADR-0071: mail encryption means what it says.

  1. SMTP transport table: port 465 is always implicit TLS; ``ssl`` is implicit
     TLS on ANY port; ``tls``/``starttls`` is STARTTLS and it is REQUIRED (a
     server that does not offer it fails the send before AUTH / MAIL FROM);
     ``none`` never upgrades.
  2. An unknown value raises at construction, naming the value and the valid ones.
  3. Every TLS connection (SMTP implicit, SMTP STARTTLS, IMAP implicit, IMAP
     STARTTLS) verifies the certificate and the host name against the runtime's
     trust store. A private CA is trusted with SSL_CERT_FILE; there is no opt-out.

THE BUGS, MEASURED on v3 (13464d4):
  * ``ssl`` on port 4465/2465/... connected with plain smtplib.SMTP and, with
    ``use_tls`` False, never upgraded: the password and the mail went in clear.
  * smtplib.SMTP_SSL / starttls() and imaplib.IMAP4_SSL / starttls() were called
    with no context, so CPython used its UNVERIFIED stdlib context: a certificate
    from any CA, for any host, was accepted.
  * ``encryption="tsl"`` (a typo) silently meant plaintext, and an unknown IMAP
    value fell back to port guessing.

NO MOCKS, NO IN-TEST SERVERS. The servers are the lab's real mail servers
(started by tina4-ruby's spec/support/mail-infra.sh):

    GreenMail 4025 SMTP + AUTH (no STARTTLS), 4465 SMTPS, 4143 IMAP, 4993 IMAPS
    Mailpit   4587 SMTP with STARTTLS required + AUTH, 4825 its HTTP API
    Dovecot   4144 IMAP with STARTTLS (LOGINDISABLED until it is up)

The TLS cases run in a CHILD Python started with SSL_CERT_FILE pointing at the
lab CA - the standard way a Python app trusts a private CA, and exactly what
ADR-0071 section 3 tells users to do. The framework itself only ever calls
``ssl.create_default_context()``. The NEGATIVE cases start the child WITHOUT
SSL_CERT_FILE and must fail: a TLS suite passes just as happily with
verification switched off, so the refusals are what prove it is on.
"""
from __future__ import annotations

import imaplib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import pytest

from tina4_python.messenger import Messenger

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
REPORT_MARKER = "TINA4_REPORT "

HOST = os.environ.get("TINA4_TEST_MAIL_TLS_HOST", "127.0.0.1")
CA_FILE = os.environ.get("TINA4_TEST_MAIL_TLS_CA_FILE", "")
USERNAME = "tina4"
PASSWORD = "mail-secret"
MAILBOX = "tina4@tina4.test"

SMTP_PLAIN_AUTH = 4025     # GreenMail, AUTH, does NOT offer STARTTLS
SMTPS = 4465               # GreenMail, implicit TLS (not 465: ssl must mean TLS on ANY port)
IMAP_PLAIN = 4143          # GreenMail
IMAPS = 4993               # GreenMail
SMTP_STARTTLS = 4587       # Mailpit, STARTTLS required
MAILPIT_API = 4825
IMAP_STARTTLS = 4144       # Dovecot, any user / password "pass"
ALL_PORTS = (SMTP_PLAIN_AUTH, SMTPS, IMAP_PLAIN, IMAPS, SMTP_STARTTLS, MAILPIT_API, IMAP_STARTTLS)


# ── Pure logic: the table and the refusal (no server, no double) ─────


@pytest.mark.parametrize("encryption, port, expected", [
    ("ssl", 465, "implicit_tls"),
    ("ssl", 2465, "implicit_tls"),
    ("ssl", 587, "implicit_tls"),
    ("tls", 465, "implicit_tls"),
    ("tls", 587, "starttls"),
    ("starttls", 465, "implicit_tls"),
    ("starttls", 25, "starttls"),
    ("none", 465, "implicit_tls"),
    ("none", 25, "plain"),
])
def test_smtp_transport_table(encryption, port, expected):
    assert Messenger(host="mail.example", port=port, encryption=encryption)._smtp_transport() == expected


@pytest.mark.parametrize("given, normalised", [("SSL", "ssl"), (" tls ", "tls"), ("StartTLS", "starttls"), ("NONE", "none")])
def test_encryption_is_trimmed_and_case_insensitive(given, normalised):
    assert Messenger(host="mail.example", encryption=given).encryption == normalised


def test_default_encryption_is_still_tls(monkeypatch):
    monkeypatch.delenv("TINA4_MAIL_ENCRYPTION", raising=False)
    assert Messenger(host="mail.example", port=587).encryption == "tls"


@pytest.mark.parametrize("bad", ["tsl", "ssl3", "yes", "", "   "])
def test_unknown_encryption_raises_at_construction(bad):
    with pytest.raises(ValueError) as raised:
        Messenger(host="mail.example", encryption=bad)
    assert str(raised.value) == f"Unknown mail encryption '{bad}'. Valid values: ssl, tls, starttls, none."


def test_unknown_encryption_from_the_environment_raises(monkeypatch):
    monkeypatch.setenv("TINA4_MAIL_ENCRYPTION", "tsl")
    with pytest.raises(ValueError, match=r"^Unknown mail encryption 'tsl'\. Valid values: ssl, tls, starttls, none\.$"):
        Messenger(host="mail.example")


@pytest.mark.parametrize("bad", ["tsl", "imaps", ""])
def test_unknown_imap_encryption_raises_at_construction(bad):
    with pytest.raises(ValueError) as raised:
        Messenger(imap_host="mail.example", imap_encryption=bad)
    assert str(raised.value) == f"Unknown IMAP encryption '{bad}'. Valid values: ssl, tls, starttls, none."


def test_imap_ssl_is_accepted_as_implicit_tls():
    assert Messenger(imap_host="mail.example", imap_encryption=" SSL ").imap_encryption == "ssl"


# ── Live: the lab's real TLS mail servers ────────────────────────────


def _reachable(port: int) -> bool:
    try:
        socket.create_connection((HOST, port), timeout=1).close()
        return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def mail_servers():
    if not CA_FILE or not os.path.isfile(CA_FILE):
        pytest.skip("TLS mail servers (SMTP/IMAP) not set: export TINA4_TEST_MAIL_TLS_HOST / "
                    "TINA4_TEST_MAIL_TLS_CA_FILE (tina4-ruby spec/support/mail-infra.sh)")
    unreachable = [port for port in ALL_PORTS if not _reachable(port)]
    if unreachable:
        pytest.skip(f"TLS mail servers (SMTP/IMAP) not reachable at {HOST} ports {unreachable}")
    return HOST


_CHILD_SOURCE = r'''
import json, os, sys
from tina4_python.messenger import Messenger, MessengerError
spec = json.loads(os.environ["MAIL_TEST_INPUT"])
messenger = Messenger(**spec["messenger"])
try:
    if spec["action"] == "send":
        result = messenger.send(to=spec["to"], subject=spec["subject"], body="adr-0071")
    elif spec["action"] == "test_connection":
        result = messenger.test_connection()
    elif spec["action"] == "search":
        result = {"found": [m["subject"] for m in messenger.search(subject=spec["subject"])]}
    elif spec["action"] == "inbox":
        result = {"count": len(messenger.inbox(limit=5))}
except Exception as exc:
    result = {"error_class": type(exc).__name__, "error": str(exc)}
print("TINA4_REPORT " + json.dumps(result))
'''


def _child(spec: dict, *, trust_ca: bool) -> dict:
    """Run one Messenger action in a fresh Python. SSL_CERT_FILE is set to the
    lab CA only when `trust_ca` - OpenSSL reads it when the default store is
    built, which is the standard, framework-independent way to trust a CA."""
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("PYTHON") and key not in ("SSL_CERT_FILE", "SSL_CERT_DIR")}
    environment.update({
        "PYTHONPATH": str(REPOSITORY_ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "MAIL_TEST_INPUT": json.dumps(spec),
    })
    for name in ("TINA4_MAIL_CAPTURE", "TINA4_MAIL_REDIRECT_TO", "TINA4_MAIL_ENCRYPTION", "TINA4_MAIL_IMAP_ENCRYPTION"):
        environment.pop(name, None)
    if trust_ca:
        environment["SSL_CERT_FILE"] = CA_FILE
    completed = subprocess.run([sys.executable, "-c", _CHILD_SOURCE], env=environment,
                               capture_output=True, text=True, timeout=90)
    for line in completed.stdout.splitlines():
        if line.startswith(REPORT_MARKER):
            return json.loads(line[len(REPORT_MARKER):])
    raise AssertionError(f"mail child reported nothing (exit {completed.returncode}):\n"
                         f"{completed.stdout}\n{completed.stderr}")


def _smtp(port: int, encryption: str) -> dict:
    return {"host": HOST, "port": port, "username": USERNAME, "password": PASSWORD,
            "from_address": "sender@tina4.test", "encryption": encryption}


def _subject(label: str) -> str:
    return f"adr0071-{label}-{uuid.uuid4().hex[:12]}"


def _greenmail_subjects(subject: str) -> list[str]:
    """Read GreenMail's mailbox out of band with stdlib imaplib over the plain
    IMAP port - nothing of the framework's IMAP path is involved."""
    conn = imaplib.IMAP4(HOST, IMAP_PLAIN)
    try:
        conn.login(USERNAME, PASSWORD)
        conn.select("INBOX", readonly=True)
        status, data = conn.search(None, "SUBJECT", f'"{subject}"')
        return data[0].split() if status == "OK" and data and data[0] else []
    finally:
        conn.logout()


def _mailpit_subjects(subject: str) -> list[str]:
    query = urllib.parse.urlencode({"query": f'subject:"{subject}"'})
    with urllib.request.urlopen(f"http://{HOST}:{MAILPIT_API}/api/v1/search?{query}", timeout=10) as reply:
        return [message["Subject"] for message in json.loads(reply.read())["messages"]]


def _eventually(probe, attempts: int = 20, delay: float = 0.25):
    found = probe()
    for _ in range(attempts):
        if found:
            break
        time.sleep(delay)
        found = probe()
    return found


class TestSmtpSsl:
    def test_ssl_on_a_non_465_port_delivers_over_implicit_tls(self, mail_servers):
        subject = _subject("ssl-4465")
        result = _child({"action": "send", "messenger": _smtp(SMTPS, "ssl"), "to": MAILBOX, "subject": subject},
                        trust_ca=True)
        assert result["success"] is True, result
        assert _eventually(lambda: _greenmail_subjects(subject)), f"{subject} never arrived"

    def test_ssl_against_a_plaintext_only_server_fails_instead_of_sending_in_clear(self, mail_servers):
        """Before ADR-0071 this DELIVERED the mail, password and all, in clear."""
        subject = _subject("ssl-plain")
        result = _child({"action": "send", "messenger": _smtp(SMTP_PLAIN_AUTH, "ssl"), "to": MAILBOX,
                         "subject": subject}, trust_ca=True)
        assert result["success"] is False, result
        time.sleep(0.5)
        assert _greenmail_subjects(subject) == []

    def test_ssl_to_an_untrusted_certificate_fails(self, mail_servers):
        subject = _subject("ssl-untrusted")
        result = _child({"action": "send", "messenger": _smtp(SMTPS, "ssl"), "to": MAILBOX, "subject": subject},
                        trust_ca=False)
        assert result["success"] is False, result
        assert "certificate verify failed" in result["message"].lower(), result
        assert _greenmail_subjects(subject) == []

    def test_connection_check_uses_the_same_rules(self, mail_servers):
        spec = {"action": "test_connection", "messenger": _smtp(SMTPS, "ssl")}
        assert _child(spec, trust_ca=True) == {"success": True, "error": None}
        untrusted = _child(spec, trust_ca=False)
        assert untrusted["success"] is False and "certificate verify failed" in untrusted["error"].lower(), untrusted
        plain = _child({"action": "test_connection", "messenger": _smtp(SMTP_PLAIN_AUTH, "ssl")}, trust_ca=True)
        assert plain["success"] is False, plain


class TestSmtpStarttls:
    @pytest.mark.parametrize("encryption", ["tls", "starttls"])
    def test_starttls_delivers_with_a_trusted_certificate(self, mail_servers, encryption):
        subject = _subject(f"starttls-{encryption}")
        result = _child({"action": "send", "messenger": _smtp(SMTP_STARTTLS, encryption), "to": "rcpt@tina4.test",
                         "subject": subject}, trust_ca=True)
        assert result["success"] is True, result
        assert _eventually(lambda: _mailpit_subjects(subject)) == [subject]

    def test_starttls_to_an_untrusted_certificate_fails(self, mail_servers):
        subject = _subject("starttls-untrusted")
        result = _child({"action": "send", "messenger": _smtp(SMTP_STARTTLS, "starttls"), "to": "rcpt@tina4.test",
                         "subject": subject}, trust_ca=False)
        assert result["success"] is False, result
        assert "certificate verify failed" in result["message"].lower(), result
        assert _mailpit_subjects(subject) == []

    @pytest.mark.parametrize("encryption", ["tls", "starttls"])
    def test_starttls_is_required_when_the_server_does_not_offer_it(self, mail_servers, encryption):
        subject = _subject(f"no-starttls-{encryption}")
        result = _child({"action": "send", "messenger": _smtp(SMTP_PLAIN_AUTH, encryption), "to": MAILBOX,
                         "subject": subject}, trust_ca=True)
        assert result["success"] is False, result
        assert result["message"] == f"STARTTLS was requested but {HOST}:{SMTP_PLAIN_AUTH} does not offer it", result
        time.sleep(0.5)
        assert _greenmail_subjects(subject) == []

    def test_none_never_upgrades_so_a_starttls_only_server_refuses(self, mail_servers):
        subject = _subject("none-on-starttls")
        result = _child({"action": "send", "messenger": _smtp(SMTP_STARTTLS, "none"), "to": "rcpt@tina4.test",
                         "subject": subject}, trust_ca=True)
        assert result["success"] is False, result
        assert _mailpit_subjects(subject) == []

    def test_none_on_a_plain_server_still_delivers(self, mail_servers):
        """Positive control for `none`: plaintext on purpose still works."""
        subject = _subject("none-plain")
        result = _child({"action": "send", "messenger": _smtp(SMTP_PLAIN_AUTH, "none"), "to": MAILBOX,
                         "subject": subject}, trust_ca=False)
        assert result["success"] is True, result
        assert _eventually(lambda: _greenmail_subjects(subject))


class TestImapVerification:
    def _imaps(self, encryption: str = "tls") -> dict:
        return {"imap_host": HOST, "imap_port": IMAPS, "imap_encryption": encryption,
                "imap_username": USERNAME, "imap_password": PASSWORD}

    def _imap_starttls(self) -> dict:
        return {"imap_host": HOST, "imap_port": IMAP_STARTTLS, "imap_encryption": "starttls",
                "imap_username": f"py{uuid.uuid4().hex[:8]}", "imap_password": "pass"}

    @pytest.mark.parametrize("encryption", ["tls", "ssl"])
    def test_imaps_reads_with_a_trusted_certificate(self, mail_servers, encryption):
        subject = _subject("imaps-read")
        sent = _child({"action": "send", "messenger": _smtp(SMTPS, "ssl"), "to": MAILBOX, "subject": subject},
                      trust_ca=True)
        assert sent["success"] is True, sent
        assert _eventually(lambda: _greenmail_subjects(subject))
        result = _child({"action": "search", "messenger": self._imaps(encryption), "subject": subject}, trust_ca=True)
        assert result == {"found": [subject]}, result

    def test_imaps_to_an_untrusted_certificate_raises(self, mail_servers):
        result = _child({"action": "inbox", "messenger": self._imaps()}, trust_ca=False)
        assert result.get("error_class") == "MessengerConnectionError", result
        assert "certificate verify failed" in result["error"].lower(), result

    def test_imap_starttls_works_with_a_trusted_certificate(self, mail_servers):
        result = _child({"action": "inbox", "messenger": self._imap_starttls()}, trust_ca=True)
        assert result == {"count": 0}, result

    def test_imap_starttls_to_an_untrusted_certificate_raises(self, mail_servers):
        result = _child({"action": "inbox", "messenger": self._imap_starttls()}, trust_ca=False)
        assert result.get("error_class") == "MessengerConnectionError", result
        assert "certificate verify failed" in result["error"].lower(), result
