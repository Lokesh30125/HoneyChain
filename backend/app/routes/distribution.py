"""Distribution and retailer routes — shipments, their journey, and its receipt.

``POST /distribution`` / ``PATCH /distribution/{id}``
    Raise a shipment against a *released* package, and correct it before it leaves.
``POST /distribution/{id}/{dispatch,in-transit,deliver,cancel}``
    Move it along, one recorded step at a time. A delivery is refused unless a
    dispatch preceded it — in the service, and in a database check constraint.
``GET /distribution`` / ``GET /distribution/{id}`` / ``GET /distribution/summary``
    Read the register, one shipment with its whole provenance, and the counters.
``GET /retailer/shipments`` / ``GET /retailer/packages``
    What is inbound to, and held by, the signed-in retailer. Bounded by the
    shipments addressed to that account, not by a filter the client sends.
``POST /retailer/shipments/{id}/receive``
    The retailer's own confirmation of receipt.

Nothing here writes a status. Every endpoint performs one named act, and the
service decides from the stored record whether that act is legal.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import db_session
from app.core.permissions import Permission, require_permission
from app.models.enums import DistributionStatus, PackageStatus
from app.models.user import User
from app.schemas.common import ApiResponse, PaginationParams, ok, paginated
from app.schemas.distribution import (
    DistributionCreate,
    DistributionDetail,
    DistributionListItem,
    DistributionSummary,
    DistributionUpdate,
    RetailerDirectoryItem,
    RetailerSummary,
    ShipmentAction,
    ShipmentRetailerAssign,
)
from app.schemas.packaging import PackageListItem
from app.services.distribution_service import DistributionService

router = APIRouter(tags=["Distribution"])

READ_DISTRIBUTION = require_permission(Permission.DISTRIBUTION_READ)
WRITE_DISTRIBUTION = require_permission(Permission.DISTRIBUTION_WRITE)
RECEIVE_SHIPMENT = require_permission(Permission.SHIPMENT_RECEIVE)


# --------------------------------------------------------------------------- #
# Shipments
# --------------------------------------------------------------------------- #
@router.get(
    "/distribution/summary",
    response_model=ApiResponse[DistributionSummary],
    summary="Distribution counters",
    description="Shipments by state and the quantities dispatched and delivered.",
)
def distribution_summary(
    user: User = Depends(READ_DISTRIBUTION),
    session: Session = Depends(db_session),
) -> dict:
    return ok(DistributionService(session).summary(user))


@router.get(
    "/distribution",
    response_model=ApiResponse[list[DistributionListItem]],
    summary="List shipments",
    description=(
        "Shipments in the caller's scope: a distributor sees their own, a retailer the ones "
        "addressed to them, a beekeeper or cluster officer those of the batches they can already "
        "read. Each row carries what the caller may do next."
    ),
)
def list_distributions(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120),
    status_filter: DistributionStatus | None = Query(default=None, alias="status"),
    batch_id: uuid.UUID | None = Query(default=None),
    retailer_id: uuid.UUID | None = Query(default=None),
    user: User = Depends(READ_DISTRIBUTION),
    session: Session = Depends(db_session),
) -> dict:
    items, total = DistributionService(session).list_distributions(
        user,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        status_filter=status_filter,
        batch_id=batch_id,
        retailer_id=retailer_id,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.post(
    "/distribution",
    response_model=ApiResponse[DistributionDetail],
    status_code=201,
    summary="Raise a shipment",
    description=(
        "Creates a shipment (``READY_FOR_DISPATCH``) for a released package. A quantity larger "
        "than the package has left, or a package that is not released, is refused."
    ),
)
def create_distribution(
    payload: DistributionCreate,
    user: User = Depends(WRITE_DISTRIBUTION),
    session: Session = Depends(db_session),
) -> dict:
    return ok(DistributionService(session).create_distribution(user, payload))


@router.get(
    "/distribution/retailers",
    response_model=ApiResponse[list[RetailerDirectoryItem]],
    summary="Retailers a shipment may be addressed to",
    description=(
        "Active retailer accounts, read from the users table: the shop an administrator created "
        "appears at once and one they deactivate disappears. A distributor names the receiver from "
        "this list, because a shipment addressed to nobody reaches nobody."
    ),
)
def list_retailers(
    user: User = Depends(require_permission(Permission.RETAILER_DIRECTORY_READ)),
    session: Session = Depends(db_session),
) -> dict:
    return ok(DistributionService(session).list_retailers(user))


@router.get(
    "/distribution/unassigned",
    response_model=ApiResponse[list[DistributionListItem]],
    summary="Shipments that name no retailer",
    description=(
        "Shipments recorded before a receiver was required. They are reported rather than "
        "repaired: nothing is guessed, and the shop each one went to is named deliberately by a "
        "distributor or administrator, which is audited."
    ),
)
def list_unassigned_shipments(
    pagination: PaginationParams = Depends(),
    user: User = Depends(WRITE_DISTRIBUTION),
    session: Session = Depends(db_session),
) -> dict:
    items, total = DistributionService(session).unassigned_shipments(
        user, page=pagination.page, page_size=pagination.page_size
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.get(
    "/distribution/{distribution_id}",
    response_model=ApiResponse[DistributionDetail],
    summary="One shipment",
    description="The shipment with its package, batch and the chain back to the apiary.",
)
def get_distribution(
    distribution_id: uuid.UUID,
    user: User = Depends(READ_DISTRIBUTION),
    session: Session = Depends(db_session),
) -> dict:
    return ok(DistributionService(session).get_distribution(user, distribution_id))


@router.patch(
    "/distribution/{distribution_id}",
    response_model=ApiResponse[DistributionDetail],
    summary="Update a shipment",
    description="Corrects a shipment before it is dispatched. Afterwards it is history.",
)
def update_distribution(
    distribution_id: uuid.UUID,
    payload: DistributionUpdate,
    user: User = Depends(WRITE_DISTRIBUTION),
    session: Session = Depends(db_session),
) -> dict:
    return ok(DistributionService(session).update_distribution(user, distribution_id, payload))


@router.post(
    "/distribution/{distribution_id}/assign-retailer",
    response_model=ApiResponse[DistributionDetail],
    summary="Name the retailer on a shipment that has none",
    description=(
        "The repair for shipments recorded before a receiver was required. Works at any stage "
        "because those records are usually already dispatched, refuses a shipment that already "
        "names one, and writes its own audit entry: who named which shop, when, and why."
    ),
)
def assign_retailer(
    distribution_id: uuid.UUID,
    payload: ShipmentRetailerAssign,
    user: User = Depends(WRITE_DISTRIBUTION),
    session: Session = Depends(db_session),
) -> dict:
    return ok(
        DistributionService(session).assign_retailer(user, distribution_id, payload)
    )


@router.post(
    "/distribution/{distribution_id}/dispatch",
    response_model=ApiResponse[DistributionDetail],
    summary="Dispatch a shipment",
    description=(
        "Records that the packages left. The package becomes IN_DISTRIBUTION and the batch moves "
        "to DISTRIBUTION — the first move of the batch into the downstream half of the chain."
    ),
)
def dispatch_distribution(
    distribution_id: uuid.UUID,
    payload: ShipmentAction,
    user: User = Depends(WRITE_DISTRIBUTION),
    session: Session = Depends(db_session),
) -> dict:
    return ok(DistributionService(session).dispatch(user, distribution_id, payload))


@router.post(
    "/distribution/{distribution_id}/in-transit",
    response_model=ApiResponse[DistributionDetail],
    summary="Mark a shipment in transit",
    description="Records that a dispatched shipment is moving.",
)
def mark_in_transit(
    distribution_id: uuid.UUID,
    payload: ShipmentAction,
    user: User = Depends(WRITE_DISTRIBUTION),
    session: Session = Depends(db_session),
) -> dict:
    return ok(DistributionService(session).mark_in_transit(user, distribution_id, payload))


@router.post(
    "/distribution/{distribution_id}/deliver",
    response_model=ApiResponse[DistributionDetail],
    summary="Record delivery",
    description=(
        "Records arrival on the carrier's side. Refused unless the shipment was dispatched, and "
        "refused before its time: ``delivered_at`` cannot precede ``dispatched_at``."
    ),
)
def deliver_distribution(
    distribution_id: uuid.UUID,
    payload: ShipmentAction,
    user: User = Depends(WRITE_DISTRIBUTION),
    session: Session = Depends(db_session),
) -> dict:
    return ok(DistributionService(session).deliver(user, distribution_id, payload))


@router.post(
    "/distribution/{distribution_id}/cancel",
    response_model=ApiResponse[DistributionDetail],
    summary="Cancel a shipment",
    description=(
        "Abandons a shipment that has not been delivered. A cancelled shipment accounts for no "
        "quantity, so the package's honey becomes available to ship again."
    ),
)
def cancel_distribution(
    distribution_id: uuid.UUID,
    payload: ShipmentAction,
    user: User = Depends(WRITE_DISTRIBUTION),
    session: Session = Depends(db_session),
) -> dict:
    return ok(DistributionService(session).cancel(user, distribution_id, payload))


# --------------------------------------------------------------------------- #
# Retailer
# --------------------------------------------------------------------------- #
@router.get(
    "/retailer/summary",
    response_model=ApiResponse[RetailerSummary],
    summary="Retailer counters",
    description="What is inbound to the signed-in retailer, and what they have received.",
)
def retailer_summary(
    user: User = Depends(RECEIVE_SHIPMENT),
    session: Session = Depends(db_session),
) -> dict:
    return ok(DistributionService(session).retailer_summary(user))


@router.get(
    "/retailer/shipments",
    response_model=ApiResponse[list[DistributionListItem]],
    summary="The retailer's inbound shipments",
    description=(
        "Shipments addressed to the signed-in retailer's account. The list is bounded by the "
        "shipments themselves, so no request can widen it to somebody else's deliveries."
    ),
)
def retailer_shipments(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120),
    status_filter: DistributionStatus | None = Query(default=None, alias="status"),
    awaiting_receipt: bool = Query(
        default=False,
        description="Only shipments this shop has not confirmed yet (carrier-delivered included).",
    ),
    user: User = Depends(RECEIVE_SHIPMENT),
    session: Session = Depends(db_session),
) -> dict:
    items, total = DistributionService(session).retailer_shipments(
        user,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        status_filter=status_filter,
        awaiting_receipt=awaiting_receipt,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.get(
    "/retailer/packages",
    response_model=ApiResponse[list[PackageListItem]],
    summary="The retailer's received packages",
    description=(
        "The packages the retailer holds, read from the shipments that reached them. Each package "
        "still resolves to its own batch, collection and apiary."
    ),
)
def retailer_packages(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120),
    status_filter: PackageStatus | None = Query(default=None, alias="status"),
    user: User = Depends(RECEIVE_SHIPMENT),
    session: Session = Depends(db_session),
) -> dict:
    items, total = DistributionService(session).retailer_packages(
        user,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        status_filter=status_filter,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.post(
    "/retailer/shipments/{distribution_id}/receive",
    response_model=ApiResponse[DistributionDetail],
    summary="Confirm receipt of a shipment",
    description=(
        "The retailer's own confirmation. Refused before the shipment was dispatched, and refused "
        "for a shipment addressed to a different account. Confirming closes the package when all "
        "of its honey has arrived."
    ),
)
def receive_shipment(
    distribution_id: uuid.UUID,
    payload: ShipmentAction,
    user: User = Depends(RECEIVE_SHIPMENT),
    session: Session = Depends(db_session),
) -> dict:
    return ok(DistributionService(session).receive(user, distribution_id, payload))
