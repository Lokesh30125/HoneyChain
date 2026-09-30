import { SkeletonBlock } from '@/components/common/LoadingState';

/**
 * Headline metric tile.
 *
 * Used by dashboards across every phase (hive counts, sensor averages, quality
 * pass rates, batches anchored on chain …), so it stays presentational: it
 * renders whatever it is given and never fetches.
 */
export function StatCard({
  label,
  value,
  helper,
  icon = null,
  tone = 'default',
  loading = false,
  className = '',
}) {
  const toneStyles = {
    default: 'bg-white',
    honey: 'bg-honey-50',
    forest: 'bg-forest-50',
    // A figure that needs attention — held laboratory tests, blocked batches —
    // is not painted the same as one that is merely a count.
    warning: 'bg-status-warning-bg',
  };

  return (
    <div
      className={`rounded-card border border-sand-300 p-4 shadow-card ${toneStyles[tone] || toneStyles.default} ${className}`}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-ink-soft">{label}</p>
        {icon ? (
          <span className="flex h-8 w-8 flex-none items-center justify-center rounded-lg bg-white text-forest-700 ring-1 ring-sand-300">
            {icon}
          </span>
        ) : null}
      </div>

      {loading ? (
        <SkeletonBlock className="mt-3 h-7 w-20" />
      ) : (
        <p className="mt-2 text-2xl font-semibold tracking-tight text-ink">{value ?? '—'}</p>
      )}

      {helper ? <p className="mt-1 text-xs text-ink-muted">{helper}</p> : null}
    </div>
  );
}

export default StatCard;
