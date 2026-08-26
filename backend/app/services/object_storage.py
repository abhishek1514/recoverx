"""Production Object Storage Provider Abstraction for RecoverX.

Provides an enterprise-ready abstraction supporting S3-compatible cloud object storage
(AWS S3, Cloudflare R2, MinIO, Google Cloud Storage) and local filesystem fallback.
Enforces multi-tenant isolation, UUID-based key generation, and time-limited signed access.
"""

from __future__ import annotations

import logging
import os
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Base local storage fallback directory
LOCAL_STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "storage" / "documents"


class ObjectStorageProvider(ABC):
    """Abstract interface for object storage providers."""

    @abstractmethod
    def upload(self, key: str, content: bytes, content_type: str | None = None) -> str:
        """Upload binary content to storage key. Returns the canonical object reference."""
        pass

    @abstractmethod
    def download(self, key: str) -> tuple[bytes, str]:
        """Download binary content and content-type for a key. Returns (content, content_type)."""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete an object from storage. Returns True if deleted or already absent."""
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if an object exists in storage."""
        pass

    @abstractmethod
    def get_signed_url(self, key: str, expires_in_seconds: int = 300) -> str:
        """Generate a time-limited signed URL for direct object download."""
        pass

    @abstractmethod
    def check_health(self) -> bool:
        """Verify storage provider connectivity and readiness."""
        pass


class LocalStorageProvider(ObjectStorageProvider):
    """Local filesystem storage provider for development and standalone staging."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or LOCAL_STORAGE_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, key: str) -> Path:
        # Strip leading slash or reference prefixes
        clean_key = key.lstrip("/").replace("documents/", "")
        return self.base_dir / clean_key

    def upload(self, key: str, content: bytes, content_type: str | None = None) -> str:
        target_path = self._resolve_path(key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "wb") as f:
            f.write(content)
        return key

    def download(self, key: str) -> tuple[bytes, str]:
        target_path = self._resolve_path(key)
        if not target_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Object '{key}' not found in local storage.",
            )
        with open(target_path, "rb") as f:
            content = f.read()

        _, ext = os.path.splitext(target_path.name.lower())
        content_type = "application/pdf" if ext == ".pdf" else f"image/{ext.replace('.', '')}"
        return content, content_type

    def delete(self, key: str) -> bool:
        target_path = self._resolve_path(key)
        if target_path.exists():
            try:
                target_path.unlink()
                return True
            except OSError as exc:
                logger.warning("Failed to delete local object %s: %s", key, exc)
                return False
        return True

    def exists(self, key: str) -> bool:
        return self._resolve_path(key).exists()

    def get_signed_url(self, key: str, expires_in_seconds: int = 300) -> str:
        # For local storage, returns the internal API route
        return f"/api/documents/download?key={key}"

    def check_health(self) -> bool:
        try:
            return self.base_dir.exists() and os.access(self.base_dir, os.W_OK)
        except Exception:
            return False


class S3ObjectStorageProvider(ObjectStorageProvider):
    """Production S3-compatible cloud object storage provider."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.bucket = self.settings.s3_bucket
        self.region = self.settings.s3_region or "us-east-1"
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config

                kwargs: dict[str, Any] = {
                    "region_name": self.region,
                    "config": Config(
                        signature_version="s3v4",
                        connect_timeout=5,
                        read_timeout=10,
                        retries={"max_attempts": 3},
                    ),
                }
                if self.settings.s3_access_key_id and self.settings.s3_secret_access_key:
                    kwargs["aws_access_key_id"] = self.settings.s3_access_key_id
                    kwargs["aws_secret_access_key"] = self.settings.s3_secret_access_key

                if self.settings.s3_endpoint_url:
                    kwargs["endpoint_url"] = self.settings.s3_endpoint_url

                self._client = boto3.client("s3", **kwargs)
            except Exception as exc:
                logger.error("Failed to initialize boto3 S3 client: %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Cloud object storage service is unavailable.",
                ) from exc
        return self._client

    def upload(self, key: str, content: bytes, content_type: str | None = None) -> str:
        client = self._get_client()
        extra_args: dict[str, Any] = {"ServerSideEncryption": "AES256"}
        if content_type:
            extra_args["ContentType"] = content_type

        try:
            client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                **extra_args,
            )
            logger.info("Uploaded object to S3 bucket %s with key %s", self.bucket, key)
            return key
        except Exception as exc:
            logger.error("S3 upload failed for key %s: %s", key, exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to persist document to cloud object storage.",
            ) from exc

    def download(self, key: str) -> tuple[bytes, str]:
        client = self._get_client()
        try:
            response = client.get_object(Bucket=self.bucket, Key=key)
            content = response["Body"].read()
            content_type = response.get("ContentType", "application/octet-stream")
            return content, content_type
        except Exception as exc:
            logger.error("S3 download failed for key %s: %s", key, exc)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document '{key}' not found in cloud storage.",
            ) from exc

    def delete(self, key: str) -> bool:
        client = self._get_client()
        try:
            client.delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as exc:
            logger.warning("S3 delete failed for key %s: %s", key, exc)
            return False

    def exists(self, key: str) -> bool:
        client = self._get_client()
        try:
            client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def get_signed_url(self, key: str, expires_in_seconds: int = 300) -> str:
        client = self._get_client()
        try:
            url = client.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in_seconds,
            )
            return str(url)
        except Exception as exc:
            logger.error("Failed generating S3 pre-signed URL for key %s: %s", key, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate secure document download link.",
            ) from exc

    def check_health(self) -> bool:
        if not self.bucket:
            return False
        try:
            client = self._get_client()
            client.head_bucket(Bucket=self.bucket)
            return True
        except Exception as exc:
            logger.error("S3 health check failed for bucket %s: %s", self.bucket, exc)
            return False


def generate_tenant_object_key(merchant_id: int, filename: str, doc_type: str = "documents") -> str:
    """Generate a sanitized, tenant-isolated, UUID-based object storage key."""
    _, ext = os.path.splitext(filename.lower())
    clean_ext = ext if ext else ".bin"
    unique_id = uuid.uuid4().hex
    return f"merchants/{merchant_id}/{doc_type}/{unique_id}{clean_ext}"


def get_object_storage() -> ObjectStorageProvider:
    """Factory function returning the configured object storage provider."""
    settings = get_settings()
    provider = (settings.object_storage_provider or "local").lower().strip()
    if provider == "s3":
        return S3ObjectStorageProvider(settings=settings)
    return LocalStorageProvider()

