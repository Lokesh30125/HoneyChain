import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { DataTable } from '@/components/common/DataTable';
import { DISTRIBUTION_STATUS_META } from '@/constants/distribution';
import { formatDate, formatDateTime, formatNumber } from '@/utils/format';

/**
 * Shipments, as the distributor works them.
 *
 * A row is one consignment of one package to one destination. The actions offered
 * follow the journey exactly and never jump a step: dispatch is offered only
 * before departure, in-transit and delivery only after it, and cancellation only
 * while the honey has not actually arrived. The server enforces the same order, so
 * a delivery cannot be recorded before the dispatch exists even if a button were
 * somehow reached.
 *
 * The receiving shop gets one action of its own — confirming receipt — because a
 * receipt is a record of what arrived at the counter, not something the sender can
 * write on the receiver's behalf.
 */
export function ShipmentTable({
  shipments = [],
  loading = false,
  error = null,
  onRetry,
  meta,
  onPageChange,
  canWrite = false,
  onOpen = null,
  onDispatch = null,
  onInTransit = null,
  onDeliver = null,
  onCancel = null,
  onReceive = null,
  canReceive = false,
  busyId = null,
  emptyTitle = 'No shipments have been recorded yet.',
  emptyDescription = 'A shipment is raised against a package the packaging unit released.',
}) {
  const columns = [
    {
      key: 'distribution_code',
      header: 'Shipment',
      render: (row) => (
        <span className="flex flex-col gap-1">
          <button
            type="button"
            className="text-left font-mono text-sm font-medium text-forest-700 underline decoration-honey-400 decoration-2 underline-offset-2"
            onClick={() => onOpen?.(row)}
          >
            {row.distribution_code}
          </button>
          <span className="font-mono text-xs text-ink-muted">{row.package_code}</span>
          <span className="font-mono text-xs text-ink-muted">{row.batch_code}</span>
        </span>
      ),
    },
    {
      key: 'destination',
      header: 'Destination',
      render: (row) => (
        <span className="flex flex-col gap-1 text-xs">
          <span className="text-sm text-ink-soft">{row.destination}</span>
          {row.destination_district ? (
            <span className="text-ink-muted">{row.destination_district}</span>
          ) : null}
          {row.retailer_name ? (
            <span className="text-ink-muted">To {row.retailer_name}</span>
          ) : (
            <span className="text-ink-muted">No retailer named</span>
          )}
        </span>
      ),
    },
    {
      key: 'quantity',
      header: 'Quantity',
      align: 'right',
      render: (row) => (
        <span className="flex flex-col gap-1">
          <span className="text-sm text-ink">
            {formatNumber(row.quantity)} {row.unit_label || ''}
          </span>
          {row.package_quantity ? (
            <span className="text-xs text-ink-muted">
              of {formatNumber(row.package_quantity)} in the package
            </span>
          ) : null}
        </span>
      ),
    },
    {
      key: 'journey',
      header: 'Journey',
      render: (row) => (
        <span className="flex flex-col gap-1 text-xs">
          {row.dispatched_at ? (
            <span className="text-ink-soft">Dispatched {formatDateTime(row.dispatched_at)}</span>
          ) : (
            <span className="text-ink-muted">Not dispatched yet</span>
          )}
          {row.delivered_at ? (
            <span className="text-ink-soft">Delivered {formatDateTime(row.delivered_at)}</span>
          ) : row.expected_delivery_date ? (
            <span className="text-ink-muted">Expected {formatDate(row.expected_delivery_date)}</span>
          ) : null}
          {row.received_by_name ? (
            <span className="text-ink-muted">Received by {row.received_by_name}</span>
          ) : null}
          {row.carrier ? <span className="text-ink-muted">Carrier: {row.carrier}</span> : null}
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (row) => {
        const statusMeta = DISTRIBUTION_STATUS_META[row.status] || {
          label: row.status_label,
          variant: 'neutral',
        };
        return (
          <span className="flex flex-col gap-1">
            <Badge variant={statusMeta.variant} size="sm">
              {row.status_label || statusMeta.label}
            </Badge>
            {statusMeta.hint ? (
              <span className="text-xs text-ink-muted">{statusMeta.hint}</span>
            ) : null}
          </span>
        );
      },
    },
    {
      key: 'actions',
      header: 'Actions',
      render: (row) => {
        if (!canWrite) {
          // Receivable once it has left the sender and until this shop confirms it
          // — including after the carrier marked it delivered. The server refuses
          // a receipt for a shipment that was never dispatched.
          const receivable =
            canReceive &&
            !row.received_at &&
            ['DISPATCHED', 'IN_TRANSIT', 'DELIVERED'].includes(row.status);
          if (!receivable) {
            return <span className="text-xs text-ink-muted">Read-only</span>;
          }
          return (
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                disabled={busyId === row.id}
                onClick={() => onReceive?.(row)}
                data-testid={`receive-${row.distribution_code}`}
              >
                Confirm receipt
              </Button>
              <Button size="sm" variant="ghost" onClick={() => onOpen?.(row)}>
                Open
              </Button>
            </div>
          );
        }
        const busy = busyId === row.id;
        return (
          <div className="flex flex-wrap gap-2">
            {row.status === 'READY_FOR_DISPATCH' ? (
              <Button
                size="sm"
                disabled={busy}
                onClick={() => onDispatch?.(row)}
                data-testid={`dispatch-${row.distribution_code}`}
              >
                Dispatch
              </Button>
            ) : null}
            {row.status === 'DISPATCHED' ? (
              <Button
                size="sm"
                disabled={busy}
                onClick={() => onInTransit?.(row)}
                data-testid={`in-transit-${row.distribution_code}`}
              >
                In transit
              </Button>
            ) : null}
            {row.status === 'IN_TRANSIT' ? (
              <Button
                size="sm"
                disabled={busy}
                onClick={() => onDeliver?.(row)}
                data-testid={`deliver-${row.distribution_code}`}
              >
                Record delivery
              </Button>
            ) : null}
            {row.status === 'READY_FOR_DISPATCH' || row.status === 'DISPATCHED' ? (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => onCancel?.(row)}
                data-testid={`cancel-shipment-${row.distribution_code}`}
              >
                Cancel
              </Button>
            ) : null}
            <Button size="sm" variant="ghost" onClick={() => onOpen?.(row)}>
              Open
            </Button>
          </div>
        );
      },
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={shipments}
      rowKey={(row) => row.id}
      loading={loading}
      error={error}
      onRetry={onRetry}
      meta={meta}
      onPageChange={onPageChange}
      emptyTitle={emptyTitle}
      emptyDescription={emptyDescription}
      caption="Shipments"
    />
  );
}

export default ShipmentTable;
