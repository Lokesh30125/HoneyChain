import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Building2, RefreshCw } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { StatCard } from '@/components/common/StatCard';
import { DataTable } from '@/components/common/DataTable';
import { WorkspaceHeader } from '@/components/common/WorkspaceHeader';
import { unitLabel } from '@/constants/collection';
import { normaliseError } from '@/utils/errors';
import { formatDateTime } from '@/utils/format';
import * as clusterAnalytics from '@/services/clusterAnalyticsService';
import * as clusterService from '@/services/clusterService';

/**
 * Cluster analytics — the production figures of the clusters the officer oversees.
 *
 * Every number on this page is counted from stored rows by the API:
 *
 * * batches, harvests, beekeepers represented and hives behind them come from
 *   `GET /clusters/{id}/batch-analytics`, which counts the cluster's own batch
 *   rows (the same rows its batch table lists);
 * * quantity collected and packaged are summed from those batches' quantities;
 * * the laboratory, packaging and distribution counters are read from each
 *   batch's own stage records — the lab tests, packaging runs/packages and
 *   shipments the other roles own;
 * * members and hives come from the cluster summary and registry.
 *
 * Nothing is estimated, nothing is a stored total that could go stale, and a
 * cluster with no records reports zeros rather than a blank. A per-cluster read
 * that fails is *named*: its figures are unavailable, which is not the same thing
 * as zero, and it is never quietly rendered as "nothing recorded".
 */
export default function KvicClusterAnalyticsPage() {
  const [rows, setRows] = useState([]);
  const [totals, setTotals] = useState(null);
  const [failures, setFailures] = useState([]);
  const [generatedAt, setGeneratedAt] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setFailures([]);
    try {
      const { clusters, meta } = await clusterService.listClusters({ pageSize: 100 });

      const analysed = await Promise.all(
        clusters.map(async (cluster) => {
          const [analytics, registry, summary] = await Promise.allSettled([
            clusterService.getClusterBatchAnalytics(cluster.id),
            clusterService.getCluster(cluster.id),
            clusterAnalytics.getClusterOverview(cluster.id),
          ]);

          const problems = [];
          if (analytics.status === 'rejected') {
            problems.push(`production figures: ${normaliseError(analytics.reason).message}`);
          }
          if (registry.status === 'rejected') {
            problems.push(`members: ${normaliseError(registry.reason).message}`);
          }
          if (summary.status === 'rejected') {
            problems.push(`hives: ${normaliseError(summary.reason).message}`);
          }

          const figures = analytics.status === 'fulfilled' ? analytics.value : null;
          const detail = registry.status === 'fulfilled' ? registry.value : null;
          const overview = summary.status === 'fulfilled' ? summary.value : null;

          return {
            id: cluster.id,
            code: cluster.cluster_code,
            name: cluster.cluster_name,
            district: cluster.district || '—',
            is_active: cluster.is_active,
            beekeepers: detail?.member_count ?? overview?.beekeepers?.total ?? null,
            hives: overview?.hives?.total ?? null,
            batches: figures?.totals?.batches ?? null,
            collections: figures?.totals?.collections ?? null,
            represented: figures?.totals?.beekeepers_represented ?? null,
            quantity_collected: figures?.totals?.quantity_collected ?? null,
            quantity_packaged: figures?.totals?.quantity_packaged ?? null,
            packages: figures?.totals?.packages ?? null,
            unit: figures?.totals?.unit ?? null,
            mixed_units: figures?.totals?.mixed_units ?? false,
            breakdown: figures?.status_breakdown ?? null,
            laboratory: figures?.laboratory ?? null,
            generated_at: figures?.generated_at ?? null,
            problems,
          };
        }),
      );

      const broken = analysed.filter((row) => row.problems.length);
      // Only the clusters that answered are summed: a total that includes an
      // unreadable cluster would be wrong, and it would look complete.
      const counted = analysed.filter((row) => row.batches !== null);
      const sum = (pick) => counted.reduce((accumulator, row) => accumulator + (pick(row) || 0), 0);
      const units = new Set(counted.map((row) => row.unit).filter(Boolean));

      setRows(analysed);
      setFailures(broken);
      setGeneratedAt(
        analysed.reduce((latest, row) => (row.generated_at && row.generated_at > latest ? row.generated_at : latest), '') || null,
      );
      setTotals({
        clusters: meta?.total_items ?? clusters.length,
        countedClusters: counted.length,
        batches: sum((row) => row.batches),
        collections: sum((row) => row.collections),
        quantity_collected: sum((row) => Number(row.quantity_collected || 0)),
        quantity_packaged: sum((row) => Number(row.quantity_packaged || 0)),
        packages: sum((row) => row.packages),
        approved: sum((row) => row.laboratory?.approved),
        rejected: sum((row) => row.laboratory?.rejected),
        hold: sum((row) => row.laboratory?.hold),
        delivered: sum((row) => row.breakdown?.delivered),
        unit: units.size === 1 ? unitLabel([...units][0]) : null,
      });
    } catch (caught) {
      // The registry itself failed: this is an error, not an empty register.
      setError(normaliseError(caught));
      setRows([]);
      setTotals(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const formatQuantity = useCallback(
    (value) =>
      value === null || value === undefined
        ? '—'
        : `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 })}${totals?.unit ? ` ${totals.unit}` : ''}`,
    [totals?.unit],
  );

  const columns = useMemo(
    () => [
      {
        key: 'name',
        header: 'Cluster',
        render: (row) => (
          <div className="min-w-0">
            <Link className="font-medium text-forest-700 hover:underline" to={`/kvic/clusters/${row.id}`}>
              {row.name}
            </Link>
            <p className="truncate text-xs text-ink-muted">
              {row.district} · {row.code}
            </p>
          </div>
        ),
      },
      { key: 'beekeepers', header: 'Beekeepers', align: 'right', render: (row) => row.beekeepers ?? '—' },
      { key: 'hives', header: 'Hives', align: 'right', render: (row) => row.hives ?? '—' },
      {
        key: 'batches',
        header: 'Batches',
        align: 'right',
        render: (row) =>
          row.batches === null ? (
            <span className="text-xs text-ink-muted">unavailable</span>
          ) : (
            <div>
              <p>{row.batches}</p>
              <p className="text-xs text-ink-muted">
                {row.collections} harvest(s) · {row.represented} beekeeper(s)
              </p>
            </div>
          ),
      },
      {
        key: 'collected',
        header: 'Collected',
        align: 'right',
        render: (row) =>
          row.quantity_collected === null ? (
            <span className="text-xs text-ink-muted">unavailable</span>
          ) : (
            formatQuantity(row.quantity_collected)
          ),
      },
      {
        key: 'packaged',
        header: 'Packaged',
        align: 'right',
        render: (row) =>
          row.quantity_packaged === null ? (
            <span className="text-xs text-ink-muted">unavailable</span>
          ) : (
            <div>
              <p>{formatQuantity(row.quantity_packaged)}</p>
              <p className="text-xs text-ink-muted">{row.packages} package(s)</p>
            </div>
          ),
      },
      {
        key: 'laboratory',
        header: 'Laboratory',
        render: (row) =>
          row.laboratory === null ? (
            <span className="text-xs text-ink-muted">unavailable</span>
          ) : (
            <div className="flex flex-wrap gap-1">
              <Badge variant={row.laboratory.approved ? 'success' : 'neutral'} size="sm">
                {row.laboratory.approved} approved
              </Badge>
              <Badge variant={row.laboratory.rejected ? 'danger' : 'neutral'} size="sm">
                {row.laboratory.rejected} rejected
              </Badge>
              <Badge variant={row.laboratory.hold ? 'warning' : 'neutral'} size="sm">
                {row.laboratory.hold} hold
              </Badge>
            </div>
          ),
      },
      {
        key: 'stages',
        header: 'Stage breakdown',
        render: (row) =>
          row.breakdown === null ? (
            <span className="text-xs text-ink-muted">unavailable</span>
          ) : (
            <div className="flex flex-wrap gap-1">
              {[
                ['Collection', row.breakdown.collection],
                ['Processing', row.breakdown.processing],
                ['Lab', row.breakdown.laboratory],
                ['Packaging', row.breakdown.packaging],
                ['Distribution', row.breakdown.distribution],
                ['Delivered', row.breakdown.delivered],
              ].map(([label, value]) => (
                <Badge key={label} variant={value ? 'forest' : 'neutral'} size="sm">
                  {label}: {value}
                </Badge>
              ))}
            </div>
          ),
      },
      {
        key: 'state',
        header: 'State',
        render: (row) => (
          <div className="space-y-1">
            <Badge variant={row.is_active ? 'success' : 'neutral'} size="sm">
              {row.is_active ? 'Active' : 'Inactive'}
            </Badge>
            {row.problems.length ? (
              <Badge variant="warning" size="sm">
                Partly unavailable
              </Badge>
            ) : null}
          </div>
        ),
      },
    ],
    [formatQuantity],
  );

  return (
    <div className="space-y-6">
      <WorkspaceHeader
        title="Cluster analytics"
        description="Production figures per cluster you oversee — batches, quantities and how far each batch has travelled. All of it counted from the stored records."
        requiredRoles={['KVIC_OFFICER']}
        actions={
          <>
            <Button
              size="sm"
              variant="secondary"
              onClick={load}
              loading={loading}
              leftIcon={<RefreshCw size={15} aria-hidden="true" />}
            >
              Refresh
            </Button>
            <Button to="/kvic/clusters" size="sm" variant="secondary" leftIcon={<Building2 size={15} />}>
              Manage clusters
            </Button>
          </>
        }
      />

      <section aria-label="Scope totals" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Clusters in scope"
          value={totals?.clusters ?? '—'}
          helper={
            totals && totals.countedClusters !== totals.clusters
              ? `${totals.countedClusters} with readable figures`
              : 'Every cluster in your scope'
          }
          icon={<Building2 size={16} />}
          tone="honey"
          loading={loading}
        />
        <StatCard
          label="Honey batches in clusters"
          value={totals?.batches ?? '—'}
          helper={`${totals?.collections ?? 0} harvest record(s) behind them`}
          loading={loading}
        />
        <StatCard
          label="Quantity collected"
          value={formatQuantity(totals?.quantity_collected ?? 0)}
          helper={`${formatQuantity(totals?.quantity_packaged ?? 0)} packed as ${totals?.packages ?? 0} package(s)`}
          loading={loading}
        />
        <StatCard
          label="Laboratory outcomes"
          value={`${totals?.approved ?? 0} / ${totals?.rejected ?? 0} / ${totals?.hold ?? 0}`}
          helper={`approved / rejected / hold · ${totals?.delivered ?? 0} batch(es) delivered`}
          loading={loading}
        />
      </section>

      {failures.length ? (
        <Alert variant="warning" title="Some clusters could not be fully read">
          {failures
            .map((row) => `${row.code} — ${row.problems.join('; ')}`)
            .join(' · ')}{' '}
          Their figures are shown as <em>unavailable</em>, which is not the same as zero. Use Refresh to
          try again.
        </Alert>
      ) : null}

      <Card>
        <CardHeader
          title="By cluster"
          description="One row per cluster in your scope. Counters come from each cluster's own batch records — the same rows its batch table lists."
        />
        <CardBody className="space-y-3">
          <DataTable
            columns={columns}
            rows={rows}
            loading={loading}
            error={error}
            onRetry={load}
            emptyTitle="No clusters in your scope."
            emptyDescription="Clusters appear here once an administrator registers them and you are authorised for them."
            caption="Cluster analytics"
          />
          {generatedAt ? (
            <p className="text-xs text-ink-muted">
              Counted at {formatDateTime(generatedAt)}. Nothing on this page is stored ahead of time;
              it is queried when the page is opened.
            </p>
          ) : null}
        </CardBody>
      </Card>
    </div>
  );
}
