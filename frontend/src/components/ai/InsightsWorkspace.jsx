import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Activity, BellRing, Hexagon, Search, Sparkles, TrendingUp } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { DataTable } from '@/components/common/DataTable';
import { PageHeader } from '@/components/common/PageHeader';
import { StatCard } from '@/components/common/StatCard';
import { AiModelNotice } from '@/components/ai/AiModelNotice';
import { HEALTH_STATUS_META, healthMeta, riskMeta, sourceMeta } from '@/constants/ai';
import { formatDateTime } from '@/utils/format';
import { normaliseError } from '@/utils/errors';
import { useToast } from '@/hooks/useToast';
import * as aiService from '@/services/aiService';

const PAGE_SIZE = 10;
const RISK_ORDER = ['LOW', 'MODERATE', 'HIGH', 'UNKNOWN'];

/**
 * The AI overview across every hive in scope.
 *
 * Two questions drive the layout: "how are my hives doing?" (the band counters)
 * and "which one should I look at?" (the table, ordered by hive code, with the
 * indicator and its quality side by side).
 *
 * Every cell is a stored value. A hive that has never been analysed says so —
 * it is not shown as healthy, and it is not hidden either.
 */
export function InsightsWorkspace({
  mode = 'owner',
  title = 'AI insights',
  description = 'Colony health indicators, risk bands and yield projections built from stored telemetry.',
  hivePathPrefix = '/beekeeper/hives',
}) {
  const toast = useToast();
  const isOwner = mode === 'owner';

  const [filters, setFilters] = useState({ search: '', onlyAnalysed: false });
  const [applied, setApplied] = useState({ search: '', onlyAnalysed: false });
  const [page, setPage] = useState(1);
  const [reloadKey, setReloadKey] = useState(0);

  const [rows, setRows] = useState([]);
  const [meta, setMeta] = useState(null);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { hives, meta: pageMeta } = await aiService.listHiveInsights({
        page,
        pageSize: PAGE_SIZE,
        search: applied.search || undefined,
        onlyWithAnalysis: applied.onlyAnalysed || undefined,
      });
      setRows(hives);
      setMeta(pageMeta);
    } catch (caught) {
      setError(normaliseError(caught));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [page, applied]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    aiService
      .getSummary()
      .then((payload) => {
        if (!cancelled) setSummary(payload);
      })
      .catch(() => {
        if (!cancelled) setSummary(null);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const refresh = () => setReloadKey((key) => key + 1);

  const runAll = async () => {
    setRunning(true);
    try {
      const result = await aiService.analyzeAll('manual run from the insights overview');
      toast.success(
        'Analysis complete',
        `${result.hives_analyzed} hive(s) analysed · ${result.alerts_created} alert(s) raised${
          result.hives_with_insufficient_data
            ? ` · ${result.hives_with_insufficient_data} still short of telemetry`
            : ''
        }.`,
      );
      load();
      refresh();
    } catch (caught) {
      const normalised = normaliseError(caught);
      toast.error('The bulk analysis did not finish', normalised.message);
    } finally {
      setRunning(false);
    }
  };

  const columns = [
    {
      key: 'hive_code',
      header: 'Hive',
      render: (row) => (
        <div>
          <Link to={`${hivePathPrefix}/${row.hive_id}`} className="font-medium text-forest-700 hover:underline">
            {row.hive_code}
          </Link>
          <p className="text-xs text-ink-muted">Status {row.status}</p>
        </div>
      ),
    },
    {
      key: 'health',
      header: 'Health indicator',
      render: (row) =>
        row.analyzed && typeof row.health_score === 'number' ? (
          <div className="flex items-center gap-2">
            <span className="font-semibold tabular-nums text-ink">{row.health_score}</span>
            <Badge variant={healthMeta(row.health_status).tone} size="sm">
              {row.health_status_label || healthMeta(row.health_status).label}
            </Badge>
          </div>
        ) : row.analyzed ? (
          <Badge variant="neutral" size="sm">
            {row.health_status_label || 'Not scored'}
          </Badge>
        ) : (
          <span className="text-ink-muted">Not analysed yet</span>
        ),
    },
    {
      key: 'risk',
      header: 'Risk indicators',
      render: (row) =>
        row.analyzed ? (
          <div className="flex flex-wrap gap-1.5">
            <Badge variant={riskMeta(row.disease_risk_level).tone} size="sm">
              Disease {riskMeta(row.disease_risk_level).label}
            </Badge>
            <Badge variant={riskMeta(row.swarming_risk_level).tone} size="sm">
              Swarming {riskMeta(row.swarming_risk_level).label}
            </Badge>
          </div>
        ) : (
          <span className="text-ink-muted">—</span>
        ),
    },
    {
      key: 'yield',
      header: 'Projection',
      align: 'right',
      render: (row) =>
        row.predicted_yield_kg !== null && row.predicted_yield_kg !== undefined ? (
          <span className="tabular-nums text-ink">
            {row.predicted_yield_kg.toFixed(2)} kg / {row.yield_period_days} d
          </span>
        ) : (
          <span className="text-ink-muted">Not projected</span>
        ),
    },
    {
      key: 'evidence',
      header: 'Evidence',
      render: (row) =>
        row.analyzed ? (
          <div className="text-xs text-ink-muted">
            <p>
              {row.data_quality_label} · {row.sample_count} reading(s)
            </p>
            <p>
              <Badge variant={sourceMeta(row.analysis_source).tone} size="sm">
                {row.analysis_source_label || sourceMeta(row.analysis_source).label}
              </Badge>
            </p>
          </div>
        ) : (
          <span className="text-ink-muted">
            {row.sample_count ? `${row.sample_count} reading(s)` : 'No telemetry yet'}
          </span>
        ),
    },
    {
      key: 'analyzed_at',
      header: 'Last run',
      render: (row) => (
        <div className="text-xs text-ink-muted">
          <p>{row.analyzed_at ? formatDateTime(row.analyzed_at) : 'Never'}</p>
          {row.is_stale && row.analyzed ? <p className="text-status-warning">Stored analysis is stale</p> : null}
        </div>
      ),
    },
    {
      key: 'alerts',
      header: 'Alerts',
      align: 'center',
      render: (row) =>
        row.open_alerts ? (
          <Badge variant="warning" size="sm">
            {row.open_alerts} open
          </Badge>
        ) : (
          <span className="text-xs text-ink-muted">None</span>
        ),
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title={title}
        description={description}
        actions={
          <>
            <Button variant="secondary" onClick={refresh} leftIcon={<Activity size={16} aria-hidden="true" />}>
              Refresh
            </Button>
            <Button
              onClick={runAll}
              loading={running}
              leftIcon={<Sparkles size={16} aria-hidden="true" />}
            >
              Analyse all hives
            </Button>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label={isOwner ? 'My hives' : 'Hives in scope'}
          value={summary?.total_hives ?? 0}
          helper={`${summary?.hives_with_telemetry ?? 0} with telemetry`}
          icon={<Hexagon size={16} aria-hidden="true" />}
          tone="honey"
          loading={!summary}
        />
        <StatCard
          label="Analysed"
          value={summary?.analysed_hives ?? 0}
          helper={`${summary?.hives_without_analysis ?? 0} without an analysis yet`}
          icon={<Sparkles size={16} aria-hidden="true" />}
          loading={!summary}
        />
        <StatCard
          label="Needing attention"
          value={summary?.open_alerts ?? 0}
          helper="Open or acknowledged alerts"
          icon={<BellRing size={16} aria-hidden="true" />}
          loading={!summary}
        />
        <StatCard
          label="Projected accumulation"
          value={`${(summary?.yield_projection?.total_predicted_kg ?? 0).toFixed(2)} kg`}
          helper={`Across ${summary?.yield_projection?.hives_with_projection ?? 0} hive(s) with a projection · average ${(summary?.yield_projection?.average_predicted_kg ?? 0).toFixed(2)} kg`}
          icon={<TrendingUp size={16} aria-hidden="true" />}
          tone="forest"
          loading={!summary}
        />
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <BandStrip
          title="Health bands"
          counts={summary?.health}
          keys={Object.keys(HEALTH_STATUS_META)}
          label={(key) => healthMeta(key).label}
          tone={(key) => healthMeta(key).tone}
        />
        <BandStrip
          title="Disease risk bands"
          counts={summary?.disease_risk}
          keys={RISK_ORDER}
          label={(key) => riskMeta(key).label}
          tone={(key) => riskMeta(key).tone}
        />
        <BandStrip
          title="Swarming risk bands"
          counts={summary?.swarming_risk}
          keys={RISK_ORDER}
          label={(key) => riskMeta(key).label}
          tone={(key) => riskMeta(key).tone}
        />
      </div>

      {summary ? (
        <Alert variant="info" title={`Model: ${summary.model.type} v${summary.model.version}`}>
          <p>{summary.model.note}</p>
          <p className="mt-1">
            Analyses use a {summary.analysis_window_hours}-hour telemetry window.{' '}
            {summary.auto_analysis_enabled
              ? 'Analyses are recomputed automatically when a stored one is stale or enough new readings have arrived.'
              : 'Automatic analysis is disabled on this deployment — runs happen only when requested.'}
          </p>
        </Alert>
      ) : null}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          setPage(1);
          setApplied(filters);
        }}
        className="flex flex-wrap items-end gap-3 rounded-card border border-sand-300 bg-white p-4 shadow-card"
      >
        <div className="min-w-[220px] flex-1">
          <Input
            label="Search"
            name="search"
            placeholder="Hive code or district"
            value={filters.search}
            onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))}
          />
        </div>
        <label className="flex items-center gap-2 pb-2 text-sm text-ink-soft">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-sand-400 text-forest-700 focus:ring-forest-500"
            checked={filters.onlyAnalysed}
            onChange={(event) => setFilters((prev) => ({ ...prev, onlyAnalysed: event.target.checked }))}
          />
          Only hives with an analysis
        </label>
        <Button type="submit" leftIcon={<Search size={15} aria-hidden="true" />}>
          Apply
        </Button>
      </form>

      <div className="rounded-card border border-sand-300 bg-white p-4 shadow-card">
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={(row) => row.hive_id}
          loading={loading}
          error={error}
          onRetry={load}
          meta={meta}
          onPageChange={setPage}
          caption="AI state per hive"
          emptyTitle="No hives to analyse"
          emptyDescription={
            isOwner
              ? 'Register a hive and pair a device with it. Once telemetry arrives, its assessment appears here.'
              : 'No hive in this scope has been registered yet.'
          }
        />
      </div>

      <AiModelNotice model={summary?.model} />
    </div>
  );
}

/** One row of band counters, rendered as chips so no colour stands alone. */
function BandStrip({ title, counts, keys, label, tone }) {
  return (
    <div className="rounded-card border border-sand-300 bg-white p-4 shadow-card">
      <p className="text-sm font-medium text-ink-soft">{title}</p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {keys.map((key) => (
          <Badge key={key} variant={tone(key)} size="sm">
            {label(key)}: {counts?.[key] ?? 0}
          </Badge>
        ))}
      </div>
    </div>
  );
}

export default InsightsWorkspace;
