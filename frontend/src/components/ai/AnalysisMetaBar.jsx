import { RefreshCw, Sparkles } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { AiModelNotice } from '@/components/ai/AiModelNotice';
import { formatAge, qualityMeta, sourceMeta, COMPUTE_REASON_LABELS } from '@/constants/ai';
import { formatDateTime } from '@/utils/format';

/**
 * The strip above an analysis: when it ran, what it read, and how to run it again.
 *
 * `compute_reason` is shown verbatim-ish because "why is this number from
 * yesterday?" is the question a stored analysis always raises. A read that
 * reused the stored row says so; a forced run says so too.
 */
export function AnalysisMetaBar({
  insight,
  busy = false,
  onRead = null,
  onRecompute = null,
  className = '',
}) {
  if (!insight) return null;

  const quality = insight.quality;
  const freshness = insight.freshness || {};
  const reason = COMPUTE_REASON_LABELS[insight.compute_reason] || insight.compute_reason;
  const age = formatAge(freshness.age_minutes);
  const origin = sourceMeta(insight.analysis_source);

  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-3 rounded-lg border border-sand-300 bg-sand-50/70 px-4 py-3 ${className}`}
      data-testid="ai-meta-bar"
    >
      <div className="min-w-0 space-y-1.5">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="flex items-center gap-1.5 font-medium text-ink">
            <Sparkles size={15} className="text-honey-600" aria-hidden="true" />
            {insight.analyzed
              ? `Analysis from ${formatDateTime(insight.analyzed_at)}`
              : 'No analysis stored for this hive yet'}
          </span>
          {age && insight.analyzed ? <span className="text-ink-muted">({age} ago)</span> : null}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant={origin.tone} size="sm">
            {insight.analysis_source_label || origin.label}
          </Badge>
          {quality ? (
            <Badge variant={quality.level === 'GOOD' ? 'success' : 'warning'} size="sm">
              Data quality: {qualityMeta(quality.level).label}
            </Badge>
          ) : null}
          {insight.analyzed ? (
            <Badge variant="neutral" size="sm">
              {insight.sample_count} reading(s) · window {insight.window_start
                ? formatDateTime(insight.window_start)
                : '—'}
            </Badge>
          ) : null}
          {insight.compute_reason ? (
            <Badge variant="neutral" size="sm">
              {reason}
            </Badge>
          ) : null}
          {insight.auto_analysis_enabled === false ? (
            <Badge variant="warning" size="sm">
              Automatic analysis is off on this deployment
            </Badge>
          ) : null}
        </div>

        {insight.analyzed ? (
          <AiModelNotice modelType={insight.model_type} modelVersion={insight.model_version} />
        ) : null}
      </div>

      {onRead || onRecompute ? (
        <div className="flex flex-none flex-wrap gap-2">
          {onRead ? (
            <Button variant="secondary" size="sm" onClick={onRead} disabled={busy}>
              Re-read
            </Button>
          ) : null}
          {onRecompute ? (
            <Button
              size="sm"
              loading={busy}
              onClick={onRecompute}
              leftIcon={<RefreshCw size={14} aria-hidden="true" />}
            >
              {insight.analyzed ? 'Recompute' : 'Run analysis'}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export default AnalysisMetaBar;
