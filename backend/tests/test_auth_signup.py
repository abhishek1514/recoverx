from __future__ import annotations

import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import verify_password
from app.database.connection import Base
from app.database.session import get_db
from app.main import app
from app.models.merchant import Merchant
from app.models.user import User


class MerchantSignupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        cls.Session = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)

        def override_get_db():
            db = cls.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=cls.engine)

    @staticmethod
    def payload(email: str = "owner@example.com") -> dict[str, str]:
        return {
            "business_name": "New Merchant Ltd",
            "full_name": "New Owner",
            "email": email,
            "password": "StrongPass123",
            "confirm_password": "StrongPass123",
            "country_code": "IN",
            "currency": "INR",
        }

    def test_01_successful_signup_creates_linked_merchant_admin_and_jwt(self) -> None:
        response = self.client.post("/api/auth/signup", json=self.payload())
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("access_token", data)
        self.assertNotIn("hashed_password", data)
        self.assertEqual(data["user"]["role"], "merchant_admin")

        with self.Session() as db:
            user = db.scalar(select(User).where(User.email == "owner@example.com"))
            merchant = db.get(Merchant, data["user"]["merchant_id"])
            self.assertIsNotNone(user)
            self.assertIsNotNone(merchant)
            self.assertEqual(user.merchant_id, merchant.id)
            self.assertEqual(merchant.name, "New Merchant Ltd")
            self.assertTrue(user.is_active)
            self.assertNotEqual(user.hashed_password, "StrongPass123")
            self.assertTrue(verify_password("StrongPass123", user.hashed_password))

        me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["merchant_id"], data["user"]["merchant_id"])

    def test_02_duplicate_email_returns_clean_conflict(self) -> None:
        self.assertEqual(self.client.post("/api/auth/signup", json=self.payload("duplicate@example.com")).status_code, 201)
        response = self.client.post("/api/auth/signup", json=self.payload("duplicate@example.com"))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "An account with this email already exists.")

    def test_03_invalid_email_short_or_weak_password_and_mismatch_are_rejected(self) -> None:
        invalid_email = self.payload("not-an-email")
        self.assertEqual(self.client.post("/api/auth/signup", json=invalid_email).status_code, 422)
        short_password = self.payload("short@example.com")
        short_password.update(password="Short1", confirm_password="Short1")
        self.assertEqual(self.client.post("/api/auth/signup", json=short_password).status_code, 422)
        mismatch = self.payload("mismatch@example.com")
        mismatch["confirm_password"] = "Different123"
        self.assertEqual(self.client.post("/api/auth/signup", json=mismatch).status_code, 422)
        privileged_fields = self.payload("privileged@example.com")
        privileged_fields["merchant_id"] = 999
        privileged_fields["role"] = "admin"
        self.assertEqual(self.client.post("/api/auth/signup", json=privileged_fields).status_code, 422)

    def test_04_existing_login_and_protected_route_behavior_are_preserved(self) -> None:
        self.client.post("/api/auth/signup", json=self.payload("login@example.com"))
        login = self.client.post("/api/auth/login", json={"email": "login@example.com", "password": "StrongPass123"})
        self.assertEqual(login.status_code, 200)
        self.assertIn("access_token", login.json())
        protected = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
        self.assertEqual(protected.status_code, 200)


if __name__ == "__main__":
    unittest.main()