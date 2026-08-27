from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.dependencies import get_current_user
from app.core.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.database.session import get_db
from app.models.merchant import Merchant
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshTokenRequest, SignupRequest, TokenResponse, UserProfile

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Authenticate merchant user and issue signed JWT access & refresh tokens."""
    settings = get_settings()
    user = db.scalar(select(User).where(User.email == payload.email.lower().strip()))
    if user is None or not verify_password(payload.password, user.hashed_password):
        logger.warning("Failed login attempt for email: %s", payload.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is deactivated.")

    merchant = db.get(Merchant, user.merchant_id)
    merchant_name = merchant.name if merchant else "Default Merchant"

    access_token = create_access_token(
        data={"sub": str(user.id), "merchant_id": user.merchant_id, "role": user.role},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    refresh_token = create_refresh_token(
        data={"sub": str(user.id), "merchant_id": user.merchant_id},
    )

    logger.info("Merchant user %s logged in successfully", user.email)
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        refresh_token=refresh_token,
        user=UserProfile(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            merchant_id=user.merchant_id,
            merchant_name=merchant_name,
        ),
    )


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Create an isolated merchant account and its initial administrator."""
    settings = get_settings()
    email = str(payload.email).lower().strip()

    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists.")

    try:
        merchant = Merchant(name=payload.business_name, country_code=payload.country_code, currency=payload.currency, is_active=True)
        db.add(merchant)
        db.flush()
        user = User(merchant_id=merchant.id, email=email, hashed_password=hash_password(payload.password), full_name=payload.full_name, role="merchant_admin", is_active=True)
        db.add(user)
        db.flush()
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.info("Signup rejected because the email is already registered.")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists.") from None
    except Exception:
        db.rollback()
        logger.exception("Merchant signup failed while creating a new account.")
        raise

    access_token = create_access_token(data={"sub": str(user.id), "merchant_id": user.merchant_id, "role": user.role}, expires_delta=timedelta(minutes=settings.access_token_expire_minutes))
    refresh_token = create_refresh_token(data={"sub": str(user.id), "merchant_id": user.merchant_id})
    logger.info("Created merchant account for %s", email)
    return TokenResponse(access_token=access_token, token_type="bearer", expires_in=settings.access_token_expire_minutes * 60, refresh_token=refresh_token, user=UserProfile(id=user.id, email=user.email, full_name=user.full_name, role=user.role, merchant_id=user.merchant_id, merchant_name=merchant.name))

@router.get("/me", response_model=UserProfile)
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserProfile:
    """Return currently authenticated merchant user profile."""
    merchant = db.get(Merchant, current_user.merchant_id)
    return UserProfile(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        merchant_id=current_user.merchant_id,
        merchant_name=merchant.name if merchant else "Default Merchant",
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(payload: RefreshTokenRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Issue a new access token from a valid refresh token."""
    settings = get_settings()
    try:
        decoded = decode_token(payload.refresh_token)
        if decoded.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token type.")
        user_id = decoded.get("sub")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        ) from exc

    user = db.get(User, int(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive or not found.")

    merchant = db.get(Merchant, user.merchant_id)
    new_access_token = create_access_token(
        data={"sub": str(user.id), "merchant_id": user.merchant_id, "role": user.role},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )

    return TokenResponse(
        access_token=new_access_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        refresh_token=payload.refresh_token,
        user=UserProfile(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            merchant_id=user.merchant_id,
            merchant_name=merchant.name if merchant else "Default Merchant",
        ),
    )

