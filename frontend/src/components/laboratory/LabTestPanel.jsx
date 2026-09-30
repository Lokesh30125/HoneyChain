import { useCallback, useEffect, useState } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  Brain,
  CheckCircle2,
  FlaskConical,
  Info,
  PauseCircle,
  Pencil,
  Plus,
  ShieldAlert,
  Trash2,
} from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import { SelectWithOther } from '@/components/ui/SelectWithOther';
import { ROLES } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';
import { AssignmentDialog } from '@/components/common/AssignmentDialog';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import {
  LAB_MEASURE_UNITS,
  LAB_MESSAGES,
  LAB_METHODS,
  LAB_PARAMETER_STATUS_META,
  LAB_RESULT_META,
  LAB_TEST_STATUS_META,
  analysisMeta,
  measurementSourceMeta,
  measurementText,
  referenceText,
} from '@/constants/laboratory';
import * as laboratoryService from '@/services/laboratoryService';
import { normaliseError } from '@/utils/errors';
import { formatDate, formatDateTime } from '@/utils/format';

/**
 * One laboratory test.
 *
 * The panel records measurements and then asks the platform for a decision. It
 * never offers the verdict as a choice: `Complete test` sends the remarks and the
 * server computes PASS, FAIL or INCONCLUSIVE from the recorded values and the
 * configured ranges, explaining itself in `evaluation_notes`. The single
 * exception — an authorised override — is an administrator-only dialog that
 * demands a reason and is written to the audit log.
 *
 * While the test is open every recorded value can be corrected or removed, and the
 * correction is logged with the value it replaced. Once the test is completed the
 * panel becomes a record: no edit controls, and a retest is the way forward.
 */

/**
 * The words stored for a chosen method.
 *
 * The column holds text because that is what a laboratory writes down; the dropdown
 * is a convenience over it, so what is saved is the label the technician saw
 * ("Refractometry (refractive index)"), not an internal key. The catalogue's own
 * methods are preferred, and the general list answers only for a choice made from
 * it (a parameter with no methods configured of its own).
 */
function selectedMethodLabel(value) {
  return LAB_METHODS.find((method) => method.value === value)?.label || value;
}

function Row({ label, children }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2 py-1.5">
      <dt className="text-sm text-ink-muted">{label}</dt>
      <dd className="text-sm font-medium text-ink">{children}</dd>
    </div>
  );
}

export function LabTestPanel({ testId, canWrite = false, canOverride = false, onChanged = null }) {
  const { user } = useAuth();
  const [assignOpen, setAssignOpen] = useState(false);
  const [technicians, setTechnicians] = useState([]);
  const [techniciansLoading, setTechniciansLoading] = useState(false);
  const [techniciansError, setTechniciansError] = useState(null);
  const [test, setTest] = useState(null);
  const [parameters, setParameters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);
  // The measurement form holds the pair-fields as pairs: the chosen parameter and
  // the name typed for "Other measurement", the chosen method and the words typed
  // for "Other". Clearing one side when the choice changes is what keeps a stale
  // value from being saved against the wrong record.
  const [resultForm, setResultForm] = useState({
    open: false,
    code: '',
    parameterName: '',
    value: '',
    unit: '',
    method: '',
    methodOther: '',
    remarks: '',
  });
  const [resultErrors, setResultErrors] = useState({});
  const closeResultForm = () =>
    setResultForm({
      open: false,
      code: '',
      parameterName: '',
      value: '',
      unit: '',
      method: '',
      methodOther: '',
      remarks: '',
    });
  const [editingResult, setEditingResult] = useState(null);
  const [overrideOpen, setOverrideOpen] = useState(false);
  // No outcome is pre-chosen for an override: it is the administrator's decision.
  const [override, setOverride] = useState({ result: '', reason: '' });
  const [completeOpen, setCompleteOpen] = useState(false);
  const [completeRemarks, setCompleteRemarks] = useState('');
  /**
   * What the server said when it refused to complete a flagged test.
   *
   * The server owns this rule: a stored analysis that is not a pass cannot be
   * completed away, and the refusal carries the reasons and the two ways forward.
   * The panel renders exactly the options it was given, so a build with the
   * temporary override switched off cannot offer it.
   */
  const [decision, setDecision] = useState(null);
  const [holdOpen, setHoldOpen] = useState(false);
  const [hold, setHold] = useState({ reason: '', runAnalysis: false });
  const [proceedOpen, setProceedOpen] = useState(false);
  const [proceed, setProceed] = useState({ confirmation: '', reason: '' });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [payload, catalogue] = await Promise.all([
        laboratoryService.getTest(testId),
        laboratoryService.listParameters().catch(() => []),
      ]);
      setTest(payload);
      setParameters(catalogue);
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [testId]);

  useEffect(() => {
    load();
  }, [load]);

  // Who may take this sample comes from the server, through the endpoint built for
  // the question: an administrator is given the active technician accounts the
  // platform holds, a technician is given themselves. Nobody's name is written into
  // the interface, and a technician is never sent to an administrator-only endpoint.
  const openAssign = async () => {
    setAssignOpen(true);
    setTechniciansLoading(true);
    setTechniciansError(null);
    try {
      const { users } = await laboratoryService.listEligibleTechnicians();
      setTechnicians(users);
    } catch (caught) {
      setTechniciansError(normaliseError(caught));
    } finally {
      setTechniciansLoading(false);
    }
  };

  const act = async (operation, { onRefusal = null } = {}) => {
    setBusy(true);
    setActionError(null);
    try {
      await operation();
      await load();
      if (onChanged) onChanged();
      return true;
    } catch (caught) {
      const normalised = normaliseError(caught);
      // A refusal that carries a choice is not an error to shout about: it is the
      // server telling the technician what the analysis found and what may be done
      // about it. It is handed to the caller, which opens the dialog for it.
      if (onRefusal && normalised.details?.options?.length) {
        onRefusal(normalised);
        return false;
      }
      setActionError(normalised);
      return false;
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <LoadingState message={LAB_MESSAGES.loadingLaboratory} />;
  if (error) return <ErrorState error={error} onRetry={load} />;
  if (!test) return null;

  const statusMeta = LAB_TEST_STATUS_META[test.status] || LAB_TEST_STATUS_META.PENDING;
  const resultMeta = LAB_RESULT_META[test.overall_result] || LAB_RESULT_META.PENDING;
  // Open means the bench is still working on it: a completed *or held* test is
  // closed to edits, because a hold is a decision to stop with the record as it
  // stands rather than an invitation to keep changing it.
  const open = test.status === 'PENDING' || test.status === 'IN_PROGRESS';
  const analysis = test.ai_analysis || null;
  const analysisBadge = analysis ? analysisMeta(analysis.overall_status) : null;
  const recordedCodes = new Set(test.results.map((result) => result.parameter_code));
  const available = parameters.filter(
    (parameter) => parameter.is_active !== false && !recordedCodes.has(parameter.code),
  );
  const selectedParameter = parameters.find((parameter) => parameter.code === resultForm.code) || null;
  /**
   * The methods that apply to the chosen parameter.
   *
   * From the catalogue, not from a general list: moisture is measured by
   * refractometry or Karl Fischer, acidity by titration, and offering every method
   * for every parameter is how a record ends up claiming a method that was never
   * used. A parameter configured without methods falls back to the general list.
   */
  const methodOptions = (selectedParameter?.methods?.length ? selectedParameter.methods : LAB_METHODS).map(
    (method) =>
      method.code
        ? { value: method.code, label: method.label || method.code }
        : { value: method.value, label: method.label || method.value },
  );
  const methodLabelFor = (code) =>
    methodOptions.find((option) => option.value === code)?.label || code || '—';
  // "Other measurement" is a real row in the catalogue, so the custom name is
  // asked for only when that row is the one chosen.
  const wantsCustomParameter = resultForm.code === 'OTHER';
  const methodIsOther = resultForm.method === 'OTHER';

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title={`Laboratory test ${test.test_code}`}
          description={test.next_step || 'Record the measured values, then ask the platform to decide.'}
          icon={<FlaskConical size={18} aria-hidden="true" />}
          action={
            <span className="flex flex-wrap items-center gap-2">
              <Badge variant={statusMeta.variant} size="sm">
                {test.status_label || statusMeta.label}
              </Badge>
              <Badge variant={resultMeta.variant} size="sm">
                {test.overall_result_label || resultMeta.label}
              </Badge>
              {test.round_number > 1 || test.retest_of_id ? (
                <Badge variant="neutral" size="sm">
                  Round {test.round_number}
                </Badge>
              ) : null}
              {test.is_override ? (
                <Badge variant="warning" size="sm">
                  Overridden
                </Badge>
              ) : null}
            </span>
          }
        />
        <CardBody className="space-y-4">
          <dl className="divide-y divide-sand-100">
            <Row label="Sample">
              <span className="font-mono text-sm">{test.sample_code}</span>
              <span className="ml-2 text-xs text-ink-muted">
                {Number(test.sample_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })}{' '}
                {test.sample_unit_label}
                {test.sample_collected_at ? ` · taken ${formatDateTime(test.sample_collected_at)}` : ''}
              </span>
            </Row>
            <Row label="Laboratory">{test.laboratory_name || test.laboratory_code || '—'}</Row>
            <Row label="Technician">{test.technician_name || '—'}</Row>
            {test.hold_reason ? (
              <Row label="On hold">
                <span className="text-ink-soft">{test.hold_reason}</span>
                <span className="ml-2 text-xs text-ink-muted">
                  {test.held_at ? `· ${formatDateTime(test.held_at)}` : ''}
                  {test.held_by ? ` · ${test.held_by}` : ''}
                </span>
              </Row>
            ) : null}
            {/*
              Who is responsible for this sample, and whether they have taken it on.
              Allocating and accepting are two different facts: the sample is on the
              bench because somebody accepted it, not because it was allocated.
            */}
            <Row label="Assignment">
              {test.assigned_technician_id ? (
                <span className="flex flex-wrap items-center gap-2">
                  <Badge
                    variant={test.assignment_status === 'ACCEPTED' ? 'success' : 'neutral'}
                    size="sm"
                  >
                    {test.assignment_status === 'ACCEPTED' ? 'Accepted' : 'Assigned'}
                  </Badge>
                  <span>{test.assigned_technician_name || 'Named technician'}</span>
                  {test.assigned_at ? (
                    <span className="text-xs text-ink-muted">allocated {formatDateTime(test.assigned_at)}</span>
                  ) : null}
                  {canWrite && open ? (
                    <Button size="sm" variant="ghost" onClick={() => openAssign()}>
                      Re-allocate
                    </Button>
                  ) : null}
                </span>
              ) : (
                <span className="flex flex-wrap items-center gap-2">
                  <Badge variant="warning" size="sm">
                    Unassigned
                  </Badge>
                  <span className="text-xs text-ink-muted">Nobody is responsible for this sample</span>
                  {canWrite && open ? (
                    <Button size="sm" variant="secondary" onClick={() => openAssign()}>
                      Assign
                    </Button>
                  ) : null}
                </span>
              )}
            </Row>
            {test.accepted_at ? (
              <Row label="Accepted">{formatDateTime(test.accepted_at)}</Row>
            ) : null}
            {test.assigned_by_name && test.assignment_status === 'ASSIGNED' ? (
              <Row label="Allocated by">{test.assigned_by_name}</Row>
            ) : null}
            <Row label="Test date">{formatDate(test.test_date)}</Row>
            {test.completed_at ? <Row label="Completed">{formatDateTime(test.completed_at)}</Row> : null}
            {test.remarks ? <Row label="Remarks">{test.remarks}</Row> : null}
            {test.override_reason ? (
              <Row label="Override reason">
                <span className="text-ink-soft">{test.override_reason}</span>
                {test.decided_by_name ? (
                  <span className="ml-2 text-xs text-ink-muted">{test.decided_by_name}</span>
                ) : null}
              </Row>
            ) : null}
          </dl>

          {test.evaluation_notes?.length ? (
            <Alert variant={test.overall_result === 'FAIL' ? 'danger' : 'info'} icon={<Info size={16} aria-hidden="true" />}>
              <ul className="space-y-1">
                {test.evaluation_notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </Alert>
          ) : null}

          {actionError ? (
            <Alert variant="danger" icon={<AlertCircle size={16} aria-hidden="true" />}>
              {actionError.message}
            </Alert>
          ) : null}
        </CardBody>
      </Card>

      {/* The chain back to the apiary, from stored records */}
      <Card>
        <CardHeader
          title="Sample traceability"
          description="Batch → processing → collection → hives → beekeeper → cluster, read from the records themselves."
        />
        <CardBody>
          <ol className="space-y-3">
            {test.traceability.map((node) => (
              <li key={`${node.kind}-${node.identifier}`} className="flex gap-3">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-sand-300 bg-white text-xs font-semibold text-ink-soft">
                  {node.kind.slice(0, 2)}
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ink">
                    {node.label}: <span className="font-mono">{node.identifier}</span>
                  </p>
                  <p className="text-xs text-ink-muted">
                    {node.detail || '—'}
                    {node.recorded_at ? ` · ${formatDateTime(node.recorded_at)}` : ''}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </CardBody>
      </Card>

      {/*
        Handing the sample to a named technician. A technician may only name
        themselves; an administrator allocates to the accounts the platform holds.
      */}
      <AssignmentDialog
        open={assignOpen}
        onClose={() => setAssignOpen(false)}
        title={`Assign ${test.test_code}`}
        description={`Sample ${test.sample_code}. The technician who accepts it is the one who measures it — the server records both facts separately.`}
        assigneeLabel="Laboratory technician"
        people={user?.role === ROLES.ADMIN ? technicians : []}
        peopleLoading={techniciansLoading}
        peopleError={techniciansError}
        currentAssigneeId={test.assigned_technician_id}
        selfOption={
          user?.role === ROLES.ADMIN || !user
            ? null
            : {
                id: user.id,
                label: 'Assign to me',
                helper: 'A technician can take an unallocated sample personally.',
              }
        }
        emptyHint="No laboratory technician account is available yet. An administrator creates one in Administration → Users."
        onAssign={async (technicianId) => {
          await act(() => laboratoryService.assignTest(test.id, technicianId));
        }}
      />

      {/* Measurements */}
      <Card>
        <CardHeader
          title="Measured values"
          description="Only what an instrument reported is stored here — no default, no expected value."
          action={
            canWrite && open ? (
              <span className="flex flex-wrap gap-2">
                {test.can_accept ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={busy}
                    onClick={() => act(() => laboratoryService.acceptTest(test.id))}
                    data-testid="accept-test"
                  >
                    Accept this sample
                  </Button>
                ) : null}
                <Button
                  size="sm"
                  leftIcon={<Plus size={15} />}
                  onClick={() =>
                    setResultForm({
                      open: true,
                      code: '',
                      parameterName: '',
                      value: '',
                      unit: '',
                      method: '',
                      methodOther: '',
                      remarks: '',
                    })
                  }
                >
                  Record a measurement
                </Button>
              </span>
            ) : null
          }
        />
        <CardBody className="space-y-4">
          {test.results.length ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-sand-200 text-sm" data-testid="lab-results">
                <thead className="bg-sand-100/70">
                  <tr>
                    {['Parameter', 'Measured', 'Configured range', 'Outcome', 'Method', 'Source', ''].map((header) => (
                      <th
                        key={header}
                        scope="col"
                        className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-soft"
                      >
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-sand-100">
                  {test.results.map((result) => {
                    const status = LAB_PARAMETER_STATUS_META[result.status] || LAB_PARAMETER_STATUS_META.NOT_EVALUATED;
                    return (
                      <tr key={result.id} data-parameter={result.parameter_code}>
                        <td className="px-4 py-3">
                          <span className="font-medium text-ink">{result.parameter_name}</span>
                          <span className="ml-2 text-xs text-ink-muted">{result.parameter_code}</span>
                        </td>
                        <td className="px-4 py-3 text-ink">{measurementText(result)}</td>
                        <td className="px-4 py-3 text-sm text-ink-soft">
                          {referenceText(result) || <span className="text-ink-muted">No range configured</span>}
                          {result.reference_source ? (
                            <span className="ml-1 text-xs text-ink-muted">({result.reference_source})</span>
                          ) : null}
                        </td>
                        <td className="px-4 py-3">
                          <Badge variant={status.variant} size="sm">
                            {status.label}
                          </Badge>
                        </td>
                        <td className="px-4 py-3 text-xs text-ink-muted">{result.method || '—'}</td>
                        <td className="px-4 py-3">
                          {(() => {
                            const source = measurementSourceMeta(result.measurement_source);
                            return (
                              <span
                                className="inline-flex flex-col gap-0.5"
                                title={source.hint || undefined}
                                data-measurement-source={result.measurement_source}
                              >
                                <Badge variant={source.variant} size="sm">
                                  {result.measurement_source_label || source.label}
                                </Badge>
                                {result.is_development_value ? (
                                  <span className="text-xs text-ink-muted">Not a laboratory reading</span>
                                ) : null}
                              </span>
                            );
                          })()}
                        </td>
                        <td className="px-4 py-3 text-right">
                          {canWrite && open ? (
                            <span className="flex justify-end gap-1">
                              <Button
                                size="sm"
                                variant="ghost"
                                aria-label={`Correct ${result.parameter_name}`}
                                onClick={() => setEditingResult(result)}
                              >
                                <Pencil size={14} />
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                aria-label={`Remove ${result.parameter_name}`}
                                loading={busy}
                                onClick={() => act(() => laboratoryService.deleteResult(test.id, result.id))}
                              >
                                <Trash2 size={14} />
                              </Button>
                            </span>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-ink-muted">{LAB_MESSAGES.resultsEmpty}</p>
          )}

          {test.missing_required_parameters?.length ? (
            <p className="text-xs text-ink-muted">
              Required and not yet recorded: {test.missing_required_parameters.join(', ')}. Until they
              are recorded, a completed test can only be inconclusive.
            </p>
          ) : null}

          {test.results.some((result) => result.is_development_value) ? (
            <Alert variant="info" title="Some values are development values, not measurements">
              The rows marked <strong>Development value</strong> were filled in by the platform while
              the project runs without connected laboratory instruments. They are there to be confirmed
              or replaced: type the real reading over one and it is stored as{' '}
              <strong>Entered by hand</strong>, with the change audited. Nothing here is presented as a
              laboratory measurement that was never taken.
            </Alert>
          ) : null}

          {/**
           * The quality analysis.
           *
           * Shown as its own block because it is its own step: the measurements are
           * what the laboratory recorded, the analysis is what the platform concluded
           * from them, and a reader has to be able to tell the two apart. The block
           * carries the model, its version and its source, the parameters it could
           * not judge, and its own stated limitations — never a bare "AI: OK".
           */}
          <div
            className="rounded-lg border border-sand-300 bg-sand-50/60 px-4 py-3"
            data-testid="lab-quality-analysis"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Brain size={16} className="text-ink-soft" aria-hidden="true" />
                <p className="text-sm font-semibold text-ink">Quality analysis</p>
                {analysisBadge ? (
                  <Badge variant={analysisBadge.variant} size="sm">
                    {analysisBadge.label}
                  </Badge>
                ) : (
                  <Badge variant="neutral" size="sm">
                    Not run
                  </Badge>
                )}
                {analysis?.risk_level ? (
                  <Badge variant="neutral" size="sm">
                    Risk: {analysis.risk_level}
                  </Badge>
                ) : null}
              </div>
              {canWrite && test.can_analyse ? (
                <Button
                  size="sm"
                  variant="secondary"
                  leftIcon={<Brain size={15} />}
                  loading={busy}
                  data-testid="analyse-with-ai"
                  onClick={() =>
                    act(() => laboratoryService.analyzeTest(test.id, { recompute: Boolean(analysis) }))
                  }
                >
                  {analysis ? 'Run the analysis again' : 'Analyse with AI'}
                </Button>
              ) : null}
            </div>

            {analysis ? (
              <div className="mt-3 space-y-2 text-sm text-ink-soft">
                <p>{analysis.explanation}</p>
                {analysis.recommendation ? <p>{analysis.recommendation}</p> : null}
                {analysis.vulnerabilities?.length ? (
                  <ul className="list-disc space-y-1 pl-5" data-testid="analysis-vulnerabilities">
                    {analysis.vulnerabilities.map((row) => (
                      <li key={row}>{row}</li>
                    ))}
                  </ul>
                ) : null}
                {analysis.isolation_remarks?.length ? (
                  <p className="text-xs text-ink-muted">
                    Recorded as remarks, not holds: {analysis.isolation_remarks.join(', ')}.
                  </p>
                ) : null}
                <dl className="grid gap-x-6 gap-y-1 text-xs text-ink-muted sm:grid-cols-2">
                  <div className="flex gap-1">
                    <dt>Model:</dt>
                    <dd className="text-ink-soft">
                      {analysis.model} {analysis.model_version}
                    </dd>
                  </div>
                  <div className="flex gap-1">
                    <dt>Source:</dt>
                    <dd className="text-ink-soft">{analysis.source}</dd>
                  </div>
                  <div className="flex gap-1">
                    <dt>Analysed:</dt>
                    <dd className="text-ink-soft">
                      {test.ai_analysed_at ? formatDateTime(test.ai_analysed_at) : '—'}
                      {test.ai_analysed_by ? ` by ${test.ai_analysed_by}` : ''}
                    </dd>
                  </div>
                  <div className="flex gap-1">
                    <dt>Judged:</dt>
                    <dd className="text-ink-soft">
                      {analysis.passed_parameters?.length || 0} inside range,{' '}
                      {analysis.abnormal_parameters?.length || 0} outside,{' '}
                      {analysis.inconclusive_parameters?.length || 0} not judgeable
                    </dd>
                  </div>
                </dl>
                {analysis.classifier ? (
                  <p className="text-xs text-ink-muted">{analysis.classifier}</p>
                ) : null}
                {analysis.limitations?.length ? (
                  <ul className="space-y-1 text-xs text-ink-muted" data-testid="analysis-limitations">
                    {analysis.limitations.map((row) => (
                      <li key={row}>{row}</li>
                    ))}
                  </ul>
                ) : null}
                {test.risk_override ? (
                  <Alert variant="warning" title="Released to packaging with a recorded risk">
                    {test.risk_override.user_name || 'A named user'} accepted the risks on{' '}
                    {formatDateTime(test.risk_override.at)}: {test.risk_override.reason}
                  </Alert>
                ) : null}
              </div>
            ) : (
              <p className="mt-2 text-sm text-ink-soft">
                No analysis has been run on this test yet. It reads the measured values and the
                configured ranges and says whether the batch may go to packaging — it never invents a
                value, and it is development decision-support rather than a certified method.
              </p>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            {canWrite && open ? (
              <Button
                size="sm"
                leftIcon={<CheckCircle2 size={15} />}
                onClick={() => setCompleteOpen(true)}
                disabled={!test.results.length && !test.is_override}
                data-testid="complete-test"
              >
                Complete test
              </Button>
            ) : null}
            {canWrite && (test.can_hold || test.can_proceed_with_risk) ? (
              <Button
                size="sm"
                variant="secondary"
                leftIcon={<PauseCircle size={15} />}
                data-testid="hold-batch"
                onClick={() => {
                  setHold({ reason: '', runAnalysis: Boolean(analysis) });
                  setHoldOpen(true);
                }}
              >
                Hold batch
              </Button>
            ) : null}
            {canWrite && test.can_proceed_with_risk ? (
              <Button
                size="sm"
                variant="danger"
                leftIcon={<AlertTriangle size={15} />}
                data-testid="proceed-anyway"
                onClick={() => {
                  setProceed({ confirmation: '', reason: '' });
                  setProceedOpen(true);
                }}
              >
                Proceed anyway
              </Button>
            ) : null}
            {canOverride ? (
              <Button
                size="sm"
                variant="secondary"
                leftIcon={<ShieldAlert size={15} />}
                onClick={() => setOverrideOpen(true)}
              >
                Override the outcome
              </Button>
            ) : null}
          </div>

          {!open ? (
            <p className="rounded-lg border border-sand-300 bg-sand-50 px-3 py-2 text-xs text-ink-soft">
              {test.status === 'HOLD'
                ? 'This test is on hold: it was closed without a decision, and the reason is recorded above. ' +
                  'The batch cannot be packed while it is held — a further test against the same batch releases it.'
                : 'This test is closed. Its recorded values and its result are read, never rewritten. A ' +
                  'retest opens a new round against the same batch and leaves this one exactly as it is.'}
            </p>
          ) : null}
        </CardBody>
      </Card>

      {/* Record a measurement */}
      <Modal
        open={resultForm.open}
        onClose={closeResultForm}
        title="Record a measured value"
        description="The number you enter is the number that is stored; the platform does not round or adjust it."
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={closeResultForm}
            >
              Close
            </Button>
            <Button
              size="sm"
              loading={busy}
              onClick={() => {
                // Checked before the request so nothing typed is lost to a 422: the
                // dialog stays open, says what is missing, and keeps the numbers.
                const errors = {};
                if (!resultForm.code) {
                  errors.code = 'Choose the measurement being recorded.';
                }
                if (wantsCustomParameter && !resultForm.parameterName.trim()) {
                  errors.parameterName =
                    'Name the measurement: "Other measurement" on its own records nothing.';
                }
                if (resultForm.value === '' || Number.isNaN(Number(resultForm.value))) {
                  errors.value = 'Enter the number the instrument reported.';
                }
                if (methodIsOther && !resultForm.methodOther.trim()) {
                  errors.methodOther = 'Describe how it was measured, or choose a listed method.';
                }
                setResultErrors(errors);
                if (Object.keys(errors).length) return;

                act(async () => {
                  await laboratoryService.recordResult(test.id, {
                    parameter_code: resultForm.code,
                    ...(wantsCustomParameter
                      ? { parameter_name: resultForm.parameterName.trim() }
                      : {}),
                    value: resultForm.value,
                    // The unit travels with the measurement only when the
                    // technician supplied it — otherwise the server applies the
                    // parameter's configured unit, which is the record of what the
                    // instrument reports in.
                    ...(wantsCustomParameter && resultForm.unit ? { unit: resultForm.unit } : {}),
                    ...(resultForm.method && !methodIsOther
                      ? { method: methodLabelFor(resultForm.method) || selectedMethodLabel(resultForm.method) }
                      : {}),
                    ...(methodIsOther && resultForm.methodOther.trim()
                      ? { method: resultForm.methodOther.trim() }
                      : {}),
                    ...(resultForm.remarks.trim() ? { remarks: resultForm.remarks.trim() } : {}),
                  });
                  setResultErrors({});
                  closeResultForm();
                });
              }}
            >
              Save the measurement
            </Button>
          </div>
        }
      >
        <div className="space-y-3">
          <Select
            label="Parameter"
            name="parameter_code"
            required
            value={resultForm.code}
            onChange={(event) =>
              setResultForm((form) => ({
                ...form,
                code: event.target.value,
                // A name typed for the previous choice belongs to that choice.
                parameterName: '',
                unit: '',
              }))
            }
            placeholder="Choose a parameter"
            error={resultErrors.code}
            hint="The catalogue the laboratory is configured with — nothing is typed by hand."
            options={available.map((parameter) => ({
              value: parameter.code,
              label: `${parameter.name} (${parameter.unit_label})${parameter.is_required ? ' — required' : ''}`,
            }))}
          />

          {wantsCustomParameter ? (
            <Input
              label="Specify the measurement"
              name="parameter_name"
              required
              value={resultForm.parameterName}
              onChange={(event) =>
                setResultForm((form) => ({ ...form, parameterName: event.target.value }))
              }
              placeholder="For example: residual sugar by the bench method"
              error={resultErrors.parameterName}
              hint="Stored as the name of this measurement on the test."
            />
          ) : null}

          <div className="grid gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <Input
              label="Measured value"
              name="value"
              type="number"
              step="0.0001"
              required
              value={resultForm.value}
              onChange={(event) => setResultForm((form) => ({ ...form, value: event.target.value }))}
              error={resultErrors.value}
              hint="The number the instrument reported. It is stored exactly as entered."
            />
            {wantsCustomParameter ? (
              <Select
                label="Unit"
                name="unit"
                value={resultForm.unit || selectedParameter?.unit || 'unitless'}
                onChange={(event) => setResultForm((form) => ({ ...form, unit: event.target.value }))}
                options={LAB_MEASURE_UNITS}
                hint="The units the platform stores, not a conversion."
              />
            ) : (
              <div>
                <p className="hc-label">Unit</p>
                <p
                  className="flex h-11 items-center rounded-lg border border-sand-300 bg-sand-100 px-3 text-sm text-ink-soft"
                  data-testid="measurement-unit"
                >
                  {selectedParameter?.unit_label || '—'}
                </p>
                <p className="mt-1 text-xs text-ink-muted">
                  Set by the parameter; the value is stored in it, never converted.
                </p>
              </div>
            )}
          </div>

          <SelectWithOther
            label="Method"
            name="method"
            value={resultForm.method}
            onChange={(event) =>
              setResultForm((form) => ({
                ...form,
                method: event.target.value,
                // A custom description belongs to the "Other" choice; replacing it
                // clears the text rather than leaving it attached to a listed method.
                methodOther: event.target.value === 'OTHER' ? form.methodOther : '',
              }))
            }
            options={methodOptions}
            otherValue={resultForm.methodOther}
            onOtherChange={(text) => setResultForm((form) => ({ ...form, methodOther: text }))}
            otherLabel="Custom Method"
            otherPlaceholder="For example: bench refractometer, second reading"
            error={resultErrors.methodOther}
            hint={
              selectedParameter?.methods?.length
                ? `The methods configured for ${selectedParameter.name}. Other lets you write one that is not on the list.`
                : 'How the measurement was taken. Other records the words you type.'
            }
          />

          <Input
            label="Remarks"
            name="remarks"
            value={resultForm.remarks}
            onChange={(event) => setResultForm((form) => ({ ...form, remarks: event.target.value }))}
            hint="Optional."
          />
          {selectedParameter && !selectedParameter.is_configured ? (
            <Alert variant="info">
              No reference range is configured for {selectedParameter.name}, so this measurement will be
              stored as recorded and marked <strong>Not evaluated</strong>. The platform does not invent
              a limit.
            </Alert>
          ) : null}
        </div>
      </Modal>

      {/* Correct a measurement */}
      <Modal
        open={Boolean(editingResult)}
        onClose={() => setEditingResult(null)}
        title="Correct a measured value"
        description="The value being replaced is written to the audit log with the correction."
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setEditingResult(null)}>
              Close
            </Button>
            <Button
              size="sm"
              loading={busy}
              onClick={() =>
                act(async () => {
                  await laboratoryService.updateResult(test.id, editingResult.id, {
                    value: editingResult.value,
                    correction_reason: 'Corrected while the test was open',
                  });
                  setEditingResult(null);
                })
              }
            >
              Save the correction
            </Button>
          </div>
        }
      >
        {editingResult ? (
          <div className="space-y-3">
            <p className="text-sm text-ink-soft">
              {editingResult.parameter_name} — recorded {measurementText(editingResult)}
            </p>
            <Input
              label="Corrected value"
              name="corrected_value"
              type="number"
              step="0.0001"
              value={editingResult.value}
              onChange={(event) => setEditingResult({ ...editingResult, value: event.target.value })}
            />
          </div>
        ) : null}
      </Modal>

      {/* Complete the test — the verdict is computed, not chosen */}
      <Modal
        open={completeOpen}
        onClose={() => setCompleteOpen(false)}
        title="Complete the test"
        description="The platform decides PASS, FAIL or INCONCLUSIVE from the recorded values and the configured ranges."
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setCompleteOpen(false)}>
              Close
            </Button>
            <Button
              size="sm"
              loading={busy}
              onClick={() =>
                act(
                  async () => {
                    await laboratoryService.completeTest(test.id, {
                      remarks: completeRemarks.trim() || undefined,
                    });
                    setCompleteOpen(false);
                    setCompleteRemarks('');
                    setDecision(null);
                  },
                  {
                    // A flagged test cannot be completed away. The server sends back
                    // what it found and the choices it allows; the dialog for them is
                    // opened here rather than an error being printed, because the
                    // technician has a decision to make and not a mistake to fix.
                    onRefusal: (refusal) => {
                      setCompleteOpen(false);
                      setDecision(refusal);
                      if ((refusal.details?.options || []).includes('proceed_with_risk')) {
                        setProceed({ confirmation: '', reason: '' });
                        setProceedOpen(true);
                      } else {
                        setHold({ reason: '', runAnalysis: Boolean(analysis) });
                        setHoldOpen(true);
                      }
                    },
                  },
                )
              }
            >
              Complete and decide
            </Button>
          </div>
        }
      >
        <div className="space-y-3">
          {test.missing_required_parameters?.length ? (
            <Alert
              variant="warning"
              title="This test is missing a required measurement"
              icon={<AlertCircle size={16} aria-hidden="true" />}
            >
              {test.missing_required_parameters.join(', ')}
              {test.missing_required_parameters.length === 1
                ? ' has not been recorded yet.'
                : ' have not been recorded yet.'}{' '}
              Completing without {test.missing_required_parameters.length === 1 ? 'it' : 'them'} leaves
              the test inconclusive — the batch stays in testing and cannot be packed. Record the
              measurement first if you have the result.
            </Alert>
          ) : null}
          <ul className="space-y-1 text-sm text-ink-soft">
            <li>
              Required parameters recorded: {test.required_parameters.length - test.missing_required_parameters.length} of{' '}
              {test.required_parameters.length || 0}
              {test.missing_required_parameters.length
                ? ` (missing: ${test.missing_required_parameters.join(', ')})`
                : ''}
            </li>
            <li>
              Measurements evaluated against a configured range:{' '}
              {test.results.filter((result) => result.evaluated).length} of {test.results.length}
            </li>
            <li>
              A required parameter that fails ⇒ the test fails. A required parameter that cannot be
              judged ⇒ the test is inconclusive, and the batch stays in testing.
            </li>
          </ul>
          <Input
            label="Remarks"
            name="complete_remarks"
            value={completeRemarks}
            onChange={(event) => setCompleteRemarks(event.target.value)}
            placeholder="Anything the record should carry"
          />
        </div>
      </Modal>

      {/**
       * Waiting / Hold.
       *
       * The laboratory is allowed to stop without deciding — a value is missing, a
       * reading is disputed, the sample needs re-taking. Holding is not deleting and
       * not failing: the measurements, the analysis and the reason all stay on the
       * test, the batch is blocked from packaging, and a further test releases it.
       * It needs a reason of its own, because "on hold" with no explanation is the
       * state a reviewer cannot act on.
       */}
      <Modal
        open={holdOpen}
        onClose={() => setHoldOpen(false)}
        title="Hold the batch"
        description="Stops the test without deciding it. The measurements, the analysis and your reason are kept, the batch cannot be packed while it is on hold, and a further test releases it."
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setHoldOpen(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              loading={busy}
              disabled={hold.reason.trim().length < 3}
              data-testid="confirm-hold"
              onClick={() =>
                act(
                  async () => {
                    await laboratoryService.holdTest(test.id, {
                      reason: hold.reason.trim(),
                      runAnalysis: hold.runAnalysis,
                    });
                    setHoldOpen(false);
                    setDecision(null);
                    setHold({ reason: '', runAnalysis: false });
                  },
                  {
                    onRefusal: (refusal) => {
                      setHoldOpen(false);
                      setDecision(refusal);
                    },
                  },
                )
              }
            >
              Hold the batch
            </Button>
          </div>
        }
      >
        <div className="space-y-3">
          {decision?.details?.vulnerabilities?.length ? (
            <Alert
              variant="warning"
              title="What the analysis found"
              icon={<AlertTriangle size={16} aria-hidden="true" />}
            >
              <ul className="list-disc space-y-1 pl-4">
                {decision.details.vulnerabilities.map((row) => (
                  <li key={row}>{row}</li>
                ))}
              </ul>
            </Alert>
          ) : null}
          <Input
            label="Reason for the hold"
            name="hold_reason"
            required
            value={hold.reason}
            onChange={(event) => setHold((form) => ({ ...form, reason: event.target.value }))}
            placeholder="For example: moisture above the configured range; resampling from the apiary."
            hint="Stored on the test and shown to the beekeeper, the officer and the packaging unit."
            error={hold.reason.length > 0 && hold.reason.trim().length < 3 ? 'Use at least 3 characters.' : null}
          />
          <label className="flex items-start gap-2 text-sm text-ink-soft">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={hold.runAnalysis}
              onChange={(event) => setHold((form) => ({ ...form, runAnalysis: event.target.checked }))}
            />
            <span>
              Analyse the recorded values first, so the hold names what it is waiting for.
            </span>
          </label>
        </div>
      </Modal>

      {/**
       * Proceed anyway.
       *
       * The temporary development override. It is offered only when the server says
       * it is available (`risk_override_available`, which depends on the
       * installation's setting), it shows the risks being accepted, and it demands
       * the confirmation word the server published — checked there as well, so the
       * dialog is a courtesy rather than the control. What is stored is
       * PROCEEDED_WITH_RISK: the risks, the analysis and the person, all audited.
       */}
      <Modal
        open={proceedOpen}
        onClose={() => setProceedOpen(false)}
        title="Proceed anyway, with the risk recorded"
        description="Releases the batch to packaging although the analysis flagged it. This is a deliberate act: it is stored as proceeding with a recorded risk, with the analysis and your name attached, and it is written to the audit log."
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setProceedOpen(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              variant="danger"
              loading={busy}
              disabled={
                proceed.reason.trim().length < 10 ||
                proceed.confirmation.trim() !== (test.confirmation_word || 'PROCEED')
              }
              data-testid="confirm-proceed"
              onClick={() =>
                act(async () => {
                  await laboratoryService.proceedWithRisk(test.id, {
                    confirmation: proceed.confirmation.trim(),
                    reason: proceed.reason.trim(),
                  });
                  setProceedOpen(false);
                  setDecision(null);
                  setProceed({ confirmation: '', reason: '' });
                })
              }
            >
              Record the risk and proceed
            </Button>
          </div>
        }
      >
        <div className="space-y-3">
          <Alert
            variant="danger"
            title="This does not change the measurements"
            icon={<AlertTriangle size={16} aria-hidden="true" />}
          >
            The test keeps the outcome its measurements produced. The batch is released to packaging
            with the risk on the record, and the risk is visible to every role that reads it.
          </Alert>
          {decision?.details?.vulnerabilities?.length || analysis?.vulnerabilities?.length ? (
            <div>
              <p className="text-sm font-semibold text-ink">Risks being accepted</p>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-ink-soft">
                {(decision?.details?.vulnerabilities || analysis?.vulnerabilities || []).map((row) => (
                  <li key={row}>{row}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <Input
            label="Reason for proceeding"
            name="proceed_reason"
            required
            value={proceed.reason}
            onChange={(event) => setProceed((form) => ({ ...form, reason: event.target.value }))}
            placeholder="For example: the buyer accepted the deviation in writing; pilot batch."
            hint="At least 10 characters. This is what a reviewer will read."
          />
          <Input
            label="Type the confirmation word"
            name="confirmation"
            required
            value={proceed.confirmation}
            onChange={(event) => setProceed((form) => ({ ...form, confirmation: event.target.value }))}
            placeholder={test.confirmation_word || 'PROCEED'}
            hint={`Type ${test.confirmation_word || 'PROCEED'} to confirm. A stray click cannot do this.`}
            error={
              proceed.confirmation.length > 0 &&
              proceed.confirmation.trim() !== (test.confirmation_word || 'PROCEED')
                ? `Type ${test.confirmation_word || 'PROCEED'} exactly.`
                : null
            }
          />
        </div>
      </Modal>

      {/* Administrator override */}
      <Modal
        open={overrideOpen}
        onClose={() => setOverrideOpen(false)}
        title="Override the outcome"
        description="An override is an administrative act: it is restricted to administrators, requires a reason, and is audited with the computed result it replaced."
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setOverrideOpen(false)}>
              Close
            </Button>
            <Button
              size="sm"
              variant="danger"
              loading={busy}
              disabled={!override.result || override.reason.trim().length < 10}
              onClick={() =>
                act(async () => {
                  await laboratoryService.overrideTest(test.id, {
                    overallResult: override.result,
                    reason: override.reason.trim(),
                  });
                  setOverrideOpen(false);
                  setOverride({ result: '', reason: '' });
                })
              }
            >
              Record the override
            </Button>
          </div>
        }
      >
        <div className="space-y-3">
          <p className="text-sm text-ink-soft">
            The platform computed <strong>{test.overall_result_label || test.overall_result}</strong> from
            the recorded values. The override is stored alongside it, never in place of it.
          </p>
          <Select
            label="Outcome"
            name="override_result"
            placeholder="Select outcome"
            value={override.result}
            onChange={(event) => setOverride({ ...override, result: event.target.value })}
            options={[
              { value: 'PASS', label: 'Pass' },
              { value: 'FAIL', label: 'Fail' },
              { value: 'INCONCLUSIVE', label: 'Inconclusive' },
            ]}
          />
          <Input
            label="Reason"
            name="override_reason"
            value={override.reason}
            onChange={(event) => setOverride({ ...override, reason: event.target.value })}
            hint="At least 10 characters — this is what a reviewer will read."
            required
          />
        </div>
      </Modal>
    </div>
  );
}

export default LabTestPanel;
