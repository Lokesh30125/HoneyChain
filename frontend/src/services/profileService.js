/**
 * Profile service — the signed-in user's own profile.
 *
 * There is no "get another user's profile" call by design: the API has no route
 * for it, and administrative review goes through `adminService`.
 */

import { ENDPOINTS } from '@/constants/api';
import { http } from '@/services/apiClient';

/** Account, profile details and (for beekeepers) the beekeeper summary. */
export async function getMyProfile() {
  const { data } = await http.get(ENDPOINTS.profile);
  return data;
}

/** Full update — fields omitted from the payload are cleared. */
export async function replaceMyProfile(changes) {
  const { data } = await http.put(ENDPOINTS.profile, changes);
  return data;
}

/** Partial update — only the fields supplied are changed. */
export async function updateMyProfile(changes) {
  const { data } = await http.patch(ENDPOINTS.profile, changes);
  return data;
}
