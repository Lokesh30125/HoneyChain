"""Audit log behaviour.

Two properties are asserted throughout: the trail records what happened (and who
did it), and it never becomes a place where credentials or personal secrets are
stored.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.models.enums import AuditAction

API = "/api/v1"


def actions_of(client: TestClient, headers, **params) -> list[str]:
    response = client.get(f"{API}/admin/audit-logs", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return [entry["action"] for entry in response.json()["data"]]


class TestAuditCapture:
    def test_registration_is_recorded(self, client: TestClient, admin_headers, register_user):
        payload = register_user(name="Audited Beekeeper", role="BEEKEEPER")
        entries = client.get(f"{API}/admin/audit-logs?entity_type=user", headers=admin_headers).json()["data"]

        registration = next(entry for entry in entries if entry["action"] == "USER_REGISTERED")
        assert registration["entity_id"] == payload["user"]["id"]
        assert registration["actor_email"] == payload["user"]["email"]
        assert registration["actor_role"] == "BEEKEEPER"

    def test_login_and_logout_are_recorded(self, client: TestClient, admin_headers, register_user):
        payload = register_user(name="Signing In", role="CONSUMER")
        login = client.post(
            f"{API}/auth/login",
            json={"email": payload["user"]["email"], "password": payload["_password"]},
        )
        assert login.status_code == 200

        actions = actions_of(client, admin_headers)
        assert "USER_LOGIN" in actions
        assert "USER_REGISTERED" in actions

        refresh = login.json()["data"]["refresh_token"]
        assert client.post(f"{API}/auth/logout", json={"refresh_token": refresh}).status_code == 200
        assert "USER_LOGOUT" in actions_of(client, admin_headers)

    def test_failed_login_is_recorded_without_the_password(
        self, client: TestClient, admin_headers, register_user
    ):
        payload = register_user(name="Wrong Password", role="CONSUMER")
        response = client.post(
            f"{API}/auth/login",
            json={"email": payload["user"]["email"], "password": "TotallyWrong123"},
        )
        assert response.status_code == 401

        entries = client.get(
            f"{API}/admin/audit-logs?action=USER_LOGIN_FAILED", headers=admin_headers
        ).json()["data"]
        assert len(entries) == 1
        assert entries[0]["description"] == "Failed sign-in attempt"
        # Only the domain is kept — never the address, never the password.
        assert entries[0]["metadata"]["email_domain"] == "honeychain.example.com"
        assert "TotallyWrong123" not in str(entries[0])

    def test_profile_update_records_field_names_not_values(
        self, client: TestClient, admin_headers, auth_headers, user_payload
    ):
        client.patch(
            f"{API}/profile",
            headers=auth_headers,
            json={"village": "Tenali", "date_of_birth": "1994-04-04"},
        )
        entries = client.get(
            f"{API}/admin/audit-logs?action=PROFILE_UPDATED", headers=admin_headers
        ).json()["data"]
        assert len(entries) == 1
        metadata = entries[0]["metadata"]
        assert metadata["changed_fields"] == ["date_of_birth", "village"]
        # The values themselves are personal data and are not copied into the log.
        assert "Tenali" not in str(entries[0])
        assert "1994-04-04" not in str(entries[0])

    def test_verification_decision_is_recorded_with_its_reason(
        self, client: TestClient, admin_headers, user_payload
    ):
        client.patch(
            f"{API}/beekeepers/{user_payload['beekeeper']['id']}/verification",
            headers=admin_headers,
            json={"status": "VERIFIED", "remarks": "Field visit on 12 March."},
        )
        entries = client.get(
            f"{API}/admin/audit-logs?action=BEEKEEPER_VERIFIED", headers=admin_headers
        ).json()["data"]
        assert len(entries) == 1
        assert entries[0]["entity_id"] == user_payload["beekeeper"]["id"]
        assert entries[0]["metadata"]["previous_status"] == "PENDING"
        assert entries[0]["metadata"]["new_status"] == "VERIFIED"
        assert entries[0]["metadata"]["remarks"] == "Field visit on 12 March."

    def test_cluster_events_are_recorded(self, client: TestClient, admin_headers, user_payload):
        cluster = client.post(
            f"{API}/clusters",
            headers=admin_headers,
            json={"cluster_name": "Audit Cluster", "district": "Guntur", "state": "Andhra Pradesh"},
        ).json()["data"]
        client.post(
            f"{API}/clusters/{cluster['id']}/beekeepers/{user_payload['beekeeper']['id']}",
            headers=admin_headers,
        )

        assert "CLUSTER_CREATED" in actions_of(client, admin_headers)
        # Phase 4.1 renamed this event to say what it actually changes: the
        # *beekeeper's* link, and through it their hives. The historical name is
        # kept as an enum alias so rows written earlier stay filterable, but new
        # rows are recorded under the relationship vocabulary.
        assert "BEEKEEPER_ASSIGNED_TO_CLUSTER" in actions_of(client, admin_headers)
        assert "CLUSTER_RELATIONSHIP_UPDATED" in actions_of(client, admin_headers)
        assert AuditAction.CLUSTER_MEMBER_ASSIGNED in set(AuditAction)

    def test_account_status_change_is_recorded(self, client: TestClient, admin_headers, register_user):
        victim = register_user(name="Suspended User", role="CONSUMER")
        response = client.patch(
            f"{API}/admin/users/{victim['user']['id']}/status",
            headers=admin_headers,
            json={"is_active": False, "reason": "Fraudulent activity reported."},
        )
        assert response.status_code == 200, response.text

        entries = client.get(
            f"{API}/admin/audit-logs?action=USER_DEACTIVATED", headers=admin_headers
        ).json()["data"]
        assert len(entries) == 1
        assert entries[0]["metadata"]["reason"] == "Fraudulent activity reported."
        assert entries[0]["actor_email"] == "admin@honeychain.example.com"

    def test_no_audit_entry_contains_a_credential(
        self, client: TestClient, admin_headers, register_user
    ):
        payload = register_user(name="Secret Check", role="CONSUMER")
        client.post(
            f"{API}/auth/login",
            json={"email": payload["user"]["email"], "password": payload["_password"]},
        )
        body = client.get(f"{API}/admin/audit-logs?page_size=100", headers=admin_headers).text
        assert payload["_password"] not in body
        assert payload["access_token"] not in body
        assert "password_hash" not in body
        assert "$2b$" not in body  # bcrypt hashes never reach the log


class TestAuditAccess:
    def test_only_administrators_can_read_the_log(
        self, client: TestClient, kvic_headers, auth_headers, consumer_headers
    ):
        """KVIC officers manage beekeepers, but the platform log is admin-only."""
        for headers in (kvic_headers, auth_headers, consumer_headers):
            assert client.get(f"{API}/admin/audit-logs", headers=headers).status_code == 403

    def test_requires_authentication(self, client: TestClient):
        assert client.get(f"{API}/admin/audit-logs").status_code == 401

    def test_filters_and_pagination(self, client: TestClient, admin_headers, register_user):
        for index in range(3):
            register_user(name=f"Bulk {index}", role="CONSUMER")

        page = client.get(f"{API}/admin/audit-logs?page=1&page_size=2", headers=admin_headers).json()
        assert len(page["data"]) == 2
        # Three registrations plus the administrator's own sign-in, which is
        # audited exactly like everyone else's.
        assert page["meta"]["total_items"] == 4
        assert page["meta"]["total_pages"] == 2

        filtered = client.get(
            f"{API}/admin/audit-logs?action=USER_REGISTERED&page_size=100", headers=admin_headers
        ).json()
        assert filtered["meta"]["total_items"] == 3

    def test_activity_summary_counts_recent_actions(self, client: TestClient, admin_headers, register_user):
        register_user(name="Activity One", role="CONSUMER")
        response = client.get(f"{API}/admin/activity?hours=24", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["window_hours"] == 24
        assert data["by_action"]["USER_REGISTERED"] >= 1

    def test_admin_user_detail_includes_recent_activity(
        self, client: TestClient, admin_headers, register_user
    ):
        payload = register_user(name="Detail Target", role="BEEKEEPER")
        response = client.get(f"{API}/admin/users/{payload['user']['id']}", headers=admin_headers)
        assert response.status_code == 200, response.text
        data = response.json()["data"]

        assert data["user"]["id"] == payload["user"]["id"]
        assert data["beekeeper"]["beekeeper_code"] == payload["beekeeper"]["beekeeper_code"]
        assert any(entry["action"] == "USER_REGISTERED" for entry in data["recent_activity"])

    def test_unknown_user_is_not_found(self, client: TestClient, admin_headers):
        assert client.get(f"{API}/admin/users/{uuid.uuid4()}", headers=admin_headers).status_code == 404
