import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { DataTable } from '@/components/common/DataTable';
import { formatDate, formatDateTime } from '@/utils/format';

/**
 * Batches that have reached the laboratory but have no sample booked in yet.
 *
 * This is the seam between the two workspaces: the processor's completed run put
 * the batch at LAB_TESTING, and until a technician (or an administrator) opens a
 * test, the honey is waiting with nobody responsible for it. Showing the row here —
 * with the completed run's code and measured quantities — is what makes that gap
 * visible instead of silent.
 *
 * The batch is never copied: these are the batch's own fields, read through the
 * laboratory's scope.
 */
export function LabBatchQueueTable({
  batches = [],
  loading = false,
  error = null,
  onRetry,
  meta,
  onPageChange,
  canWrite = false,
  onOpenTest = null,
  onAssign = null,
  busyId = null,
  emptyTitle = 'No batch is waiting for a sample.',
  emptyDescription = 'A batch appears here as soon as its processing run is completed.',
}) {
  const columns = [
    {
      key: 'batch_code',
      header: 'Batch',
      render: (row) => (
        <span className="flex flex-col gap-1">
          <span className="font-mono text-sm font-medium text-ink">{row.batch_code}</span>
          {row.collection_code ? (
            <span className="font-mono text-xs text-ink-muted">{row.collection_code}</span>
          ) : null}
        </span>
      ),
    },
    {
      key: 'source',
      header: 'Beekeeper / cluster',
      render: (row) => (
        <span className="flex flex-col gap-1 text-xs">
          <span className="text-sm text-ink-soft">{row.beekeeper_name || 'Beekeeper'}</span>
          <span className="font-mono text-ink-muted">{row.beekeeper_code || '—'}</span>
          <span className="font-mono text-ink-muted">{row.cluster_code || 'No cluster'}</span>
        </span>
      ),
    },
    {
      key: 'processing',
      header: 'Completed processing',
      render: (row) => (
        <span className="flex flex-col gap-1">
          <span className="font-mono text-xs text-ink-soft">{row.processing_code || '—'}</span>
          <span className="text-xs text-ink-muted">{row.processing_type_display || row.processing_type_label || ''}</span>
          {row.input_quantity !== null && row.input_quantity !== undefined ? (
            <span className="text-xs text-ink-soft">
              {Number(row.input_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} →{' '}
              {row.output_quantity === null || row.output_quantity === undefined
                ? '—'
                : Number(row.output_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })}{' '}
              {row.unit_label}
            </span>
          ) : null}
          {row.completion_time ? (
            <span className="text-xs text-ink-muted">Completed {formatDateTime(row.completion_time)}</span>
          ) : null}
        </span>
      ),
    },
    {
      key: 'quantity',
      header: 'Collected',
      align: 'right',
      render: (row) => (
        <span className="flex flex-col gap-1">
          <span className="text-sm text-ink">
            {Number(row.quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} {row.unit_label}
          </span>
          <span className="text-xs text-ink-muted">{formatDate(row.collection_date)}</span>
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Laboratory',
      render: () => (
        <span className="flex flex-col gap-1">
          <Badge variant="warning" size="sm">
            No sample yet
          </Badge>
          <span className="text-xs text-ink-muted">Nobody is responsible for it</span>
        </span>
      ),
    },
    {
      key: 'actions',
      header: 'Actions',
      render: (row) => {
        if (!canWrite) return <span className="text-xs text-ink-muted">Read-only</span>;
        const busy = busyId === row.batch_id;
        return (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" disabled={busy} onClick={() => onOpenTest?.(row)}>
              Open test
            </Button>
            {onAssign ? (
              <Button size="sm" variant="secondary" disabled={busy} onClick={() => onAssign(row)}>
                Assign
              </Button>
            ) : null}
          </div>
        );
      },
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={batches}
      rowKey={(row) => row.batch_id}
      loading={loading}
      error={error}
      onRetry={onRetry}
      meta={meta}
      onPageChange={onPageChange}
      emptyTitle={emptyTitle}
      emptyDescription={emptyDescription}
      caption="Batches awaiting a laboratory sample"
    />
  );
}

export default LabBatchQueueTable;
