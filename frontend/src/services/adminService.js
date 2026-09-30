/**
 * Administrator services (ADMIN role only — the API enforces this).
 *
 * Covers the Phase 1 summary, the Phase 2 identity directory (search, detail,
 * account status changes, the audit log) and role management: creating an
 * account for any of the ten roles, and moving an account between roles.
 *
 * None of it is client-side authority. Every call is authorised by the API
 * against the stored role, so hiding a control in this app is a courtesy to the
 * user, never the control itself.
 */

import { ENDPOINTS } from '@/constants/api';
import { http } from '@/services/apiClient';

/** Platform summary: user, beekeeper and cluster counts plus module status. */
export async function getPlatformSummary() {
  const { data } = await http.get(ENDPOINTS.admin.summary);
  return data;
}

/** Paginated user directory with search, role and status filters. */
export async function listUsers({
  page = 1,
  pageSize = 20,
  search,
  role,
  isActive,
  isVerified,
} = {}) {
  const { data, meta } = await http.get(ENDPOINTS.admin.users, {
    params: {
      page,
      page_size: pageSize,
      ...(search ? { search } : {}),
      ...(role ? { role } : {}),
      ...(isActive === undefined || isActive === null ? {} : { is_active: isActive }),
      ...(isVerified === undefined || isVerified === null ? {} : { is_verified: isVerified }),
    },
  });
  return { users: data, meta };
}

/** One account with its beekeeper context and recent audited activity. */
export async function getUserDetail(userId) {
  const { data } = await http.get(ENDPOINTS.admin.userDetail(userId));
  return data;
}

/**
 * Provision an account for any of the ten roles.
 *
 * The role is chosen here and stored by the API on the account; it is what the
 * permission table consults on every later request. A BEEKEEPER account is
 * created together with its apiary record, which starts PENDING review.
 */
export async function createUser({
  name,
  email,
  password,
  role,
  phone,
  state,
  district,
  organization,
  isActive = true,
  reason,
  beekeeper,
  packagingUnitId,
} = {}) {
  const { data } = await http.post(ENDPOINTS.admin.users, {
    name,
    email,
    password,
    role,
    is_active: isActive,
    ...(phone ? { phone } : {}),
    ...(state ? { state } : {}),
    ...(district ? { district } : {}),
    ...(organization ? { organization } : {}),
    ...(reason ? { reason } : {}),
    ...(beekeeper ? { beekeeper } : {}),
    // Where a packaging operator works. The server accepts this only for a
    // PACKAGING_UNIT account, and checks the unit exists and is active before the
    // account row is written — a role that needs a facility cannot be created
    // pointing at one that is not there.
    ...(packagingUnitId ? { packaging_unit_id: packagingUnitId } : {}),
  });
  return data;
}

/**
 * Move an account to another role.
 *
 * The API records both the previous and the new role in the audit log, revokes
 * the account's live sessions (its permissions changed), and refuses the
 * caller's own account and the last active administrator.
 */
export async function setUserRole(userId, role, reason) {
  const { data } = await http.patch(ENDPOINTS.admin.userRole(userId), {
    role,
    ...(reason ? { reason } : {}),
  });
  return data;
}

/** Activate or deactivate an account, with an optional audited reason. */
export async function setUserStatus(userId, isActive, reason) {
  const { data } = await http.patch(ENDPOINTS.admin.userStatus(userId), {
    is_active: isActive,
    ...(reason ? { reason } : {}),
  });
  return data;
}

/** Append-only audit log, newest first, with optional filters. */
export async function listAuditLogs({
  page = 1,
  pageSize = 50,
  action,
  entityType,
  entityId,
  userId,
} = {}) {
  const { data, meta } = await http.get(ENDPOINTS.admin.auditLogs, {
    params: {
      page,
      page_size: pageSize,
      ...(action ? { action } : {}),
      ...(entityType ? { entity_type: entityType } : {}),
      ...(entityId ? { entity_id: entityId } : {}),
      ...(userId ? { user_id: userId } : {}),
    },
  });
  return { entries: data, meta };
}

/** Action counts over a recent window, for the dashboard activity panel. */
export async function getActivitySummary({ hours = 24 } = {}) {
  const { data } = await http.get(ENDPOINTS.admin.activity, { params: { hours } });
  return data;
}
