import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Package, Plus, RefreshCw } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Modal } from '@/components/ui/Modal';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { DataTable } from '@/components/common/DataTable';
import { StatCard } from '@/components/common/StatCard';
import { ClusterBatchPicker, placementOf } from '@/components/clusters/ClusterBatchPicker';
import { unitLabel } from '@/constants/collection';
import { normaliseError } from '@/utils/errors';
import { formatDate, formatDateTime } from '@/utils/format';
import { useToast } from '@/hooks/useToast';
import * as batchService from '@/services/batchService';
import * as clusterService from '@/services/clusterService';

const PAGE_SIZE = 10;

/** Status pill colours, by the stage's own label. Shared with the other tables. */
const STAGE_VARIANT = {
  APPROVED: 'success',
  COMPLETED: 'success',
  DELIVERED: 'success',
  REJECTED: 'danger',
  HOLD: 'warning',
  INCONCLUSIVE: 'warning',
  IN_PROGRESS: 'info',
  DISPATCHED: 'info',
  IN_TRANSIT: 'info',
  NOT_STARTED: 'neutral',
};

function stageBadge(value, label) {
  return (
    <Badge variant={STAGE_VARIANT[value] || 'neutral'} size="sm">
      {label || value}
    </Badge>
  );
}

/**
 * The batches a cluster **holds** — the relationship the KVIC screens manage.
 *
 * `cluster → honey batches → collections → beekeepers → hives`. The rows are the
 * beekeepers' own batches, shown through the cluster endpoint; placing or
 * removing one writes the batch's own `cluster_id` and nothing else. The
 * counters above the table are counted by the server from those same rows, so the
 * headline and the list can never disagree.
 *
 * Removing a batch is offered because the relationship is editable; the batch
 * itself, its harvest, its beekeeper and its hives are never touched by it.
 */
export function ClusterBatchSection({
  clusterId,
  canManage = false,
  batchesPath = null,
  onChanged = null,
}) {
  const toast = useToast();
  const [rows, setRows] = useState([]);
  const [meta, setMeta] = useState(null);
  const [page, setPage] = useState(1);
  const [analytics, setAnalytics] = useState(null);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [analyticsError, setAnalyticsError] = useState(null);

  const [pickerOpen, setPickerOpen] = useState(false);
  const [picked, setPicked] = useState([]);
  const [confirmMove, setConfirmMove] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [detachTarget, setDetachTarget] = useState(null);

  const load = useCallback(
    async ({ silent = false } = {}) => {
      if (silent) setRefreshing(true);
      else setLoading(true);
      setError(null);
      setAnalyticsError(null);
      try {
        const [produced, counters] = await Promise.allSettled([
          batchService.getClusterBatches(clusterId, { page, pageSize: PAGE_SIZE }),
          clusterService.getClusterBatchAnalytics(clusterId),
        ]);

        if (produced.status === 'fulfilled') {
          setRows(produced.value.batches);
          setMeta(produced.value.meta);
        } else {
          // A failed read is reported as a failed read. It is not an empty
          // cluster, and it is never silently rendered as "no batches".
          setError(normaliseError(produced.reason));
          setRows([]);
          setMeta(null);
        }

        if (counters.status === 'fulfilled') {
          setAnalytics(counters.value);
        } else {
          setAnalytics(null);
          setAnalyticsError(normaliseError(counters.reason));
        }
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [clusterId, page],
  );

  useEffect(() => {
    load();
  }, [load]);

  const totals = analytics?.totals;
  const breakdown = analytics?.status_breakdown;

  const unit = totals?.unit ? unitLabel(totals.unit) : null;
  const quantity = (value) =>
    `${Number(value ?? 0).toLocaleString(undefined, { maximumFractionDigits: 3 })}${unit ? ` ${unit}` : ''}`;

  const onToggle = (batch) => {
    setPicked((previous) =>
      previous.includes(batch.id)
        ? previous.filter((id) => id !== batch.id)
        : [...previous, batch.id],
    );
  };

  const onSelectMany = (ids) => {
    setPicked((previous) => Array.from(new Set([...previous, ...ids])));
  };

  const openPicker = () => {
    setPicked([]);
    setSaveError(null);
    setPickerOpen(true);
  };

  const closePicker = () => {
    setPickerOpen(false);
    setPicked([]);
    setConfirmMove(false);
    setSaveError(null);
  };

  //: The selected batches that would have to be *moved* — they belong to another
  //: cluster right now. The server refuses them without `reassign: true`, which is
  //: only ever sent after the officer confirms here.
  const movingBatches = useMemo(
    () =>
      rows.filter(
        (row) => picked.includes(row.id) && placementOf(row, clusterId).needsConfirmation,
      ),
    [rows, picked, clusterId],
  );

  const save = async (reassign) => {
    setSaving(true);
    setSaveError(null);
    try {
      const result = await clusterService.assignBatches(clusterId, picked, { reassign });
      const added = result.assigned?.length ?? 0;
      const already = result.already?.length ?? 0;
      const moved = result.moved?.length ?? 0;
      toast.success(
        added
          ? `${added} batch${added === 1 ? '' : 'es'} added to ${result.cluster_code}`
          : `${result.cluster_code} unchanged`,
        [
          moved ? `${moved} moved from another cluster` : null,
          already ? `${already} already in this cluster` : null,
          `The cluster now holds ${result.batch_count} batch${result.batch_count === 1 ? '' : 'es'}.`,
        ]
          .filter(Boolean)
          .join(' · '),
      );
      closePicker();
      // Re-read both the table and the counters: the numbers update from the
      // server's answer rather than from anything this screen guessed.
      await load({ silent: true });
      onChanged?.(result);
    } catch (caught) {
      setSaveError(normaliseError(caught));
    } finally {
      setSaving(false);
    }
  };

  const detach = async () => {
    if (!detachTarget) return;
    setSaving(true);
    try {
      const result = await clusterService.detachBatch(clusterId, detachTarget.id);
      toast.success(
        `${result.detached} removed from ${result.cluster_code}`,
        `The cluster now holds ${result.batch_count} batch${result.batch_count === 1 ? '' : 'es'}. The batch itself is untouched.`,
      );
      setDetachTarget(null);
      await load({ silent: true });
      onChanged?.(result);
    } catch (caught) {
      toast.error('Could not remove the batch', normaliseError(caught).message);
    } finally {
      setSaving(false);
    }
  };

  const columns = [
    {
      key: 'batch_code',
      header: 'Batch ID',
      render: (row) =>
        batchesPath ? (
          <Link
            className="font-mono text-xs font-medium text-forest-700 underline-offset-2 hover:underline"
            to={`${batchesPath}/${row.id}`}
          >
            {row.batch_code}
          </Link>
        ) : (
          <span className="font-mono text-xs font-medium text-ink">{row.batch_code}</span>
        ),
    },
    {
      key: 'collection_code',
      header: 'Collection',
      render: (row) => (
        <div className="min-w-0">
          <p className="font-mono text-xs text-ink-soft">{row.collection_code}</p>
          <p className="text-xs text-ink-muted">{formatDate(row.collection_date)}</p>
        </div>
      ),
    },
    {
      key: 'beekeeper',
      header: 'Beekeeper',
      render: (row) => (
        <div className="min-w-0">
          <p className="truncate text-ink">{row.beekeeper_name || '—'}</p>
          <p className="font-mono text-xs text-ink-muted">{row.beekeeper_code || '—'}</p>
        </div>
      ),
    },
    {
      key: 'honey_type',
      header: 'Honey type',
      // No honey/floral variety exists on the harvest record, so the column states
      // that plainly rather than showing an invented value.
      render: () => <span className="text-xs text-ink-muted">Not recorded</span>,
    },
    {
      key: 'quantity',
      header: 'Quantity',
      align: 'right',
      render: (row) =>
        `${Number(row.quantity ?? 0).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${unitLabel(row.unit)}`,
    },
    {
      key: 'status',
      header: 'Supply-chain status',
      render: (row) => (
        <div className="min-w-0">
          {stageBadge(row.status, row.status_label)}
          <p className="mt-1 text-xs text-ink-muted">{row.current_stage_label}</p>
        </div>
      ),
    },
    {
      key: 'laboratory',
      header: 'Laboratory',
      render: (row) => stageBadge(row.laboratory_status, row.laboratory_status_label),
    },
    {
      key: 'packaging',
      header: 'Packaging',
      render: (row) => (
        <div className="min-w-0">
          {stageBadge(row.packaging_status, row.packaging_status_label)}
          <p className="mt-1 text-xs text-ink-muted">
            {row.package_count ? `${row.package_count} package(s)` : 'No packages yet'}
          </p>
        </div>
      ),
    },
    {
      key: 'distribution',
      header: 'Distribution',
      render: (row) => (
        <div className="min-w-0">
          {stageBadge(row.distribution_status, row.distribution_status_label)}
          {row.packaged_quantity ? (
            <p className="mt-1 text-xs text-ink-muted">
              {Number(row.packaged_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })}{' '}
              {unitLabel(row.unit)} packed
            </p>
          ) : null}
        </div>
      ),
    },
  ];

  return (
    <Card>
      <CardHeader
        icon={<Package size={18} aria-hidden="true" />}
        title="Batches in this Cluster"
        description="Real honey batches placed in this cluster. Each row is the batch's own record — batch → collection → beekeeper → hive — shown here, not copied."
        action={
          <div className="flex flex-wrap items-center gap-2">
            {canManage ? (
              <Button
                size="sm"
                onClick={openPicker}
                leftIcon={<Plus size={15} aria-hidden="true" />}
                data-testid="cluster-add-batches"
              >
                Add batches
              </Button>
            ) : null}
            <Button
              variant="ghost"
              size="sm"
              loading={refreshing}
              onClick={() => load({ silent: true })}
              leftIcon={<RefreshCw size={15} aria-hidden="true" />}
            >
              Refresh
            </Button>
          </div>
        }
      />
      <CardBody className="space-y-4">
        {error ? <Alert variant="danger" title="Unable to load this cluster's batches">{error.message}</Alert> : null}

        {totals ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Batches in cluster"
              value={totals.batches}
              helper={`${totals.collections} harvest record(s)`}
              tone="honey"
            />
            <StatCard
              label="Beekeepers represented"
              value={totals.beekeepers_represented}
              helper={`${totals.hives_behind_them} hive(s) behind them`}
            />
            <StatCard
              label="Quantity collected"
              value={quantity(totals.quantity_collected)}
              helper={`${quantity(totals.quantity_packaged)} packed as ${totals.packages} package(s)`}
            />
            <StatCard
              label="Delivered"
              value={breakdown?.delivered ?? 0}
              helper={`${breakdown?.distribution ?? 0} dispatched · ${breakdown?.laboratory ?? 0} laboratory-tested`}
            />
          </div>
        ) : analyticsError ? (
          <Alert variant="warning" title="Unable to load the cluster's production counters">
            {analyticsError.message}
          </Alert>
        ) : null}

        {breakdown ? (
          <div className="flex flex-wrap gap-2" aria-label="Batch stage breakdown">
            {[
              ['Collection', breakdown.collection],
              ['Processing', breakdown.processing],
              ['Laboratory', breakdown.laboratory],
              ['Packaging', breakdown.packaging],
              ['Distribution', breakdown.distribution],
              ['Delivered', breakdown.delivered],
            ].map(([label, value]) => (
              <Badge key={label} variant={value ? 'forest' : 'neutral'} size="sm">
                {label}: {value}
              </Badge>
            ))}
          </div>
        ) : null}

        <DataTable
          columns={columns}
          rows={rows}
          loading={loading}
          error={null}
          onRetry={() => load()}
          meta={meta}
          onPageChange={setPage}
          emptyTitle="No batches in this cluster yet"
          emptyDescription={
            canManage
              ? 'Use “Add batches” to place a real honey batch in this cluster. Batches are created by completing a harvest — they are selected here, never entered.'
              : 'Batches appear here once they are placed in this cluster.'
          }
          caption="Batches held by this cluster"
          skeletonRows={4}
        />

        {canManage && rows.length > 0 ? (
          <div className="space-y-2">
            <p className="text-xs uppercase tracking-wide text-ink-muted">Remove a batch from the cluster</p>
            <div className="flex flex-wrap gap-2">
              {rows.map((row) => (
                <Button
                  key={row.id}
                  size="sm"
                  variant="secondary"
                  onClick={() => setDetachTarget(row)}
                >
                  Remove {row.batch_code}
                </Button>
              ))}
            </div>
            <p className="text-xs text-ink-muted">
              Removing ends the cluster link only. The batch, its harvest, its beekeeper and its hives keep
              their own records.
            </p>
          </div>
        ) : null}

        {analytics?.generated_at ? (
          <p className="text-xs text-ink-muted">
            Counted at {formatDateTime(analytics.generated_at)} from the batches listed here.
          </p>
        ) : null}
      </CardBody>

      <Modal
        open={pickerOpen}
        onClose={closePicker}
        title="Add honey batches to this cluster"
        description="Select the real batches to place here. A batch already in another cluster must be confirmed before it is moved."
        size="xl"
        footer={
          <>
            <Button variant="secondary" onClick={closePicker} disabled={saving}>
              Cancel
            </Button>
            <Button
              onClick={() => (movingBatches.length ? setConfirmMove(true) : save(false))}
              loading={saving}
              disabled={picked.length === 0}
              data-testid="confirm-add-batches"
            >
              {picked.length ? `Add ${picked.length} batch${picked.length === 1 ? '' : 'es'}` : 'Add batches'}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {saveError ? (
            <Alert variant="danger" title="The batches were not placed">
              {saveError.message}
            </Alert>
          ) : null}
          <ClusterBatchPicker
            clusterId={clusterId}
            selectedIds={picked}
            onToggle={onToggle}
            onSelectMany={onSelectMany}
          />
        </div>
      </Modal>

      <ConfirmDialog
        open={confirmMove}
        title="Move batches from another cluster?"
        description={`${movingBatches
          .map((row) => `${row.batch_code} (${row.cluster_code || 'another cluster'})`)
          .join(', ')} currently belong to another cluster. Moving them rewrites the cluster recorded on those batches — the honey, its harvest and its beekeeper stay the same.`}
        confirmLabel="Move and add"
        loading={saving}
        onConfirm={() => {
          setConfirmMove(false);
          save(true);
        }}
        onCancel={() => setConfirmMove(false)}
      />

      <ConfirmDialog
        open={Boolean(detachTarget)}
        title={`Remove ${detachTarget?.batch_code || 'this batch'} from the cluster?`}
        description="This clears the cluster link on the batch (and on its harvest). The batch itself, its records and its traceability timeline are not deleted, and it can be placed again later."
        confirmLabel="Remove from cluster"
        variant="danger"
        loading={saving}
        onConfirm={detach}
        onCancel={() => setDetachTarget(null)}
      />
    </Card>
  );
}

export default ClusterBatchSection;
