import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { RefreshCw, Wheat } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { CollectionSummaryCards } from '@/components/collections/CollectionSummaryCards';
import { CollectionTable } from '@/components/collections/CollectionTable';
import { RecordCollectionPanel } from '@/components/collections/RecordCollectionPanel';
import { COLLECTION_MESSAGES, COLLECTION_STATUS_META } from '@/constants/collection';
import { ROLES } from '@/constants/roles';
import * as collectionService from '@/services/collectionService';
import * as clusterService from '@/services/clusterService';
import { normaliseError } from '@/utils/errors';

/**
 * The collection workspace, shared by the beekeeper, KVIC and admin screens.
 *
 * The **beekeeper** gets the harvest form and the actions that go with owning the
 * record — until a harvest is completed, after which the UI stops offering them
 * (the API refuses them anyway; this just does not pretend otherwise).
 *
 * **Staff** get the same list read-only, with a cluster filter, because the rows
 * are the beekeepers' own — the cluster screen is a view, never a second copy.
 * The record form is not rendered for them at all, since only the beekeeper who
 * harvested the honey can record it.
 */
const STATUS_OPTIONS = Object.entries(COLLECTION_STATUS_META).map(([value, meta]) => ({
  value,
  label: meta.label,
}));

export function CollectionWorkspace({
  role = ROLES.BEEKEEPER,
  basePath,
  title = 'Collections',
  description,
}) {
  const isBeekeeper = role === ROLES.BEEKEEPER;
  // The collection centre reads the same rows the officer and the administrator
  // read: same table, same filters, no form — the write path belongs to the
  // beekeeper, and the API refuses anyone else regardless of what is rendered.
  const isStaff =
    role === ROLES.KVIC_OFFICER ||
    role === ROLES.ADMIN ||
    role === ROLES.COLLECTION_CENTER;

  const [collections, setCollections] = useState([]);
  const [meta, setMeta] = useState(null);
  const [summary, setSummary] = useState(null);
  const [eligible, setEligible] = useState(null);
  const [clusters, setClusters] = useState([]);
  const [ownClusterLabel, setOwnClusterLabel] = useState(null);
  // A cluster screen can link here with ?cluster=<id>; the filter is the caller's
  // own scope restricted further, so it can never widen what they may read.
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
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState(null);

  const load = useCallback(
    async ({ silent = false } = {}) => {
      if (silent) setRefreshing(true);
      else setLoading(true);
      setError(null);
      try {
        const [list, counters] = await Promise.all([
          collectionService.listCollections({
            page: filters.page,
            pageSize: 20,
            search: filters.search || undefined,
            status: filters.status || undefined,
            clusterId: filters.clusterId || undefined,
          }),
          collectionService.getCollectionSummary(),
        ]);
        setCollections(list.collections);
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

  // The beekeeper's harvestable hives, and the cluster their harvests will land
  // in. Both are read, not chosen: the cluster comes from their membership.
  useEffect(() => {
    if (!isBeekeeper) return undefined;
    let cancelled = false;
    collectionService
      .getEligibleHives()
      .then((payload) => {
        if (!cancelled) setEligible(payload);
      })
      .catch(() => {
        if (!cancelled) setEligible({ hives: [], total: 0, note: COLLECTION_MESSAGES.emptyEligibleHives });
      });
    clusterService
      .listClusters({ pageSize: 100 })
      .then(({ clusters: rows }) => {
        if (!cancelled && rows.length) setOwnClusterLabel(rows[0].cluster_name);
      })
      .catch(() => {
        /* No cluster registry access: the form still says the harvest is recorded to the apiary. */
      });
    return () => {
      cancelled = true;
    };
  }, [isBeekeeper]);

  useEffect(() => {
    if (!isStaff) return undefined;
    let cancelled = false;
    clusterService
      .listClusters({ pageSize: 100 })
      .then(({ clusters: rows }) => {
        if (!cancelled) setClusters(rows.map((cluster) => ({ value: cluster.id, label: cluster.cluster_name })));
      })
      .catch(() => {
        if (!cancelled) setClusters([]);
      });
    return () => {
      cancelled = true;
    };
  }, [isStaff]);

  const record = async (payload) => {
    setSubmitting(true);
    setFormError(null);
    try {
      const { collection, meta: responseMeta } = await collectionService.createCollection(payload);
      // Refresh the workspace from the server rather than assuming the new
      // harvest looks the way we sent it: codes, totals and the AI snapshot are
      // the server's to decide.
      setFilters((prev) => ({ ...prev, page: 1 }));
      await load({ silent: true });
      if (eligible) {
        collectionService.getEligibleHives().then(setEligible).catch(() => {});
      }
      return { ok: true, reused: responseMeta?.reused === true, collection };
    } catch (caught) {
      const normalised = normaliseError(caught);
      setFormError(normalised.message || String(normalised));
      return { ok: false, reused: false };
    } finally {
      setSubmitting(false);
    }
  };

  const totals = summary?.harvested_totals || {};
  const harvested = Object.entries(totals)
    .filter(([, value]) => Number(value) > 0)
    .map(([unit, value]) => `${Number(value).toLocaleString()} ${unit === 'GRAM' ? 'g' : 'kg'}`)
    .join(' · ');

  return (
    <div className="space-y-6">
      {error && !loading ? (
        <Alert variant="danger" title={COLLECTION_MESSAGES.loadFailed} onClose={() => setError(null)}>
          {error.message || String(error)}
        </Alert>
      ) : null}

      <CollectionSummaryCards summary={summary} loading={loading && !summary} />

      <Card>
        <CardHeader
          title={title}
          description={
            description ||
            (isBeekeeper
              ? 'Every harvest you record, from the hives it came from to the batch it becomes.'
              : 'Harvests recorded by the beekeepers in your scope — the same records their owners see.')
          }
          icon={<Wheat size={18} aria-hidden="true" />}
          action={
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                loading={refreshing}
                leftIcon={<RefreshCw size={14} aria-hidden="true" />}
                onClick={() => load({ silent: true })}
              >
                Refresh
              </Button>
              {isBeekeeper ? (
                <Button as={Link} to={`${basePath}/batches`} variant="secondary" size="sm">
                  Honey batches
                </Button>
              ) : null}
            </div>
          }
        />
        <CardBody className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Input
              label="Search"
              placeholder="Collection code or notes"
              value={filters.search}
              onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value, page: 1 }))}
            />
            <Select
              label="Status"
              placeholder="All statuses"
              options={STATUS_OPTIONS}
              value={filters.status}
              onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value, page: 1 }))}
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
              <p className="text-xs text-ink-muted">Harvested total</p>
              <p className="text-sm font-medium text-ink">{harvested || '—'}</p>
              <p className="text-xs text-ink-muted">Completed harvests only, per unit</p>
            </div>
          </div>

          <CollectionTable
            collections={collections}
            loading={loading}
            error={error}
            onRetry={() => load()}
            meta={meta}
            onPageChange={(page) => setFilters((prev) => ({ ...prev, page }))}
            detailPath={`${basePath}/collections`}
          />
        </CardBody>
      </Card>

      {isBeekeeper ? (
        <RecordCollectionPanel
          eligibleHives={eligible?.hives || []}
          loadingHives={eligible === null}
          clusterLabel={ownClusterLabel}
          onSubmit={record}
          submitting={submitting}
          error={formError}
          onDismissError={() => setFormError(null)}
        />
      ) : (
        <Alert variant="info" title="Staff read harvests, they do not record them">
          A collection is the beekeeper&apos;s own harvest record, so only the beekeeper who took the
          honey can create it. This screen shows the same rows their owner sees, within your scope.
        </Alert>
      )}
    </div>
  );
}

export default CollectionWorkspace;
