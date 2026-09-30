"""Registration: happy path, role policy, validation and duplicate handling."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.user import User
from tests.conftest import API_PREFIX


class TestSuccessfulRegistration:
    def test_returns_201_with_user_and_tokens(self, client: TestClient) -> None:
        email = f"ravi-{uuid.uuid4().hex[:6]}@honey.example.com"
        response = client.post(
            f"{API_PREFIX}/auth/register",
            json={
                "name": "Ravi Kumar",
                "email": email,
                "phone": "9876543210",
                "password": "HoneyPass123",
                "confirm_password": "HoneyPass123",
                "role": UserRole.BEEKEEPER.value,
                "state": "Andhra Pradesh",
                "district": "Guntur",
                "organization": "Guntur Beekeepers Co-operative",
                "accepted_terms": True,
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["success"] is True

        data = body["data"]
        assert data["user"]["email"] == email.lower()
        assert data["user"]["role"] == UserRole.BEEKEEPER.value
        assert data["user"]["role_label"] == "Beekeeper"
        assert data["user"]["account_status"] == "ACTIVE"
        assert data["user"]["district"] == "Guntur"
        # Phone is normalised to E.164 for a 10-digit Indian number.
        assert data["user"]["phone"] == "+919876543210"
        assert data["token"]["token_type"] == "Bearer"
        assert data["token"]["expires_in"] > 0
        assert data["access_token"]

    def test_never_exposes_credentials(self, client: TestClient, db: Session) -> None:
        response = client.post(
            f"{API_PREFIX}/auth/register",
            json={
                "name": "Credential Check",
                "email": f"nohash-{uuid.uuid4().hex[:6]}@honey.example.com",
                "password": "HoneyPass123",
                "role": UserRole.CONSUMER.value,
            },
        )

        raw = response.text
        assert "password" not in raw.lower()
        assert "password_hash" not in raw.lower()
        assert "HoneyPass123" not in raw

    def test_password_is_stored_hashed(self, client: TestClient, db: Session) -> None:
        email = f"hash-{uuid.uuid4().hex[:6]}@honey.example.com"
        client.post(
            f"{API_PREFIX}/auth/register",
            json={
                "name": "Hash Check",
                "email": email,
                "password": "HoneyPass123",
                "role": UserRole.BEEKEEPER.value,
            },
        )

        user = db.execute(select(User).where(User.email == email)).scalars().one()
        assert user.password_hash != "HoneyPass123"
        assert user.password_hash.startswith("$2b$")  # bcrypt
        assert user.is_active is True
        assert user.last_login_at is None  # registering is not a login

    def test_session_is_recorded_for_logout_support(self, client: TestClient, db: Session) -> None:
        from app.models.refresh_token import RefreshToken

        client.post(
            f"{API_PREFIX}/auth/register",
            json={
                "name": "Session Check",
                "email": f"session-{uuid.uuid4().hex[:6]}@honey.example.com",
                "password": "HoneyPass123",
                "role": UserRole.BEEKEEPER.value,
            },
        )

        tokens = db.execute(select(RefreshToken)).scalars().all()
        assert len(tokens) == 1
        # Only a fingerprint is persisted — never the token itself.
        assert len(tokens[0].token_hash) == 64
        assert tokens[0].revoked is False

    def test_all_self_registrable_roles_are_accepted(self, client: TestClient) -> None:
        for role in UserRole.self_registrable():
            response = client.post(
                f"{API_PREFIX}/auth/register",
                json={
                    "name": f"{role.label} User",
                    "email": f"{role.value.lower()}-{uuid.uuid4().hex[:6]}@honey.example.com",
                    "password": "HoneyPass123",
                    "role": role.value,
                },
            )
            assert response.status_code == 201, f"{role} -> {response.text}"
            assert response.json()["data"]["user"]["role"] == role.value


class TestRolePolicy:
    def test_privileged_roles_cannot_be_self_assigned(self, client: TestClient) -> None:
        for role in (UserRole.ADMIN, UserRole.KVIC_OFFICER, UserRole.LAB_TECHNICIAN):
            response = client.post(
                f"{API_PREFIX}/auth/register",
                json={
                    "name": f"Would-be {role.label}",
                    "email": f"escalate-{role.value.lower()}-{uuid.uuid4().hex[:6]}@honey.example.com",
                    "password": "HoneyPass123",
                    "role": role.value,
                },
            )

            assert response.status_code == 422, f"{role} was self-assignable!"
            body = response.json()
            assert body["success"] is False
            assert body["error"]["code"] == "VALIDATION_ERROR"

    def test_unknown_role_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            f"{API_PREFIX}/auth/register",
            json={
                "name": "Bad Role",
                "email": f"badrole-{uuid.uuid4().hex[:6]}@honey.example.com",
                "password": "HoneyPass123",
                "role": "SUPER_USER",
            },
        )

        assert response.status_code == 422


class TestValidation:
    def test_duplicate_email_returns_409(self, client: TestClient, register_user) -> None:
        existing = register_user()

        response = client.post(
            f"{API_PREFIX}/auth/register",
            json={
                "name": "Impostor",
                "email": existing["user"]["email"],
                "password": "HoneyPass123",
                "role": UserRole.BEEKEEPER.value,
            },
        )

        assert response.status_code == 409
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "DUPLICATE_RESOURCE"

    def test_duplicate_phone_returns_409(self, client: TestClient, register_user) -> None:
        register_user(phone="+919000000001")

        response = client.post(
            f"{API_PREFIX}/auth/register",
            json={
                "name": "Second Caller",
                "email": f"dup-phone-{uuid.uuid4().hex[:6]}@honey.example.com",
                "phone": "+919000000001",
                "password": "HoneyPass123",
                "role": UserRole.BEEKEEPER.value,
            },
        )

        assert response.status_code == 409

    def test_weak_password_is_rejected_with_field_details(self, client: TestClient) -> None:
        response = client.post(
            f"{API_PREFIX}/auth/register",
            json={
                "name": "Weak Password",
                "email": f"weak-{uuid.uuid4().hex[:6]}@honey.example.com",
                "password": "password",  # no digit
                "role": UserRole.BEEKEEPER.value,
            },
        )

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert any(detail["field"] == "password" for detail in error["details"])

    def test_short_password_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            f"{API_PREFIX}/auth/register",
            json={
                "name": "Short Password",
                "email": f"short-{uuid.uuid4().hex[:6]}@honey.example.com",
                "password": "Ab1",
                "role": UserRole.BEEKEEPER.value,
            },
        )

        assert response.status_code == 422

    def test_mismatched_confirmation_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            f"{API_PREFIX}/auth/register",
            json={
                "name": "Mismatch",
                "email": f"mismatch-{uuid.uuid4().hex[:6]}@honey.example.com",
                "password": "HoneyPass123",
                "confirm_password": "HoneyPass124",
                "role": UserRole.BEEKEEPER.value,
            },
        )

        assert response.status_code == 422

    def test_invalid_email_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            f"{API_PREFIX}/auth/register",
            json={
                "name": "Bad Email",
                "email": "not-an-email",
                "password": "HoneyPass123",
                "role": UserRole.BEEKEEPER.value,
            },
        )

        assert response.status_code == 422

    def test_unexpected_field_is_rejected(self, client: TestClient) -> None:
        """``extra="forbid"`` stops clients smuggling in fields such as is_active."""
        response = client.post(
            f"{API_PREFIX}/auth/register",
            json={
                "name": "Extra Fields",
                "email": f"extra-{uuid.uuid4().hex[:6]}@honey.example.com",
                "password": "HoneyPass123",
                "role": UserRole.BEEKEEPER.value,
                "is_active": False,
            },
        )

        assert response.status_code == 422
