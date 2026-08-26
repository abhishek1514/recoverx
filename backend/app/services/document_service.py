"""Document handling service for the RecoverX recovery workflow with private storage, signed access, and retention."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_signed_document_token, verify_signed_document_token
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.services.object_storage import (
    ObjectStorageProvider,
    generate_tenant_object_key,
    get_object_storage,
)

logger = logging.getLogger(__name__)

# Base directory for local secure document storage
STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "storage" / "documents"

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/pjpeg",
}

BLOCKED_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".sh", ".py", ".js", ".vbs", ".msi", ".dll", ".so", ".bin"
}


class DocumentService:
    def __init__(
        self,
        storage_dir: Path | None = None,
        storage_provider: ObjectStorageProvider | None = None,
    ) -> None:
        self.storage_dir = storage_dir or STORAGE_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.storage = storage_provider or get_object_storage()

    def scan_file_for_malware(self, content: bytes) -> None:
        """Malware scanning extension hook (e.g. ClamAV / VirusTotal integration)."""
        # Basic heuristic for embedded executable signatures
        if content.startswith(b"MZ") or content.startswith(b"\x7fELF") or b"<script" in content.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Security policy violation: Suspicious file content detected.",
            )

    def validate_file(
        self,
        filename: str,
        content_type: str | None,
        file_size: int,
        content: bytes | None = None,
    ) -> str:
        """Validate file size, extension, MIME type, and binary magic bytes."""
        if file_size <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )

        if file_size > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File exceeds maximum allowed size of {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB.",
            )

        _, ext = os.path.splitext(filename.lower())
        if ext in BLOCKED_EXTENSIONS or ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File extension '{ext}' is not permitted. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            )

        mime = (content_type or "").lower().split(";")[0].strip()
        if mime and mime not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"MIME type '{mime}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_MIME_TYPES))}",
            )

        # Magic byte check when content bytes are available
        if content:
            self.scan_file_for_malware(content)
            if ext == ".pdf" and not content.startswith(b"%PDF"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="File header does not match a valid PDF document.",
                )
            elif ext in {".jpg", ".jpeg"} and not (content.startswith(b"\xff\xd8\xff")):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="File header does not match a valid JPEG image.",
                )
            elif ext == ".png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="File header does not match a valid PNG image.",
                )

        return ext

    def store_file(
        self,
        content: bytes,
        filename: str,
        content_type: str | None,
        recovery_case_id: int | None,
        db: Session,
        merchant_id: int = 1,
        document_type: str = "invoice",
    ) -> Document:
        """Store uploaded file with tenant-isolated UUID name in object storage and record in database."""
        ext = self.validate_file(filename, content_type, len(content), content)
        object_key = generate_tenant_object_key(merchant_id=merchant_id, filename=filename, doc_type=document_type)

        # Upload to configured storage provider (S3 or local)
        self.storage.upload(object_key, content, content_type=content_type)

        doc = Document(
            merchant_id=merchant_id,
            recovery_case_id=recovery_case_id,
            document_type=document_type,
            reference=object_key,
            status="available",
        )
        db.add(doc)
        db.flush()

        if recovery_case_id:
            db.add(
                AuditLog(
                    merchant_id=merchant_id,
                    entity_type="recovery_case",
                    entity_id=str(recovery_case_id),
                    event_type="document_uploaded",
                    details=f"Document '{document_type}' uploaded securely (ref: {object_key}).",
                )
            )

        logger.info(
            "Stored document %s for merchant %s (case %s) at %s",
            doc.id,
            merchant_id,
            recovery_case_id,
            object_key,
        )
        return doc

    def get_signed_download_url(self, doc_id: int, merchant_id: int, expires_in_seconds: int = 300) -> str:
        """Generate a time-limited signed URL for private document download."""
        token = create_signed_document_token(doc_id, merchant_id, expires_in_seconds)
        return f"/api/documents/{doc_id}/download?token={token}"

    def retrieve_file(self, doc_id: int, token: str, merchant_id: int, db: Session) -> tuple[Path, str]:
        """Verify token, enforce merchant tenant access, and return local file path & media type."""
        doc = db.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

        # Multi-tenant isolation check
        if doc.merchant_id and doc.merchant_id != merchant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

        if not verify_signed_document_token(token, doc_id, merchant_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired download token.",
            )

        ref = doc.reference or ""
        _, ext = os.path.splitext(ref.lower())
        media_type = "application/pdf" if ext == ".pdf" else f"image/{ext.replace('.', '')}"

        # If object exists locally in storage_dir
        local_path = self.storage_dir / os.path.basename(ref)
        if local_path.exists():
            return local_path, media_type

        # Otherwise download from storage provider to local cache file
        try:
            content, ct = self.storage.download(ref)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(content)
            return local_path, ct or media_type
        except Exception:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Physical document not found.")

    def cleanup_expired_documents(self, db: Session, retention_days: int | None = None) -> int:
        """Clean up documents older than retention period according to retention policy."""
        settings = get_settings()
        days = retention_days if retention_days is not None else settings.document_retention_days
        cutoff_date = datetime.now(UTC) - timedelta(days=days)

        expired_docs = db.scalars(
            select(Document).where(Document.created_at < cutoff_date)
        ).all()

        deleted_count = 0
        for doc in expired_docs:
            if doc.reference:
                self.storage.delete(doc.reference)
                local_path = self.storage_dir / os.path.basename(doc.reference)
                if local_path.exists():
                    try:
                        local_path.unlink()
                    except OSError as e:
                        logger.warning("Failed to delete local cached file %s: %s", local_path, e)

            db.add(
                AuditLog(
                    merchant_id=doc.merchant_id or 1,
                    entity_type="document",
                    entity_id=str(doc.id),
                    event_type="document_retention_cleanup",
                    details=f"Document expired after {days} days retention policy and was safely deleted.",
                )
            )
            db.delete(doc)
            deleted_count += 1

        db.commit()
        logger.info("Document retention cleanup removed %s expired documents", deleted_count)
        return deleted_count
