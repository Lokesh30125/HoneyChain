import { DataTable } from '@/components/common/DataTable';
import { Badge } from '@/components/ui/Badge';
import { healthMeta, riskMeta } from '@/constants/ai';
import { formatDate, formatDateTime } from '@/utils/format';

/**
 * Stored analyses, newest first.
 *
 * History is not decoration: it is how a beekeeper sees whether the indicator is
 * drifting, and it is why an analysis is stored rather than recomputed on every
 * page view. Each row is a frozen snapshot — an old row keeps the model version
 * and the band it was produced with.
 */
export function AnalysisHistoryTable({
  analyses = [],
  loading = false,
  error = null,
  onRetry = null,
  meta = null,
  onPageChange = null,
  className = '',
}) {
  const columns = [
    {
      key: 'analyzed_at',
      header: 'Run at',
      render: (row) => (
        <div>
          <p className="font-medium text-ink">{formatDateTime(row.analyzed_at)}</p>
          <p className="text-xs text-ink-muted">
            {formatDate(row.window_start)} → {formatDate(row.window_end)}
          </p>
        </div>
      ),
    },
    {
      key: 'health',
      header: 'Health',
      render: (row) => (
        <div className="flex items-center gap-2">
          <span className="font-semibold tabular-nums text-ink">
            {row.health?.score ?? '—'}
          </span>
          <Badge variant={healthMeta(row.health?.status).tone} size="sm">
            {row.health?.status_label || healthMeta(row.health?.status).label}
          </Badge>
        </div>
      ),
    },
    {
      key: 'disease_risk',
      header: 'Disease risk',
      render: (row) => (
        <Badge variant={riskMeta(row.disease_risk?.level).tone} size="sm">
          {row.disease_risk?.level_label || riskMeta(row.disease_risk?.level).label}
          {typeof row.disease_risk?.score === 'number' ? ` · ${row.disease_risk.score}` : ''}
        </Badge>
      ),
    },
    {
      key: 'swarming_risk',
      header: 'Swarming risk',
      render: (row) => (
        <Badge variant={riskMeta(row.swarming_risk?.level).tone} size="sm">
          {row.swarming_risk?.level_label || riskMeta(row.swarming_risk?.level).label}
          {typeof row.swarming_risk?.score === 'number' ? ` · ${row.swarming_risk.score}` : ''}
        </Badge>
      ),
    },
    {
      key: 'yield',
      header: 'Projection',
      render: (row) =>
        row.yield_prediction?.available && row.yield_prediction.predicted_yield !== null ? (
          <span className="tabular-nums text-ink">
            {row.yield_prediction.predicted_yield.toFixed(2)} {row.yield_prediction.unit} /{' '}
            {row.yield_prediction.period_days} d
          </span>
        ) : (
          <span className="text-ink-muted">Not projected</span>
        ),
    },
    {
      key: 'quality',
      header: 'Evidence',
      render: (row) => (
        <div className="text-xs text-ink-muted">
          <p>{row.data_quality_label}</p>
          <p>
            {row.sample_count} reading(s) · {row.analysis_source_label || row.analysis_source}
          </p>
        </div>
      ),
    },
    {
      key: 'model',
      header: 'Model',
      render: (row) => (
        <span className="text-xs text-ink-muted">
          {row.model_type} v{row.model_version}
        </span>
      ),
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={analyses}
      loading={loading}
      error={error}
      onRetry={onRetry}
      meta={meta}
      onPageChange={onPageChange}
      caption="Stored AI analyses for this hive"
      emptyTitle="No analyses stored yet"
      emptyDescription="An analysis is stored each time the engine runs for this hive — automatically, or when you ask for one."
      className={className}
    />
  );
}

export default AnalysisHistoryTable;
