import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { DataTable } from '@/components/common/DataTable';
import { PACKAGE_STATUS_META } from '@/constants/packaging';
import { formatDate, formatNumber } from '@/utils/format';

/**
 * The package register: one row per individual package.
 *
 * Each package carries its own stable code (`HC-PKG-…`), its own size and the run
 * that made it. The code is the identity a later QR label will point at, so nothing
 * on this screen rewrites it, and the register is the same list the distributor,
 * the retailer and the beekeeper read — filtered, never copied.
 */
export function PackageRegisterTable({
  packages = [],
  loading = false,
  error = null,
  onRetry,
  meta,
  onPageChange,
  canWrite = false,
  onOpen = null,
  onRelease = null,
  busyId = null,
  showBatch = true,
  // A screen that has no package detail to open (the distributor's dispatch list,
  // for one) turns the bare code into plain text rather than a control that leads
  // nowhere.
  enableOpen = true,
  emptyTitle = 'No packages have been created yet.',
  emptyDescription = 'Packages are created when a packaging run is completed.',
}) {
  const columns = [
    {
      key: 'package_code',
      header: 'Package',
      render: (row) => (
        <span className="flex flex-col gap-1">
          {enableOpen ? (
            <button
              type="button"
              className="text-left font-mono text-sm font-medium text-forest-700 underline decoration-honey-400 decoration-2 underline-offset-2"
              onClick={() => onOpen?.(row)}
            >
              {row.package_code}
            </button>
          ) : (
            <span className="font-mono text-sm font-medium text-ink">{row.package_code}</span>
          )}
          <span className="text-xs text-ink-muted">
            {formatNumber(row.package_size)} {row.unit_label || ''} ·{' '}
            {row.packaging_type_display || row.packaging_type_label || row.packaging_type}
          </span>
          <span className="text-xs text-ink-muted">{formatDate(row.packaging_date)}</span>
        </span>
      ),
    },
  ];

  if (showBatch) {
    columns.push({
      key: 'batch_code',
      header: 'Batch',
      render: (row) => (
        <span className="flex flex-col gap-1 text-xs">
          <span className="font-mono text-ink-soft">{row.batch_code}</span>
          {row.collection_code ? (
            <span className="font-mono text-ink-muted">{row.collection_code}</span>
          ) : null}
          {row.beekeeper_name ? (
            <span className="text-ink-muted">{row.beekeeper_name}</span>
          ) : null}
        </span>
      ),
    });
  }

  columns.push(
    {
      key: 'run',
      header: 'Packaging run',
      render: (row) => (
        <span className="flex flex-col gap-1 text-xs">
          <span className="font-mono text-ink-soft">{row.packaging_code}</span>
          {row.packaging_unit_name ? (
            <span className="text-ink-muted">{row.packaging_unit_name}</span>
          ) : null}
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
          {Number(row.dispatched_quantity || 0) > 0 ? (
            <span className="text-xs text-ink-muted">
              Shipped {formatNumber(row.dispatched_quantity)} · left{' '}
              {formatNumber(row.remaining_quantity)}
            </span>
          ) : (
            <span className="text-xs text-ink-muted">{row.shipment_count || 0} shipment(s)</span>
          )}
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (row) => {
        const statusMeta = PACKAGE_STATUS_META[row.status] || {
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
        const canRelease = canWrite && row.status === 'CREATED' && row.can_release;
        if (!enableOpen && !canRelease) {
          return <span className="text-xs text-ink-muted">{row.status === 'DELIVERED' ? 'Received' : 'With distribution'}</span>;
        }
        return (
          <div className="flex flex-wrap gap-2">
            {enableOpen ? (
              <Button size="sm" variant="ghost" onClick={() => onOpen?.(row)}>
                Open
              </Button>
            ) : null}
            {canRelease ? (
              <Button
                size="sm"
                variant="secondary"
                disabled={busyId === row.id}
                onClick={() => onRelease?.(row)}
                data-testid={`release-package-${row.package_code}`}
              >
                Release
              </Button>
            ) : null}
            {row.status !== 'CREATED' && row.status !== 'CANCELLED' ? (
              <span className="self-center text-xs text-ink-muted">
                {row.status === 'DELIVERED' ? 'Received' : 'With distribution'}
              </span>
            ) : null}
          </div>
        );
      },
    },
  );

  return (
    <DataTable
      columns={columns}
      rows={packages}
      rowKey={(row) => row.id}
      loading={loading}
      error={error}
      onRetry={onRetry}
      meta={meta}
      onPageChange={onPageChange}
      emptyTitle={emptyTitle}
      emptyDescription={emptyDescription}
      caption="Individual packages"
    />
  );
}

export default PackageRegisterTable;
