import { Badge } from '@/components/ui/Badge';
import { priorityMeta, sensorLabel } from '@/constants/ai';

/**
 * The actionable list.
 *
 * Every entry carries the observation it came from, because "check ventilation"
 * with no reason is indistinguishable from advice a machine made up. Priority is
 * a reading order, not an alarm: `PRIORITY` means look at the first opportunity,
 * and the engine never labels a sensor reading urgent.
 */
export function RecommendationList({ recommendations = [], className = '' }) {
  if (!recommendations.length) {
    return (
      <p className={`text-sm text-ink-muted ${className}`} data-testid="ai-recommendation-list">
        Nothing on this hive needs attention from the recorded patterns.
      </p>
    );
  }

  return (
    <ul className={`space-y-3 ${className}`} data-testid="ai-recommendation-list">
      {recommendations.map((item) => {
        const priority = priorityMeta(item.priority);
        return (
          <li key={item.code} className="rounded-lg border border-sand-200 bg-sand-50/60 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={priority.tone} size="sm">
                {priority.label}
              </Badge>
              <p className="text-sm font-semibold text-ink">{item.title}</p>
            </div>
            <p className="mt-1 text-sm text-ink-soft">{item.detail}</p>
            {item.reason ? <p className="mt-1.5 text-xs text-ink-muted">{item.reason}</p> : null}
            {item.sensors?.length ? (
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {item.sensors.map((sensor) => (
                  <Badge key={sensor} variant="honey" size="sm">
                    {sensorLabel(sensor)}
                  </Badge>
                ))}
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

export default RecommendationList;
