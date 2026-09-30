import { Link } from 'react-router-dom';
import { CalendarClock, Check, RotateCcw, Repeat2 } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { alertStatusMeta, alertTypeLabel, severityMeta } from '@/constants/ai';
import { formatDateTime } from '@/utils/format';

/**
 * One recorded alert.
 *
 * An alert is a *prompt*, so the card shows what was recorded, when it was first
 * and last seen, how many times it recurred, and — once handled — who handled it
 * and when. The available actions are decided by the alert's own status, which
 * is why there is no "resolve" button on something already resolved.
 */
export function AlertCard({ alert, onAction = null, busy = false, hiveHref = null, className = '' }) {
  if (!alert) return null;

  const severity = severityMeta(alert.severity);
  const status = alertStatusMeta(alert.status);

  return (
    <div
      className={`rounded-lg border border-sand-300 bg-white p-4 shadow-card ${className}`}
      data-testid="ai-alert-card"
      data-alert-id={alert.id}
      data-alert-status={alert.status}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={severity.tone} size="sm">
              {severity.label}
            </Badge>
            <Badge variant={status.tone} size="sm">
              {status.label}
            </Badge>
            <span className="text-xs text-ink-muted">{alertTypeLabel(alert.alert_type)}</span>
          </div>
          <p className="mt-1.5 text-sm font-semibold text-ink">{alert.title}</p>
          <p className="mt-1 text-sm text-ink-soft">{alert.message}</p>
        </div>

        {alert.hive_code ? (
          <div className="flex-none text-right text-xs text-ink-muted">
            {hiveHref ? (
              <Link to={hiveHref} className="font-medium text-forest-700 hover:underline">
                {alert.hive_code}
              </Link>
            ) : (
              <span className="font-medium text-ink">{alert.hive_code}</span>
            )}
            {alert.metric ? <p className="mt-1">{alert.metric}</p> : null}
          </div>
        ) : null}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
        <span className="flex items-center gap-1.5">
          <CalendarClock size={13} aria-hidden="true" />
          First seen {formatDateTime(alert.first_seen_at)}
        </span>
        <span>Last seen {formatDateTime(alert.last_seen_at)}</span>
        {alert.occurrences > 1 ? (
          <span className="flex items-center gap-1.5">
            <Repeat2 size={13} aria-hidden="true" />
            Recorded {alert.occurrences}×
          </span>
        ) : null}
        {alert.acknowledged_at ? (
          <span>Acknowledged {formatDateTime(alert.acknowledged_at)}</span>
        ) : null}
      </div>

      {alert.context?.acknowledged_note ? (
        <p className="mt-2 rounded bg-sand-100 px-2.5 py-1.5 text-xs text-ink-soft">
          Note: {alert.context.acknowledged_note}
        </p>
      ) : null}

      {onAction ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {alert.status === 'OPEN' ? (
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => onAction(alert, 'acknowledge')}
              leftIcon={<Check size={14} aria-hidden="true" />}
            >
              Acknowledge
            </Button>
          ) : null}
          {alert.status !== 'RESOLVED' ? (
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => onAction(alert, 'resolve')}
              leftIcon={<Check size={14} aria-hidden="true" />}
            >
              Resolve
            </Button>
          ) : null}
          {alert.status === 'RESOLVED' ? (
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => onAction(alert, 'reopen')}
              leftIcon={<RotateCcw size={14} aria-hidden="true" />}
            >
              Reopen
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export default AlertCard;
