"""Pluggable file storage for the realtime "files" feature.

``StorageBackend`` is the interface; ``LocalStorage`` (default, zero-dependency,
filesystem) and ``S3Storage`` (opt-in, S3-compatible via boto3) are the shipped
implementations. Selection mirrors the cache/session/queue backend pattern:
``TINA4_STORAGE_BACKEND`` (``local`` default | ``s3``) plus per-backend env vars,
with a graceful fallback to local if an ``s3`` backend cannot be constructed
(missing driver or incomplete config) -- a real persistent store, never a silent
no-op.

Env vars:
- ``TINA4_STORAGE_BACKEND``  ``local`` (default) | ``s3``
- ``TINA4_STORAGE_DIR``      local directory (default ``data/rt_storage``)
- ``TINA4_STORAGE_URL``      S3 endpoint URL (e.g. an S3-compatible/MinIO host)
- ``TINA4_STORAGE_KEY`` / ``TINA4_STORAGE_SECRET``  S3 credentials
- ``TINA4_STORAGE_BUCKET``   S3 bucket name
- ``TINA4_STORAGE_REGION``   S3 region (default ``us-east-1``)
"""
import os
import re
import uuid

from tina4_python.debug import Log

_SAFE_KEY = re.compile(r"[^A-Za-z0-9._-]")


def storage_key(filename: str = "") -> str:
    """Generate an opaque, collision-free storage key, preserving the extension.

    The key is url-safe and carries no user-controlled path segment, so it can
    never traverse outside the storage root.
    """
    ext = ""
    if filename and "." in filename:
        ext = "." + _SAFE_KEY.sub("", filename.rsplit(".", 1)[1])[:12]
    return uuid.uuid4().hex + ext


class StorageBackend:
    """Blob store interface.

    ``put`` writes bytes, ``get`` reads them back, ``url`` returns a directly
    fetchable URL when the backend supports one (else ``None`` -- serve via the
    app download route), ``delete`` removes, ``exists`` checks presence.
    """

    name = "storage"

    def put(self, key: str, data: bytes, mime: str = "application/octet-stream") -> None:
        raise NotImplementedError

    def get(self, key: str) -> bytes | None:
        raise NotImplementedError

    def url(self, key: str, ttl: int = 3600) -> str | None:
        return None

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError


class LocalStorage(StorageBackend):
    """Zero-dependency filesystem store. The default backend."""

    name = "local"

    def __init__(self, directory: str = None):
        self.directory = os.path.abspath(
            directory or os.getenv("TINA4_STORAGE_DIR", "data/rt_storage"))
        os.makedirs(self.directory, exist_ok=True)

    def _path(self, key: str) -> str:
        # Resolve inside the root and reject any traversal attempt.
        target = os.path.abspath(os.path.join(self.directory, key))
        if os.path.commonpath([self.directory, target]) != self.directory:
            raise ValueError(f"unsafe storage key: {key!r}")
        return target

    def put(self, key, data, mime="application/octet-stream"):
        with open(self._path(key), "wb") as fh:
            fh.write(data)

    def get(self, key):
        try:
            with open(self._path(key), "rb") as fh:
                return fh.read()
        except (FileNotFoundError, ValueError):
            return None

    def url(self, key, ttl=3600):
        # No direct URL: the permissioned app download route serves local files.
        return None

    def delete(self, key):
        try:
            os.remove(self._path(key))
        except (FileNotFoundError, ValueError):
            pass

    def exists(self, key):
        try:
            return os.path.isfile(self._path(key))
        except ValueError:
            return False


class S3Storage(StorageBackend):
    """S3-compatible store (AWS S3, MinIO, ...). Opt-in; needs boto3.

    Presigned GET URLs let clients fetch large blobs straight from object
    storage instead of streaming through the app.
    """

    name = "s3"

    def __init__(self, *, endpoint=None, key=None, secret=None, bucket=None,
                 region=None):
        import boto3  # optional dependency, imported lazily

        self.bucket = bucket or os.getenv("TINA4_STORAGE_BUCKET")
        if not self.bucket:
            raise ValueError("S3Storage requires TINA4_STORAGE_BUCKET")
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint or os.getenv("TINA4_STORAGE_URL") or None,
            aws_access_key_id=key or os.getenv("TINA4_STORAGE_KEY"),
            aws_secret_access_key=secret or os.getenv("TINA4_STORAGE_SECRET"),
            region_name=region or os.getenv("TINA4_STORAGE_REGION", "us-east-1"),
        )

    def put(self, key, data, mime="application/octet-stream"):
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data,
                                ContentType=mime)

    def get(self, key):
        try:
            obj = self._client.get_object(Bucket=self.bucket, Key=key)
            return obj["Body"].read()
        except Exception:
            return None

    def url(self, key, ttl=3600):
        return self._client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=ttl)

    def delete(self, key):
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            Log.error(f"S3Storage delete failed for {key}: {exc}")

    def exists(self, key):
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False


def select_storage(storage: StorageBackend = None) -> StorageBackend:
    """Resolve the storage backend from an explicit arg or the environment.

    Falls back to :class:`LocalStorage` when an ``s3`` backend cannot be built
    (boto3 missing or config incomplete), logging why -- a real store, never a
    silent no-op.
    """
    if storage is not None:
        return storage
    name = os.getenv("TINA4_STORAGE_BACKEND", "local").lower()
    if name == "s3":
        try:
            return S3Storage()
        except Exception as exc:
            Log.warning(
                f"realtime files: S3 storage unavailable ({exc}); "
                "falling back to local filesystem storage.")
            return LocalStorage()
    return LocalStorage()
