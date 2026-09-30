import { Link } from 'react-router-dom';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { DataTable } from '@/components/common/DataTable';
import { PROCESSING_MESSAGES, PROCESSING_STATUS_META } from '@/constants/processing';
import { formatDate, formatDateTime } from '@/utils/format';

/**
 * The list of processing runs.
 *
 * The input/output columns show what was measured and leave the difference to the
 * server's own arithmetic — an open run has no figures at all rather than zeros,
 * because a run that has not been weighed did not weigh nothing.
 *
 * The table is read-only unless the caller hands it something to do. ``onAssign``
 * adds an Actions column that appears only on the rows the server says this caller
 * may allocate (``row.can_assign``), which is how an administrator hands a batch to
 * a processor from the platform-wide list — the same dialog the processor's own
 * queues use, rather than a second way of doing it.
 */
export function ProcessingRunTable({
  runs = [],
  loading = false,
  error = null,
  onRetry,
  meta,
  onPageChange,
  detailPath = null,
  onAssign = null,
  busyId = null,
}) {
  const columns = [
    {
      key: 'processing_code',
      header: 'Run',
      render: (row) =>
        detailPath ? (
          <Link className="font-mono text-sm font-medium text-forest-700 hover:underline" to={`${detailPath}/${row.id}`}>
            {row.processing_code}
          </Link>
        ) : (
          <span className="font-mono text-sm font-medium text-ink">{row.processing_code}</span>
        ),
    },
    {
      key: 'batch_code',
      header: 'Batch',
      render: (row) => <span className="font-mono text-sm text-ink-soft">{row.batch_code}</span>,
    },
    { key: 'processing_type_label', header: 'Type', render: (row) => row.processing_type_display || row.processing_type_label || row.processing_type },
    {
      key: 'processing_unit',
      header: 'Unit',
      render: (row) =>
        row.processing_unit_name ? (
          <span className="text-sm text-ink-soft">
            {row.processing_unit_name}
            {row.processing_unit_code ? <span className="ml-2 text-xs text-ink-muted">{row.processing_unit_code}</span> : null}
          </span>
        ) : (
          <span className="text-xs text-ink-muted">Not recorded</span>
        ),
    },
    {
      key: 'quantities',
      header: 'Measured in → out',
      align: 'right',
      render: (row) => {
        const unit = row.unit_label || '';
        if (row.input_quantity === null || row.input_quantity === undefined) {
          return <span className="text-xs text-ink-muted">Not recorded</span>;
        }
        const out =
          row.output_quantity === null || row.output_quantity === undefined
            ? '—'
            : Number(row.output_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 });
        return (
          <span className="text-sm text-ink">
            {Number(row.input_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} → {out} {unit}
            {row.loss_quantity !== null && row.loss_quantity !== undefined ? (
              <span className="ml-2 text-xs text-ink-muted">
                ({Number(row.loss_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} {unit} less)
              </span>
            ) : null}
          </span>
        );
      },
    },
    { key: 'processing_date', header: 'Date', render: (row) => formatDate(row.processing_date) },
    {
      key: 'status',
      header: 'Status',
      render: (row) => {
        const meta_ = PROCESSING_STATUS_META[row.status] || PROCESSING_STATUS_META.PENDING;
        return (
          <span className="flex flex-col gap-1">
            <Badge variant={meta_.variant} size="sm">
              {row.status_label || meta_.label}
            </Badge>
            {row.completion_time ? (
              <span className="text-xs text-ink-muted">{formatDateTime(row.completion_time)}</span>
            ) : null}
          </span>
        );
      },
    },
    {
      key: 'cluster',
      header: 'Cluster',
      render: (row) =>
        row.cluster_code ? (
          <span className="text-xs text-ink-soft">{row.cluster_code}</span>
        ) : (
          <span className="text-xs text-ink-muted">—</span>
        ),
    },
  ];

  if (onAssign) {
    columns.push({
      key: 'actions',
      header: 'Actions',
      render: (row) =>
        // The server decides: an unallocated open run is the administrator's to
        // allocate, a closed one is history and carries no button at all.
        row.can_assign ? (
          <Button
            size="sm"
            variant="secondary"
            disabled={busyId === row.id}
            onClick={() => onAssign(row)}
            data-testid={`assign-run-${row.processing_code}`}
          >
            Assign
          </Button>
        ) : null,
    });
  }

  return (
    <DataTable
      columns={columns}
      rows={runs}
      loading={loading}
      error={error}
      onRetry={onRetry}
      meta={meta}
      onPageChange={onPageChange}
      emptyTitle={PROCESSING_MESSAGES.runsEmpty}
      emptyDescription="A run is opened against a collected batch, then started and completed with the quantities actually measured."
      caption="Processing runs"
    />
  );
}

export default ProcessingRunTable;
