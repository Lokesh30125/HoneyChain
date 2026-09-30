/**
 * Authentication context.
 *
 * Holds exactly one piece of global state (the signed-in user) and exposes the
 * four operations the UI needs. Everything else — form state, loading flags for
 * a specific button — stays local to components, which keeps state ownership
 * predictable.
 *
 * Boot sequence:
 *   1. If no access token is present, finish immediately as "anonymous".
 *   2. Otherwise call `GET /auth/me` to confirm the token is still valid and to
 *      pick up role or profile changes since the token was issued.
 */

import { createContext, useCallback, useEffect, useMemo, useRef, useState } from 'react';

import * as authService from '@/services/authService';
import { onSessionExpired } from '@/services/apiClient';
import { getAccessToken } from '@/services/storage';
import { normaliseError } from '@/utils/errors';

export const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState('loading'); // loading | authenticated | anonymous
  const [error, setError] = useState(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  /** Confirm the stored token and load the profile. */
  const bootstrap = useCallback(async () => {
    if (!getAccessToken()) {
      setUser(null);
      setStatus('anonymous');
      return;
    }

    setStatus('loading');
    try {
      const profile = await authService.getCurrentUser();
      if (!mounted.current) return;
      setUser(profile);
      setStatus('authenticated');
    } catch (caught) {
      if (!mounted.current) return;
      setUser(null);
      setStatus('anonymous');
      setError(normaliseError(caught));
    }
  }, []);

  useEffect(() => {
    bootstrap();
  }, [bootstrap]);

  // When a background refresh fails, drop the session instead of leaving the UI
  // in a half-authenticated state.
  useEffect(
    () =>
      onSessionExpired(() => {
        setUser(null);
        setStatus('anonymous');
      }),
    [],
  );

  const login = useCallback(async (credentials) => {
    const profile = await authService.login(credentials);
    setUser(profile);
    setStatus('authenticated');
    setError(null);
    return profile;
  }, []);

  const register = useCallback(async (payload) => {
    const result = await authService.register(payload);
    setUser(result.user);
    setStatus('authenticated');
    setError(null);
    return result;
  }, []);

  const logout = useCallback(async (options = {}) => {
    try {
      await authService.logout(options);
    } finally {
      setUser(null);
      setStatus('anonymous');
    }
  }, []);

  /**
   * Re-read the session from the API (`GET /auth/me`).
   *
   * Used after a page reload and after any change that may have altered the
   * account server-side (role, activation, beekeeper verification), so the UI
   * never keeps rendering stale authorisation.
   */
  const refreshSession = useCallback(async () => {
    const profile = await authService.getCurrentUser();
    setUser(profile);
    return profile;
  }, []);

  /** Apply a locally updated profile (e.g. PATCH /users/me response). */
  const applyProfile = useCallback((updated) => {
    setUser(updated);
    return updated;
  }, []);

  const value = useMemo(
    () => ({
      user,
      role: user?.role ?? null,
      isAuthenticated: status === 'authenticated',
      isLoading: status === 'loading',
      error,
      login,
      register,
      logout,
      refreshSession,
      applyProfile,
    }),
    [user, status, error, login, register, logout, refreshSession, applyProfile],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
