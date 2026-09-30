import { describe, expect, it } from 'vitest';

import { INVALID_QR_MESSAGE, parseHoneyChainQr } from '@/utils/honeychainQr';

// The payload the backend encodes is `<PUBLIC_TRACE_BASE_URL>/<package_code>`
// (backend/app/services/blockchain/events.py: qr_identity), and the default base
// is `http://localhost:4173/trace`.
describe('parseHoneyChainQr', () => {
  it('reads the link the packaging system encodes into a label', () => {
    expect(parseHoneyChainQr('http://localhost:4173/trace/HC-PKG-2026-000014')).toBe('HC-PKG-2026-000014');
  });

  it('does not depend on the deployment host or path prefix', () => {
    expect(parseHoneyChainQr('https://trace.example.org/HC-PKG-2027-000003')).toBe('HC-PKG-2027-000003');
    expect(parseHoneyChainQr('https://honey.example.in/t/trace/HC-PKG-2026-000001/')).toBe('HC-PKG-2026-000001');
    expect(parseHoneyChainQr('http://x.test/trace/HC-PKG-2026-000001?utm=1#top')).toBe('HC-PKG-2026-000001');
  });

  it('accepts the QR id and the bare package code printed on the label', () => {
    expect(parseHoneyChainQr('QR-HC-PKG-2026-000014')).toBe('QR-HC-PKG-2026-000014');
    expect(parseHoneyChainQr('HC-PKG-2026-000014')).toBe('HC-PKG-2026-000014');
    expect(parseHoneyChainQr('http://localhost:4173/verify/QR-HC-PKG-2026-000014')).toBe('QR-HC-PKG-2026-000014');
    expect(parseHoneyChainQr('  HC-PKG-2026-000014\n')).toBe('HC-PKG-2026-000014');
  });

  it.each([
    ['', 'empty'],
    ['   ', 'blank'],
    ['hello world', 'plain text'],
    ['https://example.com', 'a link with no code'],
    ['https://example.com/trace/some-other-product', 'a link to something else'],
    ['https://example.com/trace/HC-BATCH-2026-000001', 'a batch code, not a package'],
    ['HC-PKG-2026', 'a truncated code'],
    ['javascript:alert(1)//HC-PKG-2026-000001', 'a non-http scheme'],
    ['ftp://host/HC-PKG-2026-000001', 'another scheme'],
    ['upi://pay?pa=someone@bank', 'a payment QR'],
    ['WIFI:S:net;T:WPA;P:pw;;', 'a wifi QR'],
  ])('rejects %j (%s)', (raw) => {
    expect(parseHoneyChainQr(raw)).toBeNull();
  });

  it('rejects non-strings', () => {
    expect(parseHoneyChainQr(null)).toBeNull();
    expect(parseHoneyChainQr(undefined)).toBeNull();
    expect(parseHoneyChainQr(42)).toBeNull();
  });

  it('exposes the exact message the customer sees for a bad QR', () => {
    expect(INVALID_QR_MESSAGE).toBe('Invalid HoneyChain QR Code');
  });
});
