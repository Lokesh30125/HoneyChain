import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Boxes, PackageCheck, RefreshCw, Route, Truck } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { StatCard } from '@/components/common/StatCard';
import { CreateShipmentDialog } from '@/components/distribution/CreateShipmentDialog';
import { ShipmentTable } from '@/components/distribution/ShipmentTable';
import { PackageRegisterTable } from '@/components/packaging/PackageRegisterTable';
import {
  DISTRIBUTION_MESSAGES,
  DISTRIBUTION_STATUS_META,
  DISTRIBUTION_VIEW_COPY,
} from '@/constants/distribution';
import { ROLES } from '@/constants/roles';
import { useToast } from '@/hooks/useToast';
import * as distributionService from '@/services/distributionService';
import * as packagingService from '@/services/packagingService';
import { normaliseError } from '@/utils/errors';
import { formatNumber } from '@/utils/format';

/**
 * The distributor's workspace.
 *
 * A shipment is raised against a *released package* — one the packaging unit has
 * already let go of — and then walks the journey the server allows: ready →
 * dispatched → in transit → delivered, or cancelled while nothing has arrived. The
 * buttons mirror that order exactly; there is no control that jumps a step, and the
 * server refuses the same jumps independently.
 *
 * The batch is not copied here. A shipment carries a package, the package carries
 * the batch, and every screen reads those same rows.
 */

const STATUS_FILTERS = [
  { value: '', label: 'All shipment statuses' },
  ...Object.entries(DISTRIBUTION_STATUS_META).map(([value, meta]) => ({ value, label: meta.label })),
];

const VIEW_COPY = {
  overview: DISTRIBUTION_VIEW_COPY.overview,
  ready: DISTRIBUTION_VIEW_COPY.ready,
  shipments: DISTRIBUTION_VIEW_COPY.shipments,
  transit: DISTRIBUTION_VIEW_COPY.transit,
  delivered: DISTRIBUTION_VIEW_COPY.delivered,
  history: DISTRIBUTION_VIEW_COPY.history,
};

export function DistributionWorkspace({ role = ROLES.DISTRIBUTOR, view = 'overview' }) {
  const toast = useToast();
  const canWrite = role === ROLES.DISTRIBUTOR || role === ROLES.ADMIN;

  const [summary, setSummary] = useState(null);
  const [shipments, setShipments] = useState([]);
  const [meta, setMeta] = useState(null);
  const [releasedPackages, setReleasedPackages] = useState([]);
  // The shops a shipment may be addressed to, and the shipments that name none.
  // Both are read from the API rather than assumed, and a failure to read either is
  // reported: an empty retailer list means "no shop can receive", which must never
  // be shown as though it were true when the request simply failed.
  const [retailers, setRetailers] = useState([]);
  const [retailersLoading, setRetailersLoading] = useState(false);
  const [retailersError, setRetailersError] = useState(null);
  const [unassigned, setUnassigned] = useState([]);
  // Which shop is being named for which shipment, before the operator commits it.
  const [assignments, setAssignments] = useState({});

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [creating, setCreating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [dialogError, setDialogError] = useState(null);

  const [filters, setFilters] = useState({ search: '', status: '', page: 1 });

  const statusFilter =
    view === 'ready'
      ? 'READY_FOR_DISPATCH'
      : view === 'transit'
        ? 'IN_TRANSIT'
        : view === 'delivered'
          ? 'DELIVERED'
          : filters.status;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // A failure to read the shipments is a failure of this page: showing an empty
      // table would say "there are no shipments", which is a different, false, claim.
      // The summary and the package picker are the only parts allowed to degrade —
      // they are counters and a form's suggestions, and each reports its own state.
      const listResult = await distributionService.listDistributions({
        page: filters.page,
        search: filters.search || undefined,
        status: statusFilter || undefined,
      });
      const [summaryData, packageResult] = await Promise.all([
        distributionService.getDistributionSummary().catch(() => null),
        canWrite
          ? packagingService
              .listPackages({ pageSize: 100, status: 'READY_FOR_DISTRIBUTION' })
              .catch(() => ({ packages: [] }))
          : Promise.resolve({ packages: [] }),
      ]);
      setSummary(summaryData);
      setShipments(listResult.shipments || []);
      setMeta(listResult.meta || null);
      setReleasedPackages((packageResult.packages || []).filter((row) => row.remaining_quantity > 0));
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [canWrite, filters.page, filters.search, statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const loadRetailers = useCallback(async () => {
    if (!canWrite) return;
    setRetailersLoading(true);
    setRetailersError(null);
    try {
      const rows = await distributionService.listRetailers();
      setRetailers(rows || []);
    } catch (caught) {
      // Reported, not swallowed: with no list the form cannot name a receiver, and
      // the reason has to be visible rather than looking like "there are no shops".
      setRetailers([]);
      setRetailersError(normaliseError(caught).message);
    } finally {
      setRetailersLoading(false);
    }
  }, [canWrite]);

  const loadUnassigned = useCallback(async () => {
    if (!canWrite) return;
    try {
      const { shipments } = await distributionService.listUnassignedShipments({ pageSize: 20 });
      setUnassigned(shipments || []);
    } catch {
      // The repair list is a housekeeping view. Its failure is not allowed to hide
      // the shipments themselves, which is why it is loaded separately and the
      // consolidated `error` above is left alone.
      setUnassigned([]);
    }
  }, [canWrite]);

  useEffect(() => {
    loadRetailers();
    loadUnassigned();
  }, [loadRetailers, loadUnassigned]);

  async function runAction(shipment, action, successMessage, payload = {}) {
    setBusyId(shipment.id);
    try {
      await action(shipment.id, payload);
      toast.success(successMessage);
      await load();
    } catch (caught) {
      toast.error(normaliseError(caught).message);
    } finally {
      setBusyId(null);
    }
  }

  async function handleCreate(payload) {
    setSubmitting(true);
    setDialogError(null);
    let created;
    try {
      // The API answers with the shipment it stored, including the retailer it is
      // addressed to — the receipt for the write, not a second copy of it.
      created = await distributionService.createDistribution(payload);
    } catch (caught) {
      // Only a refusal here means the shipment was not created.
      setDialogError(normaliseError(caught).message);
      setSubmitting(false);
      return;
    }

    toast.success(
      DISTRIBUTION_MESSAGES.created,
      created?.retailer_name
        ? `For ${created.retailer_name} · ${created.distribution_code}`
        : created?.distribution_code,
    );
    setCreating(false);
    setSubmitting(false);
    try {
      await Promise.all([load(), loadUnassigned()]);
    } catch {
      toast.warning(
        'Shipment created, but the list could not be refreshed',
        'The shipment is stored. Refresh to see it.',
      );
    }
  }

  /**
   * Name the retailer on a shipment that was recorded without one.
   *
   * This does not invent a receiver: the shop is chosen deliberately from the same
   * directory the create form uses, the change is audited by the server, and the
   * shipment appears in that retailer's inbound list immediately afterwards.
   */
  async function assignRetailer(shipment, retailerId) {
    setBusyId(shipment.id);
    try {
      const updated = await distributionService.assignRetailer(shipment.id, {
        retailer_id: retailerId,
        reason: 'Shipment recorded before a receiver was required.',
      });
      toast.success(
        `${shipment.distribution_code} is now addressed to ${updated.retailer_name || 'the retailer'}`,
      );
      setAssignments((current) => {
        const next = { ...current };
        delete next[shipment.id];
        return next;
      });
      await Promise.all([load(), loadUnassigned()]);
    } catch (caught) {
      toast.error('Could not assign the retailer', normaliseError(caught).message);
    } finally {
      setBusyId(null);
    }
  }

  const copy = VIEW_COPY[view] || VIEW_COPY.overview;

  return (
    <div className="space-y-6">
      {error ? (
        <Alert variant="danger" title={DISTRIBUTION_MESSAGES.loadFailed}>
          {error.message}
        </Alert>
      ) : null}

      {canWrite && unassigned.length ? (
        <Card>
          <CardHeader
            title="Shipments with no retailer named"
            description="Recorded before a receiver was required. They reach no shop until one is named — nothing is guessed."
            icon={<AlertTriangle size={18} />}
          />
          <CardBody className="space-y-3">
            {unassigned.map((shipment) => (
              <div
                key={shipment.id}
                className="flex flex-wrap items-end gap-3 rounded-lg border border-sand-300 bg-sand-50 px-4 py-3"
              >
                <div className="min-w-[16rem] flex-1 text-sm">
                  <p className="font-medium text-ink">{shipment.distribution_code}</p>
                  <p className="text-ink-muted">
                    {shipment.package_code} · {shipment.batch_code} ·{' '}
                    {formatNumber(shipment.quantity)} to {shipment.destination}
                  </p>
                </div>
                <Select
                  label="Assign retailer"
                  name={`retailer-${shipment.id}`}
                  value={assignments[shipment.id] || ''}
                  onChange={(event) =>
                    setAssignments((current) => ({ ...current, [shipment.id]: event.target.value }))
                  }
                  options={retailers.map((row) => ({
                    value: row.id,
                    label: `${row.name}${row.organization ? ` · ${row.organization}` : ''}`,
                  }))}
                  placeholder="Select retailer"
                  className="min-w-[16rem]"
                />
                <Button
                  size="sm"
                  loading={busyId === shipment.id}
                  disabled={!assignments[shipment.id]}
                  onClick={() => assignRetailer(shipment, assignments[shipment.id])}
                  data-testid={`assign-retailer-${shipment.distribution_code}`}
                >
                  Assign retailer
                </Button>
              </div>
            ))}
          </CardBody>
        </Card>
      ) : null}

      {view === 'overview' ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Ready for dispatch"
            value={summary?.ready_for_dispatch ?? '—'}
            helper={`${summary?.total ?? 0} shipment(s) in total`}
            icon={<Boxes size={16} />}
            loading={loading && !summary}
          />
          <StatCard
            label="On the road"
            value={(summary?.dispatched ?? 0) + (summary?.in_transit ?? 0)}
            helper={`${summary?.in_transit ?? 0} in transit`}
            icon={<Truck size={16} />}
            loading={loading && !summary}
          />
          <StatCard
            label="Delivered"
            value={summary?.delivered ?? '—'}
            helper={`${formatNumber(summary?.quantity_delivered)} ${summary?.unit || ''}`.trim()}
            icon={<PackageCheck size={16} />}
            loading={loading && !summary}
            tone="honey"
          />
          <StatCard
            label="Dispatched quantity"
            value={`${formatNumber(summary?.quantity_dispatched)} ${summary?.unit || ''}`.trim()}
            helper="Summed from the shipments, not from the packages they came from."
            icon={<Route size={16} />}
            loading={loading && !summary}
          />
        </div>
      ) : null}

      {view === 'ready' ? (
        <Card>
          <CardHeader
            title="Packages released to you"
            description="Individual packages the packaging unit has released and no shipment has taken yet. Raising a shipment against one of these moves that same package."
            icon={<Boxes size={18} />}
          />
          <CardBody>
            <PackageRegisterTable
              packages={releasedPackages}
              loading={loading}
              showBatch
              canWrite={false}
              enableOpen={false}
              emptyTitle="No packages are waiting for a shipment."
              emptyDescription="Packages appear here once the packaging unit releases them."
            />
          </CardBody>
        </Card>
      ) : null}

      <Card>
        <CardHeader
          title={copy.title}
          description={copy.description}
          icon={<Truck size={18} />}
          action={
            canWrite ? (
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  leftIcon={<RefreshCw size={14} />}
                  onClick={load}
                  loading={loading}
                >
                  Refresh
                </Button>
                <Button
                  size="sm"
                  leftIcon={<Boxes size={14} />}
                  onClick={() => {
                    setDialogError(null);
                    setCreating(true);
                  }}
                >
                  New shipment
                </Button>
              </div>
            ) : (
              <Button variant="secondary" size="sm" leftIcon={<RefreshCw size={14} />} onClick={load}>
                Refresh
              </Button>
            )
          }
        />
        <CardBody className="space-y-4">
          {view !== 'ready' && view !== 'transit' && view !== 'delivered' ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <Input
                label="Search"
                name="search"
                placeholder="Shipment, package or batch code"
                value={filters.search}
                onChange={(event) =>
                  setFilters((current) => ({ ...current, search: event.target.value, page: 1 }))
                }
              />
              <Select
                label="Status"
                name="status"
                options={STATUS_FILTERS}
                value={filters.status}
                onChange={(event) =>
                  setFilters((current) => ({ ...current, status: event.target.value, page: 1 }))
                }
              />
            </div>
          ) : null}

          <ShipmentTable
            shipments={shipments}
            loading={loading}
            meta={meta}
            onPageChange={(page) => setFilters((current) => ({ ...current, page }))}
            canWrite={canWrite}
            busyId={busyId}
            emptyTitle={DISTRIBUTION_MESSAGES.emptyShipments}
            onDispatch={(row) =>
              runAction(
                row,
                (id, body) => distributionService.dispatch(id, body),
                DISTRIBUTION_MESSAGES.dispatched,
              )
            }
            onInTransit={(row) =>
              runAction(
                row,
                (id, body) => distributionService.markInTransit(id, body),
                DISTRIBUTION_MESSAGES.inTransit,
              )
            }
            onDeliver={(row) =>
              runAction(
                row,
                (id, body) => distributionService.deliver(id, body),
                DISTRIBUTION_MESSAGES.delivered,
              )
            }
            onCancel={(row) =>
              runAction(
                row,
                (id, body) => distributionService.cancel(id, body),
                DISTRIBUTION_MESSAGES.cancelled,
              )
            }
          />
        </CardBody>
      </Card>

      <CreateShipmentDialog
        retailers={retailers}
        retailersLoading={retailersLoading}
        retailersError={retailersError}
        onRetryRetailers={loadRetailers}
        open={creating}
        packages={releasedPackages}
        onClose={() => setCreating(false)}
        onSubmit={handleCreate}
        submitting={submitting}
        error={dialogError}
      />
    </div>
  );
}

export default DistributionWorkspace;
