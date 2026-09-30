import { Badge } from '@/components/ui/Badge';
import { formatConfidence } from '@/constants/ai';

/**
 * Projected stored-honey mass, or an explanation of why there is no number.
 *
 * There are four outcomes and each looks different on purpose:
 *
 *  - a projection, with its period, unit, fit and the caveats recorded with it;
 *  - `available: false` with a reason (too little history, an implausible weight
 *    step) — the reason is the content, not a placeholder;
 *  - no weight sensor at all;
 *  - nothing said yet because there is no analysis.
 *
 * Nothing here ever rounds a number up, and a missing projection is never shown
 * as `0 kg`.
 */
export function YieldProjectionPanel({
  prediction = null,
  analysed = true,
  className = '',
}) {
  if (!analysed) {
    return (
      <p className={`text-sm text-ink-muted ${className}`} data-testid="ai-yield-panel">
        No analysis has been run for this hive yet.
      </p>
    );
  }

  if (!prediction) {
    return (
      <p className={`text-sm text-ink-muted ${className}`} data-testid="ai-yield-panel">
        This analysis stored no yield projection.
      </p>
    );
  }

  if (!prediction.available || prediction.predicted_yield === null) {
    return (
      <div className={`space-y-2 ${className}`} data-testid="ai-yield-panel">
        <p className="text-2xl font-semibold text-ink-muted">Not projected</p>
        <p className="text-sm text-ink-soft">
          {prediction.reason || 'There is not enough weight history to project a yield yet.'}
        </p>
        {prediction.basis ? <p className="text-xs text-ink-muted">{prediction.basis}</p> : null}
      </div>
    );
  }

  return (
    <div className={`space-y-2 ${className}`} data-testid="ai-yield-panel">
      <p className="text-3xl font-semibold tracking-tight text-ink">
        {prediction.predicted_yield.toFixed(2)}{' '}
        <span className="text-lg font-medium text-ink-soft">{prediction.unit}</span>
      </p>
      <p className="text-sm text-ink-soft">
        Projected weight change over the next {prediction.period_days} days, from the measured weight
        trend. An extrapolation — not a harvest promise.
      </p>

      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="neutral" size="sm">
          Confidence {formatConfidence(prediction.confidence)}
        </Badge>
        <Badge variant="neutral" size="sm">
          Trend {prediction.trend_label}
        </Badge>
        {prediction.fit !== null && prediction.fit !== undefined ? (
          <Badge variant="neutral" size="sm">
            Line fit {Math.round(prediction.fit * 100)}%
          </Badge>
        ) : null}
        {prediction.observed_days ? (
          <Badge variant="neutral" size="sm">
            {prediction.observed_days.toFixed(1)} days observed
          </Badge>
        ) : null}
        {prediction.samples ? (
          <Badge variant="neutral" size="sm">
            {prediction.samples} weight readings
          </Badge>
        ) : null}
      </div>

      {prediction.notes?.length ? (
        <ul className="list-disc space-y-1 pl-5 text-sm text-ink-muted">
          {prediction.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export default YieldProjectionPanel;
