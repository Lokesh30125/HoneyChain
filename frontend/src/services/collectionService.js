/**
 * Collection service — recording and reading harvests.
 *
 * Two things are deliberately absent from every payload this module builds:
 * `beekeeper_id` and `cluster_id`. The backend derives both from the signed-in
 * beekeeper's own record and their current cluster membership, so sending them
 * would only be rejected — the service does not offer the choice, and the form
 * does not render it.
 *
 * Nothing here computes a quantity either. The per-hive figures the beekeeper
 * enters are summed by the server, which is what makes a harvest total add up to
 * the contributions it came from.
 */

import { ENDPOINTS } from '@/constants/api';
import { http } from '@/services/apiClient';

/** Query parameters for a harvest listing, with empty filters omitted. */
function listParams({
  page = 1,
  pageSize = 20,
  search,
  status,
  clusterId,
  beekeeperId,
  hiveId,
  dateFrom,
  dateTo,
  hasBatch,
} = {}) {
  return {
    page,
    page_size: pageSize,
    ...(search ? { search } : {}),
    ...(status ? { status } : {}),
    ...(clusterId ? { cluster_id: clusterId } : {}),
    ...(beekeeperId ? { beekeeper_id: beekeeperId } : {}),
    ...(hiveId ? { hive_id: hiveId } : {}),
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
    ...(hasBatch === undefined || hasBatch === null ? {} : { has_batch: hasBatch }),
  };
}

/** Harvests the caller may read — their own, or their scope as staff. */
export async function listCollections(options = {}) {
  const { data, meta } = await http.get(ENDPOINTS.collections.list, {
    params: listParams(options),
  });
  return { collections: data, meta };
}

export async function getCollection(collectionId) {
  const { data } = await http.get(ENDPOINTS.collections.detail(collectionId));
  return data;
}

/** Counters for the workspace: counts per status and harvested totals per unit. */
export async function getCollectionSummary() {
  const { data } = await http.get(ENDPOINTS.collections.summary);
  return data;
}

/**
 * The caller's own hives that can be harvested.
 *
 * The list is the apiary's real hives — an empty array means there are none, and
 * `note` says so in words rather than the screen inventing a suggestion.
 */
export async function getEligibleHives({ includeAllStatuses = false } = {}) {
  const { data } = await http.get(ENDPOINTS.collections.eligibleHives, {
    params: includeAllStatuses ? { include_all_statuses: true } : {},
  });
  return data;
}

/**
 * Record a harvest.
 *
 * `payload.hives` is a list of `{ hive_id, quantity }`; when only one hive is
 * selected the total alone is enough and the server assigns it to that hive.
 * `client_reference` is optional and makes a resubmitted form safe: repeating it
 * returns the stored harvest instead of writing a second one.
 */
export async function createCollection(payload) {
  const response = await http.post(ENDPOINTS.collections.list, payload);
  return { collection: response.data, meta: response.meta };
}

/** Correct a harvest that is still PLANNED or IN_PROGRESS. */
export async function updateCollection(collectionId, changes) {
  const { data } = await http.patch(ENDPOINTS.collections.detail(collectionId), changes);
  return data;
}

/**
 * Complete a harvest.
 *
 * The backend creates the single honey batch it produces in the same transaction
 * and reports `meta.batch_created` — `false` means the harvest was already
 * complete and the existing batch was returned, so a retry is safe to make.
 */
export async function completeCollection(collectionId, notes) {
  const response = await http.post(
    ENDPOINTS.collections.complete(collectionId),
    notes ? { notes } : {},
  );
  return { collection: response.data, meta: response.meta };
}

/** Cancel a harvest. A cancelled collection can never produce a batch. */
export async function cancelCollection(collectionId, reason) {
  const { data } = await http.post(
    ENDPOINTS.collections.cancel(collectionId),
    reason ? { reason } : {},
  );
  return data;
}

/** The batch a harvest produced, or `null` while it is still open. */
export async function getCollectionBatch(collectionId) {
  const response = await http.get(ENDPOINTS.collections.batch(collectionId));
  // The envelope omits a null payload, so 'no batch yet' arrives as undefined.
  return { batch: response.data ?? null, meta: response.meta ?? {} };
}

/**
 * A cluster's harvests, read through the cluster screen.
 *
 * The rows are the members' own collections filtered to the cluster — the same
 * records the beekeepers see, not a per-cluster copy. An officer may only read
 * clusters they are authorised for; anything else is refused by the API.
 */
export async function getClusterCollections(clusterId, options = {}) {
  const { data, meta } = await http.get(ENDPOINTS.clusters.collections(clusterId), {
    params: listParams(options),
  });
  return { collections: data, meta };
}

/** Every harvest a hive has contributed to. */
export async function listHiveCollections(hiveId) {
  const { data, meta } = await http.get(ENDPOINTS.collections.forHive(hiveId));
  return { collections: data, meta };
}
