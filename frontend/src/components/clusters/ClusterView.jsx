import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Building2, Layers, RefreshCw, Trash2, UserCog } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import { ClusterDeleteDialog } from '@/components/clusters/ClusterDeleteDialog';
import { ClusterOverviewCards } from '@/components/clusters/ClusterOverviewCards';
import { ClusterHivesTable } from '@/components/clusters/ClusterHivesTable';
import { ClusterDevicesTable } from '@/components/clusters/ClusterDevicesTable';
import { ClusterHarvestPanel } from '@/components/clusters/ClusterHarvestPanel';
import { ClusterAiPanel } from '@/components/clusters/ClusterAiPanel';
import { ClusterBatchSection } from '@/components/clusters/ClusterBatchSection';
import { ClusterTelemetryPanel } from '@/components/clusters/ClusterTelemetryPanel';
import { normaliseError } from '@/utils/errors';
import { formatDateTime } from '@/utils/format';
import { useAuth } from '@/hooks/useAuth';
import { ROLES } from '@/constants/roles';
import * as clusterAnalytics from '@/services/clusterAnalyticsService';
import * as clusterService from '@/services/clusterService';

const VERIFICATION_VARIANT = {
  VERIFIED: 'success',
  PENDING: 'pending',
  UNDER_REVIEW: 'info',
  REJECTED: 'danger',
  SUSPENDED: 'warning',
};

/**
 * One cluster, seen as a view over the records that already exist.
 *
 * The chain is `KVIC → cluster → beekeeper → hive → device → telemetry →
 * analysis`, and this screen follows it without copying anything: the hives are
 * the owners' rows, the devices are paired to those hives, the readings were
 * stored against those devices and the assessments were computed from those
 * readings. Editing anything is done where the record lives — here the officer
 * reads, and follows a hive into its own screen when a closer look is needed.
 *
 * Every panel distinguishes "none" from "not loaded": counters show real zeroes,
 * and an empty list says so in words.
 */
export function ClusterView({
  clusterId,
  hiveDetailBasePath,
  membersPath,
  collectionsPath = null,
  batchesPath = null,
  //: Whether the viewer may change the cluster's batches. Presentation only:
  //: `POST/DELETE /clusters/{id}/batches` require CLUSTER_MANAGE and refuse
  //: anyone else, whatever this screen renders.
  canManageBatches = null,
  //: Where to go once this cluster has been removed. Without it the Remove button
  //: is not offered, because there would be nowhere to land.
  afterDeletePath = null,
}) {
  const navigate = useNavigate();
  const { role } = useAuth();
  const [overview, setOverview] = useState(null);
  const [aiState, setAiState] = useState(null);
  const [telemetry, setTelemetry] = useState(null);
  // The registry record itself — including what is recorded under the cluster and
  // whether it may be removed. Read from the cluster endpoint rather than derived
  // from the counters above, because the deletion rule is the server's to state.
  const [registry, setRegistry] = useState(null);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(
    async ({ silent = false } = {}) => {
      if (silent) setRefreshing(true);
      else setLoading(true);
      setError(null);
      try {
        // Three independent reads; the cluster view is composed from the same
        // records the rest of the platform serves.
        const [counters, ai, latest, record] = await Promise.all([
          clusterAnalytics.getClusterOverview(clusterId),
          clusterAnalytics.getClusterAiState(clusterId),
          clusterAnalytics.getClusterLatestTelemetry(clusterId),
          clusterService.getCluster(clusterId).catch(() => null),
        ]);
        setOverview(counters);
        setAiState(ai);
        setTelemetry(latest);
        setRegistry(record);
      } catch (caught) {
        setError(normaliseError(caught));
        setOverview(null);
        setAiState(null);
        setTelemetry(null);
        setRegistry(null);
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [clusterId],
  );

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !overview) {
    return <LoadingState message="Loading the cluster…" />;
  }

  if (error && !overview) {
    return <ErrorState error={error} onRetry={() => load()} />;
  }

  const cluster = overview?.cluster;
  const beekeepers = overview?.beekeepers;
  // KVIC officers and administrators hold CLUSTER_MANAGE on the server; everyone
  // else reads this cluster without the batch controls.
  const manageBatches =
    canManageBatches ?? [ROLES.KVIC_OFFICER, ROLES.ADMIN].includes(role);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          icon={<Building2 size={18} aria-hidden="true" />}
          title={cluster?.cluster_name || 'Cluster'}
          description={
            <>
              {cluster?.cluster_code ? <span className="font-medium text-ink-soft">{cluster.cluster_code} · </span> : null}
              {[cluster?.district, cluster?.state].filter(Boolean).join(', ') || 'District not recorded'}
            </>
          }
          action={
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={cluster?.is_active ? 'success' : 'neutral'} size="sm">
                {cluster?.is_active ? 'Active' : 'Inactive'}
              </Badge>
              {membersPath ? (
                <Button to={membersPath} variant="secondary" size="sm" leftIcon={<UserCog size={16} aria-hidden="true" />}>
                  Beekeepers
                </Button>
              ) : null}
              <Button
                variant="ghost"
                size="sm"
                loading={refreshing}
                onClick={() => load({ silent: true })}
                leftIcon={<RefreshCw size={16} aria-hidden="true" />}
              >
                Refresh
              </Button>
            </div>
          }
        />
        <CardBody className="space-y-4">
          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-xs uppercase tracking-wide text-ink-muted">Coordinator</dt>
              <dd className="text-ink">{cluster?.coordinator_name || 'Not recorded'}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-ink-muted">Coordinator phone</dt>
              <dd className="text-ink">{cluster?.coordinator_phone || 'Not recorded'}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-ink-muted">Membership</dt>
              <dd className="text-ink">
                {beekeepers?.total ?? 0} beekeeper(s)
                {beekeepers?.by_verification_status ? (
                  <span className="ml-2 inline-flex flex-wrap gap-1">
                    {Object.entries(beekeepers.by_verification_status)
                      .filter(([, value]) => value > 0)
                      .map(([status, value]) => (
                        <Badge key={status} variant={VERIFICATION_VARIANT[status] || 'neutral'} size="sm">
                          {value} {status.replaceAll('_', ' ').toLowerCase()}
                        </Badge>
                      ))}
                  </span>
                ) : null}
              </dd>
            </div>
          </dl>

          {overview?.generated_at ? (
            <p className="text-xs text-ink-muted">
              Counted at {formatDateTime(overview.generated_at)}. Every figure is a query over the
              beekeepers&apos; own records.
            </p>
          ) : null}

          {!cluster?.is_active ? (
            <Alert variant="info" title="This cluster is inactive">
              It stays readable, but no beekeeper or hive can be placed in it until it is reactivated.
            </Alert>
          ) : null}
        </CardBody>
      </Card>

      <ClusterOverviewCards overview={overview} loading={loading} />

      {/* The cluster's honey batches, straight after the cluster itself: this is
          the relationship the KVIC screens manage (cluster → batch → collection
          → beekeeper → hive), and the count here is the list's own length. */}
      <ClusterBatchSection
        clusterId={clusterId}
        canManage={manageBatches}
        batchesPath={batchesPath}
      />

      <div className="grid gap-5 lg:grid-cols-2">
        <ClusterTelemetryPanel telemetry={telemetry} loading={loading} />
        <Card>
          <CardHeader
            title="What this view is"
            description="How the records on this page are connected."
          />
          <CardBody className="space-y-3 text-sm text-ink-soft">
            <p>
              The cluster holds the beekeepers. Each beekeeper holds their own hives. Each hive holds
              its devices, the devices hold the readings, and the assessments are computed from
              those readings.
            </p>
            <p>
              This screen reads that chain from the top. It stores nothing of its own, so a hive
              corrected on its own screen — or a beekeeper moved to another cluster — is reflected
              here immediately.
            </p>
            <p>
              The one thing this screen does write is the cluster&apos;s honey batches: placing a
              batch, or removing one, edits the cluster link on that batch. The honey itself, its
              harvest, its beekeeper and its hives are left where their own records are.
            </p>
            <p className="text-ink-muted">
              Hives whose owner is not in any cluster are not shown here. Officers resolve them
              through the hive registry filter <code>has_cluster=false</code> and place them
              individually.
            </p>
          </CardBody>
        </Card>
      </div>

      <ClusterHivesTable
        clusterId={clusterId}
        hiveDetailBasePath={hiveDetailBasePath}
        onLoaded={() => {}}
      />

      <ClusterAiPanel aiState={aiState} loading={loading} />

      <ClusterDevicesTable clusterId={clusterId} />

      <ClusterHarvestPanel
        clusterId={clusterId}
        collectionsPath={collectionsPath}
        batchesPath={batchesPath}
      />

      <p className="text-xs text-ink-muted">
        Looking for a beekeeper list? Membership is managed on{' '}
        <Link className="underline" to={membersPath || '#'}>
          the cluster management screen
        </Link>
        .
      </p>

      {registry ? (
        <Card>
          <CardHeader
            icon={<Layers size={18} aria-hidden="true" />}
            title="The cluster as a register entry"
            description="What is recorded under this cluster, counted from the records themselves — and whether it may be removed."
            action={
              afterDeletePath ? (
                <Button
                  variant="secondary"
                  size="sm"
                  leftIcon={<Trash2 size={15} aria-hidden="true" />}
                  onClick={() => setDeleteOpen(true)}
                  data-testid="open-cluster-delete"
                >
                  Remove cluster
                </Button>
              ) : null
            }
          />
          <CardBody className="space-y-3">
            <div className="flex flex-wrap gap-2">
              {Object.entries(registry.dependencies || {}).map(([label, value]) => (
                <Badge key={label} variant={value ? 'info' : 'neutral'} size="sm">
                  {label}: {value}
                </Badge>
              ))}
            </div>
            <p className="text-xs text-ink-muted">
              {registry.can_delete
                ? 'Nothing is recorded under this cluster, so the server accepts its removal.'
                : registry.delete_blocked_reason}
            </p>
          </CardBody>
        </Card>
      ) : null}

      <ClusterDeleteDialog
        open={deleteOpen}
        cluster={registry?.cluster || cluster}
        onClose={() => setDeleteOpen(false)}
        onDeleted={() => {
          if (afterDeletePath) navigate(afterDeletePath);
        }}
        onDeactivate={() => {
          setDeleteOpen(false);
          load({ silent: true });
        }}
      />
    </div>
  );
}

export default ClusterView;
