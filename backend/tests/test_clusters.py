"""KVIC cluster endpoints — create, update, status and membership.

Scope note: this phase implements basic cluster management. Analytics on top of
clusters (production, quality, coverage) are a later phase and are asserted here
to be absent, so the boundary is explicit.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

API = "/api/v1"

CLUSTER = {
    "cluster_name": "Tenali Beekeeping Cluster",
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "description": "Beekeepers around Tenali mandal.",
    "coordinator_name": "S. Rao",
    "coordinator_phone": "9876543210",
}


class TestClusterCreation:
    def test_admin_creates_a_cluster_with_a_generated_code(self, client: TestClient, admin_headers):
        response = client.post(f"{API}/clusters", headers=admin_headers, json=CLUSTER)
        assert response.status_code == 201, response.text
        data = response.json()["data"]
        assert data["cluster_code"] == "KVIC-GNT-001"
        assert data["is_active"] is True
        # Phone numbers are normalised so filters and comparisons behave.
        assert data["coordinator_phone"] == "+919876543210"

    def test_kvic_officer_can_create(self, client: TestClient, kvic_headers):
        response = client.post(f"{API}/clusters", headers=kvic_headers, json=CLUSTER)
        assert response.status_code == 201, response.text

    def test_explicit_code_is_accepted_but_unique(self, client: TestClient, admin_headers):
        payload = {**CLUSTER, "cluster_code": "KVIC-GNT-999"}
        first = client.post(f"{API}/clusters", headers=admin_headers, json=payload)
        assert first.status_code == 201, first.text

        duplicate = client.post(f"{API}/clusters", headers=admin_headers, json=payload)
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["details"]["field"] == "cluster_code"

    def test_beekeepers_and_consumers_cannot_create(self, client: TestClient, auth_headers, consumer_headers):
        for headers in (auth_headers, consumer_headers):
            assert client.post(f"{API}/clusters", headers=headers, json=CLUSTER).status_code == 403

    def test_validation(self, client: TestClient, admin_headers):
        short_name = client.post(f"{API}/clusters", headers=admin_headers, json={**CLUSTER, "cluster_name": "AB"})
        assert short_name.status_code == 422

        bad_phone = client.post(
            f"{API}/clusters", headers=admin_headers, json={**CLUSTER, "coordinator_phone": "12"}
        )
        assert bad_phone.status_code == 422

        missing_state = client.post(
            f"{API}/clusters", headers=admin_headers, json={"cluster_name": "Nameless", "district": "Guntur"}
        )
        assert missing_state.status_code == 422


class TestClusterReads:
    def test_list_with_member_counts(self, client: TestClient, admin_headers, user_payload):
        created = client.post(f"{API}/clusters", headers=admin_headers, json=CLUSTER).json()["data"]
        client.post(
            f"{API}/clusters/{created['id']}/beekeepers/{user_payload['beekeeper']['id']}",
            headers=admin_headers,
        )

        listing = client.get(f"{API}/clusters", headers=admin_headers).json()
        assert listing["meta"]["total_items"] == 1
        assert listing["data"][0]["member_count"] == 1

    def test_empty_platform_reports_no_clusters(self, client: TestClient, admin_headers):
        listing = client.get(f"{API}/clusters", headers=admin_headers).json()
        assert listing["data"] == []
        assert listing["meta"]["total_items"] == 0

    def test_filters(self, client: TestClient, admin_headers):
        client.post(f"{API}/clusters", headers=admin_headers, json=CLUSTER)
        client.post(
            f"{API}/clusters",
            headers=admin_headers,
            json={**CLUSTER, "cluster_name": "Vijayawada Cluster", "district": "Krishna", "cluster_code": "KVIC-KRI-001"},
        )

        by_district = client.get(f"{API}/clusters?district=Guntur", headers=admin_headers).json()
        assert by_district["meta"]["total_items"] == 1

        by_search = client.get(f"{API}/clusters?search=vijayawada", headers=admin_headers).json()
        assert by_search["meta"]["total_items"] == 1

    def test_beekeeper_may_read_clusters(self, client: TestClient, auth_headers, admin_headers):
        """A beekeeper needs to know which cluster they belong to."""
        client.post(f"{API}/clusters", headers=admin_headers, json=CLUSTER)
        assert client.get(f"{API}/clusters", headers=auth_headers).status_code == 200

    def test_consumer_cannot_read_clusters(self, client: TestClient, consumer_headers):
        assert client.get(f"{API}/clusters", headers=consumer_headers).status_code == 403

    def test_unknown_cluster_is_not_found(self, client: TestClient, admin_headers):
        assert client.get(f"{API}/clusters/{uuid.uuid4()}", headers=admin_headers).status_code == 404


class TestClusterUpdates:
    def test_update_fields_but_not_the_code(self, client: TestClient, admin_headers):
        created = client.post(f"{API}/clusters", headers=admin_headers, json=CLUSTER).json()["data"]

        updated = client.put(
            f"{API}/clusters/{created['id']}",
            headers=admin_headers,
            json={"cluster_name": "Tenali Cluster (renamed)", "coordinator_name": "K. Devi"},
        )
        assert updated.status_code == 200, updated.text
        data = updated.json()["data"]
        assert data["cluster_name"] == "Tenali Cluster (renamed)"
        assert data["coordinator_name"] == "K. Devi"
        assert data["cluster_code"] == created["cluster_code"]

        # ``cluster_code`` is immutable and is not part of the update schema.
        attempt = client.put(
            f"{API}/clusters/{created['id']}", headers=admin_headers, json={"cluster_code": "KVIC-XXX-001"}
        )
        assert attempt.status_code == 422

    def test_status_change_and_idempotence(self, client: TestClient, admin_headers):
        created = client.post(f"{API}/clusters", headers=admin_headers, json=CLUSTER).json()["data"]

        deactivated = client.patch(
            f"{API}/clusters/{created['id']}/status",
            headers=admin_headers,
            json={"is_active": False, "reason": "Merged with the Tenali co-operative."},
        )
        assert deactivated.status_code == 200
        assert deactivated.json()["data"]["is_active"] is False

        repeat = client.patch(
            f"{API}/clusters/{created['id']}/status", headers=admin_headers, json={"is_active": False}
        )
        assert repeat.status_code == 422

        assert client.get(f"{API}/clusters?is_active=false", headers=admin_headers).json()["meta"][
            "total_items"
        ] == 1


class TestClusterMembership:
    def _cluster(self, client: TestClient, headers) -> dict:
        return client.post(f"{API}/clusters", headers=headers, json=CLUSTER).json()["data"]

    def test_add_and_remove_a_member(self, client: TestClient, admin_headers, user_payload):
        cluster = self._cluster(client, admin_headers)
        beekeeper_id = user_payload["beekeeper"]["id"]

        added = client.post(
            f"{API}/clusters/{cluster['id']}/beekeepers/{beekeeper_id}", headers=admin_headers
        )
        assert added.status_code == 200, added.text

        members = client.get(f"{API}/clusters/{cluster['id']}/beekeepers", headers=admin_headers).json()
        assert members["meta"]["total_items"] == 1
        assert members["data"][0]["beekeeper_code"] == user_payload["beekeeper"]["beekeeper_code"]

        # The beekeeper's own record reflects the assignment.
        record = client.get(f"{API}/beekeepers/{beekeeper_id}", headers=admin_headers).json()["data"]
        assert record["beekeeper"]["cluster"]["cluster_code"] == cluster["cluster_code"]

        removed = client.delete(
            f"{API}/clusters/{cluster['id']}/beekeepers/{beekeeper_id}", headers=admin_headers
        )
        assert removed.status_code == 200
        members_after = client.get(
            f"{API}/clusters/{cluster['id']}/beekeepers", headers=admin_headers
        ).json()
        assert members_after["meta"]["total_items"] == 0

    def test_double_add_is_rejected(self, client: TestClient, admin_headers, user_payload):
        cluster = self._cluster(client, admin_headers)
        path = f"{API}/clusters/{cluster['id']}/beekeepers/{user_payload['beekeeper']['id']}"
        assert client.post(path, headers=admin_headers).status_code == 200
        assert client.post(path, headers=admin_headers).status_code == 422

    def test_removing_a_non_member_is_rejected(self, client: TestClient, admin_headers, user_payload):
        cluster = self._cluster(client, admin_headers)
        response = client.delete(
            f"{API}/clusters/{cluster['id']}/beekeepers/{user_payload['beekeeper']['id']}",
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_inactive_cluster_cannot_accept_members(self, client: TestClient, admin_headers, user_payload):
        cluster = self._cluster(client, admin_headers)
        client.patch(f"{API}/clusters/{cluster['id']}/status", headers=admin_headers, json={"is_active": False})

        response = client.post(
            f"{API}/clusters/{cluster['id']}/beekeepers/{user_payload['beekeeper']['id']}",
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_beekeeper_cannot_manage_membership(self, client: TestClient, auth_headers, admin_headers, user_payload):
        cluster = self._cluster(client, admin_headers)
        response = client.post(
            f"{API}/clusters/{cluster['id']}/beekeepers/{user_payload['beekeeper']['id']}",
            headers=auth_headers,
        )
        assert response.status_code == 403

    def test_a_beekeeper_cannot_claim_a_cluster_at_registration(
        self, client: TestClient, admin_headers, register_user
    ):
        """Membership is granted by an officer, never claimed on the public form."""
        cluster = self._cluster(client, admin_headers)

        rejected = client.post(
            f"{API}/auth/register",
            json={
                "name": "Self Assigner",
                "email": "self.assigner@honeychain.example.com",
                "password": "HoneyPass123",
                "role": "BEEKEEPER",
                "beekeeper": {"district": "Guntur", "kvic_cluster_id": cluster["id"]},
            },
        )
        assert rejected.status_code == 422, rejected.text

        # A freshly registered beekeeper is therefore unassigned…
        payload = register_user(role="BEEKEEPER", beekeeper={"district": "Guntur"})
        record = client.get(f"{API}/beekeepers/{payload['beekeeper']['id']}", headers=admin_headers).json()[
            "data"
        ]
        assert record["beekeeper"]["cluster"] is None

        # …until an officer places them in a cluster.
        assignment = client.put(
            f"{API}/beekeepers/{payload['beekeeper']['id']}",
            headers=admin_headers,
            json={"kvic_cluster_id": cluster["id"]},
        )
        assert assignment.status_code == 200, assignment.text
        assert assignment.json()["data"]["cluster"]["cluster_code"] == cluster["cluster_code"]

        # An administrator can also remove the assignment with an explicit null.
        cleared = client.put(
            f"{API}/beekeepers/{payload['beekeeper']['id']}",
            headers=admin_headers,
            json={"kvic_cluster_id": None},
        )
        assert cleared.status_code == 200
        assert cleared.json()["data"]["cluster"] is None


class TestScopeBoundary:
    def test_no_analytics_endpoints_exist(self, client: TestClient, admin_headers):
        """Advanced KVIC analytics belong to a later phase.

        ``/clusters/analytics`` is not a route; it is only matched by
        ``/clusters/{cluster_id}`` and fails UUID validation there, which is why
        422 is an acceptable (and non-leaking) response.
        """
        for path, expected in (
            (f"{API}/clusters/analytics", (404, 422)),
            (f"{API}/clusters/summary/analytics", (404,)),
            (f"{API}/kvic/analytics", (404,)),
            (f"{API}/kvic/clusters", (404,)),
        ):
            status = client.get(path, headers=admin_headers).status_code
            assert status in expected, (path, status)
