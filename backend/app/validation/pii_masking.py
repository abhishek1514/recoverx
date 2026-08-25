"""Conservative PII text masking utility for the RecoverX intelligence and AI layer."""

from __future__ import annotations

import re
from typing import Any

# Match standard email addresses
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")

# Match international and domestic phone numbers with prefixes or formatting
PHONE_REGEX = re.compile(
    r"(?:\+\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s])?\d{3,4}[-.\s]\d{3,4}\b|\b(?:\+91[\s-]?)?[6789]\d{9}\b|\b\(\d{3}\)\s*\d{3}-\d{4}\b"
)

# Match PAN (5 letters, 4 digits, 1 letter), GSTIN (15 chars), SSN (3-2-4 digits)
TAX_ID_REGEX = re.compile(
    r"\b[A-Z]{5}[0-9]{4}[A-Z]\b|\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}\b|\b\d{3}-\d{2}-\d{4}\b",
    re.IGNORECASE,
)

# Match account / card / long identifier numbers (9 to 18 consecutive digits)
ACCOUNT_NUMBER_REGEX = re.compile(r"\b\d{9,18}\b")




def mask_pii_text(text: str | None) -> str:
    """Mask obvious PII occurrences in plain text strings."""
    if not text or not isinstance(text, str):
        return "" if text is None else str(text)

    masked = EMAIL_REGEX.sub("[EMAIL]", text)
    masked = TAX_ID_REGEX.sub("[TAX_ID]", masked)
    masked = PHONE_REGEX.sub("[PHONE]", masked)
    masked = ACCOUNT_NUMBER_REGEX.sub("[ACCOUNT_NUMBER]", masked)
    return masked



def mask_pii_dict(data: Any) -> Any:
    """Recursively mask PII in dictionary and list structures."""
    if isinstance(data, dict):
        return {k: mask_pii_dict(v) for k, v in data.items()}
    if isinstance(data, list):
        return [mask_pii_dict(item) for item in data]
    if isinstance(data, str):
        return mask_pii_text(data)
    return data
