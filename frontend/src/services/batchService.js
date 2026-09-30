/**
 * Honey batch service — reading the batches that completed harvests produced.
 *
 * There is no create, no update and no status call here, and that is the point:
 * a batch exists because a beekeeper completed a collection. The API has no
 * endpoint that could move a batch to PROCESSING, PACKAGED or DISTRIBUTED, so
 * this module cannot offer one — the traceability timeline renders those stages
 * as *not started* rather than as buttons.
 */

import { ENDPOINTS } from '@/constants/api';
import { http } from '@/services/apiClient';

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
  unclustered = false,
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
    // Only the batches that name no cluster — the pool a new cluster is built
    // from. A filter on the same rows, not a second list.
    ...(unclustered ? { unclustered: true } : {}),
  };
}

/** Batches the caller may read, paginated. */
export async function listBatches(options = {}) {
  const { data, meta } = await http.get(ENDPOINTS.batches.list, {
    params: listParams(options),
  });
  return { batches: data, meta };
}

/** A cluster's batches, read through the cluster screen (same rows, filtered). */
export async function getClusterBatches(clusterId, options = {}) {
  const { data, meta } = await http.get(ENDPOINTS.clusters.batches(clusterId), {
    params: listParams(options),
  });
  return { batches: data, meta };
}

/** One batch: sources, collection, AI context and the traceability timeline. */
export async function getBatch(batchId) {
  const { data } = await http.get(ENDPOINTS.batches.detail(batchId));
  return data;
}

export async function getBatchSummary() {
  const { data } = await http.get(ENDPOINTS.batches.summary);
  return data;
}

/** The hives that produced this batch, with the quantity each contributed. */
export async function getBatchSources(batchId) {
  const { data } = await http.get(ENDPOINTS.batches.sources(batchId));
  return data;
}

/** The hive records behind the batch (their state in the registry today). */
export async function getBatchHives(batchId) {
  const { data } = await http.get(ENDPOINTS.batches.hives(batchId));
  return data;
}

/** The collection the batch came from. */
export async function getBatchCollection(batchId) {
  const { data } = await http.get(ENDPOINTS.batches.collection(batchId));
  return data;
}

/** Where the batch stands on the supply chain: Collection done, the rest not started. */
export async function getBatchTimeline(batchId) {
  const { data } = await http.get(ENDPOINTS.batches.timeline(batchId));
  return data;
}
