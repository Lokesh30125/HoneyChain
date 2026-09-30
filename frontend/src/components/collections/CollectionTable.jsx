import { Link } from 'react-router-dom';

import { Badge } from '@/components/ui/Badge';
import { DataTable } from '@/components/common/DataTable';
import { COLLECTION_MESSAGES, COLLECTION_STATUS_META, unitLabel } from '@/constants/collection';
import { formatDate } from '@/utils/format';

/**
 * The harvest list.
 *
 * Source hives are shown as their codes, never as "3 hives": the whole point of
 * the per-hive rows is that a reader can see *which* hives contributed. A
 * completed harvest links to the batch it produced; an open one says it has none
 * yet rather than leaving the cell blank.
 */

function StatusCell({ status }) {
  const meta = COLLECTION_STATUS_META[status] || { label: status, variant: 'neutral', hint: '' };
  return (
    <span title={meta.hint}>
      <Badge variant={meta.variant}>{meta.label}</Badge>
    </span>
  );
}

function HiveCodes({ codes = [], count }) {
  if (!codes.length) return <span className="text-ink-muted">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {codes.slice(0, 3).map((code) => (
        <Badge key={code} variant="neutral" size="sm">
          {code}
        </Badge>
      ))}
      {count > 3 || codes.length > 3 ? (
        <span className="text-xs text-ink-muted">+{Math.max(count, codes.length) - 3} more</span>
      ) : null}
    </span>
  );
}

export function CollectionTable({ collections = [], loading = false, error = null, onRetry, meta, onPageChange, detailPath }) {
  const columns = [
    {
      key: 'collection_code',
      header: 'Collection',
      render: (row) =>
        detailPath ? (
          <Link className="font-medium text-forest-700 hover:underline" to={`${detailPath}/${row.id}`}>
            {row.collection_code}
          </Link>
        ) : (
          <span className="font-medium text-ink">{row.collection_code}</span>
        ),
    },
    { key: 'collection_date', header: 'Date', render: (row) => formatDate(row.collection_date) },
    {
      key: 'quantity',
      header: 'Harvested',
      align: 'right',
      render: (row) => `${Number(row.total_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${unitLabel(row.unit)}`,
    },
    { key: 'hives', header: 'Source hives', render: (row) => <HiveCodes codes={row.source_hive_codes} count={row.source_hive_count} /> },
    { key: 'status', header: 'Status', render: (row) => <StatusCell status={row.status} /> },
    {
      key: 'cluster',
      header: 'Cluster',
      render: (row) =>
        row.cluster_code ? (
          <span className="text-sm text-ink-soft">{row.cluster_name || row.cluster_code}</span>
        ) : (
          <span className="text-xs text-ink-muted">No cluster</span>
        ),
    },
    {
      key: 'batch',
      header: 'Batch',
      render: (row) =>
        row.batch_code ? (
          <Badge variant="success" size="sm">
            {row.batch_code}
          </Badge>
        ) : (
          <span className="text-xs text-ink-muted">
            {row.status === 'CANCELLED' ? 'Not applicable' : 'Not created yet'}
          </span>
        ),
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={collections}
      loading={loading}
      error={error}
      onRetry={onRetry}
      meta={meta}
      onPageChange={onPageChange}
      emptyTitle={COLLECTION_MESSAGES.emptyCollections}
      emptyDescription="Record a harvest to start the traceability chain — it becomes a honey batch when you complete it."
      caption="Collections"
    />
  );
}

export default CollectionTable;
