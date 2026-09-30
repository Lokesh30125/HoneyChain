"""Request and response models for shipments and the retailer's inbound view.

A dispatch always names a package and a quantity. It may not name a status, a
distribution code or a delivery: ``READY_FOR_DISPATCH`` is where every new
shipment starts, and the moves after that are endpoints of their own so each one
has its own actor, its own time and its own audit row.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.enums import DistributionStatus
from app.schemas.laboratory import TraceabilityNode

MAX_SHIPMENT_QUANTITY = Decimal("1000000")


# --------------------------------------------------------------------------- #
# Creating and moving a shipment
# --------------------------------------------------------------------------- #
class DistributionCreate(BaseModel):
    """``POST /api/v1/distribution``.

    Naming the receiving shop is optional because a destination may be a market
    rather than a platform account; when it is named, the shipment lands in that
    retailer's inbound list, which is what makes the receipt confirmable by the
    recipient. It may be named either way: ``retailer_id`` when the caller knows
    the account, ``retailer_email`` when it knows the shop — a distributor cannot
    list user accounts, and should not be able to.
    """

    model_config = ConfigDict(extra="forbid")

    package_id: uuid.UUID
    quantity: Decimal = Field(gt=0, le=MAX_SHIPMENT_QUANTITY)
    destination: str = Field(min_length=2, max_length=200)
    destination_district: str | None = Field(default=None, max_length=80)
    #: The shop the shipment is for, named by account. Required: a shipment
    #: addressed to nobody is delivered to nobody, and the retailer it was meant
    #: for has no way to see it or to confirm receipt. ``retailer_email`` remains
    #: supported for a caller that knows the shop by its sign-in address.
    retailer_id: uuid.UUID | None = None
    retailer_email: EmailStr | None = None
    carrier: str | None = Field(default=None, max_length=160)
    tracking_reference: str | None = Field(default=None, max_length=80)
    expected_delivery_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("expected_delivery_date")
    @classmethod
    def _not_in_the_past(cls, value: date | None) -> date | None:
        if value is not None and value < date.today():
            raise ValueError("The expected delivery date cannot be in the past.")
        return value

    @model_validator(mode="after")
    def _names_a_retailer(self):
        """Exactly one retailer, and never none.

        Checked here as well as in the service so the refusal arrives as a
        field-level 422 the form can point at, rather than as a conflict found
        halfway through writing the record.
        """
        if self.retailer_id is not None and self.retailer_email is not None:
            raise ValueError("Name the retailer by account or by email, not both.")
        if self.retailer_id is None and self.retailer_email is None:
            raise ValueError("Choose the retailer this shipment is for.")
        return self


class DistributionUpdate(BaseModel):
    """``PATCH /api/v1/distribution/{id}`` — corrections before it leaves."""

    model_config = ConfigDict(extra="forbid")

    destination: str | None = Field(default=None, min_length=2, max_length=200)
    destination_district: str | None = Field(default=None, max_length=80)
    retailer_id: uuid.UUID | None = None
    retailer_email: EmailStr | None = None
    quantity: Decimal | None = Field(default=None, gt=0, le=MAX_SHIPMENT_QUANTITY)
    carrier: str | None = Field(default=None, max_length=160)
    tracking_reference: str | None = Field(default=None, max_length=80)
    expected_delivery_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ShipmentRetailerAssign(BaseModel):
    """``POST /api/v1/distribution/{id}/assign-retailer`` — name the receiver.

    The repair for shipments recorded before a receiver was required. It is a
    separate act from correcting a shipment, because it must be possible on a
    shipment that has already left — which is precisely the state those records are
    in — and because naming a shop on an existing record is a decision that warrants
    its own audit entry rather than being folded into an edit.
    """

    model_config = ConfigDict(extra="forbid")

    retailer_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=500)


class ShipmentAction(BaseModel):
    """``POST /api/v1/distribution/{id}/{dispatch,in-transit,deliver,cancel}``.

    Every one of these is a *state change with a record*, not a status a caller
    may set: the field here is the note that goes with the move.
    """

    model_config = ConfigDict(extra="forbid")

    dispatch_date: date | None = None
    carrier: str | None = Field(default=None, max_length=160)
    tracking_reference: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=1000)
    reason: str | None = Field(default=None, max_length=500)
    #: The retailer's own note when confirming receipt.
    receipt_notes: str | None = Field(default=None, max_length=1000)


# --------------------------------------------------------------------------- #
# Reading a shipment
# --------------------------------------------------------------------------- #
class PackageRef(BaseModel):
    id: uuid.UUID
    package_code: str
    package_size: Decimal
    quantity: Decimal
    unit: str
    unit_label: str | None = None
    status: str
    status_label: str
    packaging_id: uuid.UUID
    packaging_code: str
    packaging_date: date


class BatchRef(BaseModel):
    id: uuid.UUID
    batch_code: str
    status: str
    status_label: str
    collection_code: str | None = None
    beekeeper_id: uuid.UUID | None = None
    beekeeper_name: str | None = None
    beekeeper_code: str | None = None
    cluster_id: uuid.UUID | None = None
    cluster_name: str | None = None
    cluster_code: str | None = None


class RetailerRef(BaseModel):
    id: uuid.UUID
    name: str | None = None
    email: str | None = None


class RetailerDirectoryItem(BaseModel):
    """One shop a shipment may be addressed to.

    The fields a distributor needs to pick the right one, and no others: no
    credential, no token, no contact history. Read from the users table, so the
    list is the platform's own account list rather than a copy of it.
    """

    id: uuid.UUID
    name: str
    email: str
    organization: str | None = None
    district: str | None = None
    state: str | None = None
    is_active: bool = True


class DistributionListItem(BaseModel):
    id: uuid.UUID
    distribution_code: str
    package_id: uuid.UUID
    package_code: str
    batch_id: uuid.UUID
    batch_code: str
    collection_code: str | None = None
    beekeeper_name: str | None = None
    beekeeper_code: str | None = None
    cluster_name: str | None = None
    cluster_code: str | None = None
    distributor_id: uuid.UUID
    distributor_name: str | None = None
    retailer_id: uuid.UUID | None = None
    retailer_name: str | None = None
    destination: str
    destination_district: str | None = None
    status: DistributionStatus
    status_label: str
    quantity: Decimal
    unit: str
    unit_label: str | None = None
    package_quantity: Decimal | None = None
    package_remaining_quantity: Decimal | None = None
    carrier: str | None = None
    tracking_reference: str | None = None
    dispatch_date: date | None = None
    expected_delivery_date: date | None = None
    dispatched_at: datetime | None = None
    in_transit_at: datetime | None = None
    delivered_at: datetime | None = None
    received_by_id: uuid.UUID | None = None
    received_by_name: str | None = None
    #: When the receiver confirmed it. Separate from ``delivered_at``, which is the
    #: carrier's delivery — the shop's own acceptance is a second, later fact.
    received_at: datetime | None = None
    cancelled_at: datetime | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    #: Server-computed: what this caller may do with this shipment next.
    can_dispatch: bool = False
    can_mark_in_transit: bool = False
    can_deliver: bool = False
    can_receive: bool = False
    can_cancel: bool = False
    can_edit: bool = False


class DistributionDetail(DistributionListItem):
    model_config = ConfigDict(extra="forbid")

    package: PackageRef
    batch: BatchRef
    retailer: RetailerRef | None = None
    traceability: list[TraceabilityNode] = Field(default_factory=list)
    next_step: str | None = None


class DistributionSummary(BaseModel):
    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    ready_for_dispatch: int = 0
    dispatched: int = 0
    in_transit: int = 0
    delivered: int = 0
    cancelled: int = 0
    quantity_dispatched: Decimal = Decimal("0")
    quantity_delivered: Decimal = Decimal("0")
    unit: str | None = None


class RetailerSummary(BaseModel):
    inbound: int = 0
    delivered: int = 0
    packages_received: int = 0
    quantity_received: Decimal = Decimal("0")
    unit: str | None = None
    by_status: dict[str, int] = Field(default_factory=dict)
