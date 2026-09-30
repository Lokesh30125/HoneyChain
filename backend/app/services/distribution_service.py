"""Distribution and retail receipt: moving packages, and confirming they arrived.

One shipment, one journey
-------------------------
A shipment is created naming a package, a quantity and a destination. From there
it moves through endpoints of its own — dispatch, in transit, delivery — so each
step has its own actor, its own timestamp and its own audit row. A caller never
sends a status: the field a request may carry is the *note* that goes with the
move, and the transition table decides whether the move is legal at all.

What the checks are for
-----------------------
* **Not more than exists.** A shipment may not carry more of a package than the
  package still has unshipped. Cancelled shipments consume nothing, which is what
  makes cancelling safe rather than a way to lose honey.
* **No delivery without a dispatch.** ``DELIVERED`` requires a recorded
  ``dispatched_at``; the database check constraint enforces it as well, so even a
  bug in this module cannot write the impossible state.
* **One confirmation, from the receiver.** The retailer's receipt is recorded as
  ``received_by_id`` / ``received_at`` — a distinct fact from the carrier's
  delivery — and that is what closes the package.

The batch follows its packages
------------------------------
When the first shipment of a batch leaves, the batch becomes ``DISTRIBUTION``;
when every package of the batch has been delivered *and* nothing of the approved
quantity is left unpacked, the batch becomes ``COMPLETED``. Both moves go through
``batch_lifecycle.advance``, so the map of legal moves remains the only authority
on where a batch may go.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.models.distribution import Distribution
from app.models.document_sequence import DocumentSequence
from app.models.enums import (
    DISTRIBUTION_STATUS_TRANSITIONS,
    AuditAction,
    BatchStatus,
    DistributionStatus,
    PackageStatus,
    UserRole,
)
from app.models.honey_batch import HoneyBatch
from app.models.packaging import HoneyPackage
from app.repositories.batch_repository import BatchRepository
from app.repositories.distribution_repository import DistributionRepository
from app.repositories.packaging_repository import PackageRepository
from app.repositories.user_repository import UserRepository
from app.schemas.laboratory import TraceabilityNode
from app.schemas.distribution import (
    BatchRef,
    DistributionDetail,
    DistributionListItem,
    DistributionSummary,
    PackageRef,
    RetailerRef,
    RetailerSummary,
)
from app.services import batch_lifecycle
from app.services.audit_service import AuditService
from app.services.blockchain import BlockchainService
from app.services.collection_service import CollectionService
from app.services.names import beekeeper_name, cluster_name, person_name
from app.services.packaging_service import PackagingService

logger = logging.getLogger(__name__)

#: Who may move honey. A distributor dispatches; an administrator can do the same
#: work because the platform must be operable without one of every role existing.
DISTRIBUTION_ROLES = (UserRole.DISTRIBUTOR, UserRole.ADMIN)
#: Who may read a shipment. Retailers read their own inbound only;
#: beekeepers and officers read them through their batch scope.
DISTRIBUTION_READ_ROLES = (
    UserRole.DISTRIBUTOR,
    UserRole.ADMIN,
    UserRole.RETAILER,
    UserRole.BEEKEEPER,
    UserRole.KVIC_OFFICER,
    UserRole.PACKAGING_UNIT,
)


def build_distribution_code(sequence: str, *, when: datetime | None = None) -> str:
    """``HC-DIST-<YYYY>-<NNNNNN>``, e.g. ``HC-DIST-2026-000001``."""
    year = (when or datetime.now(tz=timezone.utc)).year
    return f"HC-DIST-{year}-{sequence}"


def _label(value) -> str:
    return getattr(value, "label", None) or str(value)


def _enum_value(value) -> str | None:
    return None if value is None else str(getattr(value, "value", value))


class DistributionService:
    """Raise shipments, move them along, and let the receiving retailer confirm them."""

    def __init__(self, session) -> None:  # noqa: ANN001 - Session from the dependency
        self.session = session
        self.distributions = DistributionRepository(session)
        self.packages = PackageRepository(session)
        self.batches = BatchRepository(session)
        self.users = UserRepository(session)
        self.audit = AuditService(session)
        # Traceability events are recorded through this service, in the same
        # transaction as the record change (import at module level, below).
        self.blockchain = BlockchainService(session)
        self.collections = CollectionService(session)
        self.packaging = PackagingService(session)

    # ------------------------------------------------------------------ #
    # Permission and scope
    # ------------------------------------------------------------------ #
    def _assert_can_move(self, user, *, action: str, shipment: Distribution | None = None) -> None:
        if getattr(user, "role", None) not in DISTRIBUTION_ROLES:
            raise ForbiddenError(
                "Only a distributor may move shipments.",
                details={"action": action, "role": str(getattr(user, "role", None))},
            )
        if shipment is not None and not self._in_scope(user, shipment):
            # A distributor moves their own consignments. Somebody else's is not
            # "forbidden" so much as not there — the answer is the same 404 the
            # rest of the application gives for a record outside your scope.
            raise NotFoundError(
                f"Shipment {shipment.distribution_code} not found",
                details={"resource": "distribution", "action": action},
            )

    def _assert_can_receive(self, user, shipment: Distribution) -> None:
        """A retailer confirms receipt of their own inbound shipment; nobody else."""
        if user.role == UserRole.ADMIN:
            return
        if user.role == UserRole.RETAILER and shipment.retailer_id != user.id:
            # A shop cannot confirm a delivery that was never addressed to it, and
            # it is not told the shipment exists at all.
            raise NotFoundError(
                f"Shipment {shipment.distribution_code} not found",
                details={"resource": "distribution"},
            )
        if user.role != UserRole.RETAILER:
            raise ForbiddenError(
                "Only the retailer this shipment is addressed to may confirm receipt.",
                details={
                    "action": "shipment_receive",
                    "distribution_code": shipment.distribution_code,
                    "role": str(getattr(user, "role", None)),
                },
            )

    def _assert_can_read(self, user, shipment: Distribution) -> None:
        if self._in_scope(user, shipment):
            return
        if user.role in (UserRole.BEEKEEPER, UserRole.KVIC_OFFICER):
            # These two reach a batch through the scope they already have, so the
            # batch decides whether the shipment is theirs to see.
            self.collections.assert_record_scope(
                user, record=shipment.batch, resource="Shipment", resource_id=shipment.id
            )
            return
        # A shipment addressed to somebody else is invisible, not forbidden.
        raise NotFoundError(
            f"Shipment {shipment.distribution_code} not found",
            details={"resource": "distribution"},
        )

    def _in_scope(self, user, shipment: Distribution) -> bool:
        if user.role in (UserRole.ADMIN, UserRole.DISTRIBUTOR):
            return user.role == UserRole.ADMIN or shipment.distributor_id == user.id
        if user.role == UserRole.RETAILER:
            return shipment.retailer_id == user.id
        if user.role == UserRole.PACKAGING_UNIT:
            return True
        if user.role == UserRole.BEEKEEPER:
            try:
                return shipment.batch.beekeeper_id == self.collections.own_beekeeper(user).id
            except NotFoundError:
                return False
        if user.role == UserRole.KVIC_OFFICER:
            cluster_id = getattr(shipment.batch, "cluster_id", None)
            # A shipment off a batch with no cluster is still visible to the officer
            # who can see that batch; the missing cluster is reported, not hidden.
            return cluster_id is None or cluster_id in self.collections.officer_cluster_ids(user)
        return False

    # ------------------------------------------------------------------ #
    # Creating and listing shipments
    # ------------------------------------------------------------------ #
    def create_distribution(self, user, payload) -> DistributionDetail:
        """Raise a shipment against a released package.

        The package must be released by the packing unit first — existence is not
        readiness — and the quantity must fit in what the package still has.
        """
        self._assert_can_move(user, action="distribution_create")
        package = self._load_package(payload.package_id)

        if package.status not in (PackageStatus.READY_FOR_DISTRIBUTION, PackageStatus.IN_DISTRIBUTION):
            raise ConflictError(
                "Only a released package can be shipped.",
                details={
                    "package_code": package.package_code,
                    "package_status": str(package.status),
                    "package_status_label": _label(package.status),
                },
            )

        remaining = self._package_remaining(package)
        if payload.quantity > remaining:
            raise ValidationError(
                "The shipment is larger than what the package has left.",
                details={
                    "package_code": package.package_code,
                    "package_quantity": str(package.quantity),
                    "already_shipped": str(package.quantity - remaining),
                    "remaining_quantity": str(remaining),
                    "requested": str(payload.quantity),
                },
            )

        retailer = self._resolve_retailer(
            payload.retailer_id, getattr(payload, "retailer_email", None)
        )
        shipment = Distribution(
            distribution_code=self._next_code(),
            package_id=package.id,
            batch_id=package.batch_id,
            distributor_id=user.id,
            retailer_id=retailer.id if retailer else None,
            destination=payload.destination.strip(),
            destination_district=payload.destination_district,
            status=DistributionStatus.READY_FOR_DISPATCH,
            quantity=payload.quantity,
            unit=package.unit,
            carrier=payload.carrier,
            tracking_reference=payload.tracking_reference,
            expected_delivery_date=payload.expected_delivery_date,
            notes=payload.notes,
        )
        self.session.add(shipment)
        try:
            self.session.flush()
        except IntegrityError as exc:  # pragma: no cover - the code is issued by us
            raise ConflictError("A shipment with this code already exists") from exc

        self.audit.record(
            AuditAction.DISTRIBUTION_CREATED,
            actor=user,
            entity_type="distribution",
            entity_id=shipment.id,
            metadata={
                "distribution_code": shipment.distribution_code,
                "package_code": package.package_code,
                "batch_code": package.batch.batch_code,
                "quantity": str(shipment.quantity),
                "unit": shipment.unit,
                "destination": shipment.destination,
                "retailer_id": str(retailer.id) if retailer else None,
                "retailer_name": person_name(retailer),
                "status": str(shipment.status),
            },
            description=(
                f"Shipment {shipment.distribution_code} raised for package "
                f"{package.package_code} to {shipment.destination}"
            ),
        )
        self.blockchain.distribution_created(shipment, actor=user)
        self.session.commit()
        return self.get_distribution(user, shipment.id)

    def unassigned_shipments(self, user, *, page: int = 1, page_size: int = 20):
        """Shipments that name no retailer — recorded before a receiver was required.

        They are not deleted and not guessed at: the record stays exactly as it was
        written, and this is the list a distributor or administrator works through,
        naming the shop each one actually went to. Until then the shipment is
        nobody's inbound and the retailer it was sent to cannot confirm it.
        """
        self._assert_can_move(user, action="distribution_read_unassigned")
        # A distributor works through their own consignments; an administrator sees
        # every shipment nobody has addressed, because repairing them is an
        # administrative act. The scope is applied in the query, so a page of results
        # is a page of rows the caller may actually act on.
        rows, total = self.distributions.search(
            page=page,
            page_size=page_size,
            distributor_id=user.id if user.role == UserRole.DISTRIBUTOR else None,
            without_retailer=True,
            order_by="created_at",
        )
        return [self.to_list_item(row, user=user) for row in rows], total

    def list_distributions(
        self,
        user,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status_filter: DistributionStatus | None = None,
        statuses: list[DistributionStatus] | None = None,
        batch_id: uuid.UUID | None = None,
        retailer_id: uuid.UUID | None = None,
    ) -> tuple[list[DistributionListItem], int]:
        scoped_retailer, scoped_distributor, scoped_beekeeper = self._query_scope(user)
        if scoped_retailer is None:
            scoped_retailer = retailer_id

        rows, total = self.distributions.search(
            page=page,
            page_size=page_size,
            search=search,
            status=status_filter,
            statuses=statuses,
            batch_id=batch_id,
            retailer_id=scoped_retailer,
            distributor_id=scoped_distributor,
            beekeeper_id=scoped_beekeeper,
        )
        filtered = [row for row in rows if self._in_scope(user, row)]
        return [self.to_list_item(row, user=user) for row in filtered], (
            total if len(filtered) == len(rows) else len(filtered)
        )

    def get_distribution(self, user, distribution_id: uuid.UUID) -> DistributionDetail:
        shipment = self._load(distribution_id)
        self._assert_can_read(user, shipment)
        return self.to_detail(shipment, user=user)

    def update_distribution(self, user, distribution_id: uuid.UUID, payload) -> DistributionDetail:
        """Correct a shipment before it leaves. Once dispatched it is history."""
        shipment = self._load(distribution_id)
        self._assert_can_move(user, action="distribution_update", shipment=shipment)
        if shipment.status is not DistributionStatus.READY_FOR_DISPATCH:
            raise ConflictError(
                "A shipment can only be corrected before it is dispatched.",
                details={
                    "distribution_code": shipment.distribution_code,
                    "status": str(shipment.status),
                },
            )
        for field in (
            "destination",
            "destination_district",
            "quantity",
            "carrier",
            "tracking_reference",
            "expected_delivery_date",
            "notes",
        ):
            value = getattr(payload, field, None)
            if value is not None:
                setattr(shipment, field, value)
        if payload.retailer_id is not None or getattr(payload, "retailer_email", None):
            retailer = self._resolve_retailer(
                payload.retailer_id, getattr(payload, "retailer_email", None)
            )
            shipment.retailer_id = retailer.id if retailer else None

        remaining = self._package_remaining(self._load_package(shipment.package_id), exclude=shipment.id)
        if shipment.quantity > remaining:
            raise ValidationError(
                "The shipment is larger than what the package has left.",
                details={
                    "distribution_code": shipment.distribution_code,
                    "remaining_quantity": str(remaining),
                    "requested": str(shipment.quantity),
                },
            )
        self.session.flush()
        self.audit.record(
            AuditAction.DISTRIBUTION_UPDATED,
            actor=user,
            entity_type="distribution",
            entity_id=shipment.id,
            metadata={
                "distribution_code": shipment.distribution_code,
                "quantity": str(shipment.quantity),
                "destination": shipment.destination,
                "status": str(shipment.status),
            },
        )
        self.session.commit()
        return self.get_distribution(user, shipment.id)

    def assign_retailer(self, user, distribution_id: uuid.UUID, payload) -> DistributionDetail:
        """Name the shop a shipment was always meant for, after the fact.

        This is the repair for records written with no receiver. It never guesses:
        the shop is chosen deliberately, the account must be an active retailer, and
        nothing is overwritten — a shipment that already names a retailer is refused
        rather than reassigned, because moving an existing consignment to a different
        shop is not a repair, it is a different shipment.

        The stage does not matter: these records are typically already dispatched, so
        the act is allowed at any status and recorded as its own audited decision.
        """
        shipment = self._load(distribution_id)
        self._assert_can_move(user, action="distribution_assign_retailer", shipment=shipment)
        if shipment.retailer_id is not None:
            raise ConflictError(
                "This shipment already names a retailer. Naming a different one would "
                "move a delivery that has already been addressed.",
                details={
                    "distribution_code": shipment.distribution_code,
                    "retailer_id": str(shipment.retailer_id),
                    "retailer_name": getattr(shipment.retailer, "name", None),
                },
            )
        retailer = self._resolve_retailer(payload.retailer_id, None)
        if retailer.role is not UserRole.RETAILER:
            raise ValidationError(
                "Only a retailer account may be named as the receiver of a shipment.",
                details={
                    "field": "retailer_id",
                    "retailer_id": str(retailer.id),
                    "role": str(retailer.role),
                },
            )
        self._assert_receivable(retailer)
        shipment.retailer_id = retailer.id
        self.session.flush()
        self.audit.record(
            AuditAction.DISTRIBUTION_UPDATED,
            actor=user,
            entity_type="distribution",
            entity_id=shipment.id,
            metadata={
                "distribution_code": shipment.distribution_code,
                "repair": "assign_retailer",
                "previous_retailer_id": None,
                "retailer_id": str(retailer.id),
                "retailer_name": retailer.name,
                "status": str(shipment.status),
                "destination": shipment.destination,
                "reason": payload.reason,
            },
        )
        self.session.commit()
        return self.get_distribution(user, shipment.id)

    # ------------------------------------------------------------------ #
    # Moving a shipment
    # ------------------------------------------------------------------ #
    def dispatch(self, user, distribution_id: uuid.UUID, payload) -> DistributionDetail:
        """Record that the packages have left, and move the batch with them."""
        shipment = self._load(distribution_id)
        self._assert_can_move(user, action="shipment_dispatch", shipment=shipment)
        self._transition(shipment, DistributionStatus.DISPATCHED, action="shipment_dispatch")

        now = datetime.now(tz=timezone.utc)
        shipment.dispatched_at = now
        shipment.dispatch_date = payload.dispatch_date or date.today()
        if payload.carrier:
            shipment.carrier = payload.carrier
        if payload.tracking_reference:
            shipment.tracking_reference = payload.tracking_reference
        if payload.notes:
            shipment.notes = payload.notes

        # The package follows its shipment, and the batch follows its packages.
        package = shipment.package
        package_changed = False
        if package.status is PackageStatus.READY_FOR_DISTRIBUTION:
            package.status = PackageStatus.IN_DISTRIBUTION
            package_changed = True

        batch = shipment.batch
        previous_batch_status = batch.status
        batch_moved = False
        if batch.status is BatchStatus.PACKAGED:
            batch_lifecycle.advance(batch, BatchStatus.DISTRIBUTION, action="shipment_dispatch")
            batch_moved = True

        self.session.flush()

        self.audit.record(
            AuditAction.SHIPMENT_DISPATCHED,
            actor=user,
            entity_type="distribution",
            entity_id=shipment.id,
            metadata={
                "distribution_code": shipment.distribution_code,
                "package_code": package.package_code,
                "batch_id": str(shipment.batch_id),
                "batch_code": batch.batch_code,
                "quantity": str(shipment.quantity),
                "unit": shipment.unit,
                "destination": shipment.destination,
                "retailer_id": str(shipment.retailer_id) if shipment.retailer_id else None,
                "carrier": shipment.carrier,
                "dispatch_date": shipment.dispatch_date.isoformat(),
                "previous_batch_status": str(previous_batch_status),
                "batch_status": str(batch.status),
            },
            description=f"{shipment.distribution_code} dispatched to {shipment.destination}",
        )
        if package_changed:
            self.audit.record(
                AuditAction.PACKAGE_STATUS_CHANGED,
                actor=user,
                entity_type="package",
                entity_id=package.id,
                metadata={
                    "package_code": package.package_code,
                    "status": str(package.status),
                    "reason": "shipment dispatched",
                },
            )
        if batch_moved:
            self.audit.record(
                AuditAction.BATCH_MOVED_TO_DISTRIBUTION,
                actor=user,
                entity_type="batch",
                entity_id=batch.id,
                metadata={
                    "batch_code": batch.batch_code,
                    "distribution_code": shipment.distribution_code,
                    "previous_batch_status": str(previous_batch_status),
                    "batch_status": str(batch.status),
                },
                description=f"Batch {batch.batch_code} entered distribution",
            )
        self.blockchain.distribution_dispatched(shipment, actor=user)
        self.session.commit()
        return self.get_distribution(user, shipment.id)

    def mark_in_transit(self, user, distribution_id: uuid.UUID, payload) -> DistributionDetail:
        shipment = self._load(distribution_id)
        self._assert_can_move(user, action="shipment_in_transit", shipment=shipment)
        self._transition(shipment, DistributionStatus.IN_TRANSIT, action="shipment_in_transit")
        shipment.in_transit_at = datetime.now(tz=timezone.utc)
        if payload.notes:
            shipment.notes = payload.notes
        self.session.flush()
        self.audit.record(
            AuditAction.SHIPMENT_IN_TRANSIT,
            actor=user,
            entity_type="distribution",
            entity_id=shipment.id,
            metadata={
                "distribution_code": shipment.distribution_code,
                "package_code": shipment.package.package_code,
                "batch_code": shipment.batch.batch_code,
                "status": str(shipment.status),
                "location_note": payload.notes,
            },
        )
        self.blockchain.in_transit(shipment, actor=user)
        self.session.commit()
        return self.get_distribution(user, shipment.id)

    def deliver(self, user, distribution_id: uuid.UUID, payload) -> DistributionDetail:
        """Record arrival. Refused without a dispatch, and refused twice."""
        shipment = self._load(distribution_id)
        self._assert_can_move(user, action="shipment_deliver", shipment=shipment)
        if shipment.dispatched_at is None:
            raise ConflictError(
                "A shipment cannot be delivered before it has been dispatched.",
                details={
                    "distribution_code": shipment.distribution_code,
                    "status": str(shipment.status),
                    "dispatched_at": None,
                },
            )
        self._transition(shipment, DistributionStatus.DELIVERED, action="shipment_deliver")
        shipment.delivered_at = datetime.now(tz=timezone.utc)
        if payload.notes:
            shipment.notes = payload.notes
        self._settle_package_and_batch(shipment, actor=user)
        self.session.flush()
        self.audit.record(
            AuditAction.SHIPMENT_DELIVERED,
            actor=user,
            entity_type="distribution",
            entity_id=shipment.id,
            metadata={
                "distribution_code": shipment.distribution_code,
                "package_code": shipment.package.package_code,
                "batch_code": shipment.batch.batch_code,
                "quantity": str(shipment.quantity),
                "unit": shipment.unit,
                "destination": shipment.destination,
                "status": str(shipment.status),
                "received_by_id": str(shipment.received_by_id) if shipment.received_by_id else None,
            },
        )
        self.blockchain.delivered(shipment, actor=user)
        self.session.commit()
        return self.get_distribution(user, shipment.id)

    def receive(self, user, distribution_id: uuid.UUID, payload) -> DistributionDetail:
        """The retailer confirms the shipment arrived, and in what state.

        This is the second, independent confirmation of the same journey: the
        carrier's delivery and the receiver's acceptance are different facts and
        both are kept. A receipt that arrives before any dispatch is refused.
        """
        shipment = self._load(distribution_id)
        self._assert_can_receive(user, shipment)

        if shipment.dispatched_at is None:
            raise ConflictError(
                "This shipment has not been dispatched yet, so there is nothing to receive.",
                details={
                    "distribution_code": shipment.distribution_code,
                    "status": str(shipment.status),
                },
            )

        already_received = shipment.received_by_id is not None
        if shipment.status is not DistributionStatus.DELIVERED:
            self._transition(shipment, DistributionStatus.DELIVERED, action="shipment_receive")
            shipment.delivered_at = datetime.now(tz=timezone.utc)

        if not already_received:
            # The first confirmation is the fact; a repeated click confirms it
            # again (and is audited as such) without moving the moment it happened.
            shipment.received_by_id = user.id
            shipment.received_at = datetime.now(tz=timezone.utc)
        if payload.receipt_notes or payload.notes:
            shipment.notes = payload.receipt_notes or payload.notes

        self._settle_package_and_batch(shipment, actor=user)
        self.session.flush()
        self.audit.record(
            AuditAction.PACKAGE_RECEIVED,
            actor=user,
            entity_type="distribution",
            entity_id=shipment.id,
            metadata={
                "distribution_code": shipment.distribution_code,
                "package_code": shipment.package.package_code,
                "batch_code": shipment.batch.batch_code,
                "quantity": str(shipment.quantity),
                "unit": shipment.unit,
                "status": str(shipment.status),
                "retailer_id": str(user.id),
                "retailer_name": person_name(user),
                "redelivery_confirmation": already_received,
            },
            description=(
                f"{shipment.distribution_code} received by {person_name(user) or 'the retailer'}"
            ),
        )
        # Two facts, recorded as two events when both happened here: the carrier
        # brought it, and the retailer took it in. A receipt that also completed
        # the delivery writes both — the ledger should not show a package being
        # accepted before it arrived.
        if not already_received:
            self.blockchain.delivered(shipment, actor=user)
        self.blockchain.retailer_received(shipment, actor=user)
        self.session.commit()
        return self.get_distribution(user, shipment.id)

    def cancel(self, user, distribution_id: uuid.UUID, payload) -> DistributionDetail:
        """Abandon a shipment that never left. Cancelled shipments hold no quantity."""
        shipment = self._load(distribution_id)
        self._assert_can_move(user, action="distribution_cancel", shipment=shipment)
        self._transition(shipment, DistributionStatus.CANCELLED, action="distribution_cancel")
        shipment.cancelled_at = datetime.now(tz=timezone.utc)
        if payload.reason:
            shipment.notes = payload.reason
        self.session.flush()
        self.audit.record(
            AuditAction.DISTRIBUTION_CANCELLED,
            actor=user,
            entity_type="distribution",
            entity_id=shipment.id,
            metadata={
                "distribution_code": shipment.distribution_code,
                "package_code": shipment.package.package_code,
                "batch_code": shipment.batch.batch_code,
                "reason": payload.reason,
                "status": str(shipment.status),
            },
        )
        self.session.commit()
        return self.get_distribution(user, shipment.id)

    # ------------------------------------------------------------------ #
    # Retailer views
    # ------------------------------------------------------------------ #
    def retailer_shipments(
        self,
        user,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status_filter: DistributionStatus | None = None,
        awaiting_receipt: bool = False,
    ) -> tuple[list[DistributionListItem], int]:
        """The inbound list of one retailer — their own shipments, nothing else."""
        if user.role not in (UserRole.RETAILER, UserRole.ADMIN):
            raise ForbiddenError(
                "Only a retailer may read their inbound shipments.",
                details={"role": str(getattr(user, "role", None))},
            )
        retailer_id = None if user.role == UserRole.ADMIN else user.id
        rows, total = self.distributions.search(
            page=page,
            page_size=page_size,
            search=search,
            status=status_filter,
            retailer_id=retailer_id,
            awaiting_receipt=awaiting_receipt,
            require_retailer=True,
        )
        return [self.to_list_item(row, user=user) for row in rows], total

    def retailer_packages(
        self,
        user,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status_filter: PackageStatus | None = None,
    ) -> tuple[list, int]:
        """The packages a retailer has received, read from the shipments addressed to them."""
        if user.role not in (UserRole.RETAILER, UserRole.ADMIN):
            raise ForbiddenError(
                "Only a retailer may read their received packages.",
                details={"role": str(getattr(user, "role", None))},
            )
        if user.role == UserRole.ADMIN:
            rows, total = self.packages.search(
                page=page, page_size=page_size, search=search, status=status_filter
            )
            return [self.packaging.to_package_item(row) for row in rows], total

        shipments = self.distributions.for_retailer(user.id)
        # Received means the shop confirmed it. A carrier's "delivered" alone is
        # still waiting for this shop's receipt and is listed as inbound instead.
        delivered_ids = [
            shipment.package_id
            for shipment in shipments
            if shipment.status is DistributionStatus.DELIVERED and shipment.received_at is not None
        ]
        package_ids = list(dict.fromkeys(delivered_ids))
        items = []
        for package_id in package_ids:
            package = self.packages.get_with_relations(package_id)
            if package is None:
                continue
            if status_filter is not None and package.status is not status_filter:
                continue
            items.append(self.packaging.to_package_item(package))
        return items, len(items)

    def _query_scope(self, user) -> tuple[uuid.UUID | None, uuid.UUID | None, uuid.UUID | None]:
        """(retailer, distributor, beekeeper) the caller's shipment reads are bounded to.

        The same bounds serve the list and the counters, so a dashboard number
        and the table behind it can never describe different sets of rows.
        """
        if user.role == UserRole.RETAILER:
            return user.id, None, None
        if user.role == UserRole.DISTRIBUTOR:
            return None, user.id, None
        if user.role == UserRole.BEEKEEPER:
            try:
                return None, None, self.collections.own_beekeeper(user).id
            except NotFoundError:
                # No beekeeper record: nothing of theirs can be on the road.
                return None, None, uuid.UUID(int=0)
        return None, None, None

    def summary(self, user) -> DistributionSummary:
        retailer_id, distributor_id, beekeeper_id = self._query_scope(user)
        counts = self.distributions.count_by_status(
            retailer_id=retailer_id, distributor_id=distributor_id, beekeeper_id=beekeeper_id
        )
        return DistributionSummary(
            total=sum(counts.values()),
            by_status=counts,
            ready_for_dispatch=counts.get(DistributionStatus.READY_FOR_DISPATCH.value, 0),
            dispatched=counts.get(DistributionStatus.DISPATCHED.value, 0),
            in_transit=counts.get(DistributionStatus.IN_TRANSIT.value, 0),
            delivered=counts.get(DistributionStatus.DELIVERED.value, 0),
            cancelled=counts.get(DistributionStatus.CANCELLED.value, 0),
        )

    def retailer_summary(self, user) -> RetailerSummary:
        if user.role not in (UserRole.RETAILER, UserRole.ADMIN):
            raise ForbiddenError(
                "Only a retailer may read their own summary.",
                details={"role": str(getattr(user, "role", None))},
            )
        rows = (
            self.distributions.for_retailer(user.id)
            if user.role is UserRole.RETAILER
            else []
        )
        by_status: dict[str, int] = {}
        quantity = Decimal("0")
        unit = None
        received_rows = [
            shipment
            for shipment in rows
            if shipment.status is DistributionStatus.DELIVERED and shipment.received_at is not None
        ]
        for shipment in rows:
            key = str(shipment.status)
            by_status[key] = by_status.get(key, 0) + 1
        for shipment in received_rows:
            quantity += shipment.quantity
            unit = shipment.unit
        # "Received" is the shop's own confirmation; everything addressed to the
        # shop and not yet confirmed — including a carrier-delivered shipment — is
        # still on its way as far as the shop's records are concerned.
        delivered = len(received_rows)
        open_shipments = sum(
            1
            for shipment in rows
            if shipment.status is not DistributionStatus.CANCELLED and shipment.received_at is None
        )
        packages = len({shipment.package_id for shipment in received_rows})
        return RetailerSummary(
            inbound=open_shipments,
            delivered=delivered,
            packages_received=packages,
            quantity_received=quantity,
            unit=unit,
            by_status=by_status,
        )

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _load(self, distribution_id: uuid.UUID) -> Distribution:
        shipment = self.distributions.get_with_relations(distribution_id)
        if shipment is None:
            raise NotFoundError(
                f"Shipment {distribution_id} not found", details={"resource": "distribution"}
            )
        return shipment

    def _load_package(self, package_id: uuid.UUID) -> HoneyPackage:
        package = self.packages.get_with_relations(package_id)
        if package is None:
            raise NotFoundError(
                f"Package {package_id} not found", details={"resource": "package"}
            )
        return package

    def _resolve_retailer(self, retailer_id: uuid.UUID | None, retailer_email: str | None = None):
        """The shop a shipment is addressed to, named by account or by email.

        A distributor cannot list user accounts — and should not be able to — so a
        shipment may name its receiver by the email the shop signs in with. Both
        routes end in the same check: the account must exist and must be a
        retailer, because only a retailer account can confirm a receipt. The
        refusal does not say which of the two failed, so it cannot be used to
        probe who has an account.
        """
        if retailer_id is not None and retailer_email:
            raise ValidationError(
                "Name the receiving retailer by account id or by email, not both.",
                details={"fields": ["retailer_id", "retailer_email"]},
            )
        if retailer_email:
            retailer = self.users.get_by_email(retailer_email)
            if retailer is None or retailer.role is not UserRole.RETAILER:
                raise ValidationError(
                    "No retailer account is registered with that email address.",
                    details={"field": "retailer_email"},
                )
            return self._assert_receivable(retailer)
        if retailer_id is None:
            raise ValidationError(
                "Name the retailer this shipment is for. A shipment addressed to nobody "
                "cannot be received by anybody.",
                details={"field": "retailer_id"},
            )
        retailer = self.users.get(retailer_id)
        if retailer is None:
            raise NotFoundError(
                f"Retailer {retailer_id} not found", details={"resource": "user"}
            )
        if retailer.role is not UserRole.RETAILER:
            raise ValidationError(
                "A shipment can only be addressed to a retailer account.",
                details={"user_id": str(retailer_id), "role": str(retailer.role)},
            )
        return self._assert_receivable(retailer)

    def _assert_receivable(self, retailer):
        """A shipment may only be addressed to a shop that can take delivery.

        A deactivated account still exists — its history is intact — but it cannot
        sign in, so it cannot confirm a receipt, and a shipment sent to one would sit
        in transit for ever. The refusal says exactly that.
        """
        if not getattr(retailer, "is_active", True):
            raise ValidationError(
                f"{retailer.name} is a deactivated retailer account and cannot confirm receipt. "
                "Choose an active retailer.",
                details={
                    "field": "retailer_id",
                    "retailer_id": str(retailer.id),
                    "is_active": False,
                },
            )
        return retailer

    def list_retailers(self, user) -> list[dict]:
        """The shops a shipment may be addressed to — active retailer accounts only.

        Read from the users table, so a retailer an administrator creates appears
        here at once and one they deactivate disappears, rather than either being
        typed into a form from memory. The fields are the ones a distributor
        legitimately needs to choose the right shop; no credential, token or
        contact detail beyond the organisation is returned.
        """
        rows = self.users.active_by_role(UserRole.RETAILER)
        return [
            {
                "id": row.id,
                "name": row.name,
                "email": row.email,
                "organization": getattr(row, "organization", None),
                "district": getattr(row, "district", None),
                "state": getattr(row, "state", None),
                "is_active": bool(row.is_active),
            }
            for row in rows
        ]

    def _package_remaining(
        self, package: HoneyPackage, *, exclude: uuid.UUID | None = None
    ) -> Decimal:
        shipments = self.distributions.for_package(package.id)
        moved = sum(
            (
                shipment.quantity
                for shipment in shipments
                if shipment.status is not DistributionStatus.CANCELLED
                and (exclude is None or shipment.id != exclude)
            ),
            Decimal("0"),
        )
        remaining = package.quantity - moved
        return remaining if remaining > 0 else Decimal("0")

    def _package_undelivered(self, package: HoneyPackage) -> Decimal:
        """How much of a package has not yet *arrived* anywhere.

        Unlike :meth:`_package_remaining` (what is still free to ship), this
        counts delivered shipments only: a package split over two shipments is
        not delivered while the second is still in the warehouse.
        """
        shipments = self.distributions.for_package(package.id)
        arrived = sum(
            (
                shipment.quantity
                for shipment in shipments
                if shipment.status is DistributionStatus.DELIVERED
            ),
            Decimal("0"),
        )
        remaining = package.quantity - arrived
        return remaining if remaining > 0 else Decimal("0")

    def _transition(
        self, shipment: Distribution, target: DistributionStatus, *, action: str
    ) -> None:
        if target not in DISTRIBUTION_STATUS_TRANSITIONS.get(shipment.status, ()):
            raise ConflictError(
                f"A {_label(shipment.status).lower()} shipment cannot move to {_label(target).lower()}.",
                details={
                    "action": action,
                    "distribution_code": shipment.distribution_code,
                    "status": str(shipment.status),
                    "requested": str(target),
                },
            )
        shipment.status = target

    def _settle_package_and_batch(self, shipment: Distribution, *, actor) -> None:
        """Close the package when its honey is all delivered; then check the batch.

        A package is delivered when every unit of it has been received. A batch is
        complete when every one of its packages is delivered *and* there is no
        approved honey still waiting to be packed — a batch with an unpacked
        remainder is not finished, however much of it has shipped.
        """
        package = shipment.package
        if package.status is not PackageStatus.DELIVERED and self._package_undelivered(package) <= 0:
            package.status = PackageStatus.DELIVERED
            package.delivered_at = datetime.now(tz=timezone.utc)
            self.audit.record(
                AuditAction.PACKAGE_STATUS_CHANGED,
                actor=actor,
                entity_type="package",
                entity_id=package.id,
                metadata={
                    "package_code": package.package_code,
                    "status": str(package.status),
                    "reason": "all of the package has been received",
                },
            )

        batch = shipment.batch
        if batch.status is not BatchStatus.DISTRIBUTION:
            return
        packages = self.packages.for_batch(batch.id)
        if not packages or any(row.status is not PackageStatus.DELIVERED for row in packages):
            return
        if self.packaging.batch_quantities(batch).remaining_quantity > 0:
            return
        if self.distributions.undelivered_for_batch(batch.id):
            return
        # Delivered is the carrier's word; the chain closes on the retailer's.
        # Until every shipment of the batch has been received, the batch stays in
        # distribution — which is exactly what its timeline says.
        if any(
            row.status is not DistributionStatus.CANCELLED and row.received_at is None
            for row in self.distributions.for_batch(batch.id)
        ):
            return
        previous = batch.status
        batch_lifecycle.advance(batch, BatchStatus.COMPLETED, action="shipment_receive")
        self.session.flush()
        self.audit.record(
            AuditAction.BATCH_DISTRIBUTION_COMPLETED,
            actor=actor,
            entity_type="batch",
            entity_id=batch.id,
            metadata={
                "batch_code": batch.batch_code,
                "previous_batch_status": str(previous),
                "batch_status": str(batch.status),
                "packages": [row.package_code for row in packages],
            },
            description=f"Batch {batch.batch_code} completed distribution",
        )

    def _next_code(self) -> str:
        scope = f"DISTRIBUTION:{datetime.now(tz=timezone.utc).strftime('%Y')}"
        return build_distribution_code(DocumentSequence.next_value(self.session, scope, width=6))

    # ------------------------------------------------------------------ #
    # Serialisation
    # ------------------------------------------------------------------ #
    def to_list_item(self, shipment: Distribution, user=None) -> DistributionListItem:
        package = shipment.package
        batch = shipment.batch
        role = getattr(user, "role", None)
        is_distributor = role in DISTRIBUTION_ROLES
        is_recipient = role == UserRole.RETAILER and shipment.retailer_id == getattr(user, "id", None)
        package_remaining = self._package_remaining(package)
        return DistributionListItem(
            id=shipment.id,
            distribution_code=shipment.distribution_code,
            package_id=shipment.package_id,
            package_code=getattr(package, "package_code", ""),
            batch_id=shipment.batch_id,
            batch_code=batch.batch_code,
            collection_code=getattr(batch.collection, "collection_code", None),
            beekeeper_name=beekeeper_name(getattr(batch, "beekeeper", None)),
            beekeeper_code=getattr(getattr(batch, "beekeeper", None), "beekeeper_code", None),
            cluster_name=cluster_name(getattr(batch, "cluster", None)),
            cluster_code=getattr(getattr(batch, "cluster", None), "cluster_code", None),
            distributor_id=shipment.distributor_id,
            distributor_name=person_name(shipment.distributor),
            retailer_id=shipment.retailer_id,
            retailer_name=person_name(shipment.retailer),
            destination=shipment.destination,
            destination_district=shipment.destination_district,
            status=shipment.status,
            status_label=_label(shipment.status),
            quantity=shipment.quantity,
            unit=shipment.unit,
            unit_label=_label(shipment.unit),
            package_quantity=getattr(package, "quantity", None),
            package_remaining_quantity=package_remaining,
            carrier=shipment.carrier,
            tracking_reference=shipment.tracking_reference,
            dispatch_date=shipment.dispatch_date,
            expected_delivery_date=shipment.expected_delivery_date,
            dispatched_at=shipment.dispatched_at,
            in_transit_at=shipment.in_transit_at,
            delivered_at=shipment.delivered_at,
            received_by_id=shipment.received_by_id,
            received_at=shipment.received_at,
            received_by_name=person_name(shipment.received_by),
            cancelled_at=shipment.cancelled_at,
            notes=shipment.notes,
            created_at=shipment.created_at,
            updated_at=shipment.updated_at,
            can_dispatch=is_distributor
            and shipment.status is DistributionStatus.READY_FOR_DISPATCH,
            can_mark_in_transit=is_distributor
            and shipment.status is DistributionStatus.DISPATCHED,
            can_deliver=is_distributor
            and shipment.status in (DistributionStatus.DISPATCHED, DistributionStatus.IN_TRANSIT),
            can_receive=(
                (is_recipient or role == UserRole.ADMIN)
                and shipment.dispatched_at is not None
                and shipment.status is not DistributionStatus.CANCELLED
            ),
            can_cancel=is_distributor
            and shipment.status
            in (
                DistributionStatus.READY_FOR_DISPATCH,
                DistributionStatus.DISPATCHED,
            ),
            can_edit=is_distributor
            and shipment.status is DistributionStatus.READY_FOR_DISPATCH,
        )

    def to_detail(self, shipment: Distribution, user=None) -> DistributionDetail:
        base = self.to_list_item(shipment, user=user)
        package = shipment.package
        batch = shipment.batch
        return DistributionDetail(
            **base.model_dump(),
            package=PackageRef(
                id=package.id,
                package_code=package.package_code,
                package_size=package.package_size,
                quantity=package.quantity,
                unit=package.unit,
                unit_label=_label(package.unit),
                status=str(package.status),
                status_label=_label(package.status),
                packaging_id=package.packaging_id,
                packaging_code=getattr(package.packaging, "packaging_code", ""),
                packaging_date=package.packaging_date,
            ),
            batch=BatchRef(
                id=batch.id,
                batch_code=batch.batch_code,
                status=str(batch.status),
                status_label=batch_lifecycle.STATUS_LABEL.get(batch.status, _label(batch.status)),
                collection_code=getattr(batch.collection, "collection_code", None),
                beekeeper_id=batch.beekeeper_id,
                beekeeper_name=beekeeper_name(getattr(batch, "beekeeper", None)),
                beekeeper_code=getattr(getattr(batch, "beekeeper", None), "beekeeper_code", None),
                cluster_id=getattr(batch, "cluster_id", None),
                cluster_name=cluster_name(getattr(batch, "cluster", None)),
                cluster_code=getattr(getattr(batch, "cluster", None), "cluster_code", None),
            ),
            retailer=(
                RetailerRef(
                    id=shipment.retailer.id,
                    name=person_name(shipment.retailer),
                    email=getattr(shipment.retailer, "email", None),
                )
                if shipment.retailer is not None
                else None
            ),
            traceability=self._traceability(shipment),
            next_step=self._next_step(shipment),
        )

    def _traceability(self, shipment: Distribution):
        """Shipment → package → packaging → batch → apiary, read from the records."""
        nodes = [
            TraceabilityNode(
                kind="DISTRIBUTION",
                label="Shipment",
                identifier=shipment.distribution_code,
                detail=(
                    f"{shipment.quantity} {_label(shipment.unit)} to {shipment.destination} — "
                    f"{_label(shipment.status)}"
                ),
                recorded_at=shipment.dispatched_at or shipment.created_at,
                href=f"/api/v1/distribution/{shipment.id}",
            )
        ]
        nodes.extend(
            self.packaging.traceability_for_batch(
                shipment.batch, packaging=shipment.package.packaging, package=shipment.package
            )
        )
        return nodes

    @staticmethod
    def _next_step(shipment: Distribution) -> str | None:
        if shipment.status is DistributionStatus.READY_FOR_DISPATCH:
            return "Dispatch the shipment when it leaves, then mark it in transit."
        if shipment.status is DistributionStatus.DISPATCHED:
            return "Mark it in transit while it is moving, or record delivery on arrival."
        if shipment.status is DistributionStatus.IN_TRANSIT:
            return "The retailer confirms receipt when it arrives, which closes the package."
        if shipment.status is DistributionStatus.DELIVERED:
            return (
                "Delivered and received"
                if shipment.received_by_id
                else "Delivered — waiting for the retailer to confirm receipt"
            )
        return None
