import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, ArrowRight, CheckCircle2, Factory, Pencil, Play, XCircle } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { SelectWithOther } from '@/components/ui/SelectWithOther';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import {
  IMMUTABLE_RUN_FIELDS,
  PROCESSING_MESSAGES,
  PROCESSING_STATUS_META,
  PROCESSING_TYPES,
  QUANTITY_UNITS,
  lossPercent,
} from '@/constants/processing';
import { unitLabel } from '@/constants/collection';
import * as processingService from '@/services/processingService';
import { normaliseError } from '@/utils/errors';
import { formatDate, formatDateTime } from '@/utils/format';

/**
 * One processing run, and the work it allows.
 *
 * The panel is a small state machine over the run's own status, and every button
 * it renders is one the API will accept: an open run can be edited, started and
 * cancelled; a completed run offers nothing but the record of what was measured,
 * because the server would refuse the edit anyway. The distinction between
 * "the button is hidden" and "the request is refused" is deliberate — the UI does
 * not pretend to be the boundary.
 */

function Row({ label, children }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2 py-1.5">
      <dt className="text-sm text-ink-muted">{label}</dt>
      <dd className="text-sm font-medium text-ink">{children}</dd>
    </div>
  );
}

/** The measured difference, shown as arithmetic on the two recorded numbers. */
function DifferenceRow({ input, output, unit }) {
  const difference = lossPercent(input, output);
  if (input === null || input === undefined || output === null || output === undefined) {
    return (
      <Row label="Difference">
        <span className="text-ink-muted">Measured once both quantities are recorded</span>
      </Row>
    );
  }
  const lost = Number(input) - Number(output);
  return (
    <Row label="Difference (input − output)">
      <span className="text-ink">
        {Number(input).toLocaleString(undefined, { maximumFractionDigits: 3 })} →{' '}
        {Number(output).toLocaleString(undefined, { maximumFractionDigits: 3 })} {unit} ={' '}
        {lost.toLocaleString(undefined, { maximumFractionDigits: 3 })} {unit}
      </span>
      {difference !== null ? (
        <span className="ml-2 text-xs text-ink-muted">{difference}% less than the input</span>
      ) : null}
    </Row>
  );
}

export function ProcessingRunPanel({
  processingId,
  canWrite = false,
  units = [],
  onChanged = null,
  compact = false,
}) {
  const [run, setRun] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [editing, setEditing] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState('');
  const [form, setForm] = useState({
    processing_type: 'FILTERING',
    processing_type_other: '',
    processing_unit_id: '',
    processing_date: '',
    input_quantity: '',
    output_quantity: '',
    unit: 'KG',
    notes: '',
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await processingService.getRun(processingId);
      setRun(payload);
      setForm({
        processing_type: payload.processing_type || 'FILTERING',
        processing_type_other: payload.processing_type_other || '',
        processing_unit_id: payload.processing_unit_id || '',
        processing_date: payload.processing_date || '',
        input_quantity: payload.input_quantity ?? '',
        output_quantity: payload.output_quantity ?? '',
        unit: payload.unit || 'KG',
        notes: payload.notes || '',
      });
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [processingId]);

  useEffect(() => {
    load();
  }, [load]);

  const act = async (operation) => {
    setBusy(true);
    setActionError(null);
    try {
      await operation();
      await load();
      if (onChanged) onChanged();
    } catch (caught) {
      setActionError(normaliseError(caught));
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <LoadingState message={PROCESSING_MESSAGES.loadingBatch} />;
  if (error) return <ErrorState error={error} onRetry={load} />;
  if (!run) return null;

  const statusMeta = PROCESSING_STATUS_META[run.status] || PROCESSING_STATUS_META.PENDING;
  const open = run.status === 'PENDING' || run.status === 'IN_PROGRESS';
  const unit = unitLabel(run.unit);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={`Processing run ${run.processing_code}`}
          description={run.next_step || 'Measured quantities are recorded while the run is open.'}
          icon={<Factory size={18} aria-hidden="true" />}
          action={
            <span className="flex flex-wrap items-center gap-2">
              <Badge variant={statusMeta.variant} size="sm">
                {run.status_label || statusMeta.label}
              </Badge>
              {!compact ? (
                <Badge variant="neutral" size="sm">
                  Batch {run.batch_code}
                </Badge>
              ) : null}
            </span>
          }
        />
        <CardBody className="space-y-3">
          <dl className="divide-y divide-sand-100">
            <Row label="Honey batch">
              <span className="font-mono text-sm">{run.batch_code}</span>
              <Badge variant="neutral" size="sm" className="ml-2">
                {run.batch_status_label || run.batch_status}
              </Badge>
            </Row>
            <Row label="Batch quantity">
              {Number(run.batch?.quantity ?? 0).toLocaleString(undefined, { maximumFractionDigits: 3 })} {unit}
              <span className="ml-2 text-xs text-ink-muted">from collection {run.collection_code || '—'}</span>
            </Row>
            <Row label="Type">{run.processing_type_display || run.processing_type_label || run.processing_type}</Row>
            <Row label="Processing unit">
              {run.processing_unit_name ? (
                <span>
                  {run.processing_unit_name}
                  {run.processing_unit_code ? (
                    <span className="ml-2 text-xs text-ink-muted">{run.processing_unit_code}</span>
                  ) : null}
                </span>
              ) : (
                <span className="text-ink-muted">Not recorded</span>
              )}
            </Row>
            <Row label="Processing date">{formatDate(run.processing_date)}</Row>
            <Row label="Input (measured)">
              {run.input_quantity === null || run.input_quantity === undefined
                ? 'Not recorded'
                : `${Number(run.input_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${unit}`}
            </Row>
            <Row label="Output (measured)">
              {run.output_quantity === null || run.output_quantity === undefined
                ? 'Not recorded'
                : `${Number(run.output_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${unit}`}
            </Row>
            <DifferenceRow input={run.input_quantity} output={run.output_quantity} unit={unit} />
            <Row label="Started">{run.start_time ? formatDateTime(run.start_time) : 'Not started'}</Row>
            <Row label="Completed">
              {run.completion_time ? formatDateTime(run.completion_time) : 'Not completed'}
            </Row>
            {run.status === 'CANCELLED' ? (
              <Row label="Cancellation">
                {run.cancellation_reason}
                {run.cancelled_at ? (
                  <span className="ml-2 text-xs text-ink-muted">{formatDateTime(run.cancelled_at)}</span>
                ) : null}
              </Row>
            ) : null}
            {run.notes ? <Row label="Notes">{run.notes}</Row> : null}
          </dl>

          {actionError ? (
            <Alert variant="danger" icon={<AlertCircle size={16} aria-hidden="true" />}>
              {actionError.message}
            </Alert>
          ) : null}

          {canWrite && open ? (
            <div className="flex flex-wrap gap-2">
              {run.status === 'PENDING' ? (
                <Button
                  size="sm"
                  leftIcon={<Play size={15} />}
                  loading={busy}
                  onClick={() => act(() => processingService.startRun(run.id))}
                >
                  Start processing
                </Button>
              ) : null}
              <Button
                size="sm"
                variant="secondary"
                leftIcon={<Pencil size={15} />}
                onClick={() => setEditing((value) => !value)}
              >
                {editing ? 'Close the form' : 'Record or correct details'}
              </Button>
              {run.status === 'IN_PROGRESS' ? (
                <Button
                  size="sm"
                  leftIcon={<CheckCircle2 size={15} />}
                  loading={busy}
                  onClick={() => act(() => processingService.completeRun(run.id, {}))}
                >
                  Complete run
                </Button>
              ) : null}
              <Button
                size="sm"
                variant="ghost"
                leftIcon={<XCircle size={15} />}
                onClick={() => setCancelOpen((value) => !value)}
              >
                Cancel run
              </Button>
            </div>
          ) : null}

          {canWrite && !open ? (
            <p className="rounded-lg border border-sand-300 bg-sand-50 px-3 py-2 text-xs text-ink-soft">
              This run is {String(run.status).toLowerCase().replace('_', ' ')}. Its{' '}
              {IMMUTABLE_RUN_FIELDS.join(', ')} stay as first recorded; a correction is made by
              recording a new run, and every change is written to the audit log.
            </p>
          ) : null}

          {!canWrite ? (
            <p className="text-xs text-ink-muted">
              Read-only: your role may follow this run, but processing is recorded by the operator who
              performed it.
            </p>
          ) : null}

          {cancelOpen && canWrite && open ? (
            <div className="space-y-2 rounded-lg border border-sand-300 bg-sand-50 p-3">
              <label className="text-sm font-medium text-ink" htmlFor={`cancel-${run.id}`}>
                Why did this run not happen?
              </label>
              <Input
                id={`cancel-${run.id}`}
                value={cancelReason}
                onChange={(event) => setCancelReason(event.target.value)}
                placeholder="For example: the batch was redirected to another unit"
                data-testid="cancel-reason"
              />
              <Button
                size="sm"
                variant="danger"
                loading={busy}
                onClick={() =>
                  act(async () => {
                    await processingService.cancelRun(run.id, cancelReason.trim());
                    setCancelOpen(false);
                    setCancelReason('');
                  })
                }
                disabled={cancelReason.trim().length < 3}
              >
                Record the cancellation
              </Button>
            </div>
          ) : null}

          {editing && canWrite && open ? (
            <form
              className="space-y-3 rounded-lg border border-sand-300 bg-sand-50 p-3"
              onSubmit={(event) => {
                event.preventDefault();
                act(() =>
                  processingService.updateRun(run.id, {
                    processing_type: form.processing_type,
                    // The description travels with the type, and only when the type
                    // is Other — the server refuses the pair recorded half-way.
                    ...(form.processing_type === 'OTHER'
                      ? { processing_type_other: form.processing_type_other.trim() }
                      : {}),
                    ...(form.processing_unit_id ? { processing_unit_id: form.processing_unit_id } : {}),
                    ...(form.processing_date ? { processing_date: form.processing_date } : {}),
                    ...(form.input_quantity !== '' ? { input_quantity: form.input_quantity } : {}),
                    ...(form.output_quantity !== '' ? { output_quantity: form.output_quantity } : {}),
                    ...(form.notes ? { notes: form.notes } : {}),
                  }),
                );
                setEditing(false);
              }}
            >
              <p className="text-sm font-medium text-ink">Record what was measured</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <SelectWithOther
                  label="Processing type"
                  name="processing_type"
                  value={form.processing_type}
                  onChange={(event) => setForm({ ...form, processing_type: event.target.value })}
                  options={PROCESSING_TYPES}
                  otherValue={form.processing_type_other}
                  onOtherChange={(text) => setForm({ ...form, processing_type_other: text })}
                  otherLabel="Specify the operation"
                  otherPlaceholder="For example: centrifuged"
                  hint="What the run did. Choose Other to record an operation outside the list."
                />
                <Select
                  label="Processing unit"
                  name="processing_unit_id"
                  value={form.processing_unit_id}
                  onChange={(event) => setForm({ ...form, processing_unit_id: event.target.value })}
                  placeholder="No facility recorded"
                  options={units.map((entry) => ({ value: entry.id, label: `${entry.name} (${entry.unit_code})` }))}
                />
                <Input
                  label="Processing date"
                  name="processing_date"
                  type="date"
                  value={form.processing_date}
                  onChange={(event) => setForm({ ...form, processing_date: event.target.value })}
                />
                <Select
                  label="Unit"
                  name="unit"
                  value={form.unit}
                  onChange={(event) => setForm({ ...form, unit: event.target.value })}
                  options={QUANTITY_UNITS}
                  disabled
                  hint="The batch's own unit; quantities are never converted."
                />
                <Input
                  label={`Input quantity (${unit})`}
                  name="input_quantity"
                  type="number"
                  step="0.001"
                  min="0"
                  value={form.input_quantity}
                  onChange={(event) => setForm({ ...form, input_quantity: event.target.value })}
                  hint="Weighed or measured before processing."
                />
                <Input
                  label={`Output quantity (${unit})`}
                  name="output_quantity"
                  type="number"
                  step="0.001"
                  min="0"
                  value={form.output_quantity}
                  onChange={(event) => setForm({ ...form, output_quantity: event.target.value })}
                  hint="Never assumed equal to the input; the difference is shown as measured."
                />
              </div>
              <Input
                label="Notes"
                name="notes"
                value={form.notes}
                onChange={(event) => setForm({ ...form, notes: event.target.value })}
                placeholder="Anything the next reader should know about this run"
              />
              <div className="flex flex-wrap items-center gap-2">
                <Button type="submit" size="sm" loading={busy} rightIcon={<ArrowRight size={15} />}>
                  Save the run
                </Button>
                <span className="text-xs text-ink-muted">
                  The honey batch quantity of {Number(run.batch?.quantity ?? 0).toLocaleString(undefined, { maximumFractionDigits: 3 })} {unit} is
                  unchanged by this run — what was weighed in and out is recorded on the run itself.
                </span>
              </div>
            </form>
          ) : null}
        </CardBody>
      </Card>
    </div>
  );
}

export default ProcessingRunPanel;
