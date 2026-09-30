"""Hive routes — a thin HTTP layer over :class:`app.services.hive_service.HiveService`.

Authorisation is declarative (``require_any_permission``): a beekeeper reaches
these endpoints through ``HIVE_*_SELF``, staff through ``HIVE_*_ALL``, and a
consumer holds neither so the whole module answers 403 without a single role
check in a handler. The service then narrows every query to the caller's own
apiary, so knowing a hive id is never enough to read it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import db_session
from app.core.permissions import Permission, require_any_permission
from app.models.enums import ColonyStrength, HiveStatus
from app.models.user import User
from app.schemas.collection import CollectionListItem
from app.schemas.common import ApiResponse, PaginationParams, ok, paginated
from app.schemas.hive import (
    HiveClusterUpdate,
    HiveCreate,
    HiveDetail,
    HiveFilterOptions,
    HiveListItem,
    HiveStatusUpdate,
    HiveSummary,
    HiveUpdate,
)
from app.services.collection_service import CollectionService
from app.services.hive_service import HiveService

router = APIRouter(prefix="/hives", tags=["Hives"])

#: Reading the registry needs either scope; changing it needs a write scope.
READ_HIVES = require_any_permission(Permission.HIVE_READ_SELF, Permission.HIVE_READ_ALL)
WRITE_HIVES = require_any_permission(Permission.HIVE_WRITE_SELF, Permission.HIVE_WRITE_ALL)


@router.get(
    "",
    response_model=ApiResponse[list[HiveListItem]],
    summary="List hives",
    description=(
        "Hives visible to the caller: a beekeeper sees only their own, KVIC and "
        "administrators see every hive and may filter by ``beekeeper_id``. "
        "Each row carries its primary device and latest reading, if any."
    ),
)
def list_hives(
    pagination: PaginationParams = Depends(),
    status: HiveStatus | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120, description="Code, village or district."),
    district: str | None = Query(default=None, max_length=80),
    state: str | None = Query(default=None, max_length=80),
    bee_species: str | None = Query(default=None, max_length=80),
    colony_strength: ColonyStrength | None = Query(default=None),
    cluster_id: uuid.UUID | None = Query(default=None),
    beekeeper_id: uuid.UUID | None = Query(
        default=None, description="Staff only: hives belonging to one beekeeper."
    ),
    has_device: bool | None = Query(default=None, description="Only hives with/without a device."),
    has_cluster: bool | None = Query(
        default=None,
        description=(
            "Only hives with/without a KVIC cluster. `false` is the administrative worklist: "
            "hives whose owner has no cluster, and which therefore no cluster view can see yet."
        ),
    ),
    include_removed: bool = Query(default=False, description="Include retired hives."),
    actor: User = Depends(READ_HIVES),
    session: Session = Depends(db_session),
) -> dict:
    items, total = HiveService(session).list_items(
        actor,
        page=pagination.page,
        page_size=pagination.page_size,
        status=status,
        search=search,
        district=district,
        state=state,
        bee_species=bee_species,
        colony_strength=colony_strength,
        cluster_id=cluster_id,
        beekeeper_id=beekeeper_id,
        has_device=has_device,
        has_cluster=has_cluster,
        include_removed=include_removed,
    )
    return paginated(
        items, total_items=total, page=pagination.page, page_size=pagination.page_size
    )


@router.get(
    "/summary",
    response_model=ApiResponse[HiveSummary],
    summary="Hive counters",
    description="Counts by status, plus how many hives are paired with a device.",
)
def hive_summary(
    actor: User = Depends(READ_HIVES),
    session: Session = Depends(db_session),
) -> dict:
    return ok(HiveService(session).summary(actor))


@router.get(
    "/filters",
    response_model=ApiResponse[HiveFilterOptions],
    summary="Filter values present in the caller's hives",
    description="Distinct districts and species drawn from the caller's own data.",
)
def hive_filters(
    actor: User = Depends(READ_HIVES),
    session: Session = Depends(db_session),
) -> dict:
    return ok(HiveService(session).filter_options(actor))


@router.post(
    "",
    response_model=ApiResponse[HiveDetail],
    status_code=201,
    summary="Register a hive",
    description=(
        "Registers a hive under the calling beekeeper. ``hive_code`` is generated "
        "by the backend from the location district (``HIVE-GNT-00001``) and cannot "
        "be supplied or influenced by the client."
    ),
)
def create_hive(
    payload: HiveCreate,
    actor: User = Depends(WRITE_HIVES),
    session: Session = Depends(db_session),
) -> dict:
    service = HiveService(session)
    hive = service.create(actor, payload)
    return ok(service.detail(actor, hive.id))


@router.get(
    "/{hive_id}",
    response_model=ApiResponse[HiveDetail],
    summary="Read a hive",
    description="Owner, cluster, attached devices and the current sensor values.",
)
def read_hive(
    hive_id: uuid.UUID,
    actor: User = Depends(READ_HIVES),
    session: Session = Depends(db_session),
) -> dict:
    return ok(HiveService(session).detail(actor, hive_id))


@router.put(
    "/{hive_id}",
    response_model=ApiResponse[HiveDetail],
    summary="Update a hive",
    description="Partial update of the editable fields. The hive code is immutable.",
)
def update_hive(
    hive_id: uuid.UUID,
    payload: HiveUpdate,
    actor: User = Depends(WRITE_HIVES),
    session: Session = Depends(db_session),
) -> dict:
    service = HiveService(session)
    service.update(actor, hive_id, payload)
    return ok(service.detail(actor, hive_id))


@router.patch(
    "/{hive_id}/status",
    response_model=ApiResponse[HiveDetail],
    summary="Change hive status",
    description=(
        "ACTIVE / INACTIVE / MAINTENANCE / REMOVED. The previous and new status "
        "are both recorded in the audit log, along with any reason given."
    ),
)
def update_hive_status(
    hive_id: uuid.UUID,
    payload: HiveStatusUpdate,
    actor: User = Depends(WRITE_HIVES),
    session: Session = Depends(db_session),
) -> dict:
    service = HiveService(session)
    service.set_status(actor, hive_id, payload)
    return ok(service.detail(actor, hive_id))


@router.post(
    "/{hive_id}/cluster",
    response_model=ApiResponse[HiveDetail],
    summary="Place a hive in a cluster (staff only)",
    description=(
        "A beekeeper never calls this: a hive inherits the cluster of its owner's membership, "
        "and the owner cannot pick a different one. Staff use this endpoint for the two cases "
        "inheritance cannot cover — resolving a hive whose owner has no cluster, and a hive "
        "physically moved to another district. Sending `cluster_id: null` clears the placement, "
        "which is how a hive is left for administrative resolution rather than being attached "
        "to a cluster at random. Both the old and the new cluster are audited."
    ),
)
def assign_hive_cluster(
    hive_id: uuid.UUID,
    payload: HiveClusterUpdate,
    actor: User = Depends(WRITE_HIVES),
    session: Session = Depends(db_session),
) -> dict:
    service = HiveService(session)
    service.change_cluster(actor, hive_id, cluster_id=payload.cluster_id, reason=payload.reason)
    return ok(service.detail(actor, hive_id))


@router.delete(
    "/{hive_id}",

    response_model=ApiResponse[dict],
    summary="Remove a hive",
    description=(
        "A hive with devices or telemetry history is *marked* REMOVED so the data "
        "stays intact; use ``?force=true`` to do that explicitly when the check "
        "would otherwise return 409. A hive with nothing attached is deleted."
    ),
)
def delete_hive(
    hive_id: uuid.UUID,
    force: bool = Query(default=False),
    actor: User = Depends(WRITE_HIVES),
    session: Session = Depends(db_session),
) -> dict:
    return ok(HiveService(session).delete(actor, hive_id, force=force))


__all__ = ["router", "READ_HIVES", "WRITE_HIVES"]


# --------------------------------------------------------------------------- #
# Phase 5 — the harvest history of one hive
# --------------------------------------------------------------------------- #
# Read-only, and scoped exactly like every other hive read: a beekeeper sees the
# harvests of their own hives, and a hive that is not theirs is a 404 — the same
# rule the registry uses, so the two screens cannot disagree about who may look.
@router.get(
    "/{hive_id}/collections",
    response_model=ApiResponse[list[CollectionListItem]],
    summary="Harvests recorded from this hive",
    description=(
        "Every collection this hive has contributed to, newest first. Empty until the "
        "beekeeper records a harvest from it."
    ),
)
def list_hive_collections(
    hive_id: uuid.UUID,
    actor: User = Depends(READ_HIVES),
    session: Session = Depends(db_session),
) -> dict:
    items = CollectionService(session).hive_history(actor, hive_id)
    return paginated(items, total_items=len(items), page=1, page_size=max(1, len(items)))
