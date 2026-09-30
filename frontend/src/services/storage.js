/**
 * Token storage.
 *
 * Design decision (Phase 1):
 *  - The **access token** is held in memory only. It disappears when the tab is
 *    closed, which limits the damage an XSS payload can do.
 *  - The **refresh token** lives in an HttpOnly cookie set by the API, so it is
 *    unreadable from JavaScript. The SPA never stores it.
 *
 * A small `sessionStorage` mirror of the access token is kept purely so a page
 * refresh does not force a visible re-login: the app boots, reads it, and then
 * immediately re-validates against `GET /auth/me`. Nothing here is trusted
 * beyond that round trip.
 */

const ACCESS_TOKEN_KEY = 'honeychain.access_token';

let inMemoryAccessToken = null;
const listeners = new Set();

function notify() {
  listeners.forEach((listener) => listener(inMemoryAccessToken));
}

export function getAccessToken() {
  if (inMemoryAccessToken) return inMemoryAccessToken;
  try {
    inMemoryAccessToken = window.sessionStorage.getItem(ACCESS_TOKEN_KEY);
  } catch {
    inMemoryAccessToken = null;
  }
  return inMemoryAccessToken;
}

export function setAccessToken(token) {
  inMemoryAccessToken = token || null;
  try {
    if (token) {
      window.sessionStorage.setItem(ACCESS_TOKEN_KEY, token);
    } else {
      window.sessionStorage.removeItem(ACCESS_TOKEN_KEY);
    }
  } catch {
    /* storage unavailable (private mode / SSR) — memory copy still works */
  }
  notify();
}

export function clearAccessToken() {
  setAccessToken(null);
}

export function onAccessTokenChange(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
