# Smart Hive IoT — module reference (Phase 3)

This document describes the hive registry and the smart-hive telemetry foundation:
what exists, what a device may send, how a reading is validated and stored, and
how to move from the development simulator to real ESP32 hardware without
changing the contract.

It is the reference implementation companion to `firmware/esp32_hive_node/esp32_hive_node.ino`
and to the tests in `backend/tests/test_hives.py`, `test_iot_devices.py`,
`test_telemetry.py` and `test_mqtt_ingest.py`.

---

## 1. Scope — and what is deliberately *not* claimed

**Delivered in this phase**

* A hive registry: platform-generated `hive_code`, apiary location, colony and
  queen observations, status lifecycle, cluster/beekeeper links.
* Devices bound to a hive, with ownership enforced on the server.
* Per-device sensor configuration seeded from the hardware profile.
* A telemetry pipeline — HTTP and MQTT — behind one validation path
  (`TelemetryService.ingest`), storing wide `sensor_readings` rows.
* Device health: derived `ONLINE` / `WARNING` / `OFFLINE` status, `MAINTENANCE`
  override, heartbeat, offline sweep, `/api/v1/health/mqtt`.
* Dashboards: beekeeper, KVIC and admin surfaces over the same APIs, with an
  explicit `REAL_DEVICE` / `SIMULATOR` / `MANUAL` label on every reading.

**Deliberately out of scope** (later phases; do not describe these as working)

* No disease detection, colony-health scoring, queen-presence inference or yield
  prediction. The platform stores what a sensor measured; it does not interpret it.
* No blockchain anchoring of hive events, no QR/batch traceability.
* No actuator commands, hive-access control or remote hive operations.
* The sensor ranges below are **data-validity bounds** — the limits a broken probe
  or a malformed packet falls outside. They are not agricultural thresholds and
  carry no advisory meaning.

---

## 2. Data model

| Table | Purpose | Key columns |
| --- | --- | --- |
| `hives` | One physical hive | `hive_code` (unique), `beekeeper_id`, `cluster_id`, `status`, location fields, `colony_strength`, `queen_status`, `notes` |
| `iot_devices` | One node bound to a hive | `device_id` (unique, case-insensitive), `hive_id`, `beekeeper_id`, `status`, `last_seen`, `battery_level`, `signal_strength`, `mqtt_topic`, `firmware_version` |
| `sensor_configs` | Per-device sensor set | `device_id`, `sensor_type`, `sensor_name`, `unit`, `enabled`, `sampling_interval`, `min_valid_value`, `max_valid_value` |
| `sensor_readings` | Telemetry packets (wide) | `device_id`, `hive_id`, `beekeeper_id`, `timestamp`, `temperature`, `humidity`, `weight`, `vibration`, `acoustic_level`, `battery_level`, `signal_strength`, `source` |
| `document_sequences` | Code generation | `key`, `next_value` — backs `hive_code` and `beekeeper_code` |

Ownership is copied down the chain, so a single indexed column decides visibility
at every level:

```
User ──1:1── Beekeeper ──1:N── Hive ──1:N── IotDevice ──1:N── SensorReading
                                  └── KVIC Cluster (1:N, optional)
```

`sensor_readings` denormalises `hive_id` and `beekeeper_id` on purpose: the
history of a hive, and the history of an apiary, are each one indexed read
(`ix_sensor_readings_hive_timestamp`, `ix_sensor_readings_beekeeper_timestamp`).

Idempotency is enforced by `uq_sensor_readings_device_timestamp` — a device that
replays a packet (a reconnected ESP32, a retrying gateway) does not create a
duplicate row.

### Hive codes

`HIVE-<DISTRICT>-NNNNN`, generated from `DocumentSequence` — never supplied by a
client and never hardcoded:

| District | Prefix | Example |
| --- | --- | --- |
| Guntur | `GNT` | `HIVE-GNT-00001` |
| Srikakulam | `SRK` | `HIVE-SRK-00001` |
| East Godavari | `EGA` | `HIVE-EGA-00001` |
| *(empty)* | `GEN` | `HIVE-GEN-00001` |

The rule (`app/models/document_sequence.py::district_code`) takes the first three
consonants of a single-word district, or the initials of a multi-word one. It only
has to be short, readable and *stable* for a given name, so a code printed on a
beekeeper's card still makes sense years later.

---

## 3. Sensors

Sensor vocabulary (`SensorType`) and the set a hive node is seeded with
(`DEFAULT_SENSOR_SPECS`, applied when a device is registered):

| Sensor | Default name | Unit | Suggested interval | Stored column |
| --- | --- | --- | --- | --- |
| `TEMPERATURE` | Hive temperature | °C | 300 s | `temperature` |
| `HUMIDITY` | Hive humidity | % | 300 s | `humidity` |
| `WEIGHT` | Hive weight | kg | 900 s | `weight` |
| `VIBRATION` | Vibration | g | 120 s | `vibration` |
| `ACOUSTIC` | Acoustic activity | dB | 300 s | `acoustic_level` |
| `BATTERY` | — (power telemetry) | % | — | `battery_level` |
| `SIGNAL` | — (link quality) | dBm | — | `signal_strength` |

`BATTERY` and `SIGNAL` have no seeded `sensor_configs` row: they are device health
facts reported alongside a packet, not measurements a beekeeper configures.

Validity bounds (`VALID_RANGES`, `app/models/sensor_reading.py`):

| Field | Accepted range |
| --- | --- |
| `temperature` | −20 … 80 °C |
| `humidity` | 0 … 100 % |
| `weight` | 0 … 1000 kg |
| `vibration` | 0 … 50 g |
| `acoustic_level` | 0 … 120 dB |
| `battery_level` | 0 … 100 % |
| `signal_strength` | −140 … 0 dBm |

**Values outside these bounds are rejected with `422`, never clamped.** Silently
correcting a reading would put a number in the database that no sensor produced.

Each `sensor_configs` row may carry its own narrower `min_valid_value` /
`max_valid_value`; the effective check is the configured range when present, and
the global sanity range otherwise.

---

## 4. Telemetry contract

Both ingest paths — HTTP and MQTT — converge on `TelemetryService.ingest`, so the
payload a device codes against does not change when the transport does.

### 4.1 Payload

```json
{
  "device_id": "ESP32-GNT-0001",
  "timestamp": "2026-09-23T12:54:17+00:00",
  "temperature": 34.2,
  "humidity": 58.4,
  "weight": 42.61,
  "vibration": 0.31,
  "acoustic_level": 41.5,
  "battery_level": 91,
  "signal_strength": -67,
  "source": "SIMULATOR"
}
```

Rules enforced by the schema and the service:

| Rule | Behaviour |
| --- | --- |
| At least one measurement | `422` — a packet with only a `device_id` is not a reading |
| `device_id` normalised | trimmed and upper-cased before matching |
| Unknown fields | `422` (`extra="forbid"`) — a typo is not silently dropped |
| `timestamp` omitted | receipt time (UTC) is used |
| `timestamp` in the future beyond `TELEMETRY_MAX_CLOCK_SKEW_SECONDS` (300 s) | `422`; modest skew is tolerated |
| `device_id` on HTTP that belongs to another beekeeper | `403` |
| `device_id` that does not exist | `404` |
| Value outside range | `422`, with the field name in `error.details` |
| Same `(device_id, timestamp)` posted twice | accepted as `duplicate`, no second row |

### 4.2 Reading source

Every row records how it was produced, and the API returns it:

* `REAL_DEVICE` — hardware reported it. HTTP submissions are labelled this only
  when the caller is the device; the MQTT consumer treats an unlabelled packet as
  `REAL_DEVICE` because that transport is the device transport.
* `SIMULATOR` — produced by `app/scripts/hive_simulator.py`. The UI prints
  "produced by the development simulator, not hardware" wherever these appear.
* `MANUAL` — entered by a person through the HTTP API (the default for an
  authenticated HTTP call that does not declare `SIMULATOR`).

Nothing in the platform upgrades a simulator or manual reading into hardware data.

### 4.3 HTTP ingest

```
POST /api/v1/iot/telemetry          # one packet  → ReadingResult
POST /api/v1/iot/telemetry/batch    # 1–200 packets (bare JSON array)
```

The batch endpoint is what the simulator and a store-and-forward gateway use:
each item is validated independently and the response reports
`{submitted, stored, duplicates, rejected_count, rejected[{index, reason}]}`, so a
device learns exactly which packet was refused and why.

### 4.4 MQTT ingest

| Topic | Direction | Purpose |
| --- | --- | --- |
| `<prefix>/devices/{device_id}/telemetry` | device → platform | A reading (subscribed with `+` wildcard) |
| `<prefix>/devices/{device_id}/status` | device → platform | Reachability/heartbeat without a full packet |
| `<prefix>/devices/{device_id}/commands` | platform → device | Reserved for a later phase |
| `<prefix>/devices/{device_id}/config` | platform → device | Reserved for a later phase |

`prefix` is `MQTT_TOPIC_PREFIX` (default `honeychain`), so a device's topic is
`honeychain/devices/ESP32-GNT-0001/telemetry` — the same string stored on the
device row as `mqtt_topic` and displayed in the UI.

The consumer validates before it trusts anything:

* non-object payload, bad UTF-8 or oversized payload (`TELEMETRY_MAX_PAYLOAD_BYTES`,
  default 8192) → rejected;
* payload `device_id` that does not match the topic's → rejected;
* unknown device → rejected (logged, never a crash);
* on success the row is stored and device status/last seen refreshed.

Every outcome is returned as one of `stored`, `duplicate`, `rejected`, `ignored`
and counted in `/api/v1/health/mqtt`, which is how a demo proves a packet really
travelled the broker path.

---

## 5. Running the broker (optional by design)

`MQTT_BROKER_URL` unset is a **supported** configuration: the API, the HTTP ingest
endpoint and every dashboard work without a broker, and `/api/v1/health/mqtt`
answers `not_configured` with an explanation rather than an error.

Settings (`backend/.env`):

| Setting | Default | Meaning |
| --- | --- | --- |
| `MQTT_BROKER_URL` | *(unset)* | Host of the broker; unset disables broker ingest |
| `MQTT_PORT` | `1883` | Broker port |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | *(unset)* | Credentials, if the broker requires them |
| `MQTT_TOPIC_PREFIX` | `honeychain` | Root of every topic |
| `MQTT_CLIENT_ID` | `honeychain-backend` | Consumer client id |
| `MQTT_USE_TLS` | `false` | TLS for the connection |
| `MQTT_KEEPALIVE_SECONDS` | `60` | Keep-alive interval |
| `MQTT_RECONNECT_SECONDS` | `5` | Backoff between reconnect attempts |
| `MQTT_CONSUMER_ENABLED` | `true` | Set `false` to run HTTP-only ingest |

Local broker (the package is optional; install it only if you want the MQTT leg):

```bash
sudo apt-get install -y mosquitto mosquitto-clients
mosquitto -p 1883 &                       # dev only: no auth, no TLS

# point the API at it and restart
echo 'MQTT_BROKER_URL=localhost' >> backend/.env
```

The consumer runs as a daemon thread started from the FastAPI lifespan and
reconnects forever in the background — a broker that is down delays ingest, it
does not take the API down. `paho-mqtt` is imported lazily, so the backend runs
(and the test suite passes) with the library absent.

Watch the broker leg end to end:

```bash
curl -s localhost:8000/api/v1/health/mqtt | python3 -m json.tool     # stats + last message

cd backend && .venv/bin/python -m app.scripts.hive_simulator \
    --device ESP32-GNT-0001 --transport mqtt --interval 5 --count 12
```

---

## 6. Device lifecycle and health

### Status derivation

Status is *computed*, not asserted — a device that stops reporting goes offline by
itself instead of staying green forever:

| Result | Condition |
| --- | --- |
| `MAINTENANCE` | Set deliberately by an operator; never overwritten by the sweeper |
| `OFFLINE` | Never seen, or last seen more than `DEVICE_OFFLINE_THRESHOLD_SECONDS` (900 s) ago |
| `WARNING` | Reporting, but battery at or below `DEVICE_LOW_BATTERY_PERCENT` (20 %) |
| `ONLINE` | Reporting within the threshold with a healthy battery |

`PATCH /api/v1/iot/devices/{id}/status` accepts `ONLINE`, `OFFLINE`, `WARNING`
and `MAINTENANCE`, but the derived value wins for the first three — a manual
`OFFLINE` clears the moment a valid packet arrives, and a device whose battery is
low returns to `WARNING`. Only `MAINTENANCE` is sticky, which is the point: it
takes a device out of service without pretending its hardware is healthy.

### Lifecycle

```bash
# register (beekeeper's own hive; seeds the five sensor configs)
curl -s -X POST localhost:8000/api/v1/iot/devices -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{
    "device_id": "ESP32-GNT-0001",
    "device_name": "Guntur apiary node A",
    "hive_id": "<hive uuid>"
  }'

# heartbeat (reachability without a reading)
curl -s -X POST localhost:8000/api/v1/iot/devices/heartbeat -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"device_id":"ESP32-GNT-0001","battery_level":74}'

# take out of service / return to service
curl -s -X PATCH localhost:8000/api/v1/iot/devices/<device uuid>/status \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"status":"MAINTENANCE","reason":"Chassis swapped"}'
```

Deleting a device that has telemetry history is refused with `409` and the
reading count, because deleting it would delete evidence. Re-issue with
`?confirm=true` to delete the device and its readings deliberately:

```bash
curl -s -X DELETE 'localhost:8000/api/v1/iot/devices/<device uuid>'        # 409 + explanation
curl -s -X DELETE 'localhost:8000/api/v1/iot/devices/<device uuid>?confirm=true'
```

The same principle applies to hives: a hive with devices or readings is moved to
`REMOVED` (history intact) rather than erased. Pass `?force=true` to retire it
that way explicitly.

### Sweeper

A device only becomes `OFFLINE` promptly if something re-evaluates it. Run the
sweep on a timer (cron, systemd timer, or any scheduler):

```bash
cd backend && .venv/bin/python -m app.scripts.device_status_sweep
```

The MQTT consumer loop performs the same sweep while it is connected, and the API
also derives the status on read, so a dashboard never shows a stale `ONLINE`.

---

## 7. Development simulator

`backend/app/scripts/hive_simulator.py` is a stand-in for a hive node. It is
always loud about what it is: every packet carries `"source": "SIMULATOR"`, and
the UI labels those readings accordingly.

```bash
cd backend
.venv/bin/python -m app.scripts.hive_simulator --help

# HTTP (works with no broker configured)
.venv/bin/python -m app.scripts.hive_simulator \
    --device ESP32-GNT-0001 --transport http \
    --email beekeeper@honeychain.example.com --password HoneyPass123 \
    --interval 30 --count 20

# MQTT (needs a broker; same payloads, same validation)
.venv/bin/python -m app.scripts.hive_simulator \
    --device ESP32-GNT-0001 --transport mqtt --interval 5 --count 12

# inspect the packets without sending them
.venv/bin/python -m app.scripts.hive_simulator --device ESP32-GNT-0001 --dry-run --count 2
```

Useful flags: `--sensors temperature,weight` to report a subset, `--seed 42` for a
repeatable run, `--interval 0 --count 12` to prove idempotency (identical
timestamps collapse to one row and every response reads `duplicate`).

The simulator's job is to prove the pipeline the *hardware* will use: with
`--transport http` it exercises the authenticated ingest endpoint, and with
`--transport mqtt` it exercises the broker, the topic contract and the consumer.

---

## 8. From simulator to real hardware

The contract is transport + payload, and neither changes:

1. **Keep the payload.** `device_id` plus any subset of the seven measurement
   fields. Extra fields are rejected on purpose, so a firmware change is visible
   immediately instead of being ignored.
2. **Publish, do not invent a new endpoint.** `honeychain/devices/{device_id}/telemetry`
   with QoS 1 is what the consumer subscribes to. A device that cannot reach the
   broker can POST the same JSON to `/api/v1/iot/telemetry` (or a batch) with its
   own credentials.
3. **Label honestly.** Hardware omits `source` (the MQTT consumer records
   `REAL_DEVICE`) or may state it explicitly. A device must never claim
   `SIMULATOR`, and the platform never promotes a simulator reading to hardware.
4. **Register the device first.** An unknown `device_id` is rejected; `device_id`
   is unique and case-insensitive, and a duplicate registration is a `422`.
5. **Respect the clock.** Timestamps are UTC; more than 300 s in the future is
   refused, and replaying the same `(device_id, timestamp)` is a no-op.
6. **Existing simulator rows stay what they are.** When a real node starts
   reporting, its readings appear alongside the labelled simulator history —
   nothing is rewritten, and the source column keeps the record honest.

The reference sketch lives at `firmware/esp32_hive_node/esp32_hive_node.ino`
(WiFi + MQTT publish loop). It is a starting point for the hardware task, not a
claim that a board has been flashed and tested.

---

## 9. Authorisation

Authorisation is server-side and re-checked on every request
(`app/core/permissions.py`); the UI only hides what a role cannot use.

| Capability | Beekeeper | KVIC officer | Admin |
| --- | --- | --- | --- |
| Read own hives/devices/telemetry | yes | n/a (`*_ALL`) | n/a (`*_ALL`) |
| Read any hive/device/telemetry | no | yes | yes |
| Create/edit hive, register device, configure sensor | own only | yes | yes |
| Submit telemetry | own devices only | yes | yes |
| Delete a device/hive | own only | yes | yes |
| Consumer role | no hive/device/telemetry access at all | | |

Detail, because it is the part that is easy to get wrong:

* A beekeeper reading another beekeeper's hive, device or sensor configuration
  receives **404**, not 403 — the record is not confirmed to exist.
* Submitting telemetry for a device that belongs to someone else is **403**.
* Cross-owner attempts are covered by `test_hives.py`, `test_iot_devices.py` and
  `test_telemetry.py` (read, write, register, sensor config, delete), and by the
  browser walk, which opens another beekeeper's hive by URL and asserts nothing
  about it is rendered.

---

## 10. API reference

Base path `/api/v1`. All endpoints require `Authorization: Bearer <access token>`
and return the standard envelope (`{success, data}` / `{success, error}`).

### Hives

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/hives` | Paginated; filters `status`, `search`, `district`, `state`, `bee_species`, `colony_strength`, `cluster_id`, `beekeeper_id`, `has_device`, `include_removed`. Each row carries `cluster`, `device_count`, `primary_device`, `latest_reading` |
| `GET` | `/hives/summary` | `total`, `by_status`, `with_device`, `without_device` |
| `GET` | `/hives/filters` | Values present in scope, for filter dropdowns |
| `POST` | `/hives` | Create; the code is generated server-side |
| `GET` | `/hives/{id}` | `owner`, `devices` (each with derived `status`), `sensor_values`, `latest_reading` |
| `PUT` | `/hives/{id}` | Update apiary/colony details |
| `PATCH` | `/hives/{id}/status` | `ACTIVE` / `INACTIVE` / `MAINTENANCE` / `REMOVED` |
| `DELETE` | `/hives/{id}?force=` | `409` when history exists; `force=true` marks `REMOVED` |
| `GET` | `/beekeepers/me/hives` | The signed-in beekeeper's own hives |

### Devices and sensors

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/iot/devices` | Paginated; filters `search`, `status`, `hive_id`, `beekeeper_id`, `device_type`, `connection_type` |
| `GET` | `/iot/devices/summary` | Fleet counters (`window_hours`) |
| `POST` | `/iot/devices` | Register against one of your hives (seeds sensor configs) |
| `POST` | `/iot/devices/heartbeat` | Reachability without a reading |
| `GET` | `/iot/devices/{id}` | Detail, with sensors and last reading |
| `PUT` | `/iot/devices/{id}` | Name, firmware, connection type, installed date, topic |
| `PATCH` | `/iot/devices/{id}/status` | As described in §6 |
| `DELETE` | `/iot/devices/{id}?confirm=` | `409` when readings exist, unless confirmed |
| `GET` | `/iot/devices/{id}/sensors` | The device's sensor configuration |
| `PATCH` | `/iot/devices/{id}/sensors/{sensor_type}` | Enable/disable, rename, retune the valid range |
| `GET` | `/iot/me/devices` | Every device the caller owns |

### Telemetry

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/iot/telemetry` | One reading |
| `POST` | `/iot/telemetry/batch` | 1–200 readings (bare JSON array) |
| `GET` | `/iot/telemetry/{hive_id}` | History; `range` (`1h`, `6h`, `24h`, `7d`, `30d`) or `from`/`to`, `interval` for averaged buckets, optional `sensor_type` / `device_id`, `limit` ≤ 2000 |
| `GET` | `/iot/telemetry/{hive_id}/latest` | Newest values per device on a hive |
| `GET` | `/iot/last-telemetry` | Most recent reading in scope (always returns a body) |
| `GET` | `/health/mqtt` | Consumer status, topic, counters, last error |

---

## 11. Operational notes

* **Retention.** Readings are append-only. There is no automatic pruning; decide a
  retention window before production volumes (a 5-minute cadence on five sensors
  is ~2 600 rows/day/device).
* **Scaling the ingest path.** The MQTT consumer writes through the same service
  as HTTP; when volume grows, the natural split is a dedicated consumer process
  (`MQTT_CONSUMER_ENABLED=false` on the API) rather than a second code path.
* **Never run the sweeper as the only source of truth.** It is a convenience for
  stored status; reads derive status anyway.
* **Backups.** `sensor_readings` is the irreplaceable table — it is the history a
  hive cannot regenerate. `pg_dump` covers everything, but that table deserves a
  shorter interval if a decision ever depends on it.
* **Retiring a device.** Prefer `MAINTENANCE` over deletion; keep the series.

---

## 12. Troubleshooting

| Symptom | Cause | Action |
| --- | --- | --- |
| `/health/mqtt` says `not_configured` | No `MQTT_BROKER_URL` | Expected. HTTP ingest works; set the variable and restart to use a broker |
| `/health/mqtt` says `stopped` | Consumer thread not running (or `MQTT_CONSUMER_ENABLED=false`) | Check the broker address; restart the API |
| `/health/mqtt` says `disconnected` | Broker unreachable or credentials wrong | Watch `last_error`; the consumer retries every `MQTT_RECONNECT_SECONDS` |
| Packet is `rejected: device id mismatch` | Payload `device_id` differs from the topic | Fix the firmware topic/payload pair |
| Packet is `ignored: unexpected topic` | Publishing outside `<prefix>/devices/+/telemetry|status` | Align the topic with §4.4 |
| `422` on a reading | Value outside the validity range, future timestamp, or an unknown field | Read `error.details[].field`; values are rejected, never clamped |
| Every simulator response says `duplicate` | `--interval 0` reuses one timestamp on purpose | Use `--interval 1` or more to store a series |
| Device shows `OFFLINE` although it reported | Threshold passed (900 s default), or a stale row awaiting a sweep | Confirm `last_seen`, run the sweep, check battery for `WARNING` |
| Dashboard shows no readings for a live node | `device_id` unknown, or the reading was rejected | Check `/iot/devices/{id}` and the audit/ingest counters |

---

## 13. Tests

| File | Covers |
| --- | --- |
| `tests/test_hives.py` | Registry CRUD, code generation, filters, summary, ownership, status lifecycle |
| `tests/test_iot_devices.py` | Registration, sensor seeding, duplicate ids, derived status, battery warning, heartbeat, deletion rules |
| `tests/test_telemetry.py` | Ingest, idempotency, range rejection, clock skew, batching, history, aggregation, ownership |
| `tests/test_mqtt_ingest.py` | Topic parsing, payload validation, mismatch rejection, counters, health states, broker-absent behaviour |
| `tests/api_smoke_phase3.py` | The same surface against a running API and a real database, self-cleaning |
| `tests/browser_smoke_phase3.py` | A browser walk: dashboards, registry, device detail, historical charts, empty states, cross-user isolation, layout |

```bash
cd backend
.venv/bin/python -m pytest tests/test_hives.py tests/test_iot_devices.py \
    tests/test_telemetry.py tests/test_mqtt_ingest.py -q
.venv/bin/python tests/api_smoke_phase3.py
```

See `docs/phase-3-report.md` for the full verification record, and `docs/api.md`
for the complete endpoint list across all phases.
