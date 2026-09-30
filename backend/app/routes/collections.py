"""Collection routes — the beekeeper's harvest record.

No business rule lives in this file. Each endpoint resolves the caller, hands the
call to :class:`~app.services.collection_service.CollectionService` and wraps the
result in the standard envelope. Ownership, cluster inheritance, code generation,
AI snapshots and the collection → batch transaction are all decided in the
service, where they can be tested without HTTP and cannot be bypassed by another
route.

``/complete`` is the important one: it returns the batch as well as the
collection, and reports ``batch_created: false`` when the harvest was already
complete — so a client that retries a completion is told exactly what happened
rather than being handed a second batch.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import db_session
from app.core.permissions import Permission, require_any_permission, require_permission
from app.models.enums import CollectionStatus
from app.models.user import User
from app.schemas.batch import BatchListItem
from app.schemas.collection import (
    CollectionCancel,
    CollectionComplete,
    CollectionCreate,
    CollectionDetail,
    CollectionListItem,
    CollectionSummary,
    CollectionUpdate,
    EligibleHiveList,
)
from app.schemas.common import ApiResponse, Meta, PaginationParams, ok, paginated
from app.services.collection_service import CollectionService

router = APIRouter(prefix="/collections", tags=["Collections"])

#: Reading a harvest: a beekeeper reads their own, staff read within their scope.
READ_COLLECTIONS = require_any_permission(
    Permission.COLLECTION_READ_SELF, Permission.COLLECTION_READ_ALL
)
#: Recording, correcting, completing and cancelling are the beekeeper's own acts.
WRITE_COLLECTIONS = require_permission(Permission.COLLECTION_WRITE_SELF)


@router.get(
    "/eligible-hives",
    response_model=ApiResponse[EligibleHiveList],
    summary="Hives available for harvesting",
    description=(
        "The caller's own hives that can be harvested, with the AI estimate and latest "
        "reading available for each. Returns an explicit empty list when there are none."
    ),
)
def list_eligible_hives(
    include_all_statuses: bool = Query(
        default=False,
        description="Include hives under maintenance or retired. They cannot be harvested.",
    ),
    user: User = Depends(READ_COLLECTIONS),
    session: Session = Depends(db_session),
) -> dict:
    data = CollectionService(session).eligible_hives(user, include_all_statuses=include_all_statuses)
    return ok(data)


@router.get(
    "/summary",
    response_model=ApiResponse[CollectionSummary],
    summary="Collection counters",
    description="Counts and harvested totals for the caller's scope, counted from stored rows.",
)
def collection_summary(
    user: User = Depends(READ_COLLECTIONS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(CollectionService(session).summary(user))


@router.get(
    "",
    response_model=ApiResponse[list[CollectionListItem]],
    summary="List collections",
    description=(
        "Paginated harvest listing. A beekeeper sees only their own; a cluster officer "
        "sees the beekeepers of the clusters they oversee; an administrator sees all. "
        "Filters narrow the caller's scope and can never widen it."
    ),
)
def list_collections(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120, description="Collection code or notes."),
    status_filter: CollectionStatus | None = Query(default=None, alias="status"),
    beekeeper_id: uuid.UUID | None = Query(default=None, description="Administrators only."),
    cluster_id: uuid.UUID | None = Query(default=None),
    hive_id: uuid.UUID | None = Query(default=None, description="Harvests that drew on this hive."),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    has_batch: bool | None = Query(
        default=None, description="true → completed harvests, false → still open."
    ),
    user: User = Depends(READ_COLLECTIONS),
    session: Session = Depends(db_session),
) -> dict:
    items, total = CollectionService(session).list_collections(
        user,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        status_filter=status_filter,
        beekeeper_id=beekeeper_id,
        cluster_id=cluster_id,
        hive_id=hive_id,
        date_from=date_from,
        date_to=date_to,
        has_batch=has_batch,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.post(
    "",
    response_model=ApiResponse[CollectionDetail],
    status_code=201,
    summary="Record a collection",
    description=(
        "Records a harvest. The beekeeper and cluster are taken from the authenticated "
        "account's current relationship — they are not, and cannot be, request fields. "
        "Repeating a request with the same client_reference returns the stored collection "
        "instead of recording the harvest twice."
    ),
)
def create_collection(
    payload: CollectionCreate,
    user: User = Depends(WRITE_COLLECTIONS),
    session: Session = Depends(db_session),
) -> dict:
    detail, reused = CollectionService(session).create(user, payload)
    return ok(detail, meta=Meta(reused=reused))


@router.get(
    "/{collection_id}",
    response_model=ApiResponse[CollectionDetail],
    summary="Get a collection",
    description="The harvest, its source hives, the AI estimate captured with it, and IoT context.",
)
def get_collection(
    collection_id: uuid.UUID,
    user: User = Depends(READ_COLLECTIONS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(CollectionService(session).get_collection(user, collection_id))


@router.patch(
    "/{collection_id}",
    response_model=ApiResponse[CollectionDetail],
    summary="Correct an open collection",
    description=(
        "Changes the source hives, date, quantity, unit or notes of a harvest that is still "
        "PLANNED or IN_PROGRESS. A completed or cancelled harvest is history and is refused."
    ),
)
def update_collection(
    collection_id: uuid.UUID,
    payload: CollectionUpdate,
    user: User = Depends(WRITE_COLLECTIONS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(CollectionService(session).update(user, collection_id, payload))


@router.post(
    "/{collection_id}/complete",
    response_model=ApiResponse[CollectionDetail],
    summary="Complete a collection and create its batch",
    description=(
        "Marks the harvest complete and creates the single honey batch it produces, in one "
        "transaction. Retrying a completion returns the existing batch — the meta field "
        "batch_created is false and no second batch is written."
    ),
)
def complete_collection(
    collection_id: uuid.UUID,
    payload: CollectionComplete | None = None,
    user: User = Depends(WRITE_COLLECTIONS),
    session: Session = Depends(db_session),
) -> dict:
    service = CollectionService(session)
    detail, batch, created = service.complete(user, collection_id, payload)
    return ok(
        detail,
        meta=Meta(
            batch_created=created,
            batch={
                "id": str(batch.id),
                "batch_code": batch.batch_code,
                "status": str(batch.status),
            },
        ),
    )


@router.post(
    "/{collection_id}/cancel",
    response_model=ApiResponse[CollectionDetail],
    summary="Cancel a collection",
    description=(
        "Cancels a harvest that did not happen. A cancelled collection can never be completed "
        "and can never produce a batch."
    ),
)
def cancel_collection(
    collection_id: uuid.UUID,
    payload: CollectionCancel | None = None,
    user: User = Depends(WRITE_COLLECTIONS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(CollectionService(session).cancel(user, collection_id, payload))


@router.get(
    "/{collection_id}/batch",
    response_model=ApiResponse[BatchListItem | None],
    summary="The batch a collection produced",
    description=(
        "The batch created from this harvest, addressed through the collection. While the "
        "harvest is still open there is no batch to report: data is omitted (the envelope "
        "never carries a null payload) and meta.batch_exists is false. An open harvest has "
        "produced no batch yet, which is a fact rather than an error."
    ),
)
def collection_batch(
    collection_id: uuid.UUID,
    user: User = Depends(READ_COLLECTIONS),
    session: Session = Depends(db_session),
) -> dict:
    service = CollectionService(session)
    collection = service.get_collection(user, collection_id)
    batch = service.batches.get_by_collection(collection.id)
    if batch is None:
        return ok(None, meta=Meta(batch_exists=False, collection_code=collection.collection_code))
    return ok(
        service.batch_list_item(batch),
        meta=Meta(batch_exists=True, collection_code=collection.collection_code),
    )


__all__ = ["router"]
