/**
 * Distribution service — shipments, their journey, and the retailer's receipt.
 *
 * The journey is moved by the server through its transition table, so this module
 * posts an *action* (`dispatch`, `inTransit`, `deliver`, `cancel`) rather than a
 * status. A shipment cannot be set to a state it has not reached, and a delivery
 * cannot be recorded before a dispatch exists.
 *
 * The retailer's confirmation goes through the retailer's own endpoint, because a
 * receipt is a record of what arrived at the shop — not something the sender can
 * write on the receiver's behalf.
 */

import { ENDPOINTS } from '@/constants/api';
import { http } from '@/services/apiClient';

function listParams({ page = 1, pageSize = 20, search, ...rest } = {}) {
  return {
    page,
    page_size: pageSize,
    ...(search ? { search } : {}),
    ...Object.fromEntries(
      Object.entries(rest).filter(([, value]) => value !== undefined && value !== null && value !== ''),
    ),
  };
}

/** Shipments the caller may read: a distributor sees their own consignments. */
export async function listDistributions({
  page = 1,
  pageSize = 20,
  search,
  status,
  batchId,
  retailerId,
} = {}) {
  const { data, meta } = await http.get(ENDPOINTS.distribution.list, {
    params: listParams({
      page,
      pageSize,
      search,
      status,
      batch_id: batchId,
      retailer_id: retailerId,
    }),
  });
  return { shipments: data, meta };
}

export async function getDistributionSummary() {
  const { data } = await http.get(ENDPOINTS.distribution.summary);
  return data;
}

/** One shipment: its package, its batch, its retailer and the chain behind it. */
export async function getDistribution(distributionId) {
  const { data } = await http.get(ENDPOINTS.distribution.detail(distributionId));
  return data;
}

/** Raise a shipment against a released package. */
export async function createDistribution(payload) {
  const { data } = await http.post(ENDPOINTS.distribution.list, payload);
  return data;
}

/** Correct a shipment that has not left yet. */
export async function updateDistribution(distributionId, payload) {
  const { data } = await http.patch(ENDPOINTS.distribution.detail(distributionId), payload);
  return data;
}

export async function dispatch(distributionId, payload = {}) {
  const { data } = await http.post(ENDPOINTS.distribution.dispatch(distributionId), payload);
  return data;
}

export async function markInTransit(distributionId, payload = {}) {
  const { data } = await http.post(ENDPOINTS.distribution.inTransit(distributionId), payload);
  return data;
}

export async function deliver(distributionId, payload = {}) {
  const { data } = await http.post(ENDPOINTS.distribution.deliver(distributionId), payload);
  return data;
}

export async function cancel(distributionId, payload = {}) {
  const { data } = await http.post(ENDPOINTS.distribution.cancel(distributionId), payload);
  return data;
}

/**
 * The shops a shipment may be addressed to.
 *
 * Active retailer accounts, read from the users table through the API — not a
 * hardcoded list, and not free text. A shipment names one of these by id, which is
 * what makes it appear in that retailer's inbound list and nowhere else.
 */
export async function listRetailers() {
  const { data } = await http.get(ENDPOINTS.distribution.retailers);
  return data;
}

/**
 * Name the shop on a shipment that has none.
 *
 * Its own call rather than an edit, because the shipments needing it are usually
 * already dispatched and this is a recorded decision, not a correction.
 */
export async function assignRetailer(distributionId, payload) {
  const { data } = await http.post(ENDPOINTS.distribution.assignRetailer(distributionId), payload);
  return data;
}

/**
 * Shipments that name no retailer.
 *
 * Recorded before a receiver was required. They are reported so somebody can name
 * the shop each one actually went to; nothing is guessed automatically.
 */
export async function listUnassignedShipments({ page = 1, pageSize = 20 } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.distribution.unassigned, {
    params: { page, page_size: pageSize },
  });
  return { shipments: data, meta };
}

// --------------------------------------------------------------------------- //
// The retailer's side
// --------------------------------------------------------------------------- //
/** Counters for the retail dashboard: inbound, delivered, packages received. */
export async function getRetailerSummary() {
  const { data } = await http.get(ENDPOINTS.distribution.retailerSummary);
  return data;
}

/** Shipments addressed to the signed-in retailer. */
export async function listRetailerShipments({
  page = 1,
  pageSize = 20,
  search,
  status,
  awaitingReceipt,
} = {}) {
  const params = listParams({ page, pageSize, search, status });
  // Filtered by the server, so the page and its total describe the same rows.
  if (awaitingReceipt) params.awaiting_receipt = true;
  const { data, meta } = await http.get(ENDPOINTS.distribution.retailerShipments, { params });
  return { shipments: data, meta };
}

/** The packages the retailer has received. */
export async function listRetailerPackages({ page = 1, pageSize = 20, search, status } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.distribution.retailerPackages, {
    params: listParams({ page, pageSize, search, status }),
  });
  return { packages: data, meta };
}

/** Confirm receipt of an inbound shipment. */
export async function receiveShipment(distributionId, payload = {}) {
  const { data } = await http.post(ENDPOINTS.distribution.retailerReceive(distributionId), payload);
  return data;
}
