"""Audit logging service.

Called by other services at the end of a **successful** operation, so the trail
records what actually happened rather than what was attempted. Failures that
matter (a rejected login, for instance) are recorded explicitly.

Two guarantees:

* **No secrets.** ``event_metadata`` is passed through the same redaction used by
  the logging layer, so a caller cannot accidentally persist a password, token or
  API key.
* **Never breaks the caller.** If writing an audit row fails, the error is logged
  and swallowed — losing an audit entry is bad, but it must not roll back the
  business action the user just completed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.logging import get_logger, scrub
from app.models.audit_log import AuditLog
from app.models.enums import AuditAction
from app.models.user import User
from app.repositories.audit_repository import AuditLogRepository

logger = get_logger("service")

#: Values longer than this are truncated before storage, to bound row size.
MAX_METADATA_TEXT = 500


def _bound(value: Any) -> Any:
    """Trim long strings so a stray payload cannot bloat an audit row."""
    if isinstance(value, str) and len(value) > MAX_METADATA_TEXT:
        return value[:MAX_METADATA_TEXT] + "…"
    if isinstance(value, dict):
        return {key: _bound(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_bound(item) for item in value]
    return value


def _as_text(value) -> str | None:  # noqa: ANN001 - Decimal | None
    """A quantity as a string, so a JSON audit entry never carries a float.

    Decimal → float is lossy for figures people reconcile by hand; the same
    convention the rest of the audit metadata uses.
    """
    return None if value is None else str(value)


class AuditService:
    """Writes audit entries and answers review queries over them."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.logs = AuditLogRepository(session)

    # ------------------------------------------------------------------ #
    # Writing
    # ------------------------------------------------------------------ #
    def record(
        self,
        action: AuditAction | str,
        *,
        actor: User | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | str | None = None,
        metadata: dict[str, Any] | None = None,
        description: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        commit: bool = False,
    ) -> AuditLog | None:
        """Persist one audit entry.

        ``commit=False`` (default) flushes inside the caller's transaction so the
        audit row and the business change succeed or fail together. Pass
        ``commit=True`` for standalone events such as a login, where there is no
        surrounding write to attach to.

        The insert runs inside a SAVEPOINT: if it fails, only the audit row is
        rolled back. Without this, a failed audit write would poison the
        caller's transaction and silently discard the user's actual operation.
        """
        try:
            with self.session.begin_nested():
                entry = self.logs.record(
                    action=str(action),
                    user_id=actor.id if actor else None,
                    actor_email=actor.email if actor else None,
                    actor_role=str(actor.role) if actor else None,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    # Redaction is defence in depth: callers must not pass secrets,
                    # and this guarantees it even if one does.
                    event_metadata=_bound(scrub(metadata)) if metadata else None,
                    description=description,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            if commit:
                self.logs.commit()
            return entry
        except SQLAlchemyError:
            # Never let auditing take down the operation it was recording. The
            # savepoint above has already restored the session to a usable state.
            logger.error(
                "Failed to write audit entry",
                extra={"action": str(action), "entity_type": entity_type},
                exc_info=True,
            )
            return None

    # ------------------------------------------------------------------ #
    # Convenience wrappers for the events Phase 2 emits
    # ------------------------------------------------------------------ #
    def user_registered(self, user: User, *, role: str, **context: Any) -> None:
        self.record(
            AuditAction.USER_REGISTERED,
            actor=user,
            entity_type="user",
            entity_id=user.id,
            metadata={"role": role, **context},
            description=f"Account registered as {role}",
        )

    def user_login(self, user: User, *, ip_address: str | None = None, user_agent: str | None = None) -> None:
        self.record(
            AuditAction.USER_LOGIN,
            actor=user,
            entity_type="user",
            entity_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            description="Signed in successfully",
            commit=True,
        )

    def user_login_failed(self, email: str, *, ip_address: str | None = None) -> None:
        """Record a failed attempt without storing the submitted password."""
        self.record(
            AuditAction.USER_LOGIN_FAILED,
            entity_type="user",
            metadata={"email_domain": email.split("@")[-1] if email and "@" in email else None},
            description="Failed sign-in attempt",
            ip_address=ip_address,
            commit=True,
        )

    def user_logout(self, user: User, *, all_devices: bool = False) -> None:
        self.record(
            AuditAction.USER_LOGOUT,
            actor=user,
            entity_type="user",
            entity_id=user.id,
            metadata={"all_devices": all_devices},
            description="Signed out" + (" from all devices" if all_devices else ""),
            commit=True,
        )

    def profile_updated(self, user: User, *, changed_fields: list[str]) -> None:
        self.record(
            AuditAction.PROFILE_UPDATED,
            actor=user,
            entity_type="user",
            entity_id=user.id,
            # Field names only — never the values, which may be personal data.
            metadata={"changed_fields": changed_fields},
            description=f"Profile updated ({len(changed_fields)} field(s))",
        )

    def user_status_changed(self, user: User, *, is_active: bool, actor: User, reason: str | None) -> None:
        self.record(
            AuditAction.USER_ACTIVATED if is_active else AuditAction.USER_DEACTIVATED,
            actor=actor,
            entity_type="user",
            entity_id=user.id,
            metadata={"is_active": is_active, "reason": reason, "subject_email": user.email},
            description=f"Account {'activated' if is_active else 'deactivated'}",
        )

    def user_provisioned(
        self,
        user: User,
        *,
        role: str,
        actor: User,
        is_active: bool = True,
        reason: str | None = None,
        beekeeper_code: str | None = None,
    ) -> None:
        """An administrator created an account for an operational role."""
        self.record(
            AuditAction.USER_PROVISIONED,
            actor=actor,
            entity_type="user",
            entity_id=user.id,
            metadata={
                "role": role,
                "is_active": is_active,
                "reason": reason,
                "subject_email": user.email,
                "organization": user.organization,
                "beekeeper_code": beekeeper_code,
            },
            description=f"Account provisioned as {role}",
        )

    def user_role_changed(
        self,
        user: User,
        *,
        previous_role: str,
        new_role: str,
        actor: User,
        reason: str | None = None,
        sessions_revoked: int = 0,
        beekeeper_created: bool = False,
    ) -> None:
        """An administrator changed which role an account holds.

        Both roles are recorded: after the fact, "what was this account before"
        is not answerable from the new value alone.
        """
        self.record(
            AuditAction.USER_ROLE_CHANGED,
            actor=actor,
            entity_type="user",
            entity_id=user.id,
            metadata={
                "previous_role": previous_role,
                "new_role": new_role,
                "reason": reason,
                "sessions_revoked": sessions_revoked,
                "beekeeper_created": beekeeper_created,
                "subject_email": user.email,
            },
            description=f"Role changed from {previous_role} to {new_role}",
        )

    def beekeeper_created(self, beekeeper, *, actor: User | None = None) -> None:
        self.record(
            AuditAction.BEEKEEPER_CREATED,
            actor=actor or beekeeper.user,
            entity_type="beekeeper",
            entity_id=beekeeper.id,
            metadata={
                "beekeeper_code": beekeeper.beekeeper_code,
                "district": beekeeper.district,
                "state": beekeeper.state,
                "verification_status": str(beekeeper.verification_status),
            },
            description=f"Beekeeper {beekeeper.beekeeper_code} registered",
        )

    def beekeeper_updated(self, beekeeper, *, actor: User, changed_fields: list[str]) -> None:
        self.record(
            AuditAction.BEEKEEPER_UPDATED,
            actor=actor,
            entity_type="beekeeper",
            entity_id=beekeeper.id,
            metadata={"changed_fields": changed_fields, "beekeeper_code": beekeeper.beekeeper_code},
            description=f"Beekeeper {beekeeper.beekeeper_code} updated",
        )

    def beekeeper_verification_changed(
        self,
        beekeeper,
        *,
        actor: User,
        previous_status: str,
        new_status: str,
        remarks: str | None,
    ) -> None:
        action = {
            "VERIFIED": AuditAction.BEEKEEPER_VERIFIED,
            "REJECTED": AuditAction.BEEKEEPER_REJECTED,
            "SUSPENDED": AuditAction.BEEKEEPER_SUSPENDED,
        }.get(new_status, AuditAction.BEEKEEPER_VERIFICATION_UPDATED)

        self.record(
            action,
            actor=actor,
            entity_type="beekeeper",
            entity_id=beekeeper.id,
            metadata={
                "beekeeper_code": beekeeper.beekeeper_code,
                "previous_status": previous_status,
                "new_status": new_status,
                "remarks": remarks,
            },
            description=f"Verification {previous_status} → {new_status}",
        )

    def cluster_created(self, cluster, *, actor: User) -> None:
        self.record(
            AuditAction.CLUSTER_CREATED,
            actor=actor,
            entity_type="kvic_cluster",
            entity_id=cluster.id,
            metadata={
                "cluster_code": cluster.cluster_code,
                "cluster_name": cluster.cluster_name,
                "district": cluster.district,
            },
            description=f"Cluster {cluster.cluster_code} created",
        )

    def cluster_updated(self, cluster, *, actor: User, changed_fields: list[str]) -> None:
        self.record(
            AuditAction.CLUSTER_UPDATED,
            actor=actor,
            entity_type="kvic_cluster",
            entity_id=cluster.id,
            metadata={"cluster_code": cluster.cluster_code, "changed_fields": changed_fields},
            description=f"Cluster {cluster.cluster_code} updated",
        )

    def cluster_status_changed(self, cluster, *, actor: User, is_active: bool) -> None:
        self.record(
            AuditAction.CLUSTER_STATUS_CHANGED,
            actor=actor,
            entity_type="kvic_cluster",
            entity_id=cluster.id,
            metadata={"cluster_code": cluster.cluster_code, "is_active": is_active},
            description=f"Cluster {cluster.cluster_code} {'activated' if is_active else 'deactivated'}",
        )

    def cluster_member_assigned(self, beekeeper, *, actor: User, cluster) -> None:
        """A beekeeper joined a cluster (or was cleared from one).

        The action name distinguishes joining from leaving, because the two mean
        different things to whoever reads the trail later: one grants visibility
        of the apiary to a cluster, the other withdraws it.
        """
        self.record(
            AuditAction.BEEKEEPER_ASSIGNED_TO_CLUSTER
            if cluster
            else AuditAction.BEEKEEPER_REMOVED_FROM_CLUSTER,
            actor=actor,
            entity_type="beekeeper",
            entity_id=beekeeper.id,
            metadata={
                "beekeeper_code": beekeeper.beekeeper_code,
                "cluster_code": cluster.cluster_code if cluster else None,
            },
            description=f"Assigned to cluster {cluster.cluster_code}"
            if cluster
            else "Removed from cluster",
        )

    def cluster_batches_assigned(
        self,
        cluster,
        *,
        actor: User,
        batch_codes: list[str],
        moved_codes: list[str] | None = None,
    ) -> None:
        """Honey batches placed in a cluster (or moved into it).

        The codes are recorded because the question asked of this trail later is
        "which honey went into this cluster, and when" — and because a *move*
        between clusters has to be visible as one.
        """
        self.record(
            AuditAction.CLUSTER_BATCHES_ASSIGNED,
            actor=actor,
            entity_type="kvic_cluster",
            entity_id=cluster.id,
            metadata={
                "cluster_code": cluster.cluster_code,
                "batches": batch_codes,
                "moved_from_another_cluster": moved_codes or [],
                "count": len(batch_codes),
            },
            description=(
                f"{len(batch_codes)} batch(es) placed in {cluster.cluster_code}"
                + (f", {len(moved_codes)} moved from another cluster" if moved_codes else "")
            ),
        )

    def cluster_batch_detached(
        self, cluster, *, actor: User, batch_code: str, batch_id
    ) -> None:
        """One batch taken out of a cluster. Nothing is deleted but the link."""
        self.record(
            AuditAction.CLUSTER_BATCH_DETACHED,
            actor=actor,
            entity_type="kvic_cluster",
            entity_id=cluster.id,
            metadata={
                "cluster_code": cluster.cluster_code,
                "batch_code": batch_code,
                "batch_id": str(batch_id),
            },
            description=f"Batch {batch_code} removed from {cluster.cluster_code}",
        )

    def cluster_relationship_updated(
        self,
        beekeeper,
        *,
        actor: User,
        previous_cluster,
        cluster,
        hives_followed: list[str],
        hives_detached: list[str] | None = None,
        records_linked: dict[str, int] | None = None,
    ) -> None:
        """The summary entry for a membership change, including what followed.

        Reassigning a beekeeper moves their hives with them, so the trail records
        the affected hive codes alongside the two clusters. No hive *row* is
        rewritten historically: the hive keeps its readings, its analyses and its
        owner, and only its organisational pointer changes.
        """
        self.record(
            AuditAction.CLUSTER_RELATIONSHIP_UPDATED,
            actor=actor,
            entity_type="beekeeper",
            entity_id=beekeeper.id,
            metadata={
                "beekeeper_code": beekeeper.beekeeper_code,
                "previous_cluster_code": previous_cluster.cluster_code if previous_cluster else None,
                "cluster_code": cluster.cluster_code if cluster else None,
                "hives_followed": sorted(hives_followed),
                "hives_followed_count": len(hives_followed),
                "hives_detached": sorted(hives_detached or []),
                # Harvests recorded before the membership that were given the
                # cluster as part of this action. Present and zero when nothing
                # needed filling in, so the trail always answers "was anything
                # backfilled here?".
                "records_linked": records_linked or {"collections": 0, "batches": 0},
            },
            description=(
                f"Cluster link updated: {previous_cluster.cluster_code if previous_cluster else 'none'}"
                f" → {cluster.cluster_code if cluster else 'none'}"
                f" ({len(hives_followed)} hive(s) followed)"
            ),
        )

    def hive_cluster_changed(self, hive, *, actor: User, previous_cluster, cluster) -> None:
        """One hive's organisational pointer was set, changed or cleared."""
        self.record(
            AuditAction.HIVE_ASSOCIATED_WITH_CLUSTER,
            actor=actor,
            entity_type="hive",
            entity_id=hive.id,
            metadata={
                "hive_code": hive.hive_code,
                "previous_cluster_code": previous_cluster.cluster_code if previous_cluster else None,
                "cluster_code": cluster.cluster_code if cluster else None,
            },
            description=(
                f"Hive {hive.hive_code} cluster: "
                f"{previous_cluster.cluster_code if previous_cluster else 'none'} → "
                f"{cluster.cluster_code if cluster else 'none'}"
            ),
        )

    # ------------------------------------------------------------------ #
    # Phase 3 — hives, devices and telemetry
    # ------------------------------------------------------------------ #
    def hive_created(self, hive, *, actor: User | None = None) -> None:
        self.record(
            AuditAction.HIVE_CREATED,
            actor=actor,
            entity_type="hive",
            entity_id=hive.id,
            metadata={
                "hive_code": hive.hive_code,
                "district": hive.district,
                "cluster_id": str(hive.cluster_id) if hive.cluster_id else None,
                "status": str(hive.status),
            },
            description=f"Hive {hive.hive_code} registered",
        )

    def hive_updated(self, hive, *, actor: User | None, changed_fields: list[str]) -> None:
        self.record(
            AuditAction.HIVE_UPDATED,
            actor=actor,
            entity_type="hive",
            entity_id=hive.id,
            # Field names only — the values include the hive's GPS position.
            metadata={"hive_code": hive.hive_code, "changed_fields": changed_fields},
            description=f"Hive {hive.hive_code} updated ({len(changed_fields)} field(s))",
        )

    def hive_status_changed(
        self, hive, *, actor: User | None, previous: str, new: str, reason: str | None = None
    ) -> None:
        self.record(
            AuditAction.HIVE_STATUS_CHANGED,
            actor=actor,
            entity_type="hive",
            entity_id=hive.id,
            metadata={
                "hive_code": hive.hive_code,
                "previous_status": str(previous),
                "new_status": str(new),
                "reason": reason,
            },
            description=f"Hive {hive.hive_code}: {previous} → {new}",
        )

    def hive_removed(self, hive, *, actor: User | None = None, hard: bool = False) -> None:
        """A hive leaving the registry.

        ``hard=True`` means the row (and its now-empty device/reading set) was
        deleted; ``False`` means it was soft-deleted to ``REMOVED``. Either way
        the audit entry survives, which is the point.
        """
        self.record(
            AuditAction.HIVE_REMOVED,
            actor=actor,
            entity_type="hive",
            entity_id=hive.id,
            metadata={"hive_code": hive.hive_code, "hard_delete": hard},
            description=(
                f"Hive {hive.hive_code} deleted"
                if hard
                else f"Hive {hive.hive_code} marked REMOVED"
            ),
        )

    def device_registered(
        self, device, *, actor: User | None = None, sensor_count: int | None = None
    ) -> None:
        self.record(
            AuditAction.DEVICE_REGISTERED,
            actor=actor,
            entity_type="iot_device",
            entity_id=device.id,
            metadata={
                "device_id": device.device_id,
                "device_type": str(device.device_type),
                "connection_type": str(device.connection_type),
                "hive_id": str(device.hive_id),
                "sensors_configured": sensor_count,
            },
            description=f"Device {device.device_id} registered",
        )

    def device_updated(self, device, *, actor: User | None, changed_fields: list[str]) -> None:
        self.record(
            AuditAction.DEVICE_UPDATED,
            actor=actor,
            entity_type="iot_device",
            entity_id=device.id,
            metadata={"device_id": device.device_id, "changed_fields": changed_fields},
            description=f"Device {device.device_id} updated",
        )

    def device_removed(self, device, *, actor: User | None = None, readings: int = 0) -> None:
        """The one audit entry that records telemetry being deleted with a device."""
        self.record(
            AuditAction.DEVICE_UPDATED,
            actor=actor,
            entity_type="iot_device",
            entity_id=device.id,
            metadata={"device_id": device.device_id, "removed": True, "readings_deleted": readings},
            description=(
                f"Device {device.device_id} removed"
                + (f" with {readings} reading(s)" if readings else "")
            ),
        )

    def device_status_changed(
        self,
        device,
        *,
        actor: User | None,
        previous: str,
        new: str,
        automatic: bool = False,
        reason: str | None = None,
    ) -> None:
        """Record a status transition.

        ``automatic`` marks a change the platform made on its own (the offline
        sweep, or a packet arriving) rather than one a person requested — the
        audit log should not suggest an operator did something they did not.
        """
        self.record(
            AuditAction.DEVICE_STATUS_CHANGED,
            actor=actor,
            entity_type="iot_device",
            entity_id=device.id,
            metadata={
                "device_id": device.device_id,
                "previous_status": str(previous),
                "new_status": str(new),
                "automatic": automatic,
                "reason": reason,
            },
            description=(
                f"Device {device.device_id}: {previous} → {new}"
                + (" (automatic)" if automatic else "")
            ),
        )

    def telemetry_received(
        self,
        device,
        *,
        actor: User | None = None,
        source: str | None = None,
        reading_at: Any = None,
    ) -> None:
        """One entry per device per audit window, not one per packet."""
        self.record(
            AuditAction.TELEMETRY_RECEIVED,
            actor=actor,
            entity_type="iot_device",
            entity_id=device.id,
            metadata={
                "device_id": device.device_id,
                "source": source,
                "reading_at": reading_at.isoformat() if hasattr(reading_at, "isoformat") else reading_at,
            },
            description=f"Telemetry received from {device.device_id}",
        )

    # ------------------------------------------------------------------ #
    # Review
    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # Phase 5 — collections and honey batches
    # ------------------------------------------------------------------ #
    def collection_created(
        self,
        collection,
        *,
        actor: User | None,
        source_hive_codes: list[str] | None = None,
        ai_analysis_hives: int = 0,
    ) -> None:
        """A harvest was recorded.

        The metadata carries codes, counts and the recorded quantity — enough to
        reconstruct who harvested what, which hive contributed and whether an AI
        estimate was attached, without copying the whole record into the log.
        """
        self.record(
            AuditAction.COLLECTION_CREATED,
            actor=actor,
            entity_type="collection",
            entity_id=collection.id,
            metadata={
                "collection_code": collection.collection_code,
                "beekeeper_id": str(collection.beekeeper_id),
                "cluster_id": str(collection.cluster_id) if collection.cluster_id else None,
                "collection_date": collection.collection_date.isoformat(),
                "total_quantity": str(collection.total_quantity),
                "unit": str(collection.unit),
                "status": str(collection.status),
                "source_hive_codes": source_hive_codes or [],
                "ai_analysis_hives": ai_analysis_hives,
            },
            description=(
                f"Collection {collection.collection_code} recorded for "
                f"{collection.total_quantity} {collection.unit.label} from "
                f"{len(source_hive_codes or [])} hive(s)"
            ),
        )

    def collection_updated(self, collection, *, actor: User | None, fields: list[str]) -> None:
        self.record(
            AuditAction.COLLECTION_UPDATED,
            actor=actor,
            entity_type="collection",
            entity_id=collection.id,
            metadata={
                "collection_code": collection.collection_code,
                "changed_fields": fields,
                "total_quantity": str(collection.total_quantity),
            },
            description=(
                f"Collection {collection.collection_code} updated ({len(fields)} field(s))"
            ),
        )

    def collection_completed(
        self, collection, *, actor: User | None, previous: str, batch_code: str | None = None
    ) -> None:
        self.record(
            AuditAction.COLLECTION_COMPLETED,
            actor=actor,
            entity_type="collection",
            entity_id=collection.id,
            metadata={
                "collection_code": collection.collection_code,
                "previous_status": str(previous),
                "new_status": str(collection.status),
                "batch_code": batch_code,
                "total_quantity": str(collection.total_quantity),
                "unit": str(collection.unit),
            },
            description=f"Collection {collection.collection_code} completed: {previous} → {collection.status}",
        )

    def collection_cancelled(
        self, collection, *, actor: User | None, previous: str, reason: str | None = None
    ) -> None:
        self.record(
            AuditAction.COLLECTION_CANCELLED,
            actor=actor,
            entity_type="collection",
            entity_id=collection.id,
            metadata={
                "collection_code": collection.collection_code,
                "previous_status": str(previous),
                "new_status": str(collection.status),
                "reason": reason,
            },
            description=f"Collection {collection.collection_code} cancelled",
        )

    def batch_created(
        self,
        batch,
        *,
        actor: User | None,
        collection_code: str | None = None,
        source_hive_codes: list[str] | None = None,
    ) -> None:
        self.record(
            AuditAction.BATCH_CREATED,
            actor=actor,
            entity_type="batch",
            entity_id=batch.id,
            metadata={
                "batch_code": batch.batch_code,
                "collection_id": str(batch.collection_id),
                "collection_code": collection_code,
                "beekeeper_id": str(batch.beekeeper_id),
                "cluster_id": str(batch.cluster_id) if batch.cluster_id else None,
                "collection_date": batch.collection_date.isoformat(),
                "quantity": str(batch.quantity),
                "unit": str(batch.unit),
                "status": str(batch.status),
                "current_stage": str(batch.current_stage),
                "source_hive_codes": source_hive_codes or [],
            },
            description=(
                f"Batch {batch.batch_code} created from collection "
                f"{collection_code or batch.collection_id} ({batch.quantity} {batch.unit.label})"
            ),
        )

    def batch_status_changed(
        self, batch, *, actor: User | None, previous: str, new_stage: str | None = None
    ) -> None:
        """Reserved for the later phases.

        No Phase-5 endpoint calls this — a batch cannot advance past ``COLLECTED``
        until the modules that do the work exist. It is defined now so the
        vocabulary is in one place when they arrive.
        """
        self.record(
            AuditAction.BATCH_STATUS_CHANGED,
            actor=actor,
            entity_type="batch",
            entity_id=batch.id,
            metadata={
                "batch_code": batch.batch_code,
                "previous_status": str(previous),
                "new_status": str(batch.status),
                "stage": new_stage,
            },
            description=f"Batch {batch.batch_code}: {previous} → {batch.status}",
        )

    # ------------------------------------------------------------------ #
    # Phase 6: processing
    # ------------------------------------------------------------------ #
    def processing_unit_created(self, unit, *, actor: User | None) -> None:
        self.record(
            AuditAction.PROCESSING_UNIT_CREATED,
            actor=actor,
            entity_type="processing_unit",
            entity_id=unit.id,
            metadata={
                "unit_code": unit.unit_code,
                "name": unit.name,
                "district": unit.district,
                "status": str(unit.status),
            },
            description=f"Processing unit {unit.unit_code} registered",
        )

    def processing_unit_updated(self, unit, *, actor: User | None, fields: list[str]) -> None:
        self.record(
            AuditAction.PROCESSING_UNIT_UPDATED,
            actor=actor,
            entity_type="processing_unit",
            entity_id=unit.id,
            metadata={
                "unit_code": unit.unit_code,
                "changed_fields": fields,
                "status": str(unit.status),
            },
            description=f"Processing unit {unit.unit_code} updated ({len(fields)} field(s))",
        )

    def processing_created(self, run, *, actor: User | None, batch) -> None:
        """A run was opened against a batch — the batch itself is untouched here."""
        self.record(
            AuditAction.PROCESSING_CREATED,
            actor=actor,
            entity_type="processing",
            entity_id=run.id,
            metadata={
                "processing_code": run.processing_code,
                "batch_id": str(run.batch_id),
                "batch_code": getattr(batch, "batch_code", None),
                "processing_type": str(run.processing_type),
                "processing_unit_id": str(run.processing_unit_id) if run.processing_unit_id else None,
                "processing_date": run.processing_date.isoformat()
                if run.processing_date
                else None,
                "status": str(run.status),
                "batch_status": str(getattr(batch, "status", "")) or None,
            },
            description=(
                f"Processing {run.processing_code} opened for batch "
                f"{getattr(batch, 'batch_code', run.batch_id)}"
            ),
        )

    def processing_assigned(
        self, run, *, actor: User | None, processor, batch
    ) -> None:
        """A run was handed to a named processor (or re-handed to another).

        The *who* matters more than the *what* here: this is the record that
        answers "who was responsible for this honey when it was processed", and it
        names both the person who allocated it and the person who received it.
        """
        self.record(
            AuditAction.PROCESSING_ASSIGNED,
            actor=actor,
            entity_type="processing",
            entity_id=run.id,
            metadata={
                "processing_code": run.processing_code,
                "batch_id": str(run.batch_id),
                "batch_code": getattr(batch, "batch_code", None),
                "batch_status": str(getattr(batch, "status", "")) or None,
                "processor_id": str(getattr(processor, "id", "")) or None,
                "processor_name": getattr(processor, "name", None),
                "processor_email": getattr(processor, "email", None),
                "assigned_by_id": str(getattr(actor, "id", "")) or None,
                "assigned_at": run.assigned_at.isoformat() if run.assigned_at else None,
                "assignment_status": str(run.assignment_status),
                "processing_status": str(run.status),
            },
            description=(
                f"Processing {run.processing_code} assigned to "
                f"{getattr(processor, 'name', None) or getattr(processor, 'email', 'a processor')}"
            ),
        )

    def processing_accepted(self, run, *, actor: User | None, batch) -> None:
        """The named processor took the run on — the work is now theirs."""
        self.record(
            AuditAction.PROCESSING_ACCEPTED,
            actor=actor,
            entity_type="processing",
            entity_id=run.id,
            metadata={
                "processing_code": run.processing_code,
                "batch_id": str(run.batch_id),
                "batch_code": getattr(batch, "batch_code", None),
                "processor_id": str(run.processor_id) if run.processor_id else None,
                "processor_name": getattr(getattr(run, "processor", None), "name", None),
                "accepted_at": run.accepted_at.isoformat() if run.accepted_at else None,
                "processing_status": str(run.status),
            },
            description=f"Processing {run.processing_code} accepted by its processor",
        )

    def batch_moved_to_lab_testing(
        self, run, *, actor: User | None, batch, previous_batch_status: str
    ) -> None:
        """The hand-off: completed processing put this batch in the laboratory queue.

        Written whenever the move actually happened, so the sequence "processing
        completed → batch at LAB_TESTING → visible to the laboratory" can be
        checked from the audit trail alone rather than inferred from a status
        field that some later step might change.
        """
        self.record(
            AuditAction.BATCH_MOVED_TO_LAB_TESTING,
            actor=actor,
            entity_type="batch",
            entity_id=getattr(batch, "id", None),
            metadata={
                "batch_code": getattr(batch, "batch_code", None),
                "processing_id": str(run.id),
                "processing_code": run.processing_code,
                "previous_batch_status": previous_batch_status,
                "batch_status": str(getattr(batch, "status", "")) or None,
                "input_quantity": _as_text(run.input_quantity),
                "output_quantity": _as_text(run.output_quantity),
                "stage": "LABORATORY",
            },
            description=(
                f"Batch {getattr(batch, 'batch_code', '')} moved to laboratory testing "
                f"after processing {run.processing_code} was completed"
            ),
        )

    def lab_test_assigned(
        self, test, *, actor: User | None, technician, batch
    ) -> None:
        """A laboratory test was allocated to a named technician."""
        self.record(
            AuditAction.LAB_TEST_ASSIGNED,
            actor=actor,
            entity_type="lab_test",
            entity_id=test.id,
            metadata={
                "test_code": test.test_code,
                "sample_code": test.sample_code,
                "batch_id": str(test.batch_id),
                "batch_code": getattr(batch, "batch_code", None),
                "lab_technician_id": str(getattr(technician, "id", "")) or None,
                "lab_technician_name": getattr(technician, "name", None),
                "lab_technician_email": getattr(technician, "email", None),
                "assigned_by_id": str(getattr(actor, "id", "")) or None,
                "assigned_at": test.assigned_at.isoformat() if test.assigned_at else None,
                "assignment_status": str(test.assignment_status),
                "test_status": str(test.status),
            },
            description=(
                f"Laboratory test {test.test_code} assigned to "
                f"{getattr(technician, 'name', None) or getattr(technician, 'email', 'a technician')}"
            ),
        )

    def lab_test_accepted(self, test, *, actor: User | None, batch) -> None:
        """The named technician took the test on."""
        self.record(
            AuditAction.LAB_TEST_ACCEPTED,
            actor=actor,
            entity_type="lab_test",
            entity_id=test.id,
            metadata={
                "test_code": test.test_code,
                "sample_code": test.sample_code,
                "batch_id": str(test.batch_id),
                "batch_code": getattr(batch, "batch_code", None),
                "lab_technician_id": (
                    str(test.assigned_technician_id) if test.assigned_technician_id else None
                ),
                "accepted_at": test.accepted_at.isoformat() if test.accepted_at else None,
                "test_status": str(test.status),
            },
            description=f"Laboratory test {test.test_code} accepted by its technician",
        )

    def processing_started(self, run, *, actor: User | None, batch, previous_batch_status: str) -> None:
        """Work began; this is also the moment the batch became PROCESSING."""
        self.record(
            AuditAction.PROCESSING_STARTED,
            actor=actor,
            entity_type="processing",
            entity_id=run.id,
            metadata={
                "processing_code": run.processing_code,
                "batch_id": str(run.batch_id),
                "batch_code": getattr(batch, "batch_code", None),
                "start_time": run.start_time.isoformat() if run.start_time else None,
                "previous_batch_status": previous_batch_status,
                "batch_status": str(getattr(batch, "status", "")) or None,
            },
            description=f"Processing {run.processing_code} started",
        )

    def processing_updated(
        self, run, *, actor: User | None, changed: list[dict[str, Any]]
    ) -> None:
        """Corrections while the run is open, with the before and after of each.

        ``changed`` carries one entry per field: ``{"field", "from", "to"}``. That
        is what makes a later correction answerable — the platform can say what
        the figure was before, because it recorded it rather than overwriting it
        silently.
        """
        self.record(
            AuditAction.PROCESSING_UPDATED,
            actor=actor,
            entity_type="processing",
            entity_id=run.id,
            metadata={
                "processing_code": run.processing_code,
                "batch_id": str(run.batch_id),
                "status": str(run.status),
                "changes": changed,
            },
            description=(
                f"Processing {run.processing_code} updated "
                f"({', '.join(item['field'] for item in changed)})"
            ),
        )

    def processing_completed(
        self,
        run,
        *,
        actor: User | None,
        batch,
        previous_batch_status: str,
    ) -> None:
        """The run finished and the batch became ready for the laboratory."""
        self.record(
            AuditAction.PROCESSING_COMPLETED,
            actor=actor,
            entity_type="processing",
            entity_id=run.id,
            metadata={
                "processing_code": run.processing_code,
                "batch_id": str(run.batch_id),
                "batch_code": getattr(batch, "batch_code", None),
                "input_quantity": str(run.input_quantity),
                "output_quantity": str(run.output_quantity),
                "loss_quantity": str(run.loss_quantity) if run.loss_quantity is not None else None,
                "unit": str(run.unit),
                "completion_time": run.completion_time.isoformat() if run.completion_time else None,
                "previous_batch_status": previous_batch_status,
                "batch_status": str(getattr(batch, "status", "")) or None,
            },
            description=(
                f"Processing {run.processing_code} completed: "
                f"{run.input_quantity} → {run.output_quantity} {run.unit}"
            ),
        )

    def processing_cancelled(
        self,
        run,
        *,
        actor: User | None,
        reason: str,
        batch,
        previous_batch_status: str,
        previous_run_status: str | None = None,
    ) -> None:
        self.record(
            AuditAction.PROCESSING_CANCELLED,
            actor=actor,
            entity_type="processing",
            entity_id=run.id,
            metadata={
                "processing_code": run.processing_code,
                "batch_id": str(run.batch_id),
                "batch_code": getattr(batch, "batch_code", None),
                "reason": reason,
                "previous_status": previous_run_status or str(run.status),
                "new_status": str(run.status),
                "previous_batch_status": previous_batch_status,
                "batch_status": str(getattr(batch, "status", "")) or None,
            },
            description=f"Processing {run.processing_code} cancelled: {reason}",
        )

    # ------------------------------------------------------------------ #
    # Phase 6: laboratory
    # ------------------------------------------------------------------ #
    def laboratory_created(self, laboratory, *, actor: User | None) -> None:
        self.record(
            AuditAction.LABORATORY_CREATED,
            actor=actor,
            entity_type="laboratory",
            entity_id=laboratory.id,
            metadata={
                "laboratory_code": laboratory.laboratory_code,
                "name": laboratory.name,
                "district": laboratory.district,
                "accredited": laboratory.accredited,
                "status": str(laboratory.status),
            },
            description=f"Laboratory {laboratory.laboratory_code} registered",
        )

    def laboratory_updated(
        self, laboratory, *, actor: User | None, fields: list[str]
    ) -> None:
        self.record(
            AuditAction.LABORATORY_UPDATED,
            actor=actor,
            entity_type="laboratory",
            entity_id=laboratory.id,
            metadata={
                "laboratory_code": laboratory.laboratory_code,
                "changed_fields": fields,
                "status": str(laboratory.status),
            },
            description=f"Laboratory {laboratory.laboratory_code} updated ({len(fields)} field(s))",
        )

    def lab_parameter_configured(
        self, parameter, *, actor: User | None, changes: list[dict[str, Any]]
    ) -> None:
        """A reference range or requirement flag was set.

        This is audited in its own right because it changes what *every* future
        test will decide: the entry records the source the administrator quoted.
        """
        self.record(
            AuditAction.LAB_PARAMETER_CONFIGURED,
            actor=actor,
            entity_type="lab_parameter",
            entity_id=parameter.code,
            metadata={
                "code": parameter.code,
                "name": parameter.name,
                "unit": str(parameter.unit),
                "is_required": bool(parameter.is_required),
                "is_active": bool(parameter.is_active),
                "reference_source": parameter.reference_source,
                "changes": changes,
            },
            description=f"Laboratory parameter {parameter.code} configured",
        )

    def lab_test_created(self, test, *, actor: User | None, batch, processing) -> None:
        """A test was opened and a sample recorded against it.

        The action names both the test and the sample code, because the sample is
        the thing that physically moved: it is what makes a result traceable back
        to a specific run of a specific batch.
        """
        self.record(
            AuditAction.LAB_TEST_CREATED,
            actor=actor,
            entity_type="lab_test",
            entity_id=test.id,
            metadata={
                "test_code": test.test_code,
                "sample_code": test.sample_code,
                "batch_id": str(test.batch_id),
                "batch_code": getattr(batch, "batch_code", None),
                "processing_id": str(test.processing_id),
                "processing_code": getattr(processing, "processing_code", None),
                "laboratory_id": str(test.laboratory_id),
                "round_number": test.round_number,
                "retest_of_id": str(test.retest_of_id) if test.retest_of_id else None,
                "status": str(test.status),
                "test_date": test.test_date.isoformat() if test.test_date else None,
            },
            description=(
                f"Laboratory test {test.test_code} opened for batch "
                f"{getattr(batch, 'batch_code', test.batch_id)}"
            ),
        )

    def lab_sample_recorded(self, test, *, actor: User | None, previous: dict[str, Any]) -> None:
        """The sample's own details — quantity, unit, when and where it was taken."""
        self.record(
            AuditAction.LAB_SAMPLE_RECORDED,
            actor=actor,
            entity_type="lab_test",
            entity_id=test.id,
            metadata={
                "test_code": test.test_code,
                "sample_code": test.sample_code,
                "sample_quantity": str(test.sample_quantity),
                "sample_unit": str(test.sample_unit),
                "sample_collected_at": test.sample_collected_at.isoformat()
                if test.sample_collected_at
                else None,
                "previous": previous,
            },
            description=f"Sample {test.sample_code} recorded for test {test.test_code}",
        )

    def lab_result_recorded(self, result, *, actor: User | None, test) -> None:
        self.record(
            AuditAction.LAB_RESULT_RECORDED,
            actor=actor,
            entity_type="lab_test",
            entity_id=test.id,
            metadata={
                "test_code": test.test_code,
                "result_id": str(result.id),
                "parameter_code": result.parameter_code,
                "parameter_name": result.parameter_name,
                "value": str(result.value),
                "unit": str(result.unit),
                "status": str(result.status),
                "reference_min": str(result.reference_min) if result.reference_min is not None else None,
                "reference_max": str(result.reference_max) if result.reference_max is not None else None,
                "reference_source": result.reference_source,
            },
            description=(
                f"Result recorded for {result.parameter_code} = {result.value} "
                f"{result.unit} on test {test.test_code}"
            ),
        )

    def lab_result_updated(
        self,
        result,
        *,
        actor: User | None,
        test,
        previous: dict[str, Any],
        reason: str | None,
    ) -> None:
        """A correction to a recorded value.

        The previous value is written into the entry, so a correction can never
        be mistaken for the original measurement: the log holds both, and the
        reason the caller gave for changing it.
        """
        self.record(
            AuditAction.LAB_RESULT_UPDATED,
            actor=actor,
            entity_type="lab_test",
            entity_id=test.id,
            metadata={
                "test_code": test.test_code,
                "result_id": str(result.id),
                "parameter_code": result.parameter_code,
                "previous": previous,
                "value": str(result.value),
                "unit": str(result.unit),
                "status": str(result.status),
                "reason": reason,
            },
            description=(
                f"Result for {result.parameter_code} on test {test.test_code} corrected"
                + (f": {reason}" if reason else "")
            ),
        )

    def lab_result_removed(
        self, result, *, actor: User | None, test, reason: str | None = None
    ) -> None:
        self.record(
            AuditAction.LAB_RESULT_REMOVED,
            actor=actor,
            entity_type="lab_test",
            entity_id=test.id,
            metadata={
                "test_code": test.test_code,
                "result_id": str(result.id),
                "parameter_code": result.parameter_code,
                "removed_value": str(result.value),
                "unit": str(result.unit),
                "reason": reason,
            },
            description=(
                f"Result for {result.parameter_code} removed from test {test.test_code}"
            ),
        )

    def lab_test_completed(
        self,
        test,
        *,
        actor: User | None,
        batch,
        previous_batch_status: str,
        verdict,
        resulting_batch_status: str | None = None,
    ) -> None:
        """The test was decided, with the reasoning that produced the outcome.

        ``verdict.reasons`` is stored rather than only the result, so the log
        answers "why was this inconclusive?" months later, even if the parameter
        configuration has changed since.
        """
        self.record(
            AuditAction.LAB_TEST_COMPLETED,
            actor=actor,
            entity_type="lab_test",
            entity_id=test.id,
            metadata={
                "test_code": test.test_code,
                "sample_code": test.sample_code,
                "batch_id": str(test.batch_id),
                "batch_code": getattr(batch, "batch_code", None),
                "overall_result": str(test.overall_result),
                "result_summary": test.result_summary,
                "decided_from": "records" if not test.is_override else "override",
                "reasons": list(getattr(verdict, "reasons", []) or []),
                "failed_parameters": list(getattr(verdict, "failed_parameters", []) or []),
                "unevaluated_parameters": list(
                    getattr(verdict, "unevaluated_parameters", []) or []
                ),
                "previous_batch_status": previous_batch_status,
                # The status the batch holds *because of* this test. Passed in
                # rather than read from the row, so the entry says what happened
                # rather than what was true a moment before it happened.
                "batch_status": resulting_batch_status or (str(getattr(batch, "status", "")) or None),
            },
            description=f"Laboratory test {test.test_code} completed: {test.overall_result}",
        )

    def lab_test_overridden(
        self, test, *, actor: User | None, computed: str, reason: str
    ) -> None:
        """An administrator set the outcome by hand — the loudest entry there is."""
        self.record(
            AuditAction.LAB_TEST_OVERRIDDEN,
            actor=actor,
            entity_type="lab_test",
            entity_id=test.id,
            metadata={
                "test_code": test.test_code,
                "batch_id": str(test.batch_id),
                "computed_result": computed,
                "override_result": str(test.overall_result),
                "reason": reason,
                "overridden_from": "user_decision",
            },
            description=(
                f"Laboratory test {test.test_code} overridden by hand: "
                f"{computed} → {test.overall_result}"
            ),
        )

    def batch_decided(
        self, batch, *, actor: User | None, decision: str, test, previous_status: str
    ) -> None:
        """The batch itself changed state because of a laboratory outcome."""
        action = (
            AuditAction.BATCH_APPROVED
            if str(decision).upper() == "APPROVED"
            else AuditAction.BATCH_REJECTED
        )
        self.record(
            action,
            actor=actor,
            entity_type="batch",
            entity_id=batch.id,
            metadata={
                "batch_code": batch.batch_code,
                "previous_status": previous_status,
                "new_status": str(batch.status),
                "decision": decision,
                "test_code": getattr(test, "test_code", None),
                "sample_code": getattr(test, "sample_code", None),
                "overall_result": str(getattr(test, "overall_result", "")) or None,
                "is_override": bool(getattr(test, "is_override", False)),
            },
            description=(
                f"Batch {batch.batch_code} {str(decision).lower()} on laboratory test "
                f"{getattr(test, 'test_code', '')}"
            ),
        )

    def list_entries(self, **kwargs) -> tuple[list[AuditLog], int]:
        return self.logs.search(**kwargs)

    def history_for(self, entity_type: str, entity_id) -> list[AuditLog]:
        return self.logs.for_entity(entity_type, entity_id)

    def activity_summary(self, *, hours: int = 24) -> dict[str, Any]:
        return {
            "window_hours": hours,
            "total": self.logs.count_total(),
            "by_action": self.logs.recent_actions(hours=hours),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def purge_older_than(self, *, days: int = 365) -> int:
        """Retention helper for a future scheduled job.

        Deliberately not wired to a scheduler in this phase: audit retention is a
        policy decision, not a default.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        from sqlalchemy import delete

        result = self.session.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
        self.session.flush()
        return int(result.rowcount or 0)
