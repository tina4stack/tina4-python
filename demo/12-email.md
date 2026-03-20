# Email

Tina4's `Messenger` class handles email sending (SMTP) and reading (IMAP) using Python stdlib only. It supports plain text, HTML, attachments, CC/BCC, Reply-To, TLS/STARTTLS, and environment-based configuration.

## Sending Email

### Plain Text

```python
from tina4_python.messenger import Messenger

mail = Messenger(
    host="smtp.gmail.com",
    port=587,
    username="you@gmail.com",
    password="app-password",
)

result = mail.send(
    to="alice@example.com",
    subject="Hello from Tina4",
    body="This is a plain text email.",
)

if result["success"]:
    print(f"Sent! Message ID: {result['message_id']}")
else:
    print(f"Failed: {result['error']}")
```

### HTML Email

```python
result = mail.send(
    to="alice@example.com",
    subject="Welcome!",
    body="<h1>Welcome to Our App</h1><p>Thanks for signing up.</p>",
    html=True,
)
```

### Multiple Recipients, CC, BCC

```python
result = mail.send(
    to=["alice@example.com", "bob@example.com"],
    subject="Team Update",
    body="Weekly report attached.",
    cc=["manager@example.com"],
    bcc=["archive@example.com"],
    reply_to="support@example.com",
)
```

### Attachments

```python
# From file path
result = mail.send(
    to="alice@example.com",
    subject="Report",
    body="Please find the report attached.",
    attachments=["reports/monthly.pdf", "data/export.csv"],
)

# From bytes
result = mail.send(
    to="alice@example.com",
    subject="Generated Report",
    body="See attached.",
    attachments=[{
        "filename": "report.pdf",
        "content": pdf_bytes,
        "mime": "application/pdf",
    }],
)
```

### Custom Headers

```python
mail.add_header("X-Mailer", "Tina4 App")
mail.add_header("X-Priority", "1")
```

## Reading Email (IMAP)

```python
mail = Messenger(
    imap_host="imap.gmail.com",
    imap_port=993,
    username="you@gmail.com",
    password="app-password",
)

# Read inbox (latest messages)
messages = mail.inbox(limit=10)
for msg in messages:
    print(f"From: {msg['from']}, Subject: {msg['subject']}")

# Read unread messages
unread = mail.unread()

# Read a specific message
message = mail.read(message_id)

# Search
results = mail.search("FROM alice@example.com")
results = mail.search("SUBJECT report")
```

## Environment Configuration

Instead of passing credentials in code, use `.env` variables:

```bash
# .env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=you@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=you@gmail.com
SMTP_FROM_NAME=My App

IMAP_HOST=imap.gmail.com
IMAP_PORT=993
```

Then create a Messenger with no arguments:

```python
mail = Messenger()  # Reads from environment variables
```

## Send Response Format

```python
{
    "success": True,          # Boolean
    "error": None,            # None on success, error message on failure
    "message_id": "<abc123>"  # SMTP message ID
}
```

## Queue-Based Email

For production, always send emails through a queue to avoid blocking requests.

```python
from tina4_python.core.router import post
from tina4_python.queue import Queue, Producer

@post("/api/invite")
async def invite(request, response):
    Producer(Queue(db, topic="emails")).push({
        "to": request.body["email"],
        "subject": "You're Invited!",
        "body": f"<h1>Hello {request.body['name']}</h1>",
        "html": True,
    })
    return response({"sent": True})

# worker.py
from tina4_python.messenger import Messenger
from tina4_python.queue import Queue, Consumer

mail = Messenger()

def send_email(job):
    result = mail.send(**job.data)
    if result["success"]:
        job.complete()
    else:
        job.fail(result["error"])

Consumer(Queue(db, topic="emails"), callback=send_email).run()
```

## Tips

- Use app-specific passwords for Gmail (not your main password).
- Always use TLS (`use_tls=True`, which is the default).
- For HTML emails, include a plain text fallback for accessibility.
- Send emails via a queue in production -- never block route handlers.
- Store credentials in `.env`, not in source code.
