# HoneyChain — Phase 3 delivery report

**Module:** Hive Management + Smart Hive IoT Foundation
**Problem statement:** Smart India Hackathon 2026 — ID 26021
**Status:** delivered and verified end to end against PostgreSQL 17
**Database:** `honeychain_dev`, migration head `78889ff27825`

Phase 3 adds the physical layer of the platform: each beekeeper's hive registry, the devices
attached to those hives, and the telemetry pipeline a real ESP32 node will use. It extends the
Phase 1/2 stack, schema and authorisation model — nothing from the earlier phases was rebuilt, and no
new technology was introduced (PostgreSQL, FastAPI, SQLAlchemy, Alembic, React/Vite/Tailwind; MQTT
stays optional).

Module reference: `docs/iot.md`. Screens from this phase: `docs/screenshots/phase-3-*.png`.

---

## 1. What was delivered

| Layer | Delivered |
| --- | --- |
| **Database** | One migration (`78889ff27825`): `hives`, `iot_devices`, `sensor_configs`, wide `sensor_readings`, plus eight enum types (`hive_status`, `colony_strength`, `queen_status`, `device_type`, `connection_type`, `device_status`, `sensor_type`, `telemetry_source`). Alembic only, no manual DDL, and `downgrade()` drops the types explicitly. |
| **Models / repositories** | `hive`, `iot_device`, `sensor_config`, `sensor_reading` models; `HiveRepository`, `IotDeviceRepository`, `SensorConfigRepository`, `SensorReadingRepository` (batched `latest_for_devices` / `latest_per_hive`, `count_in_window`, `aggregate`). |
| **Services** | `HiveService` (registry, lifecycle, ownership, summary, filters, retirement rules), `DeviceService` (registration, derived status, heartbeat, sweep, sensor configuration), `TelemetryService` (single validation path for HTTP and MQTT), `IotMonitoringService` (fleet counters), `MqttIngestService` (optional broker consumer). |
| **Authorisation** | Six new capabilities in the central catalogue — `HIVE_READ_SELF/WRITE_SELF`, `HIVE_READ_ALL/WRITE_ALL`, `DEVICE_*`, `TELEMETRY_*` — granted to beekeepers (own scope), KVIC officers and admins (platform scope). Consumers hold none. |
| **API** | 25 new endpoints (9 hive, 16 IoT) plus `GET /health/mqtt`. |
| **Hive registry** | Platform-generated `HIVE-<DISTRICT>-NNNNN` codes from `document_sequences`, apiary location, colony strength and queen status as *beekeeper observations*, notes, status lifecycle, cluster link, filters and summary. |
| **Devices** | Registration against one of your own hives, per-device MQTT topic, five seeded sensor configurations, rename/retire, heartbeat, derived `ONLINE`/`WARNING`/`OFFLINE`, sticky `MAINTENANCE`, deletion refused while telemetry exists. |
| **Telemetry** | `POST /iot/telemetry` and batch ingest, MQTT `<prefix>/devices/{device_id}/telemetry`, idempotent on `(device_id, timestamp)`, validity bounds rejected (never clamped), `REAL_DEVICE`/`SIMULATOR`/`MANUAL` stored on every row, history with range + aggregation, last-telemetry lookup. |
| **Frontend** | `/beekeeper/hives` (registry, register, edit, status, row → detail), `/beekeeper/hives/:id` (registration, sensors, paired devices, stored history), `/beekeeper/iot` (fleet counters, device table, device panel, sensor configuration, trend chart, manual test reading), `/kvic/hives`, `/kvic/iot`, `/admin/hives`, `/admin/iot`, and monitoring blocks on all three dashboards. |
| **Scripts** | `hive_simulator.py` (HTTP and MQTT transports, `--dry-run`, `--seed`, subset of sensors), `device_status_sweep.py`. |
| **Tests** | 195 backend tests for the module (49 hives, 40 devices, 38 telemetry, 27 MQTT, plus migrations/beekeepers), 64 API smoke checks, 110 browser checks. |
| **Docs** | `docs/iot.md` (new), `docs/phase-3-report.md` (this file), and Phase-3 sections in `docs/api.md`, `docs/database.md`, `docs/architecture.md`, `docs/development-roadmap.md`, `README.md`, `run.md`. |

---

## 2. Database

```
                     hives ──1:N── iot_devices ──1:N── sensor_readings   (wide, one row per packet)
                       │              │      │
                       │              │      └──1:N── sensor_configs     (one row per sensor)
                       │              │
        beekeepers ────┘              └── beekeeper_id  (denormalised ownership)
        kvic_clusters ─┘

document_sequences   scope = HIVE:<PREFIX>   → HIVE-GNT-00001, HIVE-SMK-00005, …
```

Three decisions carried the module:

- **Ownership is copied down the chain.** `iot_devices.beekeeper_id`, `sensor_readings.hive_id` and
  `sensor_readings.beekeeper_id` are set at write time, so visibility is one indexed column — and a
  cross-owner leak would have to defeat two independent checks.
- **A wide reading row with `UNIQUE (device_id, timestamp)`.** One packet is one insert; a replayed
  packet is a no-op; a sensor the device does not carry is `NULL` and renders as "No data" rather
  than as a fabricated zero.
- **`source` is stored, not inferred.** `REAL_DEVICE` / `SIMULATOR` / `MANUAL` is written with the
  reading, so a simulated value can never be displayed as hardware data later.

Indexes are limited to the three access patterns the module actually uses — `(hive_id, timestamp)`,
`(device_id, timestamp)`, `(beekeeper_id, timestamp)` — plus `hive_code`, `device_id`,
`beekeepers.id`, `iot_devices(hive_id, status)`, `iot_devices(beekeeper_id, status)` and
`iot_devices(last_seen)` for the sweep.

---

## 3. API surface

| Group | Endpoints |
| --- | --- |
| Hives | `GET /hives`, `GET /hives/summary`, `GET /hives/filters`, `POST /hives`, `GET /hives/{id}`, `PUT /hives/{id}`, `PATCH /hives/{id}/status`, `DELETE /hives/{id}?force=`, `GET /beekeepers/me/hives` |
| Devices | `GET /iot/devices`, `GET /iot/devices/summary`, `POST /iot/devices`, `POST /iot/devices/heartbeat`, `GET|PUT|DELETE /iot/devices/{id}`, `PATCH /iot/devices/{id}/status`, `GET /iot/devices/{id}/sensors`, `PATCH /iot/devices/{id}/sensors/{sensor_type}`, `GET /iot/me/devices` |
| Telemetry | `POST /iot/telemetry`, `POST /iot/telemetry/batch`, `GET /iot/telemetry/{hive_id}`, `GET /iot/telemetry/{hive_id}/latest`, `GET /iot/last-telemetry` |
| Health | `GET /health/mqtt` |

Every response keeps the Phase-1 envelope, pagination metadata and error-code conventions; list
endpoints are paginated and bounded (`page_size ≤ 100`, batch ≤ 200 packets).

**Why one ingest path matters:** HTTP and MQTT both end in `TelemetryService.ingest`. A device moving
from the simulator to hardware changes the transport, not the contract — and no second code path can
drift away from the validation rules.

---

## 4. Authorisation

| Action | Beekeeper | KVIC officer | Admin | Consumer |
| --- | --- | --- | --- | --- |
| List/read own hives, devices, readings | ✅ | — (`*_ALL`) | — (`*_ALL`) | ❌ `403` |
| List/read any hive, device, reading | ❌ `404` | ✅ | ✅ | ❌ `403` |
| Create/edit hive, register device, configure sensors | own only | ✅ | ✅ | ❌ `403` |
| Submit telemetry | own devices | ✅ | ✅ | ❌ `403` |
| Submit telemetry for someone else's device | ❌ `403` | ✅ | ✅ | ❌ `403` |
| Delete hive/device | own only | ✅ | ✅ | ❌ `403` |

Cross-owner reads answer **404** rather than 403 — the record is not confirmed to exist. The checks
live in the services (`HiveService._assert_can_write`, `DeviceService._require_visible`,
`TelemetryService` ownership resolution), so a new route cannot forget them; routes only declare
capabilities.

Evidence: `test_hives.py`, `test_iot_devices.py`, `test_telemetry.py` cover cross-owner read, write,
register, sensor-config and delete attempts for every role, and the browser walk signs in as one
beekeeper and opens another's hive by URL, asserting that nothing about it renders.

---

## 5. The acceptance path

The phase's acceptance criterion is *simulator → MQTT/(HTTP) → FastAPI → PostgreSQL → dashboard*.
All four legs are demonstrable:

1. **Simulator** — `python -m app.scripts.hive_simulator --device ESP32-GNT-0001 --transport http
   --email beekeeper@honeychain.example.com --password HoneyPass123 --interval 30 --count 20`.
   Every packet carries `"source": "SIMULATOR"`.
2. **Ingest** — HTTP posts to `POST /api/v1/iot/telemetry` (or the batch endpoint); with a broker
   configured the same payload travels `<prefix>/devices/ESP32-GNT-0001/telemetry` and is consumed by
   `MqttIngestService`, which reports `stored` / `duplicate` / `rejected` per message.
3. **PostgreSQL** — 73 readings are stored in the development database for `HIVE-GNT-00001`
   (`sensor_readings`, every row labelled `SIMULATOR`), including 48 packets inserted in a single
   batch call and 12 posted to prove idempotency.
4. **Dashboard** — the beekeeper dashboard, hive detail and IoT monitoring screens read those rows
   through the public API and label them "produced by the development simulator, not hardware".

The broker is optional by design. In this environment `/api/v1/health/mqtt` answers
`not_configured` and the IoT screen says so in words — "Devices that publish over MQTT will not be
received until a broker is configured. Telemetry can still be submitted over HTTP … and nothing on
this screen is fabricated to fill the gap." That is the honest state of a deployment without a
broker, not a hidden failure.

**Real hardware replaces the simulator without a contract change** (`docs/iot.md` §8): same payload,
same topic, `REAL_DEVICE` source, and existing simulator rows stay attributed to the simulator.

---

## 6. Frontend

| Route | What it shows |
| --- | --- |
| `/beekeeper/hives` | Registry with summary tiles (hives, active, paired with a device, waiting for a device), filters, and rows linking to detail; register/edit modals; status change; delete with the "history is kept" rule |
| `/beekeeper/hives/:id` | Registration facts, colony/queen observations, sensor snapshot from the newest packet, paired devices with derived status, stored sensor history, MQTT topic, pair-a-device action |
| `/beekeeper/iot` | Fleet counters, ingest state (including "no MQTT broker is configured"), last-packet strip, device table, device panel with sensor configuration and trend chart, manual test reading |
| `/beekeeper` | Rebuilt as a real workspace: hive/device/offline counters, hive overview with latest readings, sensor overview, device status, quick actions — and a "Later phases" card that lists what is *not* built |
| `/kvic/hives`, `/kvic/iot`, `/admin/hives`, `/admin/iot` | The same registries and monitoring at platform scope, read-only for oversight (no edit or pair actions offered) |
| KVIC / admin dashboards | Live hive and device tiles beside their existing beekeeper/cluster work |
| Sidebar | **My Hives** and **IoT Monitoring** are live links; AI Insights, Harvest Records, Honey Batches and Alerts still carry a "Soon" badge — the platform does not pretend unfinished modules work |

Honesty rules enforced in the UI: empty states everywhere ("No telemetry data available yet", "No
device is paired with this hive yet", "No IoT devices connected"), no placeholder numbers, and every
reading attributed to its source. The sensor overview prints "No data" for a sensor a device does not
carry instead of a zero.

### Defects found and fixed while verifying this phase

| # | Defect | Fix |
| --- | --- | --- |
| 1 | `DeviceService.list_items*` were not the single list path; an early revision queried sensors and readings per row (N+1) | Batched `SensorConfigRepository.list_for_devices` + `SensorReadingRepository.latest_for_devices`, two queries per page |
| 2 | `GET /beekeepers/me/hives` and hive `PUT`/`PATCH`/detail returned `500` | Ownership resolution moved into `HiveService` with the same 404 semantics as the rest of the module |
| 3 | `to_device_summary` import error broke the IoT summary endpoint | Mapper moved to `app/schemas/iot.py` with the other mappers |
| 4 | `SensorStatus` was undefined at runtime in `to_sensor_status` | Imported from `app.schemas.hive` inside the mapper, avoiding the schema import cycle |
| 5 | MQTT consumer counters never incremented (`stats` captured per call) | Stats counted in `handle_message`, exposed at `/health/mqtt` |
| 6 | `admin_service` still reported `iot: planned`, so the admin dashboard described a delivered module as unfinished | Module status now `available` for `hives`/`iot`, and the dashboard links to the screens |
| 7 | Long dialogs (KVIC beekeeper review, cluster members) were taller than the viewport with no internal scroll, and the page behind is locked while a dialog is open — content was unreachable without zooming out | `Modal` constrained to the viewport with a sticky header/footer and a scrollable body; verified at four desktop widths and in the browser smoke |
| 8 | "Readings · last 24 h" tile read `summary.devices`, which is not a field of `IotSummary`, so it always described a different number ("Across 0 paired device(s)") | Reads `total_devices` |
| 9 | IoT filter row put Apply and Reset in separate grid cells, stretching Apply across a column | Both share one action group, matching the hive registry |
| 10 | Hive registry showed "Unknown / Unknown" for a colony nobody has assessed yet | Renders "Not assessed yet" and prefixed labels ("Colony: …", "Queen: …") once assessed |
| 11 | Truncated filter placeholders ("Search code, village or distric…") | Shorter, self-describing placeholders |
| 12 | The verification harness itself: the Vite dev server accumulates memory per navigation and crashed the renderer under this sandbox's 2 GB | The browser walk now runs against the production build (`npm run preview`), one browser per scenario group, and reads page text instead of whole documents |

Also corrected during the phase: the frontend validation schema had drifted from the backend
(`queenStatus` still used the old `REPLACED`/`MISSING` vocabulary, `deviceId` allowed `:` and
`deviceName` was optional) — the shared Zod schemas now match the Pydantic enums and patterns.

---

## 7. Verification evidence

| Check | Result | Artefact |
| --- | --- | --- |
| Backend test suite (`pytest`, PostgreSQL `honeychain_test`) | **343 passed**, exit 0 | `/tmp/pytest-final.txt` |
| Hive registry tests | 49 passed | `tests/test_hives.py` |
| Device tests | 40 passed | `tests/test_iot_devices.py` |
| Telemetry tests | 38 passed | `tests/test_telemetry.py` |
| MQTT ingest tests | 27 passed | `tests/test_mqtt_ingest.py` |
| Phase 3 API smoke (running API + real database, self-cleaning) | **64 passed, 0 failed** | `tests/api_smoke_phase3.py` |
| Phase 2 API smoke (regression) | **43 passed, 0 failed** | `tests/api_smoke_phase2.py` |
| Phase 3 browser walk | **110 passed, 0 failed**, no unexpected console errors | `tests/browser_smoke_phase3.py` |
| Frontend lint | clean (`npx eslint "src/**/*.{js,jsx}"`) | — |
| Frontend production build | success (Vite 6, 2 732 modules) | `frontend/dist` |
| Migration round trip | `upgrade head` → `downgrade base` → `upgrade head` leaves no orphan enum types | `tests/test_migrations.py` |

The browser walk covers: the beekeeper dashboard on live data; sidebar state (live vs "Soon"); the
registry including registering a hive and asserting the platform-generated `HIVE-<PREFIX>-NNNNN`
code; hive detail reaching a paired device, its sensor snapshot and stored history; IoT monitoring
with device identity, derived status, battery, signal, source labels and the MQTT topic; empty states
for a brand-new beekeeper; **cross-user isolation** (another beekeeper's hive opened by URL renders
nothing about it); admin and KVIC screens scrolling end to end; the KVIC review dialog fitting the
viewport at 100 % zoom; and no horizontal scrolling at 1280 / 1366 / 1440 / 1920 px.

---

## 8. Development data and scripts

| Item | Value |
| --- | --- |
| Seeded accounts | `admin@honeychain.example.com`, `kvic@honeychain.example.com`, `beekeeper@honeychain.example.com`, `consumer@honeychain.example.com` (DEVELOPMENT ONLY) |
| Seeded apiary | `HIVE-GNT-00001` (Tenali, Guntur) with device `ESP32-GNT-0001` and 73 stored `SIMULATOR` readings |
| Simulator | `cd backend && .venv/bin/python -m app.scripts.hive_simulator --device ESP32-GNT-0001 --transport http --email beekeeper@honeychain.example.com --password HoneyPass123 --interval 30 --count 20` |
| Simulator over MQTT | `--transport mqtt --interval 5 --count 12` once `MQTT_BROKER_URL` is set |
| Offline sweep | `cd backend && .venv/bin/python -m app.scripts.device_status_sweep` |
| Smoke fixtures | Each smoke run cleans up after itself; this run's throwaway rows were removed from `honeychain_dev` |

---

## 9. Explicitly not built (out of scope for this phase)

Disease detection, colony-health scoring, queen-presence inference, yield or harvest prediction,
alerting/notifications, actuator or remote-hive control, blockchain anchoring, QR codes, batch
traceability, harvest records, laboratory workflows and KVIC analytics do not exist in the codebase.
The UI marks Harvest Records, Honey Batches, Alerts and AI Insights as future work, and no screen
presents simulated, absent or estimated data as measured fact.

Sensor ranges documented in `docs/iot.md` are **data-validity bounds** — the limits a broken probe or
a malformed packet falls outside. They are not agricultural thresholds, and the platform attaches no
advisory meaning to a reading.
