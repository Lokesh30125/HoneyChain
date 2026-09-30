/**
 * Distribution vocabulary.
 *
 * Mirrors the backend enum `DistributionStatus` and the wording the distribution
 * and retailer screens must show. The order of `DISTRIBUTION_FLOW` is the order
 * the journey happens in, which is what lets a screen say what the next step is
 * without inventing one.
 */

export const DISTRIBUTION_STATUSES = Object.freeze({
  READY_FOR_DISPATCH: 'READY_FOR_DISPATCH',
  DISPATCHED: 'DISPATCHED',
  IN_TRANSIT: 'IN_TRANSIT',
  DELIVERED: 'DELIVERED',
  CANCELLED: 'CANCELLED',
});

export const DISTRIBUTION_STATUS_META = Object.freeze({
  READY_FOR_DISPATCH: {
    label: 'Ready for dispatch',
    variant: 'pending',
    hint: 'Raised against a released package; not on the road yet.',
  },
  DISPATCHED: { label: 'Dispatched', variant: 'warning', hint: 'Has left; not yet arrived.' },
  IN_TRANSIT: { label: 'In transit', variant: 'info', hint: 'On the way to the destination.' },
  DELIVERED: {
    label: 'Delivered',
    variant: 'success',
    hint: 'Arrived and confirmed by the receiving retailer.',
  },
  CANCELLED: { label: 'Cancelled', variant: 'neutral', hint: 'Abandoned before it moved.' },
});

/** The journey, in order. A screen reads this rather than assuming a sequence. */
export const DISTRIBUTION_FLOW = Object.freeze([
  'READY_FOR_DISPATCH',
  'DISPATCHED',
  'IN_TRANSIT',
  'DELIVERED',
]);

export const DISTRIBUTION_VIEW_COPY = Object.freeze({
  overview: {
    title: 'Distribution workspace',
    description:
      'Packages released by the packaging unit, the shipments they travel on, and what has been received.',
  },
  ready: {
    title: 'Ready for dispatch',
    description:
      'Shipments raised against released packages that have not left yet. A shipment can be corrected, dispatched or cancelled here — once it is on the road it is history.',
  },
  shipments: {
    title: 'Shipments',
    description:
      'Every shipment with its package, its destination and where it has got to — the same rows the retailer and the beekeeper read.',
  },
  transit: {
    title: 'In transit',
    description: 'Shipments on the road, with the carrier and the expected delivery date.',
  },
  delivered: {
    title: 'Delivered',
    description:
      'Shipments that arrived, with the retailer’s own confirmation of what was received and when.',
  },
  history: {
    title: 'Distribution history',
    description:
      'Every shipment recorded, newest first — including cancelled ones, which moved no honey and are kept rather than deleted.',
  },
});

export const RETAILER_VIEW_COPY = Object.freeze({
  overview: {
    title: 'Retail workspace',
    description:
      'Shipments on their way to you, the packages you have received, and where each one came from.',
  },
  inbound: {
    title: 'Incoming shipments',
    description:
      'Packages addressed to you that have been dispatched. Confirm receipt when they arrive — the record is yours, and it is what completes the batch.',
  },
  received: {
    title: 'Received packages',
    description:
      'The packages you have confirmed receiving, each tracing back to the batch, the harvest and the hive it came from.',
  },
  history: {
    title: 'History',
    description:
      'Every shipment addressed to you, newest first — including ones still on the way and any that were cancelled by the distributor.',
  },
});

/** The empty, loading and failure strings the Phase 7 screens show. */
export const DISTRIBUTION_MESSAGES = Object.freeze({
  emptyShipments: 'No shipments have been recorded yet.',
  emptyReady: 'No shipment is waiting to be dispatched.',
  emptyTransit: 'No shipment is on the road at the moment.',
  emptyDelivered: 'No shipment has been delivered yet.',
  emptyHistory: 'No shipments recorded yet.',
  emptyInbound: 'No shipment is on its way to you.',
  emptyReceived: 'You have not confirmed receiving any package yet.',
  loadingShipments: 'Loading shipments...',
  loadingPackages: 'Loading packages...',
  loadFailed: 'Unable to load the distribution records.',
  created: 'Shipment created.',
  dispatched: 'Shipment dispatched.',
  inTransit: 'Shipment marked in transit.',
  delivered: 'Shipment recorded as delivered.',
  cancelled: 'Shipment cancelled — no honey moved.',
  received: 'Receipt confirmed. The package is now recorded as delivered.',
  noPackage:
    'A shipment is raised against one released package. Choose a package that is ready for distribution.',
});
