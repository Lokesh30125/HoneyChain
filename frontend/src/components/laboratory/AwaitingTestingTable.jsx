import { Link } from 'react-router-dom';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { DataTable } from '@/components/common/DataTable';
import { LAB_MESSAGES } from '@/constants/laboratory';
import { formatDate } from '@/utils/format';

/**
 * The laboratory worklist.
 *
 * A row is a batch at LAB_TESTING in the reader's scope, with the completed
 * processing run that produced the honey the sample is taken from. If a test is
 * already open against the batch, the row offers to continue it rather than
 * opening a second one — a retest is a deliberate act with a reason, not
 * something a second click can create by accident.
 */
export function AwaitingTestingTable({
  basePath = '/laboratory',
  rows = [],
  loading = false,
  error = null,
  onRetry,
  meta,
  onPageChange,
  onOpenTest = null,
  detailPath = null,
  actionLabel = 'Open a test',
}) {
  const columns = [
    {
      key: 'batch_code',
      header: 'Batch',
      render: (row) =>
        detailPath ? (
          <Link className="font-mono text-sm font-medium text-forest-700 hover:underline" to={`${detailPath}/${row.batch_id}`}>
            {row.batch_code}
          </Link>
        ) : (
          <span className="font-mono text-sm font-medium text-ink">{row.batch_code}</span>
        ),
    },
    {
      key: 'processing_code',
      header: 'Processing run',
      render: (row) =>
        row.processing_code ? (
          <span className="font-mono text-xs text-ink-soft">{row.processing_code}</span>
        ) : (
          <span className="text-xs text-ink-muted">None recorded</span>
        ),
    },
    {
      key: 'output_quantity',
      header: 'Processed output',
      align: 'right',
      render: (row) =>
        row.output_quantity === null || row.output_quantity === undefined
          ? '—'
          : `${Number(row.output_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${row.unit_label || ''}`.trim(),
    },
    {
      key: 'quantity',
      header: 'Batch quantity',
      align: 'right',
      render: (row) =>
        `${Number(row.quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${row.unit_label || ''}`.trim(),
    },
    { key: 'collection_date', header: 'Harvest date', render: (row) => formatDate(row.collection_date) },
    {
      key: 'beekeeper',
      header: 'Beekeeper',
      render: (row) => (
        <span className="text-sm text-ink-soft">
          {row.beekeeper_code || '—'}
          {row.cluster_code ? <span className="ml-2 text-xs text-ink-muted">{row.cluster_code}</span> : null}
        </span>
      ),
    },
    {
      key: 'open_test',
      header: 'Open test',
      render: (row) =>
        row.open_test_id ? (
          <Badge variant="pending" size="sm">
            {row.open_test_code}
          </Badge>
        ) : (
          <span className="text-xs text-ink-muted">
            {row.test_count ? `${row.test_count} earlier test(s)` : 'None'}
          </span>
        ),
    },
  ];

  if (onOpenTest) {
    columns.push({
      key: 'actions',
      header: '',
      align: 'right',
      render: (row) =>
        row.open_test_id ? (
          <Button size="sm" variant="secondary" to={`${basePath}/tests/${row.open_test_id}`}>
            Continue {row.open_test_code}
          </Button>
        ) : (
          <Button size="sm" variant="secondary" onClick={() => onOpenTest(row)} data-testid={`open-test-${row.batch_code}`}>
            {actionLabel}
          </Button>
        ),
    });
  }

  return (
    <DataTable
      columns={columns}
      rows={rows}
      loading={loading}
      error={error}
      onRetry={onRetry}
      meta={meta}
      onPageChange={onPageChange}
      emptyTitle={LAB_MESSAGES.awaitingEmpty}
      emptyDescription={LAB_MESSAGES.awaitingEmptyDescription}
      caption="Batches awaiting laboratory testing"
    />
  );
}

export default AwaitingTestingTable;
