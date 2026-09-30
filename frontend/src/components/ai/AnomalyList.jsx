import { AlertTriangle, Info, Siren } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { sensorLabel } from '@/constants/ai';

/**
 * Patterns that fell outside a reference band.
 *
 * The wording matters: an entry here says a value moved, and names the band it
 * left. It never says why, and it never names a condition — those claims are not
 * something sensor data can support.
 */

const SEVERITY = {
  INFO: { icon: Info, className: 'text-status-info', label: 'Note' },
  WARNING: { icon: AlertTriangle, className: 'text-status-warning', label: 'Watch' },
  CRITICAL: { icon: Siren, className: 'text-status-danger', label: 'Out of band' },
};

export function AnomalyList({ anomalies = [], className = '' }) {
  if (!anomalies.length) {
    return (
      <p className={`text-sm text-ink-muted ${className}`}>
        Every measured pattern sat inside its reference band for this window.
      </p>
    );
  }

  return (
    <ul className={`space-y-2.5 ${className}`} data-testid="ai-anomaly-list">
      {anomalies.map((anomaly) => {
        const meta = SEVERITY[anomaly.severity] || SEVERITY.INFO;
        const Icon = meta.icon;
        return (
          <li key={anomaly.code} className="flex items-start gap-2.5">
            <Icon size={16} className={`mt-0.5 flex-none ${meta.className}`} aria-hidden="true" />
            <div className="min-w-0">
              <p className="text-sm font-medium text-ink">{anomaly.label}</p>
              <p className="mt-0.5 text-sm text-ink-soft">{anomaly.detail}</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <Badge variant="neutral" size="sm">
                  {meta.label}
                </Badge>
                {anomaly.reference ? (
                  <Badge variant="neutral" size="sm">
                    {anomaly.reference}
                  </Badge>
                ) : null}
                {(anomaly.sensors || []).map((sensor) => (
                  <Badge key={sensor} variant="honey" size="sm">
                    {sensorLabel(sensor)}
                  </Badge>
                ))}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export default AnomalyList;
