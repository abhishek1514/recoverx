from __future__ import annotations

import hmac
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings


def hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against hashed password."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Generate a signed JWT access token."""
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(data: dict[str, Any]) -> str:
    """Generate a signed JWT refresh token."""
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a signed JWT token."""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def constant_time_compare(val1: str, val2: str) -> bool:
    """Timing-safe string comparison to mitigate side-channel timing attacks."""
    return hmac.compare_digest(val1.encode("utf-8"), val2.encode("utf-8"))


def create_signed_document_token(doc_id: int, merchant_id: int, expires_in_seconds: int = 300) -> str:
    """Create short-lived HMAC token for authorized private document download."""
    settings = get_settings()
    expiry = int((datetime.now(UTC) + timedelta(seconds=expires_in_seconds)).timestamp())
    payload = f"{doc_id}:{merchant_id}:{expiry}"
    sig = hmac.new(
        settings.document_download_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{expiry}.{sig}"


def verify_signed_document_token(token: str, doc_id: int, merchant_id: int) -> bool:
    """Verify signed document download token."""
    try:
        settings = get_settings()
        parts = token.split(".")
        if len(parts) != 2:
            return False
        expiry_str, received_sig = parts
        expiry = int(expiry_str)
        if datetime.now(UTC).timestamp() > expiry:
            return False  # Expired

        payload = f"{doc_id}:{merchant_id}:{expiry}"
        expected_sig = hmac.new(
            settings.document_download_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(received_sig, expected_sig)
    except Exception:
        return False

