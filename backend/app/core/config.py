from __future__ import annotations

import os
from decimal import Decimal
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class Settings(BaseModel):
    """Runtime production settings for the RecoverX API."""

    app_name: str = Field(default="RecoverX API")
    environment: str = Field(default="development")
    database_url: str = Field(default="sqlite:///./recoverx.db")
    db_pool_size: int = Field(default=10)
    db_max_overflow: int = Field(default=20)
    log_level: str = Field(default="INFO")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    jwt_secret: str = Field(default="recoverx_default_dev_jwt_secret_change_in_production_32b")
    jwt_algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=60)
    refresh_token_expire_days: int = Field(default=7)
    razorpay_key_id: str = Field(default="")
    razorpay_key_secret: str = Field(default="")
    razorpay_webhook_secret: str = Field(default="")
    webhook_tolerance_seconds: int = Field(default=300)
    document_retention_days: int = Field(default=90)
    document_download_secret: str = Field(default="recoverx_doc_sign_secret_32b")
    rate_limit_per_minute: int = Field(default=120)
    high_value_threshold: Decimal = Field(default=Decimal("100000"))
    high_value_thresholds: dict[str, Decimal] = Field(
        default_factory=lambda: {
            "INR": Decimal("100000"),
            "USD": Decimal("10000"),
            "EUR": Decimal("10000"),
            "GBP": Decimal("10000"),
            "SGD": Decimal("15000"),
            "AUD": Decimal("15000"),
            "CAD": Decimal("15000"),
        }
    )
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="")

    def get_high_value_threshold(self, currency: str | None = None) -> Decimal:
        """Return the application-configured business threshold for a currency."""
        curr = (currency or "INR").upper().strip()
        if curr in self.high_value_thresholds:
            return self.high_value_thresholds[curr]
        return self.high_value_threshold


@lru_cache
def get_settings() -> Settings:
    origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    inr_thresh = Decimal(os.getenv("HIGH_VALUE_THRESHOLD_INR", os.getenv("HIGH_VALUE_THRESHOLD", "100000")))
    usd_thresh = Decimal(os.getenv("HIGH_VALUE_THRESHOLD_USD", "10000"))
    eur_thresh = Decimal(os.getenv("HIGH_VALUE_THRESHOLD_EUR", "10000"))
    gbp_thresh = Decimal(os.getenv("HIGH_VALUE_THRESHOLD_GBP", "10000"))
    sgd_thresh = Decimal(os.getenv("HIGH_VALUE_THRESHOLD_SGD", "15000"))

    thresholds_map = {
        "INR": inr_thresh,
        "USD": usd_thresh,
        "EUR": eur_thresh,
        "GBP": gbp_thresh,
        "SGD": sgd_thresh,
        "AUD": Decimal(os.getenv("HIGH_VALUE_THRESHOLD_AUD", "15000")),
        "CAD": Decimal(os.getenv("HIGH_VALUE_THRESHOLD_CAD", "15000")),
    }

    return Settings(
        app_name=os.getenv("APP_NAME", "RecoverX API"),
        environment=os.getenv("ENVIRONMENT", "development"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./recoverx.db"),
        db_pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
        db_max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        cors_origins=[origin.strip() for origin in origins.split(",") if origin.strip()],
        jwt_secret=os.getenv("JWT_SECRET", "recoverx_default_dev_jwt_secret_change_in_production_32b"),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        access_token_expire_minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")),
        refresh_token_expire_days=int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7")),
        razorpay_key_id=os.getenv("RAZORPAY_KEY_ID", ""),
        razorpay_key_secret=os.getenv("RAZORPAY_KEY_SECRET", ""),
        razorpay_webhook_secret=os.getenv("RAZORPAY_WEBHOOK_SECRET", ""),
        webhook_tolerance_seconds=int(os.getenv("WEBHOOK_TOLERANCE_SECONDS", "300")),
        document_retention_days=int(os.getenv("DOCUMENT_RETENTION_DAYS", "90")),
        document_download_secret=os.getenv("DOCUMENT_DOWNLOAD_SECRET", "recoverx_doc_sign_secret_32b"),
        rate_limit_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "120")),
        high_value_threshold=inr_thresh,
        high_value_thresholds=thresholds_map,
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", ""),
    )
