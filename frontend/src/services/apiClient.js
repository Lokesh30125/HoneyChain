/**
 * Axios instance shared by every service module.
 *
 * Responsibilities
 *  - Attach the bearer access token.
 *  - Unwrap the `{ success, data, meta }` envelope so callers receive `data`.
 *  - On a 401, transparently refresh the access token once and replay the
 *    request; concurrent 401s share a single refresh (no refresh storms).
 *  - When refresh fails, notify the app so the user is returned to /login.
 *
 * UI components never import this module directly — they call a service
 * function (authService, adminService, …) so HTTP details stay in one layer.
 */

import axios from 'axios';

import { API_BASE_URL, ENDPOINTS } from '@/constants/api';
import { getAccessToken, setAccessToken, clearAccessToken } from '@/services/storage';
import { normaliseError } from '@/utils/errors';

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 20000,
  withCredentials: true, // send the HttpOnly refresh cookie
  headers: { Accept: 'application/json' },
});

// --------------------------------------------------------------------------- //
// Session-expiry notification
// --------------------------------------------------------------------------- //
const sessionListeners = new Set();

export function onSessionExpired(listener) {
  sessionListeners.add(listener);
  return () => sessionListeners.delete(listener);
}

function broadcastSessionExpired() {
  clearAccessToken();
  sessionListeners.forEach((listener) => listener());
}

// --------------------------------------------------------------------------- //
// Request interceptor
// --------------------------------------------------------------------------- //
apiClient.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token && !config.skipAuth) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// --------------------------------------------------------------------------- //
// Response interceptor — envelope unwrapping + single-flight refresh
// --------------------------------------------------------------------------- //
let refreshPromise = null;

async function refreshAccessToken() {
  if (!refreshPromise) {
    refreshPromise = apiClient
      .post(ENDPOINTS.auth.refresh, {}, { skipAuth: true, _isRefreshCall: true })
      .then((response) => {
        const accessToken = response.data?.data?.access_token;
        if (!accessToken) throw new Error('Refresh response contained no access token');
        setAccessToken(accessToken);
        return accessToken;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config || {};
    const status = error.response?.status;
    const errorCode = error.response?.data?.error?.code;
    // No point trying to refresh while the user is already on the sign-in page.
    const canAttemptRefresh = !window.location.pathname.startsWith('/login');

    const isAuthFailure =
      status === 401 &&
      !originalRequest._retried &&
      !originalRequest._isRefreshCall &&
      !originalRequest.skipAuth &&
      // A failed sign-in attempt must not trigger a refresh attempt.
      !originalRequest.url?.includes(ENDPOINTS.auth.login) &&
      !originalRequest.url?.includes(ENDPOINTS.auth.register);

    if (isAuthFailure && canAttemptRefresh) {
      originalRequest._retried = true;
      try {
        const token = await refreshAccessToken();
        originalRequest.headers = { ...(originalRequest.headers || {}), Authorization: `Bearer ${token}` };
        return apiClient(originalRequest);
      } catch {
        broadcastSessionExpired();
        return Promise.reject(normaliseError(error));
      }
    }

    // Session genuinely gone (expired/revoked refresh token) — tell the app.
    if (isAuthFailure || errorCode === 'TOKEN_INVALID' || errorCode === 'TOKEN_EXPIRED') {
      broadcastSessionExpired();
    }

    return Promise.reject(normaliseError(error));
  },
);

/**
 * Perform a request and return the unwrapped payload.
 *
 * @returns {Promise<{ data: any, meta: object|null, status: number }>}
 */
export async function request(config) {
  const response = await apiClient(config);
  const body = response.data ?? {};
  return {
    data: body.data ?? body,
    meta: body.meta ?? null,
    status: response.status,
  };
}

export const http = {
  get: (url, config = {}) => request({ ...config, method: 'get', url }),
  post: (url, data, config = {}) => request({ ...config, method: 'post', url, data }),
  patch: (url, data, config = {}) => request({ ...config, method: 'patch', url, data }),
  put: (url, data, config = {}) => request({ ...config, method: 'put', url, data }),
  delete: (url, config = {}) => request({ ...config, method: 'delete', url }),
};

export default apiClient;
