"""HoneyChain API — application factory and global error handling.

Run locally with::

    uvicorn app.main:app --reload --port 8000

The module builds the ASGI app, wires middleware, mounts the versioned router
and translates every exception class into the single documented error envelope.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.core.config import get_settings
from app.core.database import check_database_connection
from app.core.exceptions import AppError, DatabaseError, ErrorCode
from app.core.logging import configure_logging, get_logger
from app.middleware.request_context import REQUEST_ID_HEADER, RequestContextMiddleware
from app.schemas.common import HealthResponse

settings = get_settings()
configure_logging(settings)
logger = get_logger("api")


# --------------------------------------------------------------------------- #
# Error envelope helpers
# --------------------------------------------------------------------------- #
def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict] | dict | None = None,
    request_id: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the canonical ``{"success": false, "error": {...}}`` response."""
    error: dict[str, object] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": error, "request_id": request_id},
        headers=headers,
    )


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


# HTTP status -> stable error code mapping for framework-raised errors.
HTTP_STATUS_CODES: dict[int, ErrorCode] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.AUTHENTICATION_ERROR,
    403: ErrorCode.PERMISSION_DENIED,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.BAD_REQUEST,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.RATE_LIMITED,
    500: ErrorCode.INTERNAL_ERROR,
    501: ErrorCode.NOT_IMPLEMENTED,
    503: ErrorCode.SERVICE_UNAVAILABLE,
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown hooks: fail loudly on misconfiguration, log readiness."""
    logger.info(
        "Starting HoneyChain API",
        extra={
            "version": settings.VERSION,
            "environment": settings.ENVIRONMENT,
            "debug": settings.DEBUG,
            "api_prefix": settings.API_V1_PREFIX,
            "cors_origins": settings.CORS_ORIGINS,
        },
    )

    database = check_database_connection(settings)
    if database["connected"]:
        logger.info(
            "Database connection established",
            extra={"dialect": database["dialect"], "server_version": database["server_version"]},
        )
    else:
        # Deliberately non-fatal: the API still serves /health so an operator or
        # container orchestrator can see *why* the service is unhealthy.
        logger.error(
            "Database connection could not be established at startup — "
            "health endpoints will report 'degraded'"
        )

    # -- MQTT ingest ------------------------------------------------------- #
    # Started in a background thread so a slow or absent broker delays nothing.
    # With no broker configured this is a no-op and the HTTP telemetry endpoint
    # remains the ingest path (the ESP32 firmware can use either).
    from app.services.mqtt_service import get_ingest_service

    mqtt = get_ingest_service(settings)
    if mqtt.enabled:
        mqtt.start()
    else:
        logger.info(
            "MQTT ingest is not configured — telemetry can still be posted to "
            "POST %s/iot/telemetry",
            settings.API_V1_PREFIX,
        )

    # -- Blockchain outbox worker ------------------------------------------ #
    # One asyncio task that submits traceability events the blockchain service
    # has not accepted yet. It is what makes an outage recover by itself: an
    # event recorded while the chain was unreachable is written as soon as the
    # chain answers again, with no operator involved and nothing faked in the
    # meantime. Switched off for tests, which submit explicitly.
    outbox_task: asyncio.Task | None = None
    if settings.BLOCKCHAIN_ENABLED and settings.BLOCKCHAIN_OUTBOX_WORKER_ENABLED:
        from app.services.blockchain.worker import run_outbox_worker

        outbox_task = asyncio.create_task(run_outbox_worker(), name="blockchain-outbox")
    else:
        logger.info(
            "Blockchain outbox worker is off — pending events wait for "
            "POST %s/blockchain/sync",
            settings.API_V1_PREFIX,
        )

    yield

    if outbox_task is not None:
        outbox_task.cancel()
        with suppress(asyncio.CancelledError):
            await outbox_task
    mqtt.stop()
    logger.info("Shutting down HoneyChain API")


def create_app() -> FastAPI:
    """Application factory (also used by the test suite)."""
    application = FastAPI(
        title=settings.SERVICE_NAME,
        description=(
            "Blockchain-based honey traceability and smart beekeeping management.\n\n"
            "**Phase 3 (current):** hive management and the smart-hive IoT foundation — "
            "hive registry, device registration, sensor configuration, MQTT/HTTP "
            "telemetry ingest and live monitoring.\n\n"
            "Blockchain anchoring, AI insights, QR verification and the supply-chain "
            "modules are delivered in later phases."
        ),
        version=settings.VERSION,
        # Off in production: the schema of every endpoint is not public material.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
        contact={"name": "HoneyChain Project Team"},
        license_info={"name": "Proprietary — Smart India Hackathon 2026, PS ID 26021"},
    )

    # -- Middleware (outermost first) --------------------------------------
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,  # explicit allow-list, never "*"
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
        max_age=600,
    )

    # -- Routes -------------------------------------------------------------
    application.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @application.get("/", tags=["Health"], response_model=HealthResponse, include_in_schema=False)
    def root() -> HealthResponse:
        return HealthResponse(status="ok", service=settings.SERVICE_NAME)

    # -- Exception handlers -------------------------------------------------
    _register_exception_handlers(application)
    return application


def _register_exception_handlers(application: FastAPI) -> None:
    @application.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        """Domain errors raised by services/routes."""
        level = logger.warning if exc.status_code < 500 else logger.error
        level(
            "Application error",
            extra={
                "code": str(exc.code),
                "status_code": exc.status_code,
                "path": request.url.path,
            },
        )
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return error_response(
            status_code=exc.status_code,
            code=str(exc.code),
            message=exc.message,
            details=exc.details,
            request_id=_request_id(request),
            headers=headers,
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Convert Pydantic errors into field-level details the UI can render."""
        details = [
            {
                "field": ".".join(str(part) for part in error.get("loc", ()) if part != "body"),
                "message": error.get("msg", "Invalid value"),
                "type": error.get("type", "value_error"),
            }
            for error in exc.errors()
        ]
        logger.info(
            "Request validation failed",
            extra={"path": request.url.path, "fields": [d["field"] for d in details]},
        )
        return error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=str(ErrorCode.VALIDATION_ERROR),
            message="Invalid request",
            details=details,
            request_id=_request_id(request),
        )

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Framework-level HTTP errors (404 routing, 405 method, 401 from deps)."""
        code = HTTP_STATUS_CODES.get(exc.status_code, ErrorCode.BAD_REQUEST)
        headers = dict(exc.headers or {})
        if exc.status_code == 401 and "WWW-Authenticate" not in headers:
            headers["WWW-Authenticate"] = "Bearer"
        return error_response(
            status_code=exc.status_code,
            code=str(code),
            message=str(exc.detail) if exc.detail else "Request failed",
            request_id=_request_id(request),
            headers=headers,
        )

    @application.exception_handler(IntegrityError)
    async def handle_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        """Database constraint violations are a 409, never a stack trace."""
        logger.warning(
            "Database integrity error",
            extra={"path": request.url.path, "constraint": getattr(exc.orig, "diag", None) and getattr(exc.orig.diag, "constraint_name", None)},
        )
        return error_response(
            status_code=status.HTTP_409_CONFLICT,
            code=str(ErrorCode.CONFLICT),
            message="The request conflicts with existing data",
            request_id=_request_id(request),
        )

    @application.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        """Any other database failure — logged in full, generic to the client."""
        logger.error(
            "Unhandled database error",
            extra={"path": request.url.path, "error_type": type(exc).__name__},
            exc_info=exc,
        )
        database_error = DatabaseError()
        return error_response(
            status_code=database_error.status_code,
            code=str(database_error.code),
            message=database_error.message,
            request_id=_request_id(request),
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """Last resort: never leak internals, always log the traceback."""
        logger.exception(
            "Unhandled exception",
            extra={"path": request.url.path, "error_type": type(exc).__name__},
        )
        return error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code=str(ErrorCode.INTERNAL_ERROR),
            message="An unexpected error occurred. Please try again.",
            request_id=_request_id(request),
        )


app = create_app()

__all__ = ["app", "create_app", "error_response"]
