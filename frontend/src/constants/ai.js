/**
 * AI vocabulary: labels, colours and the sentences that must travel with a number.
 *
 * Two rules are encoded here rather than in components, so no screen can forget
 * them:
 *
 *  1. **A score is never shown without its meaning.** Every band has a label in
 *     plain words next to it, and the disclaimer text lives here so it is
 *     identical wherever an assessment is rendered.
 *  2. **The telemetry source is always visible.** A `SIMULATOR` analysis and a
 *     `REAL_DEVICE` analysis produce the same numbers, and the only difference a
 *     beekeeper cares about is which one they are looking at — so the source
 *     badge is part of every assessment header.
 */

/** Colony-health bands produced by the backend. */
export const HEALTH_STATUS_META = {
  HEALTHY: { label: 'Healthy', tone: 'success', hint: 'Recorded patterns sit inside the reference bands.' },
  ATTENTION: { label: 'Needs attention', tone: 'warning', hint: 'Some recorded patterns have moved off the bands.' },
  AT_RISK: { label: 'At risk', tone: 'warning', hint: 'Several recorded patterns are outside the bands.' },
  CRITICAL: { label: 'Critical', tone: 'danger', hint: 'Multiple strong deviations were recorded.' },
  INSUFFICIENT_DATA: { label: 'Insufficient data', tone: 'neutral', hint: 'Not enough telemetry to produce an indicator.' },
};

/** Risk bands shared by the disease and swarming assessments. */
export const RISK_LEVEL_META = {
  LOW: { label: 'Low', tone: 'success' },
  MODERATE: { label: 'Moderate', tone: 'warning' },
  HIGH: { label: 'High', tone: 'danger' },
  UNKNOWN: { label: 'Not assessed', tone: 'neutral' },
};

/** How much the analysis can be trusted, given the telemetry it consumed. */
export const QUALITY_META = {
  GOOD: { label: 'Good', tone: 'success' },
  LIMITED: { label: 'Limited', tone: 'warning' },
  INSUFFICIENT: { label: 'Insufficient', tone: 'neutral' },
};

/**
 * Where the numbers came from.
 *
 * `SIMULATOR` and `MANUAL` are deliberately shown in the same visual weight as
 * `REAL_DEVICE`: they are first-class states of the platform, and hiding them
 * would be the one thing this module must never do.
 */
export const SOURCE_META = {
  REAL_DEVICE: { label: 'Real device telemetry', short: 'Real device', tone: 'forest' },
  SIMULATOR: { label: 'Simulator telemetry', short: 'Simulator', tone: 'honey' },
  MIXED: { label: 'Mixed telemetry sources', short: 'Mixed sources', tone: 'pending' },
  MANUAL: { label: 'Manually entered readings', short: 'Manual entry', tone: 'neutral' },
  NO_DATA: { label: 'No telemetry', short: 'No telemetry', tone: 'neutral' },
};

export const TREND_LABELS = {
  RISING: 'Rising',
  STABLE: 'Stable',
  FALLING: 'Falling',
  UNKNOWN: 'Unknown',
};

export const PRIORITY_META = {
  PRIORITY: { label: 'Act first', tone: 'danger' },
  SOON: { label: 'Look soon', tone: 'warning' },
  ROUTINE: { label: 'Routine', tone: 'neutral' },
};

export const ALERT_SEVERITY_META = {
  INFO: { label: 'Information', tone: 'info' },
  WARNING: { label: 'Warning', tone: 'warning' },
  CRITICAL: { label: 'Critical', tone: 'danger' },
};

export const ALERT_STATUS_META = {
  OPEN: { label: 'Open', tone: 'danger' },
  ACKNOWLEDGED: { label: 'Acknowledged', tone: 'warning' },
  RESOLVED: { label: 'Resolved', tone: 'success' },
};

export const ALERT_TYPE_LABELS = {
  HEALTH_CRITICAL: 'Colony health critical',
  HEALTH_AT_RISK: 'Colony health at risk',
  DISEASE_RISK_HIGH: 'Elevated disease risk',
  SWARMING_RISK_HIGH: 'Elevated swarming risk',
  TEMPERATURE_ANOMALY: 'Temperature anomaly',
  HUMIDITY_ANOMALY: 'Humidity anomaly',
  WEIGHT_TREND_ANOMALY: 'Weight trend anomaly',
  ACTIVITY_ANOMALY: 'Activity anomaly',
  DATA_STALE: 'Telemetry stopped arriving',
};

/** Sensor keys the engine reasons about, in the order screens show them. */
export const AI_SENSOR_LABELS = {
  temperature: 'Temperature',
  humidity: 'Humidity',
  weight: 'Hive weight',
  vibration: 'Vibration',
  acoustic_level: 'Acoustic activity',
};

/**
 * Text that must appear next to a colony-health number and next to a risk band.
 * The API returns the same strings in every assessment payload; these are the
 * fallbacks for a stored row that predates a wording change.
 */
export const HEALTH_DISCLAIMER =
  'Colony health is a monitoring indicator derived from sensor patterns against reference bands. It is not a veterinary assessment and does not confirm the presence or absence of any disease.';

export const RISK_DISCLAIMER =
  'Risk indicators are produced by a rule-based baseline model from recorded sensor patterns. They are prompts to inspect, not diagnoses.';

/** Short form of the model identity, printed on every AI screen. */
export const MODEL_NOTICE =
  'Rule-based baseline model. Scores describe recorded sensor patterns against reference bands; they are monitoring indicators, not diagnoses.';

/** Why an analysis says "insufficient data" — mapped to reader-facing text. */
export const COMPUTE_REASON_LABELS = {
  no_analysis: 'First analysis for this hive',
  stale: 'Recalculated because the stored analysis was stale',
  new_telemetry: 'Recalculated after new telemetry arrived',
  forced: 'Recalculated on request',
  read_only: 'Read from the stored analysis',
  auto_disabled: 'Automatic analysis is disabled on this deployment',
  fresh: 'Read from the stored analysis',
};

/** Questions the AI panel is designed to answer, used in the empty state copy. */
export const INSIGHT_QUESTIONS = [
  'Are the recorded conditions inside their reference bands?',
  'Which patterns moved, and by how much?',
  'What is worth checking at the next inspection?',
];

export function healthMeta(status) {
  return HEALTH_STATUS_META[status] || { label: 'Not assessed', tone: 'neutral', hint: '' };
}

export function riskMeta(level) {
  return RISK_LEVEL_META[level] || RISK_LEVEL_META.UNKNOWN;
}

export function qualityMeta(level) {
  return QUALITY_META[level] || QUALITY_META.INSUFFICIENT;
}

export function sourceMeta(source) {
  return SOURCE_META[source] || SOURCE_META.NO_DATA;
}

export function priorityMeta(priority) {
  return PRIORITY_META[priority] || PRIORITY_META.ROUTINE;
}

export function severityMeta(severity) {
  return ALERT_SEVERITY_META[severity] || ALERT_SEVERITY_META.INFO;
}

export function alertStatusMeta(status) {
  return ALERT_STATUS_META[status] || ALERT_STATUS_META.OPEN;
}

export function alertTypeLabel(alertType) {
  return ALERT_TYPE_LABELS[alertType] || String(alertType || '').replace(/_/g, ' ');
}

export function sensorLabel(key) {
  return AI_SENSOR_LABELS[key] || String(key || '').replace(/_/g, ' ');
}

/** "+8", "−14" or "0" — the points a factor added or removed. */
export function formatDelta(delta) {
  const value = Number(delta || 0);
  if (value === 0) return '0';
  return `${value > 0 ? '+' : '−'}${Math.abs(value).toFixed(0)}`;
}

/** Confidence is always shown with its unit, never as a bare number. */
export function formatConfidence(confidence) {
  if (confidence === null || confidence === undefined) return '—';
  return `${Math.round(confidence)}%`;
}

/** "94 % of the expected cadence", or nothing when coverage is unknown. */
export function formatCoverage(coverage) {
  if (coverage === null || coverage === undefined) return null;
  return `${Math.round(coverage * 100)}% of the expected reporting cadence`;
}

/** Analysis age in words: "12 minutes", "3.4 hours", "2 days". */
export function formatAge(minutes) {
  if (minutes === null || minutes === undefined) return null;
  if (minutes < 1) return 'moments';
  if (minutes < 90) return `${Math.round(minutes)} min`;
  const hours = minutes / 60;
  if (hours < 48) return `${hours.toFixed(1)} h`;
  return `${Math.round(hours / 24)} d`;
}
