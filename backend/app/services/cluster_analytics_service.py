"""The cluster as an operational view — never as a second copy of the data.

A KVIC cluster is an organisational unit, not a datastore. Everything a cluster
screen shows is the *same row* its beekeeper sees, reached by walking the
relationships:

``cluster → beekeepers → hives → devices → readings``
``cluster → hives → AI analyses``

Consequences that this module is built around:

* **Nothing is duplicated.** There is no ``kvic_hives`` table, no telemetry copy
  and no per-cluster AI record. A hive created by a beekeeper appears in their
  cluster the moment it is stored, because it was stored *with* the cluster link
  its owner gave it.
* **Nothing is hardcoded.** Every counter in :meth:`overview` is a ``COUNT`` over
  rows in scope. An empty cluster reports zeros, which is a true statement about
  it.
* **Nothing is widened by the caller.** The hive set is resolved from the cluster
  id through :meth:`HiveRepository.ids_for_cluster`; no request parameter can add
  a hive to a cluster's view.

The counting rules themselves live where they already lived — hive statuses in
``HiveRepository``, derived device statuses in ``IotMonitoringService``, AI bands
and alerts in ``AiService`` — so the cluster view cannot drift away from the
beekeeper's own dashboard. Two views, one arithmetic.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError
from app.models.enums import HiveStatus, VerificationStatus
from app.repositories.beekeeper_repository import BeekeeperRepository
from app.repositories.cluster_repository import ClusterRepository
from app.repositories.hive_repository import HiveRepository
from app.repositories.iot_device_repository import IotDeviceRepository
from app.repositories.sensor_reading_repository import SensorReadingRepository
from app.services.ai_service import AiService
from app.services.hive_service import HiveService
from app.services.iot_monitoring_service import IotMonitoringService
from app.services.device_service import DeviceService

#: The statuses counted as "active" on a cluster dashboard. ``REMOVED`` hives are
#: out of service by definition; ``INACTIVE``/``MAINTENANCE`` are in the
#: registry but not producing, so they are reported separately rather than
#: folded into the headline figure.
_ACTIVE_HIVE_STATUSES = (HiveStatus.ACTIVE,)


class ClusterAnalyticsService:
    """Read-only aggregation of one cluster's beekeepers, hives, IoT and AI state."""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.clusters = ClusterRepository(session)
        self.beekeepers = BeekeeperRepository(session)
        self.hives = HiveRepository(session)
        self.devices = IotDeviceRepository(session)
        self.readings = SensorReadingRepository(session)
        self.ai = AiService(session, self.settings)
        self.iot = IotMonitoringService(session, self.settings)
        self.device_service = DeviceService(session, self.settings)
        self.hive_service = HiveService(session)

    # ------------------------------------------------------------------ #
    # Scope resolution
    # ------------------------------------------------------------------ #
    def get_cluster(self, cluster_id: uuid.UUID):
        cluster = self.clusters.get(cluster_id)
        if cluster is None:
            raise NotFoundError("Cluster not found")
        return cluster

    def hive_ids(self, cluster_id: uuid.UUID) -> list[uuid.UUID]:
        """The hives in this cluster — the scope every other read is built on."""
        return self.hives.ids_for_cluster(cluster_id)

    def beekeeper_ids(self, cluster_id: uuid.UUID) -> list[uuid.UUID]:
        members, _total = self.beekeepers.list_by_cluster(cluster_id, page=1, page_size=10_000)
        return [member.id for member in members]

    # ------------------------------------------------------------------ #
    # The dashboard
    # ------------------------------------------------------------------ #
    def overview(self, cluster_id: uuid.UUID) -> dict:
        """Every counter a cluster dashboard needs, counted from real rows."""
        cluster = self.get_cluster(cluster_id)
        hive_ids = self.hive_ids(cluster_id)

        members, total_members = self.beekeepers.list_by_cluster(
            cluster_id, page=1, page_size=10_000
        )
        verification: dict[str, int] = {status.value: 0 for status in VerificationStatus}
        for member in members:
            key = str(member.verification_status)
            verification[key] = verification.get(key, 0) + 1

        hive_by_status = self.hives.count_by_status(cluster_id=cluster_id)
        device_counts = self.hives.device_counts(cluster_id=cluster_id)
        iot = self.iot.summary_for_hive_ids(hive_ids)
        ai = self.ai.summary_for_hive_ids(hive_ids)

        return {
            "cluster": {
                "id": cluster.id,
                "cluster_code": cluster.cluster_code,
                "cluster_name": cluster.cluster_name,
                "district": cluster.district,
                "state": cluster.state,
                "is_active": cluster.is_active,
                "coordinator_name": cluster.coordinator_name,
                "coordinator_phone": cluster.coordinator_phone,
            },
            "beekeepers": {
                "total": total_members,
                "verified": verification.get(VerificationStatus.VERIFIED.value, 0),
                "pending": verification.get(VerificationStatus.PENDING.value, 0),
                "under_review": verification.get(VerificationStatus.UNDER_REVIEW.value, 0),
                "suspended": verification.get(VerificationStatus.SUSPENDED.value, 0),
                "rejected": verification.get(VerificationStatus.REJECTED.value, 0),
                "by_verification_status": verification,
            },
            "hives": {
                "total": device_counts["total"],
                "active": hive_by_status.get(HiveStatus.ACTIVE.value, 0),
                "inactive": hive_by_status.get(HiveStatus.INACTIVE.value, 0),
                "maintenance": hive_by_status.get(HiveStatus.MAINTENANCE.value, 0),
                "removed": hive_by_status.get(HiveStatus.REMOVED.value, 0),
                "by_status": hive_by_status,
                "with_device": device_counts["with_device"],
                "without_device": device_counts["without_device"],
            },
            "devices": {
                "total": iot["total_devices"],
                "online": iot["connected_devices"],
                "offline": iot["offline_devices"],
                "warning": iot["warning_devices"],
                "maintenance": iot["maintenance_devices"],
                "sensors_active": iot["sensors_active"],
                "last_seen_at": iot["last_telemetry_at"],
                "offline_threshold_seconds": iot["offline_threshold_seconds"],
            },
            "telemetry": {
                "readings_last_24h": iot["readings_last_window"],
                "latest_reading_at": iot["last_telemetry_at"],
                "hives_with_telemetry": ai["hives_with_telemetry"],
                "hives_without_telemetry": max(
                    len(hive_ids) - ai["hives_with_telemetry"], 0
                ),
            },
            "ai": {
                "analysed_hives": ai["analysed_hives"],
                "hives_without_analysis": ai["hives_without_analysis"],
                "health": ai["health"],
                "disease_risk": ai["disease_risk"],
                "swarming_risk": ai["swarming_risk"],
                "yield_projection": ai["yield"],
                "open_alerts": ai["open_alerts"],
                "alerts_by_severity": ai["alerts_by_severity"],
                "model": ai["model"],
            },
            "generated_at": datetime.now(timezone.utc),
        }

    # ------------------------------------------------------------------ #
    # The cluster's honey batches, and what they amount to
    # ------------------------------------------------------------------ #
    def batch_analytics(self, cluster_id: uuid.UUID) -> dict:
        """Every figure the cluster asks of its batches, counted from the rows.

        This is the **batch** relationship the KVIC screens manage
        (``cluster → honey batches → collections → beekeepers → hives``), and it
        is computed from exactly the rows the cluster's batch table shows — the
        same ``BatchListItem`` values the officer reads beside the counters — so
        a number here cannot disagree with the list under it.

        Nothing is duplicated and nothing is estimated: each counter is the size
        of a filtered set of the beekeepers' own batches, their own stage records
        and their own laboratory tests. A cluster with no batches reports zeros.
        """
        # Imported here for the same reason the cluster service does it: the batch
        # service reaches the collection service, which reaches the cluster
        # repository, and a module-level import would close that circle.
        from app.services.batch_service import BatchService

        self.get_cluster(cluster_id)
        rows = BatchService(self.session).batches_for_cluster(cluster_id)

        processing = {"not_started": 0, "in_progress": 0, "completed": 0}
        laboratory = {"not_started": 0, "in_progress": 0, "approved": 0, "rejected": 0, "hold": 0}
        by_status: dict[str, int] = {}
        #: Batches that have *reached* each stage. Cumulative by nature: honey
        #: cannot be delivered without having been collected, and the counters are
        #: read as "how much of this cluster's honey has got this far".
        reached = {
            "collection": 0,
            "processing": 0,
            "laboratory": 0,
            "packaging": 0,
            "distribution": 0,
            "delivered": 0,
        }

        quantities = {"collected": Decimal("0"), "packaged": Decimal("0")}
        units: set[str] = set()
        collection_ids: set[uuid.UUID] = set()
        beekeeper_ids: set[uuid.UUID] = set()
        hive_codes: set[str] = set()
        package_count = 0
        distributed = 0
        delivered = 0
        packaged_batches = 0

        for row in rows:
            units.add(str(row.unit))
            quantities["collected"] += Decimal(str(row.quantity or 0))
            quantities["packaged"] += Decimal(str(row.packaged_quantity or 0))
            collection_ids.add(row.collection_id)
            if row.beekeeper_id is not None:
                beekeeper_ids.add(row.beekeeper_id)
            hive_codes.update(row.source_hive_codes or [])
            package_count += row.package_count or 0
            by_status[str(row.status)] = by_status.get(str(row.status), 0) + 1

            # Every batch exists because a harvest was completed, so the
            # collection stage is where the whole set stands.
            reached["collection"] += 1
            if row.processing_status in ("COMPLETED", "IN_PROGRESS"):
                reached["processing"] += 1
            processing[
                {"COMPLETED": "completed", "IN_PROGRESS": "in_progress"}.get(
                    row.processing_status, "not_started"
                )
            ] += 1

            if row.laboratory_status in ("APPROVED", "REJECTED", "INCONCLUSIVE", "IN_PROGRESS"):
                reached["laboratory"] += 1
            laboratory[
                {
                    "APPROVED": "approved",
                    "REJECTED": "rejected",
                    # INCONCLUSIVE is the laboratory's *hold*: tested, nothing
                    # decided, and the sample may be retested. Reported under the
                    # name the KVIC screens already use for it.
                    "INCONCLUSIVE": "hold",
                    "IN_PROGRESS": "in_progress",
                }.get(row.laboratory_status, "not_started")
            ] += 1

            if (row.package_count or 0) > 0 or row.packaging_status not in ("NOT_STARTED", None):
                reached["packaging"] += 1
                packaged_batches += 1

            if row.distribution_status in ("DISPATCHED", "IN_TRANSIT", "DELIVERED"):
                reached["distribution"] += 1
                distributed += 1
            if row.distribution_status == "DELIVERED":
                reached["delivered"] += 1
                delivered += 1

        return {
            "cluster_id": cluster_id,
            "totals": {
                "batches": len(rows),
                "collections": len(collection_ids),
                "beekeepers_represented": len(beekeeper_ids),
                "hives_behind_them": len(hive_codes),
                "packages": package_count,
                "quantity_collected": quantities["collected"],
                "quantity_packaged": quantities["packaged"],
                "unit": next(iter(units)) if len(units) == 1 else None,
                "mixed_units": len(units) > 1,
            },
            "status_breakdown": reached,
            "by_status": by_status,
            "processing": processing,
            "laboratory": laboratory,
            "packaging": {
                "batches_packaged": packaged_batches,
                "packages": package_count,
                "quantity_packaged": quantities["packaged"],
            },
            "distribution": {"batches_distributed": distributed, "batches_delivered": delivered},
            "generated_at": datetime.now(timezone.utc),
        }

    # ------------------------------------------------------------------ #
    # The lists behind the dashboard
    # ------------------------------------------------------------------ #
    def list_hives(
        self,
        user,
        cluster_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        status: HiveStatus | None = None,
        search: str | None = None,
        beekeeper_id: uuid.UUID | None = None,
    ):
        """Hives in this cluster, as the same rows the beekeeper sees.

        ``HiveService.list_items`` is reused deliberately: the cluster list has
        the same shape as ``My Hives`` — cluster, device count, primary device and
        latest reading — so a KVIC officer is looking at the beekeeper's own list,
        filtered by membership instead of by ownership.
        """
        self.get_cluster(cluster_id)
        return self.hive_service.list_items(
            user,
            page=page,
            page_size=page_size,
            status=status,
            search=search,
            cluster_id=cluster_id,
            beekeeper_id=beekeeper_id,
        )

    def list_devices(
        self,
        user,
        cluster_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        status=None,
        search: str | None = None,
        hive_id: uuid.UUID | None = None,
    ):
        """Devices on this cluster's hives, with their derived status."""
        self.get_cluster(cluster_id)
        cluster_hive_ids = set(self.hive_ids(cluster_id))
        device_ids = {
            device.id
            for hive in self.hives.list_for_cluster(cluster_id)
            for device in hive.devices
        }
        if hive_id is not None and hive_id not in cluster_hive_ids:
            # A hive id outside the cluster is not an error worth explaining in
            # detail: it simply contributes no devices.
            return [], 0

        rows, _total = self.device_service.list_items(
            user, page=1, page_size=10_000, search=search, status=status, hive_id=hive_id
        )
        scoped = [row for row in rows if getattr(row, "id", None) in device_ids]
        ordered = sorted(scoped, key=lambda row: (row.hive_code or "", row.device_id))
        start = (page - 1) * page_size
        return ordered[start : start + page_size], len(ordered)

    def ai_state(self, cluster_id: uuid.UUID) -> dict:
        """AI state of this cluster's hives, per hive and aggregated."""
        self.get_cluster(cluster_id)
        hive_ids = self.hive_ids(cluster_id)
        summary = self.ai.summary_for_hive_ids(hive_ids)
        latest = summary.pop("latest_analyses", {})

        hives = {hive.id: hive for hive in self.hives.list_for_cluster(cluster_id)}
        rows = []
        for hive_id, hive in hives.items():
            analysis = latest.get(str(hive_id))
            rows.append(
                {
                    "hive_id": hive_id,
                    "hive_code": hive.hive_code,
                    "status": str(hive.status),
                    "analyzed": analysis is not None,
                    "analyzed_at": analysis.analyzed_at if analysis else None,
                    "health_score": analysis.health_score if analysis else None,
                    "health_status": analysis.health_status if analysis else None,
                    "health_confidence": analysis.health_confidence if analysis else None,
                    "disease_risk_level": analysis.disease_risk_level if analysis else None,
                    "disease_risk_score": analysis.disease_risk_score if analysis else None,
                    "swarming_risk_level": analysis.swarming_risk_level if analysis else None,
                    "swarming_risk_score": analysis.swarming_risk_score if analysis else None,
                    "predicted_yield_kg": analysis.predicted_yield_kg if analysis else None,
                    "yield_period_days": analysis.yield_period_days if analysis else None,
                    "data_quality": analysis.data_quality if analysis else None,
                    "analysis_source": analysis.analysis_source if analysis else None,
                    "sample_count": analysis.sample_count if analysis else 0,
                }
            )
        rows.sort(key=lambda row: row["hive_code"])
        return {"summary": summary, "hives": rows}

    def latest_telemetry(self, cluster_id: uuid.UUID) -> dict:
        """The newest packet in the cluster, with the path it travelled.

        Returned as ``device → hive → beekeeper`` so the screen can print the
        whole chain: it is the same route the relationship is built on.
        """
        self.get_cluster(cluster_id)
        hive_ids = self.hive_ids(cluster_id)
        if not hive_ids:
            return {"has_data": False, "hive_count": 0}

        latest_by_hive = self.readings.latest_per_hive(hive_ids)
        if not latest_by_hive:
            return {"has_data": False, "hive_count": len(hive_ids)}

        newest_hive_id, newest = max(
            latest_by_hive.items(), key=lambda item: item[1].timestamp
        )
        device = self.devices.get(newest.device_id) if newest.device_id else None
        hive = self.hives.get(newest_hive_id)
        owner = self.beekeepers.get(hive.beekeeper_id) if hive else None
        return {
            "has_data": True,
            "hive_count": len(hive_ids),
            "hives_reporting": len(latest_by_hive),
            "reading": newest,
            "device": device,
            "hive": hive,
            "beekeeper": owner,
            "timestamp": newest.timestamp,
        }


__all__ = ["ClusterAnalyticsService"]
