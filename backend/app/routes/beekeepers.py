"""Beekeeper routes.

Two audiences share this prefix:

* **Beekeepers** — ``/beekeepers/me`` (read and update their own record). They
  cannot see any other beekeeper and cannot change their own verification.
* **Administrators and KVIC officers** — the directory, detail views, edits and
  the verification workflow.

Access is declared per route through the permission dependencies, so the rules
are readable at a glance and identical everywhere.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import db_session
from app.core.permissions import Permission, require_permission
from app.models.enums import VerificationStatus
from app.models.user import User
from app.schemas.beekeeper import (
    BeekeeperDetail,
    BeekeeperFilterOptions,
    BeekeeperListItem,
    BeekeeperPublic,
    BeekeeperSelfUpdate,
    BeekeeperSummary,
    BeekeeperUpdate,
    VerificationChangeRequest,
    to_beekeeper_detail,
    to_beekeeper_list_item,
    to_beekeeper_public,
)
from app.schemas.common import ApiResponse, PaginationParams, ok, paginated
from app.schemas.hive import HiveListItem
from app.services.beekeeper_service import BeekeeperService
from app.services.hive_service import HiveService

router = APIRouter(prefix="/beekeepers", tags=["Beekeepers"])


# --------------------------------------------------------------------------- #
# Self-service — declared before /{beekeeper_id} so the literal paths win
# --------------------------------------------------------------------------- #
@router.get(
    "/me",
    response_model=ApiResponse[BeekeeperPublic],
    summary="Read my beekeeper record",
    description="Only available to accounts with the BEEKEEPER role.",
)
def read_my_beekeeper_record(
    user: User = Depends(require_permission(Permission.BEEKEEPER_READ_SELF)),
    session: Session = Depends(db_session),
) -> dict:
    beekeeper = BeekeeperService(session).get_by_user(user)
    return ok(to_beekeeper_public(beekeeper))


@router.put(
    "/me",
    response_model=ApiResponse[BeekeeperPublic],
    summary="Update my beekeeper record",
    description=(
        "Apiary details and location. The beekeeper code, verification status "
        "and cluster assignment cannot be changed here — sending those fields "
        "returns 422."
    ),
)
def update_my_beekeeper_record(
    payload: BeekeeperSelfUpdate,
    user: User = Depends(require_permission(Permission.BEEKEEPER_UPDATE_SELF)),
    session: Session = Depends(db_session),
) -> dict:
    beekeeper = BeekeeperService(session).update_own(user, payload)
    return ok(to_beekeeper_public(beekeeper))



@router.get(
    "/me/hives",
    response_model=ApiResponse[list[HiveListItem]],
    summary="My hives",
    description=(
        "Every hive owned by the signed-in beekeeper, newest first and paginated. "
        "This is the same data as ``GET /api/v1/hives`` — it exists because a "
        "beekeeper's own dashboard should not have to know about hive filters — and "
        "it is scoped by the server, never by a client-supplied id."
    ),
)
def read_my_hives(
    pagination: PaginationParams = Depends(),
    status: str | None = Query(default=None, description="Filter by hive status."),
    include_removed: bool = Query(default=False),
    user: User = Depends(require_permission(Permission.HIVE_READ_SELF)),
    session: Session = Depends(db_session),
) -> dict:
    from app.models.enums import HiveStatus

    hive_status = HiveStatus(status) if status else None
    items, total = HiveService(session).list_items(
        user,
        page=pagination.page,
        page_size=pagination.page_size,
        status=hive_status,
        include_removed=include_removed,
    )
    return paginated(
        items, total_items=total, page=pagination.page, page_size=pagination.page_size
    )


# --------------------------------------------------------------------------- #
# Directory
# --------------------------------------------------------------------------- #
@router.get(
    "/filters",
    response_model=ApiResponse[BeekeeperFilterOptions],
    summary="Filter values for the beekeeper directory",
    description="Distinct districts and states actually present in the data.",
)
def beekeeper_filter_options(
    _: User = Depends(require_permission(Permission.BEEKEEPER_READ_ALL)),
    session: Session = Depends(db_session),
) -> dict:
    return ok(BeekeeperFilterOptions(**BeekeeperService(session).filter_options()))


@router.get(
    "/summary",
    response_model=ApiResponse[BeekeeperSummary],
    summary="Beekeeper counts",
    description=(
        "Aggregate counts used by the management screens. Every value is "
        "computed from the database; an empty platform reports zeros."
    ),
)
def beekeeper_summary(
    _: User = Depends(require_permission(Permission.BEEKEEPER_READ_ALL)),
    session: Session = Depends(db_session),
) -> dict:
    return ok(BeekeeperSummary(**BeekeeperService(session).summary()))


@router.get(
    "",
    response_model=ApiResponse[list[BeekeeperListItem]],
    summary="List beekeepers",
    description=(
        "Paginated beekeeper directory. Search matches the beekeeper code, "
        "name and email. Restricted to administrators and KVIC officers."
    ),
)
def list_beekeepers(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120, description="Code, name or email."),
    district: str | None = Query(default=None, max_length=80),
    state: str | None = Query(default=None, max_length=80),
    cluster: uuid.UUID | None = Query(default=None, description="Filter by KVIC cluster id."),
    verification_status: VerificationStatus | None = Query(
        default=None, description="Filter by verification state."
    ),
    bee_species: str | None = Query(default=None, max_length=80),
    _: User = Depends(require_permission(Permission.BEEKEEPER_READ_ALL)),
    session: Session = Depends(db_session),
) -> dict:
    rows, total = BeekeeperService(session).list_beekeepers(
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        district=district,
        state=state,
        cluster_id=cluster,
        verification_status=verification_status,
        bee_species=bee_species,
    )
    return paginated(
        [to_beekeeper_list_item(row) for row in rows],
        total_items=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/{beekeeper_id}",
    response_model=ApiResponse[BeekeeperDetail],
    summary="Read a beekeeper",
    description="Full record including the append-only verification history.",
)
def read_beekeeper(
    beekeeper_id: uuid.UUID,
    _: User = Depends(require_permission(Permission.BEEKEEPER_READ_ALL)),
    session: Session = Depends(db_session),
) -> dict:
    beekeeper = BeekeeperService(session).get(beekeeper_id)
    return ok(to_beekeeper_detail(beekeeper))


@router.put(
    "/{beekeeper_id}",
    response_model=ApiResponse[BeekeeperPublic],
    summary="Update a beekeeper",
    description=(
        "Officer or administrator edit, including cluster assignment. Editing "
        "another person's record is recorded in the audit log."
    ),
)
def update_beekeeper(
    beekeeper_id: uuid.UUID,
    payload: BeekeeperUpdate,
    actor: User = Depends(require_permission(Permission.BEEKEEPER_UPDATE_ALL)),
    session: Session = Depends(db_session),
) -> dict:
    beekeeper = BeekeeperService(session).update_by_officer(beekeeper_id, payload, actor=actor)
    return ok(to_beekeeper_public(beekeeper))


@router.patch(
    "/{beekeeper_id}/verification",
    response_model=ApiResponse[BeekeeperDetail],
    summary="Change a beekeeper's verification status",
    description=(
        "Moves the record through the review workflow "
        "(PENDING → UNDER_REVIEW → VERIFIED/REJECTED, VERIFIED → SUSPENDED, …). "
        "Rejections and suspensions require a remark. Every change is appended "
        "to the verification history and the audit log."
    ),
)
def change_beekeeper_verification(
    beekeeper_id: uuid.UUID,
    payload: VerificationChangeRequest,
    actor: User = Depends(require_permission(Permission.BEEKEEPER_VERIFY)),
    session: Session = Depends(db_session),
) -> dict:
    service = BeekeeperService(session)
    beekeeper = service.change_verification(
        beekeeper_id, status=payload.status, remarks=payload.remarks, actor=actor
    )
    return ok(to_beekeeper_detail(beekeeper))
