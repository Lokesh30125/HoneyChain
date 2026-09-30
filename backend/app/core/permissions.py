"""Permission catalogue and reusable FastAPI authorization dependencies.

Why permissions rather than scattered role checks
-------------------------------------------------
Writing ``if user.role not in ("ADMIN", "KVIC_OFFICER")`` in a dozen routes
guarantees the rules will drift. Instead:

* every capability is a named ``Permission``;
* ``ROLE_PERMISSIONS`` is the single place mapping roles to capabilities;
* routes declare what they need — ``Depends(require_permission(Permission.BEEKEEPER_READ_ALL))``.

Adding a role or re-scoping a capability is then a one-line change here, and the
whole surface follows.

The frontend mirrors this catalogue only to *hide* navigation it cannot use.
Authorisation is always re-checked here on the server.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from fastapi import Depends

from app.api.dependencies import get_current_user
from app.core.exceptions import ForbiddenError
from app.core.logging import get_logger
from app.models.enums import UserRole
from app.models.user import User

logger = get_logger("auth")


class Permission(StrEnum):
    """A capability that can be granted to a role."""

    # -- Own account --------------------------------------------------------
    USER_READ_SELF = "USER_READ_SELF"
    USER_UPDATE_SELF = "USER_UPDATE_SELF"

    # -- Own beekeeper record ----------------------------------------------
    BEEKEEPER_READ_SELF = "BEEKEEPER_READ_SELF"
    BEEKEEPER_UPDATE_SELF = "BEEKEEPER_UPDATE_SELF"

    # -- Across the platform ------------------------------------------------
    BEEKEEPER_READ_ALL = "BEEKEEPER_READ_ALL"
    BEEKEEPER_UPDATE_ALL = "BEEKEEPER_UPDATE_ALL"
    BEEKEEPER_VERIFY = "BEEKEEPER_VERIFY"

    CLUSTER_READ = "CLUSTER_READ"
    #: Reading a cluster as an *operational view* — its beekeepers, their hives,
    #: the devices on those hives, their telemetry and their AI state. Distinct
    #: from ``CLUSTER_READ``, which every signed-in role holds so a beekeeper can
    #: see the name of their own cluster. Only staff hold this one: aggregation
    #: across other people's apiaries is oversight, not participation.
    CLUSTER_ANALYTICS_READ = "CLUSTER_ANALYTICS_READ"
    CLUSTER_MANAGE = "CLUSTER_MANAGE"

    # -- Own hives, devices and telemetry ------------------------------------
    HIVE_READ_SELF = "HIVE_READ_SELF"
    HIVE_WRITE_SELF = "HIVE_WRITE_SELF"
    DEVICE_READ_SELF = "DEVICE_READ_SELF"
    DEVICE_WRITE_SELF = "DEVICE_WRITE_SELF"
    TELEMETRY_READ_SELF = "TELEMETRY_READ_SELF"
    TELEMETRY_INGEST = "TELEMETRY_INGEST"

    # -- Across the platform -------------------------------------------------
    HIVE_READ_ALL = "HIVE_READ_ALL"
    HIVE_WRITE_ALL = "HIVE_WRITE_ALL"
    DEVICE_READ_ALL = "DEVICE_READ_ALL"
    DEVICE_WRITE_ALL = "DEVICE_WRITE_ALL"
    TELEMETRY_READ_ALL = "TELEMETRY_READ_ALL"

    # -- Collections and honey batches (Phase 5) ------------------------------
    #: Recording a harvest and reading it back, scoped to the caller's apiary.
    COLLECTION_READ_SELF = "COLLECTION_READ_SELF"
    COLLECTION_WRITE_SELF = "COLLECTION_WRITE_SELF"
    BATCH_READ_SELF = "BATCH_READ_SELF"
    #: Oversight across the platform, filtered by cluster where appropriate.
    #: Note there is deliberately no ``COLLECTION_WRITE_ALL``: a collection is a
    #: beekeeper's harvest record, and no role may enter one on their behalf.
    COLLECTION_READ_ALL = "COLLECTION_READ_ALL"
    BATCH_READ_ALL = "BATCH_READ_ALL"

    # -- Processing (Phase 6) ------------------------------------------------
    #: Reading processing runs. The *scope* is the service's job: a beekeeper
    #: reads their own batch's runs, a cluster officer the runs of their cluster,
    #: and the operational roles the shared work queue. One row, filtered — the
    #: platform does not keep a second copy for KVIC to read.
    PROCESSING_READ = "PROCESSING_READ"
    #: Opening, starting, correcting and completing a run. Held by processors and
    #: administrators; never by a beekeeper, who owns the honey but not the work.
    PROCESSING_WRITE = "PROCESSING_WRITE"
    #: Registering and editing processing units.
    PROCESSING_UNIT_MANAGE = "PROCESSING_UNIT_MANAGE"

    # -- Laboratory (Phase 6) ------------------------------------------------
    LABORATORY_READ = "LABORATORY_READ"
    #: Registering and editing laboratory facilities.
    LABORATORY_MANAGE = "LABORATORY_MANAGE"
    #: Reading laboratory tests and their recorded results (same scope rules as
    #: PROCESSING_READ).
    LAB_TEST_READ = "LAB_TEST_READ"
    #: Opening a test, recording its sample and its measured values, and
    #: completing it. Held by laboratory technicians and administrators.
    LAB_TEST_WRITE = "LAB_TEST_WRITE"
    #: Deciding a test against the configured rules rather than the recorded
    #: measurements. Administrator only, always with a reason, always audited.
    LAB_TEST_OVERRIDE = "LAB_TEST_OVERRIDE"
    #: Reading the parameter catalogue — which measurements exist, and whether a
    #: reference range has been configured for each.
    LAB_PARAMETER_READ = "LAB_PARAMETER_READ"
    #: Setting those reference ranges. Deliberately separate from LAB_TEST_WRITE:
    #: measuring honey and defining what "acceptable" means are different jobs.
    LAB_PARAMETER_CONFIGURE = "LAB_PARAMETER_CONFIGURE"

    # -- Packaging and distribution (Phase 7) --------------------------------
    #: Reading packaging runs, packages and the approved worklist. The *scope* is
    #: the service's job, exactly as in processing and the laboratory: a beekeeper
    #: reads their own batch's packages, an officer the packages of their
    #: clusters, and the operational roles the shared register.
    PACKAGING_READ = "PACKAGING_READ"
    #: Opening, running, completing and cancelling a packaging run, and releasing
    #: the packages it produced. Held by packaging units and administrators.
    PACKAGING_WRITE = "PACKAGING_WRITE"
    #: Registering and editing packaging facilities.
    PACKAGING_UNIT_MANAGE = "PACKAGING_UNIT_MANAGE"
    #: Reading shipments. A distributor reads their own; a retailer the ones
    #: addressed to them; a beekeeper and an officer through the batch they own.
    DISTRIBUTION_READ = "DISTRIBUTION_READ"
    #: Raising a shipment, dispatching it, marking it in transit, cancelling it.
    DISTRIBUTION_WRITE = "DISTRIBUTION_WRITE"
    #: Confirming receipt of a shipment addressed to the caller's own account.
    #: Separate from DISTRIBUTION_WRITE on purpose: receiving is the retailer's
    #: act about their own delivery, not authority over somebody else's shipment.
    SHIPMENT_RECEIVE = "SHIPMENT_RECEIVE"
    #: The directory of retailer accounts a shipment may be addressed to: names,
    #: organisation and district, and nothing else. A distributor has to be able to
    #: name the shop a shipment goes to, and typing it by hand is how shipments end
    #: up addressed to nobody — but a directory is not the user administration
    #: screen, which is why this is its own permission and returns its own fields.
    RETAILER_DIRECTORY_READ = "RETAILER_DIRECTORY_READ"

    # -- Blockchain traceability (Phase 8) ----------------------------------
    #: Reading the traceability ledger: the events HoneyChain recorded, their
    #: chain status and their payloads, and a batch's traceability. Held by
    #: administrators and cluster officers — and by nobody else at this level,
    #: because every other role reaches the same transactions through the record
    #: they are entitled to (a batch's history, or a package's public page).
    #: The KVIC officer's *scope* — their clusters — is applied by the service,
    #: exactly as it is on the batch register.
    BLOCKCHAIN_READ = "BLOCKCHAIN_READ"
    #: Submitting outstanding events, retrying a failed one, and reading the
    #: synchronization health. Administrator only: these write to an external
    #: system, and an operator should be the one deciding when.
    BLOCKCHAIN_SYNC = "BLOCKCHAIN_SYNC"

    # -- AI insights (Phase 4) ----------------------------------------------
    #: Read stored analyses for the caller's own hives, and ask for a fresh one.
    AI_READ_SELF = "AI_READ_SELF"
    AI_ANALYZE_SELF = "AI_ANALYZE_SELF"
    #: Read and run analyses for any hive in the platform (KVIC oversight, admin).
    AI_READ_ALL = "AI_READ_ALL"
    AI_ANALYZE_ALL = "AI_ANALYZE_ALL"

    # -- Administration -----------------------------------------------------
    USER_READ_ALL = "USER_READ_ALL"
    #: Creating an account for somebody else and enabling/disabling it.
    ADMIN_USER_MANAGE = "ADMIN_USER_MANAGE"
    #: Deciding *which* role an account holds — creating one with an operational
    #: role (LAB_TECHNICIAN, PROCESSOR, KVIC_OFFICER, …) and changing it later.
    #: Deliberately separate from ADMIN_USER_MANAGE, so "can disable an account"
    #: and "can grant a role" are two different decisions that cannot be granted
    #: by accident together. Only administrators hold it, and the service refuses
    #: the caller's own account, so no user can promote themselves.
    ADMIN_ROLE_ASSIGN = "ADMIN_ROLE_ASSIGN"
    ADMIN_SYSTEM_MANAGE = "ADMIN_SYSTEM_MANAGE"
    AUDIT_READ = "AUDIT_READ"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


#: Role → granted capabilities. The authoritative authorisation table.
ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.ADMIN: frozenset(
        {
            Permission.PACKAGING_READ,
            Permission.PACKAGING_WRITE,
            Permission.PACKAGING_UNIT_MANAGE,
            Permission.DISTRIBUTION_READ,
            Permission.DISTRIBUTION_WRITE,
            Permission.SHIPMENT_RECEIVE,
            Permission.USER_READ_SELF,
            Permission.USER_UPDATE_SELF,
            # No BEEKEEPER_READ_SELF / BEEKEEPER_UPDATE_SELF here: those mean
            # "my own beekeeper record", and an administrator does not have one,
            # so /beekeepers/me answers 403 rather than 404 by accident.
            Permission.BEEKEEPER_READ_ALL,
            Permission.BEEKEEPER_UPDATE_ALL,
            Permission.BEEKEEPER_VERIFY,
            Permission.CLUSTER_READ,
            Permission.CLUSTER_MANAGE,
            Permission.CLUSTER_ANALYTICS_READ,
            # Hives, devices and telemetry across the platform. The "_ALL"
            # scopes do not include the "_SELF" ones: an administrator has no
            # apiary of their own, exactly as with the beekeeper record.
            Permission.HIVE_READ_ALL,
            Permission.HIVE_WRITE_ALL,
            Permission.DEVICE_READ_ALL,
            Permission.DEVICE_WRITE_ALL,
            Permission.TELEMETRY_READ_ALL,
            Permission.TELEMETRY_INGEST,
            # AI analyses across the platform, for oversight.
            Permission.AI_READ_ALL,
            Permission.AI_ANALYZE_ALL,
            # Collections and batches: read-only oversight. An administrator may
            # see any beekeeper's harvest record, but never create one for them.
            Permission.COLLECTION_READ_ALL,
            Permission.BATCH_READ_ALL,
            # Phase 6: the administrator holds every processing and laboratory
            # capability, including the parameter configuration and the
            # override that no other role may perform.
            Permission.PROCESSING_READ,
            Permission.PROCESSING_WRITE,
            Permission.PROCESSING_UNIT_MANAGE,
            Permission.LABORATORY_READ,
            Permission.LABORATORY_MANAGE,
            Permission.LAB_TEST_READ,
            Permission.LAB_TEST_WRITE,
            Permission.LAB_TEST_OVERRIDE,
            Permission.LAB_PARAMETER_READ,
            Permission.LAB_PARAMETER_CONFIGURE,
            Permission.USER_READ_ALL,
            Permission.BLOCKCHAIN_READ,
            Permission.BLOCKCHAIN_SYNC,
            Permission.ADMIN_USER_MANAGE,
            Permission.ADMIN_ROLE_ASSIGN,
            Permission.ADMIN_SYSTEM_MANAGE,
            Permission.AUDIT_READ,
        }
    ),
    UserRole.KVIC_OFFICER: frozenset(
        {
            Permission.USER_READ_SELF,
            Permission.USER_UPDATE_SELF,
            # No BEEKEEPER_READ_SELF / BEEKEEPER_UPDATE_SELF here: those mean
            # "my own beekeeper record", and an administrator does not have one,
            # so /beekeepers/me answers 403 rather than 404 by accident.
            Permission.BEEKEEPER_READ_ALL,
            Permission.BEEKEEPER_UPDATE_ALL,
            # KVIC officers review and verify beekeepers in their clusters,
            # but cannot manage platform accounts or system settings.
            Permission.BEEKEEPER_VERIFY,
            Permission.CLUSTER_READ,
            Permission.CLUSTER_MANAGE,
            # The cluster workspace: a cluster read as one operational view of its
            # beekeepers, hives, devices, telemetry and AI state.
            Permission.CLUSTER_ANALYTICS_READ,
            # Downstream progress of the batches they can already see: read, never
            # written. The cluster scope does the narrowing; there is no second
            # copy of a package for KVIC to read.
            Permission.PACKAGING_READ,
            Permission.DISTRIBUTION_READ,
            # A KVIC officer monitors the apiaries in their district: read and
            # correct hive/device records, but the device status and telemetry
            # remain observable facts rather than something to edit.
            Permission.HIVE_READ_ALL,
            Permission.HIVE_WRITE_ALL,
            Permission.DEVICE_READ_ALL,
            Permission.DEVICE_WRITE_ALL,
            Permission.TELEMETRY_READ_ALL,
            Permission.TELEMETRY_INGEST,
            # KVIC officers review the apiaries they oversee, so they can read
            # and run analyses for those hives — the same scope the hive and
            # telemetry endpoints already give them.
            Permission.AI_READ_ALL,
            Permission.AI_ANALYZE_ALL,
            # Harvest records for the cluster space they oversee — read only,
            # and the same single record the beekeeper sees (never a copy).
            Permission.COLLECTION_READ_ALL,
            Permission.BATCH_READ_ALL,
            # Phase 6 oversight: how the cluster's honey was processed and what
            # the laboratory found. Read-only — a KVIC officer does not process
            # honey, measure it, or configure the limits it is judged against —
            # and scoped by the service to the clusters they oversee, so the
            # same single records are filtered rather than duplicated for them.
            Permission.PROCESSING_READ,
            Permission.LABORATORY_READ,
            Permission.LAB_TEST_READ,
            Permission.LAB_PARAMETER_READ,
            # The officer reads the ledger of the clusters they oversee — bounded
            # in the service by the same cluster registry their batch register is.
            Permission.BLOCKCHAIN_READ,
        }
    ),
    UserRole.BEEKEEPER: frozenset(
        {
            Permission.USER_READ_SELF,
            Permission.USER_UPDATE_SELF,
            Permission.BEEKEEPER_READ_SELF,
            Permission.BEEKEEPER_UPDATE_SELF,
            Permission.CLUSTER_READ,
            # Everything in the IoT module is scoped to the beekeeper's own
            # hives and devices; there is no id-parameter route that would let
            # one beekeeper reach another's apiary.
            Permission.HIVE_READ_SELF,
            Permission.HIVE_WRITE_SELF,
            Permission.DEVICE_READ_SELF,
            Permission.DEVICE_WRITE_SELF,
            Permission.TELEMETRY_READ_SELF,
            Permission.TELEMETRY_INGEST,
            # AI insights are scoped the same way: an analysis is built from the
            # caller's own readings and is only ever readable by that beekeeper
            # (staff scope aside). There is no id a beekeeper can pass to reach
            # another apiary.
            Permission.AI_READ_SELF,
            Permission.AI_ANALYZE_SELF,
            # Downstream progress of their own batches — the packages that came
            # out of their honey and where those went. Read-only by construction:
            # the beekeeper holds no packaging or distribution write permission at
            # all, and the service narrows every read to their own apiary.
            Permission.PACKAGING_READ,
            Permission.DISTRIBUTION_READ,
            # Collections are the beekeeper's own harvest events, and the batches
            # they produce. Both are scoped to their apiary by the service layer.
            Permission.COLLECTION_READ_SELF,
            Permission.COLLECTION_WRITE_SELF,
            Permission.BATCH_READ_SELF,
            # Phase 6: the beekeeper may *see* the progress of their own honey —
            # the processing run and the laboratory test with its recorded
            # values. Both are scoped to their own batches by the service, and
            # neither the write nor the override permission is granted, so the
            # read is the whole of their access.
            Permission.PROCESSING_READ,
            Permission.LAB_TEST_READ,
        }
    ),
    # Supply-chain and consumer roles: own account only until their modules
    # arrive in later phases.
    UserRole.COLLECTION_CENTER: frozenset(
        {
            Permission.USER_READ_SELF,
            Permission.USER_UPDATE_SELF,
            # The intake point receives the harvests of the apiaries in its
            # district, so it reads the same collection and batch records the
            # beekeeper and the officer read — filtered to its district, and
            # read-only: it holds no write permission anywhere upstream, because
            # a collection is recorded by the beekeeper who harvested the honey.
            Permission.COLLECTION_READ_ALL,
            Permission.BATCH_READ_ALL,
            # The clusters it receives from, to name them on a harvest row and to
            # filter the list by them. Read only: the cluster registry is run by
            # the administrator and the officer.
            Permission.CLUSTER_READ,
        }
    ),
    # A processor works the honey, and only that: batches to process, the runs
    # themselves, the units they happen in, and a read of the laboratory outcome
    # that decides what happens to the batch next. No laboratory write, no
    # parameter configuration, no account or system administration.
    UserRole.PROCESSOR: frozenset(
        {
            Permission.USER_READ_SELF,
            Permission.USER_UPDATE_SELF,
            Permission.BATCH_READ_ALL,
            Permission.PROCESSING_READ,
            Permission.PROCESSING_WRITE,
            Permission.PROCESSING_UNIT_MANAGE,
            Permission.LABORATORY_READ,
            Permission.LAB_TEST_READ,
            Permission.LAB_PARAMETER_READ,
            Permission.PACKAGING_READ,
        }
    ),
    # A laboratory technician measures the honey, and only that. The read of
    # processing is there because a test is opened against a processing run and
    # the chain back to the apiary is part of the test record — not because the
    # technician may change anything about it.
    UserRole.LAB_TECHNICIAN: frozenset(
        {
            Permission.USER_READ_SELF,
            Permission.USER_UPDATE_SELF,
            Permission.BATCH_READ_ALL,
            Permission.PROCESSING_READ,
            Permission.LABORATORY_READ,
            Permission.LABORATORY_MANAGE,
            Permission.LAB_TEST_READ,
            Permission.LAB_TEST_WRITE,
            Permission.LAB_PARAMETER_READ,
        }
    ),
    # A packaging unit packs approved batches and releases what it produced. It
    # reads the batch it is working on because that batch is the work: the codes,
    # the quantities and the laboratory verdict all come from it.
    UserRole.PACKAGING_UNIT: frozenset(
        {
            Permission.USER_READ_SELF,
            Permission.USER_UPDATE_SELF,
            Permission.BATCH_READ_ALL,
            Permission.PACKAGING_READ,
            Permission.PACKAGING_WRITE,
            Permission.PACKAGING_UNIT_MANAGE,
            Permission.DISTRIBUTION_READ,
            Permission.LABORATORY_READ,
            Permission.LAB_TEST_READ,
            Permission.LAB_PARAMETER_READ,
            Permission.PROCESSING_READ,
        }
    ),
    # A distributor moves packages that were released to them and records where
    # they went. There is deliberately no PACKAGING_WRITE here: a distributor
    # cannot pack, unpack, re-label or re-size anything.
    UserRole.DISTRIBUTOR: frozenset(
        {
            Permission.USER_READ_SELF,
            Permission.USER_UPDATE_SELF,
            Permission.DISTRIBUTION_READ,
            Permission.DISTRIBUTION_WRITE,
            # Who a shipment may be addressed to. Without it a distributor cannot
            # name a receiver, and a shipment addressed to nobody reaches nobody.
            Permission.RETAILER_DIRECTORY_READ,
            Permission.PACKAGING_READ,
            Permission.BATCH_READ_ALL,
        }
    ),
    # A retailer receives what was addressed to them and reads the provenance of
    # what they now hold — read-only everywhere else.
    UserRole.RETAILER: frozenset(
        {
            Permission.USER_READ_SELF,
            Permission.USER_UPDATE_SELF,
            Permission.DISTRIBUTION_READ,
            Permission.SHIPMENT_RECEIVE,
            Permission.PACKAGING_READ,
        }
    ),
    UserRole.CONSUMER: frozenset({Permission.USER_READ_SELF, Permission.USER_UPDATE_SELF}),
}


def permissions_for(role: UserRole | str) -> frozenset[Permission]:
    """Return the capability set for a role (empty when unknown)."""
    try:
        return ROLE_PERMISSIONS[UserRole(str(role))]
    except (KeyError, ValueError):
        return frozenset()


def has_permission(role: UserRole | str, permission: Permission) -> bool:
    return permission in permissions_for(role)


def has_any_permission(role: UserRole | str, permissions: set[Permission] | list[Permission]) -> bool:
    granted = permissions_for(role)
    return any(permission in granted for permission in permissions)


def assert_permission(user: User, permission: Permission) -> None:
    """Raise ``ForbiddenError`` unless ``user`` holds ``permission``.

    For imperative checks inside a service (the declarative dependency form is
    preferred for routes).
    """
    if not has_permission(user.role, permission):
        logger.warning(
            "Authorisation denied",
            extra={
                "user_id": str(user.id),
                "role": str(user.role),
                "required_permission": str(permission),
            },
        )
        raise ForbiddenError(
            "Your role does not permit this action",
            details={
                "required_permission": str(permission),
                "your_role": str(user.role),
            },
        )


# --------------------------------------------------------------------------- #
# FastAPI dependencies
# --------------------------------------------------------------------------- #
def require_permission(*permissions: Permission) -> Callable[[User], User]:
    """Dependency factory: the caller must hold **all** listed permissions.

    Usage::

        router = APIRouter(
            prefix="/beekeepers",
            dependencies=[Depends(require_permission(Permission.BEEKEEPER_READ_ALL))],
        )
    """
    required = tuple(permissions)

    def dependency(user: User = Depends(get_current_user)) -> User:
        granted = permissions_for(user.role)
        missing = [str(p) for p in required if p not in granted]
        if missing:
            logger.warning(
                "Authorisation denied",
                extra={
                    "user_id": str(user.id),
                    "role": str(user.role),
                    "missing_permissions": missing,
                },
            )
            raise ForbiddenError(
                "Your role does not permit this action",
                details={"required_permissions": [str(p) for p in required], "your_role": str(user.role)},
            )
        return user

    return dependency


def require_any_permission(*permissions: Permission) -> Callable[[User], User]:
    """Dependency factory: the caller must hold **at least one** listed permission."""
    required = tuple(permissions)

    def dependency(user: User = Depends(get_current_user)) -> User:
        if not has_any_permission(user.role, list(required)):
            logger.warning(
                "Authorisation denied",
                extra={"user_id": str(user.id), "role": str(user.role)},
            )
            raise ForbiddenError(
                "Your role does not permit this action",
                details={
                    "required_permissions_any_of": [str(p) for p in required],
                    "your_role": str(user.role),
                },
            )
        return user

    return dependency


def require_role(*roles: UserRole | str) -> Callable[[User], User]:
    """Dependency factory keyed on roles rather than permissions.

    Kept for the few places where the requirement genuinely *is* "this role"
    (for example, role-specific dashboards). Prefer
    :func:`require_permission` for capability checks.
    """
    allowed = {str(role) for role in roles}

    def dependency(user: User = Depends(get_current_user)) -> User:
        if str(user.role) not in allowed:
            logger.warning(
                "Authorisation denied",
                extra={"user_id": str(user.id), "role": str(user.role), "required_roles": sorted(allowed)},
            )
            raise ForbiddenError(
                "Your role does not have access to this resource",
                details={"required_roles": sorted(allowed), "your_role": str(user.role)},
            )
        return user

    return dependency


__all__ = [
    "Permission",
    "ROLE_PERMISSIONS",
    "permissions_for",
    "has_permission",
    "has_any_permission",
    "assert_permission",
    "require_permission",
    "require_any_permission",
    "require_role",
]
