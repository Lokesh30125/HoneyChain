/**
 * Cluster analytics service — the KVIC officer's view of a cluster.
 *
 * Every call here is a *read through* the organisational chain
 * (`cluster → beekeeper → hive → device → telemetry → analysis`). The endpoints
 * return counts and rows that belong to records stored elsewhere; none of them
 * creates a cluster copy of a hive, a device, a reading or an assessment.
 *
 * A 403 means the signed-in role has no cluster view at all (a beekeeper reads
 * their own hive through the hive endpoints instead). The pages translate that
 * with `normaliseError`, they do not pre-empt it.
 */

import { ENDPOINTS } from '@/constants/api';
import { http } from '@/services/apiClient';

/** Counters for one cluster: members, hives, devices, telemetry, analysis. */
export async function getClusterOverview(clusterId) {
  const { data } = await http.get(ENDPOINTS.clusters.summary(clusterId));
  return data;
}

/** The hives inside the cluster, paginated. */
export async function listClusterHives(clusterId, { page = 1, pageSize = 20 } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.clusters.hives(clusterId), {
    params: { page, page_size: pageSize },
  });
  return { hives: data, meta };
}

/** The devices attached to those hives, paginated. */
export async function listClusterDevices(clusterId, { page = 1, pageSize = 20 } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.clusters.devices(clusterId), {
    params: { page, page_size: pageSize },
  });
  return { devices: data, meta };
}

/**
 * The latest stored analysis per hive in the cluster.
 *
 * An unanalysed hive is listed with `analyzed: false` rather than being omitted,
 * so the officer can see how much of the cluster has been assessed at all.
 */
export async function getClusterAiState(clusterId) {
  const { data } = await http.get(ENDPOINTS.clusters.ai(clusterId));
  return data;
}

/**
 * The most recent reading in the cluster, with the chain that produced it
 * (device → hive → beekeeper). `has_data: false` when nothing is stored: the
 * panel then says so instead of showing zeroes as if they were measurements.
 */
export async function getClusterLatestTelemetry(clusterId) {
  const { data } = await http.get(ENDPOINTS.clusters.latestTelemetry(clusterId));
  return data;
}
