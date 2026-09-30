/**
 * API configuration and endpoint catalogue.
 *
 * Every path is declared once here so a route rename in the backend is a
 * one-line change on the client, and so feature modules cannot drift into
 * inventing their own strings.
 */

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

export const ENDPOINTS = {
  health: '/health',
  healthDb: '/health/db',
  healthDetailed: '/health/detailed',
  roles: '/roles',

  auth: {
    register: '/auth/register',
    login: '/auth/login',
    refresh: '/auth/refresh',
    logout: '/auth/logout',
    me: '/auth/me',
  },

  users: {
    me: '/users/me',
  },

  // -- Phase 2 -------------------------------------------------------------
  profile: '/profile',

  beekeepers: {
    me: '/beekeepers/me',
    list: '/beekeepers',
    filters: '/beekeepers/filters',
    summary: '/beekeepers/summary',
    detail: (beekeeperId) => `/beekeepers/${beekeeperId}`,
    verification: (beekeeperId) => `/beekeepers/${beekeeperId}/verification`,
  },

  clusters: {
    list: '/clusters',
    detail: (clusterId) => `/clusters/${clusterId}`,
    status: (clusterId) => `/clusters/${clusterId}/status`,
    members: (clusterId) => `/clusters/${clusterId}/beekeepers`,
    member: (clusterId, beekeeperId) => `/clusters/${clusterId}/beekeepers/${beekeeperId}`,

    // Phase 4.1 — the cluster's *view* of records that live elsewhere: the
    // hives, devices, telemetry and analyses of the beekeepers in the cluster.
    // Nothing here creates a record of its own.
    summary: (clusterId) => `/clusters/${clusterId}/summary`,
    hives: (clusterId) => `/clusters/${clusterId}/hives`,
    devices: (clusterId) => `/clusters/${clusterId}/devices`,
    ai: (clusterId) => `/clusters/${clusterId}/ai`,
    latestTelemetry: (clusterId) => `/clusters/${clusterId}/telemetry/latest`,

    // Phase 5 — the cluster's harvest records, read through the same chain. The
    // officer sees the beekeeper's own rows; no per-cluster copy is created.
    collections: (clusterId) => `/clusters/${clusterId}/collections`,
    batches: (clusterId) => `/clusters/${clusterId}/batches`,

    // Prompt 10 — the batches a cluster *holds* (cluster → honey batches),
    // and the picker that offers real batches to place in one. POST writes the
    // batch's own cluster link; DELETE ends it. Nothing is ever duplicated.
    batchCandidates: (clusterId) => `/clusters/${clusterId}/batch-candidates`,
    batch: (clusterId, batchId) => `/clusters/${clusterId}/batches/${batchId}`,
    batchAnalytics: (clusterId) => `/clusters/${clusterId}/batch-analytics`,
  },

  // -- Phase 3 -------------------------------------------------------------
  hives: {
    list: '/hives',
    summary: '/hives/summary',
    filters: '/hives/filters',
    detail: (hiveId) => `/hives/${hiveId}`,
    status: (hiveId) => `/hives/${hiveId}/status`,
    // Phase 4.1 — staff placement of a hive into a cluster (or out of one).
    cluster: (hiveId) => `/hives/${hiveId}/cluster`,
    mine: '/beekeepers/me/hives',
  },

  iot: {
    devices: '/iot/devices',
    deviceSummary: '/iot/devices/summary',
    deviceDetail: (deviceId) => `/iot/devices/${deviceId}`,
    deviceStatus: (deviceId) => `/iot/devices/${deviceId}/status`,
    deviceSensors: (deviceId) => `/iot/devices/${deviceId}/sensors`,
    deviceSensor: (deviceId, sensorType) => `/iot/devices/${deviceId}/sensors/${sensorType}`,
    heartbeat: '/iot/devices/heartbeat',
    myDevices: '/iot/me/devices',
    telemetry: '/iot/telemetry',
    telemetryBatch: '/iot/telemetry/batch',
    history: (hiveId) => `/iot/telemetry/${hiveId}`,
    latestForHive: (hiveId) => `/iot/telemetry/${hiveId}/latest`,
    lastTelemetry: '/iot/last-telemetry',
    mqttHealth: '/health/mqtt',
  },

  // -- Phase 4 -------------------------------------------------------------
  ai: {
    summary: '/ai/summary',
    hives: '/ai/hives',
    insight: (hiveId) => `/ai/hives/${hiveId}`,
    analyze: (hiveId) => `/ai/hives/${hiveId}/analyze`,
    history: (hiveId) => `/ai/hives/${hiveId}/history`,
    hiveAlerts: (hiveId) => `/ai/hives/${hiveId}/alerts`,
    analyzeAll: '/ai/analyze',
    alerts: '/ai/alerts',
    alertSummary: '/ai/alerts/summary',
    alert: (alertId) => `/ai/alerts/${alertId}`,
    alertAcknowledge: (alertId) => `/ai/alerts/${alertId}/acknowledge`,
    alertResolve: (alertId) => `/ai/alerts/${alertId}/resolve`,
    alertReopen: (alertId) => `/ai/alerts/${alertId}/reopen`,
  },

  // -- Phase 5 -------------------------------------------------------------
  collections: {
    list: '/collections',
    summary: '/collections/summary',
    eligibleHives: '/collections/eligible-hives',
    detail: (collectionId) => `/collections/${collectionId}`,
    complete: (collectionId) => `/collections/${collectionId}/complete`,
    cancel: (collectionId) => `/collections/${collectionId}/cancel`,
    batch: (collectionId) => `/collections/${collectionId}/batch`,
    forHive: (hiveId) => `/hives/${hiveId}/collections`,
  },

  batches: {
    list: '/batches',
    summary: '/batches/summary',
    detail: (batchId) => `/batches/${batchId}`,
    sources: (batchId) => `/batches/${batchId}/sources`,
    hives: (batchId) => `/batches/${batchId}/hives`,
    collection: (batchId) => `/batches/${batchId}/collection`,
    timeline: (batchId) => `/batches/${batchId}/timeline`,
  },

  // -- Phase 6 -------------------------------------------------------------
  // Processing records what was done to a batch's honey; the laboratory records
  // what was measured in it. Neither keeps a copy of the batch — every read here
  // returns the same rows the batch screen shows.
  processing: {
    units: '/processing-units',
    unit: (unitId) => `/processing-units/${unitId}`,
    summary: '/processing/summary',
    awaiting: '/processing/awaiting',
    list: '/processing',
    detail: (processingId) => `/processing/${processingId}`,
    history: (processingId) => `/processing/${processingId}/history`,
    start: (processingId) => `/processing/${processingId}/start`,
    complete: (processingId) => `/processing/${processingId}/complete`,
    cancel: (processingId) => `/processing/${processingId}/cancel`,
    forBatch: (batchId) => `/processing?batch_id=${batchId}`,
    // The queues the processor screens are built from. Each is a filter over the
    // same stored runs, so a run never appears in two of them at once.
    pending: '/processing/pending',
    assigned: '/processing/assigned',
    completed: '/processing/completed',
    assign: (processingId) => `/processing/${processingId}/assign`,
    assignBatch: (batchId) => `/processing/batches/${batchId}/assign`,
    //: The accounts work may be allocated to, read from the users table by the
    //: server: an administrator sees every active processor, a processor sees
    //: only themselves.
    eligibleProcessors: '/processing/eligible-processors',
    accept: (processingId) => `/processing/${processingId}/accept`,
  },

  laboratory: {
    facilities: '/laboratories',
    facility: (laboratoryId) => `/laboratories/${laboratoryId}`,
    parameters: '/lab-parameters',
    parameter: (code) => `/lab-parameters/${code}`,
    summary: '/lab-tests/summary',
    awaiting: '/lab-tests/awaiting',
    tests: '/lab-tests',
    test: (testId) => `/lab-tests/${testId}`,
    results: (testId) => `/lab-tests/${testId}/results`,
    result: (testId, resultId) => `/lab-tests/${testId}/results/${resultId}`,
    complete: (testId) => `/lab-tests/${testId}/complete`,
    override: (testId) => `/lab-tests/${testId}/override`,
    forBatch: (batchId) => `/lab-tests?batch_id=${batchId}`,
    pending: '/lab-tests/pending',
    assigned: '/lab-tests/assigned',
    completed: '/lab-tests/completed',
    withoutTests: '/lab-tests/batches/awaiting-test',
    assign: (testId) => `/lab-tests/${testId}/assign`,
    assignBatch: (batchId) => `/lab-tests/batches/${batchId}/assign`,
    //: The active laboratory technicians the platform holds, with how much open
    //: work each is already carrying.
    eligibleTechnicians: '/lab-tests/eligible-technicians',
    accept: (testId) => `/lab-tests/${testId}/accept`,
    //: Tests the laboratory closed without a decision: parked, not lost, and
    //: blocking packaging until somebody answers them.
    held: '/lab-tests/held',
    //: The quality analysis. It is run by the server over the recorded values —
    //: the client never sends a verdict, a score or a risk level.
    analyze: (testId) => `/lab-tests/${testId}/analyze`,
    hold: (testId) => `/lab-tests/${testId}/hold`,
    proceedWithRisk: (testId) => `/lab-tests/${testId}/proceed-with-risk`,
  },

  // -- Phase 7 -------------------------------------------------------------
  // Packaging fills the approved honey into coded packages; distribution moves
  // those packages. Both read the batch they came from rather than copying it.
  packaging: {
    units: '/packaging-units',
    unit: (unitId) => `/packaging-units/${unitId}`,
    // The facility the signed-in operator works at. The server answers from the
    // account's own attachment, so the workspace never has to ask who the user is
    // or offer them a list of organisations to guess from.
    myUnit: '/packaging-units/mine',
    unitMembers: (unitId) => `/packaging-units/${unitId}/members`,
    unitMember: (unitId, memberId) => `/packaging-units/${unitId}/members/${memberId}`,
    summary: '/packaging/summary',
    approvedBatches: '/packaging/approved-batches',
    list: '/packaging',
    detail: (packagingId) => `/packaging/${packagingId}`,
    start: (packagingId) => `/packaging/${packagingId}/start`,
    complete: (packagingId) => `/packaging/${packagingId}/complete`,
    cancel: (packagingId) => `/packaging/${packagingId}/cancel`,
    release: (packagingId) => `/packaging/${packagingId}/release`,
    forBatch: (batchId) => `/packaging?batch_id=${batchId}`,
    packages: '/packages',
    package: (packageId) => `/packages/${packageId}`,
    packageRelease: (packageId) => `/packages/${packageId}/release`,
    packagesForBatch: (batchId) => `/batches/${batchId}/packages`,
  },

  distribution: {
    summary: '/distribution/summary',
    list: '/distribution',
    // The shops a shipment may be addressed to, and the shipments that name none.
    retailers: '/distribution/retailers',
    unassigned: '/distribution/unassigned',
    // The repair for a shipment that names no retailer.
    assignRetailer: (id) => `/distribution/${id}/assign-retailer`,
    detail: (distributionId) => `/distribution/${distributionId}`,
    dispatch: (distributionId) => `/distribution/${distributionId}/dispatch`,
    inTransit: (distributionId) => `/distribution/${distributionId}/in-transit`,
    deliver: (distributionId) => `/distribution/${distributionId}/deliver`,
    cancel: (distributionId) => `/distribution/${distributionId}/cancel`,
    forBatch: (batchId) => `/distribution?batch_id=${batchId}`,
    // The retailer's own side of the counter.
    retailerSummary: '/retailer/summary',
    retailerShipments: '/retailer/shipments',
    retailerReceive: (distributionId) => `/retailer/shipments/${distributionId}/receive`,
    retailerPackages: '/retailer/packages',
  },

  // -- Phase 8 -------------------------------------------------------------
  // The traceability layer. The ledger endpoints are read by the Admin and the
  // KVIC officer (the backend narrows a KVIC officer to their own clusters);
  // everything else reaches the chain through the record it belongs to, so no
  // screen has to know what the blockchain service's URL is.
  blockchain: {
    transactions: '/blockchain/transactions',
    transaction: (eventId) => `/blockchain/transactions/${eventId}`,
    ledger: '/blockchain/ledger',
    health: '/blockchain/health',
    sync: '/blockchain/sync',
    retry: (eventId) => `/blockchain/transactions/${eventId}/retry`,
    // A batch's own traceability: its timeline, its events, its packages.
    batch: (batchId) => `/blockchain/batches/${batchId}`,
    // A package's QR identity. POST issues it once; the same identity comes
    // back for ever after, so a printed label never points anywhere else.
    packageQr: (packageId) => `/blockchain/packages/${packageId}/qr`,
  },

  // The customer's unauthenticated route: one code resolves one package.
  trace: {
    package: (packageCode) => `/trace/${encodeURIComponent(packageCode)}`,
    qrImage: (packageCode) => `/trace/${encodeURIComponent(packageCode)}/qr.svg`,
  },

  admin: {
    summary: '/admin/summary',
    users: '/admin/users',
    userDetail: (userId) => `/admin/users/${userId}`,
    userStatus: (userId) => `/admin/users/${userId}/status`,
    userRole: (userId) => `/admin/users/${userId}/role`,
    auditLogs: '/admin/audit-logs',
    activity: '/admin/activity',
  },
};

/** Error codes emitted by the backend, mirrored for client-side branching. */
export const API_ERROR_CODES = {
  VALIDATION_ERROR: 'VALIDATION_ERROR',
  AUTHENTICATION_ERROR: 'AUTHENTICATION_ERROR',
  INVALID_CREDENTIALS: 'INVALID_CREDENTIALS',
  TOKEN_EXPIRED: 'TOKEN_EXPIRED',
  TOKEN_INVALID: 'TOKEN_INVALID',
  PERMISSION_DENIED: 'PERMISSION_DENIED',
  ACCOUNT_INACTIVE: 'ACCOUNT_INACTIVE',
  NOT_FOUND: 'NOT_FOUND',
  CONFLICT: 'CONFLICT',
  DUPLICATE_RESOURCE: 'DUPLICATE_RESOURCE',
  RATE_LIMITED: 'RATE_LIMITED',
  BAD_REQUEST: 'BAD_REQUEST',
  DATABASE_ERROR: 'DATABASE_ERROR',
  SERVICE_UNAVAILABLE: 'SERVICE_UNAVAILABLE',
  INTERNAL_ERROR: 'INTERNAL_ERROR',
  NOT_IMPLEMENTED: 'NOT_IMPLEMENTED',
  NETWORK_ERROR: 'NETWORK_ERROR',
};

/** Human-readable fallbacks shown when the API sends no message. */
export const ERROR_MESSAGES_BY_STATUS = {
  400: 'That request could not be processed. Please check the details and try again.',
  401: 'Your session has expired. Please sign in again.',
  403: 'You do not have permission to view this page.',
  404: 'We could not find what you were looking for.',
  409: 'This record already exists.',
  422: 'Some of the details you entered are not valid.',
  429: 'Too many attempts. Please wait a moment and try again.',
  500: 'Something went wrong on our side. Please try again shortly.',
  503: 'The service is temporarily unavailable. Please try again shortly.',
};

/** Verification states, mirrored from the backend enum for filters and badges. */
export const VERIFICATION_STATUSES = [
  { value: 'PENDING', label: 'Pending' },
  { value: 'UNDER_REVIEW', label: 'Under review' },
  { value: 'VERIFIED', label: 'Verified' },
  { value: 'REJECTED', label: 'Rejected' },
  { value: 'SUSPENDED', label: 'Suspended' },
];
