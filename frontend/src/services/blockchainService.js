/**
 * Traceability service — the one place the client talks to the chain layer.
 *
 * Every call here reaches a backend endpoint; none of them talk to the
 * blockchain service itself. That is deliberate: the URL of the blockchain
 * service, the payloads, the event ids and the decision about *when* an event
 * may be recorded all live on the server. A screen can read the ledger, ask
 * for a retry of something the platform already recorded, or read a package's
 * traceability — it cannot invent a transaction, choose a tx_type, or write a
 * status the workflow did not earn.
 *
 * The customer's route (`publicTrace`) is the exception in the other
 * direction: it is unauthenticated because the person holding the jar is not a
 * HoneyChain user, and it returns only the fields the backend's PublicTrace
 * model allows.
 */

import { API_BASE_URL, ENDPOINTS } from '@/constants/api';
import { http } from '@/services/apiClient';

/**
 * The ledger, newest first.
 *
 * @param {object} params page, pageSize, txType, status, batchCode, search,
 *                        dateFrom, dateTo
 */
export async function listTransactions({
  page = 1,
  pageSize = 25,
  txType,
  status,
  batchCode,
  search,
  dateFrom,
  dateTo,
} = {}) {
  const { data, meta } = await http.get(ENDPOINTS.blockchain.transactions, {
    params: {
      page,
      page_size: pageSize,
      tx_type: txType || undefined,
      status: status || undefined,
      batch_code: batchCode || undefined,
      search: search || undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    },
  });
  return { transactions: data, meta };
}

/** One transaction in full: payload, chain status, the record it describes. */
export async function getTransaction(eventId) {
  const { data } = await http.get(ENDPOINTS.blockchain.transaction(eventId));
  return data;
}

/** The chain's own answer — every transaction it holds, including its older ones. */
export async function getChainLedger({ limit = 100 } = {}) {
  const { data } = await http.get(ENDPOINTS.blockchain.ledger, { params: { limit } });
  return data;
}

/** Is the service reachable, and what is the outbox still owed to it? */
export async function getHealth() {
  const { data } = await http.get(ENDPOINTS.blockchain.health);
  return data;
}

/** Submit everything outstanding now, instead of waiting for the worker. */
export async function sync() {
  const { data } = await http.post(ENDPOINTS.blockchain.sync);
  return data;
}

/** Submit one failed event again, recording who asked. */
export async function retryTransaction(eventId) {
  const { data } = await http.post(ENDPOINTS.blockchain.retry(eventId));
  return data;
}

/** A batch's traceability: its records, its events, the timeline they make. */
export async function getBatchTraceability(batchId) {
  const { data } = await http.get(ENDPOINTS.blockchain.batch(batchId));
  return data;
}

/** A package's QR identity. Reading never issues one. */
export async function getPackageQr(packageId) {
  const { data } = await http.get(ENDPOINTS.blockchain.packageQr(packageId));
  return data;
}

/**
 * Issue the package's QR identity — once.
 *
 * The backend returns the identity that already exists if one does, so calling
 * this twice never writes a second QR event and never invalidates a printed
 * label.
 */
export async function issuePackageQr(packageId) {
  const { data } = await http.post(ENDPOINTS.blockchain.packageQr(packageId));
  return data;
}

/**
 * The customer's view of a package, by the code on its label.
 *
 * Unauthenticated: a customer is not asked to register before finding out where
 * their honey came from.
 */
export async function getPublicTrace(packageCode) {
  const { data } = await http.get(ENDPOINTS.trace.package(packageCode), { skipAuth: true });
  return data;
}

/** Where the label image can be fetched from — an <img src>, not an API call. */
export function qrImageUrl(packageCode) {
  return `${API_BASE_URL}${ENDPOINTS.trace.qrImage(packageCode)}`;
}

/** Where the customer's page lives, for the label and for copy-to-clipboard. */
export function traceUrl(packageCode) {
  return `/trace/${encodeURIComponent(packageCode)}`;
}
