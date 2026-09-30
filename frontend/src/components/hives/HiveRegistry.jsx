import { useCallback, useEffect, useMemo, useState } from 'react';
import { Hexagon, Pencil, Plus, Radio, RotateCcw, Search, Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { DataTable } from '@/components/common/DataTable';
import { PageHeader } from '@/components/common/PageHeader';
import { StatCard } from '@/components/common/StatCard';
import { StatusBadge } from '@/components/common/StatusBadge';
import { HiveFormModal } from '@/components/hives/HiveFormModal';
import { HIVE_STATUSES, sensorMeta, formatSensorValue } from '@/constants/hive';
import { normaliseError } from '@/utils/errors';
import { formatDateTime, titleCase } from '@/utils/format';
import { useToast } from '@/hooks/useToast';
import * as hiveService from '@/services/hiveService';

const PAGE_SIZE = 10;

/**
 * Whether the beekeeper has actually assessed the colony.
 *
 * Colony strength and queen status both default to UNKNOWN, and rendering
 * "Unknown / Unknown" reads like a broken value rather than "not assessed yet".
 */
function colonyAssessed(row) {
  return Boolean(
    (row.colony_strength && row.colony_strength !== 'UNKNOWN') ||
      (row.queen_status && row.queen_status !== 'UNKNOWN'),
  );
}

/**
 * Hive registry.
 *
 * One component serves three audiences, because the screens differ only in what
 * the API allows the caller to see and do — not in what a hive looks like:
 *
 *  - `owner`       — a beekeeper's own apiary, with create/edit/status/delete;
 *  - `oversight`   - a KVIC officer's or administrator's read-only view.
 *
 * The backend enforces the scope regardless of which variant is rendered, so
 * hiding a button is a convenience, never the authorisation.
 */
export function HiveRegistry({
  mode = 'owner',
  title = 'My hives',
  description,
  detailBasePath,
  emptyTitle = 'No hives yet',
  emptyDescription = 'Register your first hive and the platform will generate its code.',
  actions = null,
}) {
  const toast = useToast();
  const navigate = useNavigate();
  const canEdit = mode === 'owner';
  // Cluster placement is an organisational decision, so only the oversight view
  // offers the filter. Nothing here authorises anything: the API scopes the list.
  const canClusterFilter = mode !== 'owner';

  const [filters, setFilters] = useState({ search: '', district: '', status: '', hasCluster: '' });
  const [applied, setApplied] = useState({ search: '', district: '', status: '', hasCluster: '' });
  const [page, setPage] = useState(1);

  const [hives, setHives] = useState([]);
  const [meta, setMeta] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [options, setOptions] = useState({ districts: [], bee_species: [], statuses: [] });
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [removing, setRemoving] = useState(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [removeConflict, setRemoveConflict] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { hives: rows, meta: pageMeta } = await hiveService.listHives({
        page,
        pageSize: PAGE_SIZE,
        search: applied.search || undefined,
        district: applied.district || undefined,
        status: applied.status || undefined,
        // Oversight only: "not in a cluster" is the officers' worklist of hives
        // whose owner belongs to no cluster. The API ignores it for a beekeeper.
        hasCluster: canClusterFilter && applied.hasCluster !== '' ? applied.hasCluster === 'in' : undefined,
      });
      setHives(rows);
      setMeta(pageMeta);
    } catch (caught) {
      setError(normaliseError(caught));
      setHives([]);
    } finally {
      setLoading(false);
    }
    // `refreshKey` is a deliberate trigger: it re-runs this after a write.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, applied, refreshKey]);

  useEffect(() => {
    load();
  }, [load]);

  // Counters and filter values are drawn fresh whenever the list changes, so a
  // newly registered district appears in the dropdown without a page reload.
  useEffect(() => {
    let cancelled = false;
    Promise.all([hiveService.getHiveFilterOptions(), hiveService.getHiveSummary()])
      .then(([filterOptions, counters]) => {
        if (cancelled) return;
        setOptions(filterOptions);
        setSummary(counters);
      })
      .catch(() => {
        /* Filters and counters are decoration; the list itself is what matters. */
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  const districtOptions = useMemo(
    () => [
      { value: '', label: 'All districts' },
      ...(options.districts || []).map((district) => ({ value: district, label: district })),
    ],
    [options.districts],
  );

  const statusOptions = useMemo(
    () => [
      { value: '', label: 'All statuses' },
      ...HIVE_STATUSES.map((status) => ({ value: status.value, label: status.label })),
    ],
    [],
  );

  const applyFilters = (event) => {
    event?.preventDefault?.();
    setPage(1);
    setApplied(filters);
  };

  const clusterOptions = [
    { value: '', label: 'Any cluster state' },
    { value: 'in', label: 'In a cluster' },
    { value: 'out', label: 'Not in a cluster (worklist)' },
  ];

  const resetFilters = () => {
    const blank = { search: '', district: '', status: '', hasCluster: '' };
    setFilters(blank);
    setApplied(blank);
    setPage(1);
  };

  /**
   * Remove a hive.
   *
   * The API refuses (409) while devices or readings are attached and reports
   * what it found. Rather than hiding that, the dialog shows the counts and asks
   * the second time: retire the hive and keep the history.
   */
  const confirmRemove = async (force = false) => {
    if (!removing) return;
    setRemoveBusy(true);
    try {
      const result = await hiveService.deleteHive(removing.id, { force });
      toast.success(
        result.deleted === false
          ? `${removing.hive_code} marked REMOVED — history kept`
          : `${removing.hive_code} deleted`,
      );
      setRemoving(null);
      setRemoveConflict(null);
      setRefreshKey((key) => key + 1);
    } catch (caught) {
      const normalised = normaliseError(caught);
      const details = caught?.response?.data?.error?.details;
      if (normalised.status === 409 && details) {
        setRemoveConflict(details);
      } else {
        toast.error('Could not remove the hive', normalised.message);
        setRemoving(null);
      }
    } finally {
      setRemoveBusy(false);
    }
  };

  const columns = useMemo(() => {
    const base = [
      {
        key: 'hive_code',
        header: 'Hive',
        render: (row) => (
          <div className="min-w-0">
            <p className="font-medium text-ink">{row.hive_code}</p>
            <p className="truncate text-xs text-ink-muted">{row.location_label || 'No location recorded'}</p>
          </div>
        ),
      },
      {
        key: 'status',
        header: 'Status',
        render: (row) => <StatusBadge status={row.status} />,
      },
      {
        key: 'colony',
        header: 'Colony',
        render: (row) => (
          <div className="text-xs">
            {colonyAssessed(row) ? (
              <>
                <p className="text-ink">
                  {`Colony: ${row.colony_strength_label || titleCase(row.colony_strength)}`}
                </p>
                <p className="text-ink-muted">
                  {`Queen: ${row.queen_status_label || titleCase(row.queen_status)}`}
                </p>
              </>
            ) : (
              /* Both fields default to UNKNOWN, and printing "Unknown / Unknown"
                 reads like a broken value rather than "not assessed yet". */
              <span className="text-ink-muted">Not assessed yet</span>
            )}
          </div>
        ),
      },
      {
        key: 'device',
        header: 'Device',
        render: (row) =>
          row.primary_device ? (
            <div className="text-xs">
              <p className="font-medium text-ink">{row.primary_device.device_id}</p>
              <p className="text-ink-muted">
                <StatusBadge status={row.primary_device.status} size="sm" />{' '}
                {row.primary_device.status_label || ''}
              </p>
            </div>
          ) : (
            <span className="text-xs text-ink-muted">No device paired</span>
          ),
      },
      {
        key: 'latest',
        header: 'Latest reading',
        render: (row) => {
          const reading = row.latest_reading;
          if (!reading) return <span className="text-xs text-ink-muted">No telemetry yet</span>;
          const temperature = sensorMeta('TEMPERATURE');
          const humidity = sensorMeta('HUMIDITY');
          return (
            <div className="text-xs">
              <p className="text-ink">
                {formatSensorValue(temperature.value, reading.temperature)} ·{' '}
                {formatSensorValue(humidity.value, reading.humidity)}
              </p>
              <p className="text-ink-muted">
                {formatDateTime(reading.timestamp)} · {reading.source_label}
              </p>
            </div>
          );
        },
      },
    ];

    if (canEdit) {
      base.push({
        key: 'actions',
        header: '',
        align: 'right',
        render: (row) => (
          <div className="flex justify-end gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={(event) => {
                event.stopPropagation();
                setEditing(row);
                setFormOpen(true);
              }}
              aria-label={`Edit ${row.hive_code}`}
            >
              <Pencil size={15} aria-hidden="true" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={(event) => {
                event.stopPropagation();
                setRemoving(row);
              }}
              aria-label={`Remove ${row.hive_code}`}
            >
              <Trash2 size={15} aria-hidden="true" />
            </Button>
          </div>
        ),
      });
    }

    return base;
  }, [canEdit]);

  // Rows open the hive's own screen when the variant supplies a base path; the
  // oversight variants read their detail inline instead.
  const openRow = detailBasePath ? (row) => navigate(`${detailBasePath}/${row.id}`) : undefined;

  return (
    <div className="space-y-5">
      <PageHeader
        title={title}
        description={description}
        actions={
          <>
            {actions}
            {canEdit ? (
              <Button
                leftIcon={<Plus size={16} aria-hidden="true" />}
                onClick={() => {
                  setEditing(null);
                  setFormOpen(true);
                }}
              >
                Register hive
              </Button>
            ) : null}
          </>
        }
      />

      {summary ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Hives"
            value={summary.total}
            helper={canEdit ? 'In your registry' : 'Across the beekeepers you oversee'}
            icon={<Hexagon size={16} aria-hidden="true" />}
            tone="honey"
          />
          <StatCard
            label="Active"
            value={summary.by_status?.ACTIVE ?? 0}
            helper={`${summary.by_status?.MAINTENANCE ?? 0} under maintenance`}
          />
          <StatCard
            label="Paired with a device"
            value={summary.with_device}
            helper="Sending telemetry"
            icon={<Radio size={16} aria-hidden="true" />}
          />
          <StatCard
            label="Waiting for a device"
            value={summary.without_device}
            helper="No sensor data expected yet"
          />
        </div>
      ) : null}

      <form onSubmit={applyFilters} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Input
          name="hive-search"
          placeholder="Search hive code or village"
          leftIcon={<Search size={16} aria-hidden="true" />}
          value={filters.search}
          onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value }))}
        />
        <Select
          name="hive-district"
          options={districtOptions}
          value={filters.district}
          onChange={(event) => setFilters((current) => ({ ...current, district: event.target.value }))}
        />
        <Select
          name="hive-status"
          options={statusOptions}
          value={filters.status}
          onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value }))}
        />
        {canClusterFilter ? (
          <Select
            name="hive-cluster"
            options={clusterOptions}
            value={filters.hasCluster}
            onChange={(event) => setFilters((current) => ({ ...current, hasCluster: event.target.value }))}
          />
        ) : null}
        <div className="flex gap-2">
          <Button type="submit" variant="secondary" fullWidth>
            Apply
          </Button>
          <Button
            variant="ghost"
            onClick={resetFilters}
            aria-label="Reset filters"
            leftIcon={<RotateCcw size={16} aria-hidden="true" />}
          >
            Reset
          </Button>
        </div>
      </form>

      {canClusterFilter && applied.hasCluster === 'out' ? (
        <Alert variant="info" title="Hives with no cluster">
          These beekeepers belong to no cluster, so their hives are outside every cluster view. Open a
          hive to place it, or assign the beekeeper to a cluster — which moves all of their hives at
          once.
        </Alert>
      ) : null}

      <DataTable
        columns={columns}
        rows={hives}
        loading={loading}
        error={error}
        onRetry={load}
        meta={meta}
        onPageChange={setPage}
        onRowClick={openRow}
        emptyTitle={emptyTitle}
        emptyDescription={emptyDescription}
        caption="Registered hives"
      />

      {canEdit ? (
        <HiveFormModal
          open={formOpen}
          hive={editing}
          onClose={() => setFormOpen(false)}
          onSaved={() => setRefreshKey((key) => key + 1)}
        />
      ) : null}

      <ConfirmDialog
        open={Boolean(removing) && !removeConflict}
        title={`Remove ${removing?.hive_code || 'this hive'}?`}
        description="A hive with no devices and no readings is deleted. Anything with history is retired instead, so records are never lost."
        confirmLabel="Remove hive"
        variant="danger"
        loading={removeBusy}
        onCancel={() => setRemoving(null)}
        onConfirm={() => confirmRemove(false)}
      />

      {removeConflict ? (
        <ConfirmDialog
          open
          title={`${removing?.hive_code} still has data attached`}
          description={`The platform found ${removeConflict.device_count ?? 0} device(s) and ${removeConflict.reading_count ?? 0} stored reading(s). Retiring the hive keeps them; the hive is marked REMOVED and stays readable.`}
          confirmLabel="Retire the hive"
          variant="danger"
          loading={removeBusy}
          onCancel={() => {
            setRemoveConflict(null);
            setRemoving(null);
          }}
          onConfirm={() => confirmRemove(true)}
        />
      ) : null}
    </div>
  );
}

export default HiveRegistry;
