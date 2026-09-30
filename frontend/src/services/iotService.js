/**
 * IoT service — devices, sensor configuration and telemetry.
 *
 * The contract this module encodes:
 *  - a device is registered against one hive and inherits that hive's owner;
 *  - device status is *derived* by the backend from the last packet, so the UI
 *    reads it and never invents it;
 *  - telemetry is read, not interpreted. Nothing here computes a health,
 *    disease or yield figure.
 *
 * Readings that were produced by the simulator arrive labelled `SIMULATOR`;
 * screens must show that label rather than presenting them as hardware data.
 */

import { ENDPOINTS } from '@/constants/api';
import { http } from '@/services/apiClient';

// --------------------------------------------------------------------------- //
// Devices
// --------------------------------------------------------------------------- //
export async function listDevices({ page = 1, pageSize = 20, search, status, hiveId, beekeeperId, deviceType } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.iot.devices, {
    params: {
      page,
      page_size: pageSize,
      ...(search ? { search } : {}),
      ...(status ? { status } : {}),
      ...(hiveId ? { hive_id: hiveId } : {}),
      ...(beekeeperId ? { beekeeper_id: beekeeperId } : {}),
      ...(deviceType ? { device_type: deviceType } : {}),
    },
  });
  return { devices: data, meta };
}

export async function listMyDevices() {
  const { data } = await http.get(ENDPOINTS.iot.myDevices);
  return data;
}

export async function getDevice(deviceId) {
  const { data } = await http.get(ENDPOINTS.iot.deviceDetail(deviceId));
  return data;
}

/** Register a device on one of the caller's hives. */
export async function registerDevice(payload) {
  const { data } = await http.post(ENDPOINTS.iot.devices, payload);
  return data;
}

export async function updateDevice(deviceId, changes) {
  const { data } = await http.put(ENDPOINTS.iot.deviceDetail(deviceId), changes);
  return data;
}

/**
 * Set the operator-controlled status.
 *
 * ONLINE/OFFLINE/WARNING are derived from the last packet, so the API
 * re-derives them on the next read; MAINTENANCE is the state a human sets and
 * the sweeper leaves alone.
 */
export async function setDeviceStatus(deviceId, status) {
  const { data } = await http.patch(ENDPOINTS.iot.deviceStatus(deviceId), { status });
  return data;
}

/**
 * Delete a device and its sensor configuration.
 *
 * A device with stored readings answers 409 until `confirm` is passed, so
 * history is never deleted by accident.
 */
export async function deleteDevice(deviceId, { confirm = false } = {}) {
  const { data } = await http.delete(ENDPOINTS.iot.deviceDetail(deviceId), {
    params: confirm ? { confirm: true } : {},
  });
  return data;
}

export async function sendHeartbeat({ deviceId, firmwareVersion, batteryLevel, signalStrength }) {
  const { data } = await http.post(ENDPOINTS.iot.heartbeat, {
    device_id: deviceId,
    ...(firmwareVersion ? { firmware_version: firmwareVersion } : {}),
    ...(batteryLevel === undefined || batteryLevel === null ? {} : { battery_level: batteryLevel }),
    ...(signalStrength === undefined || signalStrength === null ? {} : { signal_strength: signalStrength }),
  });
  return data;
}

// --------------------------------------------------------------------------- //
// Sensor configuration
// --------------------------------------------------------------------------- //
export async function listSensors(deviceId) {
  const { data } = await http.get(ENDPOINTS.iot.deviceSensors(deviceId));
  return data;
}

export async function updateSensor(deviceId, sensorType, changes) {
  const { data } = await http.patch(ENDPOINTS.iot.deviceSensor(deviceId, sensorType), changes);
  return data;
}

// --------------------------------------------------------------------------- //
// Telemetry
// --------------------------------------------------------------------------- //
/**
 * Submit one reading by hand.
 *
 * Used for field testing and for proving the ingest path; a reading posted this
 * way is stored as MANUAL, not as device data. Real nodes publish to MQTT and
 * never need this call.
 */
export async function postTelemetry(payload) {
  const { data } = await http.post(ENDPOINTS.iot.telemetry, payload);
  return data;
}

/**
 * Submit a batch — what a node sends after reconnecting from an offline buffer.
 *
 * The endpoint takes a bare array of packets (1–200 per request), each validated
 * on its own; the response reports how many were stored and why any were
 * rejected. This is a testing/back-office call: real nodes publish to MQTT.
 */
export async function postTelemetryBatch(points) {
  const { data } = await http.post(ENDPOINTS.iot.telemetryBatch, points);
  return data;
}

/**
 * Hive history.
 *
 * `rangeKey` uses the API presets (1h, 6h, 24h, 7d, 30d); longer windows come
 * back averaged into buckets, with the exact bucket interval reported so the
 * chart can label its axis honestly.
 */
export async function getHistory(
  hiveId,
  { rangeKey = '24h', interval, sensorType, deviceId, from, to, limit = 500 } = {},
) {
  const { data } = await http.get(ENDPOINTS.iot.history(hiveId), {
    params: {
      range: rangeKey,
      ...(interval ? { interval } : {}),
      ...(sensorType ? { sensor_type: sensorType } : {}),
      ...(deviceId ? { device_id: deviceId } : {}),
      ...(from ? { from } : {}),
      ...(to ? { to } : {}),
      limit,
    },
  });
  return data;
}

/** Latest values for one hive, with a message when nothing has arrived yet. */
export async function getLatestForHive(hiveId) {
  const { data } = await http.get(ENDPOINTS.iot.latestForHive(hiveId));
  return data;
}

/** When the platform last received anything, and from which device. */
export async function getLastTelemetry() {
  const { data } = await http.get(ENDPOINTS.iot.lastTelemetry);
  return data;
}

/**
 * Fleet counters: how many devices are connected, how many readings arrived in
 * the window, and how many hives have no device yet. Empty really means empty.
 */
export async function getMonitoringSummary(windowHours = 24) {
  const { data } = await http.get(ENDPOINTS.iot.deviceSummary, {
    params: { window_hours: windowHours },
  });
  return data;
}

/** True once a broker is configured, so the UI can say why nothing arrives. */
export async function getMqttHealth() {
  const { data } = await http.get(ENDPOINTS.iot.mqttHealth);
  return data;
}
