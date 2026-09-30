import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, Blocks, Building2, ClipboardList, Factory, FlaskConical, Hexagon, Package, Radio, Route } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { StatCard } from '@/components/common/StatCard';
import { BlockchainHealthCard } from '@/components/blockchain/BlockchainHealthCard';
import { WorkspaceHeader } from '@/components/common/WorkspaceHeader';
import { BATCH_STATUS_META, COLLECTION_MESSAGES, unitLabel } from '@/constants/collection';
import * as batchService from '@/services/batchService';
import * as beekeeperService from '@/services/beekeeperService';
import * as clusterService from '@/services/clusterService';
import * as hiveService from '@/services/hiveService';
import * as iotService from '@/services/iotService';
import * as laboratoryService from '@/services/laboratoryService';
import * as processingService from '@/services/processingService';
import { formatDate } from '@/utils/format';

/**
 * The KVIC officer's dashboard.
 *
 * Every figure is read through the cluster relationship — the officer's own scope
 * is applied by the API, not by this page. The records are the beekeepers' own:
 * their hives, their harvests, their batches, and the processing and laboratory
 * stages those batches passed through. KVIC keeps no copy of any of them.
 */
export default function KvicDashboardPage() {
  const [figures, setFigures] = useState(null);
  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [
      beekeepers,
      clusters,
      hives,
      iot,
      batchesResult,
      processing,
      laboratory,
    ] = await Promise.allSettled([
      beekeeperService.getBeekeeperSummary(),
      clusterService.listClusters({ pageSize: 1 }),
      hiveService.getHiveSummary(),
      iotService.getMonitoringSummary(),
      batchService.listBatches({ pageSize: 5 }),
      processingService.getProcessingSummary(),
      laboratoryService.getTestSummary(),
    ]);

    const value = (result) => (result.status === 'fulfilled' ? result.value : null);
    setFigures({
      beekeepers: value(beekeepers),
      clusterCount: value(clusters)?.meta?.total_items ?? null,
      hives: value(hives),
      iot: value(iot),
      batchMeta: value(batchesResult)?.meta ?? null,
      processing: value(processing),
      laboratory: value(laboratory),
    });
    setBatches(value(batchesResult)?.batches || []);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const byStatus = figures?.beekeepers?.by_verification_status || {};

  return (
    <div className="space-y-6">
      <WorkspaceHeader
        title="KVIC officer workspace"
        description="Your clusters: the apiaries in them, the honey they produced, and how it fared in processing and testing."
        requiredRoles={['KVIC_OFFICER']}
        actions={
          <Button to="/kvic/clusters" size="sm" leftIcon={<Building2 size={15} />}>
            Open clusters
          </Button>
        }
      />

      <section aria-label="Cluster oversight" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Clusters"
          value={figures?.clusterCount ?? '—'}
          helper="Clusters you are authorised for"
          icon={<Building2 size={16} />}
          tone="honey"
          loading={loading}
        />
        <StatCard
          label="Beekeepers"
          value={figures?.beekeepers?.total ?? '—'}
          helper={`${(byStatus.PENDING || 0) + (byStatus.UNDER_REVIEW || 0)} awaiting review · ${byStatus.VERIFIED || 0} verified`}
          icon={<ClipboardList size={16} />}
          loading={loading}
        />
        <StatCard
          label="Hives registered"
          value={figures?.hives?.total ?? '—'}
          helper={figures?.hives ? `${figures.hives.by_status?.ACTIVE ?? 0} active` : undefined}
          icon={<Hexagon size={16} />}
          loading={loading}
        />
        <StatCard
          label="Devices reporting"
          value={figures?.iot?.connected_devices ?? '—'}
          helper={figures?.iot ? `${figures.iot.offline_devices ?? 0} offline` : undefined}
          icon={<Radio size={16} />}
          tone="forest"
          loading={loading}
        />
      </section>

      <section aria-label="Supply chain oversight" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Honey batches"
          value={figures?.batchMeta?.total_items ?? '—'}
          helper="Produced by your clusters"
          icon={<Package size={16} />}
          loading={loading}
        />
        <StatCard
          label="Awaiting processing"
          value={figures?.processing?.awaiting_processing ?? '—'}
          helper={`${figures?.processing?.in_progress ?? 0} runs in progress`}
          icon={<Factory size={16} />}
          loading={loading}
        />
        <StatCard
          label="Awaiting laboratory"
          value={figures?.laboratory?.awaiting_testing ?? '—'}
          helper={`${figures?.laboratory?.in_progress ?? 0} tests in progress`}
          icon={<FlaskConical size={16} />}
          loading={loading}
        />
        <StatCard
          label="Quality outcomes"
          value={
            figures?.laboratory
              ? (figures.laboratory.passed ?? 0) + (figures.laboratory.failed ?? 0)
              : '—'
          }
          helper={`${figures?.laboratory?.passed ?? 0} passed · ${figures?.laboratory?.failed ?? 0} failed · ${figures?.laboratory?.inconclusive ?? 0} inconclusive`}
          icon={<FlaskConical size={16} />}
          tone="forest"
          loading={loading}
        />
      </section>

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <Card className="min-w-0">
          <CardHeader
            title="Latest batches in your clusters"
            description="The same batch records the beekeepers see, filtered to your clusters."
            icon={<Package size={16} />}
            action={
              <Button to="/kvic/batches" size="sm" variant="secondary" rightIcon={<ArrowRight size={15} />}>
                All batches
              </Button>
            }
          />
          <CardBody>
            {loading ? (
              <p className="text-sm text-ink-muted">{COLLECTION_MESSAGES.loadingBatches}</p>
            ) : batches.length ? (
              <ul className="divide-y divide-sand-100">
                {batches.map((batch) => {
                  const meta = BATCH_STATUS_META[batch.status] || null;
                  return (
                    <li key={batch.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                      <div className="min-w-0">
                        <p className="font-mono text-sm font-medium text-ink">{batch.batch_code}</p>
                        <p className="text-xs text-ink-muted">
                          {batch.beekeeper_name || batch.beekeeper_code || '—'} ·{' '}
                          {Number(batch.quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })}{' '}
                          {unitLabel(batch.unit)} · {formatDate(batch.collection_date)}
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant={meta?.variant || 'neutral'} size="sm">
                          {batch.status_label || meta?.label || batch.status}
                        </Badge>
                        <Button to={`/kvic/batches/${batch.id}`} size="sm" variant="ghost">
                          Open
                        </Button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="text-sm text-ink-muted">{COLLECTION_MESSAGES.emptyBatches}</p>
            )}
          </CardBody>
        </Card>

        <Card className="min-w-0">
          <CardHeader
            title="Officer tools"
            description="Everything here reads the beekeepers' own records. KVIC keeps no duplicate."
            icon={<Route size={16} />}
          />
          <CardBody className="space-y-2">
            {[
              { label: 'Cluster analytics', to: '/kvic/cluster-analytics', icon: <Building2 size={15} /> },
              { label: 'Processing oversight', to: '/kvic/processing', icon: <Factory size={15} /> },
              { label: 'Laboratory oversight', to: '/kvic/laboratory', icon: <FlaskConical size={15} /> },
              { label: 'Traceability', to: '/kvic/traceability', icon: <Route size={15} /> },
              { label: 'Blockchain ledger', to: '/kvic/blockchain', icon: <Blocks size={15} /> },
            ].map((entry) => (
              <Button
                key={entry.to}
                to={entry.to}
                variant="secondary"
                size="sm"
                fullWidth
                leftIcon={entry.icon}
                className="justify-start"
              >
                {entry.label}
              </Button>
            ))}
          </CardBody>
        </Card>
      </div>

      {/* Real synchronisation numbers for the officer's own scope. */}
      <BlockchainHealthCard compact />
    </div>
  );
}
