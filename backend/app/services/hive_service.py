"""Hive management — registration, edits, status changes and scoped reads.

Scope rules (enforced here, never in the UI):

* a **beekeeper** sees and edits only the hives attached to their own beekeeper
  record — the service resolves that record from the authenticated user and
  passes its id into every query, so no request parameter can widen the result;
* an **administrator** or **KVIC officer** holds ``HIVE_READ_ALL`` /
  ``HIVE_WRITE_ALL`` and may filter across every apiary, for example by district
  or cluster.

Hive codes are generated from the same ``document_sequences`` counter the
beekeeper and cluster codes use, so the same district always produces the same
prefix (``GUNTUR`` → ``HIVE-GNT-00001``) without a hardcoded sequence anywhere.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.permissions import Permission, has_permission
from app.models.document_sequence import DocumentSequence, district_code
from app.models.enums import ColonyStrength, HiveStatus, UserRole
from app.models.hive import Hive
from app.models.user import User
from app.repositories.beekeeper_repository import BeekeeperRepository
from app.repositories.collection_repository import CollectionRepository
from app.repositories.cluster_repository import ClusterRepository
from app.repositories.hive_repository import HiveRepository
from app.repositories.iot_device_repository import IotDeviceRepository
from app.repositories.sensor_reading_repository import SensorReadingRepository
from app.services.device_service import DeviceService
from app.schemas.hive import (
    HiveCreate,
    HiveDetail,
    HiveFilterOptions,
    HiveListItem,
    HiveStatusUpdate,
    HiveSummary,
    HiveUpdate,
    to_hive_detail,
    to_hive_list_item,
)
from app.services.audit_service import AuditService

logger = get_logger("service")

#: Only these fields are ever copied from a payload onto a row.
_EDITABLE_FIELDS = (
    "bee_species",
    "queen_status",
    "colony_strength",
    "installation_date",
    "village",
    "mandal",
    "district",
    "state",
    "pincode",
    "latitude",
    "longitude",
    "notes",
)


class HiveService:
    """Business rules for the hive registry."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.hives = HiveRepository(session)
        self.beekeepers = BeekeeperRepository(session)
        # Staff place hives in clusters; the lookup for the target lives here.
        self.clusters = ClusterRepository(session)
        self.devices = IotDeviceRepository(session)
        self.readings = SensorReadingRepository(session)
        # Harvest history matters to the registry: a hive that has contributed
        # honey to a recorded collection can no longer be erased, because the
        # batch made from that harvest must keep tracing back to a real hive.
        self.collections = CollectionRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ #
    # Scope helpers
    # ------------------------------------------------------------------ #
    def _owner_record(self, user: User):
        """Resolve the caller's beekeeper record, or ``None`` for staff roles."""
        return self.beekeepers.get_by_user_id(user.id)

    @staticmethod
    def scope_of(user: User) -> str:
        """``"self"`` or ``"all"`` — which authorisation level applies."""
        if has_permission(user.role, Permission.HIVE_READ_ALL):
            return "all"
        return "self"

    def _assert_can_write(self, user: User, hive: Hive) -> None:
        """A self-scoped caller may only touch hives they own.

        The rejection is a 404, matching reads: a beekeeper who guesses another
        hive's id should not be able to tell a hive that exists from one that
        does not. The attempt is still logged and audited as a denial.
        """
        if has_permission(user.role, Permission.HIVE_WRITE_ALL):
            return
        owner = self._owner_record(user)
        if owner is None or hive.beekeeper_id != owner.id:
            logger.warning(
                "Hive write denied",
                extra={
                    "user_id": str(user.id),
                    "role": str(user.role),
                    "hive_id": str(hive.id),
                },
            )
            raise NotFoundError("Hive not found")

    def _require_visible(self, user: User, hive: Hive) -> None:
        if has_permission(user.role, Permission.HIVE_READ_ALL):
            return
        owner = self._owner_record(user)
        if owner is None or hive.beekeeper_id != owner.id:
            # 404 rather than 403: a beekeeper should not be able to probe which
            # hive ids exist on the platform.
            raise NotFoundError("Hive not found")

    # ------------------------------------------------------------------ #
    # Codes
    # ------------------------------------------------------------------ #
    @staticmethod
    def build_hive_code(district: str | None, sequence: str) -> str:
        return f"HIVE-{district_code(district)}-{sequence}"

    def generate_hive_code(self, district: str | None) -> str:
        """Reserve the next code for this district inside the caller's transaction."""
        prefix = f"HIVE-{district_code(district)}"
        sequence = DocumentSequence.next_value(self.session, f"HIVE:{prefix}", width=5)
        code = self.build_hive_code(district, sequence)
        if self.hives.code_exists(code):  # pragma: no cover - defensive
            raise ValidationError("Could not allocate a unique hive code, please retry")
        return code

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def create(self, user: User, payload: HiveCreate) -> Hive:
        """Register a hive for the calling beekeeper.

        The owner, the hive code and the timestamps are derived here — a
        payload carrying ``hive_code``, ``beekeeper_id`` or ``created_at`` is
        rejected by the schema (``extra="forbid"``) rather than silently
        ignored.
        """
        beekeeper = self._owner_record(user)
        if beekeeper is None:
            raise ForbiddenError(
                "Only a beekeeper can register a hive",
                details={"hint": "Staff roles manage hives through the KVIC/administration views."},
            )

        district = payload.district or beekeeper.district
        hive = self.hives.create(
            hive_code=self.generate_hive_code(district),
            beekeeper_id=beekeeper.id,
            # A hive registered by a beekeeper inside a cluster inherits that
            # cluster; staff can move it later.
            cluster_id=beekeeper.kvic_cluster_id,
            bee_species=payload.bee_species,
            queen_status=payload.queen_status,
            colony_strength=payload.colony_strength,
            installation_date=payload.installation_date or date.today(),
            village=payload.village,
            mandal=payload.mandal,
            district=district,
            state=payload.state or beekeeper.state,
            pincode=payload.pincode,
            latitude=payload.latitude,
            longitude=payload.longitude,
            notes=payload.notes,
            status=HiveStatus.ACTIVE,
        )
        self.audit.hive_created(hive, actor=user)
        self.hives.commit()
        logger.info(
            "Hive registered",
            extra={"hive_code": hive.hive_code, "beekeeper_code": beekeeper.beekeeper_code},
        )
        return hive

    def update(self, user: User, hive_id: uuid.UUID, payload: HiveUpdate) -> Hive:
        hive = self.get(hive_id)
        self._assert_can_write(user, hive)

        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise ValidationError("No changes supplied")

        for field, value in changes.items():
            if field in _EDITABLE_FIELDS:
                setattr(hive, field, value)

        # Keep the two denormalised location fields consistent: a hive with no
        # state of its own follows its owner's, and never falls back to an
        # invented value.
        if not hive.state:
            owner = self.beekeepers.get(hive.beekeeper_id)
            hive.state = owner.state if owner else None
        if not hive.district:
            owner = self.beekeepers.get(hive.beekeeper_id)
            hive.district = owner.district if owner else None

        self.audit.hive_updated(hive, actor=user, changed_fields=sorted(changes))
        self.hives.commit()
        return hive

    def set_status(self, user: User, hive_id: uuid.UUID, payload: HiveStatusUpdate) -> Hive:
        """Route-facing wrapper: unwraps the payload and keeps the reason for the log."""
        hive = self.change_status(
            user, hive_id, payload.status, reason=payload.reason, previous_status=None
        )
        return hive

    def change_status(
        self,
        user: User,
        hive_id: uuid.UUID,
        status: HiveStatus,
        *,
        reason: str | None = None,
        previous_status: HiveStatus | None = None,
    ) -> Hive:
        """Move a hive through its lifecycle.

        Hives are never deleted: ``REMOVED`` takes a hive out of service while
        its devices, readings and history stay queryable.
        """
        hive = self.get(hive_id)
        self._assert_can_write(user, hive)

        if hive.status == status:
            return hive

        previous = previous_status or hive.status
        hive.status = status
        self.audit.hive_status_changed(
            hive, actor=user, previous=previous, new=status, reason=reason
        )
        self.hives.commit()
        logger.info(
            "Hive status changed",
            extra={"hive_code": hive.hive_code, "from": str(previous), "to": str(status)},
        )
        return hive

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get(self, hive_id: uuid.UUID) -> Hive:
        hive = self.hives.get_with_relations(hive_id)
        if hive is None:
            raise NotFoundError("Hive not found")
        return hive

    def get_for(self, user: User, hive_id: uuid.UUID) -> Hive:
        hive = self.get(hive_id)
        self._require_visible(user, hive)
        return hive

    def list_hives(
        self,
        user: User,
        *,
        page: int = 1,
        page_size: int = 20,
        status: HiveStatus | None = None,
        search: str | None = None,
        cluster_id: uuid.UUID | None = None,
        district: str | None = None,
        state: str | None = None,
        bee_species: str | None = None,
        colony_strength: ColonyStrength | None = None,
        has_device: bool | None = None,
        has_cluster: bool | None = None,
        include_removed: bool = False,
        beekeeper_id: uuid.UUID | None = None,
    ) -> tuple[list[Hive], int]:
        scope = self.scope_of(user)
        owner_filter = None
        if scope == "self":
            owner = self._owner_record(user)
            if owner is None:
                # Staff-less roles with no apiary simply have no hives; an empty
                # page is the honest answer, not an error.
                return [], 0
            owner_filter = owner.id
        elif beekeeper_id is not None:
            # Staff narrowing an explicit directory request.
            owner_filter = beekeeper_id

        return self.hives.search(
            page=page,
            page_size=page_size,
            status=status,
            search=search,
            beekeeper_id=owner_filter,
            cluster_id=cluster_id,
            district=district,
            state=state,
            bee_species=bee_species,
            colony_strength=colony_strength,
            has_device=has_device,
            has_cluster=has_cluster,
            include_removed=include_removed,
        )

    def list_for_beekeeper_user(self, user: User) -> list[Hive]:
        """``GET /beekeepers/me/hives`` — every hive the caller owns."""
        owner = self._owner_record(user)
        if owner is None:
            raise ForbiddenError(
                "Only a beekeeper has hives",
                details={"your_role": str(user.role)},
            )
        return self.hives.list_for_beekeeper(owner.id)

    def list_items(
        self,
        user: User,
        *,
        page: int = 1,
        page_size: int = 20,
        status: HiveStatus | None = None,
        search: str | None = None,
        district: str | None = None,
        state: str | None = None,
        bee_species: str | None = None,
        colony_strength: ColonyStrength | None = None,
        cluster_id: uuid.UUID | None = None,
        beekeeper_id: uuid.UUID | None = None,
        has_device: bool | None = None,
        has_cluster: bool | None = None,
        include_removed: bool = False,
    ) -> tuple[list[HiveListItem], int]:
        """Paginated list payload: each hive with its primary device and last reading.

        The devices and readings for the whole page are fetched in two batched
        queries (``latest_per_hive`` uses ``DISTINCT ON``), so a 20-row page does
        not issue 40 extra queries.
        """
        rows, total = self.list_hives(
            user,
            page=page,
            page_size=page_size,
            status=status,
            search=search,
            district=district,
            state=state,
            bee_species=bee_species,
            colony_strength=colony_strength,
            cluster_id=cluster_id,
            beekeeper_id=beekeeper_id,
            has_device=has_device,
            has_cluster=has_cluster,
            include_removed=include_removed,
        )
        return self._decorate(rows), total

    def _decorate(self, hives: list[Hive]) -> list[HiveListItem]:
        if not hives:
            return []

        device_map: dict[uuid.UUID, list] = {}
        for hive in hives:
            devices = list(getattr(hive, "devices", []) or [])
            if not devices:
                devices = self.devices.list_for_hive(hive.id)
            device_map[hive.id] = devices

        latest = self.readings.latest_per_hive([hive.id for hive in hives])
        device_service = DeviceService(self.session)

        items: list[HiveListItem] = []
        for hive in hives:
            devices = device_map[hive.id]
            items.append(
                to_hive_list_item(
                    hive,
                    device=devices[0] if devices else None,
                    reading=latest.get(hive.id),
                    device_count=len(devices),
                    # Stored statuses can lag one sweep; the badge always shows
                    # the status derived from last_seen.
                    device_status=device_service.derive_status(devices[0]) if devices else None,
                )
            )
        return items

    def detail(self, user: User, hive_id: uuid.UUID) -> HiveDetail:
        """Everything the hive detail screen shows, in one payload."""
        hive = self.get_for(user, hive_id)
        devices = self.devices.list_for_hive(hive.id)
        readings_by_device = {device.id: self.readings.latest_for_device(device.id) for device in devices}
        # The hive's "latest reading" is the newest of its devices' readings, so
        # a hive with two nodes shows the freshest packet rather than the first
        # device's.
        candidates = [reading for reading in readings_by_device.values() if reading is not None]
        latest = max(candidates, key=lambda reading: reading.timestamp) if candidates else None

        device_service = DeviceService(self.session)
        return to_hive_detail(
            hive,
            devices=devices,
            readings_by_device=readings_by_device,
            latest=latest,
            primary_device=devices[0] if devices else None,
            statuses={
                device.id: device_service.derive_status(device) for device in devices
            },
        )

    def delete(self, user: User, hive_id: uuid.UUID, *, force: bool = False) -> dict:
        """Retire a hive.

        Telemetry history is evidence: a hive that has devices or readings is
        never silently erased. It moves to ``REMOVED`` instead, which keeps the
        series interpretable and the audit trail complete. A hive that has
        contributed honey to a recorded collection is treated the same way — its
        harvest, and the batch made from it, must keep resolving to a real hive —
        so from Phase 5 on only a hive with no history at all can be deleted
        outright.
        """
        hive = self.get(hive_id)
        self._assert_can_write(user, hive)

        devices = self.devices.list_for_hive(hive.id)
        readings = self.readings.count_in_window(hive_id=hive.id)
        harvests = self.collections.count_for_hive(hive.id)

        if (devices or readings or harvests) and not force:
            raise ConflictError(
                "This hive still has devices, telemetry or harvest history",
                details={
                    "hive_code": hive.hive_code,
                    "device_count": len(devices),
                    "reading_count": readings,
                    "collection_count": harvests,
                    "hint": "Retry with ?force=true to mark the hive REMOVED instead.",
                },
            )

        if devices or readings or harvests:
            previous = hive.status
            hive.status = HiveStatus.REMOVED
            self.audit.hive_removed(hive, actor=user, hard=False)
            self.audit.hive_status_changed(
                hive, actor=user, previous=previous, new=HiveStatus.REMOVED, reason="Hive deleted"
            )
            self.hives.commit()
            logger.info(
                "Hive soft-deleted",
                extra={
                    "hive_code": hive.hive_code,
                    "devices": len(devices),
                    "readings": readings,
                    "collections": harvests,
                },
            )
            kept = f"{len(devices)} device(s) and {readings} reading(s)"
            if harvests:
                kept += f", plus {harvests} harvest record(s)"
            return {
                "id": str(hive.id),
                "hive_code": hive.hive_code,
                "status": str(HiveStatus.REMOVED),
                "soft_deleted": True,
                "devices_preserved": len(devices),
                "readings_preserved": readings,
                "collections_preserved": harvests,
                "message": f"Hive {hive.hive_code} marked REMOVED. Its {kept} were kept.",
            }

        code = hive.hive_code
        self.audit.hive_removed(hive, actor=user, hard=True)
        self.hives.delete(hive)
        self.hives.commit()
        logger.info("Hive deleted", extra={"hive_code": code})
        return {
            "id": None,
            "hive_code": code,
            "status": None,
            "soft_deleted": False,
            "devices_preserved": 0,
            "readings_preserved": 0,
            "collections_preserved": 0,
            "message": f"Hive {code} deleted.",
        }

    def summary(self, user: User) -> HiveSummary:
        owner = None if self.scope_of(user) == "all" else self._owner_record(user)
        owner_id = owner.id if owner else None
        counts = self.hives.device_counts(beekeeper_id=owner_id)
        return HiveSummary(
            total=self.hives.count_all(beekeeper_id=owner_id),
            by_status=self.hives.count_by_status(beekeeper_id=owner_id),
            with_device=counts["with_device"],
            without_device=counts["without_device"],
            # Staff only: hives whose owner has no cluster, i.e. the ones no
            # cluster view can see yet. A beekeeper sees their own cluster on the
            # hive page instead of being handed a platform-wide worklist.
            without_cluster=self.hives.count_without_cluster() if owner_id is None else 0,
        )

    def change_cluster(
        self,
        user: User,
        hive_id: uuid.UUID,
        *,
        cluster_id: uuid.UUID | None,
        reason: str | None = None,
    ) -> Hive:
        """Place one hive in a cluster, or clear its cluster (staff only).

        A beekeeper never calls this: their hives inherit the cluster of their own
        membership, and letting them choose one would let them publish an apiary
        into a cluster they do not belong to. Staff use it for the two cases the
        inheritance cannot cover — an administrator resolving a hive whose owner
        has no cluster, and a hive physically moved to another district.
        """
        hive = self.get(hive_id)
        if self.scope_of(user) != "all":
            raise ForbiddenError(
                "Only KVIC officers and administrators can assign a hive to a cluster",
                details={
                    "hint": (
                        "A hive follows the cluster of the beekeeper who owns it. "
                        "Ask your KVIC officer to change that."
                    )
                },
            )

        previous = self.clusters.get(hive.cluster_id) if hive.cluster_id else None
        if cluster_id is None:
            if previous is None:
                raise ValidationError(
                    "This hive is not in a cluster", details={"field": "cluster_id"}
                )
            target = None
        else:
            target = self.clusters.get(cluster_id)
            if target is None:
                raise NotFoundError("Cluster not found", details={"field": "cluster_id"})
            if not target.is_active:
                raise ValidationError(
                    "This cluster is inactive and cannot receive hives",
                    details={"field": "cluster_id"},
                )
            if previous is not None and previous.id == target.id:
                raise ValidationError(
                    "This hive is already in that cluster", details={"field": "cluster_id"}
                )

        self.hives.set_cluster(hive, target.id if target else None)
        self.audit.hive_cluster_changed(hive, actor=user, previous_cluster=previous, cluster=target)
        if reason:
            self.audit.record(
                "CLUSTER_RELATIONSHIP_UPDATED",
                actor=user,
                entity_type="hive",
                entity_id=hive.id,
                metadata={
                    "hive_code": hive.hive_code,
                    "reason": reason,
                    "cluster_code": target.cluster_code if target else None,
                },
                description=f"Hive {hive.hive_code} cluster placement: {reason}",
            )
        self.hives.commit()
        logger.info(
            "Hive cluster changed",
            extra={
                "hive_code": hive.hive_code,
                "cluster_code": target.cluster_code if target else None,
            },
        )
        return hive

    def filter_options(self, user: User) -> HiveFilterOptions:
        if self.scope_of(user) == "all":
            return HiveFilterOptions(
                districts=self.hives.distinct_districts(),
                bee_species=self.hives.distinct_bee_species(),
                statuses=HiveStatus.values(),
            )
        # A beekeeper only ever needs the values present in their own apiary.
        owner = self._owner_record(user)
        if owner is None:
            return HiveFilterOptions(districts=[], bee_species=[], statuses=HiveStatus.values())
        hives = self.hives.list_for_beekeeper(owner.id)
        return HiveFilterOptions(
            districts=sorted({hive.district for hive in hives if hive.district}),
            bee_species=sorted({hive.bee_species for hive in hives if hive.bee_species}),
            statuses=HiveStatus.values(),
        )

    # ------------------------------------------------------------------ #
    # Internal helpers used by the IoT module
    # ------------------------------------------------------------------ #
    def owned_hive_or_403(self, user: User, hive_id: uuid.UUID) -> Hive:
        """Resolve a hive for a write that must belong to the caller."""
        hive = self.get_for(user, hive_id)
        self._assert_can_write(user, hive)
        return hive

    def staff_scope_ids(self, user: User) -> list[uuid.UUID] | None:
        """``None`` for staff (no restriction), otherwise the caller's hive ids."""
        if self.scope_of(user) == "all":
            return None
        owner = self._owner_record(user)
        if owner is None:
            return []
        return self.hives.ids_for_beekeeper(owner.id)


def role_can_manage_all(user: User) -> bool:
    """True when the caller manages hives platform-wide."""
    return has_permission(user.role, Permission.HIVE_WRITE_ALL) or user.role == UserRole.ADMIN


__all__ = ["HiveService", "role_can_manage_all"]
