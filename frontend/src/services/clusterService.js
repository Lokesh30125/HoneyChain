/**
 * KVIC cluster service — cluster management, membership, and the batches a
 * cluster holds.
 *
 * The batch calls here write the relationship and nothing else:
 * ``honey_batches.cluster_id`` (and, in step with it, the harvest's own
 * ``cluster_id``). No batch, collection, beekeeper or hive is created, copied or
 * moved, and the counts these calls return are the server's, counted from the
 * rows that now exist.
 */

import { ENDPOINTS } from '@/constants/api';
import { http } from '@/services/apiClient';

export async function listClusters({ page = 1, pageSize = 20, search, district, state, isActive } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.clusters.list, {
    params: {
      page,
      page_size: pageSize,
      ...(search ? { search } : {}),
      ...(district ? { district } : {}),
      ...(state ? { state } : {}),
      ...(isActive === undefined || isActive === null ? {} : { is_active: isActive }),
    },
  });
  return { clusters: data, meta };
}

export async function getCluster(clusterId) {
  const { data } = await http.get(ENDPOINTS.clusters.detail(clusterId));
  return data;
}

/** Create a cluster. Omit `cluster_code` and the backend generates one. */
export async function createCluster(payload) {
  const { data } = await http.post(ENDPOINTS.clusters.list, payload);
  return data;
}

export async function updateCluster(clusterId, changes) {
  const { data } = await http.put(ENDPOINTS.clusters.detail(clusterId), changes);
  return data;
}

export async function setClusterStatus(clusterId, isActive, reason) {
  const { data } = await http.patch(ENDPOINTS.clusters.status(clusterId), {
    is_active: isActive,
    ...(reason ? { reason } : {}),
  });
  return data;
}

/**
 * Remove a cluster.
 *
 * Only an empty cluster comes back removed. A cluster with records under it is
 * refused with a 409 whose `details` are the counts — beekeepers, hives,
 * collections, batches, tests, runs, packages — so the screen can say exactly what
 * is keeping it, and `can_delete: false` is the same answer stated plainly.
 *
 * `confirm: true` is required by the API: removing a cluster is deliberate, and a
 * request that arrives by accident must not do it.
 */
export async function deleteCluster(clusterId, { reason } = {}) {
  const { data } = await http.delete(ENDPOINTS.clusters.detail(clusterId), {
    data: { confirm: true, ...(reason ? { reason } : {}) },
  });
  return data;
}

export async function listClusterMembers(clusterId, { page = 1, pageSize = 20 } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.clusters.members(clusterId), {
    params: { page, page_size: pageSize },
  });
  return { members: data, meta };
}

export async function addClusterMember(clusterId, beekeeperId) {
  const { data } = await http.post(ENDPOINTS.clusters.member(clusterId, beekeeperId));
  return data;
}

export async function removeClusterMember(clusterId, beekeeperId) {
  const { data } = await http.delete(ENDPOINTS.clusters.member(clusterId, beekeeperId));
  return data;
}

// --------------------------------------------------------------------------- #
// The batches a cluster holds
// --------------------------------------------------------------------------- #
/**
 * Real batches offered to a cluster's *Add batches* picker.
 *
 * Each row is the batch's own record — code, harvest, beekeeper, quantity, stage
 * status — plus where it currently sits (`placement`, `placement_label`) and
 * whether moving it would need the officer's explicit confirmation
 * (`requires_confirmation`). `assignment` filters the list:
 * `unassigned` | `this_cluster` | `other_cluster` | `any`.
 */
export async function listBatchCandidates(
  clusterId,
  { page = 1, pageSize = 20, search, status, assignment = 'any' } = {},
) {
  const { data, meta } = await http.get(ENDPOINTS.clusters.batchCandidates(clusterId), {
    params: {
      page,
      page_size: pageSize,
      ...(search ? { search } : {}),
      ...(status ? { status } : {}),
      ...(assignment && assignment !== 'any' ? { assignment } : {}),
    },
  });
  return { batches: data, meta };
}

/**
 * Place batches in a cluster (writes the batch's own cluster link).
 *
 * A batch that already belongs to another cluster is refused with a 409 whose
 * `details.batches` name each one and its cluster; the same call with
 * `reassign: true` — which the form only sends after the officer confirms — moves
 * them by updating that same record. Assigning a batch that is already here is
 * reported as `already`, never as a duplicate.
 */
export async function assignBatches(clusterId, batchIds, { reassign = false } = {}) {
  const { data } = await http.post(ENDPOINTS.clusters.batches(clusterId), {
    batch_ids: batchIds,
    reassign,
  });
  return data;
}

/** End a batch's cluster link. The batch and its harvest are left untouched. */
export async function detachBatch(clusterId, batchId) {
  const { data } = await http.delete(ENDPOINTS.clusters.batch(clusterId, batchId));
  return data;
}

/**
 * The cluster's production figures, counted from the stored rows: batches,
 * harvests, beekeepers represented, quantities, packages and the stage
 * breakdown. Zeros mean "nothing stored", not "not loaded".
 */
export async function getClusterBatchAnalytics(clusterId) {
  const { data } = await http.get(ENDPOINTS.clusters.batchAnalytics(clusterId));
  return data;
}
