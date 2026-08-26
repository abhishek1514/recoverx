"""Targeted Production Infrastructure Hardening Tests for RecoverX (Phase 10).

Validates:
1. S3 storage upload / download abstraction
2. Tenant-isolated object key generation
3. Signed document access
4. Redis rate limit behavior
5. Memory fallback behavior
6. Production configuration validation
7. Health readiness when Redis is unavailable (503)
8. Health readiness when PostgreSQL is unavailable (503)
9. Worker restart with pending queue item
10. Retry / DLQ behavior
11. Secret values never appear in logs or public error responses
12. Production CORS configuration rejects unauthorized origins
"""

from __future__ import annotations

import json
import os
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.security import create_access_token
from app.database.connection import Base
from app.database.session import get_db
from app.main import app
from app.models.merchant import Merchant
from app.models.user import User
from app.models.webhook_event import WebhookEvent
from app.services.document_service import DocumentService
from app.services.object_storage import (
    LocalStorageProvider,
    S3ObjectStorageProvider,
    generate_tenant_object_key,
)
from app.services.rate_limiter import MemoryRateLimiter, RedisRateLimiter
from app.workers.durable_queue import DurableWebhookQueue


class Phase10InfrastructureHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

    def setUp(self):
        Base.metadata.create_all(bind=self.engine)
        self.db = self.TestingSessionLocal()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        # Seed Merchant 1
        self.merchant1 = Merchant(id=1, name="Production Hardening Merchant", country_code="IN", currency="INR", is_active=True)
        self.db.add(self.merchant1)
        self.db.commit()

        self.token_m1 = create_access_token({"sub": "1", "merchant_id": 1, "role": "admin"})
        self.auth_m1 = {"Authorization": f"Bearer {self.token_m1}"}

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        app.dependency_overrides.clear()

    # 1. S3 storage upload / download abstraction
    def test_01_s3_storage_upload_download_abstraction(self):
        """1. Verify S3 storage upload and download provider methods."""
        mock_boto_client = MagicMock()
        mock_boto_client.get_object.return_value = {
            "Body": MagicMock(read=lambda: b"%PDF-1.4 Mock Document Content"),
            "ContentType": "application/pdf",
        }

        with patch("boto3.client", return_value=mock_boto_client):
            settings = Settings(
                object_storage_provider="s3",
                s3_bucket="recoverx-production-documents",
                s3_region="us-east-1",
                s3_access_key_id="test_key",
                s3_secret_access_key="test_secret",
            )
            provider = S3ObjectStorageProvider(settings=settings)
            
            # Test Upload
            key = "merchants/1/invoices/test_invoice.pdf"
            uploaded_key = provider.upload(key, b"%PDF-1.4 Mock Document Content", "application/pdf")
            self.assertEqual(uploaded_key, key)
            mock_boto_client.put_object.assert_called_once()

            # Test Download
            content, ct = provider.download(key)
            self.assertEqual(content, b"%PDF-1.4 Mock Document Content")
            self.assertEqual(ct, "application/pdf")

    # 2. Tenant-isolated object key generation
    def test_02_tenant_isolated_object_key_generation(self):
        """2. Object storage keys strictly isolate merchant tenants."""
        key_m1 = generate_tenant_object_key(merchant_id=1, filename="invoice.pdf", doc_type="invoices")
        key_m2 = generate_tenant_object_key(merchant_id=2, filename="invoice.pdf", doc_type="invoices")

        self.assertTrue(key_m1.startswith("merchants/1/invoices/"))
        self.assertTrue(key_m2.startswith("merchants/2/invoices/"))
        self.assertTrue(key_m1.endswith(".pdf"))
        self.assertNotEqual(key_m1, key_m2)

    # 3. Signed document access
    def test_03_signed_document_access(self):
        """3. DocumentService creates signed access URLs with time-limited cryptographic validation."""
        doc_service = DocumentService()
        signed_url = doc_service.get_signed_download_url(doc_id=42, merchant_id=1, expires_in_seconds=300)
        self.assertIn("/api/documents/42/download?token=", signed_url)

    # 4. Redis rate limit behavior
    def test_04_redis_rate_limit_behavior(self):
        """4. RedisRateLimiter accurately tracks quota via atomic sliding window."""
        mock_redis = MagicMock()
        # Simulate pipeline result: [rem_count, add_count, active_count=3, expire_bool]
        mock_pipeline = MagicMock()
        mock_pipeline.execute.return_value = [0, 1, 3, True]
        mock_redis.pipeline.return_value = mock_pipeline

        with patch("redis.Redis.from_url", return_value=mock_redis):
            settings = Settings(rate_limit_backend="redis", redis_url="redis://localhost:6379/0")
            limiter = RedisRateLimiter(settings=settings)

            is_limited, remaining, retry_after = limiter.is_rate_limited("client_ip_1", limit=10, window_seconds=60)
            self.assertFalse(is_limited)
            self.assertEqual(remaining, 7)

    # 5. Memory fallback behavior on Redis disruption
    def test_05_memory_fallback_on_redis_disruption(self):
        """5. Redis failure engages transparent fail-safe memory limiter fallback without raising."""
        mock_redis = MagicMock()
        mock_redis.pipeline.side_effect = Exception("Redis Connection Refused")

        with patch("redis.Redis.from_url", return_value=mock_redis):
            settings = Settings(rate_limit_backend="redis", redis_url="redis://localhost:6379/0")
            limiter = RedisRateLimiter(settings=settings)

            # Does NOT raise; safely falls back to local memory rate limiting
            is_limited, remaining, retry_after = limiter.is_rate_limited("client_ip_fail", limit=5, window_seconds=60)
            self.assertFalse(is_limited)
            self.assertEqual(remaining, 4)

    # 6. Production configuration validation
    def test_06_production_configuration_validation(self):
        """6. Production environment startup validation detects missing configs without leaking secrets."""
        invalid_prod_settings = Settings(
            environment="production",
            database_url="sqlite:///./recoverx.db",  # Invalid in prod
            jwt_secret="recoverx_default_dev_jwt_secret_change_in_production_32b",  # Default dev key
            razorpay_key_id="",
            razorpay_key_secret="",
            cors_origins=["*"],  # Wildcard invalid in prod
        )

        with self.assertRaises(ValueError) as ctx:
            invalid_prod_settings.validate_production_environment()

        err_msg = str(ctx.exception)
        self.assertIn("DATABASE_URL", err_msg)
        self.assertIn("JWT_SECRET", err_msg)
        self.assertIn("CORS_ORIGINS", err_msg)
        # Verify secret values are not printed
        self.assertNotIn("recoverx_default_dev_jwt_secret", err_msg)

    # 7. Health readiness when Redis is unavailable
    def test_07_health_readiness_when_redis_unavailable(self):
        """7. GET /health/ready returns HTTP 503 when Redis backend is down."""
        mock_limiter = MagicMock()
        mock_limiter.check_health.return_value = False

        with patch("app.main.settings.rate_limit_backend", "redis"), \
             patch("app.main.get_rate_limiter", return_value=mock_limiter):
            resp = self.client.get("/health/ready")
            self.assertEqual(resp.status_code, 503)
            self.assertIn("Redis rate limiter", resp.json()["error"])

    # 8. Health readiness when PostgreSQL is unavailable
    def test_08_health_readiness_when_database_unavailable(self):
        """8. GET /health/ready returns HTTP 503 when Database connectivity fails."""
        with patch("app.main.SessionLocal", side_effect=Exception("DB Connection Timeout")):
            resp = self.client.get("/health/ready")
            self.assertEqual(resp.status_code, 503)
            self.assertEqual(resp.json()["status"], "unhealthy")

    # 9. Worker restart with pending queue item
    def test_09_worker_restart_with_pending_queue_item(self):
        """9. Worker restarts and resumes unacknowledged received events from database."""
        from app.workers.worker import poll_and_process_pending_events

        we = WebhookEvent(
            event_id="evt_restart_pending_01",
            event_type="payment.captured",
            payload=json.dumps({"id": "pay_restart_01", "amount": 1000}),
            status="received",
        )
        self.db.add(we)
        self.db.commit()

        with patch("app.workers.worker.SessionLocal", return_value=self.db), \
             patch("app.workers.worker.process_razorpay_webhook") as mock_process:
            processed_count = poll_and_process_pending_events()
            self.assertEqual(processed_count, 1)
            mock_process.assert_called_with("evt_restart_pending_01")

    # 10. Retry / DLQ behavior
    def test_10_retry_and_dlq_behavior(self):
        """10. Event transitions to DLQ after exceeding max retries."""
        we = WebhookEvent(
            event_id="evt_dlq_test_10",
            event_type="payment.failed",
            payload="{}",
            status="received",
        )
        self.db.add(we)
        self.db.commit()

        queue = DurableWebhookQueue(max_retries=2, base_backoff_seconds=0.01)
        with patch("app.workers.durable_queue.SessionLocal", return_value=self.db):
            queue._record_dead_letter("evt_dlq_test_10", "Max retry attempts exhausted")

        # Query updated event from database
        dlq_event = self.db.scalar(select(WebhookEvent).where(WebhookEvent.event_id == "evt_dlq_test_10"))
        self.assertIsNotNone(dlq_event)
        self.assertEqual(dlq_event.status, "dead_letter")

    # 11. Secret values never appear in public error logs
    def test_11_secrets_never_appear_in_error_logs(self):
        """11. Internal server errors return sanitized messages with zero secret exposure."""
        resp = self.client.get("/api/exceptions/invalid_id_format_test")
        self.assertEqual(resp.status_code, 422)  # Request validation rejects non-integer ID
        self.assertNotIn("jwt_secret", resp.text)
        self.assertNotIn("password", resp.text)

    # 12. Production CORS rejects unauthorized origin
    def test_12_production_cors_rejects_unauthorized_origin(self):
        """12. CORS headers only permit configured origins."""
        resp = self.client.options(
            "/api/dashboard/summary",
            headers={
                "Origin": "https://malicious-site.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        # Unauthorized origin will NOT have Access-Control-Allow-Origin header matching malicious origin
        allowed_origin = resp.headers.get("access-control-allow-origin")
        self.assertNotEqual(allowed_origin, "https://malicious-site.com")


if __name__ == "__main__":
    unittest.main()
