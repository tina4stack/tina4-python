# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""File-sharing regression suite for tina4_python.realtime (feature "files").

No mocks: LocalStorage hits the real filesystem, the upload/download routes run
through the real multipart parser + HTTP dispatch (TestClient), and the S3
round-trip runs against a real MinIO container when one is reachable (skipped,
never mocked, when it is not).
"""
import socket

import pytest

from tina4_python import realtime
from tina4_python.database import Database
from tina4_python.orm import bind_database
from tina4_python.auth import get_token
from tina4_python.test_client import TestClient
from tina4_python.realtime.storage import (
    LocalStorage, S3Storage, StorageBackend, select_storage, storage_key,
)


@pytest.fixture
def files_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TINA4_SECRET", "realtime-files-test-secret-01234")
    monkeypatch.setenv("TINA4_STORAGE_BACKEND", "local")
    monkeypatch.setenv("TINA4_STORAGE_DIR", str(tmp_path / "store"))
    db = Database("sqlite:///" + str(tmp_path / "database.db"))
    bind_database(db)
    from tina4_python.realtime.models import (
        CHAT_MODELS, Workspace, Channel, ChannelMember,
    )
    for model in CHAT_MODELS:
        model.create_table()
    ws = Workspace(name="Acme", created_at="2026-07-08T00:00:00"); ws.save()
    ch = Channel(workspace_id=ws.id, name="general", kind="public",
                 created_at="2026-07-08T00:00:00"); ch.save()
    ChannelMember(channel_id=ch.id, user_id="1", role="owner").save()
    realtime(features=["files"])
    try:
        yield {"channel": ch, "dir": str(tmp_path / "store")}
    finally:
        db.close()


def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    """Build a multipart/form-data body. files: name -> (filename, mime, bytes)."""
    boundary = "----tina4boundary"
    parts = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(f"{value}\r\n".encode())
    for name, (filename, mime, data) in files.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"; '
            f'filename="{filename}"\r\n'.encode())
        parts.append(f"Content-Type: {mime}\r\n\r\n".encode())
        parts.append(data)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# ── LocalStorage (real filesystem) ──────────────────────────────────

class TestLocalStorage:
    def test_roundtrip_and_delete(self, tmp_path):
        store = LocalStorage(str(tmp_path))
        key = storage_key("report.pdf")
        assert key.endswith(".pdf")
        store.put(key, b"binary-bytes", "application/pdf")
        assert store.exists(key) is True
        assert store.get(key) == b"binary-bytes"
        assert store.url(key) is None          # local has no direct URL
        store.delete(key)
        assert store.exists(key) is False
        assert store.get(key) is None

    def test_rejects_path_traversal(self, tmp_path):
        store = LocalStorage(str(tmp_path))
        assert store.get("../../etc/passwd") is None
        assert store.exists("../../etc/passwd") is False

    def test_select_defaults_to_local(self, monkeypatch):
        monkeypatch.delenv("TINA4_STORAGE_BACKEND", raising=False)
        assert isinstance(select_storage(), LocalStorage)

    def test_select_s3_without_bucket_falls_back_to_local(self, monkeypatch):
        monkeypatch.setenv("TINA4_STORAGE_BACKEND", "s3")
        monkeypatch.delenv("TINA4_STORAGE_BUCKET", raising=False)
        assert isinstance(select_storage(), LocalStorage)


# ── Upload / download routes (real multipart + HTTP dispatch) ───────

class TestFileRoutes:
    def test_member_uploads_then_downloads(self, files_env):
        cid = files_env["channel"].id
        token = get_token({"user_id": 1})
        hdrs = {"Authorization": f"Bearer {token}"}
        client = TestClient()

        body, ctype = _multipart({"channel_id": cid},
                                 {"file": ("hi.txt", "text/plain", b"file-contents")})
        up = client.post("/api/files", body=body,
                         headers={**hdrs, "Content-Type": ctype})
        assert up.status == 201
        meta = up.json()
        assert meta["filename"] == "hi.txt" and meta["size"] == len(b"file-contents")
        assert meta["url"].endswith(meta["key"])

        # A real Attachment row landed, scoped to the channel.
        from tina4_python.realtime.models import Attachment
        row = Attachment.where("storage_key = ?", [meta["key"]], limit=1)[0]
        assert row.channel_id == cid

        # Download returns the exact bytes with the stored content-type.
        down = client.get(f"/api/files/{meta['key']}", headers=hdrs)
        assert down.status == 200
        assert down.body == b"file-contents"
        assert "text/plain" in down.content_type

    def test_non_member_cannot_upload(self, files_env):
        cid = files_env["channel"].id
        token = get_token({"user_id": 9})   # not a member
        body, ctype = _multipart({"channel_id": cid},
                                 {"file": ("x.txt", "text/plain", b"z")})
        res = TestClient().post("/api/files", body=body,
                                headers={"Authorization": f"Bearer {token}",
                                         "Content-Type": ctype})
        assert res.status == 403

    def test_non_member_cannot_download(self, files_env):
        cid = files_env["channel"].id
        owner = get_token({"user_id": 1})
        body, ctype = _multipart({"channel_id": cid},
                                 {"file": ("x.txt", "text/plain", b"secret")})
        up = TestClient().post("/api/files", body=body,
                               headers={"Authorization": f"Bearer {owner}",
                                        "Content-Type": ctype})
        key = up.json()["key"]

        outsider = get_token({"user_id": 9})
        res = TestClient().get(f"/api/files/{key}",
                               headers={"Authorization": f"Bearer {outsider}"})
        assert res.status == 403


# ── S3Storage against a real MinIO (skipped if unreachable) ─────────

MINIO_HOST = "localhost"
MINIO_PORT = 9100
MINIO_BUCKET = "tina4-rt-test"

# S3Storage is now zero-dependency (Tina4's own stdlib SigV4 client, no boto3),
# so the only reason the live-S3 tests cannot run is the MinIO service being
# down. No [needs:X] tag: S3 is an always-provisioned service under the ADR-0069
# gate rule, so under TINA4_REQUIRE_SERVICES this FAILS the run (it does not
# skip). tests/test_require_services_gate.py asserts that against this constant.
MINIO_UNREACHABLE_REASON = (
    f"MinIO not reachable at {MINIO_HOST}:{MINIO_PORT} (real S3, never mocked)")


def _minio_reachable(host=MINIO_HOST, port=MINIO_PORT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _s3_skip_reason() -> str | None:
    """Why the live-S3 tests cannot run, or None when they can."""
    if not _minio_reachable():
        return MINIO_UNREACHABLE_REASON
    return None


_S3_SKIP_REASON = _s3_skip_reason()


@pytest.mark.skipif(_S3_SKIP_REASON is not None, reason=_S3_SKIP_REASON or "")
class TestS3Storage:
    def _store(self, monkeypatch):
        # The CI-provisioned S3 is MinIO on localhost:9100 (minioadmin). The same
        # zero-dependency SigV4 client is also proven against Garage and AWS;
        # only a reachable endpoint is needed, no driver.
        monkeypatch.setenv("TINA4_STORAGE_BACKEND", "s3")
        monkeypatch.setenv("TINA4_STORAGE_URL", f"http://{MINIO_HOST}:{MINIO_PORT}")
        monkeypatch.setenv("TINA4_STORAGE_KEY", "minioadmin")
        monkeypatch.setenv("TINA4_STORAGE_SECRET", "minioadmin")
        monkeypatch.setenv("TINA4_STORAGE_BUCKET", MINIO_BUCKET)
        monkeypatch.setenv("TINA4_STORAGE_REGION", "us-east-1")
        store = select_storage()
        assert isinstance(store, S3Storage)
        try:
            store._client.create_bucket(MINIO_BUCKET)
        except Exception:
            pass  # already exists
        return store

    def test_real_s3_roundtrip_and_presigned_url(self, monkeypatch):
        import urllib.request
        store = self._store(monkeypatch)
        key = storage_key("photo.png")
        store.put(key, b"\x89PNG-real-bytes", "image/png")
        assert store.exists(key) is True
        assert store.get(key) == b"\x89PNG-real-bytes"

        url = store.url(key, ttl=120)
        assert url.startswith("http") and key in url
        # The presigned URL actually fetches the object from MinIO.
        with urllib.request.urlopen(url) as resp:
            assert resp.read() == b"\x89PNG-real-bytes"

        store.delete(key)
        assert store.exists(key) is False

    def test_select_returns_s3_when_configured(self, monkeypatch):
        store = self._store(monkeypatch)
        assert store.name == "s3"
        assert isinstance(store, StorageBackend)
