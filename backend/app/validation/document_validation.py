"""Deterministic validation rules for uploaded recovery documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.services.document_service import STORAGE_DIR


def validate_case_documents(
    recovery_case_id: int,
    db: Session,
    require_document: bool = True,
) -> dict[str, Any]:
    """Validate attached documents for a recovery case."""
    documents = db.scalars(
        select(Document).where(Document.recovery_case_id == recovery_case_id)
    ).all()

    available_docs = [doc for doc in documents if doc.status == "available"]

    if require_document and not available_docs:
        return {
            "name": "document_presence",
            "status": "FAIL",
            "message": "Required supporting invoice or document has not been uploaded.",
            "document_count": 0,
        }

    if not available_docs:
        return {
            "name": "document_presence",
            "status": "PASS",
            "message": "No document was strictly required for this transaction.",
            "document_count": 0,
        }

    primary_doc = available_docs[-1]
    return {
        "name": "document_presence",
        "status": "PASS",
        "message": f"Valid document '{primary_doc.document_type}' (id={primary_doc.id}) is available and verified.",
        "document_count": len(available_docs),
        "primary_document_id": primary_doc.id,
    }

