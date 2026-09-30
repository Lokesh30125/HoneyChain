import { Link } from 'react-router-dom';

import { Badge } from '@/components/ui/Badge';
import { DataTable } from '@/components/common/DataTable';
import { LAB_MESSAGES, LAB_RESULT_META, LAB_TEST_STATUS_META } from '@/constants/laboratory';
import { formatDate } from '@/utils/format';

/**
 * The laboratory test list — every test ever taken, including superseded rounds.
 *
 * A retest adds a row; the earlier test keeps its own row, its own result and its
 * own code. Two columns carry that honesty: the round number ("round 2") and the
 * recorded-value counts, which show at a glance whether a decision rests on
 * measurements or on nothing at all.
 */
export function LabTestTable({
  tests = [],
  loading = false,
  error = null,
  onRetry,
  meta,
  onPageChange,
  detailPath = '/laboratory/tests',
  emptyTitle = LAB_MESSAGES.testsEmpty,
  emptyDescription = 'A test is opened against a batch that has completed processing.',
}) {
  const columns = [
    {
      key: 'test_code',
      header: 'Test',
      render: (row) => (
        <Link className="font-mono text-sm font-medium text-forest-700 hover:underline" to={`${detailPath}/${row.id}`}>
          {row.test_code}
        </Link>
      ),
    },
    {
      key: 'sample_code',
      header: 'Sample',
      render: (row) => (
        <span className="flex flex-col">
          <span className="font-mono text-xs text-ink-soft">{row.sample_code}</span>
          <span className="text-xs text-ink-muted">
            {Number(row.sample_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })}{' '}
            {row.sample_unit_label}
          </span>
        </span>
      ),
    },
    {
      key: 'batch_code',
      header: 'Batch',
      render: (row) => <span className="font-mono text-xs text-ink-soft">{row.batch_code}</span>,
    },
    {
      key: 'processing_code',
      header: 'Processing',
      render: (row) => <span className="font-mono text-xs text-ink-muted">{row.processing_code}</span>,
    },
    {
      key: 'laboratory',
      header: 'Laboratory',
      render: (row) => <span className="text-sm text-ink-soft">{row.laboratory_name || row.laboratory_code || '—'}</span>,
    },
    {
      key: 'round',
      header: 'Round',
      align: 'right',
      render: (row) => (
        <span className="text-sm text-ink-soft">
          {row.round_number}
          {row.retest_of_id ? <span className="ml-1 text-xs text-ink-muted">retest</span> : null}
        </span>
      ),
    },
    {
      key: 'results',
      header: 'Recorded values',
      align: 'right',
      render: (row) =>
        row.parameter_count ? (
          <span className="text-xs text-ink-soft">
            {row.parameter_count} recorded · {row.failed_count} fail · {row.unevaluated_count} not evaluated
          </span>
        ) : (
          <span className="text-xs text-ink-muted">None yet</span>
        ),
    },
    { key: 'test_date', header: 'Date', render: (row) => formatDate(row.test_date) },
    {
      key: 'status',
      header: 'Status',
      render: (row) => {
        const status = LAB_TEST_STATUS_META[row.status] || LAB_TEST_STATUS_META.PENDING;
        return (
          <Badge variant={status.variant} size="sm">
            {row.status_label || status.label}
          </Badge>
        );
      },
    },
    {
      key: 'overall_result',
      header: 'Result',
      render: (row) => {
        const result = LAB_RESULT_META[row.overall_result] || LAB_RESULT_META.PENDING;
        return (
          <span className="flex flex-wrap items-center gap-1">
            <Badge variant={result.variant} size="sm">
              {row.overall_result_label || result.label}
            </Badge>
            {row.is_override ? (
              <span className="text-xs text-ink-muted" title="Decided by an authorised override">
                override
              </span>
            ) : null}
          </span>
        );
      },
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={tests}
      loading={loading}
      error={error}
      onRetry={onRetry}
      meta={meta}
      onPageChange={onPageChange}
      emptyTitle={emptyTitle}
      emptyDescription={emptyDescription}
      caption="Laboratory tests"
    />
  );
}

export default LabTestTable;
