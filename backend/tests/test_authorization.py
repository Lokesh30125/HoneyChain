"""Role-based access control: the admin namespace must be ADMIN-only."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models.enums import UserRole
from tests.conftest import API_PREFIX


class TestAdminEndpoints:
    def test_admin_can_read_platform_summary(
        self, client: TestClient, admin_headers: dict
    ) -> None:
        response = client.get(f"{API_PREFIX}/admin/summary", headers=admin_headers)

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["users"]["total"] >= 1
        # Every role is reported so gaps in onboarding are visible.
        assert set(data["users"]["by_role"]) == set(UserRole.values())
        # Every module the platform ships is live, and the dashboard says so.
        assert data["modules"]["blockchain"] == "available"
        assert data["modules"]["supply_chain"] == "available"

    def test_beekeeper_is_forbidden_from_admin_area(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        response = client.get(f"{API_PREFIX}/admin/summary", headers=auth_headers)

        assert response.status_code == 403
        error = response.json()["error"]
        assert error["code"] == "PERMISSION_DENIED"
        assert error["details"]["your_role"] == UserRole.BEEKEEPER.value

    def test_consumer_is_forbidden_from_admin_area(
        self, client: TestClient, register_user
    ) -> None:
        consumer = register_user(role=UserRole.CONSUMER)

        response = client.get(
            f"{API_PREFIX}/admin/summary",
            headers={"Authorization": f"Bearer {consumer['access_token']}"},
        )

        assert response.status_code == 403

    def test_anonymous_user_is_unauthenticated_not_forbidden(
        self, client: TestClient
    ) -> None:
        response = client.get(f"{API_PREFIX}/admin/summary")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTHENTICATION_ERROR"

    def test_admin_user_directory_is_paginated(
        self, client: TestClient, admin_headers: dict, register_user, make_privileged_user
    ) -> None:
        register_user(role=UserRole.BEEKEEPER)
        # PROCESSSOR cannot self-register (Phase 2 policy), so it is provisioned
        # the way production does it: directly, by an administrator.
        make_privileged_user(role=UserRole.PROCESSOR)

        response = client.get(
            f"{API_PREFIX}/admin/users?page=1&page_size=2", headers=admin_headers
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 2
        assert body["meta"]["page"] == 1
        assert body["meta"]["page_size"] == 2
        assert body["meta"]["total_items"] >= 3
        assert body["meta"]["total_pages"] >= 2

    def test_admin_user_directory_filters_by_role(
        self, client: TestClient, admin_headers: dict, make_privileged_user
    ) -> None:
        make_privileged_user(role=UserRole.RETAILER)

        response = client.get(
            f"{API_PREFIX}/admin/users?role=RETAILER", headers=admin_headers
        )

        assert response.status_code == 200
        items = response.json()["data"]
        assert items and all(item["role"] == "RETAILER" for item in items)

    def test_unknown_role_filter_is_rejected(
        self, client: TestClient, admin_headers: dict
    ) -> None:
        response = client.get(
            f"{API_PREFIX}/admin/users?role=SUPREME_LEADER", headers=admin_headers
        )

        assert response.status_code == 422

    def test_admin_can_deactivate_an_account(
        self, client: TestClient, admin_headers: dict, user_payload: dict
    ) -> None:
        user_id = user_payload["user"]["id"]

        response = client.patch(
            f"{API_PREFIX}/admin/users/{user_id}/status",
            headers=admin_headers,
            json={"is_active": False, "reason": "Duplicate registration"},
        )

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["user"]["is_active"] is False
        assert body["user"]["account_status"] == "INACTIVE"
        assert body["message"] == "Account deactivated"

        # The deactivated user is now denied service.
        blocked = client.get(
            f"{API_PREFIX}/auth/me",
            headers={"Authorization": f"Bearer {user_payload['access_token']}"},
        )
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "ACCOUNT_INACTIVE"

    def test_deactivating_an_unknown_user_returns_404(
        self, client: TestClient, admin_headers: dict
    ) -> None:
        response = client.patch(
            f"{API_PREFIX}/admin/users/00000000-0000-0000-0000-000000000000/status",
            headers=admin_headers,
            json={"is_active": False},
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

    def test_malformed_user_id_is_a_validation_error(
        self, client: TestClient, admin_headers: dict
    ) -> None:
        response = client.patch(
            f"{API_PREFIX}/admin/users/not-a-uuid/status",
            headers=admin_headers,
            json={"is_active": False},
        )

        assert response.status_code == 422


class TestRoleCatalogue:
    def test_roles_endpoint_lists_all_ten_roles(self, client: TestClient) -> None:
        response = client.get(f"{API_PREFIX}/roles")

        assert response.status_code == 200
        roles = response.json()["data"]["roles"]
        assert len(roles) == 10
        assert {role["value"] for role in roles} == set(UserRole.values())

    def test_privileged_roles_are_not_self_registrable(self, client: TestClient) -> None:
        response = client.get(f"{API_PREFIX}/roles")
        by_value = {role["value"]: role for role in response.json()["data"]["roles"]}

        for role in (UserRole.ADMIN, UserRole.KVIC_OFFICER, UserRole.LAB_TECHNICIAN):
            assert by_value[role.value]["self_registrable"] is False
        assert by_value[UserRole.BEEKEEPER.value]["self_registrable"] is True
        assert by_value[UserRole.BEEKEEPER.value]["home_route"] == "/beekeeper"

    def test_role_catalogue_is_public(self, client: TestClient) -> None:
        """The registration page needs it before the user has a token."""
        assert client.get(f"{API_PREFIX}/roles").status_code == 200
