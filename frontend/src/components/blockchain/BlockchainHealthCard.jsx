import { useCallback, useEffect, useState } from 'react';
import { Blocks, RefreshCw, ServerCog, TriangleAlert } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { LoadingState } from '@/components/common/LoadingState';
import { ROLES } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';
import * as blockchainService from '@/services/blockchainService';
import { normaliseError } from '@/utils/errors';
import { formatDateTime } from '@/utils/format';

/**
 * How the traceability layer is doing, in real numbers.
 *
 * Every figure here is read from `GET /blockchain/health`: whether the service
 * answered the last read, what its ledger holds, and what HoneyChain's own
 * outbox is still owed — pending, confirmed, failed, and when the last event was
 * confirmed. Nothing is inferred and nothing is optimistic: an unreachable
 * service is reported as unreachable even while the workflow keeps recording
 * events, because those are two different facts.
 *
 * Rendered only for the accounts that may read the ledger (administrator, KVIC
 * officer); any other role would be asking for data it has no business seeing.
 */
export function BlockchainHealthCard({ compact = false }) {
  const { user } = useAuth();
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const canRead = [ROLES.ADMIN, ROLES.KVIC_OFFICER].includes(user?.role);

  const load = useCallback(async () => {
    if (!canRead) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setHealth(await blockchainService.getHealth());
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [canRead]);

  useEffect(() => {
    load();
  }, [load]);

  if (!canRead) return null;

  const service = health?.service;
  const counts = health?.honeychain;

  return (
    <Card>
      <CardHeader
        title="Blockchain synchronisation"
        description="The traceability service and what HoneyChain's outbox still owes it."
        icon={<Blocks size={16} />}
        action={
          <Button size="sm" variant="secondary" leftIcon={<RefreshCw size={15} />} onClick={load} loading={loading}>
            Refresh
          </Button>
        }
      />
      <CardBody className="space-y-4">
        {error ? (
          <Alert variant="warning" title="Unable to read blockchain health">
            {error.message}
          </Alert>
        ) : null}

        {loading && !health ? <LoadingState label="Asking the traceability service…" /> : null}

        {health ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant={service.reachable ? 'success' : 'danger'}
                size="sm"
                icon={<ServerCog size={13} />}
              >
                {service.reachable ? 'Connected' : 'Not reachable'}
              </Badge>
              {service.enabled === false ? (
                <Badge variant="neutral" size="sm">
                  Integration switched off
                </Badge>
              ) : null}
              <span className="text-xs text-ink-muted">
                {service.reachable
                  ? `${service.ledger_transactions ?? 0} transactions on the chain · answered in ${service.latency_ms ?? '—'} ms`
                  : service.message || 'The service did not answer the last read.'}
              </span>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-lg border border-sand-200 p-3">
                <p className="text-xs uppercase tracking-wide text-ink-muted">Confirmed</p>
                <p className="mt-1 text-xl font-semibold text-ink">{counts.confirmed}</p>
                <p className="text-xs text-ink-muted">
                  {counts.last_confirmed_at ? formatDateTime(counts.last_confirmed_at) : 'Nothing confirmed yet'}
                </p>
              </div>
              <div className="rounded-lg border border-sand-200 p-3">
                <p className="text-xs uppercase tracking-wide text-ink-muted">Pending</p>
                <p className="mt-1 text-xl font-semibold text-ink">
                  {counts.pending + counts.submitted}
                </p>
                <p className="text-xs text-ink-muted">Recorded, not yet written</p>
              </div>
              <div className="rounded-lg border border-sand-200 p-3">
                <p className="text-xs uppercase tracking-wide text-ink-muted">Failed</p>
                <p className="mt-1 text-xl font-semibold text-ink">{counts.failed}</p>
                <p className="text-xs text-ink-muted">
                  {counts.failed ? 'Retry from the ledger' : 'Nothing stuck'}
                </p>
              </div>
              <div className="rounded-lg border border-sand-200 p-3">
                <p className="text-xs uppercase tracking-wide text-ink-muted">Last transaction</p>
                <p className="mt-1 break-all font-mono text-xs text-ink">
                  {counts.last_confirmed_tx_id ? `${counts.last_confirmed_tx_id.slice(0, 18)}…` : '—'}
                </p>
                <p className="text-xs text-ink-muted">
                  {counts.last_confirmed_event || 'No event has been written yet'}
                </p>
              </div>
            </div>

            {counts.failed ? (
              <Alert variant="warning" icon={<TriangleAlert size={15} />}>
                {counts.failed} event(s) could not be written to the chain. The records themselves are
                safe — they are in HoneyChain and marked as not yet on the chain — and an
                administrator can retry them from the ledger.
              </Alert>
            ) : null}

            {!compact ? (
              <p className="text-xs text-ink-muted">
                An event becomes “confirmed” only when the service answers with a transaction id.
                Anything else is reported as it stands.
              </p>
            ) : null}
          </>
        ) : null}
      </CardBody>
    </Card>
  );
}

export default BlockchainHealthCard;
