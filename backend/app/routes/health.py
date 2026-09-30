"""Health and readiness endpoints.

``GET /api/v1/health``          liveness — used by the frontend status indicator
``GET /api/v1/health/db``       readiness — verifies PostgreSQL connectivity
``GET /api/v1/health/detailed`` component-by-component report
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import db_session
from app.core.config import Settings, get_settings
from app.core.database import check_database_connection
from app.core.logging import get_logger
from app.schemas.common import (
    ApiResponse,
    HealthDetailResponse,
    HealthResponse,
    ok,
)
from app.schemas.iot import MqttHealth

router = APIRouter(tags=["Health"])
logger = get_logger("service")


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service liveness",
    description="Cheap liveness probe. Does not touch the database.",
)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="HoneyChain API")


@router.get(
    "/health/db",
    response_model=ApiResponse[dict],
    summary="Database readiness",
    description="Verifies that the API can reach PostgreSQL and that migrations are applied.",
)
def health_db(
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    from sqlalchemy import inspect

    info = check_database_connection(settings)
    tables: list[str] = []
    if info["connected"]:
        tables = sorted(inspect(session.get_bind()).get_table_names())

    status = "ok" if info["connected"] else "degraded"
    if not info["connected"]:
        logger.error("Database readiness check failed")
    return ok(
        {
            "status": status,
            "database": {
                "connected": info["connected"],
                "dialect": info["dialect"],
                "server_version": info["server_version"],
                "environment": info["environment"],
            },
            "tables": tables,
        }
    )


@router.get(
    "/health/mqtt",
    response_model=ApiResponse[MqttHealth],
    summary="MQTT ingest status",
    description=(
        "Reports whether the broker consumer is running and what it has received. "
        "``not_configured`` is a normal state: without a broker the HTTP ingest "
        "endpoint (``POST /api/v1/iot/telemetry``) still accepts telemetry."
    ),
)
def health_mqtt() -> dict:
    from app.services.mqtt_service import get_ingest_service

    return ok(MqttHealth(**get_ingest_service().health()))


@router.get(
    "/health/detailed",
    response_model=HealthDetailResponse,
    summary="Full component report",
    description=(
        "Reports the status of each subsystem. The blockchain component reports "
        "the real state of the traceability outbox — how many events have been "
        "confirmed, how many are still owed to the chain — and never the URL of "
        "a service the caller has no business knowing: this endpoint is "
        "unauthenticated."
    ),
)
def health_detailed(
    settings: Settings = Depends(get_settings),
    session: Session = Depends(db_session),
) -> HealthDetailResponse:
    database = check_database_connection(settings)

    def placeholder(configured: bool) -> str:
        return "configured" if configured else "not_configured"

    # The outbox is the honest answer to "is the blockchain working?": the
    # events HoneyChain has recorded and what has become of them. It is read
    # from the database, so this endpoint stays cheap and says nothing that is
    # not already true.
    blockchain_outbox: dict[str, object]
    if not settings.BLOCKCHAIN_ENABLED:
        blockchain_outbox = {"status": "disabled", "enabled": False}
    else:
        try:
            from app.services.blockchain.service import BlockchainService

            counts = BlockchainService(session).counts()
            failed = counts["failed"]
            blockchain_outbox = {
                "status": "degraded" if failed else "ok",
                "enabled": True,
                "configured": bool(settings.BLOCKCHAIN_BASE_URL),
                "events_recorded": counts["total"],
                "pending": counts["pending"],
                "submitted": counts["submitted"],
                "confirmed": counts["confirmed"],
                "failed": failed,
                "skipped": counts["skipped"],
                "last_confirmed_at": counts["last_confirmed_at"],
                "last_confirmed_tx_id": counts["last_confirmed_tx_id"],
            }
        except Exception as error:  # noqa: BLE001 - a health report must answer
            # The report about the blockchain must not become another thing that
            # can take the health endpoint down: a failure to read the outbox is
            # reported as exactly that.
            logger.warning("Blockchain health could not be read: %s", error)
            # The detail stays in the log; the public report says only that the
            # outbox could not be read (exception text can carry SQL or hosts).
            blockchain_outbox = {"status": "unknown", "error": "The outbox could not be read."}

    components: dict[str, object] = {
        "database": {
            "status": "ok" if database["connected"] else "down",
            "dialect": database["dialect"],
        },
        "authentication": {"status": "ok", "strategy": "JWT (access + rotating refresh)"},
        "blockchain": blockchain_outbox,
        # Phase 3 delivered the IoT foundation (device registry, sensor
        # configuration, MQTT + HTTP telemetry ingest). The status here reflects
        # whether a broker is configured, not whether the module exists.
        "iot": {
            "status": "ok" if settings.MQTT_BROKER_URL else "not_configured",
            "phase": "Phase 3",
            "ingest": "MQTT + HTTP",
            "broker_configured": bool(settings.MQTT_BROKER_URL),
        },
        "ai": {"status": placeholder(bool(settings.AI_API_KEY)), "phase": "Phase 5"},
    }
    all_ok = database["connected"]
    return HealthDetailResponse(
        status="ok" if all_ok else "degraded",
        service=settings.SERVICE_NAME,
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(timezone.utc),
        components=components,
    )
