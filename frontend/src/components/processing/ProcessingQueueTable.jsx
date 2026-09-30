import { Link } from 'react-router-dom';
import { CheckCircle2, Play, UserCheck } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { DataTable } from '@/components/common/DataTable';
import { PROCESSING_STATUS_META, PROCESSING_MESSAGES } from '@/constants/processing';
import { formatDate, formatDateTime } from '@/utils/format';

/**
 * The processing queue — one table for every processing list screen.
 *
 * Pending, assigned, in-progress, completed and history are the *same rows* seen
 * through different filters, so they are rendered by one component: a second table
 * would be a second place for the columns to drift apart, and the queues are
 * defined by the server, not by the layout.
 *
 * The assignment column shows what the record actually says — who the work belongs
 * to, whether they have taken it on, and when — because "assigned" and "accepted"
 * are different facts and a processor needs to see which one applies before
 * deciding whether to act.
 *
 * Actions are only rendered for rows the caller may act on (`can_start`,
 * `can_complete`, `can_accept`), and every one of them is a request the server
 * authorises again: the buttons are a convenience, not the rule.
 */

function AssignmentCell({ run }) {
  if (!run.processor_id) {
    return (
      <span className="flex flex-col gap-1">
        <Badge variant="warning" size="sm">
          Unassigned
        </Badge>
        <span className="text-xs text-ink-muted">Nobody is responsible yet</span>
      </span>
    );
  }
  const accepted = run.assignment_status === 'ACCEPTED';
  return (
    <span className="flex flex-col gap-1">
      <Badge variant={accepted ? 'success' : 'neutral'} size="sm">
        {accepted ? 'Accepted' : 'Assigned'}
      </Badge>
      <span className="text-xs text-ink-soft">{run.processor_name || 'Named processor'}</span>
      {run.assigned_at ? (
        <span className="text-xs text-ink-muted">Allocated {formatDateTime(run.assigned_at)}</span>
      ) : null}
    </span>
  );
}

export function ProcessingQueueTable({
  runs = [],
  loading = false,
  error = null,
  onRetry,
  meta,
  onPageChange,
  detailPath = null,
  onAssign = null,
  onAccept = null,
  onStart = null,
  onComplete = null,
  onOpen = null,
  busyId = null,
  emptyTitle = PROCESSING_MESSAGES.runsEmpty,
  emptyDescription = 'A run is opened against a collected batch, then started and completed with the quantities actually measured.',
  caption = 'Processing runs',
}) {
  const columns = [
    {
      key: 'processing_code',
      header: 'Run',
      render: (row) =>
        detailPath ? (
          <Link
            className="font-mono text-sm font-medium text-forest-700 hover:underline"
            to={`${detailPath}/${row.id}`}
          >
            {row.processing_code}
          </Link>
        ) : (
          <span className="font-mono text-sm font-medium text-ink">{row.processing_code}</span>
        ),
    },
    {
      key: 'batch_code',
      header: 'Batch',
      render: (row) => (
        <span className="flex flex-col gap-1">
          <span className="font-mono text-sm text-ink-soft">{row.batch_code}</span>
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
          <span className="font-mono text-ink-soft">{row.beekeeper_code || '—'}</span>
          <span className="font-mono text-ink-muted">{row.cluster_code || 'No cluster'}</span>
        </span>
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
    { key: 'processing_type_label', header: 'Type', render: (row) => row.processing_type_display || row.processing_type_label || row.processing_type },
    { key: 'processing_date', header: 'Date', render: (row) => formatDate(row.processing_date) },
    {
      key: 'status',
      header: 'Processing status',
      render: (row) => {
        const statusMeta = PROCESSING_STATUS_META[row.status] || PROCESSING_STATUS_META.PENDING;
        return (
          <span className="flex flex-col gap-1">
            <Badge variant={statusMeta.variant} size="sm">
              {row.status_label || statusMeta.label}
            </Badge>
            {row.completion_time ? (
              <span className="text-xs text-ink-muted">Completed {formatDateTime(row.completion_time)}</span>
            ) : null}
          </span>
        );
      },
    },
    { key: 'assignment', header: 'Assignment', render: (row) => <AssignmentCell run={row} /> },
    {
      key: 'actions',
      header: 'Actions',
      render: (row) => {
        const busy = busyId === row.id;
        const buttons = [];
        if (onAssign && row.can_assign) {
          buttons.push(
            <Button
              key="assign"
              size="sm"
              variant="secondary"
              onClick={() => onAssign(row)}
              data-testid={`assign-run-${row.processing_code}`}
            >
              Assign
            </Button>,
          );
        }
        if (onAccept && row.can_accept) {
          buttons.push(
            <Button
              key="accept"
              size="sm"
              loading={busy}
              onClick={() => onAccept(row)}
              data-testid={`accept-run-${row.processing_code}`}
            >
              <UserCheck size={14} aria-hidden="true" /> Accept
            </Button>,
          );
        }
        if (onStart && row.can_start) {
          buttons.push(
            <Button
              key="start"
              size="sm"
              loading={busy}
              onClick={() => onStart(row)}
              data-testid={`start-run-${row.processing_code}`}
            >
              <Play size={14} aria-hidden="true" /> Start
            </Button>,
          );
        }
        if (onComplete && row.can_complete) {
          buttons.push(
            <Button
              key="complete"
              size="sm"
              variant="secondary"
              loading={busy}
              onClick={() => onComplete(row)}
              data-testid={`complete-run-${row.processing_code}`}
            >
              <CheckCircle2 size={14} aria-hidden="true" /> Complete
            </Button>,
          );
        }
        if (onOpen) {
          buttons.push(
            <Button
              key="open"
              size="sm"
              variant="ghost"
              onClick={() => onOpen(row)}
              data-testid={`open-run-${row.processing_code}`}
            >
              Details
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
      rows={runs}
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

export default ProcessingQueueTable;
