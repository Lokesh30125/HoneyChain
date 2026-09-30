/**
 * Platform-level services: health probes and the role catalogue.
 * Used by the dev health indicator and by the registration form.
 */

import { ENDPOINTS } from '@/constants/api';
import { http } from '@/services/apiClient';

/** Cheap liveness probe — used by the header/footer status indicator. */
export async function getHealth() {
  const { data } = await http.get(ENDPOINTS.health, { skipAuth: true, timeout: 5000 });
  return data;
}

/** Readiness probe including database connectivity and applied tables. */
export async function getDatabaseHealth() {
  const { data } = await http.get(ENDPOINTS.healthDb, { skipAuth: true, timeout: 8000 });
  return data;
}

/** Component-by-component status report. */
export async function getDetailedHealth() {
  const { data } = await http.get(ENDPOINTS.healthDetailed, { skipAuth: true });
  return data;
}

/** Authoritative role catalogue from the backend. */
export async function getRoles() {
  const { data } = await http.get(ENDPOINTS.roles, { skipAuth: true });
  return data;
}
