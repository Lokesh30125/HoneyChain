/**
 * Presentation helpers for dates, numbers and enum labels.
 *
 * Dates arrive as ISO-8601 UTC strings from the API. They are rendered in the
 * viewer's locale — never reformatted on the server — so a beekeeper in Guntur
 * and an officer in Delhi both read the time they expect.
 */

/** "12 Mar 2026". Returns an em dash for missing values rather than "Invalid Date". */
export function formatDate(value) {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '—';
  return parsed.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' });
}

/** "12 Mar 2026, 4:35 pm". */
export function formatDateTime(value) {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '—';
  return parsed.toLocaleString(undefined, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** Grouped thousands, e.g. 1,248. */
export function formatNumber(value) {
  if (value === null || value === undefined) return '—';
  return Number(value).toLocaleString();
}

/** "UNDER_REVIEW" → "Under review". */
export function titleCase(value) {
  if (!value) return '';
  return String(value)
    .toLowerCase()
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}
