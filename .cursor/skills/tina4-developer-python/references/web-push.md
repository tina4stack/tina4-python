# Feature 140: Web Push

Web Push is a standalone outbound integration. It is not WebSocket, Server-Sent Events, or a realtime backplane.

Enable it with configuration:

```env
TINA4_WEB_PUSH=true
TINA4_VAPID_SUBJECT=mailto:ops@example.com
TINA4_VAPID_PUBLIC=<base64url P-256 public key>
TINA4_VAPID_PRIVATE=<base64url P-256 private key>
```

Python's core stays dependency-free. Install the optional capability only when the project uses Web Push:

```bash
pip install tina4-python[push]
```

```python
from tina4_python import Push

sender = Push()  # reads TINA4_VAPID_* from the environment
result = sender.send(subscription, {"title": "Order ready", "body": "Order 123 is ready"})
```

The sender produces VAPID ES256 authorization and RFC 8291 `aes128gcm` payloads. A configured feature with missing keys or crypto capability fails loudly. The result exposes `ok`, `status`, `dead`, `retryable`, `endpoint`, and `response`; HTTP 404/410 are dead subscriptions, while 408, 429, and 5xx are retryable.
