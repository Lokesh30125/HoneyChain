/**
 * Processing vocabulary.
 *
 * Mirrors the backend enums (`ProcessingStatus`, `ProcessingType`,
 * `FacilityStatus`) and the wording the processing screens must show. Keeping the
 * strings in one module is what stops a component inventing a status the database
 * does not have — in particular there is no "READY" or "QUEUED" here, because the
 * platform does not have those states.
 */

export const PROCESSING_STATUSES = Object.freeze({
  PENDING: 'PENDING',
  IN_PROGRESS: 'IN_PROGRESS',
  COMPLETED: 'COMPLETED',
  CANCELLED: 'CANCELLED',
});

/** Label and tone per status, so a cancelled run never reads as a success. */
export const PROCESSING_STATUS_META = Object.freeze({
  PENDING: { label: 'Pending', variant: 'pending', hint: 'Opened; not started yet.' },
  IN_PROGRESS: { label: 'In progress', variant: 'warning', hint: 'The batch is being processed.' },
  COMPLETED: { label: 'Completed', variant: 'success', hint: 'Quantities recorded; ready for the laboratory.' },
  CANCELLED: { label: 'Cancelled', variant: 'neutral', hint: 'The run did not happen.' },
});

export const PROCESSING_TYPES = Object.freeze([
  { value: 'FILTERING', label: 'Filtering' },
  { value: 'DECRYSTALIZATION', label: 'Decrystallization' },
  { value: 'PASTEURIZATION', label: 'Pasteurization' },
  { value: 'BLENDING', label: 'Blending' },
  { value: 'MOISTURE_REDUCTION', label: 'Moisture reduction' },
  { value: 'OTHER', label: 'Other' },
]);

export const PROCESSING_TYPE_LABELS = Object.freeze(
  PROCESSING_TYPES.reduce((labels, type) => {
    labels[type.value] = type.label;
    return labels;
  }, {}),
);

/** Units a quantity can be recorded in — the batch's own units, never converted. */
export const QUANTITY_UNITS = Object.freeze([
  { value: 'KG', label: 'Kilograms (kg)' },
  { value: 'GRAM', label: 'Grams (g)' },
]);

/** Fields a completed run will not accept changes to (mirrors the service). */
export const IMMUTABLE_RUN_FIELDS = Object.freeze([
  'input quantity',
  'output quantity',
  'batch',
  'start time',
  'completion time',
  'operator',
]);

/**
 * The exact empty, loading and failure strings the processing screens show.
 *
 * `NO_RUNS` is the empty state of the run list; `AWAITING` is the empty worklist
 * the prompt names explicitly.
 */
export const PROCESSING_MESSAGES = Object.freeze({
  awaitingEmpty: 'No batches awaiting processing.',
  awaitingEmptyDescription:
    'A batch appears here the moment a harvest is completed. Nothing to process right now.',
  runsEmpty: 'No processing runs recorded yet.',
  emptyUnits: 'No processing units registered yet.',
  loadingRuns: 'Loading processing runs...',
  loadingBatch: 'Loading batch information...',
  loadFailed: 'Unable to load processing information.',
});

/** Percentage of the input that was lost, or `null` when it cannot be computed. */
export function lossPercent(input, output) {
  const start = Number(input);
  const end = Number(output);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start <= 0) return null;
  return Number((((start - end) / start) * 100).toFixed(2));
}

/** The stored difference, as a display string. Never invented for a missing side. */
export function quantityDifference(input, output) {
  if (input === null || input === undefined || output === null || output === undefined) return null;
  return Number((Number(input) - Number(output)).toFixed(3));
}

export default {
  PROCESSING_STATUSES,
  PROCESSING_STATUS_META,
  PROCESSING_TYPES,
  PROCESSING_TYPE_LABELS,
  QUANTITY_UNITS,
  PROCESSING_MESSAGES,
  lossPercent,
  quantityDifference,
};
