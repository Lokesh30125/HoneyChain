import { Link } from 'react-router-dom';
import { CheckCircle2, UserCheck } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { DataTable } from '@/components/common/DataTable';
import { LAB_RESULT_META, LAB_TEST_STATUSES, labStatusMeta } from '@/constants/laboratory';
import { formatDate, formatDateTime } from '@/utils/format';

/**
 * The laboratory queue — one table for the pending, assigned, sample, test and
 * completed screens.
 *
 * The laboratory's lists are filters over the same stored tests, so they are
 * rendered by one component: the columns cannot drift apart between the queue a
 * technician works from and the history they read afterwards.
 *
 * Two facts are kept visibly distinct, because they mean different things:
 * the **assignment** (who is responsible, and whether they have taken it on) and
 * the **test status** (whether the work has started and how it ended). A sample
 * can be allocated and unstarted, and the row says so rather than implying
 * progress that has not happened.
 *
 * Actions are rendered from the record's own `can_*` flags and re-authorised by
 * the server: this table is a view, not a permission system.
 */

function AssignmentCell({ test }) {
  if (!test.assigned_technician_id) {
    return (
      <span className="flex flex-col gap-1">
        <Badge variant="warning" size="sm">
          Unassigned
        </Badge>
        <span className="text-xs text-ink-muted">Nobody is responsible yet</span>
      </span>
    );
  }
  const accepted = test.assignment_status === 'ACCEPTED';
  return (
    <span className="flex flex-col gap-1">
      <Badge variant={accepted ? 'success' : 'neutral'} size="sm">
        {accepted ? 'Accepted' : 'Assigned'}
      </Badge>
      <span className="text-xs text-ink-soft">{test.assigned_technician_name || 'Named technician'}</span>
      {test.assigned_at ? (
        <span className="text-xs text-ink-muted">Allocated {formatDateTime(test.assigned_at)}</span>
      ) : null}
    </span>
  );
}

function ResultCell({ test }) {
  const statusMeta = labStatusMeta(test.status);
  const resultMeta = LAB_RESULT_META[test.overall_result];
  const held = test.status === LAB_TEST_STATUSES.HOLD;
  return (
    <span className="flex flex-col gap-1">
      <Badge variant={statusMeta.variant} size="sm">
        {test.status_label || statusMeta.label}
      </Badge>
      {test.status === LAB_TEST_STATUSES.COMPLETED ? (
        <Badge variant={resultMeta?.variant || 'neutral'} size="sm">
          {test.overall_result_label || test.overall_result}
        </Badge>
      ) : held ? (
        // A held test has no verdict on purpose. What it has is a reason and a
        // batch that cannot be packed, and the row says both.
        <span className="flex flex-col gap-0.5">
          <span className="text-xs text-ink-soft">{test.hold_reason || 'Reason recorded on the test'}</span>
          <span className="text-xs text-status-danger">Blocks packaging</span>
        </span>
      ) : (
        <span className="text-xs text-ink-muted">
          {test.parameter_count} measurement{test.parameter_count === 1 ? '' : 's'} recorded
        </span>
      )}
      {test.ai_status && !held ? (
        <span className="text-xs text-ink-muted">
          Analysis: {test.ai_status}
          {test.ai_risk_level ? ` · risk ${test.ai_risk_level}` : ''}
        </span>
      ) : null}
    </span>
  );
}

export function LabQueueTable({
  tests = [],
  loading = false,
  error = null,
  onRetry,
  meta,
  onPageChange,
  detailPath = '/laboratory/tests',
  onAssign = null,
  onAccept = null,
  onOpen = null,
  busyId = null,
  emptyTitle = 'No laboratory tests yet.',
  emptyDescription = 'A sample appears here once processing is complete and a test has been opened against the batch.',
  caption = 'Laboratory tests',
}) {
  const columns = [
    {
      key: 'test_code',
      header: 'Test / sample',
      render: (test) => (
        <span className="flex flex-col gap-1">
          <Link
            className="font-mono text-sm font-medium text-forest-700 hover:underline"
            to={`${detailPath}/${test.id}`}
          >
            {test.test_code}
          </Link>
          <span className="font-mono text-xs text-ink-muted">{test.sample_code}</span>
          {test.round_number > 1 ? (
            <Badge variant="neutral" size="sm">
              Retest · round {test.round_number}
            </Badge>
          ) : null}
        </span>
      ),
    },
    {
      key: 'batch_code',
      header: 'Batch / collection',
      render: (test) => (
        <span className="flex flex-col gap-1">
          <span className="font-mono text-sm text-ink-soft">{test.batch_code}</span>
          {test.collection_code ? (
            <span className="font-mono text-xs text-ink-muted">{test.collection_code}</span>
          ) : null}
        </span>
      ),
    },
    {
      key: 'processing_code',
      header: 'Processing',
      render: (test) => (
        <span className="font-mono text-xs text-ink-soft">{test.processing_code || '—'}</span>
      ),
    },
    {
      key: 'source',
      header: 'Beekeeper / cluster',
      render: (test) => (
        <span className="flex flex-col gap-1 text-xs">
          <span className="font-mono text-ink-soft">{test.beekeeper_code || '—'}</span>
          <span className="font-mono text-ink-muted">{test.cluster_code || 'No cluster'}</span>
        </span>
      ),
    },
    {
      key: 'sample',
      header: 'Sample',
      align: 'right',
      render: (test) => (
        <span className="flex flex-col gap-1">
          <span className="text-sm text-ink">
            {Number(test.sample_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })}{' '}
            {test.sample_unit_label}
          </span>
          <span className="text-xs text-ink-muted">{formatDate(test.test_date)}</span>
        </span>
      ),
    },
    { key: 'result', header: 'Status / outcome', render: (test) => <ResultCell test={test} /> },
    { key: 'assignment', header: 'Assignment', render: (test) => <AssignmentCell test={test} /> },
    {
      key: 'actions',
      header: 'Actions',
      render: (test) => {
        const busy = busyId === test.id;
        const buttons = [];
        if (onAssign && test.can_assign) {
          buttons.push(
            <Button key="assign" size="sm" variant="secondary" onClick={() => onAssign(test)}>
              Assign
            </Button>,
          );
        }
        if (onAccept && test.can_accept) {
          buttons.push(
            <Button key="accept" size="sm" loading={busy} onClick={() => onAccept(test)}>
              <UserCheck size={14} aria-hidden="true" /> Accept
            </Button>,
          );
        }
        if (onOpen) {
          buttons.push(
            <Button key="open" size="sm" variant="ghost" onClick={() => onOpen(test)}>
              {test.status === LAB_TEST_STATUSES.COMPLETED ? 'Details' : 'Record results'}
              <CheckCircle2 size={14} aria-hidden="true" />
            </Button>,
          );
        }
        if (!buttons.length) {
          return <span className="text-xs text-ink-muted">No action for your role</span>;
        }
        return <div className="flex flex-wrap gap-2">{buttons}</div>;
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
      caption={caption}
    />
  );
}

export default LabQueueTable;
