import { Badge } from '@/components/ui/Badge';
import { formatDelta, sensorLabel } from '@/constants/ai';

/**
 * The evidence list behind a score.
 *
 * Both the colony-health factors and the disease/swarming indicators are the
 * same shape, so they render through this one component: a label, the measured
 * value, the reference it was compared against, and the number of points it
 * contributed. Showing the deltas is what makes the score auditable — a reader
 * can add them up and reach the published arithmetic.
 */

const DIRECTION_CLASSES = {
  POSITIVE: 'text-status-success',
  NEGATIVE: 'text-status-danger',
  NEUTRAL: 'text-ink-muted',
};

const DIRECTION_LABELS = {
  POSITIVE: 'Supports',
  NEGATIVE: 'Counts against',
  NEUTRAL: 'Neutral',
};

export function ContributionList({
  items = [],
  emptyLabel = 'No contributing patterns were recorded for this window.',
  showDelta = true,
  className = '',
}) {
  if (!items.length) {
    return <p className={`text-sm text-ink-muted ${className}`}>{emptyLabel}</p>;
  }

  return (
    <ul className={`divide-y divide-sand-200 ${className}`} data-testid="ai-contribution-list">
      {items.map((item) => (
        <li key={item.code} className="flex items-start justify-between gap-3 py-2.5 first:pt-0 last:pb-0">
          <div className="min-w-0">
            <p className="text-sm font-medium text-ink">{item.label}</p>
            <p className="mt-0.5 text-sm text-ink-soft">{item.detail}</p>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              {item.reference ? (
                <Badge variant="neutral" size="sm">
                  {item.reference}
                </Badge>
              ) : null}
              {(item.sensors || []).map((sensor) => (
                <Badge key={sensor} variant="honey" size="sm">
                  {sensorLabel(sensor)}
                </Badge>
              ))}
            </div>
          </div>

          {showDelta ? (
            <div className="flex-none text-right">
              <span
                className={`text-sm font-semibold tabular-nums ${
                  DIRECTION_CLASSES[item.direction] || DIRECTION_CLASSES.NEUTRAL
                }`}
                title={DIRECTION_LABELS[item.direction] || ''}
              >
                {formatDelta(item.delta)}
              </span>
              <p className="text-[11px] text-ink-muted">points</p>
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

export default ContributionList;
