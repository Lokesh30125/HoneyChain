/**
 * Hive and IoT vocabulary, mirrored from the backend enums.
 *
 * Everything the UI says about a hive, a device or a sensor comes from here, so
 * a status that exists in the database cannot be rendered as something else on a
 * screen. The backend remains the authority: these lists only label what it
 * returns.
 *
 * The sensor bounds are the API's data-validity ranges — they say what counts as
 * a physically plausible packet, nothing more. They are not health, disease or
 * colony-condition thresholds, and the UI never presents them as such.
 */

/** Hive lifecycle states (`HiveStatus`). */
export const HIVE_STATUSES = [
  { value: 'ACTIVE', label: 'Active' },
  { value: 'INACTIVE', label: 'Inactive' },
  { value: 'MAINTENANCE', label: 'Under maintenance' },
  { value: 'REMOVED', label: 'Removed' },
];

export const HIVE_STATUS_VALUES = HIVE_STATUSES.map((status) => status.value);

/** Device connection states (`DeviceStatus`). */
export const DEVICE_STATUSES = [
  { value: 'ONLINE', label: 'Online' },
  { value: 'OFFLINE', label: 'Offline' },
  { value: 'WARNING', label: 'Needs attention' },
  { value: 'MAINTENANCE', label: 'Maintenance' },
];

/**
 * The one status an operator sets by hand. ONLINE/OFFLINE/WARNING are derived by
 * the backend from the last packet, so offering them as a choice would let the
 * UI claim something the data contradicts.
 */
export const DEVICE_MANUAL_STATUSES = [
  { value: 'MAINTENANCE', label: 'Maintenance' },
  { value: 'ONLINE', label: 'Return to service' },
];

/** Sensor kinds a hive node can carry (`SensorType`). */
export const SENSOR_TYPES = [
  { value: 'TEMPERATURE', label: 'Temperature', unit: '°C', readingKey: 'temperature', precision: 1 },
  { value: 'HUMIDITY', label: 'Humidity', unit: '%', readingKey: 'humidity', precision: 0 },
  { value: 'WEIGHT', label: 'Hive weight', unit: 'kg', readingKey: 'weight', precision: 2 },
  { value: 'VIBRATION', label: 'Vibration', unit: 'g', readingKey: 'vibration', precision: 3 },
  { value: 'ACOUSTIC', label: 'Acoustic activity', unit: 'dB', readingKey: 'acoustic_level', precision: 1 },
  { value: 'BATTERY', label: 'Battery', unit: '%', readingKey: 'battery_level', precision: 0 },
];

/**
 * Battery is reported by the node itself and is never registered as a
 * configurable sensor, so it is listed for display only.
 */
export const CONFIGURABLE_SENSOR_TYPES = SENSOR_TYPES.filter((sensor) => sensor.value !== 'BATTERY');

/** Values the node adds to every packet but that are not sensors. */
export const DEVICE_TELEMETRY_FIELDS = [
  { label: 'Battery level', readingKey: 'battery_level', unit: '%' },
  { label: 'Signal strength', readingKey: 'signal_strength', unit: 'dBm' },
];

export const SENSOR_LABELS = Object.fromEntries(
  SENSOR_TYPES.map((sensor) => [sensor.value, sensor.label]),
);

/** Look a sensor up by its enum value or its reading key. */
export function sensorMeta(key) {
  if (!key) return null;
  const normalised = String(key).toUpperCase();
  return (
    SENSOR_TYPES.find((sensor) => sensor.value === normalised) ||
    SENSOR_TYPES.find((sensor) => sensor.readingKey === key) ||
    null
  );
}

/** "23.4 °C" — a value with its unit, or an em dash when nothing was sent. */
export function formatSensorValue(key, value) {
  const meta = sensorMeta(key);
  if (value === null || value === undefined || value === '') return '—';
  const precision = meta?.precision ?? 2;
  const number = Number(value);
  if (Number.isNaN(number)) return '—';
  return `${number.toFixed(precision)}${meta?.unit ? ` ${meta.unit}` : ''}`;
}

/** Windowing presets the history endpoint understands (`RANGE_PRESETS`). */
export const TELEMETRY_RANGES = [
  { value: '1h', label: 'Last hour' },
  { value: '6h', label: 'Last 6 hours' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
];

/** How the source of a reading is described on screen. */
export const READING_SOURCE_LABELS = {
  REAL_DEVICE: 'Hardware device',
  SIMULATOR: 'Simulator',
  MANUAL: 'Manual entry',
};

/**
 * True when a series contains simulator or manual readings, so the chart can say
 * so instead of letting simulated data pass for hardware data.
 */
export function includesSimulatedData(sourceMix) {
  if (!sourceMix) return false;
  return Boolean(sourceMix.SIMULATOR || sourceMix.MANUAL);
}

/** Human sentence describing where the points came from. */
export function describeSourceMix(sourceMix) {
  const entries = Object.entries(sourceMix || {}).filter(([, count]) => count > 0);
  if (entries.length === 0) return null;
  return entries
    .map(([source, count]) => `${count} ${READING_SOURCE_LABELS[source] || source}`)
    .join(' · ');
}

/** Connection types a node may declare (`ConnectionType`). */
export const CONNECTION_TYPES = [
  { value: 'WIFI', label: 'Wi-Fi' },
  { value: 'CELLULAR', label: 'Cellular' },
  { value: 'LORA', label: 'LoRa' },
  { value: 'MQTT', label: 'MQTT over Wi-Fi' },
  { value: 'LORA_MQTT', label: 'LoRa gateway to MQTT' },
];

export const DEVICE_TYPES = [
  { value: 'ESP32', label: 'ESP32 hive node' },
  { value: 'ESP32_GATEWAY', label: 'ESP32 gateway' },
  { value: 'LORA_NODE', label: 'LoRa node' },
  { value: 'OTHER', label: 'Other' },
];

/** Plain-language explanation of what each hive status means. */
export const HIVE_STATUS_HELP = {
  ACTIVE: 'In service and reporting.',
  INACTIVE: 'Registered but not currently in service.',
  MAINTENANCE: 'Temporarily out of service for work on the hive.',
  REMOVED: 'Retired. History is kept and the hive stays readable.',
};
