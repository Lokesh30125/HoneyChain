"""Administrator role management: provisioning operational accounts and changing roles.

What this module is here to prove
---------------------------------
The platform has ten roles and one authentication system. An administrator
creates an account for any of them from **Administration → Users**, the account
signs in through the same ``/auth/login`` every other account uses, and the role
that was stored decides what the account can reach — because the permission
table is consulted on every request against the *stored* role, not against
anything the client sends.

The checks below therefore fall into five groups:

1. **Provisioning works for every role** — all ten can be created by an
   administrator, and each one can then actually sign in and reach the module its
   role owns.
2. **The role is real state**, not a display value: it is in the database, it
   comes back from ``/auth/me``, and it decides authorisation on the API.
3. **Public registration stays closed** to the eight operational roles, no matter
   what the request body claims.
4. **Role changes work and are guarded** — audited with both roles, impossible on
   your own account, impossible for the last administrator to be moved off ADMIN,
   and impossible for anybody without the capability.
5. **Nobody changes their own role**, through any door: the admin endpoint
   refuses the caller's own account, and the self-service profile endpoint
   rejects the field outright.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.enums import ROLE_HOME_ROUTES, AuditAction, UserRole
from app.models.user import User
from app.repositories.user_repository import UserRepository
from tests.conftest import API_PREFIX

#: Every role the administrator may create an account for, in the order the
#: administration screen lists them.
MANAGED_ROLES = [
    UserRole.ADMIN,
    UserRole.BEEKEEPER,
    UserRole.CONSUMER,
    UserRole.KVIC_OFFICER,
    UserRole.COLLECTION_CENTER,
    UserRole.PROCESSOR,
    UserRole.LAB_TECHNICIAN,
    UserRole.PACKAGING_UNIT,
    UserRole.DISTRIBUTOR,
    UserRole.RETAILER,
]

#: The only two roles the public registration form may offer.
SELF_REGISTRABLE = {UserRole.BEEKEEPER, UserRole.CONSUMER}

PASSWORD = "Operational123"


def create_account(
    client: TestClient,
    admin_headers: dict,
    *,
    role: UserRole,
    email: str | None = None,
    is_active: bool = True,
    password: str = PASSWORD,
    **extra,
) -> dict:
    """Provision an account the way the administration screen does."""
    payload = {
        "name": f"{role.label} Test Account",
        "email": email or f"{role.value.lower()}-{uuid.uuid4().hex[:8]}@honeychain.example.com",
        "password": password,
        "role": role.value,
        "is_active": is_active,
        **extra,
    }
    response = client.post(f"{API_PREFIX}/admin/users", json=payload, headers=admin_headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def sign_in(client: TestClient, email: str, password: str = PASSWORD) -> dict:
    response = client.post(
        f"{API_PREFIX}/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def headers_for(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# 1. Every role can be created by an administrator
# --------------------------------------------------------------------------- #
class TestProvisioningEveryRole:
    @pytest.mark.parametrize("role", MANAGED_ROLES, ids=[role.value for role in MANAGED_ROLES])
    def test_admin_can_create_an_account_for_the_role(
        self, client: TestClient, admin_headers: dict, db: Session, role: UserRole
    ) -> None:
        created = create_account(client, admin_headers, role=role)

        assert created["user"]["role"] == role.value
        assert created["user"]["role_label"] == role.label
        assert created["user"]["is_active"] is True

        # The role is stored, not echoed: read it back from the database.
        stored = db.get(User, uuid.UUID(created["user"]["id"]))
        assert stored is not None and str(stored.role) == role.value

        # And the account works through the one authentication system.
        session = sign_in(client, created["user"]["email"])
        assert session["user"]["role"] == role.value
        assert session["home_route"] == ROLE_HOME_ROUTES[role]

    def test_a_created_beekeeper_gets_its_apiary_record(
        self, client: TestClient, admin_headers: dict
    ) -> None:
        """An account that says BEEKEEPER but has no apiary cannot do its job."""
        created = create_account(
            client,
            admin_headers,
            role=UserRole.BEEKEEPER,
            beekeeper={"village": "Tenali", "district": "Guntur", "state": "Andhra Pradesh"},
        )

        assert created["beekeeper_created"] is True

        session = sign_in(client, created["user"]["email"])
        record = client.get(f"{API_PREFIX}/beekeepers/me", headers=headers_for(session["access_token"]))

        assert record.status_code == 200, record.text
        assert record.json()["data"]["beekeeper_code"].startswith("BKR-")
        # Created by an administrator, but still PENDING: provisioning is not verification.
        assert record.json()["data"]["verification_status"] == "PENDING"

    def test_an_operational_account_can_be_created_inactive(
        self, client: TestClient, admin_headers: dict
    ) -> None:
        """'Starts next week' is a real case: create the account, enable it later."""
        created = create_account(
            client, admin_headers, role=UserRole.LAB_TECHNICIAN, is_active=False
        )

        assert created["user"]["is_active"] is False
        assert "(inactive)" in created["message"]

        denied = client.post(
            f"{API_PREFIX}/auth/login",
            json={"email": created["user"]["email"], "password": PASSWORD},
        )
        assert denied.status_code in (401, 403), denied.text

        # The administrator can activate it from the same directory.
        activated = client.patch(
            f"{API_PREFIX}/admin/users/{created['user']['id']}/status",
            json={"is_active": True, "reason": "Technician starts this week"},
            headers=admin_headers,
        )
        assert activated.status_code == 200, activated.text
        assert activated.json()["data"]["user"]["is_active"] is True

        session = sign_in(client, created["user"]["email"])
        assert session["user"]["role"] == UserRole.LAB_TECHNICIAN.value

    def test_creating_an_account_is_audited(
        self, client: TestClient, admin_headers: dict
    ) -> None:
        created = create_account(client, admin_headers, role=UserRole.PROCESSOR)

        detail = client.get(
            f"{API_PREFIX}/admin/users/{created['user']['id']}", headers=admin_headers
        ).json()["data"]
        actions = [entry["action"] for entry in detail["recent_activity"]]

        assert AuditAction.USER_PROVISIONED.value in actions
        entry = next(e for e in detail["recent_activity"] if e["action"] == "USER_PROVISIONED")
        assert entry["metadata"]["role"] == UserRole.PROCESSOR.value

    def test_duplicate_email_is_a_conflict(
        self, client: TestClient, admin_headers: dict, register_user
    ) -> None:
        existing = register_user()
        response = client.post(
            f"{API_PREFIX}/admin/users",
            json={
                "name": "Copy Cat",
                "email": existing["user"]["email"],
                "password": PASSWORD,
                "role": UserRole.RETAILER.value,
            },
            headers=admin_headers,
        )

        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "DUPLICATE_RESOURCE"

    def test_a_weak_password_is_rejected_by_the_same_policy(
        self, client: TestClient, admin_headers: dict
    ) -> None:
        response = client.post(
            f"{API_PREFIX}/admin/users",
            json={
                "name": "Weak Pass",
                "email": f"weak-{uuid.uuid4().hex[:8]}@honeychain.example.com",
                "password": "allletters",
                "role": UserRole.LAB_TECHNICIAN.value,
            },
            headers=admin_headers,
        )

        assert response.status_code == 422, response.text

    def test_an_unknown_role_cannot_be_created(
        self, client: TestClient, admin_headers: dict
    ) -> None:
        response = client.post(
            f"{API_PREFIX}/admin/users",
            json={
                "name": "Invented Role",
                "email": f"invented-{uuid.uuid4().hex[:8]}@honeychain.example.com",
                "password": PASSWORD,
                "role": "SUPREME_LEADER",
            },
            headers=admin_headers,
        )

        assert response.status_code == 422, response.text


# --------------------------------------------------------------------------- #
# 2. The assigned role is what authorises the account
# --------------------------------------------------------------------------- #
class TestAssignedRoleDrivesAuthorisation:
    """A created account reaches its own module — and nothing else."""

    @pytest.mark.parametrize(
        ("role", "path"),
        [
            (UserRole.LAB_TECHNICIAN, "/lab-tests"),
            (UserRole.PROCESSOR, "/processing"),
            (UserRole.KVIC_OFFICER, "/clusters"),
        ],
    )
    def test_the_account_reaches_the_module_its_role_owns(
        self, client: TestClient, admin_headers: dict, role: UserRole, path: str
    ) -> None:
        created = create_account(client, admin_headers, role=role)
        session = sign_in(client, created["user"]["email"])

        allowed = client.get(f"{API_PREFIX}{path}", headers=headers_for(session["access_token"]))
        admin_area = client.get(
            f"{API_PREFIX}/admin/summary", headers=headers_for(session["access_token"])
        )

        assert allowed.status_code == 200, f"{role} could not read {path}: {allowed.text}"
        # Only an administrator reaches the administration namespace.
        assert admin_area.status_code == 403, admin_area.text

    def test_a_created_technician_cannot_process_honey(
        self, client: TestClient, admin_headers: dict
    ) -> None:
        """Holding one operational role does not carry another role's powers."""
        created = create_account(client, admin_headers, role=UserRole.LAB_TECHNICIAN)
        session = sign_in(client, created["user"]["email"])

        response = client.post(
            f"{API_PREFIX}/processing-units",
            json={"name": "Not mine to create", "location": "Guntur"},
            headers=headers_for(session["access_token"]),
        )

        assert response.status_code == 403, response.text

    def test_the_role_is_read_from_the_database_on_every_request(
        self, client: TestClient, admin_headers: dict, db: Session
    ) -> None:
        """A token minted under one role cannot keep the old role's powers.

        The access token carries the role as a claim, but authorisation never
        trusts it: the user is loaded from the database per request, so a role
        changed (or an account disabled) after the token was issued takes effect
        immediately. This is what makes role management a security control rather
        than a display setting.
        """
        created = create_account(client, admin_headers, role=UserRole.RETAILER)
        session = sign_in(client, created["user"]["email"])
        token = headers_for(session["access_token"])

        # While RETAILER, the processing queue is closed to them.
        assert client.get(f"{API_PREFIX}/processing", headers=token).status_code == 403

        # Promote the account straight in the database — no new token issued.
        user = db.get(User, uuid.UUID(created["user"]["id"]))
        assert user is not None
        user.role = UserRole.PROCESSOR
        db.commit()

        # The very same token now reads what PROCESSOR may read.
        promoted = client.get(f"{API_PREFIX}/processing", headers=token)
        assert promoted.status_code == 200, promoted.text


# --------------------------------------------------------------------------- #
# 3. Public registration remains limited
# --------------------------------------------------------------------------- #
class TestPublicRegistrationStaysClosed:
    @pytest.mark.parametrize(
        "role", [role for role in MANAGED_ROLES if role not in SELF_REGISTRABLE],
        ids=lambda role: role.value,
    )
    def test_operational_roles_cannot_register_themselves(
        self, client: TestClient, role: UserRole
    ) -> None:
        response = client.post(
            f"{API_PREFIX}/auth/register",
            json={
                "name": "Self Appointed",
                "email": f"self.{role.value.lower()}.{uuid.uuid4().hex[:8]}@honeychain.example.com",
                "password": PASSWORD,
                "role": role.value,
                "accepted_terms": True,
            },
        )

        assert response.status_code == 422, f"{role} self-registered: {response.text}"

    @pytest.mark.parametrize("role", sorted(SELF_REGISTRABLE, key=lambda r: r.value))
    def test_the_two_public_roles_still_work(self, client: TestClient, role: UserRole) -> None:
        response = client.post(
            f"{API_PREFIX}/auth/register",
            json={
                "name": "Public Sign Up",
                "email": f"public.{role.value.lower()}.{uuid.uuid4().hex[:8]}@honeychain.example.com",
                "password": PASSWORD,
                "role": role.value,
                "accepted_terms": True,
            },
        )

        assert response.status_code == 201, response.text
        assert response.json()["data"]["user"]["role"] == role.value

    def test_the_role_catalogue_reports_what_is_public(
        self, client: TestClient
    ) -> None:
        roles = {row["value"]: row for row in client.get(f"{API_PREFIX}/roles").json()["data"]["roles"]}

        assert len(roles) == 10
        assert {value for value, row in roles.items() if row["self_registrable"]} == {
            role.value for role in SELF_REGISTRABLE
        }
        # Every role still lands somewhere real after sign-in.
        assert all(row["home_route"] for row in roles.values())


# --------------------------------------------------------------------------- #
# 4. Changing a role
# --------------------------------------------------------------------------- #
class TestRoleChange:
    def test_an_admin_moves_an_account_to_another_role(
        self, client: TestClient, admin_headers: dict, db: Session
    ) -> None:
        created = create_account(client, admin_headers, role=UserRole.CONSUMER)
        user_id = created["user"]["id"]

        response = client.patch(
            f"{API_PREFIX}/admin/users/{user_id}/role",
            json={"role": UserRole.COLLECTION_CENTER.value, "reason": "Joined the Guntur centre"},
            headers=admin_headers,
        )

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["previous_role"] == UserRole.CONSUMER.value
        assert data["user"]["role"] == UserRole.COLLECTION_CENTER.value
        assert "Collection centre" in data["message"]

        stored = db.get(User, uuid.UUID(user_id))
        assert stored is not None and str(stored.role) == UserRole.COLLECTION_CENTER.value

    def test_the_change_is_audited_with_both_roles(
        self, client: TestClient, admin_headers: dict
    ) -> None:
        created = create_account(client, admin_headers, role=UserRole.RETAILER)
        user_id = created["user"]["id"]
        client.patch(
            f"{API_PREFIX}/admin/users/{user_id}/role",
            json={"role": UserRole.DISTRIBUTOR.value, "reason": "Now runs distribution"},
            headers=admin_headers,
        )

        detail = client.get(f"{API_PREFIX}/admin/users/{user_id}", headers=admin_headers).json()["data"]
        entry = next(e for e in detail["recent_activity"] if e["action"] == "USER_ROLE_CHANGED")

        assert entry["metadata"]["previous_role"] == UserRole.RETAILER.value
        assert entry["metadata"]["new_role"] == UserRole.DISTRIBUTOR.value
        assert entry["metadata"]["reason"] == "Now runs distribution"

    def test_the_new_role_takes_effect_at_the_next_sign_in(
        self, client: TestClient, admin_headers: dict
    ) -> None:
        created = create_account(client, admin_headers, role=UserRole.CONSUMER)
        client.patch(
            f"{API_PREFIX}/admin/users/{created['user']['id']}/role",
            json={"role": UserRole.LAB_TECHNICIAN.value},
            headers=admin_headers,
        )

        session = sign_in(client, created["user"]["email"])

        assert session["user"]["role"] == UserRole.LAB_TECHNICIAN.value
        assert session["home_route"] == "/laboratory"
        allowed = client.get(
            f"{API_PREFIX}/lab-tests", headers=headers_for(session["access_token"])
        )
        assert allowed.status_code == 200, allowed.text

    def test_existing_sessions_are_revoked_on_a_role_change(
        self, client: TestClient, admin_headers: dict
    ) -> None:
        """Permissions changed, so the session opened under the old role ends."""
        created = create_account(client, admin_headers, role=UserRole.CONSUMER)
        session = sign_in(client, created["user"]["email"])
        refresh = session.get("refresh_token")

        response = client.patch(
            f"{API_PREFIX}/admin/users/{created['user']['id']}/role",
            json={"role": UserRole.BEEKEEPER.value},
            headers=admin_headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["data"]["sessions_revoked"] >= (1 if refresh else 0)

    def test_promoting_a_second_administrator_is_allowed(
        self, client: TestClient, admin_headers: dict
    ) -> None:
        """A platform with one administrator must be able to name a successor."""
        created = create_account(client, admin_headers, role=UserRole.KVIC_OFFICER)

        response = client.patch(
            f"{API_PREFIX}/admin/users/{created['user']['id']}/role",
            json={"role": UserRole.ADMIN.value, "reason": "Second platform administrator"},
            headers=admin_headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["data"]["user"]["role"] == UserRole.ADMIN.value

        session = sign_in(client, created["user"]["email"])
        summary = client.get(
            f"{API_PREFIX}/admin/summary", headers=headers_for(session["access_token"])
        )
        assert summary.status_code == 200, summary.text

    def test_promoting_to_beekeeper_creates_the_missing_apiary_record(
        self, client: TestClient, admin_headers: dict
    ) -> None:
        created = create_account(client, admin_headers, role=UserRole.RETAILER)
        client.patch(
            f"{API_PREFIX}/admin/users/{created['user']['id']}/role",
            json={"role": UserRole.BEEKEEPER.value},
            headers=admin_headers,
        )

        session = sign_in(client, created["user"]["email"])
        record = client.get(
            f"{API_PREFIX}/beekeepers/me", headers=headers_for(session["access_token"])
        )

        assert record.status_code == 200, record.text
        assert record.json()["data"]["beekeeper_code"].startswith("BKR-")

    def test_the_same_role_is_a_no_op(self, client: TestClient, admin_headers: dict) -> None:
        created = create_account(client, admin_headers, role=UserRole.PACKAGING_UNIT)

        response = client.patch(
            f"{API_PREFIX}/admin/users/{created['user']['id']}/role",
            json={"role": UserRole.PACKAGING_UNIT.value},
            headers=admin_headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["data"]["sessions_revoked"] == 0
        assert "already held" in response.json()["data"]["message"]

    def test_an_unknown_role_is_rejected(self, client: TestClient, admin_headers: dict) -> None:
        created = create_account(client, admin_headers, role=UserRole.PACKAGING_UNIT)

        response = client.patch(
            f"{API_PREFIX}/admin/users/{created['user']['id']}/role",
            json={"role": "HONEY_TYRANT"},
            headers=admin_headers,
        )

        assert response.status_code == 422, response.text

    def test_an_unknown_account_is_a_not_found(
        self, client: TestClient, admin_headers: dict
    ) -> None:
        response = client.patch(
            f"{API_PREFIX}/admin/users/{uuid.uuid4()}/role",
            json={"role": UserRole.RETAILER.value},
            headers=admin_headers,
        )

        assert response.status_code == 404, response.text

    def test_the_last_administrator_cannot_be_moved_off_admin(
        self, client: TestClient, admin_headers: dict, admin_payload: dict
    ) -> None:
        """The platform must not be able to demote itself out of existence."""
        response = client.patch(
            f"{API_PREFIX}/admin/users/{admin_payload['id']}/role",
            json={"role": UserRole.BEEKEEPER.value},
            headers=admin_headers,
        )

        # Refused either as "not your own role" (the actor is the only admin) or
        # as "the last administrator" — never allowed.
        assert response.status_code == 422, response.text
        detail = response.json()["error"]
        assert detail["code"] == "VALIDATION_ERROR"


# --------------------------------------------------------------------------- #
# 5. Nobody changes their own role
# --------------------------------------------------------------------------- #
class TestNoSelfServiceRoleChange:
    def test_the_self_service_profile_endpoint_rejects_the_field(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """PATCH /users/me forbids unknown fields, and `role` is one of them."""
        response = client.patch(
            f"{API_PREFIX}/users/me", json={"role": UserRole.ADMIN.value}, headers=auth_headers
        )

        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_the_full_profile_endpoint_rejects_the_field(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        profile = client.get(f"{API_PREFIX}/profile", headers=auth_headers)
        assert profile.status_code == 200, profile.text
        current = profile.json()["data"].get("personal", {})

        response = client.put(
            f"{API_PREFIX}/profile",
            json={
                "full_name": current.get("full_name") or "Test Beekeeper",
                "role": UserRole.ADMIN.value,
            },
            headers=auth_headers,
        )

        assert response.status_code == 422, response.text

    def test_a_non_admin_cannot_reach_the_role_endpoint(
        self, client: TestClient, auth_headers: dict, user_payload: dict
    ) -> None:
        """Even against their *own* id: the endpoint is administration-only."""
        response = client.patch(
            f"{API_PREFIX}/admin/users/{user_payload['user']['id']}/role",
            json={"role": UserRole.ADMIN.value},
            headers=auth_headers,
        )

        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"

    def test_a_kvic_officer_cannot_create_accounts_or_assign_roles(
        self, client: TestClient, kvic_headers: dict, consumer_payload: dict
    ) -> None:
        """An officer manages beekeepers, not platform roles."""
        created = client.post(
            f"{API_PREFIX}/admin/users",
            json={
                "name": "Officer Made",
                "email": f"officer.made.{uuid.uuid4().hex[:8]}@honeychain.example.com",
                "password": PASSWORD,
                "role": UserRole.PROCESSOR.value,
            },
            headers=kvic_headers,
        )
        changed = client.patch(
            f"{API_PREFIX}/admin/users/{consumer_payload['user']['id']}/role",
            json={"role": UserRole.ADMIN.value},
            headers=kvic_headers,
        )

        assert created.status_code == 403, created.text
        assert changed.status_code == 403, changed.text

    def test_an_operational_account_cannot_grant_itself_a_role(
        self, client: TestClient, admin_headers: dict
    ) -> None:
        """The realistic escalation attempt: a technician trying to become ADMIN."""
        created = create_account(client, admin_headers, role=UserRole.LAB_TECHNICIAN)
        session = sign_in(client, created["user"]["email"])
        token = headers_for(session["access_token"])

        own = client.patch(
            f"{API_PREFIX}/admin/users/{created['user']['id']}/role",
            json={"role": UserRole.ADMIN.value},
            headers=token,
        )
        profile = client.patch(
            f"{API_PREFIX}/users/me", json={"role": UserRole.ADMIN.value}, headers=token
        )

        assert own.status_code == 403, own.text
        assert profile.status_code == 422, profile.text

    def test_an_administrator_cannot_change_their_own_role(
        self, client: TestClient, admin_headers: dict, admin_payload: dict, db: Session
    ) -> None:
        """Self-service role change is refused even for an administrator.

        Otherwise the single capability that guards role assignment would also be
        the capability to hand yourself any other role.
        """
        # Give the platform a second administrator so the "last administrator"
        # guard is not what refuses this — the self-change guard must be.
        UserRepository(db).create_user(
            name="Second Administrator",
            email=f"second.admin.{uuid.uuid4().hex[:8]}@honeychain.example.com",
            password_hash=hash_password("SecondAdmin123"),
            role=UserRole.ADMIN,
        )
        db.commit()

        response = client.patch(
            f"{API_PREFIX}/admin/users/{admin_payload['id']}/role",
            json={"role": UserRole.BEEKEEPER.value},
            headers=admin_headers,
        )

        assert response.status_code == 422, response.text
        assert "your own role" in response.json()["error"]["message"].lower()

    def test_a_user_cannot_patch_another_users_role_directly(
        self, client: TestClient, auth_headers: dict, consumer_payload: dict
    ) -> None:
        """The URL exists; the permission is what stops it."""
        response = client.patch(
            f"{API_PREFIX}/admin/users/{consumer_payload['user']['id']}/role",
            json={"role": UserRole.ADMIN.value},
            headers=auth_headers,
        )

        assert response.status_code == 403, response.text

        # And nothing changed.
        still_consumer = client.post(
            f"{API_PREFIX}/auth/login",
            json={"email": consumer_payload["user"]["email"], "password": consumer_payload["_password"]},
        )
        assert still_consumer.json()["data"]["user"]["role"] == UserRole.CONSUMER.value


# --------------------------------------------------------------------------- #
# The directory itself still works for every role
# --------------------------------------------------------------------------- #
class TestDirectoryCoversEveryRole:
    def test_the_directory_lists_an_account_from_every_role(
        self, client: TestClient, admin_headers: dict
    ) -> None:
        for role in MANAGED_ROLES:
            create_account(client, admin_headers, role=role)

        body = client.get(
            f"{API_PREFIX}/admin/users?page_size=100", headers=admin_headers
        ).json()

        # Paginated envelope: `data` is the page of accounts, `meta` the paging.
        assert body["meta"]["total_items"] >= len(MANAGED_ROLES)
        present = {row["role"] for row in body["data"]}
        assert {role.value for role in MANAGED_ROLES} <= present

    def test_each_role_can_be_filtered_for(self, client: TestClient, admin_headers: dict) -> None:
        create_account(client, admin_headers, role=UserRole.PACKAGING_UNIT)

        response = client.get(
            f"{API_PREFIX}/admin/users?role=PACKAGING_UNIT", headers=admin_headers
        )

        assert response.status_code == 200, response.text
        rows = response.json()["data"]
        assert rows and all(row["role"] == "PACKAGING_UNIT" for row in rows)
        assert rows[0]["role_label"] == "Packaging unit"

    def test_the_platform_summary_counts_every_role(self, client: TestClient, admin_headers: dict) -> None:
        create_account(client, admin_headers, role=UserRole.DISTRIBUTOR)

        summary = client.get(f"{API_PREFIX}/admin/summary", headers=admin_headers).json()["data"]

        assert set(summary["users"]["by_role"]) == set(UserRole.values())
        assert summary["users"]["by_role"]["DISTRIBUTOR"] >= 1


def test_role_change_by_an_administrator_is_recorded_in_the_platform_audit_log(
    client: TestClient, admin_headers: dict
) -> None:
    """The audit trail is the review surface an administrator actually reads."""
    created = create_account(client, admin_headers, role=UserRole.COLLECTION_CENTER)
    client.patch(
        f"{API_PREFIX}/admin/users/{created['user']['id']}/role",
        json={"role": UserRole.RETAILER.value, "reason": "Moved to retail"},
        headers=admin_headers,
    )

    logs = client.get(
        f"{API_PREFIX}/admin/audit-logs?action=USER_ROLE_CHANGED", headers=admin_headers
    ).json()["data"]

    assert logs, "no USER_ROLE_CHANGED entry was written"
    entry = logs[0]
    assert entry["entity_id"] == created["user"]["id"]
    assert entry["metadata"]["new_role"] == "RETAILER"


def test_the_role_vocabulary_matches_the_documented_ten(
    client: TestClient, db: Session
) -> None:
    """A guard against a role existing in the database but nowhere in the UI."""
    assert {role.value for role in UserRole} == {role.value for role in MANAGED_ROLES}
    # One declared order drives the admin screen and the public catalogue.
    assert list(UserRole.administration_order()) == MANAGED_ROLES
    assert [role.value for role in UserRole.assignable_by_admin()] == [
        role.value for role in MANAGED_ROLES
    ]

    published = client.get(f"{API_PREFIX}/roles").json()["data"]["roles"]
    assert [role["value"] for role in published] == [role.value for role in MANAGED_ROLES]
    assert [role["label"] for role in published] == [
        "Administrator",
        "Beekeeper",
        "Consumer",
        "KVIC officer",
        "Collection centre",
        "Processor",
        "Lab technician",
        "Packaging unit",
        "Distributor",
        "Retailer",
    ]

    rows = db.execute(select(User)).scalars().all()
    assert all(str(row.role) in UserRole.values() for row in rows)
