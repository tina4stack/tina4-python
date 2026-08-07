# Tina4 Messenger — Zero-dependency email via stdlib smtplib + imaplib.
"""
Send and read email using Python's built-in smtplib, imaplib, and email modules.
Unified .env-driven configuration with constructor override across all Tina4 frameworks.

Priority: constructor params > .env > sensible defaults

    # .env config:
    # TINA4_MAIL_HOST=smtp.gmail.com
    # TINA4_MAIL_PORT=587
    # TINA4_MAIL_USERNAME=user@gmail.com
    # TINA4_MAIL_PASSWORD=app-password
    # TINA4_MAIL_FROM=noreply@myapp.com
    # TINA4_MAIL_ENCRYPTION=tls
    # TINA4_MAIL_IMAP_HOST=imap.gmail.com
    # TINA4_MAIL_IMAP_PORT=993

    from tina4_python.messenger import Messenger

    # Reads from .env
    mail = Messenger()

    # Override specific settings
    mail = Messenger(host="smtp.office365.com", port=587)

    # Send
    mail.send(to="user@example.com", subject="Welcome",
              body="<h1>Hello!</h1>", html=True, text="Hello!")

    # Read inbox
    messages = mail.inbox(limit=10)
    message = mail.read(message_id)

Supported:
    - Plain text and HTML emails (with text alternative)
    - Attachments (file path or bytes)
    - CC, BCC recipients
    - Reply-To header
    - Template rendering (via Frond engine)
    - TLS / STARTTLS / SSL
    - IMAP inbox reading, search, mark read/unread, delete
    - Environment variable configuration (TINA4_MAIL_* with SMTP_* fallback)
"""
import os
import re
import ssl
import json
import time
import socket
import smtplib
import imaplib
import mimetypes
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders, policy
from email.parser import BytesParser
from email.utils import formataddr, formatdate, parsedate_to_datetime, make_msgid
from pathlib import Path
from datetime import datetime, timezone


class MessengerError(Exception):
    """Raised on send failure."""
    pass


class MessengerConnectionError(MessengerError):
    """Raised when an IMAP read fails to connect, authenticate, or speak the
    protocol. Distinct from a successful fetch that simply has no messages —
    that still returns an empty result, NOT an error.
    """
    pass


# Errors that mean "we could not talk to the mail server", as opposed to
# "we talked fine and the mailbox is empty". These must fail loud, never be
# silently swallowed into an empty result.
_IMAP_CONNECTION_ERRORS = (
    imaplib.IMAP4.error,   # protocol / auth errors (covers .abort, .readonly)
    OSError,               # socket errors, connection refused/reset, DNS, timeout
    ssl.SSLError,          # TLS handshake / cert failures
    socket.timeout,        # explicit read/connect timeout
    EOFError,              # server hung up mid-conversation
)


def _imap_fail(method: str, exc: Exception) -> "MessengerConnectionError":
    """Log an IMAP connection/protocol failure and return the error to raise.

    A genuinely empty mailbox is NOT an error and never reaches here.
    """
    from tina4_python.debug import Log
    Log.error(f"Messenger IMAP {method}() failed: {exc.__class__.__name__}: {exc}")
    if isinstance(exc, MessengerError):
        return exc
    return MessengerConnectionError(f"IMAP {method} failed: {exc}")


class Messenger:
    """SMTP email client using Python stdlib."""

    def __init__(self, host: str = None, port: int = None,
                 username: str = None, password: str = None,
                 from_address: str = None, from_name: str = None,
                 encryption: str = None, use_tls: bool = None,
                 imap_host: str = None, imap_port: int = None,
                 imap_username: str = None, imap_password: str = None,
                 imap_encryption: str = None):
        # SMTP (send) — priority: constructor > .env > sensible default
        # Whether a host was actually CONFIGURED, which is not the same as
        # self.host being set: self.host falls back to "localhost", so it is never
        # empty and cannot answer "can this messenger send?". The dev-capture gate
        # needs that answer, so record it here while the real inputs are in scope.
        self._smtp_configured = bool(host or os.environ.get("TINA4_MAIL_HOST"))
        self.host = host or os.environ.get("TINA4_MAIL_HOST", "localhost")
        self.port = port or int(os.environ.get("TINA4_MAIL_PORT", "587"))
        self.username = username or os.environ.get("TINA4_MAIL_USERNAME", "")
        self.password = password or os.environ.get("TINA4_MAIL_PASSWORD", "")
        self.from_address = from_address or os.environ.get(
            "TINA4_MAIL_FROM", self.username or "noreply@localhost")
        self.from_name = from_name or os.environ.get("TINA4_MAIL_FROM_NAME", "")

        # Encryption: constructor > .env > backward-compat use_tls > default "tls"
        resolved_encryption = encryption or os.environ.get("TINA4_MAIL_ENCRYPTION", None)
        if resolved_encryption is not None:
            self.encryption = resolved_encryption.lower()
        elif use_tls is not None:
            self.encryption = "tls" if use_tls else "none"
        else:
            self.encryption = "tls"
        # Backward compat: use_tls derived from encryption
        self.use_tls = self.encryption in ("tls", "starttls")

        self._default_headers: dict[str, str] = {}

        # IMAP (read)
        self.imap_host = imap_host or os.environ.get("TINA4_MAIL_IMAP_HOST", "")
        self.imap_port = imap_port or int(os.environ.get("TINA4_MAIL_IMAP_PORT", "993"))
        # IMAP credentials — the mailbox being READ is not always the account mail
        # is SENT from, so IMAP has its own username/password. Resolution (G8):
        # constructor arg > TINA4_MAIL_IMAP_USERNAME/_PASSWORD > the SMTP username/
        # password (which themselves came from TINA4_MAIL_USERNAME/_PASSWORD). The
        # last fallback is what keeps a single-account setup working with no IMAP
        # vars; before this, IMAP always authenticated with the SMTP creds, so a
        # separate IMAP account silently read the wrong mailbox.
        self.imap_username = (
            imap_username
            or os.environ.get("TINA4_MAIL_IMAP_USERNAME")
            or self.username
        )
        self.imap_password = (
            imap_password
            or os.environ.get("TINA4_MAIL_IMAP_PASSWORD")
            or self.password
        )
        # IMAP encryption — independent of SMTP encryption above. Lets ops
        # connect to e.g. an SMTP relay over starttls while reading mail over
        # implicit TLS. Constructor arg beats env (ADR-0041, G9); env default
        # "tls". Cross-framework parity v3.12.4.
        self.imap_encryption = (
            imap_encryption
            or os.environ.get("TINA4_MAIL_IMAP_ENCRYPTION", "tls")
        ).lower().strip()

    def add_header(self, name: str, value: str):
        """Add a default header to all outgoing emails."""
        self._default_headers[name] = value

    def _should_capture(self) -> bool:
        """Should send() capture to a local mailbox instead of talking to SMTP?

        Availability decides, not verbosity. With no SMTP host configured sending
        is impossible, so simulate it into a folder rather than failing -- that is
        what makes a laptop with no mail server usable. ``TINA4_MAIL_CAPTURE``
        forces capture even when a host IS configured, for anyone who wants
        "never send real mail from this box".

        ``TINA4_DEBUG`` deliberately does NOT gate this. Debug must still be able
        to send: tying capture to it means nobody can test a real send from a dev
        box, which is the common case.
        """
        from tina4_python.dotenv import is_truthy
        if is_truthy(os.environ.get("TINA4_MAIL_CAPTURE", "")):
            return True
        return not self._smtp_configured

    def _dev_mailbox(self) -> "DevMailbox":
        """The local mailbox, created on first capture and reused after.

        Attached lazily so a messenger that never captures never grows the
        attribute -- callers test ``hasattr(messenger, "dev_mailbox")`` to ask
        "is this a capturing messenger?".
        """
        mailbox = getattr(self, "dev_mailbox", None)
        if mailbox is None:
            mailbox = DevMailbox()
            self.dev_mailbox = mailbox
        return mailbox

    def send(self, to: str | list[str], subject: str, body: str,
             html: bool = False, text: str = None,
             cc: str | list[str] = None,
             bcc: str | list[str] = None, reply_to: str = None,
             attachments: list = None, headers: dict = None) -> dict:
        """Send an email.

        Args:
            to: Recipient(s)
            subject: Email subject
            body: Email body (plain text or HTML)
            html: If True, body is HTML
            text: Plain text alternative (when body is HTML)
            cc: CC recipient(s)
            bcc: BCC recipient(s)
            reply_to: Reply-To address
            attachments: List of file paths (str/Path) or dicts {"filename": ..., "content": bytes, "mime": ...}
            headers: Additional headers

        Returns:
            {"success": bool, "message": None or str, "id": str or None}

            One shape on BOTH the real-send and the dev-capture path. On success
            ``message`` is None and ``id`` is the real Message-ID header (or the
            local capture id); on failure ``message`` is the error text and ``id``
            is None. No path-specific extra keys.
        """
        to_list = [to] if isinstance(to, str) else list(to)
        cc_list = [cc] if isinstance(cc, str) else list(cc or [])
        bcc_list = [bcc] if isinstance(bcc, str) else list(bcc or [])

        # Dev capture is a BRANCH here, not a method swapped onto the instance.
        # The swap was the cause of tina4-nodejs#42 in Python: dev_send declared
        # (to, subject, body, html, cc, ...) while this method declares
        # (to, subject, body, html, text, cc, ...), so one name meant two
        # signatures -- send(to, subj, body, True, "plain text") filed the
        # plain-text body as a CC RECIPIENT and reported success, and
        # send(text=...) raised TypeError on a dev messenger.
        if self._should_capture():
            return self._dev_mailbox().capture(
                to, subject, body, html, text,
                cc=cc_list, bcc=bcc_list, reply_to=reply_to,
                from_address=self.from_address, from_name=self.from_name,
                attachments=attachments,
            )

        has_attachments = bool(attachments)
        has_text_alt = text is not None and html

        if has_attachments or has_text_alt:
            if has_attachments:
                msg = MIMEMultipart("mixed")
                if has_text_alt:
                    alt_part = MIMEMultipart("alternative")
                    alt_part.attach(MIMEText(text, "plain", "utf-8"))
                    alt_part.attach(MIMEText(body, "html", "utf-8"))
                    msg.attach(alt_part)
                elif html:
                    msg.attach(MIMEText(body, "html", "utf-8"))
                else:
                    msg.attach(MIMEText(body, "plain", "utf-8"))
            else:
                # text alternative without attachments
                msg = MIMEMultipart("alternative")
                msg.attach(MIMEText(text, "plain", "utf-8"))
                msg.attach(MIMEText(body, "html", "utf-8"))
        else:
            subtype = "html" if html else "plain"
            msg = MIMEText(body, subtype, "utf-8")

        # Headers
        msg["Subject"] = subject
        msg["From"] = formataddr((self.from_name, self.from_address))
        msg["To"] = ", ".join(to_list)
        msg["Date"] = formatdate(localtime=True)
        # A real Message-ID, so send() can return the id the server will carry.
        # Domain comes from the sender address when it has one, else stdlib picks
        # the FQDN. Without this the header was never set and send() reported an
        # empty id on every real send.
        domain = self.from_address.split("@")[-1] if "@" in (self.from_address or "") else None
        msg["Message-ID"] = make_msgid(domain=domain)

        if cc_list:
            msg["Cc"] = ", ".join(cc_list)
        if reply_to:
            msg["Reply-To"] = reply_to

        # Default + custom headers
        for k, v in self._default_headers.items():
            msg[k] = v
        if headers:
            for k, v in headers.items():
                msg[k] = v

        # Attachments
        if attachments:
            for attachment in attachments:
                part = self._make_attachment(attachment)
                if part:
                    msg.attach(part)

        # Send
        all_recipients = to_list + cc_list + bcc_list
        try:
            message_id = self._smtp_send(msg, all_recipients)
            return {"success": True, "message": None, "id": message_id}
        except Exception as e:
            return {"success": False, "message": str(e), "id": None}

    def send_template(self, to: str | list[str], subject: str,
                      template: str, data: dict = None, **kwargs) -> dict:
        """Send an email rendered from a Frond template string.

        Args:
            to: Recipient(s)
            subject: Email subject
            template: Template string (Twig/Jinja2 syntax)
            data: Template variables
            **kwargs: Passed to send() (cc, bcc, attachments, etc.)
        """
        try:
            from tina4_python.core.response import get_frond
            body = get_frond().render_string(template, data or {})
        except ImportError:
            body = template

        return self.send(to=to, subject=subject, body=body, html=True, **kwargs)

    def _smtp_send(self, msg: MIMEText | MIMEMultipart, recipients: list[str]) -> str:
        """Connect to SMTP and send."""
        if self.port == 465:
            # Direct TLS
            server = smtplib.SMTP_SSL(self.host, self.port, timeout=30)
        else:
            server = smtplib.SMTP(self.host, self.port, timeout=30)
            if self.use_tls:
                server.starttls()

        try:
            if self.username and self.password:
                server.login(self.username, self.password)
            server.sendmail(self.from_address, recipients, msg.as_string())
            message_id = msg.get("Message-ID", "")
            return message_id
        finally:
            try:
                server.quit()
            except Exception:
                pass

    def _make_attachment(self, attachment) -> MIMEBase | None:
        """Create a MIME attachment from a file path or dict."""
        if isinstance(attachment, (str, Path)):
            path = Path(attachment)
            if not path.is_file():
                return None
            mime_type, _ = mimetypes.guess_type(str(path))
            mime_type = mime_type or "application/octet-stream"
            maintype, subtype = mime_type.split("/", 1)
            with open(path, "rb") as f:
                content = f.read()
            part = MIMEBase(maintype, subtype)
            part.set_payload(content)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=path.name)
            return part

        if isinstance(attachment, dict):
            filename = attachment.get("filename", "attachment")
            content = attachment.get("content", b"")
            mime_type = attachment.get("mime", "application/octet-stream")
            maintype, subtype = mime_type.split("/", 1)
            part = MIMEBase(maintype, subtype)
            part.set_payload(content)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=filename)
            return part

        return None

    # ── IMAP (Read) ────────────────────────────────────────────

    def _imap_connect(self) -> imaplib.IMAP4_SSL | imaplib.IMAP4:
        """Connect and authenticate to the IMAP server.

        Honours TINA4_MAIL_IMAP_ENCRYPTION:
            "tls"      → implicit TLS (IMAP4_SSL). Default.
            "starttls" → plain IMAP4, then STARTTLS upgrade.
            "none"     → plain IMAP4, no encryption (lab/dev only).

        Falls back to "use port 993 = TLS" for back-compat when the env
        var is missing — that's how the previous version behaved.
        """
        if not self.imap_host:
            raise MessengerError("IMAP host not configured (set imap_host or IMAP_HOST env)")

        enc = self.imap_encryption
        if enc == "none":
            conn = imaplib.IMAP4(self.imap_host, self.imap_port)
        elif enc == "starttls":
            conn = imaplib.IMAP4(self.imap_host, self.imap_port)
            conn.starttls()
        elif enc == "tls":
            conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        else:
            # Unknown value — fall back to historical port-based logic so
            # a typo doesn't break a working deployment.
            if self.imap_port == 993:
                conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
            else:
                conn = imaplib.IMAP4(self.imap_host, self.imap_port)
                if self.use_tls:
                    conn.starttls()

        if self.imap_username and self.imap_password:
            conn.login(self.imap_username, self.imap_password)
        return conn

    def inbox(self, folder: str = "INBOX", limit: int = 20,
              offset: int = 0) -> list[dict]:
        """Fetch latest messages from a folder.

        Returns list of dicts: {uid, subject, from, to, date, snippet, seen}

        Raises MessengerConnectionError on a connection/auth/protocol failure.
        A successful fetch from an empty folder returns [] (that is NOT an error).
        """
        try:
            conn = self._imap_connect()
        except _IMAP_CONNECTION_ERRORS as exc:
            raise _imap_fail("inbox", exc) from exc
        try:
            conn.select(folder, readonly=True)
            status, data = conn.uid("SEARCH", "ALL")
            if status != "OK":
                raise MessengerConnectionError(
                    f"IMAP search returned {status} for folder {folder!r}")
            if not data[0]:
                return []

            uids = data[0].split()
            # Latest first
            uids = list(reversed(uids))
            selected = uids[offset:offset + limit]

            messages = []
            for uid in selected:
                messages.append(self._fetch_header(conn, uid))
            return messages
        except _IMAP_CONNECTION_ERRORS as exc:
            raise _imap_fail("inbox", exc) from exc
        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass

    def unread(self, folder: str = "INBOX") -> int:
        """Return count of unseen messages.

        Raises MessengerConnectionError on a connection/protocol failure.
        A successful query with no unseen messages returns 0 (not an error).
        """
        try:
            conn = self._imap_connect()
        except _IMAP_CONNECTION_ERRORS as exc:
            raise _imap_fail("unread", exc) from exc
        try:
            conn.select(folder, readonly=True)
            status, data = conn.uid("SEARCH", "UNSEEN")
            if status != "OK":
                raise MessengerConnectionError(
                    f"IMAP search returned {status} for folder {folder!r}")
            if not data[0]:
                return 0
            return len(data[0].split())
        except _IMAP_CONNECTION_ERRORS as exc:
            raise _imap_fail("unread", exc) from exc
        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass

    def read(self, uid: str | bytes, folder: str = "INBOX",
             mark_read: bool = True) -> dict | None:
        """Read a single message by UID.

        Returns: {uid, subject, from, to, cc, date, body_text, body_html, attachments, headers}

        Raises MessengerConnectionError on a connection/protocol failure.
        A successful fetch for a non-existent UID returns None (not an error, and
        not {} — an empty dict is falsy but `result is None` gets it wrong, and it
        serialises to `{}` where the other frameworks carry `null`). G2.
        """
        if isinstance(uid, str):
            uid = uid.encode()
        try:
            conn = self._imap_connect()
        except _IMAP_CONNECTION_ERRORS as exc:
            raise _imap_fail("read", exc) from exc
        try:
            conn.select(folder, readonly=not mark_read)
            status, data = conn.uid("FETCH", uid, "(RFC822)")
            if status != "OK":
                raise MessengerConnectionError(
                    f"IMAP fetch returned {status} for uid {uid!r}")
            if not data or not data[0]:
                return None

            raw = data[0][1] if isinstance(data[0], tuple) else data[0]
            msg = BytesParser(policy=policy.default).parsebytes(raw)

            if mark_read:
                conn.uid("STORE", uid, "+FLAGS", "(\\Seen)")

            return self._parse_message(uid, msg)
        except _IMAP_CONNECTION_ERRORS as exc:
            raise _imap_fail("read", exc) from exc
        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass

    def search(self, folder: str = "INBOX", subject: str = None,
               sender: str = None, since: str = None, before: str = None,
               unseen_only: bool = False, limit: int = 50) -> list[dict]:
        """Search messages using IMAP search criteria.

        Args:
            subject: Search in subject line
            sender: Search by sender address
            since: Date string "DD-Mon-YYYY" (e.g. "01-Jan-2025")
            before: Date string "DD-Mon-YYYY"
            unseen_only: Only unseen messages
            limit: Max results

        Raises MessengerConnectionError on a connection/protocol failure.
        A successful search with no matches returns [] (not an error).
        """
        try:
            conn = self._imap_connect()
        except _IMAP_CONNECTION_ERRORS as exc:
            raise _imap_fail("search", exc) from exc
        try:
            conn.select(folder, readonly=True)

            criteria = []
            if unseen_only:
                criteria.append("UNSEEN")
            if subject:
                criteria.append(f'SUBJECT "{subject}"')
            if sender:
                criteria.append(f'FROM "{sender}"')
            if since:
                criteria.append(f'SINCE {since}')
            if before:
                criteria.append(f'BEFORE {before}')

            search_str = " ".join(criteria) if criteria else "ALL"
            status, data = conn.uid("SEARCH", search_str)
            if status != "OK":
                raise MessengerConnectionError(
                    f"IMAP search returned {status} for folder {folder!r}")
            if not data[0]:
                return []

            uids = list(reversed(data[0].split()))[:limit]
            messages = []
            for uid in uids:
                messages.append(self._fetch_header(conn, uid))
            return messages
        except _IMAP_CONNECTION_ERRORS as exc:
            raise _imap_fail("search", exc) from exc
        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass

    def mark_read(self, uid: str | bytes, folder: str = "INBOX"):
        """Mark a message as read."""
        self._set_flag(uid, folder, "+FLAGS", "\\Seen")

    def mark_unread(self, uid: str | bytes, folder: str = "INBOX"):
        """Mark a message as unread."""
        self._set_flag(uid, folder, "-FLAGS", "\\Seen")

    def delete(self, uid: str | bytes, folder: str = "INBOX"):
        """Mark a message for deletion and expunge."""
        if isinstance(uid, str):
            uid = uid.encode()
        conn = self._imap_connect()
        try:
            conn.select(folder)
            conn.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
            conn.expunge()
        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass

    def folders(self) -> list[str]:
        """List all mailbox folders.

        Raises MessengerConnectionError on a connection/protocol failure.
        """
        try:
            conn = self._imap_connect()
        except _IMAP_CONNECTION_ERRORS as exc:
            raise _imap_fail("folders", exc) from exc
        try:
            status, data = conn.list()
            if status != "OK":
                raise MessengerConnectionError(
                    f"IMAP list returned {status}")
            result = []
            for item in data:
                if isinstance(item, bytes):
                    # Parse: (\\HasNoChildren) "/" "INBOX"
                    match = re.search(rb'"([^"]+)"$', item)
                    if match:
                        result.append(match.group(1).decode())
                    else:
                        parts = item.decode().rsplit(" ", 1)
                        if parts:
                            result.append(parts[-1].strip('"'))
            return result
        except _IMAP_CONNECTION_ERRORS as exc:
            raise _imap_fail("folders", exc) from exc
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def _set_flag(self, uid: str | bytes, folder: str, action: str, flag: str):
        if isinstance(uid, str):
            uid = uid.encode()
        conn = self._imap_connect()
        try:
            conn.select(folder)
            conn.uid("STORE", uid, action, f"({flag})")
        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass

    @staticmethod
    def _iso_date(msg) -> str:
        """The message Date as ISO-8601, or "" when absent/unparseable."""
        if msg["Date"]:
            try:
                # Normalise to UTC. parsedate_to_datetime preserves the SENDER's
                # offset, so the same message read on a +02:00 host printed
                # +02:00 while PHP/Ruby (also +00:00) and Node (Z) emitted UTC -
                # a host-dependent string for the same instant. MEASURED against
                # live GreenMail in the four-way parity check.
                dt = parsedate_to_datetime(msg["Date"])
                if dt.tzinfo is not None:
                    dt = dt.astimezone(timezone.utc)
                return dt.isoformat()
            except Exception:
                return str(msg["Date"])
        return ""

    @staticmethod
    def _extract_bodies(msg) -> tuple[str, str, list[dict]]:
        """Walk a parsed message into (body_text, body_html, attachments).

        ``get_payload(decode=True)`` TRANSFER-decodes each part (base64 /
        quoted-printable → raw bytes), which is exactly what the snippet and the
        read() bodies both need. Shared by _fetch_header and _parse_message so the
        two never drift.
        """
        body_text = ""
        body_html = ""
        attachments: list[dict] = []
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get("Content-Disposition", ""))
                if "attachment" in disposition:
                    attachments.append({
                        "filename": part.get_filename() or "attachment",
                        "content_type": content_type,
                        "size": len(part.get_payload(decode=True) or b""),
                        "content": part.get_payload(decode=True),
                    })
                elif content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        body_text = payload.decode("utf-8", errors="replace")
                elif content_type == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        body_html = payload.decode("utf-8", errors="replace")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                text = payload.decode("utf-8", errors="replace")
                if msg.get_content_type() == "text/html":
                    body_html = text
                else:
                    body_text = text
        return body_text, body_html, attachments

    @staticmethod
    def _make_snippet(body_text: str, body_html: str) -> str:
        """A decoded, tag-stripped, whitespace-collapsed 200-char preview (G3).

        Prefers the plain-text part; falls back to the HTML with its tags removed.
        The input is already transfer-decoded by _extract_bodies, so this is real
        readable text, never the raw base64 the partial-fetch path used to emit.
        """
        text = body_text or body_html or ""
        text = re.sub(r"<[^>]+>", " ", text)          # strip any HTML tags
        text = re.sub(r"\s+", " ", text).strip()      # collapse whitespace
        return text[:200]

    def _fetch_header(self, conn, uid: bytes) -> dict:
        """Fetch the listing fields for one message: {uid, subject, from, to,
        date (ISO-8601), snippet, seen} — exactly these seven keys (G4).

        Fetches the whole message with BODY.PEEK[] and parses it so the snippet is
        transfer-decoded (G3). The partial BODY.PEEK[TEXT]<0.200> it replaced could
        only ever hand back the RAW first 200 bytes — base64 for a base64-encoded
        part, i.e. gibberish.

        tina4: full-message fetch per listing row. inbox()/search() are bounded
        (default limit 20), so this is correct-first and cheap in practice; the
        upgrade if it ever gets hot is a BODYSTRUCTURE-guided single-part fetch.
        """
        empty = {"uid": uid.decode(), "subject": "", "from": "", "to": "",
                 "date": "", "snippet": "", "seen": False}
        status, data = conn.uid("FETCH", uid, "(FLAGS BODY.PEEK[])")
        if status != "OK" or not data:
            return empty

        raw = b""
        flags_str = ""
        for part in data:
            if isinstance(part, tuple):
                desc = part[0].decode("utf-8", errors="replace") if isinstance(part[0], bytes) else str(part[0])
                if "FLAGS" in desc:
                    flags_str = desc
                if part[1]:
                    raw = part[1]
            elif isinstance(part, bytes):
                s = part.decode("utf-8", errors="replace")
                if "FLAGS" in s:
                    flags_str = s

        if not raw:
            return empty

        msg = BytesParser(policy=policy.default).parsebytes(raw)
        body_text, body_html, _ = self._extract_bodies(msg)
        return {
            "uid": uid.decode(),
            "subject": str(msg.get("Subject", "")),
            "from": str(msg.get("From", "")),
            "to": str(msg.get("To", "")),
            "date": self._iso_date(msg),
            "snippet": self._make_snippet(body_text, body_html),
            "seen": "\\Seen" in flags_str,
        }

    def _parse_message(self, uid: bytes, msg) -> dict:
        """Parse a full email message into the read() dict — EXACTLY the ten
        canonical keys {uid, subject, from, to, cc, date, body_text, body_html,
        attachments, headers}, no more (ADR-0042; messenger_contract
        msg-read-item-shape). Message-ID lives in ``headers``.

        Each attachment is {filename, content_type, size, content} where
        ``content`` is the RAW DECODED BYTES of the part (same convention as
        request.files[x]["content"] — bytes, not base64) and ``size`` is that
        byte length. The bytes live INSIDE ``attachments``; there is no separate
        ``attachments_data`` carrier (folded away in 3.13.96).
        """
        body_text, body_html, attachments = self._extract_bodies(msg)
        return {
            "uid": uid.decode() if isinstance(uid, bytes) else str(uid),
            "subject": str(msg.get("Subject", "")),
            "from": str(msg.get("From", "")),
            "to": str(msg.get("To", "")),
            "cc": str(msg.get("Cc", "") or ""),
            "date": self._iso_date(msg),
            "body_text": body_text,
            "body_html": body_html,
            "attachments": attachments,
            "headers": dict(msg.items()),
        }

    def test_connection(self) -> dict:
        """Test SMTP connectivity without sending."""
        try:
            if self.port == 465:
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=10)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=10)
                if self.use_tls:
                    server.starttls()
            if self.username and self.password:
                server.login(self.username, self.password)
            server.quit()
            return {"success": True, "error": None}
        except Exception as e:
            return {"success": False, "error": str(e)}


    def test_imap_connection(self) -> dict:
        """Test IMAP connectivity without reading."""
        try:
            conn = self._imap_connect()
            conn.logout()
            return {"success": True, "error": None}
        except Exception as e:
            return {"success": False, "error": str(e)}


class DevMailbox:
    """Local file-based mailbox for development — captures emails instead of sending.

    In dev mode (TINA4_DEBUG=true), Messenger uses this instead of SMTP.
    All "sent" messages are stored in data/mailbox/ as JSON files and can be
    browsed via the dev admin panel at /__dev/mailbox.

    Also supports seeding fake inbox messages for testing.

        mailbox = DevMailbox()
        mailbox.inbox()                          # list all messages
        mailbox.read("msg_id")                   # read a specific message
        mailbox.seed(5)                          # generate 5 fake messages
        mailbox.clear()                          # delete all messages
    """

    def __init__(self, mailbox_dir: str = None):
        self.mailbox_dir = Path(
            mailbox_dir or os.environ.get("TINA4_MAILBOX_DIR", "data/mailbox")
        )
        self.mailbox_dir.mkdir(parents=True, exist_ok=True)
        self._outbox_dir = self.mailbox_dir / "outbox"
        self._inbox_dir = self.mailbox_dir / "inbox"
        self._outbox_dir.mkdir(exist_ok=True)
        self._inbox_dir.mkdir(exist_ok=True)

    def capture(self, to: str | list[str], subject: str, body: str,
                html: bool = False, text: str = None,
                cc: str | list[str] = None,
                bcc: str | list[str] = None, reply_to: str = None,
                from_address: str = "", from_name: str = "",
                attachments: list = None) -> dict:
        """Capture a message to the local outbox (instead of sending via SMTP).

        The parameter order MATCHES ``Messenger.send`` on purpose. It did not
        before: send's 5th positional was ``text`` and capture's was ``cc``, so the
        same call meant different things depending on which door it came through --
        that mismatch IS tina4-nodejs#42.

        BREAKING: ``text`` is now the 5th positional. A caller passing ``cc``
        positionally must switch to the keyword form. Aligning the two signatures
        is the fix; leaving them apart would preserve the bug.

        cc/bcc are normalised HERE, at the boundary, so a message is well formed
        however it arrived. Normalising in one caller only (which is what Python
        did -- in dev_send, never in capture) means a direct caller stores a
        malformed message and is told it succeeded, and a dev mailbox that accepts
        a broken message defeats its own purpose.
        """
        msg_id = f"{int(time.time() * 1000)}_{id(subject) & 0xFFFF:04x}"
        to_list = [to] if isinstance(to, str) else list(to)
        cc_list = [cc] if isinstance(cc, str) else list(cc or [])
        bcc_list = [bcc] if isinstance(bcc, str) else list(bcc or [])

        message = {
            "id": msg_id,
            "type": "outbox",
            "from": f"{from_name} <{from_address}>" if from_name else from_address,
            "to": to_list,
            "cc": cc_list,
            "bcc": bcc_list,
            "reply_to": reply_to or "",
            "subject": subject,
            "body": body,
            "text": text,
            "html": html,
            "attachments": [
                a if isinstance(a, str) else a.get("filename", "attachment")
                for a in (attachments or [])
            ],
            "date": datetime.now(timezone.utc).isoformat(),
            "read": False,
        }

        (self._outbox_dir / f"{msg_id}.json").write_text(
            json.dumps(message, indent=2, default=str), encoding="utf-8"
        )

        # One send() result shape on both paths (G6): {success, message, id}.
        # The capture id is the local mailbox id — the best "id" a message that
        # never hit SMTP can have. No capture-only `dev` key.
        return {"success": True, "message": None, "id": msg_id}

    def inbox(self, limit: int = 50, offset: int = 0,
              folder: str = None) -> list[dict]:
        """List messages from inbox or outbox (all local mail)."""
        target = self._inbox_dir if folder == "inbox" else None
        messages = []

        # Collect from both dirs unless folder specified
        dirs = []
        if folder == "inbox":
            dirs = [self._inbox_dir]
        elif folder == "outbox":
            dirs = [self._outbox_dir]
        else:
            dirs = [self._outbox_dir, self._inbox_dir]

        for d in dirs:
            for f in d.glob("*.json"):
                try:
                    msg = json.loads(f.read_text(encoding="utf-8"))
                    messages.append(msg)
                except (json.JSONDecodeError, OSError):
                    pass

        # Sort newest first
        messages.sort(key=lambda m: m.get("date", ""), reverse=True)
        return messages[offset:offset + limit]

    def read(self, msg_id: str) -> dict:
        """Read a specific message by ID."""
        for d in [self._outbox_dir, self._inbox_dir]:
            path = d / f"{msg_id}.json"
            if path.exists():
                msg = json.loads(path.read_text(encoding="utf-8"))
                msg["read"] = True
                path.write_text(json.dumps(msg, indent=2, default=str), encoding="utf-8")
                return msg
        return {}

    def unread_count(self) -> int:
        """Count unread messages across all folders."""
        count = 0
        for d in [self._outbox_dir, self._inbox_dir]:
            for f in d.glob("*.json"):
                try:
                    msg = json.loads(f.read_text(encoding="utf-8"))
                    if not msg.get("read", False):
                        count += 1
                except (json.JSONDecodeError, OSError):
                    pass
        return count

    def delete(self, msg_id: str) -> bool:
        """Delete a message."""
        for d in [self._outbox_dir, self._inbox_dir]:
            path = d / f"{msg_id}.json"
            if path.exists():
                path.unlink()
                return True
        return False

    def clear(self, folder: str = None):
        """Delete all messages."""
        dirs = []
        if folder == "inbox":
            dirs = [self._inbox_dir]
        elif folder == "outbox":
            dirs = [self._outbox_dir]
        else:
            dirs = [self._outbox_dir, self._inbox_dir]

        for d in dirs:
            for f in d.glob("*.json"):
                f.unlink()

    def seed(self, count: int = 5, seed: int = None) -> int:
        """Generate fake inbox messages for development testing.

        Creates realistic-looking incoming emails so developers can test
        email-related UI without needing a real mail server.
        """
        try:
            from tina4_python.seeder import FakeData
        except ImportError:
            return 0

        fake = FakeData(seed=seed)
        created = 0

        for i in range(count):
            msg_id = f"fake_{int(time.time() * 1000) + i}_{fake.integer(1000, 9999)}"
            sender_name = fake.name()
            sender_email = fake.email()
            subject_prefixes = [
                "Re: ", "Fwd: ", "", "", "", "Urgent: ", "Meeting: ",
                "Invoice ", "Update: ", "Question about ",
            ]
            subject = fake.choice(subject_prefixes) + fake.sentence(4).rstrip(".")

            body_html = (
                f"<p>Hi,</p>"
                f"<p>{fake.paragraph(2)}</p>"
                f"<p>{fake.paragraph(1)}</p>"
                f"<p>Best regards,<br>{sender_name}</p>"
            )

            message = {
                "id": msg_id,
                "type": "inbox",
                "from": f"{sender_name} <{sender_email}>",
                "to": [os.environ.get("TINA4_MAIL_FROM", "dev@localhost")],
                "cc": [],
                "bcc": [],
                "reply_to": sender_email,
                "subject": subject,
                "body": body_html,
                "html": True,
                "attachments": [],
                "date": fake.datetime_iso(),
                "read": fake.boolean(),
            }

            (self._inbox_dir / f"{msg_id}.json").write_text(
                json.dumps(message, indent=2, default=str), encoding="utf-8"
            )
            created += 1

        return created

    def count(self, folder: str = None) -> dict:
        """Get message counts."""
        outbox = len(list(self._outbox_dir.glob("*.json")))
        inbox = len(list(self._inbox_dir.glob("*.json")))
        if folder == "outbox":
            return {"total": outbox}
        if folder == "inbox":
            return {"total": inbox}
        return {"inbox": inbox, "outbox": outbox, "total": inbox + outbox}


def _is_dev_mode() -> bool:
    """Check if running in development/debug mode."""
    from tina4_python.dotenv import is_truthy
    return is_truthy(os.environ.get("TINA4_DEBUG", ""))


def create_messenger(**kwargs) -> Messenger:
    """Factory that returns a Messenger configured for the current environment.

    Returns ONE concrete type, always. When sending is impossible (no SMTP host
    configured) or suppressed (``TINA4_MAIL_CAPTURE``), ``send()`` captures to a
    local ``DevMailbox`` instead -- decided by a branch inside ``send()``, so the
    object you get back has one ``send`` with one signature either way.

    It no longer replaces ``send`` on the instance. That swap installed a function
    with a DIFFERENT signature than ``Messenger.send`` under the same name, which
    is how the documented call ``send(to, subj, body, True, "plain text")`` came to
    file the plain-text body as a CC recipient and report success.
    """
    messenger = Messenger(**kwargs)

    # Attach the mailbox eagerly when this messenger will capture, so callers can
    # inspect it (and the dev admin panel can list it) before the first send.
    if messenger._should_capture():
        messenger.dev_mailbox = DevMailbox()

    return messenger


__all__ = [
    "Messenger",
    "MessengerError",
    "MessengerConnectionError",
    "DevMailbox",
    "create_messenger",
]
