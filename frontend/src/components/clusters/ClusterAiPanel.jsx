import { Brain } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { DataTable } from '@/components/common/DataTable';
import { formatDateTime } from '@/utils/format';

const HEALTH_VARIANT = {
  HEALTHY: 'success',
  ATTENTION: 'warning',
  AT_RISK: 'danger',
  CRITICAL: 'danger',
  INSUFFICIENT_DATA: 'neutral',
};

const RISK_VARIANT = { LOW: 'success', MODERATE: 'warning', HIGH: 'danger', UNKNOWN: 'neutral' };

/** "1 healthy · 2 attention" — only the levels that actually occur. */
function summarise(counts = {}) {
  const parts = Object.entries(counts)
    .filter(([, value]) => value > 0)
    .map(([key, value]) => `${value} ${key.toLowerCase().replaceAll('_', ' ')}`);
  return parts.length ? parts.join(' · ') : 'none';
}

/**
 * The latest stored assessment for each hive in the cluster.
 *
 * Read-through only: the officer sees the same analysis rows the beekeeper sees,
 * labelled with the source that produced them (a simulator reading is shown as
 * SIMULATOR). The panel never runs an analysis of its own — that stays with the
 * hive's owner or an explicit staff action — and an unassessed hive is listed as
 * "not analysed yet" instead of being left out of the count.
 */
export function ClusterAiPanel({ aiState, loading = false }) {
  const summary = aiState?.summary;
  const rows = aiState?.hives || [];

  const columns = [
    {
      key: 'hive_code',
      header: 'Hive',
      render: (row) => <span className="font-medium text-ink">{row.hive_code}</span>,
    },
    {
      key: 'analyzed',
      header: 'Assessment',
      render: (row) =>
        row.analyzed ? (
          <div className="space-y-1">
            <Badge variant={HEALTH_VARIANT[row.health_status] || 'neutral'} size="sm">
              {row.health_status
                ? row.health_status.replaceAll('_', ' ').toLowerCase()
                : 'assessed'}
            </Badge>
            <p className="text-xs text-ink-muted">
              {row.health_score === null
                ? 'No score — not enough stored readings'
                : `Indicator ${row.health_score}/100`}
            </p>
          </div>
        ) : (
          <span className="text-sm text-ink-muted">Not analysed yet</span>
        ),
    },
    {
      key: 'disease_risk_level',
      header: 'Disease risk',
      render: (row) =>
        row.analyzed ? (
          <Badge variant={RISK_VARIANT[row.disease_risk_level] || 'neutral'} size="sm">
            {(row.disease_risk_level || 'UNKNOWN').toLowerCase()}
          </Badge>
        ) : (
          '—'
        ),
    },
    {
      key: 'swarming_risk_level',
      header: 'Swarming risk',
      render: (row) =>
        row.analyzed ? (
          <Badge variant={RISK_VARIANT[row.swarming_risk_level] || 'neutral'} size="sm">
            {(row.swarming_risk_level || 'UNKNOWN').toLowerCase()}
          </Badge>
        ) : (
          '—'
        ),
    },
    {
      key: 'predicted_yield_kg',
      header: 'Projection',
      render: (row) =>
        row.predicted_yield_kg === null || row.predicted_yield_kg === undefined
          ? '—'
          : `${row.predicted_yield_kg} kg / ${row.yield_period_days || 30} days`,
    },
    {
      key: 'analysis_source',
      header: 'Source',
      render: (row) => (
        <div className="space-y-0.5">
          <p className="text-sm text-ink-soft">
            {(row.analysis_source || 'NO_DATA').replaceAll('_', ' ').toLowerCase()}
          </p>
          <p className="text-xs text-ink-muted">
            {row.sample_count} reading(s)
            {row.analyzed_at ? ` · ${formatDateTime(row.analyzed_at)}` : ''}
          </p>
        </div>
      ),
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Hive health insights in this cluster"
        description="The stored assessments for these hives, with the data source that produced them."
        action={<Brain size={16} className="text-ink-muted" aria-hidden="true" />}
      />
      <CardBody className="space-y-4">
        {loading && !summary ? (
          <p className="text-sm text-ink-muted">Reading the stored assessments…</p>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-lg border border-sand-200 bg-white p-3">
                <p className="text-xs uppercase tracking-wide text-ink-muted">Assessed</p>
                <p className="mt-1 text-lg font-semibold text-ink">
                  {summary?.analysed_hives ?? 0}
                  <span className="text-sm font-normal text-ink-muted">
                    {' '}
                    of {summary?.total_hives ?? 0} hives
                  </span>
                </p>
              </div>
              <div className="rounded-lg border border-sand-200 bg-white p-3">
                <p className="text-xs uppercase tracking-wide text-ink-muted">Health indicators</p>
                <p className="mt-1 text-sm text-ink-soft">{summarise(summary?.health)}</p>
              </div>
              <div className="rounded-lg border border-sand-200 bg-white p-3">
                <p className="text-xs uppercase tracking-wide text-ink-muted">Open alerts</p>
                <p className="mt-1 text-lg font-semibold text-ink">{summary?.open_alerts ?? 0}</p>
              </div>
            </div>

            <DataTable
              columns={columns}
              rows={rows}
              emptyTitle="No hives to assess in this cluster yet"
              emptyDescription="Assessments appear here once these beekeepers register hives and store readings for them."
              caption="Stored hive assessments inside the cluster"
            />

            <p className="text-xs text-ink-muted">
              {summary?.model?.note ||
                'Indicators describe recorded sensor patterns against reference bands. They are monitoring aids, not diagnoses.'}
            </p>
          </>
        )}
      </CardBody>
    </Card>
  );
}

export default ClusterAiPanel;
