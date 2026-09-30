/**
 * Laboratory service — opening a test against a batch, recording what was
 * measured, and letting the platform decide the outcome.
 *
 * Two things are deliberately absent from every payload this module builds:
 * `overall_result` on completion and any status field. A verdict is computed by
 * the server from the recorded values and the configured reference ranges —
 * requesting one is offered in exactly one place, `overrideTest`, which the API
 * restricts to an administrator and always audits with a reason.
 *
 * A result is never sent without its measurement: there is no default, no
 * "typical" value and no rounding done on the client.
 */

import { ENDPOINTS } from '@/constants/api';
import { http } from '@/services/apiClient';

function testListParams({
  page = 1,
  pageSize = 20,
  search,
  status,
  overallResult,
  batchId,
  laboratoryId,
  clusterId,
  dateFrom,
  dateTo,
} = {}) {
  return {
    page,
    page_size: pageSize,
    ...(search ? { search } : {}),
    ...(status ? { status } : {}),
    ...(overallResult ? { overall_result: overallResult } : {}),
    ...(batchId ? { batch_id: batchId } : {}),
    ...(laboratoryId ? { laboratory_id: laboratoryId } : {}),
    ...(clusterId ? { cluster_id: clusterId } : {}),
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
  };
}

/** Tests the caller may read, with their recorded-value counts. */
/**
 * The technicians laboratory work may be allocated to, from the server.
 *
 * The same set the allocation endpoint validates against: active accounts holding
 * the laboratory-technician role, each with the open work they already carry. A
 * technician sees only themselves.
 */
export async function listEligibleTechnicians() {
  const { data } = await http.get(ENDPOINTS.laboratory.eligibleTechnicians);
  return data;
}

export async function listTests(options = {}) {
  const { data, meta } = await http.get(ENDPOINTS.laboratory.tests, {
    params: testListParams(options),
  });
  return { tests: data, meta };
}

/** One test: the sample, the chain back to the apiary, and every recorded value. */
export async function getTest(testId) {
  const { data } = await http.get(ENDPOINTS.laboratory.test(testId));
  return data;
}

/** Counters by status and result, plus how many parameters have no range yet. */
export async function getTestSummary() {
  const { data } = await http.get(ENDPOINTS.laboratory.summary);
  return data;
}

/** Batches at LAB_TESTING in the caller's scope — the laboratory worklist. */
export async function listBatchesAwaitingTesting({ page = 1, pageSize = 20, search } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.laboratory.awaiting, {
    params: { page, page_size: pageSize, ...(search ? { search } : {}) },
  });
  return { batches: data, meta };
}

/**
 * Open a test against a batch.
 *
 * `retest_reason` is required by the API when the batch has already been decided;
 * the new test is opened as a new round and the earlier one is left untouched.
 */
export async function createTest(payload) {
  const { data } = await http.post(ENDPOINTS.laboratory.tests, payload);
  return data;
}

/** Correct an open test's sample details, date or remarks. */
export async function updateTest(testId, changes) {
  const { data } = await http.patch(ENDPOINTS.laboratory.test(testId), changes);
  return data;
}

/** Record a measured value. The unit comes from the parameter's catalogue entry. */
export async function recordResult(testId, payload) {
  const { data } = await http.post(ENDPOINTS.laboratory.results(testId), payload);
  return data;
}

/** Correct a measured value while the test is still open; the log keeps the old one. */
export async function updateResult(testId, resultId, changes) {
  const { data } = await http.patch(ENDPOINTS.laboratory.result(testId, resultId), changes);
  return data;
}

/** Remove a value entered in error, before the test is completed. */
export async function deleteResult(testId, resultId) {
  const { data } = await http.delete(ENDPOINTS.laboratory.result(testId, resultId));
  return data;
}

/**
 * Tests the laboratory closed without a decision.
 *
 * A held test is not a finished one: it keeps its measurements, its analysis and
 * the reason it was parked, it blocks packaging, and it is the queue the bench
 * works from when the missing answer arrives.
 */
export async function listHeldTests({ page = 1, pageSize = 20, search } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.laboratory.held, {
    params: { page, page_size: pageSize, ...(search ? { search } : {}) },
  });
  return { tests: data, meta };
}

/**
 * Run the quality analysis over the measurements already recorded.
 *
 * Nothing about the result is sent from here: the server reads the values, the
 * configured ranges and the parameter catalogue, and stores the verdict with the
 * model, its version and its source. Re-running replaces the analysis and is
 * audited — it is a fresh reading of the same numbers, not a way to change them.
 */
export async function analyzeTest(testId, { recompute = false } = {}) {
  const { data } = await http.post(ENDPOINTS.laboratory.analyze(testId), {
    ...(recompute ? { recompute: true } : {}),
  });
  return data;
}

/**
 * Hold a test: the laboratory stops without deciding.
 *
 * The measurements stay, the reason is stored, the batch is blocked from packaging
 * and everything is audited. `runAnalysis` asks the server to analyse the values
 * first, so the hold can name what it was waiting for.
 */
export async function holdTest(testId, { reason, runAnalysis = false }) {
  const { data } = await http.post(ENDPOINTS.laboratory.hold(testId), {
    reason,
    ...(runAnalysis ? { run_analysis: true } : {}),
  });
  return data;
}

/**
 * Release a flagged batch to packaging with the risk recorded against a name.
 *
 * A deliberate, audited act: the caller must type the confirmation word the server
 * published, give a reason, and the analysis that was overridden travels with the
 * record. A stray click cannot do this — the word is checked on the server, not
 * only in this dialog.
 */
export async function proceedWithRisk(testId, { confirmation, reason, runAnalysis = false }) {
  const { data } = await http.post(ENDPOINTS.laboratory.proceedWithRisk(testId), {
    confirmation,
    reason,
    ...(runAnalysis ? { run_analysis: true } : {}),
  });
  return data;
}

/** Ask the platform to decide: the verdict is computed, never submitted. */
export async function completeTest(testId, { remarks } = {}) {
  const { data } = await http.post(
    ENDPOINTS.laboratory.complete(testId),
    remarks ? { remarks } : {},
  );
  return data;
}

/** Administrator-only: decide a test against the rules, with a stated reason. */
export async function overrideTest(testId, { overallResult, reason }) {
  const { data } = await http.post(ENDPOINTS.laboratory.override(testId), {
    overall_result: overallResult,
    reason,
  });
  return data;
}

/** The parameter catalogue: what can be measured, and whether a range is set. */
export async function listParameters() {
  const { data } = await http.get(ENDPOINTS.laboratory.parameters);
  return data;
}

/**
 * Configure a parameter.
 *
 * A reference range is only ever set together with the source it came from — the
 * platform does not invent scientific limits, so it asks where they came from.
 */
export async function updateParameter(code, changes) {
  const { data } = await http.patch(ENDPOINTS.laboratory.parameter(code), changes);
  return data;
}

/** Laboratories the caller may see. */
export async function listFacilities({ page = 1, pageSize = 50, search, status } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.laboratory.facilities, {
    params: {
      page,
      page_size: pageSize,
      ...(search ? { search } : {}),
      ...(status ? { status } : {}),
    },
  });
  return { facilities: data, meta };
}

/** Register a facility. `laboratory_code` is issued by the server. */
export async function createFacility(payload) {
  const { data } = await http.post(ENDPOINTS.laboratory.facilities, payload);
  return data;
}

export async function updateFacility(laboratoryId, changes) {
  const { data } = await http.patch(ENDPOINTS.laboratory.facility(laboratoryId), changes);
  return data;
}

/**
 * Samples nobody is responsible for yet — the shared bench queue.
 *
 * An unallocated sample stays here rather than disappearing, which is the whole
 * point of the pending list.
 */
export async function listPendingTests({ page = 1, pageSize = 20, search } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.laboratory.pending, {
    params: { page, page_size: pageSize, ...(search ? { search } : {}) },
  });
  return { tests: data, meta };
}

/** Tests allocated to a named technician: the caller's own list, or all in scope. */
export async function listAssignedTests({ page = 1, pageSize = 20, search, mineOnly = false } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.laboratory.assigned, {
    params: {
      page,
      page_size: pageSize,
      ...(search ? { search } : {}),
      ...(mineOnly ? { mine_only: true } : {}),
    },
  });
  return { tests: data, meta };
}

/** Decided tests, with the outcome the platform computed. */
export async function listCompletedTests({ page = 1, pageSize = 20, search } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.laboratory.completed, {
    params: { page, page_size: pageSize, ...(search ? { search } : {}) },
  });
  return { tests: data, meta };
}

/** Batches whose processing is complete but which have no sample booked in yet. */
export async function listBatchesWithoutTests({ page = 1, pageSize = 20, search } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.laboratory.withoutTests, {
    params: { page, page_size: pageSize, ...(search ? { search } : {}) },
  });
  return { batches: data, meta };
}

/** Allocate a test to a named technician. The id is validated by the server. */
export async function assignTest(testId, technicianId) {
  const { data } = await http.post(ENDPOINTS.laboratory.assign(testId), {
    technician_id: technicianId,
  });
  return data;
}

/** Allocate a batch's laboratory work, opening its test if none exists yet. */
export async function assignBatchToTechnician(batchId, technicianId) {
  const { data } = await http.post(ENDPOINTS.laboratory.assignBatch(batchId), {
    technician_id: technicianId,
  });
  return data;
}

/** The named technician takes the sample on. */
export async function acceptTest(testId) {
  const { data } = await http.post(ENDPOINTS.laboratory.accept(testId), {});
  return data;
}
