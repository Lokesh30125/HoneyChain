import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Beaker, ClipboardList, FlaskConical, TestTubes } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import { StatCard } from '@/components/common/StatCard';
import { AssignmentDialog } from '@/components/common/AssignmentDialog';
import { AwaitingTestingTable } from '@/components/laboratory/AwaitingTestingTable';
import { LabBatchQueueTable } from '@/components/laboratory/LabBatchQueueTable';
import { LabQueueTable } from '@/components/laboratory/LabQueueTable';
import { LabTestTable } from '@/components/laboratory/LabTestTable';
import { LAB_MESSAGES, LAB_TEST_STATUSES, SAMPLE_UNITS } from '@/constants/laboratory';
import { ROLES } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';
import * as laboratoryService from '@/services/laboratoryService';
import { normaliseError } from '@/utils/errors';

/**
 * The laboratory workspace.
 *
 * Written for the **lab technician**, who works here: the pending queue, the
 * samples they have taken, the tests they have opened, and the ones they have
 * closed. A **KVIC officer** and an **administrator** can read the same screens —
 * the rows are the same rows — but the technician's actions are rendered only for a
 * role that holds them, and the API refuses them for anyone else.
 *
 * The worklist never offers a verdict. Opening a test records the sample against a
 * real batch; deciding it happens in `LabTestPanel`, where the server computes the
 * outcome.
 */
export function LaboratoryWorkspace({
  role = ROLES.LAB_TECHNICIAN,
  view = 'overview',
  // Where this role's test pages live: /laboratory, /admin/laboratory or
  // /kvic/laboratory. A hard-coded /laboratory sent admin and KVIC users to a
  // workspace they may not open.
  basePath = '/laboratory',
}) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const canWrite = role === ROLES.LAB_TECHNICIAN || role === ROLES.ADMIN;
  const canAssignOthers = role === ROLES.ADMIN;

  const [summary, setSummary] = useState(null);
  const [awaiting, setAwaiting] = useState([]);
  const [awaitingMeta, setAwaitingMeta] = useState(null);
  const [tests, setTests] = useState([]);
  const [testsMeta, setTestsMeta] = useState(null);
  const [facilities, setFacilities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState({ page: 1, search: '' });
  const [openTarget, setOpenTarget] = useState(null);
  // Empty by default, including the sample quantity: every value here is something
  // the laboratory weighed, chose or recorded, so none of it is filled in for them.
  const [form, setForm] = useState({ laboratory_id: '', sample_quantity: '', sample_unit: '', test_date: '', retest_reason: '' });
  const [formError, setFormError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [pendingTests, setPendingTests] = useState([]);
  const [pendingMeta, setPendingMeta] = useState(null);
  const [assignedTests, setAssignedTests] = useState([]);
  const [assignedMeta, setAssignedMeta] = useState(null);
  const [completedTests, setCompletedTests] = useState([]);
  const [completedMeta, setCompletedMeta] = useState(null);
  const [withoutTests, setWithoutTests] = useState([]);
  const [withoutMeta, setWithoutMeta] = useState(null);
  const [heldTests, setHeldTests] = useState([]);
  const [heldMeta, setHeldMeta] = useState(null);
  const [queuePages, setQueuePages] = useState({
    pending: 1,
    assigned: 1,
    completed: 1,
    without: 1,
    held: 1,
  });
  const [busyTestId, setBusyTestId] = useState(null);
  const [assignTarget, setAssignTarget] = useState(null);
  const [technicians, setTechnicians] = useState([]);
  const [techniciansLoading, setTechniciansLoading] = useState(false);
  const [techniciansError, setTechniciansError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [notice, setNotice] = useState(null);

  // Each queue is a filter over the same stored tests, and the dashboard shows
  // them together. Listing the queues once keeps the load in step with the views.
  const queueViews = ['overview', 'pending', 'assigned', 'tests', 'samples', 'completed'];
  const wantsAwaiting = view === 'overview' || view === 'awaiting';
  const wantsPending = queueViews.includes(view);
  const wantsAssigned = queueViews.includes(view);
  const wantsCompleted = queueViews.includes(view);
  // A held test is not a completed one and not an open one: it is its own queue,
  // because it is the list somebody has to work through for a batch to move.
  const wantsHeld = view === 'overview' || view === 'held';
  const wantsWithoutTests = view === 'overview' || view === 'awaiting';
  const wantsTests = view === 'overview' || view === 'tests' || view === 'samples';
  const statusFilter =
    view === 'completed' ? LAB_TEST_STATUSES.COMPLETED : null;

  const load = useCallback(
    async ({ silent = false } = {}) => {
      if (silent) setLoading(false);
      else setLoading(true);
      setError(null);
      try {
        const queuePageSize = view === 'overview' ? 5 : 25;
        const [
          counters,
          queue,
          testList,
          facilityList,
          pendingList,
          assignedList,
          completedList,
          withoutList,
          heldList,
        ] = await Promise.all([
          laboratoryService.getTestSummary(),
          wantsAwaiting
            ? laboratoryService.listBatchesAwaitingTesting({ pageSize: view === 'awaiting' ? 50 : 5 })
            : Promise.resolve({ batches: [], meta: null }),
          wantsTests || view === 'completed'
            ? laboratoryService.listTests({
                page: filters.page,
                pageSize: 20,
                search: filters.search || undefined,
                status: statusFilter || undefined,
              })
            : Promise.resolve({ tests: [], meta: null }),
          canWrite ? laboratoryService.listFacilities({ pageSize: 100 }) : Promise.resolve({ facilities: [] }),
          wantsPending
            ? laboratoryService.listPendingTests({ pageSize: queuePageSize, page: queuePages.pending })
            : Promise.resolve({ tests: [], meta: null }),
          wantsAssigned
            ? laboratoryService.listAssignedTests({
                pageSize: queuePageSize,
                page: queuePages.assigned,
                mineOnly: role === ROLES.LAB_TECHNICIAN,
              })
            : Promise.resolve({ tests: [], meta: null }),
          wantsCompleted
            ? laboratoryService.listCompletedTests({ pageSize: queuePageSize, page: queuePages.completed })
            : Promise.resolve({ tests: [], meta: null }),
          wantsWithoutTests
            ? laboratoryService.listBatchesWithoutTests({
                pageSize: queuePageSize,
                page: queuePages.without,
              })
            : Promise.resolve({ batches: [], meta: null }),
          wantsHeld
            ? laboratoryService.listHeldTests({ pageSize: queuePageSize, page: queuePages.held })
            : Promise.resolve({ tests: [], meta: null }),
        ]);
        setSummary(counters);
        setAwaiting(queue.batches);
        setAwaitingMeta(queue.meta);
        setTests(testList.tests);
        setTestsMeta(testList.meta);
        setFacilities(facilityList.facilities);
        setPendingTests(pendingList.tests);
        setPendingMeta(pendingList.meta);
        setAssignedTests(assignedList.tests);
        setAssignedMeta(assignedList.meta);
        setCompletedTests(completedList.tests);
        setCompletedMeta(completedList.meta);
        setWithoutTests(withoutList.batches);
        setWithoutMeta(withoutList.meta);
        setHeldTests(heldList.tests);
        setHeldMeta(heldList.meta);
      } catch (caught) {
        setError(normaliseError(caught));
      } finally {
        setLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      filters,
      view,
      role,
      queuePages,
      wantsAwaiting,
      wantsTests,
      wantsPending,
      wantsAssigned,
      wantsCompleted,
      wantsWithoutTests,
      wantsHeld,
      statusFilter,
      canWrite,
    ],
  );

  useEffect(() => {
    load();
  }, [load]);

  const openTest = async () => {
    if (!openTarget) return;
    if (!form.sample_unit) {
      setFormError({ message: 'Select the sample unit.' });
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      const created = await laboratoryService.createTest({
        batch_id: openTarget.batch_id,
        laboratory_id: form.laboratory_id,
        sample_quantity: form.sample_quantity,
        sample_unit: form.sample_unit,
        ...(form.test_date ? { test_date: form.test_date } : {}),
        ...(form.retest_reason ? { retest_reason: form.retest_reason } : {}),
      });
      setOpenTarget(null);
      navigate(`${basePath}/tests/${created.id}`);
    } catch (caught) {
      setFormError(normaliseError(caught));
    } finally {
      setBusy(false);
    }
  };

  const completedView = view === 'completed';
  const sampleView = view === 'samples';

  const setQueuePage = (queue, page) =>
    setQueuePages((current) => ({ ...current, [queue]: page }));

  const runTestAction = async (test, action, successMessage) => {
    setBusyTestId(test.id);
    setActionError(null);
    try {
      const detail = await action();
      setNotice({ message: successMessage, code: detail?.test_code || test.test_code });
      await load({ silent: true });
    } catch (caught) {
      setActionError(normaliseError(caught));
    } finally {
      setBusyTestId(null);
    }
  };

  // Who may take a sample is the server's answer, from the same endpoint the
  // allocation validates against — an administrator sees every active technician, a
  // technician sees only themselves. (It previously read the administration
  // directory, which only an administrator may open.)
  const openAssign = async (test) => {
    setAssignTarget(test);
    setActionError(null);
    setTechniciansLoading(true);
    setTechniciansError(null);
    try {
      setTechnicians(await laboratoryService.listEligibleTechnicians());
    } catch (caught) {
      setTechniciansError(normaliseError(caught));
    } finally {
      setTechniciansLoading(false);
    }
  };

  /** The queues, in one place: each view renders exactly one of them. */
  const QUEUE_COPY = {
    pending: {
      title: 'Pending lab tests',
      description:
        'Samples nobody is responsible for yet. They stay here until a technician (or an administrator) allocates them, so unallocated work cannot fall off the bench.',
      empty: 'No unallocated sample is waiting.',
    },
    assigned: {
      title: 'Assigned lab tests',
      description:
        'Samples allocated to a named technician. A technician sees their own; an administrator sees every allocation in scope.',
      empty: 'Nothing is allocated to a technician right now.',
    },
    completed: {
      title: 'Completed tests',
      description:
        'Closed tests with the outcome the platform computed from the recorded measurements — pass, fail or inconclusive.',
      empty: 'No test has been completed yet.',
    },
    held: {
      title: 'On hold',
      description:
        'Tests closed without a decision. Each one keeps its measurements, its analysis and the reason it was parked, and each one is blocking a batch from packaging until it is answered.',
      empty: 'No test is on hold.',
    },
  };

  return (
    <div className="space-y-6">
      {view === 'overview' ? (
        <section aria-label="Laboratory summary" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Awaiting testing"
            value={summary?.awaiting_testing ?? '—'}
            helper="Batches at LAB_TESTING in your scope"
            icon={<TestTubes size={16} />}
            tone="honey"
            loading={loading}
          />
          <StatCard
            label="On hold"
            value={summary?.held ?? 0}
            helper="Closed without a decision; blocking packaging"
            icon={<ClipboardList size={16} />}
            tone="warning"
            loading={loading}
          />
          <StatCard
            label="Tests in progress"
            value={(summary?.pending ?? 0) + (summary?.in_progress ?? 0)}
            helper={`${summary?.pending ?? 0} opened, no measurements yet`}
            icon={<FlaskConical size={16} />}
            loading={loading}
          />
          <StatCard
            label="Passed"
            value={summary?.passed ?? '—'}
            helper={`${summary?.failed ?? 0} failed · ${summary?.inconclusive ?? 0} inconclusive`}
            icon={<ClipboardList size={16} />}
            tone="forest"
            loading={loading}
          />
          <StatCard
            label="Waiting for a technician"
            value={summary?.unassigned ?? '—'}
            helper="Open tests nobody is responsible for"
            icon={<TestTubes size={16} />}
            tone="honey"
            loading={loading}
          />
          <StatCard
            label="Assigned to me"
            value={summary?.mine ?? '—'}
            helper={`${summary?.mine_accepted ?? 0} accepted`}
            icon={<ClipboardList size={16} />}
            loading={loading}
          />
          <StatCard
            label="Parameters without a range"
            value={summary?.unconfigured_parameters ?? '—'}
            helper="Measurements on these are recorded, never judged"
            icon={<Beaker size={16} />}
            loading={loading}
          />
        </section>
      ) : null}

      {wantsAwaiting ? (
        <Card>
          <CardHeader
            title={view === 'awaiting' ? 'Pending lab tests' : 'Waiting for a sample'}
            description={
              canWrite
                ? 'Batches whose processing is complete. Open a test to record the sample you take from the batch.'
                : 'Batches in your scope that are waiting for laboratory testing. Read-only.'
            }
            icon={<TestTubes size={18} aria-hidden="true" />}
          />
          <CardBody>
            <AwaitingTestingTable
              basePath={basePath}
              rows={awaiting}
              loading={loading}
              error={error}
              onRetry={() => load()}
              meta={awaitingMeta}
              onOpenTest={
                canWrite
                  ? (row) => {
                      setForm({
                        laboratory_id: facilities.length === 1 ? facilities[0].id : '',
                        // Left empty on purpose: the sample is weighed on the bench.
                        // A number filled in for the technician would be a value the
                        // platform invented, and sample quantities end up on records.
                        sample_quantity: '',
                        sample_unit: '',
                        test_date: '',
                        retest_reason: '',
                      });
                      setOpenTarget(row);
                    }
                  : null
              }
            />
          </CardBody>
        </Card>
      ) : null}

      {['pending', 'assigned', 'completed', 'held'].map((queueView) => {
        if (view !== queueView) return null;
        const copy = QUEUE_COPY[queueView];
        const rows =
          queueView === 'pending'
            ? pendingTests
            : queueView === 'assigned'
              ? assignedTests
              : queueView === 'held'
                ? heldTests
                : completedTests;
        const queueMeta =
          queueView === 'pending'
            ? pendingMeta
            : queueView === 'assigned'
              ? assignedMeta
              : queueView === 'held'
                ? heldMeta
                : completedMeta;
        return (
          <Card key={queueView}>
            <CardHeader
              title={copy.title}
              description={copy.description}
              icon={<TestTubes size={18} aria-hidden="true" />}
              action={
                <Button variant="secondary" size="sm" onClick={() => load({ silent: true })} loading={loading}>
                  Refresh
                </Button>
              }
            />
            <CardBody className="space-y-4">
              {actionError ? <Alert variant="danger">{actionError.message}</Alert> : null}
              {notice ? (
                <Alert variant="success">
                  {notice.code ? `${notice.code}: ` : ''}
                  {notice.message}
                </Alert>
              ) : null}
              <LabQueueTable
                tests={rows}
                loading={loading}
                error={error}
                onRetry={() => load()}
                meta={queueMeta}
                onPageChange={(page) => setQueuePage(queueView, page)}
                busyId={busyTestId}
                onAssign={queueView === 'held' ? null : canWrite ? openAssign : null}
                onAccept={
                  canWrite && queueView !== 'held'
                    ? (test) =>
                        runTestAction(test, () => laboratoryService.acceptTest(test.id), 'Sample accepted.')
                    : null
                }
                onOpen={(test) => navigate(`${basePath}/tests/${test.id}`)}
                emptyTitle={copy.empty}
              />
            </CardBody>
          </Card>
        );
      })}

      {view === 'overview'
        ? [
            { key: 'pending', rows: pendingTests, meta: pendingMeta, empty: QUEUE_COPY.pending.empty },
            { key: 'assigned', rows: assignedTests, meta: assignedMeta, empty: QUEUE_COPY.assigned.empty },
          ].map((section) => (
            <Card key={section.key}>
              <CardHeader
                title={QUEUE_COPY[section.key].title}
                description="The newest five rows. Open the queue for the full list."
                icon={<TestTubes size={18} aria-hidden="true" />}
                action={
                  <Button variant="secondary" size="sm" onClick={() => load({ silent: true })} loading={loading}>
                    Refresh
                  </Button>
                }
              />
              <CardBody className="space-y-4">
                {actionError ? <Alert variant="danger">{actionError.message}</Alert> : null}
                {notice ? (
                  <Alert variant="success">
                    {notice.code ? `${notice.code}: ` : ''}
                    {notice.message}
                  </Alert>
                ) : null}
                <LabQueueTable
                  tests={section.rows}
                  loading={loading}
                  error={error}
                  onRetry={() => load()}
                  meta={section.meta}
                  onPageChange={(page) => setQueuePage(section.key, page)}
                  busyId={busyTestId}
                  onAssign={canWrite ? openAssign : null}
                  onAccept={
                    canWrite
                      ? (test) =>
                          runTestAction(test, () => laboratoryService.acceptTest(test.id), 'Sample accepted.')
                      : null
                  }
                  onOpen={(test) => navigate(`${basePath}/tests/${test.id}`)}
                  emptyTitle={section.empty}
                />
              </CardBody>
            </Card>
          ))
        : null}

      {/* Batches at LAB_TESTING with no sample booked in yet: the seam between the
          two workspaces, shown so it can be closed rather than discovered. */}
      {wantsWithoutTests ? (
        <Card>
          <CardHeader
            title="Awaiting a sample"
            description="Batches whose processing is complete and whose honey has reached the laboratory, but for which no sample has been booked in yet."
            icon={<TestTubes size={18} aria-hidden="true" />}
            action={
              <Button variant="secondary" size="sm" onClick={() => load({ silent: true })} loading={loading}>
                Refresh
              </Button>
            }
          />
          <CardBody>
            <LabBatchQueueTable
              batches={withoutTests}
              loading={loading}
              error={error}
              onRetry={() => load()}
              meta={withoutMeta}
              onPageChange={(page) => setQueuePage('without', page)}
              canWrite={canWrite}
              busyId={busyTestId}
              onOpenTest={
                canWrite
                  ? (row) => {
                      setForm({
                        laboratory_id: facilities.length === 1 ? facilities[0].id : '',
                        sample_quantity: '',
                        sample_unit: '',
                        test_date: '',
                        retest_reason: '',
                      });
                      setOpenTarget(row);
                    }
                  : null
              }
              onAssign={
                canAssignOthers
                  ? (row) => {
                      setAssignTarget({ ...row, isBatchRow: true });
                      openAssign({ ...row, isBatchRow: true });
                    }
                  : null
              }
            />
          </CardBody>
        </Card>
      ) : null}

      {wantsTests || completedView || sampleView ? (
        <Card>
          <CardHeader
            title={
              completedView
                ? 'Completed tests'
                : sampleView
                  ? 'Samples taken for testing'
                  : 'Laboratory tests'
            }
            description={
              completedView
                ? 'Tests that have been decided. Their values and their result are read, never rewritten.'
                : sampleView
                  ? 'Every sample with the quantity and unit that was taken, and the test it belongs to.'
                  : 'Every test ever opened against a batch — retests add a round, they never replace one.'
            }
            icon={<ClipboardList size={18} aria-hidden="true" />}
          />
          <CardBody className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <Input
                label="Search"
                name="test_search"
                value={filters.search}
                onChange={(event) => setFilters((f) => ({ ...f, search: event.target.value, page: 1 }))}
                placeholder="Test, sample or batch code"
              />
            </div>
            <LabTestTable
              tests={tests}
              loading={loading}
              error={error}
              onRetry={() => load()}
              meta={testsMeta}
              onPageChange={(page) => setFilters((f) => ({ ...f, page }))}
              emptyTitle={completedView ? LAB_MESSAGES.completedEmpty : sampleView ? LAB_MESSAGES.samplesEmpty : LAB_MESSAGES.testsEmpty}
              emptyDescription={
                completedView
                  ? 'A test appears here once its measurements have been recorded and the platform has decided it.'
                  : 'A test is opened against a batch whose processing run is complete.'
              }
            />
          </CardBody>
        </Card>
      ) : null}

      {/*
        Handing a sample to a named technician. An administrator chooses from the
        technician accounts the platform holds; a technician can only take work on
        personally. If the row is a *batch* with no test yet, the server opens the
        test as part of the allocation — the caller does not need to know that.
      */}
      <AssignmentDialog
        open={Boolean(assignTarget)}
        onClose={() => setAssignTarget(null)}
        title={
          assignTarget?.test_code
            ? `Assign ${assignTarget.test_code}`
            : assignTarget?.batch_code
              ? `Assign batch ${assignTarget.batch_code}`
              : 'Assign laboratory work'
        }
        description={
          assignTarget?.sample_code
            ? `Sample ${assignTarget.sample_code}. The technician is named here; the sample's own record is not changed.`
            : 'A sample with no technician stays on the pending list; allocating it puts it on somebody\'s bench.'
        }
        assigneeLabel="Laboratory technician"
        people={technicians}
        peopleLoading={techniciansLoading}
        peopleError={techniciansError}
        currentAssigneeId={assignTarget?.assigned_technician_id || null}
        selfOption={
          canAssignOthers || !user
            ? null
            : {
                id: user.id,
                label: 'Assign to me',
                helper: 'A technician can take an unallocated sample personally; an administrator allocates to other people.',
              }
        }
        emptyHint="No laboratory technician account is available yet. An administrator creates one in Administration → Users."
        onAssign={async (technicianId) => {
          const target = assignTarget;
          if (!target) return;
          if (target.isBatchRow) {
            const detail = await laboratoryService.assignBatchToTechnician(target.batch_id, technicianId);
            setNotice({ message: 'Batch allocated — its sample is booked in.', code: detail?.test_code });
          } else {
            const detail = await laboratoryService.assignTest(target.id, technicianId);
            setNotice({ message: 'Sample allocated.', code: detail?.test_code });
          }
          await load({ silent: true });
        }}
      />

      {/* Open a test: the sample is recorded against a real batch */}
      <Modal
        open={Boolean(openTarget)}
        onClose={() => setOpenTarget(null)}
        title="Open a laboratory test"
        description="A sample is taken from a batch that has completed processing. The server issues the test and sample codes."
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setOpenTarget(null)}>
              Close
            </Button>
            <Button
              size="sm"
              loading={busy}
              disabled={!form.laboratory_id || !form.sample_quantity}
              onClick={openTest}
              data-testid="create-test"
            >
              Open the test
            </Button>
          </div>
        }
      >
        {openTarget ? (
          <div className="space-y-3">
            <dl className="divide-y divide-sand-100 text-sm">
              <div className="flex justify-between py-1.5">
                <dt className="text-ink-muted">Batch</dt>
                <dd className="font-mono text-ink">{openTarget.batch_code}</dd>
              </div>
              <div className="flex justify-between py-1.5">
                <dt className="text-ink-muted">Processing run</dt>
                <dd className="font-mono text-ink">{openTarget.processing_code || '—'}</dd>
              </div>
              {openTarget.test_count ? (
                <div className="flex justify-between py-1.5">
                  <dt className="text-ink-muted">Earlier tests</dt>
                  <dd className="text-ink">
                    {openTarget.test_count} recorded — a new one opens another round
                  </dd>
                </div>
              ) : null}
            </dl>
            <Select
              label="Laboratory"
              name="laboratory_id"
              value={form.laboratory_id}
              onChange={(event) => setForm((f) => ({ ...f, laboratory_id: event.target.value }))}
              placeholder="Choose the laboratory"
              required
              options={facilities.map((facility) => ({
                value: facility.id,
                label: `${facility.name} (${facility.laboratory_code})`,
              }))}
            />
            <div className="grid gap-3 sm:grid-cols-2">
              <Input
                label="Sample quantity"
                name="sample_quantity"
                type="number"
                step="0.001"
                min="0"
                value={form.sample_quantity}
                onChange={(event) => setForm((f) => ({ ...f, sample_quantity: event.target.value }))}
                required
              />
              <Select
                label="Sample unit"
                name="sample_unit"
                required
                placeholder="Select unit"
                value={form.sample_unit}
                onChange={(event) => setForm((f) => ({ ...f, sample_unit: event.target.value }))}
                options={SAMPLE_UNITS}
              />
            </div>
            <Input
              label="Test date"
              name="test_date"
              type="date"
              value={form.test_date}
              onChange={(event) => setForm((f) => ({ ...f, test_date: event.target.value }))}
              hint="Optional; the server records today's date if you leave it empty."
            />
            {openTarget.test_count ? (
              <Input
                label="Why a new test?"
                name="retest_reason"
                value={form.retest_reason}
                onChange={(event) => setForm((f) => ({ ...f, retest_reason: event.target.value }))}
                hint="A batch that has already been decided needs a stated reason to be tested again."
              />
            ) : null}
            {formError ? <Alert variant="danger">{formError.message}</Alert> : null}
          </div>
        ) : null}
      </Modal>

      {/* Nothing to test right now — said in words, not with a fake row */}
      {view === 'awaiting' && !loading && !awaiting.length ? (
        <p className="text-sm text-ink-muted">{LAB_MESSAGES.awaitingEmpty}</p>
      ) : null}

      {view === 'completed' && !loading && !tests.length ? (
        <p className="text-sm text-ink-muted">{LAB_MESSAGES.completedEmpty}</p>
      ) : null}

      {view === 'samples' && !loading && !tests.length ? (
        <p className="text-sm text-ink-muted">{LAB_MESSAGES.samplesEmpty}</p>
      ) : null}

      {view === 'tests' && !loading && !tests.length ? (
        <p className="text-sm text-ink-muted">{LAB_MESSAGES.testsEmpty}</p>
      ) : null}
    </div>
  );
}

export default LaboratoryWorkspace;
