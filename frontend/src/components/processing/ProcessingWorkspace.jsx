import { useCallback, useEffect, useMemo, useState } from 'react';
import { Factory, Inbox, RefreshCw, UserCheck, Warehouse } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import { SelectWithOther } from '@/components/ui/SelectWithOther';
import { StatCard } from '@/components/common/StatCard';
import { AssignmentDialog } from '@/components/common/AssignmentDialog';
import { AwaitingProcessingTable } from '@/components/processing/AwaitingProcessingTable';
import { PendingBatchTable } from '@/components/processing/PendingBatchTable';
import { ProcessingQueueTable } from '@/components/processing/ProcessingQueueTable';
import { ProcessingRunPanel } from '@/components/processing/ProcessingRunPanel';
import { ProcessingRunTable } from '@/components/processing/ProcessingRunTable';
import { PROCESSING_MESSAGES, PROCESSING_STATUS_META, PROCESSING_TYPES } from '@/constants/processing';
import { ROLES } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';
import * as processingService from '@/services/processingService';
import { normaliseError } from '@/utils/errors';

/**
 * The processing workspace.
 *
 * One component, three audiences, and the difference between them is a permission
 * rather than a page: a **processor** works the queue (open a run, start it, record
 * what was measured, complete it), an **administrator** can do the same, and a
 * **KVIC officer** reads the identical rows for the clusters they oversee with no
 * actions rendered at all.
 *
 * Nothing here creates a second copy of a batch. A run points at the batch; the
 * batch's status is moved by the server through its transition table.
 */

/** The copy for each queue view, kept in one place so the wording cannot drift. */
const QUEUE_COPY = {
  pending: {
    title: 'Pending batches',
    description:
      'Open runs nobody is responsible for yet, and collected batches with no run at all. Nothing here is lost work.',
    empty: 'No batches are waiting for a processor.',
  },
  assigned: {
    title: 'Assigned batches',
    description:
      'Work allocated to a named processor. A processor sees their own; an administrator sees every allocation in scope.',
    empty: 'Nothing is allocated to a processor right now.',
  },
  processing: {
    title: 'Processing',
    description: 'Runs that have been started and are being worked on.',
    empty: 'No run is under way at the moment.',
  },
  completed: {
    title: 'Completed processing',
    description:
      'Runs that finished: the honey was measured in and out, and the batch left for the laboratory.',
    empty: 'No processing run has been completed yet.',
  },
  history: {
    title: 'Processing history',
    description:
      'Every run recorded, newest first — including cancelled ones, which are kept rather than deleted.',
    empty: 'No processing runs recorded yet.',
  },
};

export function ProcessingWorkspace({ role = ROLES.PROCESSOR, view = 'overview', basePath = '/processor' }) {
  const { user } = useAuth();
  const canWrite = role === ROLES.PROCESSOR || role === ROLES.ADMIN;
  const isStaff = role === ROLES.KVIC_OFFICER;

  const [summary, setSummary] = useState(null);
  const [awaiting, setAwaiting] = useState([]);
  const [awaitingMeta, setAwaitingMeta] = useState(null);
  const [runs, setRuns] = useState([]);
  const [runsMeta, setRunsMeta] = useState(null);
  const [units, setUnits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [runFilters, setRunFilters] = useState({ page: 1, search: '', status: '' });
  const [selectedBatch, setSelectedBatch] = useState(null);
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [unitForm, setUnitForm] = useState({ open: false, name: '', location: '', registration_identifier: '' });
  const [unitError, setUnitError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState([]);
  const [pendingMeta, setPendingMeta] = useState(null);
  const [assigned, setAssigned] = useState([]);
  const [assignedMeta, setAssignedMeta] = useState(null);
  const [inProgress, setInProgress] = useState([]);
  const [completedRuns, setCompletedRuns] = useState([]);
  const [historyRuns, setHistoryRuns] = useState([]);
  const [busyRunId, setBusyRunId] = useState(null);
  const [assignTarget, setAssignTarget] = useState(null);
  const [processors, setProcessors] = useState([]);
  const [processorsLoading, setProcessorsLoading] = useState(false);
  const [processorsError, setProcessorsError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [notice, setNotice] = useState(null);
  // One page number per queue: paging the completed list must not move the
  // assigned list underneath the reader.
  const [awaitingPage, setAwaitingPage] = useState(1);
  const [pendingPage, setPendingPage] = useState(1);
  const [assignedPage, setAssignedPage] = useState(1);
  const [processingPage, setProcessingPage] = useState(1);
  const [completedPage, setCompletedPage] = useState(1);
  const [historyPage, setHistoryPage] = useState(1);

  // Each queue is its own view, and the dashboard shows them all at once. The
  // list of queues lives in one place rather than being spelled out per branch.
  const queueViews = ['overview', 'pending', 'assigned', 'processing', 'completed', 'history'];
  const wantsAwaiting = view === 'overview' || view === 'awaiting';
  const wantsPending = queueViews.includes(view);
  const wantsAssigned = queueViews.includes(view);
  const wantsProcessing = queueViews.includes(view);
  const wantsCompleted = queueViews.includes(view);
  const wantsHistory = view === 'history' || view === 'overview';
  const wantsRuns = view === 'runs';
  const wantsUnits = view === 'overview' || view === 'units';
  const canAssignOthers = role === ROLES.ADMIN;

  const load = useCallback(
    async ({ silent = false } = {}) => {
      if (silent) setRefreshing(true);
      else setLoading(true);
      setError(null);
      const queuePageSize = view === 'overview' ? 5 : 25;
      try {
        const [
          counters,
          queue,
          runList,
          unitList,
          pendingList,
          assignedList,
          processingList,
          completedList,
          historyList,
        ] = await Promise.all([
          processingService.getProcessingSummary(),
          wantsAwaiting
            ? processingService.listBatchesAwaitingProcessing({
                pageSize: view === 'awaiting' ? 50 : 5,
                page: awaitingPage,
              })
            : Promise.resolve({ batches: [], meta: null }),
          wantsRuns
            ? processingService.listRuns({
                page: runFilters.page,
                pageSize: 20,
                search: runFilters.search || undefined,
                status: runFilters.status || undefined,
              })
            : Promise.resolve({ runs: [], meta: null }),
          wantsUnits ? processingService.listUnits() : Promise.resolve({ units: [] }),
          wantsPending
            ? processingService.listPendingAssignments({ pageSize: queuePageSize, page: pendingPage })
            : Promise.resolve({ runs: [], meta: null }),
          wantsAssigned
            ? processingService.listAssignedRuns({
                pageSize: queuePageSize,
                page: assignedPage,
                mineOnly: role === ROLES.PROCESSOR,
              })
            : Promise.resolve({ runs: [], meta: null }),
          wantsProcessing
            ? processingService.listRuns({
                pageSize: queuePageSize,
                page: processingPage,
                status: 'IN_PROGRESS',
              })
            : Promise.resolve({ runs: [], meta: null }),
          wantsCompleted
            ? processingService.listCompletedRuns({ pageSize: queuePageSize, page: completedPage })
            : Promise.resolve({ runs: [], meta: null }),
          wantsHistory
            ? processingService.listRuns({ pageSize: queuePageSize, page: historyPage })
            : Promise.resolve({ runs: [], meta: null }),
        ]);
        setSummary(counters);
        setAwaiting(queue.batches);
        setAwaitingMeta(queue.meta);
        setRuns(runList.runs);
        setRunsMeta(runList.meta);
        setUnits(unitList.units);
        setPending(pendingList.runs);
        setPendingMeta(pendingList.meta);
        setAssigned(assignedList.runs);
        setAssignedMeta(assignedList.meta);
        setInProgress(processingList.runs);
        setCompletedRuns(completedList.runs);
        setHistoryRuns(historyList.runs);
      } catch (caught) {
        setError(normaliseError(caught));
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [
      runFilters,
      view,
      role,
      wantsAwaiting,
      wantsRuns,
      wantsUnits,
      wantsPending,
      wantsAssigned,
      wantsProcessing,
      wantsCompleted,
      wantsHistory,
      awaitingPage,
      pendingPage,
      assignedPage,
      processingPage,
      completedPage,
      historyPage,
    ],
  );

  useEffect(() => {
    load();
  }, [load]);

  // Who may take this work is the server's answer, not the UI's: the list of
  // eligible accounts comes from the same endpoint the allocation validates
  // against, so an account the server would refuse is never offered. This replaced
  // a call to the administration directory, which only an administrator may read —
  // which is why a processor could not open this dialog at all before.
  const openAssign = useCallback(
    async (row) => {
      setAssignTarget(row);
      setActionError(null);
      setProcessorsLoading(true);
      setProcessorsError(null);
      try {
        setProcessors(await processingService.listEligibleProcessors());
      } catch (caught) {
        setProcessorsError(normaliseError(caught));
      } finally {
        setProcessorsLoading(false);
      }
    },
    [],
  );

  const runAction = useCallback(
    async (row, action, successMessage) => {
      setBusyRunId(row.id ?? row.batch_id);
      setActionError(null);
      try {
        const detail = await action();
        await load({ silent: true });
        // The panel shows the record the server returned; nothing is inferred here.
        if (successMessage) setNotice({ message: successMessage, runCode: detail?.processing_code });
      } catch (caught) {
        setActionError(normaliseError(caught));
      } finally {
        setBusyRunId(null);
      }
    },
    [load],
  );

  const unitEntries = useMemo(() => Object.entries(summary?.by_unit || {}), [summary]);

  const openRun = async () => {
    if (!selectedBatch) return;
    // The type is a choice the processor makes; nothing is sent on their behalf.
    if (!unitForm.type) {
      setUnitError({ message: 'Select the processing type.' });
      return;
    }
    if (unitForm.type === 'OTHER' && !(unitForm.type_other || '').trim()) {
      setUnitError({ message: 'Describe the processing type you selected as Other.' });
      return;
    }
    setBusy(true);
    setUnitError(null);
    try {
      const created = await processingService.createRun({
        batch_id: selectedBatch.id,
        processing_type: unitForm.type,
        ...(unitForm.type === 'OTHER' ? { processing_type_other: unitForm.type_other.trim() } : {}),
        ...(unitForm.unit_id ? { processing_unit_id: unitForm.unit_id } : {}),
      });
      setSelectedBatch(null);
      setSelectedRunId(created.id);
      await load({ silent: true });
    } catch (caught) {
      setUnitError(normaliseError(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      {view === 'overview' ? (
        <section aria-label="Processing summary" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Awaiting processing"
            value={summary?.awaiting_processing ?? '—'}
            helper="Batches at COLLECTED in your scope"
            icon={<Factory size={16} />}
            tone="honey"
            loading={loading}
          />
          <StatCard
            label="Runs in progress"
            value={summary?.in_progress ?? '—'}
            helper={`${summary?.pending ?? 0} opened, not started`}
            icon={<RefreshCw size={16} />}
            loading={loading}
          />
          <StatCard
            label="Completed runs"
            value={summary?.completed ?? '—'}
            helper="Ready for the laboratory"
            icon={<Factory size={16} />}
            tone="forest"
            loading={loading}
          />
          <StatCard
            label="Awaiting laboratory"
            value={summary?.awaiting_laboratory ?? '—'}
            helper="Batches at LAB_TESTING"
            icon={<Warehouse size={16} />}
            loading={loading}
          />
          <StatCard
            label="Waiting for a processor"
            value={summary?.unassigned ?? '—'}
            helper="Open runs nobody is responsible for"
            icon={<Inbox size={16} />}
            tone="honey"
            loading={loading}
          />
          <StatCard
            label="Assigned to me"
            value={summary?.mine ?? '—'}
            helper={`${summary?.mine_accepted ?? 0} accepted`}
            icon={<UserCheck size={16} />}
            loading={loading}
          />
          <StatCard
            label="Allocated, not accepted"
            value={summary?.assigned ?? '—'}
            helper={`${summary?.accepted ?? 0} accepted in total`}
            icon={<UserCheck size={16} />}
            loading={loading}
          />
          <StatCard
            label="Cancelled runs"
            value={summary?.cancelled ?? '—'}
            helper="Kept as history, never deleted"
            icon={<RefreshCw size={16} />}
            loading={loading}
          />
        </section>
      ) : null}

      {view === 'overview' && unitEntries.length ? (
        <Card>
          <CardHeader
            title="Measured quantities by unit"
            description="Totals of the input and output quantities actually recorded — never an assumed loss."
          />
          <CardBody>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-sand-200 text-sm">
                <thead className="bg-sand-100/70">
                  <tr>
                    {['Unit', 'Input', 'Output', 'Difference', 'Runs with both measured'].map((header) => (
                      <th
                        key={header}
                        scope="col"
                        className={`px-4 py-2 text-xs font-semibold uppercase tracking-wide text-ink-soft ${
                          header === 'Unit' ? 'text-left' : 'text-right'
                        }`}
                      >
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-sand-100">
                  {unitEntries.map(([label, totals]) => (
                    <tr key={label}>
                      <td className="px-4 py-3 font-medium text-ink">{label}</td>
                      <td className="px-4 py-3 text-right">{Number(totals.input ?? 0).toLocaleString()}</td>
                      <td className="px-4 py-3 text-right">{Number(totals.output ?? 0).toLocaleString()}</td>
                      <td className="px-4 py-3 text-right">{Number(totals.loss ?? 0).toLocaleString()}</td>
                      <td className="px-4 py-3 text-right text-ink-soft">{totals.runs ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardBody>
        </Card>
      ) : null}

      {wantsAwaiting ? (
        <Card>
          <CardHeader
            title={view === 'awaiting' ? 'Batches awaiting processing' : 'Next in the queue'}
            description={
              isStaff
                ? 'Batches in the clusters you oversee, waiting for processing. Read-only.'
                : 'Collected batches in your scope. Opening a run does not change the batch until you start it.'
            }
            icon={<Factory size={18} aria-hidden="true" />}
            action={
              view === 'awaiting' && canWrite ? (
                <span className="text-xs text-ink-muted">Open a run from any row to begin.</span>
              ) : null
            }
          />
          <CardBody className="space-y-4">
            {actionError ? <Alert variant="danger">{actionError.message}</Alert> : null}
            {notice ? (
              <Alert variant="success">
                {notice.runCode ? `${notice.runCode}: ` : ''}
                {notice.message}
              </Alert>
            ) : null}
            {isStaff ? (
              // A cluster officer reads the same rows with no actions at all.
              <AwaitingProcessingTable
                batches={awaiting}
                loading={loading}
                error={error}
                onRetry={() => load()}
                meta={awaitingMeta}
                onPageChange={setAwaitingPage}
                onOpenRun={null}
              />
            ) : (
              <PendingBatchTable
                batches={awaiting}
                loading={loading}
                error={error}
                onRetry={() => load()}
                meta={awaitingMeta}
                onPageChange={setAwaitingPage}
                canWrite={canWrite}
                busyId={busyRunId}
                onTakeOn={(row) =>
                  runAction(
                    row,
                    () =>
                      processingService.assignBatchToProcessor(row.batch_id, user?.id).then((detail) =>
                        processingService.acceptRun(detail.id).then((accepted) => accepted),
                      ),
                    'Batch taken on — the run is yours and accepted.',
                  )
                }
                onAssign={canWrite ? openAssign : null}
                onOpenRun={(row) => setSelectedRunId(row.open_processing_id)}
              />
            )}
          </CardBody>
        </Card>
      ) : null}

      {['pending', 'assigned', 'processing', 'completed', 'history'].map((queueView) => {
        if (view !== queueView) return null;
        const copy = QUEUE_COPY[queueView];
        const rows =
          queueView === 'pending'
            ? pending
            : queueView === 'assigned'
              ? assigned
              : queueView === 'processing'
                ? inProgress
                : queueView === 'completed'
                  ? completedRuns
                  : historyRuns;
        const pageSetter = {
          pending: setPendingPage,
          assigned: setAssignedPage,
          processing: setProcessingPage,
          completed: setCompletedPage,
          history: setHistoryPage,
        }[queueView];
        const queueMeta = {
          pending: pendingMeta,
          assigned: assignedMeta,
          processing: null,
          completed: null,
          history: null,
        }[queueView];
        return (
          <Card key={queueView}>
            <CardHeader
              title={copy.title}
              description={copy.description}
              icon={<Factory size={18} aria-hidden="true" />}
              action={
                <Button variant="secondary" size="sm" onClick={() => load({ silent: true })} loading={refreshing}>
                  Refresh
                </Button>
              }
            />
            <CardBody className="space-y-4">
              {actionError ? <Alert variant="danger">{actionError.message}</Alert> : null}
              {notice ? (
                <Alert variant="success">
                  {notice.runCode ? `${notice.runCode}: ` : ''}
                  {notice.message}
                </Alert>
              ) : null}
              <ProcessingQueueTable
                runs={rows}
                loading={loading}
                error={error}
                onRetry={() => load()}
                meta={queueMeta}
                onPageChange={pageSetter}
                detailPath={`${basePath}/runs`}
                busyId={busyRunId}
                onAssign={canWrite ? openAssign : null}
                onAccept={
                  canWrite
                    ? (row) =>
                        runAction(row, () => processingService.acceptRun(row.id), 'Work accepted.')
                    : null
                }
                onStart={
                  canWrite
                    ? (row) =>
                        runAction(row, () => processingService.startRun(row.id), 'Processing started.')
                    : null
                }
                onComplete={canWrite ? (row) => setSelectedRunId(row.id) : null}
                onOpen={(row) => setSelectedRunId(row.id)}
                emptyTitle={copy.empty}
              />
            </CardBody>
          </Card>
        );
      })}

      {view === 'overview'
        ? [
            { key: 'pending', title: 'Waiting for a processor', rows: pending, meta: pendingMeta, setter: setPendingPage, empty: QUEUE_COPY.pending.empty },
            { key: 'assigned', title: 'Assigned to me', rows: assigned, meta: assignedMeta, setter: setAssignedPage, empty: QUEUE_COPY.assigned.empty },
          ].map((section) => (
            <Card key={section.key}>
              <CardHeader
                title={section.title}
                description="The newest five rows. Open the queue for the full list and its filters."
                icon={<UserCheck size={18} aria-hidden="true" />}
                action={
                  <Button variant="secondary" size="sm" onClick={() => load({ silent: true })} loading={refreshing}>
                    Refresh
                  </Button>
                }
              />
              <CardBody className="space-y-4">
                {actionError ? <Alert variant="danger">{actionError.message}</Alert> : null}
                <ProcessingQueueTable
                  runs={section.rows}
                  loading={loading}
                  error={error}
                  onRetry={() => load()}
                  meta={section.meta}
                  onPageChange={section.setter}
                  detailPath={`${basePath}/runs`}
                  busyId={busyRunId}
                  onAssign={canWrite ? openAssign : null}
                  onAccept={
                    canWrite
                      ? (row) => runAction(row, () => processingService.acceptRun(row.id), 'Work accepted.')
                      : null
                  }
                  onStart={
                    canWrite
                      ? (row) => runAction(row, () => processingService.startRun(row.id), 'Processing started.')
                      : null
                  }
                  onComplete={canWrite ? (row) => setSelectedRunId(row.id) : null}
                  onOpen={(row) => setSelectedRunId(row.id)}
                  emptyTitle={section.empty}
                />
              </CardBody>
            </Card>
          ))
        : null}

      {wantsRuns ? (
        <Card>
          <CardHeader
            title="Processing runs"
            description="Every run recorded in your scope, with the quantities measured on it."
            icon={<Factory size={18} aria-hidden="true" />}
            action={
              <Button variant="secondary" size="sm" onClick={() => load({ silent: true })} loading={refreshing}>
                Refresh
              </Button>
            }
          />
          <CardBody className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Input
                label="Search"
                name="run_search"
                value={runFilters.search}
                onChange={(event) => setRunFilters((f) => ({ ...f, search: event.target.value, page: 1 }))}
                placeholder="Run or batch code"
              />
              <Select
                label="Status"
                name="run_status"
                value={runFilters.status}
                onChange={(event) => setRunFilters((f) => ({ ...f, status: event.target.value, page: 1 }))}
                placeholder="Any status"
                options={Object.entries(PROCESSING_STATUS_META).map(([value, meta]) => ({
                  value,
                  label: meta.label,
                }))}
              />
            </div>
            <ProcessingRunTable
              runs={runs}
              loading={loading}
              error={error}
              onRetry={() => load()}
              meta={runsMeta}
              onPageChange={(page) => setRunFilters((f) => ({ ...f, page }))}
              detailPath={`${basePath}/runs`}
              // An administrator allocates work from this list; a processor takes
              // it on personally here, exactly as in the queues. Both go through
              // the same dialog and the same endpoint.
              onAssign={canWrite ? openAssign : null}
              busyId={busyRunId}
            />
          </CardBody>
        </Card>
      ) : null}

      {wantsUnits ? (
        <Card>
          <CardHeader
            title="Processing units"
            description="Where the work happens. A unit is read from the registry, never invented per run."
            icon={<Warehouse size={18} aria-hidden="true" />}
            action={
              canWrite ? (
                <Button size="sm" variant="secondary" onClick={() => setUnitForm((f) => ({ ...f, open: true }))}>
                  Register a unit
                </Button>
              ) : null
            }
          />
          <CardBody>
            {units.length ? (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-sand-200 text-sm">
                  <thead className="bg-sand-100/70">
                    <tr>
                      {['Code', 'Name', 'Location', 'Status', 'Runs'].map((header) => (
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
                    {units.map((unit) => (
                      <tr key={unit.id}>
                        <td className="px-4 py-3 font-mono text-xs text-ink-soft">{unit.unit_code}</td>
                        <td className="px-4 py-3 font-medium text-ink">{unit.name}</td>
                        <td className="px-4 py-3 text-ink-soft">{unit.location || '—'}</td>
                        <td className="px-4 py-3 text-ink-soft">{unit.status_label || unit.status}</td>
                        <td className="px-4 py-3 text-ink-soft">{unit.processing_run_count ?? 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-sm text-ink-muted">{PROCESSING_MESSAGES.emptyUnits}</p>
            )}
          </CardBody>
        </Card>
      ) : null}

      {/* Open a run against a collected batch */}
      <Modal
        open={Boolean(selectedBatch)}
        onClose={() => setSelectedBatch(null)}
        title="Open a processing run"
        description="The batch stays COLLECTED until you start the run. No quantities are recorded here — those are measured."
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setSelectedBatch(null)}>
              Close
            </Button>
            <Button size="sm" loading={busy} onClick={openRun}>
              Open run
            </Button>
          </div>
        }
      >
        {selectedBatch ? (
          <div className="space-y-4">
            <dl className="divide-y divide-sand-100 text-sm">
              <div className="flex justify-between py-1.5">
                <dt className="text-ink-muted">Batch</dt>
                <dd className="font-mono text-ink">{selectedBatch.batch_code}</dd>
              </div>
              <div className="flex justify-between py-1.5">
                <dt className="text-ink-muted">Quantity</dt>
                <dd className="text-ink">
                  {Number(selectedBatch.quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })}{' '}
                  {selectedBatch.unit_label}
                </dd>
              </div>
              <div className="flex justify-between py-1.5">
                <dt className="text-ink-muted">Collection</dt>
                <dd className="text-ink">{selectedBatch.collection_code || '—'}</dd>
              </div>
            </dl>
            <SelectWithOther
              label="Processing type"
              name="open_run_type"
              required
              placeholder="Select processing type"
              value={unitForm.type || ''}
              onChange={(event) => setUnitForm((f) => ({ ...f, type: event.target.value }))}
              options={PROCESSING_TYPES}
              otherValue={unitForm.type_other || ''}
              onOtherChange={(value) => setUnitForm((f) => ({ ...f, type_other: value }))}
              otherLabel="Specify the processing type"
            />
            <Select
              label="Processing unit"
              name="open_run_unit"
              value={unitForm.unit_id || ''}
              onChange={(event) => setUnitForm((f) => ({ ...f, unit_id: event.target.value }))}
              placeholder="No facility recorded"
              options={units.map((unit) => ({ value: unit.id, label: `${unit.name} (${unit.unit_code})` }))}
            />
            {unitError ? (
              <Alert variant="danger">{unitError.message}</Alert>
            ) : null}
            <p className="text-xs text-ink-muted">
              Registering a unit is a separate step: a run may record that no facility was used, but it
              may not invent one.
            </p>
          </div>
        ) : null}
      </Modal>

      {/*
        Handing work over. An administrator chooses from the processor accounts the
        platform holds; a processor can only take work on personally — which is what
        the dialog offers them, and what the server enforces either way.
      */}
      <AssignmentDialog
        open={Boolean(assignTarget)}
        onClose={() => setAssignTarget(null)}
        title={assignTarget?.processing_code ? `Assign ${assignTarget.processing_code}` : 'Assign a batch'}
        description={
          assignTarget?.batch_code
            ? `Batch ${assignTarget.batch_code}. The processor is named here; the batch's own record is not touched.`
            : 'The work is allocated to a named processor, who accepts it before starting.'
        }
        assigneeLabel="Processor"
        people={processors}
        peopleLoading={processorsLoading}
        peopleError={processorsError}
        currentAssigneeId={assignTarget?.processor_id || null}
        selfOption={
          canAssignOthers || !user
            ? null
            : {
                id: user.id,
                label: 'Assign to me',
                helper: 'A processor can take unallocated work on personally; an administrator allocates to other people.',
              }
        }
        emptyHint="No processor account is available yet. An administrator creates one in Administration → Users."
        onAssign={async (processorId) => {
          const target = assignTarget;
          if (!target) return;
          if (target.batch_id && !target.open_processing_id && !target.processing_code) {
            // A batch row from the pending list: the run is opened by the server.
            const detail = await processingService.assignBatchToProcessor(target.batch_id, processorId);
            setNotice({ message: 'Batch allocated.', runCode: detail?.processing_code });
          } else {
            const detail = await processingService.assignRun(target.id, processorId);
            setNotice({ message: 'Work allocated.', runCode: detail?.processing_code });
          }
          await load({ silent: true });
        }}
      />

      {/* Register a unit */}
      <Modal
        open={unitForm.open}
        onClose={() => setUnitForm({ open: false, name: '', location: '', registration_identifier: '' })}
        title="Register a processing unit"
        description="The server issues the unit code; nothing here can set it."
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setUnitForm({ open: false, name: '', location: '', registration_identifier: '' })}
            >
              Close
            </Button>
            <Button
              size="sm"
              loading={busy}
              onClick={async () => {
                setBusy(true);
                setUnitError(null);
                try {
                  await processingService.createUnit({
                    name: unitForm.name.trim(),
                    ...(unitForm.location ? { location: unitForm.location } : {}),
                    ...(unitForm.registration_identifier
                      ? { registration_identifier: unitForm.registration_identifier }
                      : {}),
                  });
                  setUnitForm({ open: false, name: '', location: '', registration_identifier: '' });
                  await load({ silent: true });
                } catch (caught) {
                  setUnitError(normaliseError(caught));
                } finally {
                  setBusy(false);
                }
              }}
              disabled={unitForm.name.trim().length < 2}
            >
              Register
            </Button>
          </div>
        }
      >
        <div className="space-y-3">
          <Input
            label="Name"
            name="unit_name"
            value={unitForm.name}
            onChange={(event) => setUnitForm((f) => ({ ...f, name: event.target.value }))}
            placeholder="For example: Guntur honey processing unit"
            required
          />
          <Input
            label="Location"
            name="unit_location"
            value={unitForm.location}
            onChange={(event) => setUnitForm((f) => ({ ...f, location: event.target.value }))}
            placeholder="Village, district"
          />
          <Input
            label="Registration identifier"
            name="unit_registration"
            value={unitForm.registration_identifier}
            onChange={(event) => setUnitForm((f) => ({ ...f, registration_identifier: event.target.value }))}
            hint="Optional. Recorded as stated; the platform does not verify it."
          />
          {unitError ? <Alert variant="danger">{unitError.message}</Alert> : null}
        </div>
      </Modal>

      {/* A run opened from the queue, right where it was opened */}
      <Modal
        open={Boolean(selectedRunId)}
        onClose={() => setSelectedRunId(null)}
        title="Processing run"
        size="xl"
      >
        {selectedRunId ? (
          <ProcessingRunPanel
            processingId={selectedRunId}
            canWrite={canWrite}
            units={units}
            onChanged={() => load({ silent: true })}
          />
        ) : null}
      </Modal>
    </div>
  );
}

export default ProcessingWorkspace;
