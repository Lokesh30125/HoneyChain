/**
 * Laboratory vocabulary.
 *
 * Mirrors the backend enums (`LabTestStatus`, `LabResult`, `LabParameterStatus`)
 * and the wording the laboratory screens must show. A parameter whose reference
 * range has not been configured is `NOT_EVALUATED` — the platform has no default
 * limits, so it never labels a measurement "pass" or "fail" on its own.
 */

export const LAB_TEST_STATUSES = Object.freeze({
  PENDING: 'PENDING',
  IN_PROGRESS: 'IN_PROGRESS',
  COMPLETED: 'COMPLETED',
  HOLD: 'HOLD',
});

export const LAB_TEST_STATUS_META = Object.freeze({
  PENDING: { label: 'Pending', variant: 'pending', hint: 'Sample recorded; no measurements yet.' },
  IN_PROGRESS: { label: 'In progress', variant: 'warning', hint: 'Measurements are being recorded.' },
  COMPLETED: { label: 'Completed', variant: 'info', hint: 'Closed. Its results are read, never rewritten.' },
  HOLD: {
    label: 'On hold',
    variant: 'warning',
    hint: 'Closed without a decision. The measurements and the reason are kept, packaging is blocked, and a further test releases it.',
  },
});

/**
 * Where a recorded number came from.
 *
 * This is provenance, and it is shown on every value: a development value the
 * platform filled in while the project has no instruments attached is *not* a
 * laboratory measurement, and a screen that displayed the two alike would be
 * claiming evidence that does not exist. A value a person types becomes MANUAL,
 * and REAL_DEVICE is for a reading taken from an instrument.
 */
export const LAB_MEASUREMENT_SOURCE_META = Object.freeze({
  DEMO: {
    label: 'Development value',
    variant: 'neutral',
    hint: 'Pre-filled by the platform for development. It is not a laboratory measurement: confirm or replace it.',
  },
  MANUAL: { label: 'Entered by hand', variant: 'info', hint: 'Typed by a person reading an instrument.' },
  REAL_DEVICE: { label: 'Instrument reading', variant: 'success', hint: 'Taken from a measuring device.' },
});

/**
 * The quality analysis verdicts, in the words the platform uses.
 *
 * `blocks` is not decoration: an analysis that is not PASS has an open question
 * over it, and the screens must not offer packaging for it.
 */
export const LAB_ANALYSIS_META = Object.freeze({
  PASS: { label: 'No vulnerability found', variant: 'success', blocks: false },
  HOLD: { label: 'Held for review', variant: 'warning', blocks: true },
  FAIL: { label: 'Failed', variant: 'danger', blocks: true },
  INCONCLUSIVE: { label: 'Inconclusive', variant: 'neutral', blocks: true },
});

export const LAB_RESULTS = Object.freeze({
  PENDING: 'PENDING',
  PASS: 'PASS',
  FAIL: 'FAIL',
  INCONCLUSIVE: 'INCONCLUSIVE',
});

export const LAB_RESULT_META = Object.freeze({
  PENDING: { label: 'Pending', variant: 'pending', hint: 'No decision yet.' },
  PASS: { label: 'Pass', variant: 'success', hint: 'Every evaluated and required parameter passed.' },
  FAIL: { label: 'Fail', variant: 'danger', hint: 'At least one required parameter failed.' },
  INCONCLUSIVE: {
    label: 'Inconclusive',
    variant: 'neutral',
    hint: 'A verdict needs measurements that were not recorded, or ranges that are not configured.',
  },
});

export const LAB_PARAMETER_STATUS_META = Object.freeze({
  PASS: { label: 'Pass', variant: 'success' },
  FAIL: { label: 'Fail', variant: 'danger' },
  NOT_EVALUATED: { label: 'Not evaluated', variant: 'neutral' },
});

/**
 * The units a measurement can be reported in — a mirror of the backend
 * `LabMeasureUnit` enum, one for one.
 *
 * A parameter's own unit comes from its catalogue row and is what the screen
 * shows; this list exists for the one case where the technician supplies the
 * measurement themselves (the "Other measurement" parameter), so the custom
 * measurement is still reported in a unit the platform already stores. It is
 * never a unit picker for a configured parameter: converting between units would
 * require assumptions about the instrument that nobody recorded.
 */
export const LAB_MEASURE_UNITS = Object.freeze([
  { value: '%', label: '%' },
  { value: 'mg/kg', label: 'mg/kg' },
  { value: 'mS/cm', label: 'mS/cm' },
  { value: 'DN', label: 'DN (diastase number)' },
  { value: 'mm Pfund', label: 'mm Pfund' },
  { value: 'meq/kg', label: 'meq/kg' },
  { value: 'g/100g', label: 'g/100g' },
  { value: 'pH', label: 'pH' },
  { value: 'unitless', label: 'No unit' },
]);

/**
 * How a measurement was taken, as the platform records it.
 *
 * These are **recording categories**, not claims: choosing "Refractometer" says a
 * refractometer was used, and says nothing about whether the reading is acceptable
 * — that is what the configured reference range is for. The stored value is the
 * text of the chosen option (the column is free text, `method`, which is what the
 * laboratory writes on the bench sheet), and **Other** stores whatever the
 * technician types instead.
 *
 * The list is deliberately short and holds only what the project itself already
 * describes; if a laboratory works in a way that is not on it, Other is the honest
 * answer rather than stretching a category to fit.
 *
 * It is a **fallback**. Each parameter carries the methods that actually apply to
 * it (``methods`` on the catalogue row: refractometry and Karl Fischer for moisture,
 * titration for acidity), and the measurement dialog offers those rather than this
 * general list. Sending every method for every parameter would invite a record that
 * says moisture was measured by titration, which is not a thing a laboratory does.
 */
export const LAB_METHODS = Object.freeze([
  { value: 'REFRACTOMETER', label: 'Refractometer' },
  { value: 'PH_METER', label: 'pH meter' },
  { value: 'CONDUCTIVITY_METER', label: 'Conductivity meter' },
  { value: 'LABORATORY_INSTRUMENT', label: 'Laboratory instrument' },
  { value: 'CHEMICAL_TEST', label: 'Chemical test' },
  { value: 'VISUAL_INSPECTION', label: 'Visual inspection' },
  { value: 'OTHER', label: 'Other' },
]);

/** Sample units — grams and kilograms, as the collection module stores them. */
export const SAMPLE_UNITS = Object.freeze([
  { value: 'GRAM', label: 'Grams (g)' },
  { value: 'KG', label: 'Kilograms (kg)' },
]);

/**
 * The exact empty, loading and failure strings the laboratory screens show.
 *
 * They are named rather than inlined so the required copy can be reviewed in one
 * place — and so no screen can quietly paraphrase "No laboratory results recorded."
 */
export const LAB_MESSAGES = Object.freeze({
  awaitingEmpty: 'No batches awaiting laboratory testing.',
  awaitingEmptyDescription:
    'A batch arrives here when its processing run is completed. Nothing is waiting right now.',
  testsEmpty: 'No laboratory tests recorded yet.',
  samplesEmpty: 'No samples recorded yet.',
  completedEmpty: 'No completed laboratory tests yet.',
  resultsEmpty: 'No laboratory results recorded.',
  facilitiesEmpty: 'No laboratories registered yet.',
  loadingBatch: 'Loading batch information...',
  loadingTests: 'Loading laboratory tests...',
  loadingLaboratory: 'Loading laboratory results...',
  loadFailed: 'Unable to load laboratory information.',
});

/** The badge copy for a test status, with a neutral fallback for an unknown one. */
export function labStatusMeta(status) {
  return LAB_TEST_STATUS_META[status] || { label: status || 'Unknown', variant: 'neutral' };
}

export function measurementText(result) {
  if (!result || result.value === null || result.value === undefined) return '—';
  return `${Number(result.value).toLocaleString(undefined, { maximumFractionDigits: 4 })} ${
    result.unit_label || ''
  }`.trim();
}

/** The badge copy for where a recorded value came from. */
export function measurementSourceMeta(source) {
  return (
    LAB_MEASUREMENT_SOURCE_META[source] || {
      label: source || 'Recorded',
      variant: 'neutral',
      hint: null,
    }
  );
}

/** The badge copy for an analysis verdict, with a neutral fallback. */
export function analysisMeta(status) {
  return (
    LAB_ANALYSIS_META[status] || {
      label: status || 'Unknown',
      variant: 'neutral',
      blocks: true,
    }
  );
}

/** The configured range as text, or `null` when nothing has been configured. */
export function referenceText(result) {
  if (!result) return null;
  const { reference_min: min, reference_max: max } = result;
  if (min === null || min === undefined) return max === null || max === undefined ? null : `≤ ${max}`;
  if (max === null || max === undefined) return `≥ ${min}`;
  return `${min} – ${max}`;
}

export default {
  LAB_TEST_STATUSES,
  LAB_TEST_STATUS_META,
  LAB_RESULTS,
  LAB_RESULT_META,
  LAB_PARAMETER_STATUS_META,
  LAB_MEASUREMENT_SOURCE_META,
  LAB_ANALYSIS_META,
  SAMPLE_UNITS,
  LAB_MESSAGES,
  labStatusMeta,
  measurementSourceMeta,
  analysisMeta,
  measurementText,
  referenceText,
};
