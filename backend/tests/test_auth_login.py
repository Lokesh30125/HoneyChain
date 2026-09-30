"""Login, current-user, refresh rotation and logout behaviour."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories.user_repository import UserRepository
from tests.conftest import API_PREFIX


def _login(client: TestClient, email: str, password: str):
    return client.post(f"{API_PREFIX}/auth/login", json={"email": email, "password": password})


class TestLogin:
    def test_valid_credentials_return_token_and_profile(
        self, client: TestClient, user_payload: dict
    ) -> None:
        response = _login(
            client, user_payload["user"]["email"], user_payload["_password"]
        )

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["user"]["id"] == user_payload["user"]["id"]
        assert data["access_token"]
        assert data["token"]["expires_in"] > 0

    def test_login_is_case_insensitive_for_email(
        self, client: TestClient, user_payload: dict
    ) -> None:
        uppercase = user_payload["user"]["email"].upper()

        response = _login(client, uppercase, user_payload["_password"])

        assert response.status_code == 200

    def test_wrong_password_returns_401(self, client: TestClient, user_payload: dict) -> None:
        response = _login(client, user_payload["user"]["email"], "WrongPass123")

        assert response.status_code == 401
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "INVALID_CREDENTIALS"
        assert response.headers.get("WWW-Authenticate") == "Bearer"

    def test_unknown_email_returns_same_error_as_wrong_password(
        self, client: TestClient, user_payload: dict
    ) -> None:
        """Responses must not reveal whether an account exists."""
        unknown = _login(client, "nobody@honey.example.com", "Whatever123")
        wrong = _login(client, user_payload["user"]["email"], "WrongPass123")

        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json()["error"]["code"] == wrong.json()["error"]["code"]
        assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]

    def test_inactive_account_cannot_log_in(
        self, client: TestClient, user_payload: dict, deactivate_user
    ) -> None:
        deactivate_user(user_payload["user"]["id"])

        response = _login(client, user_payload["user"]["email"], user_payload["_password"])

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "ACCOUNT_INACTIVE"

    def test_successful_login_records_last_login(
        self, client: TestClient, user_payload: dict, db: Session
    ) -> None:
        _login(client, user_payload["user"]["email"], user_payload["_password"])

        db.expire_all()
        user = UserRepository(db).get_by_email(user_payload["user"]["email"])
        assert user is not None
        assert user.last_login_at is not None

    def test_validation_error_lists_offending_fields(self, client: TestClient) -> None:
        response = client.post(f"{API_PREFIX}/auth/login", json={"email": "bad"})

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert {detail["field"] for detail in error["details"]} >= {"email", "password"}


class TestCurrentUser:
    def test_returns_profile_for_valid_token(
        self, client: TestClient, user_payload: dict, auth_headers: dict
    ) -> None:
        response = client.get(f"{API_PREFIX}/auth/me", headers=auth_headers)

        assert response.status_code == 200
        user = response.json()["data"]
        assert user["id"] == user_payload["user"]["id"]
        assert user["email"] == user_payload["user"]["email"]
        assert "password_hash" not in user

    def test_profile_endpoint_matches_auth_me(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        response = client.get(f"{API_PREFIX}/users/me", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["data"]["role"]

    def test_profile_can_be_updated(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        response = client.patch(
            f"{API_PREFIX}/users/me",
            headers=auth_headers,
            json={"district": "Krishna", "organization": "Coastal Apiaries"},
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["district"] == "Krishna"
        assert data["organization"] == "Coastal Apiaries"

    def test_role_cannot_be_escalated_via_profile_update(
        self, client: TestClient, auth_headers: dict, user_payload: dict
    ) -> None:
        response = client.patch(
            f"{API_PREFIX}/users/me",
            headers=auth_headers,
            json={"role": "ADMIN"},
        )

        assert response.status_code == 422
        assert user_payload["user"]["role"] == "BEEKEEPER"


class TestProtectedRoutesRejectAnonymous:
    def test_auth_me_requires_a_token(self, client: TestClient) -> None:
        response = client.get(f"{API_PREFIX}/auth/me")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTHENTICATION_ERROR"

    def test_malformed_token_is_rejected(self, client: TestClient) -> None:
        response = client.get(
            f"{API_PREFIX}/auth/me", headers={"Authorization": "Bearer not.a.jwt"}
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "TOKEN_INVALID"

    def test_token_signed_with_another_secret_is_rejected(self, client: TestClient) -> None:
        import jwt

        forged = jwt.encode(
            {
                "sub": "00000000-0000-0000-0000-000000000000",
                "type": "access",
                "jti": "forged",
                "iss": "honeychain-api",
                "role": "ADMIN",
            },
            "attacker-secret",
            algorithm="HS256",
        )

        response = client.get(
            f"{API_PREFIX}/auth/me", headers={"Authorization": f"Bearer {forged}"}
        )

        assert response.status_code == 401

    def test_refresh_token_cannot_be_used_as_access_token(
        self, client: TestClient, user_payload: dict
    ) -> None:
        refresh_token = user_payload["refresh_token"]
        assert refresh_token

        response = client.get(
            f"{API_PREFIX}/auth/me", headers={"Authorization": f"Bearer {refresh_token}"}
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "TOKEN_INVALID"


class TestRefreshRotation:
    def test_refresh_returns_a_new_access_token(self, client: TestClient, user_payload: dict) -> None:
        response = client.post(
            f"{API_PREFIX}/auth/refresh",
            json={"refresh_token": user_payload["refresh_token"]},
        )

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["access_token"]
        assert data["refresh_token"] != user_payload["refresh_token"]

    def test_rotated_refresh_token_works_and_old_one_does_not(
        self, client: TestClient, user_payload: dict
    ) -> None:
        first = client.post(
            f"{API_PREFIX}/auth/refresh",
            json={"refresh_token": user_payload["refresh_token"]},
        ).json()["data"]

        # The new token is valid.
        second = client.post(
            f"{API_PREFIX}/auth/refresh", json={"refresh_token": first["refresh_token"]}
        )
        assert second.status_code == 200

        # Replaying the original (already rotated) token is treated as theft.
        replay = client.post(
            f"{API_PREFIX}/auth/refresh",
            json={"refresh_token": user_payload["refresh_token"]},
        )
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "TOKEN_INVALID"

    def test_reuse_detection_revokes_every_session(
        self, client: TestClient, user_payload: dict
    ) -> None:
        rotated = client.post(
            f"{API_PREFIX}/auth/refresh",
            json={"refresh_token": user_payload["refresh_token"]},
        ).json()["data"]

        client.post(
            f"{API_PREFIX}/auth/refresh",
            json={"refresh_token": user_payload["refresh_token"]},
        )  # triggers reuse detection

        # Even the newest legitimate token is now revoked.
        blocked = client.post(
            f"{API_PREFIX}/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
        )
        assert blocked.status_code == 401

        # The user can still sign in again with their password.
        relogin = _login(client, user_payload["user"]["email"], user_payload["_password"])
        assert relogin.status_code == 200

    def test_refresh_without_token_is_a_validation_error(self, client: TestClient) -> None:
        response = client.post(f"{API_PREFIX}/auth/refresh", json={})

        assert response.status_code == 422

    def test_garbage_refresh_token_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            f"{API_PREFIX}/auth/refresh", json={"refresh_token": "clearly-not-a-token"}
        )

        assert response.status_code == 401


class TestLogout:
    def test_logout_revokes_the_refresh_token(self, client: TestClient, user_payload: dict) -> None:
        response = client.post(
            f"{API_PREFIX}/auth/logout",
            json={"refresh_token": user_payload["refresh_token"]},
        )

        assert response.status_code == 200
        assert response.json()["data"]["revoked_sessions"] == 1

        reuse = client.post(
            f"{API_PREFIX}/auth/refresh",
            json={"refresh_token": user_payload["refresh_token"]},
        )
        assert reuse.status_code == 401

    def test_access_token_still_valid_until_expiry_after_logout(
        self, client: TestClient, user_payload: dict, auth_headers: dict
    ) -> None:
        """Documented trade-off of stateless access tokens.

        Logout revokes the *session* (refresh token) immediately; the short-lived
        access token remains valid until it expires, which is why the access TTL
        is kept small.
        """
        client.post(
            f"{API_PREFIX}/auth/logout",
            json={"refresh_token": user_payload["refresh_token"]},
        )

        response = client.get(f"{API_PREFIX}/auth/me", headers=auth_headers)
        assert response.status_code == 200

    def test_logout_all_devices_revokes_every_session(
        self, client: TestClient, user_payload: dict
    ) -> None:
        # A second device session.
        second_login = _login(
            client, user_payload["user"]["email"], user_payload["_password"]
        ).json()["data"]

        response = client.post(
            f"{API_PREFIX}/auth/logout",
            json={"refresh_token": second_login["refresh_token"], "all_devices": True},
        )

        assert response.status_code == 200
        assert response.json()["data"]["revoked_sessions"] >= 2

        for token in (user_payload["refresh_token"], second_login["refresh_token"]):
            reuse = client.post(f"{API_PREFIX}/auth/refresh", json={"refresh_token": token})
            assert reuse.status_code == 401

    def test_logout_is_idempotent(self, client: TestClient, user_payload: dict) -> None:
        payload = {"refresh_token": user_payload["refresh_token"]}

        first = client.post(f"{API_PREFIX}/auth/logout", json=payload)
        second = client.post(f"{API_PREFIX}/auth/logout", json=payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["data"]["revoked_sessions"] == 0


class TestAuthFlowEndToEnd:
    def test_register_login_me_logout_sequence(self, client: TestClient) -> None:
        """The exact journey a real user takes through the SPA."""
        credentials = {"email": "flow@honeychain.example.com", "password": "FlowPass123"}

        registered = client.post(
            f"{API_PREFIX}/auth/register",
            json={
                "name": "Flow Tester",
                "email": credentials["email"],
                "password": credentials["password"],
                "role": "BEEKEEPER",
                "accepted_terms": True,
            },
        )
        assert registered.status_code == 201

        logged_in = client.post(f"{API_PREFIX}/auth/login", json=credentials)
        assert logged_in.status_code == 200
        session = logged_in.json()["data"]

        me = client.get(
            f"{API_PREFIX}/auth/me",
            headers={"Authorization": f"Bearer {session['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["data"]["email"] == credentials["email"]

        logged_out = client.post(
            f"{API_PREFIX}/auth/logout", json={"refresh_token": session["refresh_token"]}
        )
        assert logged_out.status_code == 200

        assert (
            client.post(
                f"{API_PREFIX}/auth/refresh",
                json={"refresh_token": session["refresh_token"]},
            ).status_code
            == 401
        )
