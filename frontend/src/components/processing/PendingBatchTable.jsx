import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { DataTable } from '@/components/common/DataTable';
import { formatDate } from '@/utils/format';

/**
 * The processor's pending-batch list.
 *
 * A row here is a *batch* — the shared record the beekeeper, the KVIC officer and
 * the laboratory also read — shown in the batch's own vocabulary: its code, whose
 * honey it is, which cluster it belongs to, how much was collected and when. The
 * processing column is the allocation state of the batch's run, or a plain "No run
 * opened yet", which is what a batch with nobody working on it actually looks like.
 *
 * Nothing is created by this table. "Take on" and "Assign" send an allocation to a
 * processor the server validates; the batch's quantity is never editable here,
 * because the harvest is what it is.
 */
export function PendingBatchTable({
  batches = [],
  loading = false,
  error = null,
  onRetry,
  meta,
  onPageChange,
  canWrite = false,
  onTakeOn = null,
  onAssign = null,
  onOpenRun = null,
  busyId = null,
  emptyTitle = 'No batches awaiting processing.',
  emptyDescription = 'A batch appears here the moment a harvest is completed. Nothing to process right now.',
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
      key: 'beekeeper',
      header: 'Beekeeper',
      render: (row) => (
        <span className="flex flex-col gap-1 text-xs">
          <span className="text-sm text-ink-soft">{row.beekeeper_name || 'Beekeeper'}</span>
          <span className="font-mono text-ink-muted">{row.beekeeper_code || '—'}</span>
        </span>
      ),
    },
    {
      key: 'cluster',
      header: 'KVIC cluster',
      render: (row) =>
        row.cluster_code ? (
          <span className="flex flex-col gap-1 text-xs">
            <span className="text-sm text-ink-soft">{row.cluster_name || 'Cluster'}</span>
            <span className="font-mono text-ink-muted">{row.cluster_code}</span>
          </span>
        ) : (
          <span className="text-xs text-ink-muted">Not in a cluster</span>
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
      key: 'status_label',
      header: 'Batch status',
      render: (row) => (
        <span className="flex flex-col gap-1">
          <Badge variant="warning" size="sm">
            {row.status_label || row.status}
          </Badge>
          <span className="text-xs text-ink-muted">Collected, not yet processed</span>
        </span>
      ),
    },
    {
      key: 'processing',
      header: 'Processing',
      render: (row) => {
        if (!row.open_processing_id) {
          return (
            <span className="flex flex-col gap-1">
              <span className="text-xs text-ink-muted">No run opened yet</span>
              {row.source_hive_count ? (
                <span className="text-xs text-ink-muted">{row.source_hive_count} source hive(s)</span>
              ) : null}
            </span>
          );
        }
        const accepted = row.assignment_status === 'ACCEPTED';
        return (
          <span className="flex flex-col gap-1">
            <span className="font-mono text-xs text-ink-soft">{row.open_processing_code}</span>
            <span className="text-xs text-ink-soft">{row.open_processing_status_label}</span>
            {row.processor_name ? (
              <span className="text-xs text-ink-muted">
                {row.processor_name}
                {accepted ? ' · accepted' : ' · allocated'}
              </span>
            ) : (
              <Badge variant="warning" size="sm">
                Unassigned
              </Badge>
            )}
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
        const busy = busyId === row.batch_id;
        return (
          <div className="flex flex-wrap gap-2">
            {row.open_processing_id ? (
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() => onOpenRun?.(row)}
                data-testid={`open-run-${row.batch_code}`}
              >
                Open run
              </Button>
            ) : (
              <Button
                size="sm"
                disabled={busy}
                onClick={() => onTakeOn?.(row)}
                data-testid={`take-on-${row.batch_code}`}
              >
                Take on
              </Button>
            )}
            {onAssign ? (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => onAssign(row)}
                data-testid={`assign-batch-${row.batch_code}`}
              >
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
      caption="Batches awaiting processing"
    />
  );
}

export default PendingBatchTable;
