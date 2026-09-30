/**
 * Collections and honey batches — the vocabulary shared by their screens.
 *
 * Everything here mirrors the backend enums (`CollectionStatus`, `CollectionUnit`,
 * `BatchStatus`, `BatchStage`). Keeping the strings in one module is what stops a
 * component inventing its own label for a state the database does not have — and
 * in particular stops the UI from offering a batch status this phase cannot
 * produce.
 */

export const COLLECTION_STATUSES = Object.freeze({
  PLANNED: 'PLANNED',
  IN_PROGRESS: 'IN_PROGRESS',
  COMPLETED: 'COMPLETED',
  CANCELLED: 'CANCELLED',
});

/** Status metadata for badges and filters: label plus an honest tone. */
export const COLLECTION_STATUS_META = Object.freeze({
  PLANNED: { label: 'Planned', variant: 'info', hint: 'Scheduled; nothing harvested yet.' },
  IN_PROGRESS: { label: 'In progress', variant: 'warning', hint: 'Harvesting has started.' },
  COMPLETED: { label: 'Completed', variant: 'success', hint: 'Finished, and a batch exists.' },
  CANCELLED: { label: 'Cancelled', variant: 'neutral', hint: 'The harvest did not happen.' },
});

/** Statuses a harvest can still be edited in. */
export const OPEN_COLLECTION_STATUSES = Object.freeze(['PLANNED', 'IN_PROGRESS']);

export const COLLECTION_UNITS = Object.freeze([
  { value: 'KG', label: 'Kilograms (kg)' },
  { value: 'GRAM', label: 'Grams (g)' },
]);

/** Short unit label for a stored unit value. */
export function unitLabel(unit) {
  return unit === 'GRAM' ? 'g' : 'kg';
}

/**
 * Batch statuses, exactly as the database stores them.
 *
 * The tones are not decoration: an approved batch and a rejected one must not look
 * alike in a table, and "Testing" is an in-flight state rather than a success.
 */
export const BATCH_STATUS_META = Object.freeze({
  COLLECTED: { label: 'Collected', variant: 'info', stage: 'Collection' },
  PROCESSING: { label: 'Processing', variant: 'warning', stage: 'Processing' },
  LAB_TESTING: { label: 'Laboratory testing', variant: 'pending', stage: 'Laboratory' },
  // A held batch is not being tested and not rejected: the laboratory stopped
  // without deciding. It is painted like a question left open, and it blocks the
  // packaging floor, which is why it is not the same tone as "testing".
  LAB_HOLD: { label: 'On hold in the laboratory', variant: 'warning', stage: 'Laboratory — on hold' },
  PROCEEDED_WITH_RISK: {
    label: 'Proceeding with recorded risk',
    variant: 'warning',
    stage: 'Laboratory — risk recorded',
  },
  APPROVED: { label: 'Approved', variant: 'success', stage: 'Laboratory — approved' },
  PACKAGING_READY: {
    label: 'Ready for packaging',
    variant: 'success',
    stage: 'Packaging — released',
  },
  REJECTED: { label: 'Rejected', variant: 'danger', stage: 'Laboratory — rejected' },
  PACKAGED: { label: 'Packaged', variant: 'honey', stage: 'Packaging' },
  DISTRIBUTION: { label: 'In distribution', variant: 'info', stage: 'Distribution' },
  COMPLETED: { label: 'Completed', variant: 'success', stage: 'Delivered' },
});

/** Batch statuses a screen may offer as a filter — every stored one, in order. */
export const BATCH_STATUS_OPTIONS = Object.freeze(
  Object.entries(BATCH_STATUS_META).map(([value, meta]) => ({ value, label: meta.label })),
);

/**
 * The traceability timeline.
 *
 * Every stage of the agreed journey is real as of Phase 7. `available` marks the
 * ones a batch can reach in principle; whether a *particular* batch has reached
 * one is read from its own records, never assumed from this list.
 */
export const BATCH_TIMELINE = Object.freeze([
  {
    stage: 'COLLECTION',
    label: 'Collection',
    available: true,
    description: 'Honey harvested from the hives and recorded by the beekeeper.',
  },
  {
    stage: 'PROCESSING',
    label: 'Processing',
    available: true,
    description: 'What was done to the honey, with the quantities measured in and out.',
  },
  {
    stage: 'LABORATORY',
    label: 'Laboratory',
    available: true,
    description: 'Measured values, judged against the ranges this platform has been given.',
  },
  {
    // The analysis of the measurements: what the platform concluded, recorded with
    // the model, its version and its source. Between the laboratory and the floor
    // because that is where the decision to release — or to hold — is made.
    stage: 'AI_QUALITY',
    label: 'Quality analysis',
    available: true,
    description: 'What the platform concluded from the recorded measurements, and the decision taken on it.',
  },
  {
    stage: 'PACKAGING',
    label: 'Packaging',
    available: true,
    description: 'The approved honey filled into individually coded packages by the packaging unit.',
  },
  {
    stage: 'DISTRIBUTION',
    label: 'Distribution',
    available: true,
    description: 'Shipments of those packages, and where each one has been received.',
  },
  {
    // The receiving end: the shop's own confirmation, which is a different fact
    // from the carrier's delivery and is shown as its own stop.
    stage: 'RETAILER',
    label: 'Retailer',
    available: true,
    description: 'The shop the consignment was addressed to, and its confirmation that it arrived.',
  },
  {
    stage: 'COMPLETED',
    label: 'Completed',
    available: true,
    description: 'Every package delivered and nothing left to pack: the batch is finished.',
  },
]);

/**
 * The empty, loading and failure strings the collection screens must show.
 *
 * They live here so the wording is identical everywhere and a reviewer can check
 * the required copy in one place.
 */
export const COLLECTION_MESSAGES = Object.freeze({
  emptyCollections: 'No collections recorded yet.',
  emptyEligibleHives: 'No eligible hives available for collection.',
  emptyBatches: 'No honey batches created yet.',
  loadingCollections: 'Loading collections...',
  loadingBatches: 'Loading honey batches...',
  loadingBatch: 'Loading batch information...',
  loadFailed: 'Unable to load collection data.',
});

/** Fields of a collection that a completed or cancelled record will not accept. */
export const IMMUTABLE_COLLECTION_FIELDS = Object.freeze([
  'source hives',
  'collection date',
  'quantity',
  'unit',
  'beekeeper',
  'cluster',
]);

export default {
  COLLECTION_STATUSES,
  BATCH_STATUS_META,
  BATCH_STATUS_OPTIONS,
  COLLECTION_STATUS_META,
  OPEN_COLLECTION_STATUSES,
  COLLECTION_UNITS,
  BATCH_TIMELINE,
  COLLECTION_MESSAGES,
  unitLabel,
};
