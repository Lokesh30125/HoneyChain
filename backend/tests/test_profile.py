"""Profile endpoints — ``GET/PUT/PATCH /api/v1/profile``.

Covers the two things that matter most here: a user always sees and edits only
their own profile, and every field except nothing-at-all is optional.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

API = "/api/v1"


class TestReadProfile:
    def test_returns_account_profile_and_beekeeper_block(self, client: TestClient, auth_headers, user_payload):
        response = client.get(f"{API}/profile", headers=auth_headers)
        assert response.status_code == 200, response.text
        data = response.json()["data"]

        assert data["account"]["email"] == user_payload["user"]["email"]
        assert data["account"]["role"] == "BEEKEEPER"
        assert data["account"]["role_label"] == "Beekeeper"
        # A brand new account has no profile row yet; the payload still renders.
        assert data["profile"]["user_id"] == user_payload["user"]["id"]
        assert data["beekeeper"]["beekeeper_code"] == user_payload["beekeeper"]["beekeeper_code"]

    def test_consumer_has_no_beekeeper_block(self, client: TestClient, consumer_headers):
        response = client.get(f"{API}/profile", headers=consumer_headers)
        assert response.status_code == 200
        assert response.json()["data"]["beekeeper"] is None

    def test_requires_authentication(self, client: TestClient):
        assert client.get(f"{API}/profile").status_code == 401

    def test_never_returns_credentials(self, client: TestClient, auth_headers):
        body = client.get(f"{API}/profile", headers=auth_headers).text
        assert "password" not in body
        assert "refresh" not in body
        assert "hash" not in body


class TestUpdateProfile:
    def test_patch_applies_only_sent_fields(self, client: TestClient, auth_headers):
        first = client.patch(
            f"{API}/profile",
            headers=auth_headers,
            json={"village": "Tenali", "district": "Guntur", "state": "Andhra Pradesh"},
        )
        assert first.status_code == 200, first.text
        assert first.json()["data"]["profile"]["village"] == "Tenali"

        second = client.patch(f"{API}/profile", headers=auth_headers, json={"pincode": "522201"})
        profile = second.json()["data"]["profile"]
        assert profile["pincode"] == "522201"
        # The earlier values survive a partial update.
        assert profile["village"] == "Tenali"

    def test_put_clears_omitted_fields(self, client: TestClient, auth_headers):
        client.patch(f"{API}/profile", headers=auth_headers, json={"village": "Tenali"})
        response = client.put(
            f"{API}/profile", headers=auth_headers, json={"district": "Guntur"}
        )
        assert response.status_code == 200, response.text
        profile = response.json()["data"]["profile"]
        assert profile["district"] == "Guntur"
        assert profile["village"] is None

    def test_optional_fields_stay_optional(self, client: TestClient, auth_headers):
        # An empty body is valid: nothing is required.
        assert client.put(f"{API}/profile", headers=auth_headers, json={}).status_code == 200

    def test_date_of_birth_validation(self, client: TestClient, auth_headers):
        future = (date.today() + timedelta(days=1)).isoformat()
        response = client.patch(f"{API}/profile", headers=auth_headers, json={"date_of_birth": future})
        assert response.status_code == 422

        too_old = (date.today() - timedelta(days=365 * 130)).isoformat()
        assert (
            client.patch(f"{API}/profile", headers=auth_headers, json={"date_of_birth": too_old}).status_code
            == 422
        )

    def test_pincode_validation(self, client: TestClient, auth_headers):
        for bad in ("12345", "012345", "ABCDEF", "1234567"):
            response = client.patch(f"{API}/profile", headers=auth_headers, json={"pincode": bad})
            assert response.status_code == 422, bad

    def test_gender_validation(self, client: TestClient, auth_headers):
        ok = client.patch(f"{API}/profile", headers=auth_headers, json={"gender": "female"})
        assert ok.status_code == 200
        bad = client.patch(f"{API}/profile", headers=auth_headers, json={"gender": "unicorn"})
        assert bad.status_code == 422

    def test_privileged_fields_are_rejected(self, client: TestClient, auth_headers, user_payload):
        """Role, status and email are administrator-controlled, not profile fields."""
        for payload in (
            {"role": "ADMIN"},
            {"is_active": False},
            {"email": "attacker@honeychain.example.com"},
        ):
            response = client.patch(f"{API}/profile", headers=auth_headers, json=payload)
            assert response.status_code == 422, payload

        # And the account is untouched.
        me = client.get(f"{API}/auth/me", headers=auth_headers).json()["data"]
        assert me["role"] == "BEEKEEPER"
        assert me["email"] == user_payload["user"]["email"]

    def test_location_is_mirrored_onto_the_account(self, client: TestClient, auth_headers):
        """District/state filters and dashboards read the user row, so it must agree."""
        client.patch(
            f"{API}/profile", headers=auth_headers, json={"district": "Krishna", "state": "Andhra Pradesh"}
        )
        me = client.get(f"{API}/auth/me", headers=auth_headers).json()["data"]
        assert me["district"] == "Krishna"

    def test_requires_authentication(self, client: TestClient):
        assert client.patch(f"{API}/profile", json={"village": "X"}).status_code == 401


class TestProfileIsolation:
    def test_one_users_edit_never_touches_another(
        self, client: TestClient, auth_headers, register_user
    ):
        other = register_user(name="Other Beekeeper", role="BEEKEEPER")
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}

        client.patch(f"{API}/profile", headers=auth_headers, json={"village": "Tenali"})
        client.patch(f"{API}/profile", headers=other_headers, json={"village": "Machilipatnam"})

        mine = client.get(f"{API}/profile", headers=auth_headers).json()["data"]
        theirs = client.get(f"{API}/profile", headers=other_headers).json()["data"]
        assert mine["profile"]["village"] == "Tenali"
        assert theirs["profile"]["village"] == "Machilipatnam"

    def test_there_is_no_route_to_another_users_profile(
        self, client: TestClient, auth_headers, register_user, user_payload
    ):
        """The absence of ``/profile/{id}`` is a design decision, not an oversight."""
        target = user_payload["user"]["id"]

        # A path parameter cannot be used to reach someone else's profile…
        assert client.get(f"{API}/profile/{target}", headers=auth_headers).status_code == 404

        # …and an extra identifier in the query string is ignored: the response
        # is still the caller's own profile.
        other = register_user(name="Someone Else", role="BEEKEEPER")
        smuggled = client.get(
            f"{API}/profile", headers=auth_headers, params={"user_id": other["user"]["id"]}
        )
        assert smuggled.status_code == 200
        assert smuggled.json()["data"]["account"]["id"] == user_payload["user"]["id"]
