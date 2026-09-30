/**
 * AI service — insights, alerts and the analysis runs behind them.
 *
 * What this module does *not* do is as important as what it does: it never
 * computes, smooths or infers a score, and it never upgrades a value's
 * provenance. Everything returned here was produced by the backend engine and
 * stored in `hive_ai_analyses` / `ai_alerts`.
 *
 * `getInsight` is the only read that may write: the API recomputes an analysis
 * when there is none, when the stored one is stale, or when enough new telemetry
 * has arrived. Pass `refresh: false` to read without writing, or `refresh: true`
 * to force a run. The response always reports what happened in `computed` and
 * `compute_reason`, and screens surface both.
 */

import { ENDPOINTS } from '@/constants/api';
import { http } from '@/services/apiClient';

/** Fleet-level counters: bands, projections and open alerts for the caller's scope. */
export async function getSummary() {
  const { data } = await http.get(ENDPOINTS.ai.summary);
  return data;
}

/** One row per hive in scope, with its latest analysis (if any) and alert count. */
export async function listHiveInsights({ page = 1, pageSize = 50, search, onlyWithAnalysis } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.ai.hives, {
    params: {
      page,
      page_size: pageSize,
      ...(search ? { search } : {}),
      ...(onlyWithAnalysis ? { only_with_analysis: true } : {}),
    },
  });
  return { hives: data, meta };
}

/**
 * The insight for one hive.
 *
 * @param {string} hiveId
 * @param {{refresh?: boolean|null}} options  `null`/omitted applies the platform
 *   policy; `false` reads the stored analysis only; `true` forces a fresh run.
 */
export async function getInsight(hiveId, { refresh = null } = {}) {
  const { data } = await http.get(ENDPOINTS.ai.insight(hiveId), {
    params: refresh === null || refresh === undefined ? {} : { refresh },
  });
  return data;
}

/** Run the engine now, regardless of the staleness policy. */
export async function analyzeHive(hiveId, reason) {
  const { data } = await http.post(ENDPOINTS.ai.analyze(hiveId), reason ? { reason } : {});
  return data;
}

/** Run the engine over every hive the caller can see (synchronous, caller-scoped). */
export async function analyzeAll(reason) {
  const { data } = await http.post(ENDPOINTS.ai.analyzeAll, reason ? { reason } : {});
  return data;
}

/** Stored analyses for one hive, newest first. */
export async function getHistory(hiveId, { page = 1, pageSize = 20 } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.ai.history(hiveId), {
    params: { page, page_size: pageSize },
  });
  return { analyses: data, meta };
}

/** Alerts raised for one hive, open and acknowledged by default. */
export async function listHiveAlerts(hiveId, { includeResolved = false, limit = 50 } = {}) {
  const { data } = await http.get(ENDPOINTS.ai.hiveAlerts(hiveId), {
    params: { include_resolved: includeResolved, limit },
  });
  return data;
}

/**
 * Alerts in the caller's scope.
 *
 * With no `status`, the API returns what still needs attention (open and
 * acknowledged), which is the view a beekeeper wants.
 */
export async function listAlerts({
  page = 1,
  pageSize = 20,
  status,
  severity,
  alertType,
  hiveId,
  includeResolved = false,
} = {}) {
  const { data, meta } = await http.get(ENDPOINTS.ai.alerts, {
    params: {
      page,
      page_size: pageSize,
      ...(status ? { status } : {}),
      ...(severity ? { severity } : {}),
      ...(alertType ? { alert_type: alertType } : {}),
      ...(hiveId ? { hive_id: hiveId } : {}),
      ...(includeResolved ? { include_resolved: true } : {}),
    },
  });
  return { alerts: data, meta };
}

export async function getAlertSummary() {
  const { data } = await http.get(ENDPOINTS.ai.alertSummary);
  return data;
}

export async function getAlert(alertId) {
  const { data } = await http.get(ENDPOINTS.ai.alert(alertId));
  return data;
}

export async function acknowledgeAlert(alertId, note) {
  const { data } = await http.post(ENDPOINTS.ai.alertAcknowledge(alertId), note ? { note } : {});
  return data;
}

export async function resolveAlert(alertId, note) {
  const { data } = await http.post(ENDPOINTS.ai.alertResolve(alertId), note ? { note } : {});
  return data;
}

export async function reopenAlert(alertId) {
  const { data } = await http.post(ENDPOINTS.ai.alertReopen(alertId));
  return data;
}
