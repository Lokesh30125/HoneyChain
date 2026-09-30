"""The batch lifecycle — declared once, enforced everywhere.

A batch moves through the supply chain, and every move in this platform goes
through :func:`advance`. The table of permitted moves lives in
:data:`~app.models.enums.BATCH_STATUS_TRANSITIONS`; this module is the only thing
that reads it, so "the backend enforces transitions" is a property of the code
rather than a promise in a document.

What that buys
--------------
* a client cannot set a status at all — no request model contains one;
* a caller cannot jump the queue (``COLLECTED`` → ``APPROVED`` is refused);
* a module cannot invent the next stage either: reaching ``PACKAGED`` fails here
  until a later phase deliberately extends the map and ships a migration with it;
* the same rule applies to the actor that legitimately owns each step, because
  ownership is checked before the transition, not instead of it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.exceptions import ConflictError
from app.models.enums import BATCH_STATUS_TRANSITIONS, BatchStage, BatchStatus
from app.models.honey_batch import HoneyBatch

#: The stage a batch stands at for each status Phase 5 or 6 can produce. The
#: timeline reads this rather than deriving the stage from the status, so the two
#: can never disagree.
STAGE_FOR_STATUS: dict[BatchStatus, BatchStage] = {
    BatchStatus.COLLECTED: BatchStage.COLLECTION,
    BatchStatus.PROCESSING: BatchStage.PROCESSING,
    BatchStatus.LAB_TESTING: BatchStage.LABORATORY,
    # A held or risk-flagged batch is still the laboratory's business: the honey
    # does not move while the question is open.
    BatchStatus.LAB_HOLD: BatchStage.LABORATORY,
    BatchStatus.PROCEEDED_WITH_RISK: BatchStage.LABORATORY,
    BatchStatus.APPROVED: BatchStage.LABORATORY,
    # Released to the floor: the batch is now packaging's work.
    BatchStatus.PACKAGING_READY: BatchStage.PACKAGING,
    BatchStatus.REJECTED: BatchStage.LABORATORY,
    # Phase 7: once the honey is packed the batch has left the laboratory behind,
    # and the transit of its packages is the stage it is in.
    BatchStatus.PACKAGED: BatchStage.PACKAGING,
    BatchStatus.DISTRIBUTION: BatchStage.DISTRIBUTION,
    BatchStatus.COMPLETED: BatchStage.COMPLETED,
}

#: Plain-language name for each status, used in messages the API returns.
STATUS_LABEL: dict[BatchStatus, str] = {
    BatchStatus.COLLECTED: "Collected",
    BatchStatus.PROCESSING: "Processing",
    BatchStatus.LAB_TESTING: "Laboratory testing",
    BatchStatus.LAB_HOLD: "On hold in the laboratory",
    BatchStatus.PROCEEDED_WITH_RISK: "Risk recorded, proceeding",
    BatchStatus.APPROVED: "Approved",
    BatchStatus.PACKAGING_READY: "Approved — ready for packaging",
    BatchStatus.REJECTED: "Rejected",
    BatchStatus.PACKAGED: "Packaged",
    BatchStatus.DISTRIBUTION: "In distribution",
    BatchStatus.COMPLETED: "Completed",
}


def allowed_transitions(status: BatchStatus) -> tuple[BatchStatus, ...]:
    """Where a batch in this state may legally go next."""
    return BATCH_STATUS_TRANSITIONS.get(status, ())


def can_transition(current: BatchStatus, target: BatchStatus) -> bool:
    return target in allowed_transitions(current)


def assert_transition(current: BatchStatus, target: BatchStatus, *, action: str) -> None:
    """Refuse an illegal move with a message a screen can show verbatim."""
    if can_transition(current, target):
        return
    allowed = allowed_transitions(current)
    if not allowed:
        raise ConflictError(
            f"A batch in state {STATUS_LABEL.get(current, current)} cannot move to "
            f"{STATUS_LABEL.get(target, target)}: that stage belongs to a module this "
            "build does not include.",
            details={"current_status": str(current), "requested_status": str(target), "action": action},
        )
    raise ConflictError(
        f"{action} is not possible while the batch is {STATUS_LABEL.get(current, current)}. "
        f"It must be {', '.join(STATUS_LABEL.get(item, item) for item in allowed)} first.",
        details={
            "current_status": str(current),
            "requested_status": str(target),
            "allowed_next": [str(item) for item in allowed],
            "action": action,
        },
    )


def advance(
    batch: HoneyBatch,
    target: BatchStatus,
    *,
    action: str,
) -> tuple[BatchStatus, BatchStatus]:
    """Move a batch to ``target``, or refuse.

    Returns ``(previous, new)`` so the caller can audit the change without
    re-reading the row. The stage is kept in step with the status *here*, which is
    why no other module assigns ``current_stage`` — the timeline and the status
    cannot drift apart.
    """
    previous = batch.status
    assert_transition(previous, target, action=action)
    batch.status = target
    batch.current_stage = STAGE_FOR_STATUS.get(target, batch.current_stage)
    return previous, target


def now() -> datetime:
    """One clock for the module, so tests can reason about ordering."""
    return datetime.now(timezone.utc)


__all__ = [
    "advance",
    "allowed_transitions",
    "assert_transition",
    "can_transition",
    "now",
    "STAGE_FOR_STATUS",
    "STATUS_LABEL",
]
