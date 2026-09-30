"""HoneyChain API — application configuration.

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
    DATABASE_URL: str = (
        "postgresql+psycopg://honeychain@localhost:5432/honeychain_dev"
    )
    DATABASE_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # -- Authentication -----------------------------------------------------
    JWT_SECRET_KEY: str = INSECURE_SECRET_PLACEHOLDER
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "honeychain-api"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # -- Refresh-token cookie (browser clients) -----------------------------
    COOKIE_DOMAIN: str | None = None
    COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"

    AUTH_EXPOSE_REFRESH_IN_BODY: bool = False

    # -- CORS ---------------------------------------------------------------
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    # -- Blockchain traceability (Phase 8) ----------------------------------
    BLOCKCHAIN_ENABLED: bool = True
    BLOCKCHAIN_BASE_URL: str = ""
    BLOCKCHAIN_TIMEOUT_MS: int = 10000
    BLOCKCHAIN_RETRY_ATTEMPTS: int = 3
    BLOCKCHAIN_RETRY_BACKOFF_MS: int = 500
    BLOCKCHAIN_OUTBOX_WORKER_ENABLED: bool = True
    BLOCKCHAIN_OUTBOX_POLL_SECONDS: float = 5.0
    BLOCKCHAIN_OUTBOX_BATCH_SIZE: int = 25

    PUBLIC_TRACE_BASE_URL: str = "http://localhost:4173/trace"

    # -- Legacy blockchain placeholders -------------------------------------
    BLOCKCHAIN_NETWORK: str | None = None
    BLOCKCHAIN_RPC_URL: str | None = None
    BLOCKCHAIN_CONTRACT_ADDRESS: str | None = None

    # -- AI engine (Phase 4) ------------------------------------------------
    AI_API_KEY: str | None = None
    AI_MODEL_TYPE: str = "hive_ai_baseline"
    AI_MODEL_VERSION: str = "1.0"

    # -- Laboratory quality analysis ----------------------------------------
    LAB_DEMO_CONFIGURATION_ENABLED: bool = False
    LAB_DEMO_MEASUREMENTS_ENABLED: bool = False
    LAB_QUALITY_ANALYSIS_ENABLED: bool = True
    LAB_QUALITY_MODEL: str = "IsolationForest"
    LAB_QUALITY_MODEL_VERSION: str = "dev-v1"

    LAB_ALLOW_RISK_OVERRIDE: bool = False
    LAB_RISK_OVERRIDE_CONFIRMATION: str = "PROCEED"

    # -- AI analysis ---------------------------------------------------------
    AI_ANALYSIS_WINDOW_HOURS: int = 168
    AI_MIN_SAMPLES: int = 8
    AI_MIN_HISTORY_HOURS: int = 2
    AI_STALE_AFTER_HOURS: int = 6
    AI_YIELD_MIN_DAYS: int = 3
    AI_YIELD_MIN_SAMPLES: int = 6
    AI_YIELD_PERIOD_DAYS: int = 30
    AI_RECOMPUTE_AFTER_SAMPLES: int = 12
    AI_ANALYSIS_TTL_HOURS: int = 6
    AI_ALERT_COOLDOWN_HOURS: int = 12
    AI_AUTO_ANALYSIS_ENABLED: bool = True

    # -- IoT / MQTT ---------------------------------------------------------
    MQTT_BROKER_URL: str | None = None
    MQTT_PORT: int = 1883
    MQTT_USERNAME: str | None = None
    MQTT_PASSWORD: str | None = None
    MQTT_CLIENT_ID: str = "honeychain-backend"
    MQTT_TOPIC_PREFIX: str = "honeychain"
    MQTT_USE_TLS: bool = False
    MQTT_KEEPALIVE_SECONDS: int = 60
    MQTT_RECONNECT_SECONDS: int = 5
    MQTT_CONSUMER_ENABLED: bool = True

    # -- Device health ------------------------------------------------------
    DEVICE_OFFLINE_THRESHOLD_SECONDS: int = 900
    DEVICE_LOW_BATTERY_PERCENT: int = 20

    # -- Telemetry -----------------------------------------------------------
    TELEMETRY_AUDIT_INTERVAL_SECONDS: int = 3600
    TELEMETRY_MAX_PAYLOAD_BYTES: int = 8192
    TELEMETRY_MAX_CLOCK_SKEW_SECONDS: int = 300

    # -- Logging -------------------------------------------------------------
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    # -- Defaults / bootstrap -----------------------------------------------
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

            if raw.startswith("["):
                return json.loads(raw)

            return [
                origin.strip().rstrip("/")
                for origin in raw.split(",")
                if origin.strip()
            ]

        if isinstance(value, (list, tuple)):
            return [
                str(origin).strip().rstrip("/")
                for origin in value
                if str(origin).strip()
            ]

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
                problems.append(
                    "JWT_SECRET_KEY is still the placeholder value"
                )

            if len(self.JWT_SECRET_KEY) < 32:
                problems.append(
                    "JWT_SECRET_KEY must be at least 32 characters"
                )

            if self.DEBUG:
                problems.append("DEBUG must be false in production")

            if not self.CORS_ORIGINS:
                problems.append(
                    "CORS_ORIGINS must list the deployed frontend origin(s)"
                )

            if any(origin == "*" for origin in self.CORS_ORIGINS):
                problems.append(
                    "CORS_ORIGINS must not contain '*' in production"
                )

            for name in (
                "DATABASE_URL",
                "FRONTEND_URL",
                "PUBLIC_TRACE_BASE_URL",
            ):
                value = str(getattr(self, name, "") or "")

                if "localhost" in value or "127.0.0.1" in value:
                    # Allowed only for the database when it is a sidecar
                    # of the same compose project; every public URL must
                    # be the deployed one.
                    if name != "DATABASE_URL" or not os.getenv(
                        "ALLOW_LOCAL_DATABASE"
                    ):
                        problems.append(
                            f"{name} still points at localhost"
                        )

            if self.BLOCKCHAIN_ENABLED and not self.BLOCKCHAIN_BASE_URL:
                problems.append(
                    "BLOCKCHAIN_ENABLED is true but "
                    "BLOCKCHAIN_BASE_URL is empty "
                    "(set the URL, or BLOCKCHAIN_ENABLED=false)"
                )

            # Refresh tokens must not be exposed in the response body.
            if self.AUTH_EXPOSE_REFRESH_IN_BODY:
                problems.append(
                    "AUTH_EXPOSE_REFRESH_IN_BODY must be false"
                )

            # Demo lab configuration is intentionally allowed for the
            # deployed SIH demonstration. Risk override requires demo
            # measurements to be enabled.
            if (
                self.LAB_ALLOW_RISK_OVERRIDE
                and not self.LAB_DEMO_MEASUREMENTS_ENABLED
            ):
                problems.append(
                    "LAB_ALLOW_RISK_OVERRIDE requires "
                    "LAB_DEMO_MEASUREMENTS_ENABLED"
                )

            if problems:
                raise ValueError(
                    "Invalid production configuration: "
                    + "; ".join(problems)
                )

        return self

    # --------------------------------------------------------------------- #
    # Derived helpers
    # --------------------------------------------------------------------- #

    @property
    def mqtt_configured(self) -> bool:
        """True when a broker is configured."""
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

    Used by environment-matrix tests, Alembic and scripts that need to inspect
    a configuration other than the one the process was started with.
    """
    resolved = _resolve_env(environment)

    return Settings(
        ENVIRONMENT=resolved,  # type: ignore[arg-type]
        _env_file=_env_files(resolved),  # type: ignore[call-arg]
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings for the running process."""
    return build_settings()


def clear_settings_cache() -> None:
    """Reset the cache — required by tests that switch environments."""
    get_settings.cache_clear()
