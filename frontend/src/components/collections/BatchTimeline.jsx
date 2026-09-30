import { AlertTriangle, Check, Circle, Lock, Minus, PauseCircle, X } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { BATCH_TIMELINE } from '@/constants/collection';
import { formatDate, formatDateTime } from '@/utils/format';

/**
 * The traceability timeline.
 *
 * Every stop is read from the batch payload, which is written from stored records:
 * Collection is complete because the harvest exists, Processing is complete because
 * a completed run exists, the Laboratory line carries the *outcome* of the test
 * that decided the batch ("✓ Approved" / "✕ Rejected"), and Packaging and
 * Distribution stay open circles because this build does not have them.
 *
 * One batch record, one timeline: the beekeeper, the laboratory technician, the
 * processor and the KVIC officer all read the same rows through this component. A
 * laboratory result that arrives while a beekeeper has the page open shows up on
 * the next load — nothing here is computed on the client or cached as truth.
 *
 * `stages` comes from the API (`batch.timeline`); `BATCH_TIMELINE` is the fallback
 * shape used while the payload is loading.
 */

function stageCopy(stage) {
  return BATCH_TIMELINE.find((entry) => entry.stage === stage) || null;
}

/** The marker for one stage: a tick, a filled dot, a cross, or an open circle. */
function StageMarker({ state, outcome }) {
  const rejected = outcome === 'REJECTED' || outcome === 'FAIL';
  const blocked = state === 'blocked';
  const decided = outcome === 'APPROVED' || outcome === 'PASS';
  const done = state === 'completed' && !rejected;
  const current = state === 'current';

  const classes = rejected
    ? 'border-status-danger bg-status-danger-bg text-status-danger'
    : blocked
      ? 'border-status-warning bg-status-warning-bg text-status-warning'
      : done || decided
        ? 'border-forest-500 bg-forest-500 text-white'
        : current
          ? 'border-honey-500 bg-honey-50 text-honey-700'
          : 'border-sand-300 bg-white text-ink-muted';

  return (
    <span
      className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border ${classes}`}
      aria-hidden="true"
    >
      {rejected ? (
        <X size={14} />
      ) : blocked ? (
        <AlertTriangle size={13} />
      ) : done || decided ? (
        <Check size={14} />
      ) : current ? (
        <Circle size={9} fill="currentColor" />
      ) : (
        <Circle size={11} />
      )}
    </span>
  );
}

/** The badge beside a stage: the honest word for its state. */
function StageBadge({ state, outcome }) {
  // A hold, a detected risk and a taken risk are three different facts, and each
  // gets its own words: "on hold" is not "failed", and neither is "proceeded".
  if (outcome === 'ON_HOLD') {
    return (
      <Badge variant="warning" size="sm">
        <PauseCircle size={12} className="mr-1" aria-hidden="true" />
        On hold
      </Badge>
    );
  }
  if (outcome === 'PROCEEDED_WITH_RISK') {
    return (
      <Badge variant="warning" size="sm">
        <AlertTriangle size={12} className="mr-1" aria-hidden="true" />
        Proceeded with recorded risk
      </Badge>
    );
  }
  if (outcome === 'RISK_DETECTED') {
    return (
      <Badge variant="danger" size="sm">
        <AlertTriangle size={12} className="mr-1" aria-hidden="true" />
        Risk detected
      </Badge>
    );
  }
  if (state === 'blocked') {
    return (
      <Badge variant="danger" size="sm">
        <Lock size={12} className="mr-1" aria-hidden="true" />
        Blocked
      </Badge>
    );
  }
  if (outcome === 'APPROVED' || outcome === 'PASS') {
    return (
      <Badge variant="success" size="sm">
        Approved
      </Badge>
    );
  }
  if (outcome === 'REJECTED' || outcome === 'FAIL') {
    return (
      <Badge variant="danger" size="sm">
        Rejected
      </Badge>
    );
  }
  if (outcome === 'INCONCLUSIVE') {
    return (
      <Badge variant="neutral" size="sm">
        Inconclusive
      </Badge>
    );
  }
  if (state === 'completed') {
    return (
      <Badge variant="success" size="sm">
        Completed
      </Badge>
    );
  }
  if (state === 'current') {
    return (
      <Badge variant="warning" size="sm">
        In progress
      </Badge>
    );
  }
  if (state === 'not_started') {
    return (
      <Badge variant="neutral" size="sm">
        Not started
      </Badge>
    );
  }
  return (
    <Badge variant="neutral" size="sm">
      Pending
    </Badge>
  );
}

export function BatchTimeline({ stages = [], loading = false }) {
  const rows = stages.length
    ? stages
    : BATCH_TIMELINE.map((entry) => ({ ...entry, state: 'not_started' }));

  return (
    <Card>
      <CardHeader
        title="Traceability timeline"
        description="Where this batch stands today, read from the records each stage produced."
      />
      <CardBody>
        <ol className="space-y-4" data-testid="batch-timeline">
          {rows.map((row) => {
            const meta = stageCopy(row.stage);
            const available = row.module_available ?? meta?.available ?? false;
            const detail = row.detail || (row.note || meta?.description);
            return (
              <li key={row.stage} className="flex gap-3" data-stage={row.stage}>
                <StageMarker state={row.state} outcome={row.outcome} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-medium text-ink">
                      {row.label || meta?.label || row.stage}
                    </p>
                    <StageBadge state={row.state} outcome={row.outcome} />
                    {!available ? (
                      <span className="text-xs text-ink-muted">Not recorded for this batch</span>
                    ) : null}
                  </div>
                  <p className="mt-1 text-xs text-ink-muted">
                    {detail}
                    {row.recorded_at
                      ? ` · ${
                          row.stage === 'COLLECTION' ? formatDate(row.recorded_at) : formatDateTime(row.recorded_at)
                        }`
                      : ''}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
        {loading ? <p className="mt-4 text-xs text-ink-muted">Loading timeline…</p> : null}
        <p className="mt-4 flex items-start gap-1.5 text-xs text-ink-muted">
          <Minus size={14} className="mt-0.5 flex-none" aria-hidden="true" />
          Every stage above is read from the same single batch record — the beekeeper, the laboratory,
          the packaging unit and KVIC all see these rows, not their own copies. A stage shows a tick
          only when the record behind it exists: processing completion, a decided test, an analysis
          that was run, packages that were actually created.
        </p>
      </CardBody>
    </Card>
  );
}

export default BatchTimeline;
