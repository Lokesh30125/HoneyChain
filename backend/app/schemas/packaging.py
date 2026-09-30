"""Request and response models for packaging units, packaging runs and packages.

The safety property of this phase lives in these models, exactly as it did in the
processing and laboratory phases: a request may name a batch, say what was
packed, how much of it and into what. It may **not** state a packaging code, a
package code, a status, an approved quantity or a package count that disagrees
with the honey. ``extra="forbid"`` turns an attempt into a 422 rather than a
field that is quietly dropped, and every status in a response was computed by
the service from the records.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.schemas.laboratory import TraceabilityNode as LaboratoryTraceabilityNode
from app.schemas.common import check_other_pair
from app.models.enums import (
    CollectionUnit,
    FacilityStatus,
    PackageStatus,
    PackagingStatus,
    PackagingType,
)

#: A packing run is bounded only to catch a typo, exactly as in processing: the
#: unit is whatever the batch was harvested in, and nothing is converted.
MAX_PACKING_QUANTITY = Decimal("1000000")
MAX_PACKAGE_SIZE = Decimal("1000000")
MAX_PACKAGE_COUNT = 100000


# --------------------------------------------------------------------------- #
# Packaging units
# --------------------------------------------------------------------------- #
class PackagingUnitCreate(BaseModel):
    """``POST /api/v1/packaging-units``.

    The facility's own identity, as an administrator registers it. The
    registration identifier is required because a packaging facility is a
    registered business and the number is how one is told from another in the
    register; where a facility genuinely has none, "Not registered" is an answer
    the form accepts and stores as what it is.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=160, examples=["HoneyChain Packaging Unit"])
    registration_identifier: str = Field(
        min_length=2,
        max_length=80,
        description="The facility's own registration number, or 'Not registered'.",
    )
    location: str | None = Field(default=None, max_length=200, examples=["Guntur"])
    address: str | None = Field(default=None, max_length=500)
    district: str | None = Field(default=None, max_length=80, examples=["Guntur"])
    state: str | None = Field(default=None, max_length=80, examples=["Andhra Pradesh"])
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=20)
    capacity_kg_per_day: Decimal | None = Field(default=None, gt=0)
    status: FacilityStatus = Field(
        default=FacilityStatus.ACTIVE,
        description="ACTIVE takes work; INACTIVE is retired and takes none.",
    )
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name", "registration_identifier")
    @classmethod
    def _trim(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 2:
            raise ValueError("This field must contain at least 2 characters")
        return cleaned


class PackagingUnitUpdate(BaseModel):
    """``PATCH /api/v1/packaging-units/{id}``."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=160)
    registration_identifier: str | None = Field(default=None, min_length=2, max_length=80)
    location: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    district: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=20)
    capacity_kg_per_day: Decimal | None = Field(default=None, gt=0)
    status: FacilityStatus | None = None
    notes: str | None = Field(default=None, max_length=2000)


class PackagingUnitMemberChange(BaseModel):
    """``POST /api/v1/packaging-units/{id}/members`` — attach an account.

    The unit is named in the path and the account in the body, so neither is
    guessed. The account must already hold the packaging-unit role: moving an
    account between facilities is an administrative act, and changing what an
    account *is* is a different one, kept on its own endpoint.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID = Field(description="An existing account holding the packaging-unit role.")
    reason: str | None = Field(default=None, max_length=500)


class PackagingUnitMemberRead(BaseModel):
    """One account working at a facility."""

    id: uuid.UUID
    name: str
    email: str
    role: str
    is_active: bool = True


class PackagingUnitRead(BaseModel):
    id: uuid.UUID
    unit_code: str
    name: str
    registration_identifier: str | None = None
    location: str | None = None
    address: str | None = None
    district: str | None = None
    state: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    capacity_kg_per_day: Decimal | None = None
    status: FacilityStatus
    status_label: str
    is_active: bool = False
    is_demo: bool = False
    notes: str | None = None
    #: Who works here, and how many runs the facility has taken. Both counted from
    #: the stored rows — an administrator deciding whether a unit is in use should
    #: not have to open anything else to find out.
    members: list[PackagingUnitMemberRead] = Field(default_factory=list)
    member_count: int = 0
    packaging_run_count: int = 0
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Packaging runs
# --------------------------------------------------------------------------- #
def _check_other_container(packaging_type, packaging_type_other) -> None:
    """The container and its description travel together: one shared rule."""
    check_other_pair(
        kind="container",
        value=packaging_type,
        other=packaging_type_other,
        other_option=PackagingType.OTHER.value,
    )


class PackagingCreate(BaseModel):
    """``POST /api/v1/packaging``.

    Only an approved batch may be named, and the server checks that rather than
    trusting the caller. The quantities are what the operator weighed; the
    package count is what they filled; the three must agree before the run is
    allowed to complete.
    """

    model_config = ConfigDict(extra="forbid")

    batch_id: uuid.UUID
    packaging_unit_id: uuid.UUID | None = None
    packaging_type: PackagingType = PackagingType.JAR
    packaging_type_other: str | None = Field(
        default=None,
        max_length=120,
        description=(
            "The container in the operator's own words. Required when `packaging_type` "
            "is OTHER, and refused otherwise."
        ),
    )
    packaging_date: date | None = Field(
        default=None, description="Defaults to today, in the server's timezone."
    )
    input_quantity: Decimal | None = Field(default=None, gt=0, le=MAX_PACKING_QUANTITY)
    packaged_quantity: Decimal | None = Field(default=None, gt=0, le=MAX_PACKING_QUANTITY)
    package_size: Decimal | None = Field(default=None, gt=0, le=MAX_PACKAGE_SIZE)
    number_of_packages: int | None = Field(default=None, gt=0, le=MAX_PACKAGE_COUNT)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("packaging_type_other")
    @classmethod
    def _trim_other(cls, value: str | None) -> str | None:
        """A description typed with padding is stored as the words themselves."""
        return value.strip() if value else None

    @model_validator(mode="after")
    def _other_matches_the_type(self):
        _check_other_container(self.packaging_type, self.packaging_type_other)
        return self

    @field_validator("packaging_date")
    @classmethod
    def _not_in_the_future(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("The packaging date cannot be in the future.")
        return value

    @model_validator(mode="after")
    def _quantities_consistent(self) -> "PackagingCreate":
        if (
            self.packaged_quantity is not None
            and self.input_quantity is not None
            and self.packaged_quantity > self.input_quantity
        ):
            raise ValueError(
                "The packaged quantity cannot be greater than the quantity taken from the batch."
            )
        return self


class PackagingUpdate(BaseModel):
    """``PATCH /api/v1/packaging/{id}`` — corrections while the run is open."""

    model_config = ConfigDict(extra="forbid")

    packaging_unit_id: uuid.UUID | None = None
    packaging_type: PackagingType | None = None
    packaging_type_other: str | None = Field(default=None, max_length=120)
    packaging_date: date | None = None
    input_quantity: Decimal | None = Field(default=None, gt=0, le=MAX_PACKING_QUANTITY)
    packaged_quantity: Decimal | None = Field(default=None, gt=0, le=MAX_PACKING_QUANTITY)
    package_size: Decimal | None = Field(default=None, gt=0, le=MAX_PACKAGE_SIZE)
    number_of_packages: int | None = Field(default=None, gt=0, le=MAX_PACKAGE_COUNT)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("packaging_type_other")
    @classmethod
    def _trim_other(cls, value: str | None) -> str | None:
        return value.strip() if value else None


class PackagingComplete(BaseModel):
    """``POST /api/v1/packaging/{id}/complete``.

    The figures may be supplied here if they were not recorded earlier; the same
    checks apply. No status is acceptable from a caller: completion is the
    server's decision once the numbers hold together.
    """

    model_config = ConfigDict(extra="forbid")

    packaged_quantity: Decimal | None = Field(default=None, gt=0, le=MAX_PACKING_QUANTITY)
    input_quantity: Decimal | None = Field(default=None, gt=0, le=MAX_PACKING_QUANTITY)
    package_size: Decimal | None = Field(default=None, gt=0, le=MAX_PACKAGE_SIZE)
    number_of_packages: int | None = Field(default=None, gt=0, le=MAX_PACKAGE_COUNT)
    notes: str | None = Field(default=None, max_length=2000)


class PackagingCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class PackagingBatchRef(BaseModel):
    """The batch a packaging run packs — the same record the rest of the chain reads."""

    id: uuid.UUID
    batch_code: str
    status: str
    status_label: str
    current_stage: str
    current_stage_label: str
    collection_id: uuid.UUID | None = None
    collection_code: str | None = None
    collection_date: date | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    beekeeper_id: uuid.UUID | None = None
    beekeeper_name: str | None = None
    beekeeper_code: str | None = None
    cluster_id: uuid.UUID | None = None
    cluster_name: str | None = None
    cluster_code: str | None = None


class PackagingQuantityBreakdown(BaseModel):
    """Where the honey stands, computed from records rather than stored twice.

    ``approved_quantity`` is the measured output of the batch's completed
    processing run — the honey that exists and passed the laboratory.
    ``packaged_quantity`` is what completed packaging runs have already put into
    packages. ``remaining_quantity`` is the difference, and it is what a new run
    may draw on.
    """

    approved_quantity: Decimal = Decimal("0")
    packaged_quantity: Decimal = Decimal("0")
    remaining_quantity: Decimal = Decimal("0")
    unit: str | None = None


class PackagingListItem(BaseModel):
    id: uuid.UUID
    packaging_code: str
    batch_id: uuid.UUID
    batch_code: str
    collection_code: str | None = None
    beekeeper_id: uuid.UUID | None = None
    beekeeper_name: str | None = None
    beekeeper_code: str | None = None
    cluster_id: uuid.UUID | None = None
    cluster_name: str | None = None
    cluster_code: str | None = None
    packaging_unit_id: uuid.UUID | None = None
    packaging_unit_code: str | None = None
    packaging_unit_name: str | None = None
    packaged_by_id: uuid.UUID | None = None
    packaged_by_name: str | None = None
    status: PackagingStatus
    status_label: str
    packaging_type: PackagingType
    packaging_type_label: str
    packaging_type_other: str | None = None
    packaging_type_display: str | None = Field(
        default=None, description="The listed container name, or the recorded one when Other."
    )
    packaging_date: date
    input_quantity: Decimal | None = None
    packaged_quantity: Decimal | None = None
    package_size: Decimal | None = None
    number_of_packages: int | None = None
    unit: str
    unit_label: str | None = None
    package_count: int = 0
    start_time: datetime | None = None
    completion_time: datetime | None = None
    cancelled_at: datetime | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    #: What this caller may do next, decided by the server from the record and
    #: the caller's role — a screen renders buttons from these flags rather than
    #: inferring permission from a status.
    can_start: bool = False
    can_complete: bool = False
    can_cancel: bool = False
    can_edit: bool = False


class PackagingPackageRef(BaseModel):
    id: uuid.UUID
    package_code: str
    sequence_number: int
    package_size: Decimal
    quantity: Decimal
    unit: str
    status: PackageStatus
    status_label: str


class PackagingDetail(PackagingListItem):
    model_config = ConfigDict(extra="forbid")

    batch: PackagingBatchRef
    quantities: PackagingQuantityBreakdown
    packages: list[PackagingPackageRef] = Field(default_factory=list)
    traceability: list["TraceabilityNode"] = Field(default_factory=list)
    next_step: str | None = None


# --------------------------------------------------------------------------- #
# Approved batches waiting to be packed
# --------------------------------------------------------------------------- #
class ApprovedBatchItem(BaseModel):
    """A batch a packaging unit may take work from — read from the batch itself."""

    batch_id: uuid.UUID
    batch_code: str
    batch_status: str
    batch_status_label: str
    collection_id: uuid.UUID | None = None
    collection_code: str | None = None
    collection_date: date | None = None
    collection_quantity: Decimal | None = None
    unit: str | None = None
    unit_label: str | None = None
    beekeeper_id: uuid.UUID | None = None
    beekeeper_name: str | None = None
    beekeeper_code: str | None = None
    cluster_id: uuid.UUID | None = None
    cluster_name: str | None = None
    cluster_code: str | None = None
    processing_id: uuid.UUID | None = None
    processing_code: str | None = None
    processing_output_quantity: Decimal | None = None
    laboratory_id: uuid.UUID | None = None
    laboratory_test_code: str | None = None
    laboratory_result: str | None = None
    laboratory_result_label: str | None = None
    approved_quantity: Decimal = Decimal("0")
    packaged_quantity: Decimal = Decimal("0")
    remaining_quantity: Decimal = Decimal("0")
    package_count: int = 0
    packaging_status: str | None = None
    packaging_status_label: str | None = None
    open_packaging_id: uuid.UUID | None = None
    open_packaging_code: str | None = None


# --------------------------------------------------------------------------- #
# Packages
# --------------------------------------------------------------------------- #
class PackageListItem(BaseModel):
    id: uuid.UUID
    package_code: str
    sequence_number: int
    batch_id: uuid.UUID
    batch_code: str
    collection_code: str | None = None
    beekeeper_name: str | None = None
    cluster_name: str | None = None
    packaging_id: uuid.UUID
    packaging_code: str
    packaging_unit_name: str | None = None
    package_size: Decimal
    quantity: Decimal
    unit: str
    unit_label: str | None = None
    packaging_type: PackagingType
    packaging_type_label: str
    packaging_type_other: str | None = None
    packaging_type_display: str | None = Field(
        default=None, description="The listed container name, or the recorded one when Other."
    )
    packaging_date: date
    status: PackageStatus
    status_label: str
    released_at: datetime | None = None
    delivered_at: datetime | None = None
    dispatched_quantity: Decimal = Decimal("0")
    remaining_quantity: Decimal = Decimal("0")
    shipment_count: int = 0
    created_at: datetime
    updated_at: datetime
    can_release: bool = False
    #: Whether the package's QR identity has been issued, and that identity. The
    #: id is derived from the package code, so it is the same on every read.
    qr_issued: bool = False
    qr_id: str | None = None
    qr_generated_at: datetime | None = None


class PackageDetail(PackageListItem):
    model_config = ConfigDict(extra="forbid")

    #: The same batch-reference shape the packaging detail uses: one description
    #: of a batch, so a package and the run that made it cannot disagree.
    batch: PackagingBatchRef
    notes: str | None = None
    traceability: list["TraceabilityNode"] = Field(default_factory=list)


class PackageRelease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str | None = Field(default=None, max_length=500)


# --------------------------------------------------------------------------- #
# Summaries and shared shapes
# --------------------------------------------------------------------------- #
class PackagingSummary(BaseModel):
    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    approved_batches: int = 0
    awaiting_packaging: int = 0
    in_progress: int = 0
    completed: int = 0
    packages_created: int = 0
    packages_ready: int = 0
    packages_in_distribution: int = 0
    packages_delivered: int = 0
    quantity_packaged: Decimal = Decimal("0")
    quantity_remaining: Decimal = Decimal("0")
    unit: str | None = None


#: The chain back to the apiary reuses the node shape the laboratory phase
#: introduced: one row per hop, each naming a real record, so a package and a
#: sample describe the same journey the same way instead of inventing a second
#: vocabulary for it.
TraceabilityNode = LaboratoryTraceabilityNode


PackagingDetail.model_rebuild()
