"""Traceability routes — the ledgers, a batch's history, and a package's QR.

``GET /blockchain/transactions`` / ``GET /blockchain/transactions/{id}``
    The ledger: every traceability event this platform recorded, with its chain
    status, the payload that was submitted and a link to the record it describes.
    An administrator reads it all; a KVIC officer reads the events of the
    clusters they oversee, through the same cluster registry their batch register
    uses.
``GET /blockchain/transactions/{id}``
    One transaction in full: ``tx_id``, type, batch, timestamp, status, payload
    and the HoneyChain record behind it.
``GET /blockchain/ledger``
    The chain's own answer — ``GET /transactions`` from the blockchain service,
    exactly as it reports it, including the transactions written before
    HoneyChain existed. Admin only, and marked as unlinked where they are.
``GET /blockchain/batches/{batch_id}``
    A batch's whole traceability: its timeline, its events, its packages. Read
    by anyone who may read the batch — the service applies the same scope rule
    the batch itself uses.
``GET /blockchain/health``
    Whether the service is reachable, and how many events are still waiting.
``POST /blockchain/sync``
    Submit everything outstanding, now, instead of waiting for the worker.
``POST /blockchain/transactions/{id}/retry``
    Submit one event again after a failure, and record who asked.
``POST /blockchain/packages/{package_id}/qr``
    Issue a package's QR identity (once) and return the label.
``GET /blockchain/packages/{package_id}/qr``
    Read it without issuing anything.

Nothing here writes a supply-chain status. Every endpoint either reads, or
retries work the platform already recorded; the statuses themselves are written
by the workflow that earns them, in the same transaction as the record change.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import db_session
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.permissions import (
    Permission,
    require_any_permission,
    require_permission,
)
from app.models.enums import AuditAction, BlockchainEventType, BlockchainStatus, UserRole
from app.models.packaging import HoneyPackage
from app.models.user import User
from app.schemas.blockchain import (
    BatchTraceabilityRead,
    BlockchainEventRead,
    BlockchainHealthRead,
    BlockchainTransactionRead,
    PackageQrRead,
)
from app.schemas.common import ApiResponse, PaginationParams, ok, paginated
from app.services.blockchain import BlockchainService
from app.services.blockchain.qr import qr_svg
from app.services.batch_service import BatchService

router = APIRouter(tags=["Blockchain"])

READ_LEDGER = require_permission(Permission.BLOCKCHAIN_READ)
SYNC_LEDGER = require_permission(Permission.BLOCKCHAIN_SYNC)
READ_BATCH = require_any_permission(Permission.BATCH_READ_SELF, Permission.BATCH_READ_ALL)
READ_PACKAGE = require_permission(Permission.PACKAGING_READ)
#: Issuing a label writes a QR identity and a ledger event, so it is packaging
#: work — a reader of packages (a beekeeper, a retailer) may read the label but
#: never mint one.
ISSUE_PACKAGE_QR = require_permission(Permission.PACKAGING_WRITE)


# --------------------------------------------------------------------------- #
# The ledger
# --------------------------------------------------------------------------- #
@router.get(
    "/blockchain/transactions",
    response_model=ApiResponse[list[BlockchainEventRead]],
    summary="List traceability transactions",
    description=(
        "Every supply-chain event HoneyChain recorded, newest first, with its blockchain "
        "status, its payload and the record it belongs to. An administrator reads the whole "
        "ledger; a KVIC officer reads the events of their own clusters."
    ),
)
def list_transactions(
    pagination: PaginationParams = Depends(),
    tx_type: BlockchainEventType | None = Query(default=None, description="Filter by event type."),
    status: BlockchainStatus | None = Query(default=None, description="Filter by chain status."),
    batch_code: str | None = Query(default=None, max_length=60),
    search: str | None = Query(
        default=None, max_length=120, description="Match the event id, batch code or transaction id."
    ),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    user: User = Depends(READ_LEDGER),
    session: Session = Depends(db_session),
) -> dict:
    rows, total = BlockchainService(session).ledger(
        user,
        page=pagination.page,
        page_size=pagination.page_size,
        tx_type=tx_type,
        status=status,
        batch_code=batch_code,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    service = BlockchainService(session)
    return paginated(
        [service.to_event_read(row) for row in rows],
        total_items=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/blockchain/transactions/{event_id}",
    response_model=ApiResponse[BlockchainEventRead],
    summary="One traceability transaction",
    description=(
        "The transaction in full: its id on the chain, its type, the batch it belongs to, when "
        "it was recorded and confirmed, the payload that was submitted, its synchronization "
        "status and any error from the last attempt."
    ),
)
def get_transaction(
    event_id: uuid.UUID,
    user: User = Depends(READ_LEDGER),
    session: Session = Depends(db_session),
) -> dict:
    service = BlockchainService(session)
    try:
        event = service.get_event(user, event_id)
    except LookupError as error:
        raise NotFoundError(str(error), details={"resource": "blockchain_event"}) from error
    return ok(service.to_event_read(event))


@router.get(
    "/blockchain/ledger",
    response_model=ApiResponse[list[BlockchainTransactionRead]],
    summary="The blockchain's own ledger",
    description=(
        "Every transaction the blockchain service reports, straight from GET /transactions. "
        "This is the raw ledger, and it is a superset of what HoneyChain wrote: transactions "
        "recorded before this platform had a ledger integration stay here as history. Rows that "
        "match an event HoneyChain recorded are marked as such; the rest are shown unlinked and "
        "are never attached to a batch."
    ),
)
def chain_ledger(
    limit: int = Query(default=200, ge=1, le=1000),
    user: User = Depends(READ_LEDGER),
    session: Session = Depends(db_session),
) -> dict:
    if user.role is not UserRole.ADMIN:
        # The chain's own ledger is unscoped — it carries every transaction ever
        # written — so only the administrator reads it. A KVIC officer reads the
        # cluster-scoped ledger at /blockchain/transactions.
        raise ForbiddenError(
            "Only an administrator may read the raw blockchain ledger.",
            details={"role": str(user.role)},
        )
    service = BlockchainService(session)
    transactions = service.chain_ledger(limit=limit)
    by_tx_id = {
        row.tx_id: row
        for row in service.ledger(user, page=1, page_size=1000)[0]
        if row.tx_id
    }
    return ok(
        [
            {
                "tx_id": row.tx_id,
                "tx_type": row.tx_type,
                "batch_id": row.batch_id,
                "timestamp": row.timestamp,
                "payload": row.payload,
                "matched_event_id": getattr(by_tx_id.get(row.tx_id), "event_id", None),
                "matched_batch_code": getattr(by_tx_id.get(row.tx_id), "batch_code", None),
                "honey_chain_recorded": row.tx_id in by_tx_id,
            }
            for row in transactions
        ]
    )


@router.get(
    "/blockchain/health",
    response_model=ApiResponse[BlockchainHealthRead],
    summary="Blockchain synchronization health",
    description=(
        "Whether the blockchain service is reachable right now, how long it took to answer, how "
        "many transactions it holds — and, on HoneyChain's side, how many events are confirmed, "
        "waiting or failed. Every value is measured at request time; none is estimated."
    ),
)
def blockchain_health(
    # Reading the state of the traceability layer is a read: the accounts that may
    # read the ledger (administrator, KVIC officer) may see whether it is well.
    # Writing to it stays behind BLOCKCHAIN_SYNC.
    user: User = Depends(READ_LEDGER),
    session: Session = Depends(db_session),
) -> dict:
    return ok(BlockchainService(session).health(user=user))


@router.post(
    "/blockchain/sync",
    response_model=ApiResponse[dict],
    summary="Write outstanding events to the blockchain",
    description=(
        "Submit the events that are still pending or failed, now, instead of waiting for the "
        "background worker. Safe to run at any time: an event that is already on the chain is "
        "reused, never submitted twice."
    ),
)
def sync_blockchain(
    user: User = Depends(SYNC_LEDGER),
    session: Session = Depends(db_session),
) -> dict:
    service = BlockchainService(session)
    result = service.sweep()
    service.audit.record(
        AuditAction.BLOCKCHAIN_SYNC_RUN,
        actor=user,
        entity_type="blockchain_event",
        metadata=result,
        description=(
            f"Blockchain synchronization run by hand: {result['confirmed']} confirmed, "
            f"{result['failed']} failed, {result['outstanding']} still outstanding."
        ),
    )
    session.commit()
    return ok(result)


@router.post(
    "/blockchain/transactions/{event_id}/retry",
    response_model=ApiResponse[BlockchainEventRead],
    summary="Retry one failed transaction",
    description=(
        "Submit one event again after a failure. The attempt counter is reset and the retry is "
        "recorded against the operator who asked for it."
    ),
)
def retry_transaction(
    event_id: uuid.UUID,
    user: User = Depends(SYNC_LEDGER),
    session: Session = Depends(db_session),
) -> dict:
    service = BlockchainService(session)
    try:
        event = service.get_event(user, event_id)
    except LookupError as error:
        raise NotFoundError(str(error), details={"resource": "blockchain_event"}) from error
    service.retry(event, actor=user)
    session.refresh(event)
    return ok(service.to_event_read(event))


# --------------------------------------------------------------------------- #
# A batch's traceability
# --------------------------------------------------------------------------- #
@router.get(
    "/blockchain/batches/{batch_id}",
    response_model=ApiResponse[BatchTraceabilityRead],
    summary="A batch's blockchain traceability",
    description=(
        "The batch's timeline, every traceability event recorded for it with its chain status, "
        "and its packages. The caller must be able to read the batch itself — the same scope "
        "rule, applied once."
    ),
)
def batch_traceability(
    batch_id: uuid.UUID,
    package_code: str | None = Query(
        default=None,
        max_length=60,
        description="Narrow the answer to one package of this batch (its run, shipments, label and events).",
    ),
    user: User = Depends(READ_BATCH),
    session: Session = Depends(db_session),
) -> dict:
    # Read through the batch service so an out-of-scope batch is a 404 here for
    # exactly the same reason it is a 404 on the batch screen.
    BatchService(session).get_batch(user, batch_id)
    model = BatchService(session).batches.get_with_relations(batch_id)
    service = BlockchainService(session)
    package = None
    if package_code:
        package = service.package_for_trace(package_code)
        if package is None or package.batch_id != model.id:
            # A package of another batch is "not here", never a different batch's story.
            raise NotFoundError(
                f"Package {package_code} is not part of batch {model.batch_code}",
                details={"resource": "package"},
            )
    return ok(service.batch_traceability(model, user=user, package=package))


# --------------------------------------------------------------------------- #
# A package's QR
# --------------------------------------------------------------------------- #
@router.get(
    "/blockchain/packages/{package_id}/qr",
    response_model=ApiResponse[PackageQrRead],
    summary="Read a package's QR identity",
    description=(
        "The package's QR link and the label itself, if one has been issued. Reading does not "
        "issue anything."
    ),
)
def read_package_qr(
    package_id: uuid.UUID,
    user: User = Depends(READ_PACKAGE),
    session: Session = Depends(db_session),
) -> dict:
    from app.services.packaging_service import PackagingService

    PackagingService(session).get_package(user, package_id)  # authorisation, and scope
    service = BlockchainService(session)
    package = session.get(HoneyPackage, package_id)
    return ok(_qr_read(service, package, issued=False))


@router.post(
    "/blockchain/packages/{package_id}/qr",
    response_model=ApiResponse[PackageQrRead],
    summary="Issue a package's QR identity",
    description=(
        "Give the package its QR link and label — once. Calling this again returns the identity "
        "that already exists; it never issues a second one, and a printed label stays valid."
    ),
)
def issue_package_qr(
    package_id: uuid.UUID,
    user: User = Depends(ISSUE_PACKAGE_QR),
    session: Session = Depends(db_session),
) -> dict:
    from app.services.packaging_service import PackagingService

    PackagingService(session).get_package(user, package_id)
    service = BlockchainService(session)
    package = session.get(HoneyPackage, package_id)
    if str(package.status) == "CANCELLED":
        raise ConflictError(
            f"Package {package.package_code} was cancelled and cannot be labelled.",
            details={"package_code": package.package_code, "status": str(package.status)},
        )
    service.ensure_qr(package, actor=user)
    session.commit()
    session.refresh(package)
    return ok(_qr_read(service, package, issued=True))


def _qr_read(service: BlockchainService, package, *, issued: bool) -> dict:
    # The label's own transaction: looked up by package, so a busy batch cannot
    # answer with a batchmate's QR event.
    event = service.qr_event(package.id) if package.qr_payload else None
    return {
        "package_code": package.package_code,
        "qr_id": service.qr_identifier(package),
        "batch_code": getattr(package.batch, "batch_code", None),
        "qr_payload": package.qr_payload,
        "generated_at": package.qr_generated_at,
        "scans": package.qr_scan_count or 0,
        "svg": qr_svg(package.qr_payload or ""),
        "event_id": event.event_id if event else None,
        "tx_id": event.tx_id if event else None,
    }
