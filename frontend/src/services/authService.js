/**
 * Authentication service — the only place that knows the auth endpoints.
 */

import { ENDPOINTS } from '@/constants/api';
import { http } from '@/services/apiClient';
import { clearAccessToken, setAccessToken } from '@/services/storage';

/**
 * Register a new account.
 *
 * Returns the whole auth payload — user, access token, the beekeeper record
 * created for BEEKEEPER registrations and the role's home route — because the
 * registration screen shows the generated beekeeper code and the verification
 * state immediately after sign-up.
 */
export async function register(payload) {
  const { data } = await http.post(ENDPOINTS.auth.register, payload);
  setAccessToken(data.access_token);
  return data;
}

/** Sign in and return the authenticated user. */
export async function login({ email, password, rememberMe = false }) {
  const { data } = await http.post(ENDPOINTS.auth.login, {
    email,
    password,
    remember_me: rememberMe,
  });
  setAccessToken(data.access_token);
  return data.user;
}

/**
 * End the session. The refresh token is sent by the browser as an HttpOnly
 * cookie, so no token argument is required.
 */
export async function logout({ allDevices = false } = {}) {
  try {
    await http.post(ENDPOINTS.auth.logout, { all_devices: allDevices });
  } finally {
    // Clear locally even if the network call failed: the user asked to leave.
    clearAccessToken();
  }
}

/** Resolve the signed-in user from the current access token. */
export async function getCurrentUser() {
  const { data } = await http.get(ENDPOINTS.auth.me);
  return data;
}

/** Update the signed-in user's own profile. */
export async function updateProfile(changes) {
  const { data } = await http.patch(ENDPOINTS.users.me, changes);
  return data;
}
