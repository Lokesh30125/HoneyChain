/**
 * Packaging vocabulary.
 *
 * Mirrors the backend enums (`PackagingStatus`, `PackagingType`, `PackageStatus`)
 * and the wording the packaging screens must show. A status that the database does
 * not have is not invented here — there is no "READY" packaging run and no
 * "SHIPPED" package, because the platform has no such states.
 */

export const PACKAGING_STATUSES = Object.freeze({
  PENDING: 'PENDING',
  IN_PROGRESS: 'IN_PROGRESS',
  COMPLETED: 'COMPLETED',
  CANCELLED: 'CANCELLED',
});

/** Label and tone per status, so a cancelled run never reads as a success. */
export const PACKAGING_STATUS_META = Object.freeze({
  PENDING: { label: 'Pending', variant: 'pending', hint: 'Opened; packing has not started.' },
  IN_PROGRESS: { label: 'In progress', variant: 'warning', hint: 'The honey is being packed.' },
  COMPLETED: {
    label: 'Completed',
    variant: 'success',
    hint: 'The packages exist and the quantities are recorded.',
  },
  CANCELLED: { label: 'Cancelled', variant: 'neutral', hint: 'The run did not happen.' },
});

export const PACKAGE_STATUSES = Object.freeze({
  CREATED: 'CREATED',
  READY_FOR_DISTRIBUTION: 'READY_FOR_DISTRIBUTION',
  IN_DISTRIBUTION: 'IN_DISTRIBUTION',
  DELIVERED: 'DELIVERED',
  CANCELLED: 'CANCELLED',
});

/**
 * Package states.
 *
 * `CREATED` is deliberately not "ready": a package exists as soon as the honey is
 * in it, and becomes available to distribution only when the packaging unit
 * releases it. Existence is not readiness, and the two words are not synonyms.
 */
export const PACKAGE_STATUS_META = Object.freeze({
  CREATED: { label: 'Created', variant: 'pending', hint: 'Packed, not yet released.' },
  READY_FOR_DISTRIBUTION: {
    label: 'Ready for distribution',
    variant: 'info',
    hint: 'Released by the packaging unit and available to ship.',
  },
  IN_DISTRIBUTION: {
    label: 'In distribution',
    variant: 'warning',
    hint: 'On a shipment that has left.',
  },
  DELIVERED: { label: 'Delivered', variant: 'success', hint: 'Received by the retailer.' },
  CANCELLED: { label: 'Cancelled', variant: 'neutral', hint: 'Withdrawn before it moved.' },
});

/** Packaging types the platform records. */
export const PACKAGING_TYPES = Object.freeze([
  { value: 'JAR', label: 'Jar' },
  { value: 'BOTTLE', label: 'Bottle' },
  { value: 'POUCH', label: 'Pouch' },
  { value: 'TIN', label: 'Tin' },
  { value: 'BULK_CONTAINER', label: 'Bulk container' },
  { value: 'OTHER', label: 'Other' },
]);

export const PACKAGING_TYPE_LABELS = Object.freeze(
  PACKAGING_TYPES.reduce((labels, type) => {
    labels[type.value] = type.label;
    return labels;
  }, {}),
);

/**
 * The copy each packaging screen shows, kept in one place so the wording cannot
 * drift between the dashboard, the tables and the detail pages.
 */
export const PACKAGING_VIEW_COPY = Object.freeze({
  overview: {
    title: 'Packaging workspace',
    description:
      'Batches the laboratory approved, the honey packed into individual packages, and what is still waiting to be packed.',
  },
  approved: {
    title: 'Approved batches',
    description:
      'Batches the laboratory approved, with what is left to pack. Nothing else may be packed — a rejected batch is never shown here and never accepted by the server.',
  },
  runs: {
    title: 'Packaging',
    description:
      'Runs under way and their quantities: what is being packed, into what, and how many packages it will make.',
  },
  packages: {
    title: 'Packages',
    description:
      'Every individual package with its own stable code, the run it came from and where it has got to.',
  },
  history: {
    title: 'Packaging history',
    description:
      'Every packaging run recorded, newest first — including cancelled ones, which are kept rather than deleted.',
  },
});

/**
 * The sizes a package is made in.
 *
 * Held in grams and shown in the units a person says them in, then converted into
 * whichever unit the batch is measured in when the options are built. The platform
 * stores a package size in the batch's own unit and applies no conversion of its
 * own, so the conversion has to happen once, here, visibly — not silently in the
 * database where nobody could check it.
 */
export const PACKAGE_SIZE_PRESETS = Object.freeze([
  { grams: 250, label: '250 g' },
  { grams: 500, label: '500 g' },
  { grams: 1000, label: '1 kg' },
  { grams: 2000, label: '2 kg' },
  { grams: 5000, label: '5 kg' },
  { grams: 10000, label: '10 kg' },
]);

/**
 * The standard sizes expressed in a batch's unit.
 *
 * A kilogram batch is offered 0.25 / 0.5 / 1 / 2 / 5 / 10; a gram batch is offered
 * 250 / 500 / 1,000 / 2,000 / 5,000 / 10,000. The label stays the one a person
 * reads — "250 g", "1 kg" — whichever unit the number travels in.
 */
export function packageSizeOptions(unit, { extraSizes = [] } = {}) {
  const perGram = String(unit || '').toUpperCase() === 'GRAM' ? 1 : 0.001;
  const options = PACKAGE_SIZE_PRESETS.map(({ grams, label }) => ({
    value: String(Number((grams * perGram).toFixed(6))),
    label,
    //: The value as the batch measures it, for anyone showing their working.
    helper: perGram === 1 ? `${grams} g` : `${Number((grams * perGram).toFixed(6))} kg`,
  }));

  const covered = new Set(options.map((option) => Number(option.value)));
  for (const raw of extraSizes || []) {
    const size = Number(raw);
    if (!Number.isFinite(size) || size <= 0 || covered.has(size)) continue;
    covered.add(size);
    // Sizes this facility has packed before but which are not one of the standard
    // ones — a 13 kg drum, say. Real rows, kept rather than hidden.
    options.push({ value: String(size), label: `${size} (packed before)` });
  }
  return options;
}

/**
 * Fields a completed or cancelled packaging run will not accept changes to
 * (mirrors the service). Shown to a caller rather than silently ignored.
 */
export const IMMUTABLE_PACKAGING_FIELDS = Object.freeze([
  'batch',
  'packaged quantity',
  'package size',
  'number of packages',
  'packaging type',
]);

/** The empty, loading and failure strings the packaging screens show. */
export const PACKAGING_MESSAGES = Object.freeze({
  emptyApproved: 'No approved batch is waiting to be packed.',
  emptyRuns: 'No packaging run has been recorded yet.',
  emptyPackages: 'No packages have been created yet.',
  emptyHistory: 'No packaging runs recorded yet.',
  loadingApproved: 'Loading approved batches...',
  loadingRuns: 'Loading packaging runs...',
  loadingPackages: 'Loading packages...',
  loadFailed: 'Unable to load the packaging records.',
  noUnits:
    'No packaging unit is registered yet. A run must be recorded against the unit that did the work.',
  //: Two different facts, and they used to be one sentence. "This account has not
  //: been attached to a facility" is an administrative gap to close; "no facility
  //: has been registered at all" is a setup step. Neither may be shown to an
  //: operator whose account *is* attached — that was the complaint.
  unitNotAttached:
    'This account is not attached to a packaging unit yet. An administrator attaches it from Administration → Packaging Units, and this screen then shows the facility automatically.',
  unitNotAttachedShort: 'No packaging unit attached to this account',
  created: 'Packaging run opened.',
  started: 'Packing started.',
  completed: 'Packing completed and the packages created.',
  cancelled: 'Packaging run cancelled.',
  released: 'Packages released for distribution.',
});
