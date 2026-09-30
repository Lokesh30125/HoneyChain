"""Shared pytest fixtures.

Test isolation strategy
-----------------------
* Environment variables are set **before** ``app`` is imported so the settings
  cache and the module-level engine pick up the test configuration.
* The suite runs against a real PostgreSQL database by default
  (``honeychain_test``) because that is the database the project ships on.
  If no server is reachable the fixture falls back to a temporary SQLite file
  so tests still run on a machine without PostgreSQL; the fallback is reported
  loudly and is never used in production.
* Each test gets a clean schema: tables are truncated before every test function.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator

import pytest

# --------------------------------------------------------------------------- #
# Environment must be configured before anything from `app` is imported.
# --------------------------------------------------------------------------- #
os.environ["HONEYCHAIN_ENV"] = "testing"
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault(
    "JWT_SECRET_KEY", "testing-only-secret-key-not-valid-for-deployment-0123456789"
)
# Return the refresh token in the response body so tests can drive the full
# rotation/logout lifecycle the way a mobile client would.
os.environ.setdefault("AUTH_EXPOSE_REFRESH_IN_BODY", "true")

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+psycopg://honeychain:honeychain_dev_password@localhost:5432/honeychain_test"
)
os.environ.setdefault("DATABASE_URL", DEFAULT_TEST_DATABASE_URL)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core.config import clear_settings_cache, get_settings  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.models import User  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.repositories.user_repository import UserRepository  # noqa: E402

clear_settings_cache()
settings = get_settings()

API_PREFIX = settings.API_V1_PREFIX

#: Tables cleaned between tests. Children first; ``document_sequences`` is
#: included so generated codes (BKR-GNT-00001) restart deterministically for
#: each test instead of depending on execution order.
TRUNCATE_ORDER = (
    # Children before parents, so the SQLite fallback (which DELETEs table by
    # table) stays valid without relying on cascades.
    # Phase 8: the traceability outbox references every supply-chain record, so
    # it is emptied first or the deletes below would trip its foreign keys.
    "blockchain_events",
    #
    # ``lab_parameters`` is deliberately absent: it is a catalogue installed as
    # configuration, not transient data. PostgreSQL's ``TRUNCATE ... CASCADE``
    # reaches it anyway through ``lab_test_results``, which is exactly why
    # ``clean_database`` re-installs the catalogue after emptying the tables —
    # and why no test can depend on the order the two happened in.
    # Phase 7 (children first: a distribution names a package, a package names
    # the run that made it, and a run names the unit that did the work)
    "distributions",
    "packages",
    "packaging_records",
    "packaging_units",
    # Phase 6
    "lab_test_results",
    "lab_tests",
    "honey_processing_records",
    "processing_units",
    "laboratories",
    # Phase 3
    "sensor_readings",
    "sensor_configs",
    "iot_devices",
    "hives",
    # Phase 4
    "ai_alerts",
    "hive_ai_analyses",
    "beekeeper_verification_history",
    # Phase 5
    "honey_batches",
    "honey_collection_hives",
    "honey_collections",
    # Identity
    "beekeepers",
    "user_profiles",
    "audit_logs",
    "refresh_tokens",
    "kvic_clusters",
    "document_sequences",
    "users",
)

ADMIN_EMAIL = "admin@honeychain.example.com"
ADMIN_PASSWORD = "AdminPass123"


# --------------------------------------------------------------------------- #
# Engine / schema
# --------------------------------------------------------------------------- #
def _build_test_engine() -> tuple[Engine, bool]:
    """Return ``(engine, using_postgres)``."""
    try:
        candidate = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)
        with candidate.connect() as connection:
            connection.execute(text("SELECT 1"))
        return candidate, settings.DATABASE_URL.startswith("postgresql")
    except Exception:  # pragma: no cover - exercised only without PostgreSQL
        fallback_url = f"sqlite:///{os.path.join(os.path.dirname(__file__), '.pytest_fallback.db')}"
        print(
            "\n[conftest] WARNING: PostgreSQL is not reachable at "
            f"{settings.DATABASE_URL!r}.\n"
            f"[conftest] Falling back to SQLite ({fallback_url}) for this run. "
            "Start PostgreSQL to test against the production database engine.\n"
        )
        return create_engine(fallback_url, future=True), False


@pytest.fixture(scope="session")
def engine() -> Engine:
    test_engine, using_postgres = _build_test_engine()
    if using_postgres:
        Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    # The laboratory parameter catalogue is configuration installed by the Phase-6
    # migration, which ``create_all`` knows nothing about. A database built from
    # the models alone therefore has an empty catalogue, and every laboratory test
    # would fail for the wrong reason. This installs the same rows if they are
    # missing, and leaves anything already configured untouched.
    with Session(test_engine) as session:
        from app.scripts.seed_lab_parameters import seed_lab_parameters

        seed_lab_parameters(session)

    yield test_engine
    test_engine.dispose()


@pytest.fixture(scope="session")
def session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def clean_database(engine: Engine) -> Generator[None, None, None]:
    """Empty every table before each test so tests never leak state."""
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(
                text(f"TRUNCATE TABLE {', '.join(TRUNCATE_ORDER)} CASCADE")
            )
        else:
            for table in TRUNCATE_ORDER:
                connection.execute(text(f"DELETE FROM {table}"))

    # The laboratory catalogue is configuration, and configuration is
    # platform-wide: a test that configures a reference range must not change the
    # verdict of the next test, and a cascade must not leave the platform with no
    # parameters to record against. So it is restored to the state it ships in —
    # every row present, every row unconfigured.
    with Session(engine) as session:
        from app.scripts.seed_lab_parameters import seed_lab_parameters

        seed_lab_parameters(session)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE lab_parameters SET reference_min = NULL, reference_max = NULL, "
                "reference_source = NULL, reference_updated_by_id = NULL, "
                "reference_updated_at = NULL, is_required = false, is_active = true"
            )
        )
    yield


# --------------------------------------------------------------------------- #
# Database sessions / API client
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db(session_factory: sessionmaker) -> Generator[Session, None, None]:
    """A direct session for arranging fixtures or asserting on rows."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(session_factory: sessionmaker) -> Generator[TestClient, None, None]:
    """API client whose requests use their own short-lived sessions.

    This mirrors production behaviour (a request per unit of work) rather than
    sharing a single session across requests.
    """

    def override_get_db() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    with TestClient(fastapi_app, raise_server_exceptions=False) as test_client:
        yield test_client
    fastapi_app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Identity helpers
# --------------------------------------------------------------------------- #
@pytest.fixture()
def register_user(client: TestClient):
    """Factory: register a user through the public API and return the payload."""

    def _register(
        *,
        name: str = "Test Beekeeper",
        email: str | None = None,
        password: str = "HoneyPass123",
        role: UserRole | str = UserRole.BEEKEEPER,
        phone: str | None = None,
        **extra,
    ) -> dict:
        payload = {
            "name": name,
            "email": email or f"user-{uuid.uuid4().hex[:8]}@honeychain.example.com",
            "password": password,
            "role": str(role),
            "accepted_terms": True,
            **extra,
        }
        if phone:
            payload["phone"] = phone
        response = client.post(f"{API_PREFIX}/auth/register", json=payload)
        assert response.status_code == 201, response.text
        body = response.json()["data"]
        body["_password"] = password
        body["_request"] = payload
        return body

    return _register


@pytest.fixture()
def user_payload(register_user) -> dict:
    """A default registered beekeeper."""
    return register_user()


@pytest.fixture()
def auth_headers(user_payload) -> dict[str, str]:
    return {"Authorization": f"Bearer {user_payload['access_token']}"}


@pytest.fixture()
def admin_payload(db: Session) -> dict:
    """An ACTIVE administrator created directly.

    ADMIN cannot be self-registered (privilege-escalation guard), which is why
    this fixture writes the row through the repository instead.
    """
    from app.core.security import hash_password

    user = UserRepository(db).create_user(
        name="Platform Administrator",
        email=ADMIN_EMAIL,
        password_hash=hash_password(ADMIN_PASSWORD),
        role=UserRole.ADMIN,
    )
    db.commit()
    return {"id": user.id, "email": user.email, "password": ADMIN_PASSWORD}


@pytest.fixture()
def admin_headers(client: TestClient, admin_payload: dict) -> dict[str, str]:
    response = client.post(
        f"{API_PREFIX}/auth/login",
        json={"email": admin_payload["email"], "password": admin_payload["password"]},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


@pytest.fixture()
def deactivate_user(db: Session):
    """Disable an account so authorisation paths can be exercised."""

    def _deactivate(user_id) -> None:
        user = db.get(User, uuid.UUID(str(user_id)))
        assert user is not None
        user.is_active = False
        db.commit()

    return _deactivate


# --------------------------------------------------------------------------- #
# Phase 2 helpers
# --------------------------------------------------------------------------- #
@pytest.fixture()
def make_privileged_user(db: Session):
    """Factory: create an account for a role that cannot self-register.

    Privileged roles are provisioned out of band (by ``create_admin`` in
    production), so tests write them straight through the repository.
    """

    def _create(
        *,
        role: UserRole = UserRole.KVIC_OFFICER,
        name: str = "KVIC Officer",
        email: str | None = None,
        password: str = "OfficerPass123",
    ):
        from app.core.security import hash_password

        user = UserRepository(db).create_user(
            name=name,
            email=email or f"{role.value.lower()}-{uuid.uuid4().hex[:8]}@honeychain.example.com",
            password_hash=hash_password(password),
            role=role,
        )
        db.commit()
        return {"id": user.id, "email": user.email, "password": password, "role": str(role)}

    return _create


@pytest.fixture()
def kvic_payload(make_privileged_user) -> dict:
    return make_privileged_user(role=UserRole.KVIC_OFFICER, name="District KVIC Officer")


@pytest.fixture()
def kvic_headers(client: TestClient, kvic_payload: dict) -> dict[str, str]:
    response = client.post(
        f"{API_PREFIX}/auth/login",
        json={"email": kvic_payload["email"], "password": kvic_payload["password"]},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


@pytest.fixture()
def consumer_payload(register_user) -> dict:
    """A self-registered consumer — the least privileged authenticated role."""
    return register_user(
        role=UserRole.CONSUMER, name="Honey Consumer", email=None
    )


@pytest.fixture()
def consumer_headers(consumer_payload: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {consumer_payload['access_token']}"}


@pytest.fixture()
def beekeeper_record(user_payload: dict) -> dict:
    """The beekeeper row created automatically for the default registered user."""
    return user_payload["beekeeper"]
