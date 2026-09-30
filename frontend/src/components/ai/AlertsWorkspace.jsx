import { useCallback, useEffect, useMemo, useState } from 'react';
import { BellRing, Filter, RotateCw, ShieldCheck } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Select';
import { EmptyState } from '@/components/common/EmptyState';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import { PageHeader } from '@/components/common/PageHeader';
import { PaginationBar } from '@/components/common/PaginationBar';
import { StatCard } from '@/components/common/StatCard';
import { AlertActionDialog } from '@/components/ai/AlertActionDialog';
import { AlertCard } from '@/components/ai/AlertCard';
import { ALERT_TYPE_LABELS } from '@/constants/ai';
import { normaliseError } from '@/utils/errors';
import { useToast } from '@/hooks/useToast';
import * as aiService from '@/services/aiService';

const PAGE_SIZE = 10;

const STATUS_OPTIONS = [
  { value: '', label: 'Open and acknowledged' },
  { value: 'OPEN', label: 'Open only' },
  { value: 'ACKNOWLEDGED', label: 'Acknowledged only' },
  { value: 'RESOLVED', label: 'Resolved only' },
];

const SEVERITY_OPTIONS = [
  { value: '', label: 'Any severity' },
  { value: 'CRITICAL', label: 'Critical' },
  { value: 'WARNING', label: 'Warning' },
  { value: 'INFO', label: 'Information' },
];

const TYPE_OPTIONS = [
  { value: '', label: 'Any type' },
  ...Object.entries(ALERT_TYPE_LABELS).map(([value, label]) => ({ value, label })),
];

/**
 * The alerts workspace, shared by the owner and staff views.
 *
 * Everything on this screen comes from `ai_alerts` rows the engine raised. The
 * counts are counters, the list is the records themselves, and the note at the
 * top states the delivery channel honestly: alerts live *in the app* — this
 * phase sends no SMS, email or push.
 *
 * Actions are offered by status, and each one goes back through the API, so the
 * acknowledgement a beekeeper sees is the audit entry the platform recorded.
 */
export function AlertsWorkspace({
  mode = 'owner',
  title = 'Alerts',
  description = 'Recorded findings that deserve a look, and what was done about them.',
  hivePathPrefix = '/beekeeper/hives',
  defaultStatus = '',
}) {
  const toast = useToast();
  const isOwner = mode === 'owner';

  const [filters, setFilters] = useState({ status: defaultStatus, severity: '', alertType: '' });
  const [applied, setApplied] = useState(filters);
  const [page, setPage] = useState(1);
  const [reloadKey, setReloadKey] = useState(0);

  const [alerts, setAlerts] = useState([]);
  const [meta, setMeta] = useState(null);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [dialog, setDialog] = useState({ open: false, alert: null, action: 'acknowledge' });
  const [busy, setBusy] = useState(false);

  // Resolved rows are hidden unless the filter asks for them: the API defaults
  // `include_resolved` to false so the default view is "what still needs you".
  const includeResolved = useMemo(() => applied.status === 'RESOLVED', [applied.status]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { alerts: rows, meta: pageMeta } = await aiService.listAlerts({
        page,
        pageSize: PAGE_SIZE,
        status: applied.status || undefined,
        severity: applied.severity || undefined,
        alertType: applied.alertType || undefined,
        includeResolved,
      });
      setAlerts(rows);
      setMeta(pageMeta);
    } catch (caught) {
      setError(normaliseError(caught));
      setAlerts([]);
    } finally {
      setLoading(false);
    }
  }, [page, applied, includeResolved]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    aiService
      .getAlertSummary()
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

  const reload = () => setReloadKey((key) => key + 1);

  const applyFilters = (event) => {
    event?.preventDefault?.();
    setPage(1);
    setApplied(filters);
    reload();
  };

  const resetFilters = () => {
    const cleared = { status: '', severity: '', alertType: '' };
    setFilters(cleared);
    setApplied(cleared);
    setPage(1);
    reload();
  };

  const runAction = async (note) => {
    const { alert, action } = dialog;
    if (!alert) return;
    setBusy(true);
    try {
      if (action === 'acknowledge') await aiService.acknowledgeAlert(alert.id, note);
      else if (action === 'resolve') await aiService.resolveAlert(alert.id, note);
      else await aiService.reopenAlert(alert.id);

      const done = {
        acknowledge: ['Alert acknowledged', 'It stays visible until the pattern clears or you resolve it.'],
        resolve: ['Alert resolved', 'A new alert is raised if the same pattern is recorded again after the cooldown.'],
        reopen: ['Alert reopened', 'It is back on the open list.'],
      }[action];
      toast.success(done[0], done[1]);
      setDialog({ open: false, alert: null, action: 'acknowledge' });
      load();
      reload();
    } catch (caught) {
      const normalised = normaliseError(caught);
      toast.error('That action did not go through', normalised.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title={title}
        description={description}
        actions={
          <Button
            variant="secondary"
            onClick={reload}
            leftIcon={<RotateCw size={16} aria-hidden="true" />}
          >
            Refresh
          </Button>
        }
      />

      <Alert variant="info" title="Alerts are recorded in the app">
        {summary?.note ||
          'HoneyChain does not send notifications (SMS, email or push) in this phase. Every alert below is a stored record with its own timeline.'}
      </Alert>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Needing attention"
          value={summary?.open_total ?? 0}
          helper="Open or acknowledged"
          icon={<BellRing size={16} aria-hidden="true" />}
          tone="honey"
          loading={!summary}
        />
        <StatCard
          label="Acknowledged"
          value={summary?.acknowledged ?? 0}
          helper="Seen, not yet resolved"
          loading={!summary}
        />
        <StatCard
          label="Resolved"
          value={summary?.resolved ?? 0}
          helper="Closed by a person"
          icon={<ShieldCheck size={16} aria-hidden="true" />}
          loading={!summary}
        />
        <StatCard
          label="Critical severity"
          value={summary?.by_severity?.CRITICAL ?? 0}
          helper={`${summary?.by_severity?.WARNING ?? 0} warning · ${summary?.by_severity?.INFO ?? 0} info`}
          loading={!summary}
          tone="forest"
        />
      </div>

      <form
        onSubmit={applyFilters}
        className="grid items-end gap-3 rounded-card border border-sand-300 bg-white p-4 shadow-card sm:grid-cols-2 lg:grid-cols-4"
      >
        <Select
          label="Status"
          name="status"
          options={STATUS_OPTIONS}
          value={filters.status}
          onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}
        />
        <Select
          label="Severity"
          name="severity"
          options={SEVERITY_OPTIONS}
          value={filters.severity}
          onChange={(event) => setFilters((prev) => ({ ...prev, severity: event.target.value }))}
        />
        <Select
          label="Type"
          name="alertType"
          options={TYPE_OPTIONS}
          value={filters.alertType}
          onChange={(event) => setFilters((prev) => ({ ...prev, alertType: event.target.value }))}
        />
        <div className="flex items-end gap-2">
          <Button type="submit" leftIcon={<Filter size={15} aria-hidden="true" />}>
            Apply filters
          </Button>
          <Button type="button" variant="ghost" onClick={resetFilters}>
            Reset
          </Button>
        </div>
      </form>

      {loading ? (
        <LoadingState label="Loading alerts…" />
      ) : error ? (
        <ErrorState error={error} onRetry={load} />
      ) : alerts.length === 0 ? (
        <EmptyState
          icon={<BellRing size={22} aria-hidden="true" />}
          title="No alerts match these filters"
          description={
            isOwner
              ? 'Alerts are raised from stored telemetry when a pattern leaves its reference band, when telemetry stops arriving, or when the health indicator falls into a risk band. Nothing matches right now.'
              : 'No hive in this scope has an alert matching these filters right now.'
          }
        />
      ) : (
        <div className="space-y-3">
          {alerts.map((alert) => (
            <AlertCard
              key={alert.id}
              alert={alert}
              busy={busy}
              hiveHref={`${hivePathPrefix}/${alert.hive_id}`}
              onAction={(target, action) => setDialog({ open: true, alert: target, action })}
            />
          ))}
          <PaginationBar meta={meta} onPageChange={setPage} />
        </div>
      )}

      <AlertActionDialog
        open={dialog.open}
        alert={dialog.alert}
        action={dialog.action}
        busy={busy}
        onClose={() => setDialog({ open: false, alert: null, action: 'acknowledge' })}
        onConfirm={runAction}
      />
    </div>
  );
}

export default AlertsWorkspace;
