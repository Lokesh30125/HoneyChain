import { Link } from 'react-router-dom';

import { Badge } from '@/components/ui/Badge';
import { DataTable } from '@/components/common/DataTable';
import { BATCH_STATUS_META, COLLECTION_MESSAGES, unitLabel } from '@/constants/collection';
import { formatDate } from '@/utils/format';

/**
 * The batch list.
 *
 * Status is shown as it is stored and toned by what it means: a batch that passed
 * its laboratory test and one that failed it never look alike. No row will read
 * "Packaged" here, because nothing in this build can set that.
 */
export function BatchTable({ batches = [], loading = false, error = null, onRetry, meta, onPageChange, detailPath }) {
  const columns = [
    {
      key: 'batch_code',
      header: 'Batch',
      render: (row) =>
        detailPath ? (
          <Link className="font-medium text-forest-700 hover:underline" to={`${detailPath}/${row.id}`}>
            {row.batch_code}
          </Link>
        ) : (
          <span className="font-medium text-ink">{row.batch_code}</span>
        ),
    },
    { key: 'collection_code', header: 'From collection', render: (row) => <span className="text-sm text-ink-soft">{row.collection_code}</span> },
    { key: 'collection_date', header: 'Harvest date', render: (row) => formatDate(row.collection_date) },
    {
      key: 'quantity',
      header: 'Quantity',
      align: 'right',
      render: (row) => `${Number(row.quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${unitLabel(row.unit)}`,
    },
    {
      key: 'hives',
      header: 'Source hives',
      render: (row) =>
        row.source_hive_codes?.length ? (
          <span className="flex flex-wrap gap-1">
            {row.source_hive_codes.slice(0, 3).map((code) => (
              <Badge key={code} variant="neutral" size="sm">
                {code}
              </Badge>
            ))}
            {row.source_hive_count > 3 ? (
              <span className="text-xs text-ink-muted">+{row.source_hive_count - 3} more</span>
            ) : null}
          </span>
        ) : (
          <span className="text-ink-muted">—</span>
        ),
    },
    {
      key: 'status',
      header: 'Stage',
      render: (row) => {
        // Tone, not decoration: "Rejected" must not look like "Collected".
        const meta = BATCH_STATUS_META[row.status] || null;
        return (
          <span className="flex flex-col gap-1">
            <Badge variant={meta?.variant || 'neutral'} size="sm">
              {row.status_label || meta?.label || row.status}
            </Badge>
            <span className="text-xs text-ink-muted">{row.current_stage_label || meta?.stage || row.current_stage}</span>
          </span>
        );
      },
    },
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
  ];

  return (
    <DataTable
      columns={columns}
      rows={batches}
      loading={loading}
      error={error}
      onRetry={onRetry}
      meta={meta}
      onPageChange={onPageChange}
      emptyTitle={COLLECTION_MESSAGES.emptyBatches}
      emptyDescription="A batch is created the moment you complete a collection — there is nothing to create here by hand."
      caption="Honey batches"
    />
  );
}

export default BatchTable;
