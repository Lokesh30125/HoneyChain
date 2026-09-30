import { Link } from 'react-router-dom';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { DataTable } from '@/components/common/DataTable';
import { PROCESSING_MESSAGES } from '@/constants/processing';
import { formatDate } from '@/utils/format';

/**
 * The processing worklist.
 *
 * Every row is a batch at COLLECTED in the reader's scope, exactly as the API
 * returned it — no quantities are estimated and no stage is pre-filled. The action
 * column is rendered only for a caller who may open a run, so a KVIC officer sees
 * the same table with nothing to press.
 */
export function AwaitingProcessingTable({
  batches = [],
  loading = false,
  error = null,
  onRetry,
  meta,
  onPageChange,
  onOpenRun = null,
  actionLabel = 'Start processing',
}) {
  const columns = [
    {
      key: 'batch_code',
      header: 'Batch',
      render: (row) =>
        row.detail_path ? (
          <Link className="font-medium text-forest-700 hover:underline" to={row.detail_path}>
            {row.batch_code}
          </Link>
        ) : (
          <span className="font-mono text-sm font-medium text-ink">{row.batch_code}</span>
        ),
    },
    {
      key: 'collection_code',
      header: 'From collection',
      render: (row) => <span className="text-sm text-ink-soft">{row.collection_code || '—'}</span>,
    },
    { key: 'collection_date', header: 'Harvest date', render: (row) => formatDate(row.collection_date) },
    {
      key: 'quantity',
      header: 'Quantity',
      align: 'right',
      render: (row) =>
        `${Number(row.quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${row.unit_label || ''}`.trim(),
    },
    {
      key: 'sources',
      header: 'Hives',
      align: 'right',
      render: (row) => row.source_hive_count ?? '—',
    },
    {
      key: 'beekeeper',
      header: 'Beekeeper',
      render: (row) => (
        <span className="text-sm text-ink-soft">
          {row.beekeeper_name || row.beekeeper_code || '—'}
          {row.cluster_code ? <span className="ml-2 text-xs text-ink-muted">{row.cluster_code}</span> : null}
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: () => (
        <Badge variant="info" size="sm">
          Collected
        </Badge>
      ),
    },
  ];

  if (onOpenRun) {
    columns.push({
      key: 'actions',
      header: '',
      align: 'right',
      render: (row) => (
        <Button
          size="sm"
          variant="secondary"
          onClick={() => onOpenRun(row)}
          data-testid={`open-run-${row.batch_code}`}
        >
          {actionLabel}
        </Button>
      ),
    });
  }

  return (
    <DataTable
      columns={columns}
      rows={batches}
      loading={loading}
      error={error}
      onRetry={onRetry}
      meta={meta}
      onPageChange={onPageChange}
      emptyTitle={PROCESSING_MESSAGES.awaitingEmpty}
      emptyDescription={PROCESSING_MESSAGES.awaitingEmptyDescription}
      caption="Batches awaiting processing"
    />
  );
}

export default AwaitingProcessingTable;
