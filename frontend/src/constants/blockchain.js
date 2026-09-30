/**
 * Traceability vocabulary — the event types, their chain statuses and how each
 * one reads on a screen.
 *
 * Mirrored from the backend enums in `app/models/enums.py` so a filter can offer
 * exactly the values the API accepts. A label that is unknown to this file is
 * still rendered (the API sends its own `tx_type_label`), which means a new event
 * type added on the server never blanks a screen here.
 */

/** Every event the workflow records, in the order a batch meets them. */
export const BLOCKCHAIN_EVENT_TYPES = [
  { value: 'COLLECTION_COMPLETED', label: 'Collection completed' },
  { value: 'BATCH_CREATED', label: 'Batch created' },
  { value: 'PROCESSING_STARTED', label: 'Processing started' },
  { value: 'PROCESSING_COMPLETED', label: 'Processing completed' },
  { value: 'LAB_TEST_STARTED', label: 'Laboratory test started' },
  { value: 'QUALITY_CHECKED', label: 'Quality checked' },
  { value: 'QUALITY_FAILED', label: 'Quality failed' },
  { value: 'QUALITY_HOLD', label: 'Quality on hold' },
  { value: 'PROCEEDED_WITH_RISK', label: 'Proceeded with risk' },
  { value: 'PACKAGING_STARTED', label: 'Packaging started' },
  { value: 'PACKAGE_CREATED', label: 'Package created' },
  { value: 'PACKAGED', label: 'Batch packaged' },
  { value: 'DISTRIBUTION_CREATED', label: 'Shipment created' },
  { value: 'DISTRIBUTION_DISPATCHED', label: 'Shipment dispatched' },
  { value: 'IN_TRANSIT', label: 'In transit' },
  { value: 'DELIVERED', label: 'Delivered' },
  { value: 'RETAILER_RECEIVED', label: 'Retailer received' },
  { value: 'QR_GENERATED', label: 'QR code issued' },
  { value: 'CUSTOMER_QR_VERIFIED', label: 'Customer verified' },
];

/** The events that mean something went wrong, so a screen can flag them. */
export const QUALITY_ALERT_TYPES = new Set(['QUALITY_FAILED', 'QUALITY_HOLD']);

/**
 * Chain statuses.
 *
 * `CONFIRMED` is the only one that may be described as being on the chain.
 * `SKIPPED` means the integration was switched off when the event happened —
 * it is recorded, not submitted, and it is written to the chain if the
 * integration is switched back on.
 */
export const BLOCKCHAIN_STATUS_META = {
  PENDING: { label: 'Pending', variant: 'warning', hint: 'Recorded; not submitted yet.' },
  SUBMITTED: { label: 'Submitted', variant: 'info', hint: 'Sent; waiting for the service to answer.' },
  CONFIRMED: { label: 'Confirmed', variant: 'success', hint: 'Written to the chain.' },
  FAILED: { label: 'Failed', variant: 'danger', hint: 'The service refused or could not be reached.' },
  SKIPPED: { label: 'Skipped', variant: 'neutral', hint: 'The integration was switched off when this happened.' },
};

export const BLOCKCHAIN_STATUS_OPTIONS = Object.entries(BLOCKCHAIN_STATUS_META).map(
  ([value, meta]) => ({ value, label: meta.label }),
);

/** Status metadata, with an honest fallback for a value this file has not met. */
export function blockchainStatusMeta(status) {
  return (
    BLOCKCHAIN_STATUS_META[status] || {
      label: status || 'Unknown',
      variant: 'neutral',
      hint: 'This status is not one this screen describes.',
    }
  );
}

/** A human label for an event type, falling back to the raw value. */
export function eventTypeLabel(value) {
  const match = BLOCKCHAIN_EVENT_TYPES.find((option) => option.value === value);
  return match ? match.label : value || 'Event';
}

/**
 * The line that says whether a batch's events are on the chain.
 *
 * Never "verified" unless every recorded event is confirmed: an event that is
 * still pending, or was skipped while the integration was off, is reported as
 * exactly that.
 */
export function synchronisationState(blockchain) {
  const counts = blockchain || {};
  const total =
    counts.total ??
    (counts.confirmed || 0) + (counts.pending || 0) + (counts.failed || 0) + (counts.skipped || 0);
  if (blockchain.enabled === false) {
    // The honest answer when the integration is switched off: nothing here is
    // on a chain, whatever the individual events say.
    return {
      label: 'Blockchain integration is switched off',
      variant: 'neutral',
      synchronized: false,
    };
  }
  if (!total) {
    return { label: 'No events recorded yet', variant: 'neutral', synchronized: false };
  }
  if (blockchain.failed) {
    return {
      label: `${blockchain.failed} event(s) not on the chain`,
      variant: 'danger',
      synchronized: false,
    };
  }
  if (blockchain.pending) {
    return {
      label: `${blockchain.pending} event(s) waiting to be written`,
      variant: 'warning',
      synchronized: false,
    };
  }
  if (blockchain.skipped) {
    return {
      label: `${blockchain.skipped} event(s) recorded while the integration was off`,
      variant: 'neutral',
      synchronized: false,
    };
  }
  return { label: 'Every event confirmed on the chain', variant: 'success', synchronized: true };
}
