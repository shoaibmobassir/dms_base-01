"""Object storage behind a stable interface.

Default: local filesystem (dev / single-node).
Optional: S3-compatible (MinIO) when OBJECT_STORE_BACKEND=s3.

Key layout (deterministic):
  {tenant}/{client}/{matter}/{document}/versions/v{NNN}/original.{ext}
"""
from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.config import settings

_SAFE = re.compile(r"[^a-zA-Z0-9._/-]+")


def content_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sanitize_segment(value: str) -> str:
    cleaned = _SAFE.sub("_", (value or "unknown").strip()).strip("/._")
    return cleaned or "unknown"


def build_storage_key(
    *,
    tenant_id: str,
    client_id: str,
    matter_id: str,
    document_id: str,
    version_number: int,
    filename: str,
) -> str:
    ext = Path(filename).suffix.lstrip(".") or "bin"
    return (
        f"{sanitize_segment(tenant_id)}/"
        f"{sanitize_segment(client_id)}/"
        f"{sanitize_segment(matter_id)}/"
        f"{sanitize_segment(document_id)}/"
        f"versions/v{version_number:03d}/original.{ext.lower()}"
    )


def guess_mime(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


@runtime_checkable
class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        """Store bytes; return canonical storage_uri."""

    def get(self, key_or_uri: str) -> bytes:
        ...

    def exists(self, key_or_uri: str) -> bool:
        ...

    def delete(self, key_or_uri: str) -> None:
        ...

    def uri_for(self, key: str) -> str:
        ...


class LocalObjectStore:
    """Filesystem-backed store. URIs look like ``file://{root}/{key}``."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or settings.object_store_root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key_or_uri: str) -> Path:
        key = key_or_uri
        if key.startswith("file://"):
            key = key[len("file://") :]
            # Allow absolute file:// paths under root
            p = Path(key)
            if p.is_absolute():
                return p
        # Strip root prefix if someone passed a full path as key
        return self.root / key.lstrip("/")

    def uri_for(self, key: str) -> str:
        return f"file://{self._path(key)}"

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        # sidecar content-type (optional metadata)
        if content_type:
            path.with_suffix(path.suffix + ".content_type").write_text(
                content_type, encoding="utf-8"
            )
        return self.uri_for(key)

    def get(self, key_or_uri: str) -> bytes:
        path = self._path(key_or_uri)
        if not path.is_file():
            raise FileNotFoundError(key_or_uri)
        return path.read_bytes()

    def exists(self, key_or_uri: str) -> bool:
        return self._path(key_or_uri).is_file()

    def delete(self, key_or_uri: str) -> None:
        path = self._path(key_or_uri)
        if path.is_file():
            path.unlink()
        ct = path.with_suffix(path.suffix + ".content_type")
        if ct.is_file():
            ct.unlink()


class S3ObjectStore:
    """S3-compatible backend (MinIO). Requires ``boto3``."""

    def __init__(
        self,
        bucket: str | None = None,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str = "us-east-1",
    ):
        try:
            import boto3
            from botocore.client import Config
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "OBJECT_STORE_BACKEND=s3 requires boto3. pip install boto3"
            ) from exc

        self.bucket = bucket or settings.object_store_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or settings.object_store_endpoint,
            aws_access_key_id=access_key or settings.object_store_access_key,
            aws_secret_access_key=secret_key or settings.object_store_secret_key,
            region_name=region or settings.object_store_region,
            config=Config(signature_version="s3v4"),
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except Exception:
            self._client.create_bucket(Bucket=self.bucket)

    def _key(self, key_or_uri: str) -> str:
        if key_or_uri.startswith("s3://"):
            # s3://bucket/key
            rest = key_or_uri[5:]
            parts = rest.split("/", 1)
            return parts[1] if len(parts) == 2 else parts[0]
        return key_or_uri.lstrip("/")

    def uri_for(self, key: str) -> str:
        return f"s3://{self.bucket}/{key.lstrip('/')}"

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        k = self._key(key)
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(Bucket=self.bucket, Key=k, Body=data, **extra)
        return self.uri_for(k)

    def get(self, key_or_uri: str) -> bytes:
        obj = self._client.get_object(Bucket=self.bucket, Key=self._key(key_or_uri))
        return obj["Body"].read()

    def exists(self, key_or_uri: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=self._key(key_or_uri))
            return True
        except Exception:
            return False

    def delete(self, key_or_uri: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=self._key(key_or_uri))


_store: ObjectStore | None = None


def get_object_store() -> ObjectStore:
    global _store
    if _store is not None:
        return _store
    backend = (settings.object_store_backend or "local").lower()
    if backend == "s3":
        _store = S3ObjectStore()
    else:
        _store = LocalObjectStore()
    return _store


def reset_object_store_for_tests() -> None:
    global _store
    _store = None
