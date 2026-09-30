/**
 * Beekeeper service.
 *
 * Two audiences share this module: a beekeeper reading and editing their own
 * record (`/beekeepers/me`), and administrators or KVIC officers working the
 * directory and the verification queue. The API decides who may call what; the
 * client only mirrors that in navigation and buttons.
 */

import { ENDPOINTS } from '@/constants/api';
import { http } from '@/services/apiClient';

// -- Self-service ----------------------------------------------------------
export async function getMyBeekeeperRecord() {
  const { data } = await http.get(ENDPOINTS.beekeepers.me);
  return data;
}

export async function updateMyBeekeeperRecord(changes) {
  const { data } = await http.put(ENDPOINTS.beekeepers.me, changes);
  return data;
}

// -- Directory (ADMIN / KVIC_OFFICER) --------------------------------------
/**
 * Paginated directory.
 *
 * Filters are omitted when empty so the querystring stays readable and the
 * backend receives exactly what the user asked for.
 */
export async function listBeekeepers({
  page = 1,
  pageSize = 20,
  search,
  district,
  state,
  cluster,
  verificationStatus,
  beeSpecies,
} = {}) {
  const { data, meta } = await http.get(ENDPOINTS.beekeepers.list, {
    params: {
      page,
      page_size: pageSize,
      ...(search ? { search } : {}),
      ...(district ? { district } : {}),
      ...(state ? { state } : {}),
      ...(cluster ? { cluster } : {}),
      ...(verificationStatus ? { verification_status: verificationStatus } : {}),
      ...(beeSpecies ? { bee_species: beeSpecies } : {}),
    },
  });
  return { beekeepers: data, meta };
}

/** Detail view including the append-only verification history. */
export async function getBeekeeper(beekeeperId) {
  const { data } = await http.get(ENDPOINTS.beekeepers.detail(beekeeperId));
  return data;
}

/** Officer/administrator edit, including cluster assignment. */
export async function updateBeekeeper(beekeeperId, changes) {
  const { data } = await http.put(ENDPOINTS.beekeepers.detail(beekeeperId), changes);
  return data;
}

/**
 * Change verification status.
 *
 * `remarks` is required by the API for rejections and suspensions, so the form
 * asks for it up front rather than letting the request fail.
 */
export async function changeVerification(beekeeperId, { status, remarks }) {
  const { data } = await http.patch(ENDPOINTS.beekeepers.verification(beekeeperId), {
    status,
    ...(remarks ? { remarks } : {}),
  });
  return data;
}

/** Distinct districts/states present in the data, for filter dropdowns. */
export async function getFilterOptions() {
  const { data } = await http.get(ENDPOINTS.beekeepers.filters);
  return data;
}

/** Aggregate counts (database-backed; zeros on an empty platform). */
export async function getBeekeeperSummary() {
  const { data } = await http.get(ENDPOINTS.beekeepers.summary);
  return data;
}
