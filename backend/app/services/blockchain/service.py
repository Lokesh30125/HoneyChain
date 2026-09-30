"""The traceability service: records events, writes them to the chain, reads them back.

Three responsibilities, in the order they matter:

**Record** (``record`` and the ``*_event`` helpers) writes one row per real state
transition, inside the same transaction as the record change that produced it,
and never writes the same logical event twice. This is where a workflow module
says what happened; the payload itself is built in :mod:`.events` from the rows.

**Submit** (``submit``, ``sweep``, ``retry``) is the only thing that talks to the
blockchain service. A submission that fails leaves the event recorded and the
operational record untouched — the batch is still packaged, the shipment is
still delivered — and the row says what actually went wrong. ``sweep`` is what
makes a failure recover: it is called by the background worker every few seconds
and by the Admin "sync now" action, and it retries what is due.

**Read** (``ledger``, ``events_for_batch``, ``chain_ledger``, ``health``) answers
the Admin and KVIC ledgers and a batch's traceability from HoneyChain's own
rows, and the raw chain ledger from the service. Both are shown, labelled: the
first is what this platform wrote, the second is what the chain holds.

The public side of this module — ``ensure_qr``, ``public_trace``, ``verify`` —
is deliberately small and separate: it resolves a package code to a
customer-facing payload built from allowed fields only, and it never leaks an
actor, a note, a token or a raw telemetry value.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.blockchain import MAX_PAYLOAD_CHARACTERS, BlockchainEvent
from app.models.enums import (
    AuditAction,
    BlockchainEventType,
    BlockchainStatus,
    BatchStatus,
    DistributionStatus,
    PackageStatus,
    UserRole,
)
from app.models.honey_batch import HoneyBatch
from app.models.packaging import HoneyPackage
from app.models.user import User
from app.services.audit_service import AuditService
from app.services.blockchain import events as ev
from app.services.blockchain import qr
from app.services.blockchain.client import (
    BlockchainClient,
    BlockchainError,
    BlockchainUnavailable,
    Transaction,
    blockchain_client,
)

logger = logging.getLogger("honeychain.blockchain")

#: How many times the *worker* will retry a failed submission before it stops
#: and waits for a person. An operator can always retry by hand; the cap is what
#: stops a permanently-rejected payload from being submitted forever.
MAX_AUTO_ATTEMPTS = 8

#: Statuses whose events still exist only in HoneyChain.
OUTSTANDING = (BlockchainStatus.PENDING, BlockchainStatus.SUBMITTED, BlockchainStatus.FAILED)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class BlockchainService:
    """Traceability events for the running request or worker."""

    def __init__(self, session: Session, *, client: BlockchainClient | None = None) -> None:
        self.session = session
        self.client = client or blockchain_client()
        self.audit = AuditService(session)
        # The single reader of the supply-chain records behind every trace.
        from app.services.traceability_service import TraceabilityService

        self._trace = TraceabilityService(session)

    # ------------------------------------------------------------------ #
    # Recording — called from the workflow services, inside their transaction
    # ------------------------------------------------------------------ #
    def record(
        self,
        *,
        event_id: str,
        tx_type: BlockchainEventType,
        payload: dict[str, Any],
        batch: HoneyBatch | None = None,
        collection: Any = None,
        processing: Any = None,
        lab_test: Any = None,
        packaging: Any = None,
        package: HoneyPackage | None = None,
        distribution: Any = None,
        cluster_id: uuid.UUID | None = None,
        actor: User | None = None,
    ) -> BlockchainEvent:
        """Write one traceability event, once.

        Idempotent by ``event_id``: if the event is already recorded the existing
        row is returned and nothing is written. That is what makes the whole
        layer safe to call from a retrying workflow — the second call is a read.

        The row is flushed, not committed: it belongs to the caller's
        transaction, so an operation that fails after this point leaves no event
        claiming it happened.
        """
        if len(str(payload)) > MAX_PAYLOAD_CHARACTERS:  # pragma: no cover - guard rail
            raise ValueError(
                f"Traceability payload for {event_id} is {len(str(payload))} characters; "
                "an event is a summary, not a document."
            )

        existing = self._load_by_event_id(event_id)
        if existing is not None:
            logger.debug("traceability event already recorded", extra={"event_id": event_id})
            return existing

        resolved_cluster = cluster_id or self._cluster_of(
            batch=batch, collection=collection, packaging=packaging, package=package
        )
        # The timestamp is written here rather than left to the column default
        # on purpose. Two events recorded in one transaction — a completed
        # harvest and the batch it produced — share a database transaction, and
        # ``now()`` is the same instant for both; the order they were recorded
        # in is a real fact about what happened, so the ledger keeps it.
        recorded_at = _now()
        event = BlockchainEvent(
            created_at=recorded_at,
            updated_at=recorded_at,
            event_id=event_id,
            tx_type=tx_type,
            payload=payload,
            status=BlockchainStatus.PENDING,
            batch_id=getattr(batch, "id", None),
            batch_code=getattr(batch, "batch_code", None),
            collection_id=getattr(collection, "id", None),
            processing_id=getattr(processing, "id", None),
            lab_test_id=getattr(lab_test, "id", None),
            packaging_id=getattr(packaging, "id", None),
            package_id=getattr(package, "id", None),
            distribution_id=getattr(distribution, "id", None),
            cluster_id=resolved_cluster,
            actor_id=getattr(actor, "id", None),
        )
        try:
            with self.session.begin_nested():
                self.session.add(event)
                self.session.flush()
        except IntegrityError:
            # Two requests recorded the same logical event at the same instant.
            # The savepoint is already rolled back; the winner's row is the truth.
            logger.info("traceability event recorded concurrently", extra={"event_id": event_id})
            return self._load_by_event_id(event_id)  # type: ignore[return-value]

        logger.info(
            "traceability event recorded",
            extra={
                "event_id": event_id,
                "tx_type": str(tx_type),
                "batch_code": event.batch_code,
                "blockchain_status": str(event.status),
            },
        )
        return event

    def _load_by_event_id(self, event_id: str) -> BlockchainEvent | None:
        return self.session.execute(
            select(BlockchainEvent).where(BlockchainEvent.event_id == event_id)
        ).scalar_one_or_none()

    @staticmethod
    def _cluster_of(*, batch=None, collection=None, packaging=None, package=None) -> uuid.UUID | None:
        """The cluster to file the event under, from whichever record names one."""
        for candidate in (batch, collection, packaging, package):
            cluster_id = getattr(candidate, "cluster_id", None)
            if cluster_id is not None:
                return cluster_id
        batch_of = getattr(package, "batch", None) or getattr(packaging, "batch", None)
        return getattr(batch_of, "cluster_id", None)

    # -- One helper per event type, so a call site reads as the workflow ----- #
    def collection_completed(self, collection, *, batch=None, source_hives: Iterable[Any] = (), actor=None):
        event_id, tx_type, payload = ev.collection_completed(
            collection, batch=batch, source_hives=source_hives
        )
        return self.record(
            event_id=event_id,
            tx_type=tx_type,
            payload=payload,
            batch=batch,
            collection=collection,
            actor=actor,
        )

    def batch_created(self, batch, *, collection=None, source_hives: Iterable[Any] = (), actor=None):
        event_id, tx_type, payload = ev.batch_created(
            batch, collection=collection, source_hives=source_hives
        )
        return self.record(
            event_id=event_id, tx_type=tx_type, payload=payload, batch=batch, actor=actor
        )

    def processing_started(self, run, *, actor=None):
        event_id, tx_type, payload = ev.processing_started(run, actor=actor)
        return self.record(
            event_id=event_id,
            tx_type=tx_type,
            payload=payload,
            batch=run.batch,
            processing=run,
            actor=actor,
        )

    def processing_completed(self, run, *, actor=None):
        event_id, tx_type, payload = ev.processing_completed(run, actor=actor)
        return self.record(
            event_id=event_id,
            tx_type=tx_type,
            payload=payload,
            batch=run.batch,
            processing=run,
            actor=actor,
        )

    def lab_test_started(self, test, *, actor=None):
        event_id, tx_type, payload = ev.lab_test_started(test, actor=actor)
        return self.record(
            event_id=event_id,
            tx_type=tx_type,
            payload=payload,
            batch=test.batch,
            lab_test=test,
            processing=getattr(test, "processing", None),
            actor=actor,
        )

    def quality_decision(
        self,
        test,
        *,
        results: Iterable[Any] = (),
        actor=None,
        previous_result: str | None = None,
        is_override: bool = False,
    ):
        event_id, tx_type, payload = ev.quality_decision(
            test,
            results=results,
            actor=actor,
            previous_result=previous_result,
            is_override=is_override,
        )
        if is_override:
            # Each correction is its own fact. The plain id is keyed on the verdict
            # alone, so FAIL → PASS → FAIL would reuse the first FAIL's id and the
            # second correction would be dropped as "already recorded".
            prior = self.session.execute(
                select(func.count())
                .select_from(BlockchainEvent)
                .where(
                    BlockchainEvent.lab_test_id == test.id,
                    BlockchainEvent.tx_type.in_(
                        (
                            BlockchainEventType.QUALITY_CHECKED,
                            BlockchainEventType.QUALITY_FAILED,
                            BlockchainEventType.QUALITY_HOLD,
                        )
                    ),
                )
            ).scalar_one()
            event_id = f"{event_id}-OVERRIDE-{int(prior)}"
        return self.record(
            event_id=event_id,
            tx_type=tx_type,
            payload=payload,
            batch=test.batch,
            lab_test=test,
            actor=actor,
        )

    def proceeded_with_risk(self, test, *, actor=None, reason: str | None = None):
        event_id, tx_type, payload = ev.proceeded_with_risk(test, actor=actor, reason=reason)
        return self.record(
            event_id=event_id,
            tx_type=tx_type,
            payload=payload,
            batch=test.batch,
            lab_test=test,
            actor=actor,
        )

    def packaging_started(self, run, *, actor=None):
        event_id, tx_type, payload = ev.packaging_started(run, actor=actor)
        return self.record(
            event_id=event_id,
            tx_type=tx_type,
            payload=payload,
            batch=run.batch,
            packaging=run,
            actor=actor,
        )

    def package_created(self, package, *, run=None, actor=None):
        event_id, tx_type, payload = ev.package_created(package, run=run, actor=actor)
        return self.record(
            event_id=event_id,
            tx_type=tx_type,
            payload=payload,
            batch=package.batch,
            packaging=run or getattr(package, "packaging", None),
            package=package,
            actor=actor,
        )

    def packaged(self, run, *, actor=None, packages: Sequence[HoneyPackage] = ()):
        event_id, tx_type, payload = ev.packaged(
            run, actor=actor, package_codes=[row.package_code for row in packages]
        )
        return self.record(
            event_id=event_id,
            tx_type=tx_type,
            payload=payload,
            batch=run.batch,
            packaging=run,
            actor=actor,
        )

    def distribution_created(self, shipment, *, actor=None):
        event_id, tx_type, payload = ev.distribution_created(shipment, actor=actor)
        return self.record(
            event_id=event_id,
            tx_type=tx_type,
            payload=payload,
            batch=shipment.batch,
            package=getattr(shipment, "package", None),
            distribution=shipment,
            actor=actor,
        )

    def distribution_dispatched(self, shipment, *, actor=None):
        event_id, tx_type, payload = ev.distribution_dispatched(shipment, actor=actor)
        return self._shipment_event(shipment, event_id, tx_type, payload, actor)

    def in_transit(self, shipment, *, actor=None):
        event_id, tx_type, payload = ev.in_transit(shipment, actor=actor)
        return self._shipment_event(shipment, event_id, tx_type, payload, actor)

    def delivered(self, shipment, *, actor=None):
        event_id, tx_type, payload = ev.delivered(shipment, actor=actor)
        return self._shipment_event(shipment, event_id, tx_type, payload, actor)

    def retailer_received(self, shipment, *, actor=None):
        event_id, tx_type, payload = ev.retailer_received(shipment, actor=actor)
        return self._shipment_event(shipment, event_id, tx_type, payload, actor)

    def _shipment_event(self, shipment, event_id, tx_type, payload, actor):
        return self.record(
            event_id=event_id,
            tx_type=tx_type,
            payload=payload,
            batch=shipment.batch,
            package=getattr(shipment, "package", None),
            distribution=shipment,
            actor=actor,
        )

    def qr_generated(self, package, *, url: str, actor=None):
        event_id, tx_type, payload = ev.qr_generated(
            package, url=url, generated_at=package.qr_generated_at
        )
        return self.record(
            event_id=event_id,
            tx_type=tx_type,
            payload=payload,
            batch=package.batch,
            package=package,
            actor=actor,
        )

    def customer_qr_verified(self, package, *, verified_at: datetime, actor=None):
        event_id, tx_type, payload = ev.customer_qr_verified(
            package, scans=package.qr_scan_count, verified_at=verified_at
        )
        return self.record(
            event_id=event_id,
            tx_type=tx_type,
            payload=payload,
            batch=package.batch,
            package=package,
            actor=actor,
        )

    # ------------------------------------------------------------------ #
    # Submission
    # ------------------------------------------------------------------ #
    def submit(self, event: BlockchainEvent, *, attempts: int | None = None) -> BlockchainEvent:
        """Submit one event, with retries. Never raises for a chain problem.

        Returns the event with its status updated: ``CONFIRMED`` with the
        transaction id the service returned, or ``FAILED`` with the actual error
        it gave. The caller's operational work is unaffected either way.
        """
        if event.status is BlockchainStatus.CONFIRMED and event.tx_id:
            # Already on the ledger. Re-submitting would create a second
            # transaction for one real event, which is the thing idempotency is
            # for; the existing tx_id is reused instead.
            return event

        if not self.client.enabled:
            event.status = BlockchainStatus.SKIPPED
            event.last_error = "Blockchain integration is switched off (BLOCKCHAIN_ENABLED=false)."
            self.session.flush()
            return event

        if not self.client.configured:
            # Switched on but pointed at nothing: an installation problem, said
            # as one, with the row left retryable rather than marked confirmed.
            event.status = BlockchainStatus.FAILED
            event.last_error = "No blockchain service is configured (BLOCKCHAIN_BASE_URL)."
            event.attempt_count += 1
            self.session.flush()
            return event

        budget = attempts or max(int(self.client.settings.BLOCKCHAIN_RETRY_ATTEMPTS), 1)
        backoff_ms = max(int(self.client.settings.BLOCKCHAIN_RETRY_BACKOFF_MS), 0)
        last_error: BlockchainError | None = None

        for attempt in range(1, budget + 1):
            event.attempt_count += 1
            event.status = BlockchainStatus.SUBMITTED
            event.submitted_at = _now()
            self.session.flush()
            try:
                transaction = self.client.create_transaction(
                    tx_type=str(event.tx_type),
                    batch_id=event.batch_code or event.event_id,
                    payload=event.payload,
                )
            except BlockchainUnavailable as error:
                # Retryable: the service may be restarting or the network may
                # be down. The event stays where it is and the next attempt
                # (or the worker) tries again.
                last_error = error
                if attempt < budget and backoff_ms:
                    time.sleep(backoff_ms * attempt / 1000.0)
                continue
            except BlockchainError as error:
                # Refused, or unusable configuration: retrying the same body
                # would be refused again, so this is recorded as the outcome.
                last_error = error
                break

            event.tx_id = transaction.tx_id
            event.status = BlockchainStatus.CONFIRMED
            event.confirmed_at = _now()
            event.last_error = None
            self.session.flush()
            self.audit.record(
                AuditAction.BLOCKCHAIN_EVENT_CONFIRMED,
                actor=None,
                entity_type="blockchain_event",
                entity_id=event.id,
                metadata={
                    "event_id": event.event_id,
                    "tx_type": str(event.tx_type),
                    "tx_id": transaction.tx_id,
                    "batch_id": event.batch_code,
                },
                description=f"{event.tx_type} written to the blockchain as {transaction.tx_id}.",
            )
            return event

        event.status = BlockchainStatus.FAILED
        event.last_error = (
            f"{last_error.summary}: {last_error.message}" if last_error else "unknown error"
        )
        self.session.flush()
        self.audit.record(
            AuditAction.BLOCKCHAIN_EVENT_FAILED,
            actor=None,
            entity_type="blockchain_event",
            entity_id=event.id,
            metadata={
                "event_id": event.event_id,
                "tx_type": str(event.tx_type),
                "batch_id": event.batch_code,
                "attempts": event.attempt_count,
                "error": event.last_error,
            },
            description=(
                f"{event.tx_type} for {event.batch_code or event.event_id} could not be written "
                f"to the blockchain: {event.last_error}"
            ),
        )
        logger.warning(
            "traceability event not written to the blockchain",
            extra={
                "event_id": event.event_id,
                "tx_type": str(event.tx_type),
                "attempts": event.attempt_count,
                "error": event.last_error,
            },
        )
        return event

    def submit_and_commit(self, event: BlockchainEvent) -> BlockchainEvent:
        """Submit an event recorded by a *previous* transaction and save the result.

        Used by the worker and by an explicit retry, where the outbox row is
        already committed and only its submission state changes.
        """
        self.submit(event)
        self.session.commit()
        return event

    def sweep(self, *, limit: int | None = None, include_failed: bool = True) -> dict[str, int]:
        """Submit everything that is due, oldest first.

        Runs on a timer (the worker) and on demand (Admin → "Synchronize now").
        A successful sweep is what turns a backlog of ``PENDING`` events — the
        ones recorded while the chain was unreachable — into ``CONFIRMED`` ones.
        """
        if not self.client.enabled:
            # The integration is switched off. Nothing is submitted, and nothing
            # is left looking as though it might be: the events are marked
            # SKIPPED with the reason, so the ledger states plainly that they are
            # not on the chain. Switching the integration on later sweeps them
            # up (SKIPPED rows are picked up again), so the gap is only ever
            # temporary — and it is never a secret, because that would be the
            # kind of "recorded" claim this layer exists to avoid.
            rows = list(
                self.session.execute(
                    select(BlockchainEvent).where(BlockchainEvent.status.in_(OUTSTANDING))
                ).scalars()
            )
            for row in rows:
                row.status = BlockchainStatus.SKIPPED
                row.last_error = (
                    "Blockchain integration is switched off (BLOCKCHAIN_ENABLED=false)."
                )
            self.session.commit()
            return {
                "submitted": 0,
                "confirmed": 0,
                "failed": 0,
                "skipped": len(rows),
                "outstanding": self.outstanding_count(),
                "enabled": False,
            }

        # SKIPPED rows are included on purpose: they were recorded while the
        # integration was off, and the moment it is switched back on they are
        # exactly the events that are owed to the chain.
        statuses = [*OUTSTANDING, BlockchainStatus.SKIPPED] if include_failed else [BlockchainStatus.PENDING]
        rows = list(
            self.session.execute(
                select(BlockchainEvent)
                .where(BlockchainEvent.status.in_(statuses))
                .order_by(BlockchainEvent.created_at.asc())
                .limit(limit or int(self.client.settings.BLOCKCHAIN_OUTBOX_BATCH_SIZE))
            ).scalars()
        )
        confirmed = failed = 0
        for event in rows:
            if event.attempt_count >= MAX_AUTO_ATTEMPTS:
                # Tried often enough by the machine; it needs a person now.
                continue
            self.submit(event)
            if event.status is BlockchainStatus.CONFIRMED:
                confirmed += 1
            elif event.status is BlockchainStatus.FAILED:
                failed += 1
        self.session.commit()
        return {
            "submitted": len(rows),
            "confirmed": confirmed,
            "failed": failed,
            "skipped": 0,
            "outstanding": self.outstanding_count(),
            "enabled": True,
        }

    def retry(self, event: BlockchainEvent, *, actor: User | None = None) -> BlockchainEvent:
        """Submit one event again, at an operator's request.

        Resets the attempt counter so a row the worker had given up on gets a
        fresh budget, and records who asked.
        """
        event.attempt_count = 0
        self.audit.record(
            AuditAction.BLOCKCHAIN_EVENT_RETRIED,
            actor=actor,
            entity_type="blockchain_event",
            entity_id=event.id,
            metadata={"event_id": event.event_id, "tx_type": str(event.tx_type)},
            description=f"Blockchain submission of {event.event_id} retried by hand.",
        )
        self.submit(event)
        self.session.commit()
        return event

    # ------------------------------------------------------------------ #
    # Reads — the Admin and KVIC ledgers
    # ------------------------------------------------------------------ #
    def ledger(
        self,
        user: User,
        *,
        page: int = 1,
        page_size: int = 20,
        tx_type: BlockchainEventType | None = None,
        status: BlockchainStatus | None = None,
        batch_code: str | None = None,
        search: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        cluster_scope: Iterable[uuid.UUID] | None = None,
    ) -> tuple[list[BlockchainEvent], int]:
        """HoneyChain's traceability events, filtered in the database.

        The KVIC officer's ledger is bounded by the same cluster registry their
        batch register uses — the rows are the same rows, only the filter
        changes — and includes the events of batches that name no cluster, for
        the same reason the batch register does: a batch that has vanished from
        a cluster screen is a relationship nobody can repair.
        """
        filters = []
        if user.role is UserRole.KVIC_OFFICER:
            filters.extend(self._cluster_scope_filters(user))
        elif user.role not in (UserRole.ADMIN,):
            # Only the administrator and a cluster officer read the whole ledger.
            # Everyone else reaches the same transactions through the records
            # they are entitled to: a batch's traceability, or a package's page.
            raise PermissionError("This account may not read the blockchain ledger.")
        elif cluster_scope is not None:
            filters.append(BlockchainEvent.cluster_id.in_(list(cluster_scope)))

        if tx_type is not None:
            filters.append(BlockchainEvent.tx_type == tx_type)
        if status is not None:
            filters.append(BlockchainEvent.status == status)
        if batch_code:
            filters.append(func.upper(BlockchainEvent.batch_code) == batch_code.strip().upper())
        if search:
            term = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(BlockchainEvent.event_id).like(term),
                    func.lower(func.coalesce(BlockchainEvent.batch_code, "")).like(term),
                    func.lower(func.coalesce(BlockchainEvent.tx_id, "")).like(term),
                )
            )
        if date_from is not None:
            filters.append(BlockchainEvent.created_at >= date_from)
        if date_to is not None:
            filters.append(BlockchainEvent.created_at <= date_to)

        total = self.session.execute(
            select(func.count()).select_from(BlockchainEvent).where(*filters)
        ).scalar_one()
        rows = list(
            self.session.execute(
                select(BlockchainEvent)
                .where(*filters)
                .order_by(BlockchainEvent.created_at.desc(), BlockchainEvent.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).scalars()
        )
        return rows, int(total)

    def _cluster_scope_filters(self, user: User):
        """Events of the officer's clusters, and the unclustered ones."""
        from app.services.collection_service import CollectionService

        scope = CollectionService(self.session).officer_cluster_ids(user)
        batch_cluster = (
            select(HoneyBatch.cluster_id)
            .where(HoneyBatch.id == BlockchainEvent.batch_id)
            .scalar_subquery()
        )
        return [
            or_(
                BlockchainEvent.cluster_id.in_(scope),
                BlockchainEvent.cluster_id.is_(None),
                batch_cluster.in_(scope),
            )
        ]

    def get_event(self, user: User, event_id: uuid.UUID) -> BlockchainEvent:
        event = self.session.get(BlockchainEvent, event_id)
        if event is None:
            raise LookupError(f"Blockchain event {event_id} not found")
        if user.role is UserRole.KVIC_OFFICER:
            scope = self._cluster_scope_filters(user)
            allowed = self.session.execute(
                select(func.count())
                .select_from(BlockchainEvent)
                .where(BlockchainEvent.id == event.id, *scope)
            ).scalar_one()
            if not allowed:
                raise LookupError(f"Blockchain event {event_id} not found")
        elif user.role is not UserRole.ADMIN:
            raise PermissionError("This account may not read the blockchain ledger.")
        return event

    def events_for_batch(self, batch: HoneyBatch) -> list[BlockchainEvent]:
        """Every traceability event recorded for one batch, in the order they happened."""
        rows = list(
            self.session.execute(
                select(BlockchainEvent)
                .where(BlockchainEvent.batch_id == batch.id)
                .order_by(BlockchainEvent.created_at.asc(), BlockchainEvent.id.asc())
            ).scalars()
        )
        return rows

    def events_for_distribution(self, distribution_id: uuid.UUID) -> list[BlockchainEvent]:
        return list(
            self.session.execute(
                select(BlockchainEvent)
                .where(BlockchainEvent.distribution_id == distribution_id)
                .order_by(BlockchainEvent.created_at.asc(), BlockchainEvent.id.asc())
            ).scalars()
        )

    def events_for_package(self, package_id: uuid.UUID) -> list[BlockchainEvent]:
        """A package's own events, plus the batch's events about the batch itself.

        The package's page tells the story of the honey in it, so the batch's
        events belong there too — they are the same honey. What does *not*
        belong there is another jar's record: a batch holds many packages, each
        with its own ``PACKAGE_CREATED`` and its own QR label, and those rows
        name a different product. Matching on the batch alone handed every
        package the whole batch's package-level rows — 25 labels' worth on a
        single jar's page — so the batch's contribution is narrowed to the rows
        that speak about the batch rather than about a particular package
        (``package_id IS NULL``).
        """
        package = self.session.get(HoneyPackage, package_id)
        if package is None:
            return []
        # The same narrowing also drops the rows of a packaging run that did not
        # make this package (a second run, or a cancelled one).
        return self._trace.events_for_package(package)

    def qr_event(self, package_id: uuid.UUID) -> BlockchainEvent | None:
        """This package's own ``QR_GENERATED`` row, never a batchmate's.

        The label panel reports the event behind the label in hand, so the
        lookup is by package. Picking the first ``QR_GENERATED`` row of the
        batch answered with whichever package was labelled first.
        """
        return self.session.execute(
            select(BlockchainEvent)
            .where(
                BlockchainEvent.package_id == package_id,
                BlockchainEvent.tx_type == BlockchainEventType.QR_GENERATED,
            )
            .order_by(BlockchainEvent.created_at.asc(), BlockchainEvent.id.asc())
            .limit(1)
        ).scalars().first()

    # -- Counts and health ------------------------------------------------- #
    def counts(self, *, user: User | None = None) -> dict[str, Any]:
        filters = []
        if user is not None and user.role is UserRole.KVIC_OFFICER:
            filters.extend(self._cluster_scope_filters(user))
        by_status = dict(
            self.session.execute(
                select(BlockchainEvent.status, func.count())
                .where(*filters)
                .group_by(BlockchainEvent.status)
            ).all()
        )
        by_type = dict(
            self.session.execute(
                select(BlockchainEvent.tx_type, func.count())
                .where(*filters)
                .group_by(BlockchainEvent.tx_type)
            ).all()
        )
        last_confirmed = self.session.execute(
            select(BlockchainEvent).where(
                BlockchainEvent.status == BlockchainStatus.CONFIRMED, *filters
            ).order_by(BlockchainEvent.confirmed_at.desc().nullslast()).limit(1)
        ).scalar_one_or_none()
        total = sum(by_status.values())
        return {
            "total": int(total),
            "by_status": {str(key): int(value) for key, value in by_status.items()},
            "by_type": {str(key): int(value) for key, value in by_type.items()},
            "pending": int(by_status.get(BlockchainStatus.PENDING, 0)),
            "submitted": int(by_status.get(BlockchainStatus.SUBMITTED, 0)),
            "confirmed": int(by_status.get(BlockchainStatus.CONFIRMED, 0)),
            "failed": int(by_status.get(BlockchainStatus.FAILED, 0)),
            "skipped": int(by_status.get(BlockchainStatus.SKIPPED, 0)),
            "last_confirmed_at": last_confirmed.confirmed_at if last_confirmed else None,
            "last_confirmed_event": last_confirmed.event_id if last_confirmed else None,
            "last_confirmed_tx_id": last_confirmed.tx_id if last_confirmed else None,
        }

    def outstanding_count(self) -> int:
        return int(
            self.session.execute(
                select(func.count())
                .select_from(BlockchainEvent)
                .where(BlockchainEvent.status.in_(OUTSTANDING))
            ).scalar_one()
        )

    def health(self, *, user: User | None = None) -> dict[str, Any]:
        """Real synchronization health: what the service says and what is owed to it."""
        probe = self.client.probe()
        counts = self.counts(user=user)
        return {
            "service": {
                # The service's address is server-side configuration and is never
                # returned to a browser: the screen reports whether the layer is
                # reachable, not where it lives. It is written to the log instead.
                "configured": probe.get("configured"),
                "enabled": probe.get("enabled"),
                "reachable": probe.get("reachable"),
                "connected": bool(probe.get("reachable")),
                "latency_ms": probe.get("latency_ms"),
                "ledger_transactions": probe.get("ledger_transactions"),
                "latest_ledger_timestamp": probe.get("latest_timestamp"),
                "message": probe.get("message"),
            },
            "honeychain": counts,
        }

    def chain_ledger(self, *, limit: int = 200) -> list[Transaction]:
        """The raw ledger, straight from the service.

        Admin only, and labelled as what it is: every transaction the chain
        holds, including the demonstration ones recorded before HoneyChain
        wrote any. Those older rows are never attached to a batch that did not
        produce them — they are shown here, and nowhere else.
        """
        transactions = self.client.get_transactions()
        transactions.sort(key=lambda row: row.timestamp or "", reverse=True)
        return transactions[:limit]

    # ------------------------------------------------------------------ #
    # QR and the customer's page
    # ------------------------------------------------------------------ #
    def ensure_qr(self, package: HoneyPackage, *, actor: User | None = None) -> HoneyPackage:
        """Give a package its QR identity, once.

        The identity is a link to the package's traceability page. Generating it
        twice is not an error and does not write a second transaction: the
        stored payload is returned, which is what keeps a printed label valid
        for the life of the package.
        """
        if package.qr_payload:
            return package
        settings = get_settings()
        url = ev.qr_identity(package, settings.PUBLIC_TRACE_BASE_URL)
        package.qr_payload = url
        package.qr_generated_at = _now()
        self.session.flush()
        self.qr_generated(package, url=url, actor=actor)
        self.audit.record(
            AuditAction.PACKAGE_QR_GENERATED,
            actor=actor,
            entity_type="package",
            entity_id=package.id,
            metadata={"package_code": package.package_code, "verification_url": url},
            description=f"QR identity issued for package {package.package_code}.",
        )
        return package

    def package_for_trace(self, package_code: str) -> HoneyPackage | None:
        """The package behind a scanned code, by package code or by QR id."""
        wanted = qr.package_code_from_qr(package_code).upper()
        return self.session.execute(
            select(HoneyPackage).where(func.upper(HoneyPackage.package_code) == wanted)
        ).scalar_one_or_none()

    @staticmethod
    def qr_identifier(package: HoneyPackage) -> str:
        """The package's stable QR id — the identity the label carries."""
        return qr.qr_identifier(package.package_code)

    def public_trace(self, package_code: str) -> dict[str, Any]:
        """The customer's view of a package, built from records only.

        Everything here is read from the supply chain at request time and shown
        without internal identifiers, personal data, notes, telemetry or
        documents. If a stage has not happened, the stage is not shown as
        completed — it is listed with ``reached: false`` and nothing else, so a
        customer sees where their honey is rather than a page of green ticks.

        The ledger section lists each event's type, when it happened and the
        transaction id, which is what makes the page verifiable against the
        chain without exposing the payloads.
        """
        package = self.package_for_trace(package_code)
        if package is None:
            raise LookupError(f"No package matches {package_code}")

        # A cancelled package is not traceable: its honey was withdrawn, and the
        # customer must be told that rather than shown a journey that no longer
        # describes anything they can buy. Nothing else is disclosed.
        if str(package.status) == "CANCELLED":
            return {
                "package": {"package_code": package.package_code},
                "product": {},
                "source": {},
                "processing": [],
                "laboratory": [],
                "packaging": {},
                "distribution": [],
                "timeline": [],
                "blockchain": {
                    "transactions": [],
                    "enabled": bool(get_settings().BLOCKCHAIN_ENABLED),
                    "synchronized": False,
                    "confirmed": 0,
                    "pending": 0,
                    "failed": 0,
                    "skipped": 0,
                    "note": None,
                },
                "qr": {
                    "payload": package.qr_payload,
                    "generated_at": _moment(package.qr_generated_at),
                    "scans": package.qr_scan_count or 0,
                    "qr_id": self.qr_identifier(package),
                },
                "verification": {
                    "available": False,
                    "reason": (
                        "This package was cancelled, so its traceability is no longer "
                        "published."
                    ),
                },
            }

        batch = package.batch
        collection = getattr(batch, "collection", None)
        beekeeper = getattr(batch, "beekeeper", None)
        cluster = getattr(batch, "cluster", None)
        profile = getattr(beekeeper, "profile", None)

        # The QR event is written the first time this page is opened, so the
        # ledger this page shows includes it on that first view — which means
        # recording it *before* the events are read, not after.
        self._record_first_verification(package)

        records = self._trace.for_package(package)
        runs = records.runs
        tests = records.tests
        packaging = records.packaging
        shipments = records.shipments
        events = records.events

        timeline = self.build_timeline(
            package=package, batch=batch, collection=collection, runs=runs,
            tests=tests, packaging=packaging, shipments=shipments,
        )
        return {
            "package": {
                "package_code": package.package_code,
                "package_id": package.package_code,
                "package_size": _number(package.package_size),
                "quantity": _number(package.quantity),
                "unit": _label(package.unit),
                "packaging_type": _container_label(package),
                "packaged_on": _date(package.packaging_date),
                "status": _label(package.status),
                "qr_generated_at": _moment(package.qr_generated_at),
            },
            "product": {
                "batch_code": batch.batch_code,
                "honey": "Honey",
                "net_quantity": _number(batch.quantity),
                "unit": _label(batch.unit),
            },
            "source": {
                "cluster": getattr(cluster, "cluster_name", None),
                "cluster_code": getattr(cluster, "cluster_code", None),
                "district": getattr(profile, "district", None) or getattr(cluster, "district", None),
                "state": getattr(profile, "state", None) or getattr(cluster, "state", None),
                "beekeeper": getattr(beekeeper, "beekeeper_code", None),
                "hive_count": getattr(batch, "source_hive_count", None),
                "collection_date": _date(getattr(collection, "collection_date", None)),
                "collected_quantity": _number(getattr(collection, "total_quantity", None)),
            },
            "processing": [
                {
                    "processing_code": run.processing_code,
                    "processing_type": _processing_type(run),
                    # The *facility* is the processing unit the run happened at
                    # (`unit_ref`). `run.unit` is the unit of measure the batch is
                    # counted in — reading a name off it is how the customer's page
                    # came to name "KG" as a place.
                    "facility": getattr(getattr(run, "unit_ref", None), "name", None),
                    "input_quantity": _number(run.input_quantity),
                    "output_quantity": _number(run.output_quantity),
                    "unit": _label(run.unit),
                    "completed_at": _moment(run.completion_time),
                    "status": _label(run.status),
                }
                for run in runs
            ],
            "laboratory": [
                {
                    "test_code": test.test_code,
                    "sample_code": test.sample_code,
                    "status": _label(test.status),
                    # The verdict as the laboratory recorded it. An override adds
                    # a flag beside it; it never rewrites this value.
                    "result": _label(test.overall_result),
                    "summary": test.result_summary,
                    "round": test.round_number,
                    "completed_at": _moment(test.completed_at),
                    "proceeded_with_risk": bool(
                        getattr(test, "risk_override", False) or getattr(test, "is_override", False)
                    ),
                }
                for test in tests
            ],
            "packaging": {
                "packaging_code": getattr(packaging, "packaging_code", None),
                # The packing unit's name. The relationship is `unit_ref`; asking
                # for `packaging_unit` answered None on every package ever exported.
                "facility": getattr(getattr(packaging, "unit_ref", None), "name", None),
                "packaged_quantity": _number(getattr(packaging, "packaged_quantity", None)),
                "packages_in_run": getattr(packaging, "number_of_packages", None),
                "completed_at": _moment(getattr(packaging, "completion_time", None)),
            },
            "distribution": [
                {
                    "status": _label(shipment.status),
                    "destination": shipment.destination,
                    "district": shipment.destination_district,
                    "carrier": shipment.carrier,
                    "tracking_reference": shipment.tracking_reference,
                    "dispatched_at": _moment(shipment.dispatched_at),
                    "in_transit_at": _moment(shipment.in_transit_at),
                    "delivered_at": _moment(shipment.delivered_at),
                    "received_at": _moment(shipment.received_at),
                    # The shop, not the person behind the account: this page is public.
                    "retailer": _shop_name(getattr(shipment, "retailer", None)),
                }
                for shipment in shipments
            ],
            "timeline": timeline,
            "blockchain": {
                "transactions": [
                    {
                        "event_id": row.event_id,
                        "tx_type": str(row.tx_type),
                        "tx_id": row.tx_id,
                        "status": str(row.status),
                        "timestamp": _moment(row.confirmed_at or row.created_at),
                        "synchronized": row.status is BlockchainStatus.CONFIRMED,
                    }
                    for row in events
                ],
                **{
                    key: value
                    for key, value in self._chain_state(events).items()
                    if key in ("enabled", "synchronized", "pending", "failed", "skipped", "note")
                },
                "confirmed": sum(
                    1 for row in events if row.status is BlockchainStatus.CONFIRMED
                ),
            },
            "qr": {
                "payload": package.qr_payload,
                "generated_at": _moment(package.qr_generated_at),
                "scans": package.qr_scan_count,
                # The stable public identity of the label: derived from the
                # package, so the same jar always answers to the same QR id.
                "qr_id": self.qr_identifier(package),
                "status": _label(package.status),
            },
            "verification": {"available": True, "reason": None},
        }

    def _record_first_verification(self, package: HoneyPackage) -> None:
        """Count the open, and record the verification once.

        A customer refreshing the page, or a second customer scanning the same
        label, increments a counter — it does not write another transaction. The
        chain records that the package was verified, not how many times a
        browser reloaded.
        """
        if not package.qr_payload:
            self.ensure_qr(package)
        package.qr_scan_count = (package.qr_scan_count or 0) + 1
        package.qr_last_scanned_at = _now()
        self.session.flush()
        if package.qr_scan_count == 1:
            self.customer_qr_verified(package, verified_at=package.qr_last_scanned_at)
            self.audit.record(
                AuditAction.PACKAGE_QR_VERIFIED,
                actor=None,
                entity_type="package",
                entity_id=package.id,
                metadata={"package_code": package.package_code},
                description=f"Package {package.package_code} was resolved from its QR code.",
            )
        self.session.commit()

    # The stage records are read by the one traceability reader, so this page,
    # the batch screens and the shipment detail can never disagree about them.
    def _processing_runs(self, batch: HoneyBatch) -> list[Any]:
        return self._trace.processing_runs(batch)

    def _lab_tests(self, batch: HoneyBatch) -> list[Any]:
        return self._trace.lab_tests(batch)

    def _shipments(self, package: HoneyPackage) -> list[Any]:
        return self._trace.shipments_for_package(package)

    # ------------------------------------------------------------------ #
    # The timeline
    # ------------------------------------------------------------------ #
    def build_timeline(
        self,
        *,
        package: HoneyPackage | None = None,
        batch: HoneyBatch | None = None,
        collection: Any = None,
        runs: Sequence[Any] = (),
        tests: Sequence[Any] = (),
        packaging: Any = None,
        shipments: Sequence[Any] = (),
        packages: Sequence[HoneyPackage] | None = None,
    ) -> list[dict[str, Any]]:
        """The supply chain's steps for one package, each marked reached or not.

        Shared by the customer's page and the batch traceability screen so the
        two can never tell different stories: the same records, the same order,
        the same rule that a step is only "completed" when the record that
        completes it exists.
        """
        steps: list[dict[str, Any]] = []

        def step(key: str, label: str, *, at: datetime | None, detail: str | None = None, reached=None):
            done = at is not None if reached is None else reached
            steps.append(
                {
                    "stage": key,
                    "label": label,
                    "reached": bool(done),
                    "at": _moment(at),
                    "detail": detail,
                }
            )

        collected = getattr(collection, "collection_date", None)
        step(
            "COLLECTION",
            "Collection completed",
            at=getattr(collection, "completed_at", None),
            detail=(
                f"{_number(getattr(collection, 'total_quantity', None))} "
                f"{_label(getattr(collection, 'unit', None)) or ''}".strip()
                if collection is not None
                else None
            ),
            reached=collection is not None and str(getattr(collection, "status", "")) == "COMPLETED",
        )
        step(
            "BATCH",
            "Batch created",
            at=getattr(batch, "created_at", None),
            detail=getattr(batch, "batch_code", None),
            reached=batch is not None,
        )
        for run in runs:
            step(
                "PROCESSING",
                "Processing completed",
                at=getattr(run, "completion_time", None),
                detail=_processing_type(run),
                reached=str(getattr(run, "status", "")) == "COMPLETED",
            )
        for test in tests:
            result = _label(getattr(test, "overall_result", None))
            step(
                "LABORATORY",
                "Laboratory checked",
                at=getattr(test, "completed_at", None) or getattr(test, "test_date", None),
                detail=_quality_detail(test),
                reached=bool(getattr(test, "completed_at", None)),
            )
            if result:
                steps[-1]["outcome"] = result
        if packaging is not None:
            step(
                "PACKAGING",
                "Packaged",
                at=getattr(packaging, "completion_time", None),
                detail=(
                    f"{getattr(packaging, 'number_of_packages', None)} × "
                    f"{_number(getattr(packaging, 'package_size', None))} "
                    f"{_label(getattr(packaging, 'unit', None)) or ''}".strip()
                ),
                reached=str(getattr(packaging, "status", "")) == "COMPLETED",
            )
        # The shipping half of the journey is shown even when nothing has been
        # shipped yet: a customer page that simply omits the last four steps
        # looks finished. The steps are listed and marked as not yet reached —
        # which is the truth — while nothing is ever marked reached without the
        # record that earned it.
        # A cancelled shipment never moved anything; it is not a step of the journey.
        shipments = [
            row for row in shipments if str(getattr(row, "status", "")) != "CANCELLED"
        ] or [None]
        # On a batch-wide timeline each shipment step names its package, so four
        # steps per shipment read as "which jar went where" rather than a list of
        # anonymous repeats.
        tag_packages = packages is not None and len(packages) > 1
        for shipment in shipments:
            if shipment is None:
                step("DISPATCHED", "Dispatched", at=None, detail=None, reached=False)
                step("IN_TRANSIT", "In transit", at=None, detail=None, reached=False)
                step("DELIVERED", "Delivered", at=None, detail=None, reached=False)
                step("RETAILER", "Retailer received", at=None, detail=None, reached=False)
                continue
            status = str(getattr(shipment, "status", ""))
            first = len(steps)
            step(
                "DISPATCHED",
                "Dispatched",
                at=getattr(shipment, "dispatched_at", None),
                detail=getattr(shipment, "destination", None),
                reached=bool(getattr(shipment, "dispatched_at", None)),
            )
            step(
                "IN_TRANSIT",
                "In transit",
                at=getattr(shipment, "in_transit_at", None),
                detail=getattr(shipment, "carrier", None),
                reached=bool(getattr(shipment, "in_transit_at", None)),
            )
            step(
                "DELIVERED",
                "Delivered",
                at=getattr(shipment, "delivered_at", None),
                detail=_shop_name(getattr(shipment, "retailer", None)),
                reached=bool(getattr(shipment, "delivered_at", None)),
            )
            step(
                "RETAILER",
                "Retailer received",
                at=getattr(shipment, "received_at", None),
                detail=_shop_name(getattr(shipment, "retailer", None)),
                reached=status == "DELIVERED" and bool(getattr(shipment, "received_at", None)),
            )
            if tag_packages:
                code = getattr(getattr(shipment, "package", None), "package_code", None)
                for row in steps[first:]:
                    row["package_code"] = code

        if packages is not None and len(packages) != 1:
            # A batch-wide view: the label and customer steps are true when they
            # are true of *some* package, and say how many — never borrowed from
            # whichever package happens to be first.
            live = [row for row in packages if str(getattr(row, "status", "")) != "CANCELLED"]
            labelled = [row for row in live if getattr(row, "qr_generated_at", None)]
            opened = [row for row in live if getattr(row, "qr_last_scanned_at", None)]
            step(
                "QR",
                "QR issued for the packages",
                at=min((row.qr_generated_at for row in labelled), default=None),
                detail=f"{len(labelled)} of {len(live)} packages" if live else None,
                reached=bool(labelled),
            )
            step(
                "VERIFIED",
                "Opened by a customer",
                at=max((row.qr_last_scanned_at for row in opened), default=None),
                detail=f"{len(opened)} of {len(live)} packages" if opened else None,
                reached=bool(opened),
            )
            return steps

        if package is None and packages:
            package = packages[0]
        step(
            "QR",
            "QR issued for this package",
            at=getattr(package, "qr_generated_at", None),
            detail=getattr(package, "package_code", None),
            reached=bool(getattr(package, "qr_generated_at", None)),
        )
        step(
            "VERIFIED",
            "Opened by a customer",
            at=getattr(package, "qr_last_scanned_at", None),
            detail=None,
            reached=bool(getattr(package, "qr_last_scanned_at", None)),
        )
        return steps

    def _chain_state(self, events: list[BlockchainEvent]) -> dict[str, Any]:
        """How far a batch or package has actually got onto the chain.

        ``synchronized`` means every event of this record answered with a
        transaction id — a *skipped* event has not been written anywhere and is
        counted separately, with the reason stated beside it, so no screen can
        claim a record is on the chain when the integration is switched off.
        """
        confirmed = sum(1 for row in events if row.status is BlockchainStatus.CONFIRMED)
        pending = sum(
            1 for row in events if row.status in (BlockchainStatus.PENDING, BlockchainStatus.SUBMITTED)
        )
        failed = sum(1 for row in events if row.status is BlockchainStatus.FAILED)
        skipped = sum(1 for row in events if row.status is BlockchainStatus.SKIPPED)
        settings = get_settings()
        note = None
        if skipped and not settings.BLOCKCHAIN_ENABLED:
            note = (
                "The blockchain integration is switched off. These steps are recorded in "
                "HoneyChain and have not been written to the chain."
            )
        elif skipped:
            note = "Some steps were not written to the chain; the reason is recorded on each event."
        elif failed:
            note = "Some steps failed to reach the chain and are waiting to be retried."
        elif pending:
            note = "Some steps are still waiting for the chain to confirm them."
        return {
            "enabled": bool(settings.BLOCKCHAIN_ENABLED),
            "synchronized": bool(events) and confirmed == len(events),
            "confirmed": confirmed,
            "pending": pending,
            "failed": failed,
            "skipped": skipped,
            "note": note,
        }

    def batch_traceability(
        self,
        batch: HoneyBatch,
        *,
        user: User | None = None,
        package: HoneyPackage | None = None,
    ) -> dict[str, Any]:
        """Everything one batch's traceability needs, in one answer.

        Used by the batch's Verification section on the batch screens, the KVIC
        ledger's per-batch view and the traceability pages: the batch's own
        records, its events with their chain status, the timeline they add up
        to, and — in ``chain`` — the real record behind every stage from the
        cluster to the retailer. With ``package`` the answer is narrowed to that
        one package: its run, its shipments, its label and its events.
        """
        records = self._trace.for_batch(batch, package=package)
        return {
            "batch": {
                "id": str(batch.id),
                "batch_code": batch.batch_code,
                "status": _label(batch.status),
                "status_value": str(batch.status),
                "quantity": _number(batch.quantity),
                "unit": _label(batch.unit),
                "collection_date": _date(batch.collection_date),
            },
            "package_code": getattr(package, "package_code", None),
            "transactions": [self.to_event_read(row) for row in records.events],
            "blockchain": self._chain_state(records.events),
            "timeline": self.build_timeline(
                batch=batch,
                collection=records.collection,
                runs=records.runs,
                tests=records.tests,
                packaging=records.packaging,
                shipments=records.shipments,
                package=package,
                packages=None if package is not None else records.packages,
            ),
            "packages": [
                {
                    "package_code": row.package_code,
                    "status": _label(row.status),
                    "qr_issued": bool(row.qr_payload),
                    "qr_id": self.qr_identifier(row) if row.qr_payload else None,
                    "trace_url": f"/trace/{row.package_code}",
                }
                for row in records.packages
            ],
            "chain": self._trace.chain(records),
        }

    @staticmethod
    def to_event_read(event: BlockchainEvent) -> dict[str, Any]:
        """The shape an Admin or KVIC screen reads one transaction in."""
        return {
            "id": str(event.id),
            "event_id": event.event_id,
            "tx_type": str(event.tx_type),
            "tx_type_label": event.tx_type.label,
            "tx_id": event.tx_id,
            "status": str(event.status),
            "status_label": event.status.label,
            "batch_id": str(event.batch_id) if event.batch_id else None,
            "batch_code": event.batch_code,
            "collection_id": str(event.collection_id) if event.collection_id else None,
            "processing_id": str(event.processing_id) if event.processing_id else None,
            "lab_test_id": str(event.lab_test_id) if event.lab_test_id else None,
            "packaging_id": str(event.packaging_id) if event.packaging_id else None,
            "package_id": str(event.package_id) if event.package_id else None,
            "distribution_id": str(event.distribution_id) if event.distribution_id else None,
            "cluster_id": str(event.cluster_id) if event.cluster_id else None,
            "payload": event.payload,
            "attempt_count": event.attempt_count,
            "last_error": event.last_error,
            "created_at": event.created_at,
            "submitted_at": event.submitted_at,
            "confirmed_at": event.confirmed_at,
        }


# --------------------------------------------------------------------------- #
# Small formatting helpers shared by the read models
# --------------------------------------------------------------------------- #
def _shop_name(user: Any) -> str | None:
    """A retailer as the public sees it: the shop's name, not the account holder's."""
    if user is None:
        return None
    return getattr(user, "organization", None) or getattr(user, "name", None)


def _label(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:  # pragma: no cover
        return None


def _date(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _moment(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _processing_type(run: Any) -> str | None:
    raw = _label(getattr(run, "processing_type", None))
    if raw == "OTHER":
        return getattr(run, "processing_type_other", None) or "Other"
    return raw.title() if raw else None


def _container_label(package: HoneyPackage) -> str | None:
    raw = _label(package.packaging_type)
    if raw == "OTHER":
        return package.packaging_type_other or "Other"
    return raw.replace("_", " ").title() if raw else None


def _quality_detail(test: Any) -> str | None:
    result = _label(getattr(test, "overall_result", None))
    if not result:
        return _label(getattr(test, "status", None))
    return result.replace("_", " ").title()


__all__ = [
    "MAX_AUTO_ATTEMPTS",
    "OUTSTANDING",
    "BlockchainService",
]
