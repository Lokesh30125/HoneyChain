/**
 * Processing service — the runs that turn a collected batch into honey that is
 * ready for the laboratory.
 *
 * Nothing in this module decides a status. Opening a run leaves the batch where
 * it is, `start` moves it to PROCESSING and `complete` moves it to LAB_TESTING —
 * and the server checks each move against its transition table. There is no
 * "set status" call here because the platform does not have one.
 *
 * Quantities are recorded, never derived: `input_quantity` and `output_quantity`
 * are what a person measured, and the difference the API returns is arithmetic on
 * those two numbers rather than an assumption that they are equal.
 */

import { ENDPOINTS } from '@/constants/api';
import { http } from '@/services/apiClient';

function listParams({
  page = 1,
  pageSize = 20,
  search,
  status,
  batchId,
  unitId,
  clusterId,
  dateFrom,
  dateTo,
} = {}) {
  return {
    page,
    page_size: pageSize,
    ...(search ? { search } : {}),
    ...(status ? { status } : {}),
    ...(batchId ? { batch_id: batchId } : {}),
    ...(unitId ? { processing_unit_id: unitId } : {}),
    ...(clusterId ? { cluster_id: clusterId } : {}),
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
  };
}

/** Runs the caller may read — their own batch's, their cluster's, or the queue. */
export async function listRuns(options = {}) {
  const { data, meta } = await http.get(ENDPOINTS.processing.list, {
    params: listParams(options),
  });
  return { runs: data, meta };
}

/** One run with the batch it belongs to and the next step the API allows. */
export async function getRun(processingId) {
  const { data } = await http.get(ENDPOINTS.processing.detail(processingId));
  return data;
}

/** Every run recorded against a batch, newest first. */
export async function getRunHistory(processingId) {
  const { data } = await http.get(ENDPOINTS.processing.history(processingId));
  return data;
}

/** Counters by status, plus the measured input/output difference per unit. */
export async function getProcessingSummary() {
  const { data } = await http.get(ENDPOINTS.processing.summary);
  return data;
}

/** Batches at COLLECTED in the caller's scope — the processing worklist. */
export async function listBatchesAwaitingProcessing({ page = 1, pageSize = 20, search } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.processing.awaiting, {
    params: { page, page_size: pageSize, ...(search ? { search } : {}) },
  });
  return { batches: data, meta };
}

/** Open a run against a collected batch. No quantities yet — they are measured. */
export async function createRun(payload) {
  const { data } = await http.post(ENDPOINTS.processing.list, payload);
  return data;
}

/** Correct an open run: type, unit, date, measured quantities, notes. */
export async function updateRun(processingId, changes) {
  const { data } = await http.patch(ENDPOINTS.processing.detail(processingId), changes);
  return data;
}

/** Start the run: the batch moves COLLECTED → PROCESSING. */
export async function startRun(processingId) {
  const { data } = await http.post(ENDPOINTS.processing.start(processingId), {});
  return data;
}

/** Complete the run: both measured quantities are required; batch → LAB_TESTING. */
export async function completeRun(processingId, payload) {
  const { data } = await http.post(ENDPOINTS.processing.complete(processingId), payload);
  return data;
}

/** Record that the run did not happen, with a reason. */
export async function cancelRun(processingId, reason) {
  const { data } = await http.post(ENDPOINTS.processing.cancel(processingId), { reason });
  return data;
}

/** Processing units the caller may see. */
export async function listUnits({ page = 1, pageSize = 50, search } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.processing.units, {
    params: { page, page_size: pageSize, ...(search ? { search } : {}) },
  });
  return { units: data, meta };
}

/** Register a unit. The server issues `unit_code`; it is never sent from here. */
export async function createUnit(payload) {
  const { data } = await http.post(ENDPOINTS.processing.units, payload);
  return data;
}

export async function updateUnit(unitId, changes) {
  const { data } = await http.patch(ENDPOINTS.processing.unit(unitId), changes);
  return data;
}

/**
 * Runs nobody has been made responsible for yet — the shared queue.
 *
 * This is the same stored record the batch was handed over as; the queue is a
 * filter over runs, not a second copy of the work.
 */
export async function listPendingAssignments({ page = 1, pageSize = 20, search } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.processing.pending, {
    params: { page, page_size: pageSize, ...(search ? { search } : {}) },
  });
  return { runs: data, meta };
}

/** Runs allocated to a named processor: the caller's own list, or all in scope. */
export async function listAssignedRuns({ page = 1, pageSize = 20, search, mineOnly = false } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.processing.assigned, {
    params: {
      page,
      page_size: pageSize,
      ...(search ? { search } : {}),
      ...(mineOnly ? { mine_only: true } : {}),
    },
  });
  return { runs: data, meta };
}

/** Runs that finished: the honey was measured in and out and left for the laboratory. */
export async function listCompletedRuns({ page = 1, pageSize = 20, search } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.processing.completed, {
    params: { page, page_size: pageSize, ...(search ? { search } : {}) },
  });
  return { runs: data, meta };
}

/**
 * Hand a run to a named processor.
 *
 * `processorId` is a user id the server validates: it must belong to an active
 * processor, and a processor may only name themselves. The UI does not decide
 * who is eligible — it shows the list the server gives it.
 */
export async function assignRun(processingId, processorId) {
  const { data } = await http.post(ENDPOINTS.processing.assign(processingId), {
    processor_id: processorId,
  });
  return data;
}

/** Hand a whole batch over, opening its run if it has none yet. */
/**
 * The accounts processing work may be allocated to.
 *
 * Read from the server rather than from the administration directory: the list is
 * the same set of accounts the allocation itself accepts (active, PROCESSOR role),
 * so a name that appears here can always be allocated to, and one that cannot is
 * never offered. An administrator sees every processor; a processor sees only
 * themselves, because giving work to a colleague is an administrator's decision.
 */
export async function listEligibleProcessors() {
  const { data } = await http.get(ENDPOINTS.processing.eligibleProcessors);
  return data;
}

export async function assignBatchToProcessor(batchId, processorId) {
  const { data } = await http.post(ENDPOINTS.processing.assignBatch(batchId), {
    processor_id: processorId,
  });
  return data;
}

/** The named processor takes the work on. */
export async function acceptRun(processingId) {
  const { data } = await http.post(ENDPOINTS.processing.accept(processingId), {});
  return data;
}
