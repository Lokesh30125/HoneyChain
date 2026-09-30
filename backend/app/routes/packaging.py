"""Packaging routes — the worklist, the runs, the packages they produce.

``GET /packaging/approved-batches``
    The batches a packaging unit may take work from. Only laboratory-approved
    batches are returned, and each row carries the quantities already recorded
    against it — the collection, the processing output, what is already packed
    and what is left. It is a *view of the batch*, not a copy of it.
``POST /packaging`` / ``PATCH /packaging/{id}``
    Open a run and record what was packed while it is open.
``POST /packaging/{id}/{start,complete,cancel}``
    Move the run along. Completion is what creates the package rows and moves the
    batch to ``PACKAGED``; there is no endpoint that sets either by hand.
``GET /packages`` / ``GET /packages/{id}`` / ``GET /batches/{id}/packages``
    The package register, read from the rows that exist.
``POST /packages/{id}/release`` / ``POST /packaging/{id}/release``
    Release packages for distribution — existence is not readiness.
``GET /packaging/summary``
    Counters for the workspace dashboard.

Authorization is declared per endpoint and re-checked in the service, which also
narrows every read to the caller's scope. A packaging unit reaches packaging rows;
a beekeeper reaches the packages of their own honey; nobody reaches a write they
do not hold the permission for.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import db_session
from app.core.permissions import Permission, require_permission
from app.models.enums import FacilityStatus, PackageStatus, PackagingStatus
from app.models.user import User
from app.schemas.common import ApiResponse, PaginationParams, ok, paginated
from app.schemas.packaging import (
    ApprovedBatchItem,
    PackageDetail,
    PackageListItem,
    PackageRelease,
    PackagingCancel,
    PackagingComplete,
    PackagingCreate,
    PackagingDetail,
    PackagingListItem,
    PackagingSummary,
    PackagingUnitCreate,
    PackagingUnitMemberChange,
    PackagingUnitRead,
    PackagingUnitUpdate,
    PackagingUpdate,
)
from app.services.packaging_service import PackagingService

router = APIRouter(tags=["Packaging"])

READ_PACKAGING = require_permission(Permission.PACKAGING_READ)
WRITE_PACKAGING = require_permission(Permission.PACKAGING_WRITE)
MANAGE_UNITS = require_permission(Permission.PACKAGING_UNIT_MANAGE)


# --------------------------------------------------------------------------- #
# Packaging units
# --------------------------------------------------------------------------- #
@router.get(
    "/packaging-units",
    response_model=ApiResponse[list[PackagingUnitRead]],
    summary="List packaging units",
    description=(
        "Registered packaging facilities, paginated. A unit is registered once and reused by "
        "every run that happens in it."
    ),
)
def list_packaging_units(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120),
    status_filter: FacilityStatus | None = Query(default=None, alias="status"),
    user: User = Depends(READ_PACKAGING),
    session: Session = Depends(db_session),
) -> dict:
    items, total = PackagingService(session).list_units(
        user,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        status=status_filter,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.get(
    "/packaging-units/mine",
    response_model=ApiResponse[PackagingUnitRead],
    summary="My packaging unit",
    description=(
        "The facility the signed-in packaging-unit account works for. This is the unit every run "
        "it opens is recorded against, so the workspace never has to ask which one to use. An "
        "account that has not been attached to a facility is told exactly that, and that an "
        "administrator attaches it."
    ),
)
def my_packaging_unit(
    user: User = Depends(READ_PACKAGING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(PackagingService(session).my_unit(user))


@router.post(
    "/packaging-units",
    response_model=ApiResponse[PackagingUnitRead],
    status_code=201,
    summary="Register a packaging unit",
    description="Registers a facility with a server-issued code (``HC-PKUNIT-000001``).",
)
def create_packaging_unit(
    payload: PackagingUnitCreate,
    user: User = Depends(MANAGE_UNITS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(PackagingService(session).create_unit(user, payload))


@router.patch(
    "/packaging-units/{unit_id}",
    response_model=ApiResponse[PackagingUnitRead],
    summary="Update a packaging unit",
    description="Corrects a facility's details or retires it (``status`` = INACTIVE).",
)
def update_packaging_unit(
    unit_id: uuid.UUID,
    payload: PackagingUnitUpdate,
    user: User = Depends(MANAGE_UNITS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(PackagingService(session).update_unit(user, unit_id, payload))


@router.post(
    "/packaging-units/{unit_id}/members",
    response_model=ApiResponse[PackagingUnitRead],
    summary="Attach an account to a packaging unit",
    description=(
        "Puts a packaging-unit account to work at a facility. Administrator-only: which "
        "organisation an operator works for is not the operator's choice, and a run recorded "
        "against the wrong unit is a false record about real honey."
    ),
)
def attach_packaging_unit_member(
    unit_id: uuid.UUID,
    payload: PackagingUnitMemberChange,
    user: User = Depends(MANAGE_UNITS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(PackagingService(session).attach_member(user, unit_id, payload))


@router.delete(
    "/packaging-units/{unit_id}/members/{member_id}",
    response_model=ApiResponse[PackagingUnitRead],
    summary="Detach an account from a packaging unit",
    description=(
        "Takes an account off a facility. The account itself is untouched — it simply has no "
        "facility until an administrator attaches it to one."
    ),
)
def detach_packaging_unit_member(
    unit_id: uuid.UUID,
    member_id: uuid.UUID,
    user: User = Depends(MANAGE_UNITS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(PackagingService(session).detach_member(user, unit_id, member_id))


# --------------------------------------------------------------------------- #
# Dashboard and worklist
# --------------------------------------------------------------------------- #
@router.get(
    "/packaging/summary",
    response_model=ApiResponse[PackagingSummary],
    summary="Packaging counters",
    description=(
        "Counters for the packaging dashboard, counted from the stored records: approved batches "
        "waiting, runs under way, packages created, released, in distribution and delivered."
    ),
)
def packaging_summary(
    user: User = Depends(READ_PACKAGING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(PackagingService(session).summary(user))


@router.get(
    "/packaging/approved-batches",
    response_model=ApiResponse[list[ApprovedBatchItem]],
    summary="Approved batches waiting to be packed",
    description=(
        "The packaging unit's worklist: laboratory-approved batches with their quantities — "
        "collected, processing output, approved, already packaged and remaining. Rejected and "
        "inconclusive batches are never returned, because the query asks for the approved status. "
        "This is a queue for the people who do the packing, so a read-only role (a beekeeper "
        "following their own honey, or an officer reading a cluster) is refused here and reads the "
        "same records through the batch timeline and the package register instead."
    ),
)
def approved_batches(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120),
    include_packed: bool = Query(
        default=True, description="Include batches whose approved quantity is already fully packed."
    ),
    user: User = Depends(WRITE_PACKAGING),
    session: Session = Depends(db_session),
) -> dict:
    items, total = PackagingService(session).approved_batches(
        user,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        include_packed=include_packed,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


# --------------------------------------------------------------------------- #
# Packaging runs
# --------------------------------------------------------------------------- #
@router.get(
    "/packaging",
    response_model=ApiResponse[list[PackagingListItem]],
    summary="List packaging runs",
    description="Packaging records in the caller's scope, newest first, paginated.",
)
def list_packaging(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120),
    status_filter: PackagingStatus | None = Query(default=None, alias="status"),
    batch_id: uuid.UUID | None = Query(default=None),
    cluster_id: uuid.UUID | None = Query(
        default=None, description="Only the packing done for one KVIC cluster."
    ),
    user: User = Depends(READ_PACKAGING),
    session: Session = Depends(db_session),
) -> dict:
    items, total = PackagingService(session).list_packaging(
        user,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        status_filter=status_filter,
        batch_id=batch_id,
        cluster_id=cluster_id,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.post(
    "/packaging",
    response_model=ApiResponse[PackagingDetail],
    status_code=201,
    summary="Open a packaging run",
    description=(
        "Opens a run against a laboratory-approved batch. A rejected, inconclusive or untested "
        "batch is refused, as is a quantity greater than the batch has left to pack."
    ),
)
def create_packaging(
    payload: PackagingCreate,
    user: User = Depends(WRITE_PACKAGING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(PackagingService(session).create_packaging(user, payload))


@router.get(
    "/packaging/{packaging_id}",
    response_model=ApiResponse[PackagingDetail],
    summary="One packaging run",
    description=(
        "The run, its batch, the quantity breakdown on the batch and the packages it produced. "
        "The batch reference is the same record the rest of the chain reads."
    ),
)
def get_packaging(
    packaging_id: uuid.UUID,
    user: User = Depends(READ_PACKAGING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(PackagingService(session).get_packaging(user, packaging_id))


@router.patch(
    "/packaging/{packaging_id}",
    response_model=ApiResponse[PackagingDetail],
    summary="Update a packaging run",
    description="Corrects an open run. A completed run is history and cannot be rewritten.",
)
def update_packaging(
    packaging_id: uuid.UUID,
    payload: PackagingUpdate,
    user: User = Depends(WRITE_PACKAGING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(PackagingService(session).update_packaging(user, packaging_id, payload))


@router.post(
    "/packaging/{packaging_id}/start",
    response_model=ApiResponse[PackagingDetail],
    summary="Start a packaging run",
    description="Marks packing as under way. Only a PENDING run may start.",
)
def start_packaging(
    packaging_id: uuid.UUID,
    user: User = Depends(WRITE_PACKAGING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(PackagingService(session).start_packaging(user, packaging_id))


@router.post(
    "/packaging/{packaging_id}/complete",
    response_model=ApiResponse[PackagingDetail],
    summary="Complete a packaging run",
    description=(
        "Checks the quantities, creates one row per package with its own stable code, and moves "
        "the batch to PACKAGED. The package size and count must add up to the packaged quantity."
    ),
)
def complete_packaging(
    packaging_id: uuid.UUID,
    payload: PackagingComplete,
    user: User = Depends(WRITE_PACKAGING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(PackagingService(session).complete_packaging(user, packaging_id, payload))


@router.post(
    "/packaging/{packaging_id}/cancel",
    response_model=ApiResponse[PackagingDetail],
    summary="Cancel a packaging run",
    description=(
        "Abandons a run that never completed. No packages were created, so no quantity of the "
        "batch is consumed and the honey stays available to pack."
    ),
)
def cancel_packaging(
    packaging_id: uuid.UUID,
    payload: PackagingCancel,
    user: User = Depends(WRITE_PACKAGING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(PackagingService(session).cancel_packaging(user, packaging_id, payload))


@router.post(
    "/packaging/{packaging_id}/release",
    response_model=ApiResponse[list[PackageListItem]],
    summary="Release every package of a run",
    description="Releases the packages a completed run produced, so they can be shipped.",
)
def release_packaging_packages(
    packaging_id: uuid.UUID,
    user: User = Depends(WRITE_PACKAGING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(PackagingService(session).release_packaging_packages(user, packaging_id))


# --------------------------------------------------------------------------- #
# Packages
# --------------------------------------------------------------------------- #
@router.get(
    "/packages",
    response_model=ApiResponse[list[PackageListItem]],
    summary="List packages",
    description=(
        "The package register in the caller's scope, newest first. Each row carries how much of "
        "the package has been shipped and what is left, computed from the shipment records."
    ),
)
def list_packages(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120),
    status_filter: PackageStatus | None = Query(default=None, alias="status"),
    batch_id: uuid.UUID | None = Query(default=None),
    packaging_id: uuid.UUID | None = Query(default=None),
    cluster_id: uuid.UUID | None = Query(
        default=None, description="Only the packages made for one KVIC cluster."
    ),
    user: User = Depends(READ_PACKAGING),
    session: Session = Depends(db_session),
) -> dict:
    items, total = PackagingService(session).list_packages(
        user,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        status_filter=status_filter,
        batch_id=batch_id,
        packaging_id=packaging_id,
        cluster_id=cluster_id,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.get(
    "/packages/{package_id}",
    response_model=ApiResponse[PackageDetail],
    summary="One package",
    description=(
        "The package with the whole chain behind it — batch, collection, hives, beekeeper and "
        "cluster — assembled from the stored records on every read."
    ),
)
def get_package(
    package_id: uuid.UUID,
    user: User = Depends(READ_PACKAGING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(PackagingService(session).get_package(user, package_id))


@router.post(
    "/packages/{package_id}/release",
    response_model=ApiResponse[PackageDetail],
    summary="Release a package",
    description="Releases one freshly created package for distribution.",
)
def release_package(
    package_id: uuid.UUID,
    payload: PackageRelease,
    user: User = Depends(WRITE_PACKAGING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(PackagingService(session).release_package(user, package_id, payload))


@router.get(
    "/batches/{batch_id}/packages",
    response_model=ApiResponse[list[PackageListItem]],
    summary="The packages of a batch",
    description="Every package produced from one batch, newest first — the same order the package register reads in.",
)
def batch_packages(
    batch_id: uuid.UUID,
    user: User = Depends(READ_PACKAGING),
    session: Session = Depends(db_session),
) -> dict:
    items, total = PackagingService(session).list_packages(
        user, page=1, page_size=100, batch_id=batch_id
    )
    return paginated(items, total_items=total, page=1, page_size=100)
