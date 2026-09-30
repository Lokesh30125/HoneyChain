/**
 * Reading a HoneyChain QR.
 *
 * The label the platform prints encodes exactly one thing: the link to the
 * package's public traceability page, `<PUBLIC_TRACE_BASE_URL>/<package code>`
 * (backend: `events.qr_identity`), e.g. `https://trace.example.org/trace/HC-PKG-2026-000014`.
 * The package code is the only identifier in it. The QR id printed beside the
 * code (`QR-HC-PKG-2026-000014`) is derived from the same code and resolves to the
 * same package, so it is accepted too, as is a bare package code.
 *
 * This file only decides "is this scan one of ours, and which code is in it?".
 * It never looks anything up and invents no format: the code it returns goes to
 * the existing verification flow, and the server decides what it means.
 */

/** `HC-PKG-<YYYY>-<NNNNNN>`, optionally with the `QR-` prefix of the QR id. */
const HONEYCHAIN_CODE = /^(?:QR-)?HC-PKG-\d{4}-\d+$/i;

const HAS_SCHEME = /^[a-z][a-z0-9+.-]*:/i;

export const INVALID_QR_MESSAGE = 'Invalid HoneyChain QR Code';

/**
 * The package code (or QR id) inside a scanned value, or `null` when the value is
 * not a HoneyChain label. The trace link's host is deliberately not checked: it is
 * configuration (`PUBLIC_TRACE_BASE_URL`) and differs per deployment; the code in
 * the last path segment is what identifies the package.
 */
export function parseHoneyChainQr(raw) {
  const value = typeof raw === 'string' ? raw.trim() : '';
  if (!value) return null;

  let candidate = value;
  if (HAS_SCHEME.test(value)) {
    let url;
    try {
      url = new URL(value);
    } catch {
      return null;
    }
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    const segments = url.pathname.split('/').filter(Boolean);
    if (!segments.length) return null;
    try {
      candidate = decodeURIComponent(segments[segments.length - 1]);
    } catch {
      return null;
    }
  }

  return HONEYCHAIN_CODE.test(candidate) ? candidate : null;
}
