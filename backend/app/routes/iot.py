"""IoT routes — device registration, sensor configuration and telemetry.

Two ingest paths reach the *same* validation pipeline:

* ``POST /api/v1/iot/telemetry`` — an authenticated device or a beekeeper
  entering a reading by hand;
* the MQTT consumer (``app/services/mqtt_service.py``), which is where an ESP32
  normally publishes.

Both end in ``TelemetryService.ingest``, so the contract a device codes against
does not change when it moves from the simulator to real hardware, and neither
path can be used to write into another beekeeper's series.
"""

from __future__ import annotations

import logging

import uuid
from datetime import datetime, timezone

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import db_session
from app.core.exceptions import ValidationError
from app.core.permissions import Permission, require_any_permission, require_permission
from app.models.enums import DeviceStatus, DeviceType, SensorType, TelemetrySource
from app.models.user import User
from app.schemas.common import ApiResponse, PaginationParams, ok, paginated
from app.schemas.iot import (
    DeviceCreate,
    DeviceDetail,
    DeviceListItem,
    DeviceStatusUpdate,
    DeviceUpdate,
    HeartbeatPayload,
    IotSummary,
    LastTelemetry,
    ReadingResult,
    SensorConfigPublic,
    SensorConfigUpdate,
    TelemetryHistoryResponse,
    TelemetryIngest,
    to_reading_snapshot,
    to_sensor_config_public,
    to_telemetry_points,
)
from app.services.device_service import DeviceService
from app.services.iot_monitoring_service import IotMonitoringService
from app.services.telemetry_service import TelemetryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/iot", tags=["IoT"])

READ_DEVICES = require_any_permission(Permission.DEVICE_READ_SELF, Permission.DEVICE_READ_ALL)
WRITE_DEVICES = require_any_permission(Permission.DEVICE_WRITE_SELF, Permission.DEVICE_WRITE_ALL)
READ_TELEMETRY = require_any_permission(Permission.TELEMETRY_READ_SELF, Permission.TELEMETRY_READ_ALL)


def resolve_sensor_type(value: str) -> SensorType:
    """Path segment → ``SensorType``, case-insensitively.

    The enum's *value* is the uppercase name, so a lowercase URL would otherwise
    be a 422 for no good reason. An unknown name is still a 422, with the
    accepted values listed.
    """
    try:
        return SensorType(value.strip().upper())
    except ValueError as exc:
        raise ValidationError(
            f"Unknown sensor type '{value}'",
            details={"field": "sensor_type", "allowed": SensorType.values()},
        ) from exc


# --------------------------------------------------------------------------- #
# Devices
# --------------------------------------------------------------------------- #
@router.get(
    "/devices",
    response_model=ApiResponse[list[DeviceListItem]],
    summary="List devices",
    description=(
        "Every device the caller may see. A beekeeper sees the devices on their own "
        "hives; KVIC and administrators see all devices and may filter by beekeeper."
    ),
)
def list_devices(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120, description="Device id, name or hive code."),
    status: DeviceStatus | None = Query(default=None, description="Includes the derived status."),
    hive_id: uuid.UUID | None = Query(default=None),
    beekeeper_id: uuid.UUID | None = Query(default=None, description="Staff only."),
    device_type: DeviceType | None = Query(default=None),
    actor: User = Depends(READ_DEVICES),
    session: Session = Depends(db_session),
) -> dict:
    items, total = DeviceService(session).list_items(
        actor,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        status=status,
        hive_id=hive_id,
        beekeeper_id=beekeeper_id,
        device_type=str(device_type) if device_type else None,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.get(
    "/devices/summary",
    response_model=ApiResponse[IotSummary],
    summary="IoT counters",
    description="Device, sensor and telemetry counters for the caller's scope, all from the database.",
)
def iot_summary(
    window_hours: int = Query(default=24, ge=1, le=168),
    actor: User = Depends(READ_DEVICES),
    session: Session = Depends(db_session),
) -> dict:
    return ok(IotMonitoringService(session).summary(actor, window_hours=window_hours))


@router.post(
    "/devices",
    response_model=ApiResponse[DeviceDetail],
    status_code=201,
    summary="Register a device",
    description=(
        "Attaches a new ESP32-class device to one of the caller's hives. The device "
        "starts OFFLINE and its sensor set is created with it; the MQTT topic is "
        "derived from the hardware id unless one is supplied."
    ),
)
def register_device(
    payload: DeviceCreate,
    actor: User = Depends(WRITE_DEVICES),
    session: Session = Depends(db_session),
) -> dict:
    service = DeviceService(session)
    device = service.register(actor, payload)
    return ok(service.detail(actor, device.id))


@router.post(
    "/devices/heartbeat",
    response_model=ApiResponse[dict],
    summary="Device heartbeat",
    description=(
        "A lightweight 'I am alive' from a device, with optional battery and signal "
        "readings. Ownership is enforced exactly as for telemetry."
    ),
)
def device_heartbeat(
    payload: HeartbeatPayload,
    actor: User = Depends(require_permission(Permission.TELEMETRY_INGEST)),
    session: Session = Depends(db_session),
) -> dict:
    device = DeviceService(session).heartbeat(actor, payload)
    return ok(
        {
            "device_id": device.device_id,
            "status": str(device.status),
            "last_seen": device.last_seen,
            "battery_level": device.battery_level,
            "signal_strength": device.signal_strength,
        }
    )


@router.get(
    "/devices/{device_pk}",
    response_model=ApiResponse[DeviceDetail],
    summary="Read a device",
    description="Device details, its configured sensors with their latest values, and 24h volume.",
)
def read_device(
    device_pk: uuid.UUID,
    actor: User = Depends(READ_DEVICES),
    session: Session = Depends(db_session),
) -> dict:
    return ok(DeviceService(session).detail(actor, device_pk))


@router.put(
    "/devices/{device_pk}",
    response_model=ApiResponse[DeviceDetail],
    summary="Update a device",
    description=(
        "Partial update. Re-parenting a device to another hive is allowed only "
        "between hives the caller controls."
    ),
)
def update_device(
    device_pk: uuid.UUID,
    payload: DeviceUpdate,
    actor: User = Depends(WRITE_DEVICES),
    session: Session = Depends(db_session),
) -> dict:
    service = DeviceService(session)
    device = service.update(actor, device_pk, payload)
    return ok(service.detail(actor, device.id))


@router.patch(
    "/devices/{device_pk}/status",
    response_model=ApiResponse[DeviceDetail],
    summary="Set device status",
    description=(
        "Used mainly to take a device out for MAINTENANCE. ONLINE/OFFLINE/WARNING are "
        "*derived* from ``last_seen`` and battery, so any other value here is recomputed "
        "on the next sweep — the API returns the effective status either way."
    ),
)
def update_device_status(
    device_pk: uuid.UUID,
    payload: DeviceStatusUpdate,
    actor: User = Depends(WRITE_DEVICES),
    session: Session = Depends(db_session),
) -> dict:
    service = DeviceService(session)
    device = service.change_status(actor, device_pk, payload.status, reason=payload.reason)
    return ok(service.detail(actor, device.id))


@router.delete(
    "/devices/{device_pk}",
    response_model=ApiResponse[dict],
    summary="Remove a device",
    description=(
        "Deletes the device and its sensor configuration. Readings already collected "
        "are kept: telemetry history is evidence and is never deleted with the hardware."
    ),
)
def delete_device(
    device_pk: uuid.UUID,
    confirm: bool = Query(
        default=False,
        description="Required when the device already has telemetry, which is deleted with it.",
    ),
    actor: User = Depends(WRITE_DEVICES),
    session: Session = Depends(db_session),
) -> dict:
    return ok(DeviceService(session).remove(actor, device_pk, confirm=confirm))


@router.get(
    "/devices/{device_pk}/sensors",
    response_model=ApiResponse[list[SensorConfigPublic]],
    summary="List a device's sensors",
)
def list_sensors(
    device_pk: uuid.UUID,
    actor: User = Depends(READ_DEVICES),
    session: Session = Depends(db_session),
) -> dict:
    configs = DeviceService(session).list_sensors(actor, device_pk)
    return ok([to_sensor_config_public(config) for config in configs])


@router.patch(
    "/devices/{device_pk}/sensors/{sensor_type}",
    response_model=ApiResponse[SensorConfigPublic],
    summary="Configure a sensor",
    description=(
        "Enable/disable a sensor or narrow its accepted range. The configured range "
        "is enforced when telemetry arrives; the platform's global sanity bounds "
        "always apply as well, and can never be widened from here."
    ),
)
def update_sensor(
    device_pk: uuid.UUID,
    sensor_type: str,
    payload: SensorConfigUpdate,
    actor: User = Depends(WRITE_DEVICES),
    session: Session = Depends(db_session),
) -> dict:
    """``sensor_type`` is accepted case-insensitively (``humidity`` or ``HUMIDITY``)."""
    resolved = resolve_sensor_type(sensor_type)
    config = DeviceService(session).update_sensor(actor, device_pk, resolved, payload)
    return ok(to_sensor_config_public(config))


# --------------------------------------------------------------------------- #
# Telemetry
# --------------------------------------------------------------------------- #
@router.post(
    "/telemetry",
    response_model=ApiResponse[ReadingResult],
    status_code=201,
    summary="Submit a telemetry reading",
    description=(
        "The ingest endpoint an ESP32 (or the development simulator) calls when it "
        "posts over HTTP rather than MQTT. Values are validated against the sensor's "
        "configured range; a packet for an instant already recorded is reported as a "
        "duplicate instead of being stored twice."
    ),
)
def ingest_telemetry(
    payload: TelemetryIngest,
    actor: User = Depends(require_permission(Permission.TELEMETRY_INGEST)),
    session: Session = Depends(db_session),
) -> dict:
    service = TelemetryService(session)
    # A signed-in caller can only ever be submitting their own reading, so an
    # unspecified source is MANUAL; SIMULATOR must be declared explicitly.
    source = payload.source or TelemetrySource.MANUAL
    result = service.ingest(payload, actor=actor, source=source)

    reading = result["reading"]
    device = result["device"]
    return ok(
        ReadingResult(
            device_id=device.device_id,
            hive_id=device.hive_id,
            hive_code=getattr(getattr(device, "hive", None), "hive_code", None),
            stored=not result["duplicate"],
            duplicate=result["duplicate"],
            timestamp=reading.timestamp,
            source=reading.source,
            device_status=device.status,
            battery_level=device.battery_level,
            signal_strength=device.signal_strength,
            message=(
                "Reading already recorded for this instant; nothing was duplicated."
                if result["duplicate"]
                else "Reading stored."
            ),
        )
    )


@router.post(
    "/telemetry/batch",
    response_model=ApiResponse[dict],
    status_code=201,
    summary="Submit several readings at once",
    description=(
        "For a device that buffers while offline and uploads a backlog when it "
        "reconnects. Every packet is validated independently: invalid ones are "
        "rejected with their index and reason, valid ones are still stored."
    ),
)
def ingest_telemetry_batch(
    payload: Annotated[list[TelemetryIngest], Body(min_length=1, max_length=200)],
    actor: User = Depends(require_permission(Permission.TELEMETRY_INGEST)),
    session: Session = Depends(db_session),
) -> dict:
    service = TelemetryService(session)
    stored, duplicates, rejected = 0, 0, []
    for index, packet in enumerate(payload):
        try:
            result = service.ingest(
                packet, actor=actor, source=packet.source or TelemetrySource.MANUAL
            )
        except Exception as exc:  # noqa: BLE001 - one bad packet must not drop the batch
            # A refusal the platform raised on purpose carries a message written for
            # the caller; anything else (a database error, a bug) is logged and
            # reported generically, never as its exception text.
            detail = getattr(exc, "message", None)
            if not detail:
                logger.exception("Telemetry packet %s could not be stored", index)
                detail = "The packet could not be stored."
                session.rollback()
            rejected.append({"index": index, "device_id": packet.device_id, "reason": detail})
            continue
        if result["duplicate"]:
            duplicates += 1
        else:
            stored += 1

    return ok(
        {
            "submitted": len(payload),
            "stored": stored,
            "duplicates": duplicates,
            "rejected": rejected,
            "rejected_count": len(rejected),
        }
    )


@router.get(
    "/telemetry/{hive_id}",
    response_model=ApiResponse[TelemetryHistoryResponse],
    summary="Hive telemetry history",
    description=(
        "Readings for one hive, raw or averaged into buckets. Any beekeeper may only "
        "read their own hives: another beekeeper's hive id returns 404."
    ),
)
def telemetry_history(
    hive_id: uuid.UUID,
    range_key: str | None = Query(default=None, alias="range", description="1h, 6h, 24h, 7d or 30d."),
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    interval: str | None = Query(default=None, description="1m, 5m, 15m, 30m, 1h, 6h or 1d."),
    sensor_type: str | None = Query(
        default=None,
        description="Return one series only (case-insensitive: humidity or HUMIDITY).",
    ),
    device_pk: uuid.UUID | None = Query(default=None, alias="device_id"),
    limit: int = Query(default=500, ge=1, le=2000),
    actor: User = Depends(READ_TELEMETRY),
    session: Session = Depends(db_session),
) -> dict:
    service = TelemetryService(session)
    resolved_sensor = resolve_sensor_type(sensor_type) if sensor_type else None
    result = service.history(
        actor,
        hive_id,
        start=start,
        end=end,
        range_key=range_key,
        interval=interval,
        sensor_type=resolved_sensor,
        device_pk=device_pk,
        limit=limit,
    )
    points = to_telemetry_points(result["points"])
    return ok(
        TelemetryHistoryResponse(
            hive_id=result["hive"].id,
            hive_code=result["hive"].hive_code,
            device_id=result["latest_device"].device_id if result["latest_device"] else None,
            **{"from": result["from"], "to": result["to"]},
            interval=result["interval"],
            sensor_type=str(resolved_sensor) if resolved_sensor else None,
            count=len(points),
            points=points,
            latest=to_reading_snapshot(result["latest"]),
            source_mix=result["source_mix"],
            message=(
                None
                if points
                else "No telemetry has been recorded for this hive in the selected window."
            ),
        )
    )


@router.get(
    "/telemetry/{hive_id}/latest",
    response_model=ApiResponse[dict],
    summary="Latest values per device on a hive",
    description="Drives the live panel on the hive detail screen.",
)
def telemetry_latest(
    hive_id: uuid.UUID,
    actor: User = Depends(READ_TELEMETRY),
    session: Session = Depends(db_session),
) -> dict:
    result = TelemetryService(session).latest_readings(actor, hive_id)
    return ok(
        {
            "hive_id": str(result["hive"].id),
            "hive_code": result["hive"].hive_code,
            "latest": to_reading_snapshot(result["latest"]),
            "devices": [
                {
                    "id": str(entry["device"].id),
                    "device_id": entry["device"].device_id,
                    "device_name": entry["device"].device_name,
                    "status": str(entry["status"]),
                    "last_seen": entry["device"].last_seen,
                    "reading": to_reading_snapshot(entry["reading"]),
                }
                for entry in result["devices"]
            ],
        }
    )


@router.get(
    "/last-telemetry",
    response_model=ApiResponse[LastTelemetry],
    summary="Most recent reading in scope",
    description=(
        "Used by the monitoring header to say *when* the platform last received "
        "anything, and from where. Returns null when nothing has been recorded — "
        "an empty account is reported as empty, never as a plausible default."
    ),
)
def last_telemetry(
    actor: User = Depends(READ_TELEMETRY),
    session: Session = Depends(db_session),
) -> dict:
    checked_at = datetime.now(timezone.utc)
    result = IotMonitoringService(session).last_telemetry(actor)
    if result is None:
        # An account with no telemetry is reported as empty — never as a
        # plausible-looking default.
        return ok(
            LastTelemetry(
                has_data=False,
                checked_at=checked_at,
                message="No telemetry has been received yet.",
            )
        )
    reading, device, hive = result["reading"], result["device"], result["hive"]
    snapshot = to_reading_snapshot(reading)
    return ok(
        LastTelemetry(
            has_data=True,
            checked_at=checked_at,
            timestamp=reading.timestamp,
            device_id=getattr(device, "device_id", None),
            device_name=getattr(device, "device_name", None),
            hive_code=getattr(hive, "hive_code", None),
            source=snapshot.source_label if snapshot else None,
            temperature=snapshot.temperature if snapshot else None,
            humidity=snapshot.humidity if snapshot else None,
            weight=snapshot.weight if snapshot else None,
            vibration=snapshot.vibration if snapshot else None,
            acoustic_level=snapshot.acoustic_level if snapshot else None,
        )
    )


@router.get(
    "/me/devices",
    response_model=ApiResponse[list[DeviceListItem]],
    summary="My devices",
    description="Convenience listing for the signed-in beekeeper's own apiary.",
)
def my_devices(
    actor: User = Depends(READ_DEVICES),
    session: Session = Depends(db_session),
) -> dict:
    return ok(DeviceService(session).list_items_for_user(actor))


__all__ = ["router"]
