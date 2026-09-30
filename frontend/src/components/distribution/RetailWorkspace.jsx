import { useCallback, useEffect, useState } from 'react';
import { Inbox, PackageCheck, RefreshCw, Store } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { StatCard } from '@/components/common/StatCard';
import { PackageRegisterTable } from '@/components/packaging/PackageRegisterTable';
import { ShipmentTable } from '@/components/distribution/ShipmentTable';
import { DISTRIBUTION_MESSAGES, RETAILER_VIEW_COPY } from '@/constants/distribution';
import { ROLES } from '@/constants/roles';
import { useToast } from '@/hooks/useToast';
import * as distributionService from '@/services/distributionService';
import { normaliseError } from '@/utils/errors';
import { formatNumber } from '@/utils/format';

/**
 * The retailer's workspace.
 *
 * Two lists, and the difference between them is a fact rather than a filter: the
 * shipments addressed to this shop that have not been received yet, and the
 * packages it has confirmed receiving. Confirming a receipt is the retailer's own
 * record — the sender cannot write it — and it is what eventually completes the
 * batch, so the button is offered only where a receipt is actually missing.
 *
 * Everything here is read-only otherwise: a shop cannot change a package, a batch,
 * a hive or anything that happened upstream of the delivery.
 */

const VIEW_COPY = {
  overview: RETAILER_VIEW_COPY.overview,
  inbound: RETAILER_VIEW_COPY.inbound,
  received: RETAILER_VIEW_COPY.received,
  history: RETAILER_VIEW_COPY.history,
};

export function RetailWorkspace({ role = ROLES.RETAILER, view = 'overview' }) {
  const toast = useToast();
  const [summary, setSummary] = useState(null);
  const [shipments, setShipments] = useState([]);
  const [meta, setMeta] = useState(null);
  const [packages, setPackages] = useState([]);
  const [packagesMeta, setPackagesMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [packagesError, setPackagesError] = useState(null);
  // The two lists page independently: turning a page of shipments must not
  // turn the page of received packages under it.
  const [filters, setFilters] = useState({ search: '', page: 1, packagesPage: 1 });

  const showPackages = view === 'overview' || view === 'received';

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setPackagesError(null);
    try {
      // The two lists are what this page is for, so neither is swallowed: a failed
      // request says so rather than showing an empty shop. Only the counters may
      // degrade, and each reports its own state where it is drawn.
      const shipmentResult = await distributionService.listRetailerShipments({
        page: filters.page,
        search: filters.search || undefined,
        awaitingReceipt: view === 'inbound',
      });
      const [summaryData, packageResult] = await Promise.all([
        distributionService.getRetailerSummary().catch(() => null),
        showPackages
          ? distributionService
              .listRetailerPackages({
                page: filters.packagesPage,
                search: filters.search || undefined,
              })
              .catch(() => null)
          : Promise.resolve(null),
      ]);
      setSummary(summaryData);
      setShipments(shipmentResult.shipments || []);
      setMeta(shipmentResult.meta || null);
      if (packageResult === null && showPackages) {
        // The received list failed while the inbound list succeeded: say so on that
        // list, and do not let the inbound shipments disappear with it.
        setPackagesError('Unable to load the received packages.');
      }
      setPackages(packageResult?.packages || []);
      setPackagesMeta(packageResult?.meta || null);
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [filters.page, filters.packagesPage, filters.search, showPackages, view]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleReceive(shipment) {
    setBusyId(shipment.id);
    try {
      await distributionService.receiveShipment(shipment.id, {});
      toast.success(DISTRIBUTION_MESSAGES.received);
      await load();
    } catch (caught) {
      toast.error(normaliseError(caught).message);
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
      {packagesError ? <Alert variant="warning">{packagesError}</Alert> : null}

      {view === 'overview' ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <StatCard
            label="On the way to you"
            value={summary?.inbound ?? '—'}
            helper="Dispatched or in transit, not yet confirmed."
            icon={<Inbox size={16} />}
            loading={loading && !summary}
          />
          <StatCard
            label="Received"
            value={summary?.delivered ?? '—'}
            helper={`${summary?.packages_received ?? 0} package(s) confirmed`}
            icon={<PackageCheck size={16} />}
            loading={loading && !summary}
            tone="honey"
          />
          <StatCard
            label="Quantity received"
            value={`${formatNumber(summary?.quantity_received)} ${summary?.unit || ''}`.trim()}
            helper="Read from the packages you confirmed."
            icon={<Store size={16} />}
            loading={loading && !summary}
          />
        </div>
      ) : null}

      <Card>
        <CardHeader
          title={copy.title}
          description={copy.description}
          icon={<Store size={18} />}
          action={
            <Button
              variant="secondary"
              size="sm"
              leftIcon={<RefreshCw size={14} />}
              onClick={load}
              loading={loading}
            >
              Refresh
            </Button>
          }
        />
        <CardBody className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              label="Search"
              name="search"
              placeholder="Shipment, package or batch code"
              value={filters.search}
              onChange={(event) =>
                setFilters((current) => ({
                  ...current,
                  search: event.target.value,
                  page: 1,
                  packagesPage: 1,
                }))
              }
            />
          </div>
          <ShipmentTable
            shipments={shipments}
            loading={loading}
            meta={meta}
            onPageChange={(page) => setFilters((current) => ({ ...current, page }))}
            canWrite={false}
            canReceive
            busyId={busyId}
            emptyTitle={
              view === 'inbound' ? DISTRIBUTION_MESSAGES.emptyInbound : DISTRIBUTION_MESSAGES.emptyShipments
            }
            onReceive={handleReceive}
          />
        </CardBody>
      </Card>

      {showPackages ? (
        <Card>
          <CardHeader
            title="Packages you have received"
            description="Each package with the batch it carries and where it came from. Read-only: nothing a shop can do changes the record."
          />
          <CardBody>
            <PackageRegisterTable
              packages={packages}
              loading={loading}
              meta={packagesMeta}
              onPageChange={(page) => setFilters((current) => ({ ...current, packagesPage: page }))}
              canWrite={false}
              emptyTitle={DISTRIBUTION_MESSAGES.emptyReceived}
            />
          </CardBody>
        </Card>
      ) : null}
    </div>
  );
}

export default RetailWorkspace;
