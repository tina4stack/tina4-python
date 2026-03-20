# Tina4 Messenger — Zero-dependency email via stdlib smtplib + imaplib.
"""
Send and read email using Python's built-in smtplib, imaplib, and email modules.

    from tina4_python.messenger import Messenger

    # Send
    mail = Messenger(host="smtp.gmail.com", port=587, username="...", password="...")
    mail.send(to="user@example.com", subject="Hello", body="<h1>Welcome!</h1>", html=True)

    # Read
    mail = Messenger(imap_host="imap.gmail.com", imap_port=993, username="...", password="...")
    messages = mail.inbox(limit=10)
    message = mail.read(message_id)
    unread = mail.unread()

Supported:
    - Plain text and HTML emails (send)
    - Attachments (file path or bytes)
    - CC, BCC recipients
    - Reply-To header
    - Template rendering (via Frond engine)
    - TLS / STARTTLS
    - IMAP inbox reading, search, mark read/unread, delete
    - Environment variable configuration
"""
import os
import re
import json
import time
import smtplib
import imaplib
import mimetypes
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders, policy
from email.parser import BytesParser
from email.utils import formataddr, formatdate, parsedate_to_datetime
from pathlib import Path
from datetime import datetime, timezone


class MessengerError(Exception):
    """Raised on send failure."""
    pass


class Messenger:
    """SMTP email client using Python stdlib."""

    def __init__(self, host: str = None, port: int = None,
                 username: str = None, password: str = None,
                 from_address: str = None, from_name: str = None,
                 use_tls: bool = True,
                 imap_host: str = None, imap_port: int = None):
        # SMTP (send)
        self.host = host or os.environ.get("SMTP_HOST", "localhost")
        self.port = port or int(os.environ.get("SMTP_PORT", "587"))
        self.username = username or os.environ.get("SMTP_USERNAME", "")
        self.password = password or os.environ.get("SMTP_PASSWORD", "")
        self.from_address = from_address or os.environ.get("SMTP_FROM", self.username)
        self.from_name = from_name or os.environ.get("SMTP_FROM_NAME", "")
        self.use_tls = use_tls
        self._default_headers: dict[str, str] = {}
        # IMAP (read)
        self.imap_host = imap_host or os.environ.get("IMAP_HOST", "")
        self.imap_port = imap_port or int(os.environ.get("IMAP_PORT", "993"))

    def add_header(self, name: str, value: str):
        """Add a default header to all outgoing emails."""
        self._default_headers[name] = value

    def send(self, to: str | list[str], subject: str, body: str,
             html: bool = False, cc: str | list[str] = None,
             bcc: str | list[str] = None, reply_to: str = None,
             attachments: list = None, headers: dict = None) -> dict:
        """Send an email.

        Args:
            to: Recipient(s)
            subject: Email subject
            body: Email body (plain text or HTML)
            html: If True, body is HTML
            cc: CC recipient(s)
            bcc: BCC recipient(s)
            reply_to: Reply-To address
            attachments: List of file paths (str/Path) or dicts {"filename": ..., "content": bytes, "mime": ...}
            headers: Additional headers

        Returns:
            {"success": True/False, "error": None or str, "message_id": str or None}
        """
        to_list = [to] if isinstance(to, str) else list(to)
        cc_list = [cc] if isinstance(cc, str) else list(cc or [])
        bcc_list = [bcc] if isinstance(bcc, str) else list(bcc or [])

        has_attachments = bool(attachments)

        if has_attachments:
            msg = MIMEMultipart("mixed")
            if html:
                msg.attach(MIMEText(body, "html", "utf-8"))
            else:
                msg.attach(MIMEText(body, "plain", "utf-8"))
        else:
            subtype = "html" if html else "plain"
            msg = MIMEText(body, subtype, "utf-8")

        # Headers
        msg["Subject"] = subject
        msg["From"] = formataddr((self.from_name, self.from_address))
        msg["To"] = ", ".join(to_list)
        msg["Date"] = formatdate(localtime=True)

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
            return {"success": True, "error": None, "message_id": message_id}
        except Exception as e:
            return {"success": False, "error": str(e), "message_id": None}

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
            from tina4_python.frond import Frond
            engine = Frond()
            body = engine.render_string(template, data or {})
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
        """Connect and authenticate to the IMAP server."""
        if not self.imap_host:
            raise MessengerError("IMAP host not configured (set imap_host or IMAP_HOST env)")
        if self.imap_port == 993:
            conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        else:
            conn = imaplib.IMAP4(self.imap_host, self.imap_port)
            if self.use_tls:
                conn.starttls()
        if self.username and self.password:
            conn.login(self.username, self.password)
        return conn

    def inbox(self, folder: str = "INBOX", limit: int = 20,
              offset: int = 0) -> list[dict]:
        """Fetch latest messages from a folder.

        Returns list of dicts: {uid, subject, from, to, date, snippet, seen}
        """
        conn = self._imap_connect()
        try:
            conn.select(folder, readonly=True)
            status, data = conn.search(None, "ALL")
            if status != "OK" or not data[0]:
                return []

            uids = data[0].split()
            # Latest first
            uids = list(reversed(uids))
            selected = uids[offset:offset + limit]

            messages = []
            for uid in selected:
                messages.append(self._fetch_header(conn, uid))
            return messages
        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass

    def unread(self, folder: str = "INBOX") -> int:
        """Return count of unseen messages."""
        conn = self._imap_connect()
        try:
            conn.select(folder, readonly=True)
            status, data = conn.search(None, "UNSEEN")
            if status != "OK" or not data[0]:
                return 0
            return len(data[0].split())
        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass

    def read(self, uid: str | bytes, folder: str = "INBOX",
             mark_read: bool = True) -> dict:
        """Read a single message by UID.

        Returns: {uid, subject, from, to, cc, date, body_text, body_html, attachments, headers}
        """
        if isinstance(uid, str):
            uid = uid.encode()
        conn = self._imap_connect()
        try:
            conn.select(folder, readonly=not mark_read)
            status, data = conn.fetch(uid, "(RFC822)")
            if status != "OK" or not data or not data[0]:
                return {}

            raw = data[0][1] if isinstance(data[0], tuple) else data[0]
            msg = BytesParser(policy=policy.default).parsebytes(raw)

            if mark_read:
                conn.store(uid, "+FLAGS", "\\Seen")

            return self._parse_message(uid, msg)
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
        """
        conn = self._imap_connect()
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
            status, data = conn.search(None, search_str)
            if status != "OK" or not data[0]:
                return []

            uids = list(reversed(data[0].split()))[:limit]
            messages = []
            for uid in uids:
                messages.append(self._fetch_header(conn, uid))
            return messages
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
            conn.store(uid, "+FLAGS", "\\Deleted")
            conn.expunge()
        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass

    def folders(self) -> list[str]:
        """List all mailbox folders."""
        conn = self._imap_connect()
        try:
            status, data = conn.list()
            if status != "OK":
                return []
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
            conn.store(uid, action, flag)
        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass

    def _fetch_header(self, conn, uid: bytes) -> dict:
        """Fetch just headers + snippet for a message."""
        status, data = conn.fetch(uid, "(FLAGS BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.200>)")
        if status != "OK" or not data:
            return {"uid": uid.decode(), "subject": "", "from": "", "date": "", "seen": False}

        # Parse the response parts
        headers_raw = b""
        snippet_raw = b""
        flags_str = ""
        for part in data:
            if isinstance(part, tuple):
                desc = part[0].decode() if isinstance(part[0], bytes) else str(part[0])
                if "HEADER" in desc:
                    headers_raw = part[1]
                elif "TEXT" in desc:
                    snippet_raw = part[1]
                elif "FLAGS" in desc:
                    flags_str = desc
            elif isinstance(part, bytes):
                if b"FLAGS" in part:
                    flags_str = part.decode()

        msg = BytesParser(policy=policy.default).parsebytes(headers_raw)
        seen = "\\Seen" in flags_str

        snippet = snippet_raw.decode("utf-8", errors="replace").strip()[:150]
        # Clean up snippet
        snippet = re.sub(r"<[^>]+>", "", snippet)  # strip HTML tags
        snippet = re.sub(r"\s+", " ", snippet).strip()

        date_str = ""
        if msg["Date"]:
            try:
                date_str = parsedate_to_datetime(msg["Date"]).isoformat()
            except Exception:
                date_str = msg["Date"]

        return {
            "uid": uid.decode(),
            "subject": str(msg.get("Subject", "")),
            "from": str(msg.get("From", "")),
            "to": str(msg.get("To", "")),
            "date": date_str,
            "snippet": snippet,
            "seen": seen,
        }

    def _parse_message(self, uid: bytes, msg) -> dict:
        """Parse a full email message into a dict."""
        body_text = ""
        body_html = ""
        attachments = []

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

        date_str = ""
        if msg["Date"]:
            try:
                date_str = parsedate_to_datetime(msg["Date"]).isoformat()
            except Exception:
                date_str = str(msg["Date"])

        return {
            "uid": uid.decode() if isinstance(uid, bytes) else str(uid),
            "subject": str(msg.get("Subject", "")),
            "from": str(msg.get("From", "")),
            "to": str(msg.get("To", "")),
            "cc": str(msg.get("Cc", "") or ""),
            "date": date_str,
            "body_text": body_text,
            "body_html": body_html,
            "attachments": [{k: v for k, v in a.items() if k != "content"} for a in attachments],
            "attachments_data": attachments,
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

    In dev mode (TINA4_DEBUG_LEVEL=DEBUG), Messenger uses this instead of SMTP.
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
                html: bool = False, cc: list[str] = None,
                bcc: list[str] = None, reply_to: str = None,
                from_address: str = "", from_name: str = "",
                attachments: list = None) -> dict:
        """Capture a message to the local outbox (instead of sending via SMTP)."""
        msg_id = f"{int(time.time() * 1000)}_{id(subject) & 0xFFFF:04x}"
        to_list = [to] if isinstance(to, str) else list(to)

        message = {
            "id": msg_id,
            "type": "outbox",
            "from": f"{from_name} <{from_address}>" if from_name else from_address,
            "to": to_list,
            "cc": cc or [],
            "bcc": bcc or [],
            "reply_to": reply_to or "",
            "subject": subject,
            "body": body,
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

        return {"success": True, "error": None, "message_id": msg_id, "dev": True}

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
            from tina4_python.seeder import Fake
        except ImportError:
            return 0

        fake = Fake(seed=seed)
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
                "to": [os.environ.get("SMTP_FROM", "dev@localhost")],
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
    level = os.environ.get("TINA4_DEBUG_LEVEL", "").upper()
    return level in ("DEBUG", "ALL")


def create_messenger(**kwargs) -> Messenger:
    """Factory that returns a Messenger configured for the current environment.

    In dev mode (TINA4_DEBUG_LEVEL=DEBUG), email sending is intercepted
    by DevMailbox — no SMTP connection needed. The original Messenger.send()
    is replaced with a local capture.
    """
    messenger = Messenger(**kwargs)

    if _is_dev_mode():
        mailbox = DevMailbox()
        # Monkey-patch send to capture locally
        _original_send = messenger.send

        def dev_send(to, subject, body, html=False, cc=None, bcc=None,
                     reply_to=None, attachments=None, headers=None):
            return mailbox.capture(
                to=to, subject=subject, body=body, html=html,
                cc=[cc] if isinstance(cc, str) else (cc or []),
                bcc=[bcc] if isinstance(bcc, str) else (bcc or []),
                reply_to=reply_to,
                from_address=messenger.from_address,
                from_name=messenger.from_name,
                attachments=attachments,
            )

        messenger.send = dev_send
        messenger.dev_mailbox = mailbox

    return messenger


__all__ = ["Messenger", "MessengerError", "DevMailbox", "create_messenger"]
