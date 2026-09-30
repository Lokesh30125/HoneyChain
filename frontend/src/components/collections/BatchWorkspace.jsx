import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Package, RefreshCw } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { BatchTable } from '@/components/collections/BatchTable';
import { BATCH_STATUS_OPTIONS, COLLECTION_MESSAGES, unitLabel } from '@/constants/collection';
import * as batchService from '@/services/batchService';
import * as clusterService from '@/services/clusterService';
import { normaliseError } from '@/utils/errors';

/**
 * The honey batch workspace, shared by the beekeeper, KVIC and admin screens.
 *
 * There is no "create batch" button anywhere on this page, and that is the honest
 * answer: batches are produced by completing a collection. The panel says so, so a
 * reader is not left wondering where the button went.
 *
 * Staff (KVIC, admin) get a cluster filter and see the batches of the beekeepers
 * in scope; a beekeeper sees their own harvests' batches. The scope is enforced by
 * the API — this component only chooses what to ask for.
 */
export function BatchWorkspace({ role = 'BEEKEEPER', basePath, title = 'Honey batches', description }) {
  const [batches, setBatches] = useState([]);
  const [meta, setMeta] = useState(null);
  const [summary, setSummary] = useState(null);
  const [clusters, setClusters] = useState([]);
  // A cluster screen can link here with ?cluster=<id>; it narrows the caller's own
  // scope further and can never widen it.
  const [searchParams] = useSearchParams();
  const [filters, setFilters] = useState({
    page: 1,
    search: '',
    status: '',
    clusterId: searchParams.get('cluster') || '',
  });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  const isStaff = role === 'KVIC_OFFICER' || role === 'ADMIN';

  const load = useCallback(
    async ({ silent = false } = {}) => {
      if (silent) setRefreshing(true);
      else setLoading(true);
      setError(null);
      try {
        const [list, counters] = await Promise.all([
          batchService.listBatches({
            page: filters.page,
            pageSize: 20,
            search: filters.search || undefined,
            status: filters.status || undefined,
            clusterId: filters.clusterId || undefined,
          }),
          batchService.getBatchSummary(),
        ]);
        setBatches(list.batches);
        setMeta(list.meta);
        setSummary(counters);
      } catch (caught) {
        setError(normaliseError(caught));
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [filters],
  );

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!isStaff) return;
    let cancelled = false;
    clusterService
      .listClusters({ pageSize: 100 })
      .then(({ clusters: rows }) => {
        if (!cancelled) {
          setClusters(rows.map((cluster) => ({ value: cluster.id, label: cluster.cluster_name })));
        }
      })
      .catch(() => {
        // A cluster list the caller may not read is not an error on this screen;
        // the batches are still shown in whatever scope the API granted.
        if (!cancelled) setClusters([]);
      });
    return () => {
      cancelled = true;
    };
  }, [isStaff]);

  const totals = summary?.batched_totals || {};
  const totalsText = Object.entries(totals)
    .filter(([, value]) => Number(value) > 0)
    .map(([unit, value]) => `${Number(value).toLocaleString()} ${unitLabel(unit)}`)
    .join(' · ');

  return (
    <div className="space-y-6">
      {error ? (
        <Alert variant="danger" title={COLLECTION_MESSAGES.loadFailed} onClose={() => setError(null)}>
          {error.message || String(error)}
        </Alert>
      ) : null}

      <Card>
        <CardHeader
          title={title}
          description={description || 'Each batch is produced by completing a collection.'}
          icon={<Package size={18} aria-hidden="true" />}
          action={
            <Button
              variant="secondary"
              size="sm"
              loading={refreshing}
              leftIcon={<RefreshCw size={14} aria-hidden="true" />}
              onClick={() => load({ silent: true })}
            >
              Refresh
            </Button>
          }
        />
        <CardBody className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Input
              label="Search"
              placeholder="Batch code"
              value={filters.search}
              onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value, page: 1 }))}
            />
            <Select
              label="Stage"
              placeholder="All stages"
              options={BATCH_STATUS_OPTIONS}
              value={filters.status}
              onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value, page: 1 }))}
              hint="Every stage the platform can actually reach."
            />
            {isStaff ? (
              <Select
                label="Cluster"
                placeholder="All clusters"
                options={clusters}
                value={filters.clusterId}
                onChange={(event) => setFilters((prev) => ({ ...prev, clusterId: event.target.value, page: 1 }))}
              />
            ) : null}
            <div className="rounded-lg bg-sand-50 px-3 py-2">
              <p className="text-xs text-ink-muted">Total batches</p>
              <p className="text-sm font-medium text-ink">{summary?.total ?? 0}</p>
              <p className="text-xs text-ink-muted">{totalsText || 'Nothing batched yet'}</p>
            </div>
          </div>

          {summary?.awaiting_collection_completion ? (
            <Alert variant="info" title={`${summary.awaiting_collection_completion} open collection(s) have no batch yet`}>
              A batch appears when a collection is completed. Open the collection and use “Complete
              &amp; create batch”.
              {basePath ? (
                <>
                  {' '}
                  <Link className="font-medium underline" to={`${basePath}/collections`}>
                    Go to collections
                  </Link>
                </>
              ) : null}
            </Alert>
          ) : null}

          <BatchTable
            batches={batches}
            loading={loading}
            error={error}
            onRetry={() => load()}
            meta={meta}
            onPageChange={(page) => setFilters((prev) => ({ ...prev, page }))}
            detailPath={`${basePath}/batches`}
          />
        </CardBody>
      </Card>
    </div>
  );
}

export default BatchWorkspace;
