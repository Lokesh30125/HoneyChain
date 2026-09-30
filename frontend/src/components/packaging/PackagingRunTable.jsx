import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { DataTable } from '@/components/common/DataTable';
import { PACKAGING_STATUS_META, PACKAGING_TYPE_LABELS } from '@/constants/packaging';
import { formatDate, formatNumber } from '@/utils/format';

/**
 * Packaging runs.
 *
 * A run is one session of packing work against one batch: what went in, how it
 * was packed, and how many packages came out. The actions offered match the state
 * exactly — an open run can be started or cancelled, a started run can be
 * completed or cancelled, and a completed run offers only "Release" and "Open".
 * The server refuses every other transition, so the buttons are a courtesy rather
 * than the rule.
 */
export function PackagingRunTable({
  runs = [],
  loading = false,
  error = null,
  onRetry,
  meta,
  onPageChange,
  canWrite = false,
  onOpen = null,
  onStart = null,
  onComplete = null,
  onCancel = null,
  onRelease = null,
  busyId = null,
  emptyTitle = 'No packaging run has been recorded yet.',
  emptyDescription = 'A run is opened against a batch the laboratory approved.',
}) {
  const columns = [
    {
      key: 'packaging_code',
      header: 'Run',
      render: (row) => (
        <span className="flex flex-col gap-1">
          <button
            type="button"
            className="text-left font-mono text-sm font-medium text-forest-700 underline decoration-honey-400 decoration-2 underline-offset-2"
            onClick={() => onOpen?.(row)}
          >
            {row.packaging_code}
          </button>
          <span className="font-mono text-xs text-ink-muted">{row.batch_code}</span>
          <span className="text-xs text-ink-muted">{formatDate(row.packaging_date)}</span>
        </span>
      ),
    },
    {
      key: 'batch',
      header: 'Batch',
      render: (row) => (
        <span className="flex flex-col gap-1 text-xs">
          <span className="text-sm text-ink-soft">{row.beekeeper_name || 'Beekeeper'}</span>
          {row.collection_code ? (
            <span className="font-mono text-ink-muted">{row.collection_code}</span>
          ) : null}
          {row.packaging_unit_name ? (
            <span className="text-ink-muted">{row.packaging_unit_name}</span>
          ) : null}
        </span>
      ),
    },
    {
      key: 'quantities',
      header: 'Quantities',
      render: (row) => (
        <span className="flex flex-col gap-1 text-xs">
          <span className="text-ink-soft">
            In {formatNumber(row.input_quantity)} {row.unit_label || ''}
          </span>
          <span className="font-medium text-ink">
            Packed {formatNumber(row.packaged_quantity)} {row.unit_label || ''}
          </span>
          <span className="text-ink-muted">
            {row.number_of_packages} × {formatNumber(row.package_size)} {row.unit_label || ''}
          </span>
        </span>
      ),
    },
    {
      key: 'packaging_type',
      header: 'Type',
      render: (row) => (
        <Badge variant="info" size="sm">
          {row.packaging_type_display || row.packaging_type_label || PACKAGING_TYPE_LABELS[row.packaging_type] || row.packaging_type}
        </Badge>
      ),
    },
    {
      key: 'packages',
      header: 'Packages',
      align: 'right',
      render: (row) => (
        <span className="flex flex-col gap-1">
          <span className="text-sm text-ink">{row.package_count ?? 0}</span>
          <span className="text-xs text-ink-muted">created by this run</span>
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (row) => {
        const meta_ = PACKAGING_STATUS_META[row.status] || { label: row.status_label, variant: 'neutral' };
        return (
          <span className="flex flex-col gap-1">
            <Badge variant={meta_.variant} size="sm">
              {row.status_label || meta_.label}
            </Badge>
            {meta_.hint ? <span className="text-xs text-ink-muted">{meta_.hint}</span> : null}
          </span>
        );
      },
    },
    {
      key: 'actions',
      header: 'Actions',
      render: (row) => {
        if (!canWrite) {
          return <span className="text-xs text-ink-muted">Read-only</span>;
        }
        const busy = busyId === row.id;
        return (
          <div className="flex flex-wrap gap-2">
            {row.status === 'PENDING' ? (
              <Button
                size="sm"
                disabled={busy}
                onClick={() => onStart?.(row)}
                data-testid={`start-run-${row.packaging_code}`}
              >
                Start packing
              </Button>
            ) : null}
            {row.status === 'IN_PROGRESS' ? (
              <Button
                size="sm"
                disabled={busy}
                onClick={() => onComplete?.(row)}
                data-testid={`complete-run-${row.packaging_code}`}
              >
                Complete
              </Button>
            ) : null}
            {row.status === 'COMPLETED' && (row.package_count ?? 0) > 0 ? (
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() => onRelease?.(row)}
                data-testid={`release-run-${row.packaging_code}`}
              >
                Release packages
              </Button>
            ) : null}
            {row.status === 'PENDING' || row.status === 'IN_PROGRESS' ? (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => onCancel?.(row)}
                data-testid={`cancel-run-${row.packaging_code}`}
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
      rows={runs}
      rowKey={(row) => row.id}
      loading={loading}
      error={error}
      onRetry={onRetry}
      meta={meta}
      onPageChange={onPageChange}
      emptyTitle={emptyTitle}
      emptyDescription={emptyDescription}
      caption="Packaging runs"
    />
  );
}

export default PackagingRunTable;
