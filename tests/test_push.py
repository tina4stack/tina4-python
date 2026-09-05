"""Feature 140 Web Push contract tests against a real local HTTP endpoint."""
import base64
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from tina4_python.push import Push, PushError, generate_vapid_keys


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def test_vapid_keys_and_real_delivery():
    cryptography = pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            received["headers"] = self.headers
            received["body"] = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(201)
            self.end_headers()
            self.wfile.write(b"accepted")

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = ec.generate_private_key(ec.SECP256R1())
        public = client.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        keys = generate_vapid_keys()
        subscription = {
            "endpoint": f"http://127.0.0.1:{server.server_port}/push",
            "keys": {"p256dh": _b64(public), "auth": _b64(bytes([7]) * 16)},
        }
        result = Push(subject="mailto:test@tina4.com", public_key=keys["publicKey"], private_key=keys["privateKey"]).send(subscription, {"message": "hello"})
        assert result.ok is True
        assert result.status == 201
        assert result.dead is False
        assert result.retryable is False
        assert received["headers"]["Content-Encoding"] == "aes128gcm"
        assert received["body"]
    finally:
        server.shutdown()


def test_missing_vapid_configuration_fails_loudly(monkeypatch):
    for name in ("TINA4_VAPID_SUBJECT", "TINA4_VAPID_PUBLIC", "TINA4_VAPID_PRIVATE"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(PushError, match="TINA4_VAPID"):
        Push().send({"endpoint": "http://127.0.0.1/push", "keys": {"p256dh": "x", "auth": "x"}}, "payload")


def test_dead_and_retryable_responses_are_classified():
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            received["status"] = int(self.path.split("status=", 1)[1])
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(received["status"])
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        keys = generate_vapid_keys()
        client = ec.generate_private_key(ec.SECP256R1())
        public = client.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        subscription = lambda status: {
            "endpoint": f"http://127.0.0.1:{server.server_port}/push?status={status}",
            "keys": {"p256dh": _b64(public), "auth": _b64(bytes([7]) * 16)},
        }
        sender = Push(subject="mailto:test@tina4.com", public_key=keys["publicKey"], private_key=keys["privateKey"])
        for status in (404, 410):
            dead = sender.send(subscription(status), "expired")
            assert dead.ok is False and dead.status == status and dead.dead is True and dead.retryable is False
        retry = sender.send(subscription(429), "busy")
        assert retry.ok is False and retry.status == 429 and retry.dead is False and retry.retryable is True
        retry = sender.send(subscription(500), "busy")
        assert retry.ok is False and retry.status == 500 and retry.dead is False and retry.retryable is True
    finally:
        server.shutdown()


def test_invalid_subscription_key_fails_before_delivery():
    pytest.importorskip("cryptography")
    keys = generate_vapid_keys()
    sender = Push(subject="mailto:test@tina4.com", public_key=keys["publicKey"], private_key=keys["privateKey"])
    with pytest.raises(PushError, match="subscription.keys.p256dh"):
        sender.send({"endpoint": "http://127.0.0.1/push", "keys": {"p256dh": "bad", "auth": _b64(bytes([7]) * 16)}}, "payload")
