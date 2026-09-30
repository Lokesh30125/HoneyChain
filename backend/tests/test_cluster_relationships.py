"""Phase 4.1 — the organisational relationship, end to end.

The chain under test is

``KVIC → Cluster → Beekeeper → Hive → IoT Device → Telemetry → AI Analysis``

and there is exactly one claim to defend: **a beekeeper's data belongs to their
cluster without being entered twice, and nobody can move it anywhere by editing a
request.** Every test below is an attempt to break that claim — from the
beekeeper's side (can I pick a cluster?), from a stranger's side (can I read this
cluster?), and from the platform's side (is the hive in two places at once, or in
none?).

Two rules for reading these tests:

* assertions are made against the **same row** read through two different views
  — the owner's endpoint and the cluster's — because "it appears in both" is only
  meaningful if it is one record;
* nothing is asserted about a value that was not stored. A hive with no cluster
  is expected to be *absent* from a cluster view and *present* in the
  administrative worklist, never silently attached anywhere.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.enums import HiveStatus, VerificationStatus
from app.models.hive import Hive
from app.models.user import User

API = "/api/v1"

HIVE_PAYLOAD = {
    "bee_species": "Apis cerana indica",
    "village": "Tenali",
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "pincode": "522201",
}

CLUSTER_PAYLOAD = {
    "cluster_name": "Guntur Cluster",
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "coordinator_name": "K. Rao",
    "coordinator_phone": "9876543210",
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def make_cluster(client: TestClient, headers: dict, **overrides) -> dict:
    response = client.post(f"{API}/clusters", headers=headers, json={**CLUSTER_PAYLOAD, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def make_hive(client: TestClient, headers: dict, **overrides) -> dict:
    response = client.post(f"{API}/hives", headers=headers, json={**HIVE_PAYLOAD, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def make_device(client: TestClient, headers: dict, hive_id: str, device_id: str = "ESP32-GNT-0001") -> dict:
    response = client.post(
        f"{API}/iot/devices",
        headers=headers,
        json={"device_id": device_id, "device_name": "North field node", "hive_id": hive_id},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def add_member(client: TestClient, headers: dict, cluster_id: str, beekeeper_id: str):
    return client.post(f"{API}/clusters/{cluster_id}/beekeepers/{beekeeper_id}", headers=headers)


def post_window(
    client: TestClient,
    headers: dict,
    device_id: str,
    *,
    samples: int = 12,
    spread_hours: float = 6,
    ends_hours_ago: float = 0,
    temperature: float = 33.4,
    humidity: float = 58.0,
    weight: float = 40.0,
) -> None:
    """Store a backdated telemetry window through the public ingest endpoint."""
    end = datetime.now(timezone.utc) - timedelta(hours=ends_hours_ago)
    step = timedelta(hours=spread_hours) / max(1, samples - 1)
    for index in range(samples):
        moment = end - step * (samples - 1 - index)
        response = client.post(
            f"{API}/iot/telemetry",
            headers=headers,
            json={
                "device_id": device_id,
                "timestamp": moment.isoformat(),
                "temperature": temperature + (index % 5) * 0.2,
                "humidity": humidity + (index % 3) * 0.4,
                "weight": weight + index * 0.02,
                "vibration": 0.6,
                "acoustic_level": 42.0,
                "battery_level": 88,
                "source": "SIMULATOR",
            },
        )
        assert response.status_code in (201, 200), response.text


def headers_for(payload: dict) -> dict[str, str]:
    """Bearer headers for a user returned by the ``register_user`` factory."""
    return {"Authorization": f"Bearer {payload['access_token']}"}


def actions_of(db: Session) -> list[str]:
    db.expire_all()
    return [row.action for row in db.query(AuditLog).all()]


# --------------------------------------------------------------------------- #
# 1–3, 15–17 — membership, authority and isolation
# --------------------------------------------------------------------------- #
class TestClusterMembership:
    def test_a_new_beekeeper_starts_without_a_cluster(self, client: TestClient, auth_headers):
        """Membership is granted, never assumed."""
        # A beekeeper reads their own record through /beekeepers/me: reading by id
        # is the staff route, and a beekeeper holds no such grant.
        response = client.get(f"{API}/beekeepers/me", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["data"]["cluster"] is None

    def test_a_kvic_officer_assigns_the_beekeeper_to_a_cluster(
        self, client: TestClient, kvic_headers, auth_headers, beekeeper_record
    ):
        cluster = make_cluster(client, kvic_headers)
        response = add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])
        assert response.status_code == 200, response.text

        detail = client.get(f"{API}/beekeepers/me", headers=auth_headers)
        assert detail.json()["data"]["cluster"]["cluster_code"] == cluster["cluster_code"]

    def test_the_beekeeper_cannot_assign_themselves(self, client: TestClient, kvic_headers, auth_headers, beekeeper_record):
        """`CLUSTER_MANAGE` is what grants membership; a beekeeper does not hold it."""
        cluster = make_cluster(client, kvic_headers)
        response = add_member(client, auth_headers, cluster["id"], beekeeper_record["id"])
        assert response.status_code == 403

    def test_a_consumer_cannot_assign_anyone(self, client: TestClient, kvic_headers, consumer_headers, beekeeper_record):
        cluster = make_cluster(client, kvic_headers)
        assert add_member(client, consumer_headers, cluster["id"], beekeeper_record["id"]).status_code == 403

    def test_membership_is_audited_under_the_relationship_vocabulary(
        self, client: TestClient, kvic_headers, db: Session, beekeeper_record
    ):
        cluster = make_cluster(client, kvic_headers)
        add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])

        actions = actions_of(db)
        assert "BEEKEEPER_ASSIGNED_TO_CLUSTER" in actions
        assert "CLUSTER_RELATIONSHIP_UPDATED" in actions

    def test_removing_a_member_clears_the_link_without_deleting_anything(
        self, client: TestClient, kvic_headers, auth_headers, db: Session, beekeeper_record
    ):
        cluster = make_cluster(client, kvic_headers)
        add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)

        response = client.delete(
            f"{API}/clusters/{cluster['id']}/beekeepers/{beekeeper_record['id']}",
            headers=kvic_headers,
        )
        assert response.status_code == 200

        # The hive still exists, still belongs to its owner, and is now waiting
        # for administrative placement rather than being attached elsewhere.
        still_there = client.get(f"{API}/hives/{hive['id']}", headers=auth_headers).json()["data"]
        assert still_there["hive_code"] == hive["hive_code"]
        assert still_there["cluster"] is None
        assert "BEEKEEPER_REMOVED_FROM_CLUSTER" in actions_of(db)

    def test_an_inactive_cluster_cannot_accept_members(
        self, client: TestClient, kvic_headers, beekeeper_record
    ):
        cluster = make_cluster(client, kvic_headers)
        client.patch(
            f"{API}/clusters/{cluster['id']}/status",
            headers=kvic_headers,
            json={"is_active": False, "reason": "Merged into the district cluster"},
        )
        response = add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])
        assert response.status_code == 422


# --------------------------------------------------------------------------- #
# 4–6 — hive creation inherits the cluster, and the payload cannot change that
# --------------------------------------------------------------------------- #
class TestHiveInheritsTheCluster:
    def test_a_hive_registered_before_any_cluster_has_none(self, client: TestClient, auth_headers):
        hive = make_hive(client, auth_headers)
        assert hive["cluster"] is None

    def test_a_hive_inherits_the_owners_cluster_at_creation(
        self, client: TestClient, kvic_headers, auth_headers, beekeeper_record
    ):
        cluster = make_cluster(client, kvic_headers)
        add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])

        hive = make_hive(client, auth_headers)
        assert hive["cluster"]["cluster_code"] == cluster["cluster_code"]

    def test_the_beekeeper_cannot_choose_a_cluster_in_the_payload(
        self, client: TestClient, kvic_headers, auth_headers, beekeeper_record
    ):
        """The one request that would let an apiary be published into a stranger's cluster."""
        mine = make_cluster(client, kvic_headers, cluster_name="Guntur Cluster")
        theirs = make_cluster(
            client, kvic_headers, cluster_name="Vijayawada Cluster", district="Krishna"
        )
        add_member(client, kvic_headers, mine["id"], beekeeper_record["id"])

        response = client.post(
            f"{API}/hives",
            headers=auth_headers,
            json={**HIVE_PAYLOAD, "cluster_id": theirs["id"]},
        )
        # `extra="forbid"` on the schema: the field is not "ignored politely", it
        # is refused, so no client can believe it took effect.
        assert response.status_code == 422
        assert any(
            "cluster_id" in str(detail) for detail in response.json()["error"]["details"]
        )

        allowed = make_hive(client, auth_headers)
        assert allowed["cluster"]["cluster_code"] == mine["cluster_code"]

    def test_a_reassigned_beekeeper_takes_their_hives_with_them(
        self, client: TestClient, kvic_headers, auth_headers, beekeeper_record
    ):
        first = make_cluster(client, kvic_headers, cluster_name="Guntur Cluster")
        second = make_cluster(
            client, kvic_headers, cluster_name="Vijayawada Cluster", district="Krishna"
        )
        add_member(client, kvic_headers, first["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)

        add_member(client, kvic_headers, second["id"], beekeeper_record["id"])

        detail = client.get(f"{API}/hives/{hive['id']}", headers=auth_headers).json()["data"]
        assert detail["cluster"]["cluster_code"] == second["cluster_code"]

    def test_the_hive_is_one_row_not_two(self, client: TestClient, kvic_headers, auth_headers, beekeeper_record, db: Session):
        cluster = make_cluster(client, kvic_headers)
        add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)

        db.expire_all()
        rows = db.query(Hive).filter(Hive.hive_code == hive["hive_code"]).all()
        assert len(rows) == 1
        assert str(rows[0].cluster_id) == cluster["id"]
        assert str(rows[0].beekeeper_id) == beekeeper_record["id"]

    def test_a_beekeeper_still_sees_only_their_own_hives(
        self, client: TestClient, kvic_headers, auth_headers, beekeeper_record, register_user
    ):
        cluster = make_cluster(client, kvic_headers)
        add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])
        mine = make_hive(client, auth_headers)

        neighbour = register_user(name="Neighbour", email=None)
        add_member(client, kvic_headers, cluster["id"], neighbour["beekeeper"]["id"])

        listed = client.get(f"{API}/beekeepers/me/hives", headers=auth_headers).json()["data"]
        assert [row["hive_code"] for row in listed] == [mine["hive_code"]]

        # And the neighbour cannot read mine, cluster or no cluster.
        assert (
            client.get(f"{API}/hives/{mine['id']}", headers=headers_for(neighbour)).status_code == 404
        )


# --------------------------------------------------------------------------- #
# 7–9, 18 — the cluster view is the same record, and only within the cluster
# --------------------------------------------------------------------------- #
class TestClusterView:
    def test_the_cluster_sees_the_hive_the_beekeeper_registered(
        self, client: TestClient, kvic_headers, auth_headers, beekeeper_record
    ):
        cluster = make_cluster(client, kvic_headers)
        add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)

        listed = client.get(f"{API}/clusters/{cluster['id']}/hives", headers=kvic_headers)
        assert listed.status_code == 200
        assert [row["hive_code"] for row in listed.json()["data"]] == [hive["hive_code"]]

    def test_a_hive_outside_the_cluster_is_not_in_the_view(
        self, client: TestClient, kvic_headers, auth_headers, register_user
    ):
        cluster = make_cluster(client, kvic_headers)
        outside = register_user(name="Outside Apiary", email=None)
        their_hive = make_hive(client, headers_for(outside))

        listed = client.get(f"{API}/clusters/{cluster['id']}/hives", headers=kvic_headers).json()["data"]
        assert listed == []
        assert their_hive["hive_code"] not in [row["hive_code"] for row in listed]

    def test_an_update_is_a_single_row_seen_by_both_views(
        self, client: TestClient, kvic_headers, auth_headers, beekeeper_record, db: Session
    ):
        cluster = make_cluster(client, kvic_headers)
        add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)

        response = client.patch(
            f"{API}/hives/{hive['id']}/status",
            headers=auth_headers,
            json={"status": HiveStatus.MAINTENANCE.value, "reason": "Repainting the roof"},
        )
        assert response.status_code == 200

        owner_view = client.get(f"{API}/hives/{hive['id']}", headers=auth_headers).json()["data"]
        cluster_view = client.get(f"{API}/clusters/{cluster['id']}/hives", headers=kvic_headers).json()["data"][0]

        assert owner_view["status"] == HiveStatus.MAINTENANCE.value
        assert cluster_view["status"] == HiveStatus.MAINTENANCE.value  # same row, no sync job

        db.expire_all()
        assert db.query(Hive).filter(Hive.id == hive["id"]).one().status is HiveStatus.MAINTENANCE

    def test_the_cluster_hive_list_is_paginated(self, client: TestClient, kvic_headers, auth_headers, beekeeper_record):
        cluster = make_cluster(client, kvic_headers)
        add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])
        for index in range(3):
            make_hive(client, auth_headers, village=f"Village {index}")

        page = client.get(
            f"{API}/clusters/{cluster['id']}/hives",
            headers=kvic_headers,
            params={"page": 1, "page_size": 2},
        ).json()
        assert len(page["data"]) == 2
        assert page["meta"]["total_items"] == 3
        assert page["meta"]["total_pages"] == 2

    def test_a_beekeeper_cannot_read_a_cluster_view(self, client: TestClient, kvic_headers, auth_headers):
        cluster = make_cluster(client, kvic_headers)
        for path in (
            f"/clusters/{cluster['id']}/summary",
            f"/clusters/{cluster['id']}/hives",
            f"/clusters/{cluster['id']}/devices",
            f"/clusters/{cluster['id']}/ai",
            f"/clusters/{cluster['id']}/telemetry/latest",
        ):
            assert client.get(f"{API}{path}", headers=auth_headers).status_code == 403, path

    def test_a_consumer_cannot_read_a_cluster_view(self, client: TestClient, kvic_headers, consumer_headers):
        cluster = make_cluster(client, kvic_headers)
        assert (
            client.get(f"{API}/clusters/{cluster['id']}/summary", headers=consumer_headers).status_code
            == 403
        )

    def test_an_unknown_cluster_is_a_404(self, client: TestClient, kvic_headers):
        import uuid

        assert (
            client.get(f"{API}/clusters/{uuid.uuid4()}/summary", headers=kvic_headers).status_code == 404
        )


# --------------------------------------------------------------------------- #
# 10–11 — the IoT and telemetry chain
# --------------------------------------------------------------------------- #
class TestDeviceAndTelemetryChain:
    def test_a_device_inherits_visibility_through_its_hive(
        self, client: TestClient, kvic_headers, auth_headers, beekeeper_record
    ):
        cluster = make_cluster(client, kvic_headers)
        add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)
        device = make_device(client, auth_headers, hive["id"])

        listed = client.get(f"{API}/clusters/{cluster['id']}/devices", headers=kvic_headers).json()["data"]
        assert [row["device_id"] for row in listed] == [device["device_id"]]
        assert listed[0]["hive_code"] == hive["hive_code"]

    def test_pairing_a_device_needs_no_cluster_information(
        self, client: TestClient, kvic_headers, auth_headers, beekeeper_record
    ):
        """The ESP32 payload carries hardware and a hive id — nothing organisational."""
        cluster = make_cluster(client, kvic_headers)
        add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)

        response = client.post(
            f"{API}/iot/devices",
            headers=auth_headers,
            json={
                "device_id": "ESP32-GNT-0009",
                "device_name": "South row node",
                "hive_id": hive["id"],
                "cluster_id": cluster["id"],  # would be refused if it were accepted
            },
        )
        assert response.status_code == 422

        device = make_device(client, auth_headers, hive["id"], device_id="ESP32-GNT-0009")
        assert device["hive_id"] == hive["id"]

        listed = client.get(f"{API}/clusters/{cluster['id']}/devices", headers=kvic_headers).json()["data"]
        assert "ESP32-GNT-0009" in [row["device_id"] for row in listed]

    def test_telemetry_is_visible_through_the_cluster_and_not_copied(
        self, client: TestClient, kvic_headers, auth_headers, beekeeper_record
    ):
        cluster = make_cluster(client, kvic_headers)
        add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)
        device = make_device(client, auth_headers, hive["id"])
        post_window(client, auth_headers, device["device_id"], samples=6, spread_hours=3)

        latest = client.get(f"{API}/clusters/{cluster['id']}/telemetry/latest", headers=kvic_headers)
        assert latest.status_code == 200
        data = latest.json()["data"]
        assert data["has_data"] is True
        assert data["hive_code"] == hive["hive_code"]
        assert data["device_id"] == device["device_id"]
        assert data["beekeeper_code"] == beekeeper_record["beekeeper_code"]
        assert data["reading"]["temperature"] is not None

        # The owner reads the same packet through the telemetry endpoint. The
        # payload shape there is per-device, so the comparison is on the stored
        # values and the timestamp of the hive's newest reading.
        mine = client.get(f"{API}/iot/telemetry/{hive['id']}/latest", headers=auth_headers)
        assert mine.status_code == 200
        latest = mine.json()["data"]["latest"]
        assert latest["timestamp"] == data["reading"]["timestamp"]
        assert latest["temperature"] == data["reading"]["temperature"]
        assert latest["source"] == data["reading"]["source"]

    def test_an_empty_cluster_says_so_instead_of_reporting_zeroes(
        self, client: TestClient, kvic_headers
    ):
        cluster = make_cluster(client, kvic_headers)
        data = client.get(
            f"{API}/clusters/{cluster['id']}/telemetry/latest", headers=kvic_headers
        ).json()["data"]
        assert data["has_data"] is False
        assert data["hive_count"] == 0
        assert data["reading"] is None

    def test_a_stranger_cannot_reach_another_apiarys_telemetry_through_the_cluster(
        self, client: TestClient, kvic_headers, auth_headers, beekeeper_record, register_user
    ):
        cluster = make_cluster(client, kvic_headers)
        add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)
        device = make_device(client, auth_headers, hive["id"])
        post_window(client, auth_headers, device["device_id"], samples=4, spread_hours=1)

        stranger = register_user(name="Stranger", email=None)
        assert (
            client.get(f"{API}/iot/telemetry/{hive['id']}", headers=headers_for(stranger)).status_code
            == 404
        )


# --------------------------------------------------------------------------- #
# 12, 16 — AI analyses are reached through the chain, never re-created per cluster
# --------------------------------------------------------------------------- #
class TestAiThroughTheCluster:
    def test_an_analysis_is_visible_through_the_cluster(
        self, client: TestClient, kvic_headers, auth_headers, beekeeper_record
    ):
        cluster = make_cluster(client, kvic_headers)
        add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)
        device = make_device(client, auth_headers, hive["id"])
        post_window(client, auth_headers, device["device_id"], samples=12, spread_hours=6)

        run = client.post(f"{API}/ai/hives/{hive['id']}/analyze", headers=auth_headers, json={})
        assert run.status_code == 200, run.text
        analysis_id = run.json()["data"]["analysis_id"]

        state = client.get(f"{API}/clusters/{cluster['id']}/ai", headers=kvic_headers)
        assert state.status_code == 200
        payload = state.json()["data"]
        row = next(item for item in payload["hives"] if item["hive_code"] == hive["hive_code"])
        assert row["analyzed"] is True
        assert row["analysis_source"] == "SIMULATOR"
        assert payload["summary"]["total_hives"] == 1

        # The same stored analysis, read through the owner's endpoint: one record.
        owner_view = client.get(f"{API}/ai/hives/{hive['id']}", headers=auth_headers).json()["data"]
        assert str(owner_view["analysis_id"]) == str(analysis_id)

    def test_the_cluster_ai_view_does_not_create_a_second_analysis_row(
        self, client: TestClient, kvic_headers, auth_headers, beekeeper_record, db: Session
    ):
        from app.models.ai_analysis import HiveAiAnalysis

        cluster = make_cluster(client, kvic_headers)
        add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)
        device = make_device(client, auth_headers, hive["id"])
        post_window(client, auth_headers, device["device_id"], samples=12, spread_hours=6)
        client.post(f"{API}/ai/hives/{hive['id']}/analyze", headers=auth_headers, json={})

        db.expire_all()
        before = db.query(HiveAiAnalysis).count()
        assert before == 1

        for _ in range(3):
            client.get(f"{API}/clusters/{cluster['id']}/ai", headers=kvic_headers)

        db.expire_all()
        assert db.query(HiveAiAnalysis).count() == before

    def test_a_hive_without_an_analysis_is_listed_rather_than_hidden(
        self, client: TestClient, kvic_headers, auth_headers, beekeeper_record
    ):
        cluster = make_cluster(client, kvic_headers)
        add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)

        payload = client.get(f"{API}/clusters/{cluster['id']}/ai", headers=kvic_headers).json()["data"]
        row = next(item for item in payload["hives"] if item["hive_code"] == hive["hive_code"])
        assert row["analyzed"] is False
        assert row["health_score"] is None
        assert payload["summary"]["hives_without_analysis"] == 1


# --------------------------------------------------------------------------- #
# 13 — dashboard counters, all of them counted
# --------------------------------------------------------------------------- #
class TestClusterCounts:
    def test_counters_reflect_the_relationships(
        self, client: TestClient, kvic_headers, auth_headers, beekeeper_record, register_user
    ):
        cluster = make_cluster(client, kvic_headers)
        add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])
        second = register_user(name="Second Member", email=None)
        add_member(client, kvic_headers, cluster["id"], second["beekeeper"]["id"])

        first_hive = make_hive(client, auth_headers)
        make_hive(client, auth_headers, village="Kuchipudi")
        outsider = register_user(name="Not a member", email=None)
        make_hive(client, headers_for(outsider), village="Somewhere else")

        device = make_device(client, auth_headers, first_hive["id"])
        post_window(client, auth_headers, device["device_id"], samples=5, spread_hours=2)

        overview = client.get(f"{API}/clusters/{cluster['id']}/summary", headers=kvic_headers)
        assert overview.status_code == 200, overview.text
        data = overview.json()["data"]

        assert data["cluster"]["cluster_code"] == cluster["cluster_code"]
        assert data["beekeepers"]["total"] == 2
        assert data["beekeepers"]["pending"] == 2  # nobody has been verified yet
        assert data["hives"]["total"] == 2  # the outsider's hive is not counted
        assert data["hives"]["active"] == 2
        assert data["hives"]["with_device"] == 1
        assert data["hives"]["without_device"] == 1
        assert data["devices"]["total"] == 1
        assert data["devices"]["online"] == 1
        assert data["devices"]["offline"] == 0
        assert data["telemetry"]["readings_last_24h"] == 5
        assert data["telemetry"]["hives_with_telemetry"] == 1
        assert data["ai"]["analysed_hives"] == 0
        assert data["ai"]["open_alerts"] == 0

    def test_an_empty_cluster_reports_zeroes_not_samples(self, client: TestClient, kvic_headers):
        cluster = make_cluster(client, kvic_headers)
        data = client.get(f"{API}/clusters/{cluster['id']}/summary", headers=kvic_headers).json()["data"]
        assert data["beekeepers"]["total"] == 0
        assert data["hives"]["total"] == 0
        assert data["devices"]["total"] == 0
        assert data["telemetry"]["readings_last_24h"] == 0
        assert data["ai"]["analysed_hives"] == 0

    def test_counts_change_when_a_member_joins_and_leaves(
        self, client: TestClient, kvic_headers, auth_headers, beekeeper_record
    ):
        cluster = make_cluster(client, kvic_headers)
        empty = client.get(f"{API}/clusters/{cluster['id']}/summary", headers=kvic_headers).json()["data"]
        assert empty["hives"]["total"] == 0

        add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])
        make_hive(client, auth_headers)
        joined = client.get(f"{API}/clusters/{cluster['id']}/summary", headers=kvic_headers).json()["data"]
        assert joined["hives"]["total"] == 1

        client.delete(
            f"{API}/clusters/{cluster['id']}/beekeepers/{beekeeper_record['id']}",
            headers=kvic_headers,
        )
        left = client.get(f"{API}/clusters/{cluster['id']}/summary", headers=kvic_headers).json()["data"]
        assert left["hives"]["total"] == 0


# --------------------------------------------------------------------------- #
# 14 — the administrative worklist for hives without a cluster
# --------------------------------------------------------------------------- #
class TestUnassignedHives:
    def test_a_hive_without_a_cluster_is_listed_for_resolution(
        self, client: TestClient, kvic_headers, auth_headers
    ):
        hive = make_hive(client, auth_headers)

        summary = client.get(f"{API}/hives/summary", headers=kvic_headers).json()["data"]
        assert summary["without_cluster"] == 1

        worklist = client.get(
            f"{API}/hives", headers=kvic_headers, params={"has_cluster": False}
        ).json()["data"]
        assert [row["hive_code"] for row in worklist] == [hive["hive_code"]]

    def test_staff_place_an_unassigned_hive_and_it_is_audited(
        self, client: TestClient, kvic_headers, auth_headers, db: Session
    ):
        cluster = make_cluster(client, kvic_headers)
        hive = make_hive(client, auth_headers)

        response = client.post(
            f"{API}/hives/{hive['id']}/cluster",
            headers=kvic_headers,
            json={"cluster_id": cluster["id"], "reason": "Owner cluster missing at registration"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["cluster"]["cluster_code"] == cluster["cluster_code"]

        actions = actions_of(db)
        assert "HIVE_ASSOCIATED_WITH_CLUSTER" in actions
        assert "CLUSTER_RELATIONSHIP_UPDATED" in actions

        listed = client.get(f"{API}/clusters/{cluster['id']}/hives", headers=kvic_headers).json()["data"]
        assert hive["hive_code"] in [row["hive_code"] for row in listed]

    def test_a_beekeeper_cannot_place_their_own_hive_in_a_cluster(
        self, client: TestClient, kvic_headers, auth_headers
    ):
        cluster = make_cluster(client, kvic_headers)
        hive = make_hive(client, auth_headers)

        response = client.post(
            f"{API}/hives/{hive['id']}/cluster",
            headers=auth_headers,
            json={"cluster_id": cluster["id"]},
        )
        assert response.status_code == 403
        assert client.get(f"{API}/hives/{hive['id']}", headers=auth_headers).json()["data"]["cluster"] is None

    def test_placement_can_be_cleared_without_deleting_the_hive(
        self, client: TestClient, kvic_headers, auth_headers, beekeeper_record
    ):
        cluster = make_cluster(client, kvic_headers)
        add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)

        response = client.post(
            f"{API}/hives/{hive['id']}/cluster", headers=kvic_headers, json={"cluster_id": None}
        )
        assert response.status_code == 200
        assert response.json()["data"]["cluster"] is None
        assert client.get(f"{API}/hives/{hive['id']}", headers=auth_headers).status_code == 200

    def test_a_hive_cannot_be_placed_in_an_inactive_cluster(
        self, client: TestClient, kvic_headers, auth_headers
    ):
        cluster = make_cluster(client, kvic_headers)
        client.patch(
            f"{API}/clusters/{cluster['id']}/status",
            headers=kvic_headers,
            json={"is_active": False},
        )
        hive = make_hive(client, auth_headers)
        response = client.post(
            f"{API}/hives/{hive['id']}/cluster",
            headers=kvic_headers,
            json={"cluster_id": cluster["id"]},
        )
        assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Backfill and verification-state interaction
# --------------------------------------------------------------------------- #
class TestBackfillAndVerification:
    def test_the_backfill_links_existing_hives_to_their_owners_cluster(
        self, client: TestClient, kvic_headers, auth_headers, beekeeper_record, db: Session
    ):
        """The migration's rule, exercised as a statement rather than as a fixture.

        A hive registered before the owner joined a cluster keeps ``cluster_id``
        NULL; assigning the owner afterwards moves it, which is the same repair
        ``5e2b7d41c8aa`` performs for rows that predate the relationship.
        """
        from sqlalchemy import text

        cluster = make_cluster(client, kvic_headers)
        hive = make_hive(client, auth_headers)

        db.expire_all()
        db.execute(
            text(
                "UPDATE beekeepers SET kvic_cluster_id = :cluster WHERE id = :beekeeper"
            ),
            {"cluster": cluster["id"], "beekeeper": beekeeper_record["id"]},
        )
        db.commit()

        # Now run the migration's statement verbatim, as the migration would.
        db.execute(
            text(
                """
                UPDATE hives
                   SET cluster_id = beekeepers.kvic_cluster_id
                  FROM beekeepers
                 WHERE hives.beekeeper_id = beekeepers.id
                   AND hives.cluster_id IS NULL
                   AND beekeepers.kvic_cluster_id IS NOT NULL
                """
            )
        )
        db.commit()

        detail = client.get(f"{API}/hives/{hive['id']}", headers=auth_headers).json()["data"]
        assert detail["cluster"]["cluster_code"] == cluster["cluster_code"]

    def test_the_backfill_never_invents_a_cluster(self, client: TestClient, auth_headers, db: Session):
        """No cluster on the beekeeper → the hive stays unassigned, not guessed."""
        from sqlalchemy import text

        hive = make_hive(client, auth_headers)
        db.execute(
            text(
                """
                UPDATE hives
                   SET cluster_id = beekeepers.kvic_cluster_id
                  FROM beekeepers
                 WHERE hives.beekeeper_id = beekeepers.id
                   AND hives.cluster_id IS NULL
                   AND beekeepers.kvic_cluster_id IS NOT NULL
                """
            )
        )
        db.commit()

        assert client.get(f"{API}/hives/{hive['id']}", headers=auth_headers).json()["data"]["cluster"] is None

    def test_an_unverified_member_is_counted_but_flagged(
        self, client: TestClient, kvic_headers, beekeeper_record
    ):
        """Verification state travels with the membership; it is not re-stored per cluster."""
        cluster = make_cluster(client, kvic_headers)
        add_member(client, kvic_headers, cluster["id"], beekeeper_record["id"])

        data = client.get(f"{API}/clusters/{cluster['id']}/summary", headers=kvic_headers).json()["data"]
        assert data["beekeepers"]["total"] == 1
        assert data["beekeepers"]["verified"] == 0
        assert data["beekeepers"]["pending"] == 1

        client.patch(
            f"{API}/beekeepers/{beekeeper_record['id']}/verification",
            headers=kvic_headers,
            json={"status": VerificationStatus.VERIFIED.value, "remarks": "Apiary inspected"},
        )
        after = client.get(f"{API}/clusters/{cluster['id']}/summary", headers=kvic_headers).json()["data"]
        assert after["beekeepers"]["verified"] == 1
        assert after["beekeepers"]["pending"] == 0


# --------------------------------------------------------------------------- #
# Regression guard: the Phase 2/3 modules must keep working unchanged
# --------------------------------------------------------------------------- #
class TestNothingElseMoved:
    def test_cluster_registry_still_works(self, client: TestClient, kvic_headers):
        cluster = make_cluster(client, kvic_headers)
        listed = client.get(f"{API}/clusters", headers=kvic_headers).json()["data"]
        assert cluster["cluster_code"] in [row["cluster_code"] for row in listed]

        detail = client.get(f"{API}/clusters/{cluster['id']}", headers=kvic_headers)
        assert detail.status_code == 200
        assert detail.json()["data"]["member_count"] == 0

    def test_hive_crud_still_works_without_a_cluster(self, client: TestClient, auth_headers):
        hive = make_hive(client, auth_headers)
        updated = client.put(
            f"{API}/hives/{hive['id']}", headers=auth_headers, json={"notes": "New roof"}
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["notes"] == "New roof"

        assert client.delete(f"{API}/hives/{hive['id']}", headers=auth_headers).status_code == 200

    def test_platform_summaries_still_answer(self, client: TestClient, kvic_headers):
        for path in ("/hives/summary", "/iot/devices/summary", "/ai/summary", "/beekeepers/summary"):
            response = client.get(f"{API}{path}", headers=kvic_headers)
            assert response.status_code == 200, path
