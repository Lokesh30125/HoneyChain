import { useCallback, useEffect, useState } from 'react';
import { Blocks, RefreshCw } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { LoadingState } from '@/components/common/LoadingState';
import { blockchainStatusMeta, eventTypeLabel, synchronisationState } from '@/constants/blockchain';
import * as blockchainService from '@/services/blockchainService';
import { normaliseError } from '@/utils/errors';
import { formatDateTime } from '@/utils/format';

/**
 * The batch's own traceability events, beside the batch they describe.
 *
 * This is the technical half of the batch screen: the events the workflow
 * actually recorded for this batch — with their event ids, the chain status each
 * one reached, and the moment it was confirmed — plus the packages the batch was
 * split into. It reads `GET /blockchain/batches/{id}`, which applies the same
 * scope rule as the batch itself, so a beekeeper sees their own honey's events
 * and nobody sees another keeper's.
 *
 * Nothing here writes anything, and nothing here calls the blockchain service
 * directly: the client has no idea what its URL is.
 */
export function BatchBlockchainSection({ batchId }) {
  const [trace, setTrace] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setTrace(await blockchainService.getBatchTraceability(batchId));
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [batchId]);

  useEffect(() => {
    load();
  }, [load]);

  const state = trace ? synchronisationState(trace.blockchain) : null;

  return (
    <Card>
      <CardHeader
        title="Blockchain traceability"
        description="Every event this batch recorded on the traceability chain, with its event id and the status the chain reports."
        action={
          <Button size="sm" variant="secondary" leftIcon={<RefreshCw size={15} />} onClick={load} loading={loading}>
            Refresh
          </Button>
        }
      />
      <CardBody className="space-y-4">
        {loading && !trace ? <LoadingState message="Reading this batch's events…" /> : null}

        {error ? (
          <Alert variant="warning" title="Unable to load blockchain traceability">
            {error.message}
          </Alert>
        ) : null}

        {trace ? (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <Badge variant={state.variant} icon={<Blocks size={13} />}>
                {state.label}
              </Badge>
              <span className="text-xs text-ink-muted">
                {trace.blockchain.confirmed} confirmed · {trace.blockchain.pending} waiting ·{' '}
                {trace.blockchain.failed} failed
                {trace.blockchain.skipped ? ` · ${trace.blockchain.skipped} skipped` : ''}
              </span>
            </div>

            {trace.blockchain.note ? (
              <p className="text-xs text-ink-muted">{trace.blockchain.note}</p>
            ) : null}

            {trace.transactions.length ? (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-sand-200 text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-wide text-ink-muted">
                      <th className="py-2 pr-4 font-medium">Event</th>
                      <th className="py-2 pr-4 font-medium">Recorded</th>
                      <th className="py-2 pr-4 font-medium">Chain status</th>
                      <th className="py-2 font-medium">Transaction id</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-sand-100">
                    {trace.transactions.map((row) => {
                      const meta = blockchainStatusMeta(row.status);
                      return (
                        <tr key={row.id}>
                          <td className="py-2 pr-4">
                            <p className="text-ink">{row.tx_type_label || eventTypeLabel(row.tx_type)}</p>
                            <p className="font-mono text-xs text-ink-muted">{row.event_id}</p>
                          </td>
                          <td className="py-2 pr-4 whitespace-nowrap text-ink-soft">
                            {formatDateTime(row.created_at)}
                          </td>
                          <td className="py-2 pr-4">
                            <Badge variant={meta.variant} size="sm">
                              {row.status_label || meta.label}
                            </Badge>
                            {row.last_error ? (
                              <p className="mt-1 max-w-xs text-xs text-status-danger">{row.last_error}</p>
                            ) : null}
                          </td>
                          <td className="py-2 font-mono text-xs text-ink-soft">
                            {row.tx_id ? (
                              <span title={row.tx_id}>{row.tx_id.slice(0, 16)}…</span>
                            ) : (
                              <span className="text-ink-muted">
                                {row.status === 'CONFIRMED' ? '—' : 'Not on the chain'}
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-sm text-ink-muted">
                No event has been recorded for this batch yet. Events appear as the workflow reaches
                them — nothing is written ahead of the work.
              </p>
            )}

            {trace.packages?.length ? (
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
                  Packages of this batch
                </p>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {trace.packages.map((row) => (
                    <li key={row.package_code}>
                      <Badge variant={row.qr_issued ? 'success' : 'neutral'} size="sm">
                        {row.package_code}
                        {row.qr_issued ? ' · QR issued' : ''}
                      </Badge>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <p className="text-xs text-ink-muted">
              The event id is HoneyChain's own record of what was written; the transaction id is
              the chain's. An event is only ever described as being on the chain once the service
              has answered with one — a pending or skipped event is shown as exactly that. The
              measurements, notes and documents behind each step stay in HoneyChain; the chain holds
              the summary alone.
            </p>
          </>
        ) : null}
      </CardBody>
    </Card>
  );
}

export default BatchBlockchainSection;
