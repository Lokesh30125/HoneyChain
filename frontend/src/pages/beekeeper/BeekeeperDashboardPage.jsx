import { useCallback, useEffect, useState } from 'react';
import {
  ArrowRight,
  ClipboardList,
  Factory,
  FlaskConical,
  Hexagon,
  Package,
  Route,
} from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { StatCard } from '@/components/common/StatCard';
import { WorkspaceHeader } from '@/components/common/WorkspaceHeader';
import { Badge } from '@/components/ui/Badge';
import { BATCH_STATUS_META, COLLECTION_MESSAGES, unitLabel } from '@/constants/collection';
import { LAB_MESSAGES } from '@/constants/laboratory';
import { VerificationBadge } from '@/components/beekeepers/VerificationBadge';
import * as batchService from '@/services/batchService';
import * as beekeeperService from '@/services/beekeeperService';
import * as collectionService from '@/services/collectionService';
import * as hiveService from '@/services/hiveService';
import * as iotService from '@/services/iotService';
import * as laboratoryService from '@/services/laboratoryService';
import { normaliseError } from '@/utils/errors';
import { formatDate } from '@/utils/format';

/**
 * The beekeeper's dashboard.
 *
 * A beekeeper's day starts with their own apiary and ends with what happened to
 * their honey. The tiles are counted from stored rows, and the journey card reads
 * the batches their harvests produced — including the laboratory stage, which is
 * written by the laboratory technician and read here from the same record. Nothing
 * on this page can change a batch; the status shown is the status the platform
 * holds.
 */
export default function BeekeeperDashboardPage() {
  const [figures, setFigures] = useState(null);
  const [record, setRecord] = useState(null);
  const [hives, setHives] = useState([]);
  const [batches, setBatches] = useState([]);
  const [collections, setCollections] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [hiveSummary, hiveList, iot, batchList, collectionList, labSummary, beekeeperRecord] =
        await Promise.allSettled([
          hiveService.getHiveSummary(),
          hiveService.listHives({ pageSize: 5 }),
          iotService.getMonitoringSummary(),
          batchService.listBatches({ pageSize: 5 }),
          collectionService.listCollections({ pageSize: 5 }),
          laboratoryService.getTestSummary(),
          beekeeperService.getMyBeekeeperRecord(),
        ]);
      setRecord(beekeeperRecord.status === 'fulfilled' ? beekeeperRecord.value : null);
      setFigures({
        hives: hiveSummary.status === 'fulfilled' ? hiveSummary.value : null,
        iot: iot.status === 'fulfilled' ? iot.value : null,
        collectionMeta: collectionList.status === 'fulfilled' ? collectionList.value.meta : null,
        batchMeta: batchList.status === 'fulfilled' ? batchList.value.meta : null,
        lab: labSummary.status === 'fulfilled' ? labSummary.value : null,
      });
      setHives(hiveList.status === 'fulfilled' ? hiveList.value.hives : []);
      setBatches(batchList.status === 'fulfilled' ? batchList.value.batches : []);
      setCollections(collectionList.status === 'fulfilled' ? collectionList.value.collections : []);
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const hiveSummary = figures?.hives;
  const iot = figures?.iot;

  return (
    <div className="space-y-6">
      <WorkspaceHeader
        title="Beekeeper workspace"
        description="Your apiary, your harvests, and where each batch of your honey stands today."
        requiredRoles={['BEEKEEPER']}
        actions={
          <Button to="/beekeeper/collections" size="sm" leftIcon={<ClipboardList size={15} />}>
            Record a harvest
          </Button>
        }
      />

      {record ? (
        <Card>
          <CardBody className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex flex-wrap items-center gap-x-8 gap-y-3 text-sm">
              <div>
                <p className="text-xs uppercase tracking-wide text-ink-muted">Apiary registration</p>
                <p className="mt-0.5 font-mono text-ink">{record.beekeeper_code}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-ink-muted">Verification</p>
                <p className="mt-1">
                  <VerificationBadge status={record.verification_status} size="sm" />
                </p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-ink-muted">Cluster</p>
                <p className="mt-0.5 text-ink">
                  {record.cluster?.cluster_name || 'Not in a cluster'}
                </p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-ink-muted">Location</p>
                <p className="mt-0.5 text-ink">
                  {[record.village, record.district].filter(Boolean).join(', ') || 'Not recorded'}
                </p>
              </div>
            </div>
            <Button to="/beekeeper/profile" size="sm" variant="secondary">
              My beekeeper profile
            </Button>
          </CardBody>
        </Card>
      ) : null}

      <section aria-label="Your apiary" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="My hives"
          value={hiveSummary?.total ?? '—'}
          helper={
            hiveSummary
              ? `${hiveSummary.by_status?.ACTIVE ?? 0} active · ${hiveSummary.with_device ?? 0} with a device`
              : undefined
          }
          icon={<Hexagon size={16} />}
          tone="honey"
          loading={loading}
        />
        <StatCard
          label="Devices reporting"
          value={iot?.connected_devices ?? '—'}
          helper={iot ? `${iot.total_devices ?? 0} paired · ${iot.offline_devices ?? 0} offline` : undefined}
          icon={<Package size={16} />}
          loading={loading}
        />
        <StatCard
          label="My harvests"
          value={figures?.collectionMeta?.total_items ?? '—'}
          helper="Collections recorded by you"
          icon={<ClipboardList size={16} />}
          loading={loading}
        />
        <StatCard
          label="My batches"
          value={figures?.batchMeta?.total_items ?? '—'}
          helper="Created when a harvest is completed"
          icon={<Package size={16} />}
          tone="forest"
          loading={loading}
        />
      </section>

      <Card>
        <CardHeader
          title="Your hives"
          description="The hives registered under your apiary, with the devices paired to them."
          icon={<Hexagon size={16} />}
          action={
            <Button to="/beekeeper/hives" size="sm" variant="secondary" rightIcon={<ArrowRight size={15} />}>
              My Hives
            </Button>
          }
        />
        <CardBody>
          {loading ? (
            <p className="text-sm text-ink-muted">Loading your hives...</p>
          ) : hives.length ? (
            <ul className="divide-y divide-sand-100">
              {hives.map((hive) => (
                <li key={hive.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                  <span className="min-w-0">
                    <span className="font-mono text-sm text-ink">{hive.hive_code}</span>
                    {hive.hive_name ? (
                      <span className="ml-2 text-sm text-ink-muted">{hive.hive_name}</span>
                    ) : null}
                  </span>
                  <span className="text-xs text-ink-muted">
                    {hive.device_count
                      ? `${hive.device_count} device(s) paired`
                      : 'No device paired yet'}
                    {hive.is_active === false ? ' · inactive' : ''}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-ink-muted">
              No hives registered yet. Register your first hive to start recording what your bees are doing.
            </p>
          )}
        </CardBody>
      </Card>

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <Card className="min-w-0">
          <CardHeader
            title="Your honey's journey"
            description="Each batch with the stage it has reached. Updated by the processing and laboratory teams — you read it, you do not edit it."
            icon={<Route size={16} />}
            action={
              <Button to="/beekeeper/traceability" size="sm" variant="secondary" rightIcon={<ArrowRight size={15} />}>
                Traceability
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
                          {Number(batch.quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })}{' '}
                          {unitLabel(batch.unit)} · harvested {formatDate(batch.collection_date)}
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant={meta?.variant || 'neutral'} size="sm">
                          {batch.status_label || meta?.label || batch.status}
                        </Badge>
                        <Button to={`/beekeeper/batches/${batch.id}`} size="sm" variant="ghost">
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
            title="Laboratory status of my honey"
            description="Measured values recorded against your batches, as they stand."
            icon={<FlaskConical size={16} />}
          />
          <CardBody className="space-y-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-ink-soft">Tests on my batches</span>
              <span className="font-medium text-ink">{figures?.lab?.total ?? (loading ? '…' : 0)}</span>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant="success" size="sm">
                {figures?.lab?.passed ?? 0} passed
              </Badge>
              <Badge variant="danger" size="sm">
                {figures?.lab?.failed ?? 0} failed
              </Badge>
              <Badge variant="neutral" size="sm">
                {figures?.lab?.inconclusive ?? 0} inconclusive
              </Badge>
            </div>
            <p className="text-xs text-ink-muted">{LAB_MESSAGES.resultsEmpty} Until then this panel stays at zero — it is not a placeholder for a number.</p>
            <Button to="/beekeeper/batches" size="sm" variant="secondary" leftIcon={<Factory size={15} />}>
              Open my batches
            </Button>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Recent harvests"
          description="The last collections you recorded, with the batch each one produced."
          icon={<ClipboardList size={16} />}
        />
        <CardBody>
          {loading ? (
            <p className="text-sm text-ink-muted">{COLLECTION_MESSAGES.loadingCollections}</p>
          ) : collections.length ? (
            <ul className="divide-y divide-sand-100">
              {collections.map((collection) => (
                <li key={collection.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                  <span className="font-mono text-sm text-ink">{collection.collection_code}</span>
                  <span className="text-xs text-ink-muted">
                    {Number(collection.total_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })}{' '}
                    {unitLabel(collection.unit)} · {formatDate(collection.collection_date)}
                  </span>
                  <Badge variant={collection.status === 'COMPLETED' ? 'success' : 'info'} size="sm">
                    {collection.status_label || collection.status}
                  </Badge>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-ink-muted">{COLLECTION_MESSAGES.emptyCollections}</p>
          )}
        </CardBody>
      </Card>

      {error ? <p className="text-sm text-status-danger">{error.message}</p> : null}
    </div>
  );
}
