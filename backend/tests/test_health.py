"""Health, readiness and API-discovery endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import API_PREFIX


class TestLiveness:
    def test_health_returns_expected_contract(self, client: TestClient) -> None:
        response = client.get(f"{API_PREFIX}/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "HoneyChain API"}

    def test_health_assigns_request_id_header(self, client: TestClient) -> None:
        response = client.get(f"{API_PREFIX}/health")

        assert response.headers.get("X-Request-ID")

    def test_root_health_alias(self, client: TestClient) -> None:
        response = client.get("/")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestReadiness:
    def test_health_db_reports_connection_and_tables(self, client: TestClient) -> None:
        response = client.get(f"{API_PREFIX}/health/db")

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True

        database = body["data"]["database"]
        assert database["connected"] is True
        assert body["data"]["status"] == "ok"
        # The authentication tables created by the first migration must exist.
        assert {"users", "refresh_tokens"} <= set(body["data"]["tables"])

    def test_health_detailed_lists_all_components(self, client: TestClient) -> None:
        response = client.get(f"{API_PREFIX}/health/detailed")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert set(body["components"]) == {
            "database",
            "authentication",
            "blockchain",
            "iot",
            "ai",
        }
        # The traceability integration is real now. In this environment it is
        # switched off, and the component says exactly that — a state, not an
        # error. The report is unauthenticated, so it carries counters and never
        # the address of the service.
        blockchain = body["components"]["blockchain"]
        assert blockchain["status"] == "disabled"
        assert blockchain["enabled"] is False
        assert "http://" not in response.text.replace("http://testserver", "")
        assert body["components"]["iot"]["status"] in {"ok", "not_configured"}
        assert body["components"]["database"]["status"] == "ok"


class TestApiDiscovery:
    def test_api_root_returns_service_document(self, client: TestClient) -> None:
        response = client.get(f"{API_PREFIX}/")

        assert response.status_code == 200
        assert response.json()["health"] == f"{API_PREFIX}/health"

    def test_openapi_schema_is_generated(self, client: TestClient) -> None:
        response = client.get("/openapi.json")

        assert response.status_code == 200
        paths = response.json()["paths"]
        assert f"{API_PREFIX}/auth/register" in paths
        assert f"{API_PREFIX}/auth/login" in paths
        assert f"{API_PREFIX}/auth/me" in paths


class TestErrorEnvelope:
    def test_unknown_route_uses_standard_error_envelope(self, client: TestClient) -> None:
        response = client.get(f"{API_PREFIX}/does-not-exist")

        assert response.status_code == 404
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "NOT_FOUND"
        assert isinstance(body["error"]["message"], str)

    def test_method_not_allowed_uses_standard_error_envelope(self, client: TestClient) -> None:
        response = client.delete(f"{API_PREFIX}/health")

        assert response.status_code == 405
        assert response.json()["success"] is False
