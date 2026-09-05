# Feature 140: Web Push

Web Push is a standalone outbound integration. It is not WebSocket, Server-Sent Events, or a realtime backplane.

Enable it with `TINA4_WEB_PUSH=true`, `TINA4_VAPID_SUBJECT`, `TINA4_VAPID_PUBLIC`, and `TINA4_VAPID_PRIVATE`. Python's core stays dependency-free; install `tina4-python[push]` only when the project uses Web Push.

```python
from tina4_python import Push
result = Push().send(subscription, {"title": "Order ready", "body": "Order 123 is ready"})
```

The sender reads the VAPID environment keys, produces VAPID ES256 authorization and RFC 8291 `aes128gcm` payloads, and fails loudly when configuration or the optional crypto capability is missing. Results expose `ok`, `status`, `dead`, `retryable`, `endpoint`, and `response`; 404/410 are dead subscriptions and 408, 429, and 5xx are retryable.
