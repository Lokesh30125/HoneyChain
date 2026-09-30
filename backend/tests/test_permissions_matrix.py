"""Authorisation matrix for the Phase 2 surface.

One table, asserted once, so a permission change cannot silently widen access.
Everything here is about *denial*: the point of the module is that each role
reaches exactly its own surface and nothing beyond it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

API = "/api/v1"

#: (method, path) pairs the module exposes, and the roles allowed to call them.
#: ``me`` paths use the acting user's own identifier, resolved per test.
MATRIX = [
    ("GET", f"{API}/profile", {"ADMIN", "KVIC_OFFICER", "BEEKEEPER", "CONSUMER"}),
    ("PUT", f"{API}/profile", {"ADMIN", "KVIC_OFFICER", "BEEKEEPER", "CONSUMER"}),
    ("GET", f"{API}/beekeepers/me", {"BEEKEEPER"}),
    ("PUT", f"{API}/beekeepers/me", {"BEEKEEPER"}),
    ("GET", f"{API}/beekeepers", {"ADMIN", "KVIC_OFFICER"}),
    ("GET", f"{API}/beekeepers/filters", {"ADMIN", "KVIC_OFFICER"}),
    ("GET", f"{API}/beekeepers/summary", {"ADMIN", "KVIC_OFFICER"}),
    ("GET", f"{API}/clusters", {"ADMIN", "KVIC_OFFICER", "BEEKEEPER"}),
    ("GET", f"{API}/admin/users", {"ADMIN"}),
    ("GET", f"{API}/admin/summary", {"ADMIN"}),
    ("GET", f"{API}/admin/audit-logs", {"ADMIN"}),
]

ALL_ROLES = ("ADMIN", "KVIC_OFFICER", "BEEKEEPER", "CONSUMER")


@pytest.fixture()
def tokens(client: TestClient, admin_headers, kvic_headers, auth_headers, consumer_headers) -> dict:
    return {
        "ADMIN": admin_headers,
        "KVIC_OFFICER": kvic_headers,
        "BEEKEEPER": auth_headers,
        "CONSUMER": consumer_headers,
    }


class TestAccessMatrix:
    @pytest.mark.parametrize(("method", "path", "allowed"), MATRIX)
    def test_only_allowed_roles_reach_the_endpoint(
        self, client: TestClient, tokens: dict, method: str, path: str, allowed: set[str]
    ):
        for role, headers in tokens.items():
            # A body is only sent where the endpoint accepts one; GETs are called
            # bare so the status code reflects authorisation, not request shape.
            kwargs = {"json": {}} if method in ("PUT", "PATCH", "POST") else {}
            response = client.request(method, path, headers=headers, **kwargs)
            if role in allowed:
                # 200 when the payload is valid; some writes need a body, which
                # is asserted separately — here we only care that it is not 401/403.
                assert response.status_code not in (401, 403), (role, method, path, response.text)
            else:
                assert response.status_code == 403, (role, method, path, response.text)

    @pytest.mark.parametrize(("method", "path", "_allowed"), MATRIX)
    def test_anonymous_callers_are_always_rejected(
        self, client: TestClient, method: str, path: str, _allowed: set[str]
    ):
        assert client.request(method, path).status_code == 401


class TestPrivilegeEscalation:
    def test_role_cannot_be_self_assigned(self, client: TestClient):
        """The single most important guard in the module."""
        for role in (
            "ADMIN",
            "KVIC_OFFICER",
            "LAB_TECHNICIAN",
            "PROCESSOR",
            "COLLECTION_CENTER",
            "PACKAGING_UNIT",
            "DISTRIBUTOR",
            "RETAILER",
        ):
            response = client.post(
                f"{API}/auth/register",
                json={
                    "name": "Escalation Attempt",
                    "email": f"escalate-{role.lower()}@honeychain.example.com",
                    "password": "HoneyPass123",
                    "role": role,
                },
            )
            assert response.status_code == 422, role
            assert response.json()["error"]["details"]["allowed"] == ["CONSUMER", "BEEKEEPER"]

    def test_a_beekeeper_cannot_reach_the_admin_directory_after_registration(
        self, client: TestClient, auth_headers
    ):
        assert client.get(f"{API}/admin/users", headers=auth_headers).status_code == 403

    def test_ordinary_user_cannot_promote_themselves_through_profile_edits(
        self, client: TestClient, auth_headers
    ):
        for payload in ({"role": "ADMIN"}, {"is_active": True}, {"is_verified": True}):
            assert client.patch(f"{API}/profile", headers=auth_headers, json=payload).status_code == 422

        me = client.get(f"{API}/auth/me", headers=auth_headers).json()["data"]
        assert me["role"] == "BEEKEEPER"
        assert me["is_verified"] is False

    def test_a_deactivated_account_loses_access_immediately(
        self, client: TestClient, admin_headers, register_user
    ):
        victim = register_user(name="Deactivated", role="CONSUMER")
        headers = {"Authorization": f"Bearer {victim['access_token']}"}
        assert client.get(f"{API}/profile", headers=headers).status_code == 200

        client.patch(
            f"{API}/admin/users/{victim['user']['id']}/status",
            headers=admin_headers,
            json={"is_active": False},
        )

        # The existing access token stops working — deactivation is not deferred
        # until the token expires.
        assert client.get(f"{API}/profile", headers=headers).status_code == 403
        assert (
            client.post(
                f"{API}/auth/login",
                json={"email": victim["user"]["email"], "password": victim["_password"]},
            ).status_code
            == 403
        )

    def test_reactivation_restores_access(self, client: TestClient, admin_headers, register_user):
        user = register_user(name="Reactivated", role="CONSUMER")
        for is_active, expected in ((False, 403), (True, 200)):
            client.patch(
                f"{API}/admin/users/{user['user']['id']}/status",
                headers=admin_headers,
                json={"is_active": is_active},
            )
            response = client.post(
                f"{API}/auth/login",
                json={"email": user["user"]["email"], "password": user["_password"]},
            )
            assert response.status_code == expected


class TestAdministratorGuardRails:
    def test_an_admin_cannot_deactivate_their_own_account(self, client: TestClient, admin_headers, admin_payload):
        response = client.patch(
            f"{API}/admin/users/{admin_payload['id']}/status",
            headers=admin_headers,
            json={"is_active": False},
        )
        assert response.status_code == 422
        assert client.get(f"{API}/admin/summary", headers=admin_headers).status_code == 200

    def test_the_last_active_admin_cannot_be_deactivated(
        self, client: TestClient, admin_headers, admin_payload, kvic_payload, db
    ):
        """The platform must never end up with zero active administrators.

        With two active administrators either may be deactivated. Once only one
        remains the operation is refused. Through HTTP that state is reached by
        the self-guard first (covered above), so the rule itself is exercised at
        the service level with a different actor — the path a future feature
        (bulk suspension, for instance) would take.
        """
        from app.core.exceptions import ValidationError as AppValidationError
        from app.core.security import hash_password
        from app.models.enums import UserRole
        from app.models.user import User
        from app.repositories.user_repository import UserRepository
        from app.services.admin_service import AdminService

        users = UserRepository(db)

        second = users.create_user(
            name="Second Administrator",
            email="second.admin@honeychain.example.com",
            password_hash=hash_password("SecondAdminPass123"),
            role=UserRole.ADMIN,
        )
        db.commit()

        login = client.post(
            f"{API}/auth/login",
            json={"email": second.email, "password": "SecondAdminPass123"},
        )
        assert login.status_code == 200
        second_headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

        # Two active administrators: the original may be deactivated…
        assert (
            client.patch(
                f"{API}/admin/users/{admin_payload['id']}/status",
                headers=second_headers,
                json={"is_active": False},
            ).status_code
            == 200
        )

        # …but the one that remains may not be.
        service = AdminService(db)
        actor = db.get(User, kvic_payload["id"])
        with pytest.raises(AppValidationError) as excinfo:
            service.set_user_active(second.id, is_active=False, actor=actor)
        assert "last active administrator" in str(excinfo.value)

        # Promoting another administrator clears the condition.
        third = users.create_user(
            name="Third Administrator",
            email="third.admin@honeychain.example.com",
            password_hash=hash_password("ThirdAdminPass123"),
            role=UserRole.ADMIN,
        )
        db.commit()
        assert service.set_user_active(second.id, is_active=False, actor=third).is_active is False
