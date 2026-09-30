"""
HoneyChain API — application configuration.

All runtime configuration is read from environment variables (optionally seeded
from ``.env`` files). Nothing in this module contains a real secret: the
placeholders in ``.env.example`` are intentionally non-functional.

Environment file resolution order (later files win):

    1. ``<repo-root>/.env``            shared defaults (optional)
    2. ``backend/.env``                local developer overrides (git-ignored)
    3. ``backend/.env.<ENVIRONMENT>``  environment specific overrides
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# backend/app/core/config.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent

Environment = Literal["development", "testing", "production"]

# Sentinel used in .env.example. Loading it in production is a hard error.
INSECURE_SECRET_PLACEHOLDER = "change-me-to-a-long-random-string"


def _resolve_env(environment: str | None = None) -> str:
    return (
        environment
        or os.getenv("HONEYCHAIN_ENV")
        or os.getenv("ENVIRONMENT")
        or "development"
    ).strip().lower()


def _env_files(environment: str) -> tuple[str, ...]:
    candidates = (
        PROJECT_ROOT / ".env",
        BACKEND_DIR / ".env",
        BACKEND_DIR / f".env.{environment}",
    )
    return tuple(str(path) for path in candidates if path.is_file())


class Settings(BaseSettings):
    """Typed, validated application settings."""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Application --------------------------------------------------------
    PROJECT_NAME: str = "HoneyChain"
    SERVICE_NAME: str = "HoneyChain API"
    VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: Environment = "development"
    DEBUG: bool = False
    BACKEND_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:5173"

    # -- Database -----------------------------------------------------------
    # No credentials in code: the development password lives in backend/.env.
    DATABASE_URL: str = "postgresql+psycopg://honeychain@localhost:5432/honeychain_dev"
    DATABASE_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # -- Authentication -----------------------------------------------------
    JWT_SECRET_KEY: str = INSECURE_SECRET_PLACEHOLDER
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "honeychain-api"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # -- Refresh-token cookie (browser clients) ------------------------------
    #: Leave unset in development (localhost). Set to the parent domain, e.g.
    #: ``.honeychain.gov.in``, only when the API and SPA share a registrable domain.
    COOKIE_DOMAIN: str | None = None
    #: ``lax`` works for same-site deployments; use ``none`` (with HTTPS) when the
    #: SPA is served from a different site than the API.
    COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"
    #: When true, the refresh token is also returned in the JSON body so that
    #: non-browser clients (mobile app, Postman) can manage it themselves.
    AUTH_EXPOSE_REFRESH_IN_BODY: bool = False

    # -- CORS ---------------------------------------------------------------
    # ``NoDecode`` keeps pydantic-settings from JSON-decoding the raw value, so
    # a plain comma-separated list works in both .env files and real env vars.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    # -- Blockchain traceability (Phase 8) ----------------------------------
    #: Whether HoneyChain writes supply-chain events to the blockchain service.
    #: With this off, events are still recorded in the outbox (and the ledger
    #: shows them as SKIPPED) — nothing about the operational workflow changes.
    BLOCKCHAIN_ENABLED: bool = True
    #: Base URL of the running ledger service. The API endpoints are appended to
    #: it: ``POST {BASE_URL}/transactions``, ``GET {BASE_URL}/transactions``.
    #: Configured here and nowhere else — no module builds this URL itself.
    BLOCKCHAIN_BASE_URL: str = ""
    #: Per-request timeout, in milliseconds.
    BLOCKCHAIN_TIMEOUT_MS: int = 10000
    #: How many times one submission is attempted before it is left FAILED for a
    #: human to retry. Each attempt is recorded; a failure is never swallowed.
    BLOCKCHAIN_RETRY_ATTEMPTS: int = 3
    #: Base delay between attempts, in milliseconds. Attempt *n* waits
    #: ``RETRY_BACKOFF_MS * n``, so a service that is coming back up is not
    #: hammered and a service that is down does not stall a request for long.
    BLOCKCHAIN_RETRY_BACKOFF_MS: int = 500
    #: The outbox worker: pending events are submitted on this interval, which is
    #: what makes a transaction that failed during an outage arrive on its own
    #: once the service is back. Set ``OUTBOX_WORKER_ENABLED=false`` in tests
    #: that submit explicitly.
    BLOCKCHAIN_OUTBOX_WORKER_ENABLED: bool = True
    BLOCKCHAIN_OUTBOX_POLL_SECONDS: float = 5.0
    #: How many pending events one sweep will submit. Bounded so a large backlog
    #: is worked through steadily rather than in one burst against the service.
    BLOCKCHAIN_OUTBOX_BATCH_SIZE: int = 25
    #: Public base URL used to build a package's QR link. On a deployment this is
    #: the customer-facing site (``https://trace.example.org``); in development
    #: it is the frontend preview. Only the package code is appended to it.
    PUBLIC_TRACE_BASE_URL: str = "http://localhost:4173/trace"

    # -- Legacy blockchain placeholders (kept so old .env files still load) --
    BLOCKCHAIN_NETWORK: str | None = None
    BLOCKCHAIN_RPC_URL: str | None = None
    BLOCKCHAIN_CONTRACT_ADDRESS: str | None = None

    # -- AI engine (Phase 4) -------------------------------------------------
    #: Reserved for a future hosted inference provider. The engine that ships
    #: today is a local, transparent baseline and needs no API key, so this
    #: stays empty and nothing reads it.
    AI_API_KEY: str | None = None
    #: The model identity written onto every analysis. ``model_type`` +
    #: ``model_version`` are what make an old result still understandable after
    #: the scoring logic changes.
    AI_MODEL_TYPE: str = "hive_ai_baseline"
    AI_MODEL_VERSION: str = "1.0"
    # -- Laboratory quality analysis (correction phase) ----------------------
    #: Whether the development reference ranges, method lists and starting values
    #: are installed onto the parameter catalogue. They are **development
    #: configuration**, labelled with their source, and they never overwrite a
    #: range a person configured. With this off the catalogue ships unconfigured
    #: and a measurement is reported as NOT_EVALUATED — which is the honest
    #: production behaviour until real limits are entered.
    LAB_DEMO_CONFIGURATION_ENABLED: bool = False
    #: Whether a development value is pre-filled for each configured parameter
    #: when a laboratory test is opened. The values are stored with
    #: ``measurement_source=DEMO`` and every screen labels them: they are a
    #: starting point a technician confirms or replaces, never a measurement the
    #: platform claims was taken. Production installations turn this off and the
    #: technician enters every reading.
    LAB_DEMO_MEASUREMENTS_ENABLED: bool = False
    #: Whether the quality analysis runs at all. It reads the measurements already
    #: on the test and the configured reference ranges; it is development
    #: decision-support, not a validated instrument.
    LAB_QUALITY_ANALYSIS_ENABLED: bool = True
    #: The identity written onto every laboratory analysis, exactly as the hive
    #: engine does — so a stored result can be read back with what produced it.
    LAB_QUALITY_MODEL: str = "IsolationForest"
    LAB_QUALITY_MODEL_VERSION: str = "dev-v1"
    #: Whether a user may continue with a batch the analysis flagged as risky.
    #: This is a **development/demo override** and is off by default: with it off,
    #: the API does not offer the action and refuses it if it is called. An
    #: override always requires an explicit confirmation and is audited.
    LAB_ALLOW_RISK_OVERRIDE: bool = False
    #: A required confirmation word for the override, so a stray click cannot
    #: release a flagged batch: the caller must echo it back.
    LAB_RISK_OVERRIDE_CONFIRMATION: str = "PROCEED"

    #: How much telemetry an analysis reads. A week is long enough for a weight
    #: trend and a diurnal temperature pattern without pulling a whole season
    #: into memory.
    AI_ANALYSIS_WINDOW_HOURS: int = 168
    #: Readings below this are not enough to say anything about a trend.
    AI_MIN_SAMPLES: int = 8
    #: History shorter than this cannot support a trend statement, however many
    #: samples it contains (a burst of ten packets in one minute is not history).
    AI_MIN_HISTORY_HOURS: int = 2
    #: A reading older than this makes the analysis stale: the colony may have
    #: changed since, and the UI says so instead of quietly showing old numbers.
    AI_STALE_AFTER_HOURS: int = 6
    #: Weight trend over fewer days than this is not projected into a yield.
    AI_YIELD_MIN_DAYS: int = 3
    AI_YIELD_MIN_SAMPLES: int = 6
    #: The forecast horizon offered in the UI ("if the current rate continued").
    AI_YIELD_PERIOD_DAYS: int = 30
    #: An analysis is recomputed automatically once this many new readings have
    #: arrived, or when it is older than the TTL — never once per packet.
    AI_RECOMPUTE_AFTER_SAMPLES: int = 12
    AI_ANALYSIS_TTL_HOURS: int = 6
    #: While an alert of the same type is active, a repeat signal inside this
    #: window updates the existing alert instead of creating another one.
    AI_ALERT_COOLDOWN_HOURS: int = 12
    #: Run the periodic sweep job (``python -m app.scripts.ai_analysis_sweep``).
    AI_AUTO_ANALYSIS_ENABLED: bool = True

    # -- IoT / MQTT ---------------------------------------------------------
    # The broker is optional: without ``MQTT_BROKER_URL`` the API, the HTTP
    # telemetry endpoint and the whole dashboard still work, and ``/health/mqtt``
    # simply reports that ingest is not configured.
    MQTT_BROKER_URL: str | None = None
    MQTT_PORT: int = 1883
    MQTT_USERNAME: str | None = None
    MQTT_PASSWORD: str | None = None
    MQTT_CLIENT_ID: str = "honeychain-backend"
    MQTT_TOPIC_PREFIX: str = "honeychain"
    MQTT_USE_TLS: bool = False
    MQTT_KEEPALIVE_SECONDS: int = 60
    #: Seconds to wait before reconnecting after a dropped broker connection.
    MQTT_RECONNECT_SECONDS: int = 5
    #: Run the MQTT subscriber inside the API process. Disable it when a
    #: dedicated consumer process is deployed instead.
    MQTT_CONSUMER_ENABLED: bool = True

    # -- Device health ------------------------------------------------------
    #: A device that has not reported for this long is OFFLINE. Deliberately
    #: generous: one lost packet must never mark working hardware as offline.
    DEVICE_OFFLINE_THRESHOLD_SECONDS: int = 900
    #: Below this battery level a reachable device is reported as WARNING.
    DEVICE_LOW_BATTERY_PERCENT: int = 20

    # -- Telemetry ----------------------------------------------------------
    #: One audit entry per device per window, instead of one per packet.
    TELEMETRY_AUDIT_INTERVAL_SECONDS: int = 3600
    #: Hard cap on an ingest payload, so a misbehaving device cannot post
    #: megabytes into the time series.
    TELEMETRY_MAX_PAYLOAD_BYTES: int = 8192
    #: A reading timestamped further in the future than this is rejected;
    #: unsynchronised clocks are common on cheap hardware.
    TELEMETRY_MAX_CLOCK_SKEW_SECONDS: int = 300

    # -- Logging ------------------------------------------------------------
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    # -- Defaults / bootstrap ----------------------------------------------
    DEFAULT_ADMIN_EMAIL: str | None = None
    DEFAULT_ADMIN_PASSWORD: str | None = None

    # --------------------------------------------------------------------- #
    # Validators
    # --------------------------------------------------------------------- #
    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept ``a,b,c`` strings as well as JSON lists."""
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):  # JSON array form is still accepted
                return json.loads(raw)
            return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]
        if isinstance(value, (list, tuple)):
            return [str(origin).strip().rstrip("/") for origin in value if str(origin).strip()]
        return value

    @field_validator("LOG_LEVEL")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> "Settings":
        if self.ENVIRONMENT == "production":
            problems: list[str] = []
            if self.JWT_SECRET_KEY == INSECURE_SECRET_PLACEHOLDER:
                problems.append("JWT_SECRET_KEY is still the placeholder value")
            if len(self.JWT_SECRET_KEY) < 32:
                problems.append("JWT_SECRET_KEY must be at least 32 characters")
            if self.DEBUG:
                problems.append("DEBUG must be false in production")
            if not self.CORS_ORIGINS:
                problems.append("CORS_ORIGINS must list the deployed frontend origin(s)")
            if any(origin == "*" for origin in self.CORS_ORIGINS):
                problems.append("CORS_ORIGINS must not contain '*' in production")
            for name in ("DATABASE_URL", "FRONTEND_URL", "PUBLIC_TRACE_BASE_URL"):
                value = str(getattr(self, name, "") or "")
                if "localhost" in value or "127.0.0.1" in value:
                    # Allowed only for the database when it is a sidecar of the same
                    # compose project; every public URL must be the deployed one.
                    if name != "DATABASE_URL" or not os.getenv("ALLOW_LOCAL_DATABASE"):
                        problems.append(f"{name} still points at localhost")
            if self.BLOCKCHAIN_ENABLED and not self.BLOCKCHAIN_BASE_URL:
                problems.append(
                    "BLOCKCHAIN_ENABLED is true but BLOCKCHAIN_BASE_URL is empty "
                    "(set the URL, or BLOCKCHAIN_ENABLED=false)"
                )
            for flag in (
                "AUTH_EXPOSE_REFRESH_IN_BODY",
                "LAB_ALLOW_RISK_OVERRIDE",
                "LAB_DEMO_CONFIGURATION_ENABLED",
                "LAB_DEMO_MEASUREMENTS_ENABLED",
            ):
                if getattr(self, flag, False):
                    problems.append(f"{flag} is a development setting and must be false")
            if problems:
                raise ValueError(
                    "Invalid production configuration: " + "; ".join(problems)
                )
        return self

    # --------------------------------------------------------------------- #
    # Derived helpers
    # --------------------------------------------------------------------- #
    @property
    def mqtt_configured(self) -> bool:
        """True when a broker is configured, i.e. MQTT ingest should be started."""
        return bool(self.MQTT_BROKER_URL)

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_testing(self) -> bool:
        return self.ENVIRONMENT == "testing"

    @property
    def access_token_ttl_seconds(self) -> int:
        return self.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60

    @property
    def refresh_token_ttl_seconds(self) -> int:
        return self.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60


def build_settings(environment: str | None = None) -> Settings:
    """Build a *fresh* ``Settings`` instance for the requested environment.

    Used by environment-matrix tests, Alembic and scripts that need to inspect a
    configuration other than the one the process was started with.
    """
    resolved = _resolve_env(environment)
    return Settings(
        ENVIRONMENT=resolved,  # type: ignore[arg-type]
        _env_file=_env_files(resolved),  # type: ignore[call-arg]
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings for the running process (the normal entry point)."""
    return build_settings()


def clear_settings_cache() -> None:
    """Reset the cache — required by tests that switch environments."""
    get_settings.cache_clear()
