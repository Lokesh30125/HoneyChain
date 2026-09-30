import { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, Circle, Link2, RefreshCw } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import * as blockchainService from '@/services/blockchainService';
import { normaliseError } from '@/utils/errors';
import { formatDateTime } from '@/utils/format';

/**
 * The whole supply chain of one batch, from the records each module wrote.
 *
 * Reads `GET /blockchain/batches/{id}` — the one traceability service — and
 * shows its `chain` section: cluster, harvest, beekeeper, source hives,
 * processing, laboratory, packaging, packages, shipments, the retailer's
 * receipt and the blockchain events. A stage the records do not show is listed
 * as not reached; nothing is inferred from the batch status. The server applies
 * the batch's own read scope, so a beekeeper sees only their honey and an
 * out-of-scope or unknown id is a clear "not found", never a blank panel.
 */
export function SupplyChainPanel({ batchId }) {
  const [trace, setTrace] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setTrace(await blockchainService.getBatchTraceability(batchId));
    } catch (caught) {
      setTrace(null);
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [batchId]);

  useEffect(() => {
    load();
  }, [load]);

  const chain = trace?.chain || null;

  return (
    <Card>
      <CardHeader
        title="Supply chain"
        description="Every stage from the cluster to the retailer, read from the stage's own record."
        icon={<Link2 size={16} />}
        action={
          <Button size="sm" variant="secondary" leftIcon={<RefreshCw size={15} />} onClick={load} loading={loading}>
            Refresh
          </Button>
        }
      />
      <CardBody className="space-y-5">
        {loading && !trace ? <LoadingState message="Reading this batch's records…" /> : null}
        {error ? (
          <ErrorState error={error} title="This batch's supply chain could not be loaded" onRetry={load} />
        ) : null}
        {chain ? (
          <>
            <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" aria-label="Stages">
              {(chain.stages || []).map((stage) => (
                <li
                  key={stage.stage}
                  className="flex items-start gap-2 rounded-lg border border-sand-200 px-3 py-2"
                  data-testid={`chain-stage-${stage.stage}`}
                  data-reached={stage.reached ? 'true' : 'false'}
                >
                  {stage.reached ? (
                    <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-status-success" aria-hidden="true" />
                  ) : (
                    <Circle size={16} className="mt-0.5 shrink-0 text-ink-muted" aria-hidden="true" />
                  )}
                  <span className="min-w-0">
                    <span className="block text-sm font-medium text-ink">{stage.label}</span>
                    <span className="block truncate text-xs text-ink-muted">
                      {stage.reached ? stage.detail || 'Recorded' : 'Not reached yet'}
                    </span>
                  </span>
                </li>
              ))}
            </ol>

            <dl className="grid gap-4 text-sm sm:grid-cols-2">
              <Fact label="Cluster">
                {chain.cluster ? `${chain.cluster.cluster_name} (${chain.cluster.cluster_code})` : 'Not placed in a cluster'}
              </Fact>
              <Fact label="Harvest">
                {chain.collection
                  ? `${chain.collection.collection_code} · ${chain.collection.total_quantity ?? '—'} ${chain.collection.unit || ''}`
                  : '—'}
              </Fact>
              <Fact label="Beekeeper">
                {chain.beekeeper
                  ? `${chain.beekeeper.name || chain.beekeeper.beekeeper_code} (${chain.beekeeper.beekeeper_code})`
                  : '—'}
              </Fact>
              <Fact label="Source hives">
                {chain.hives?.length ? chain.hives.map((hive) => hive.hive_code).join(', ') : '—'}
              </Fact>
            </dl>

            <RecordList
              title="Processing"
              rows={chain.processing}
              render={(row) => `${row.processing_code} · ${label(row.status)}${row.facility ? ` · ${row.facility}` : ''}`}
            />
            <RecordList
              title="Laboratory"
              rows={chain.laboratory}
              render={(row) =>
                `${row.test_code} · round ${row.round ?? 1} · ${label(row.status)}${row.result ? ` · ${row.result}` : ''}`
              }
            />
            <RecordList
              title="Packaging"
              rows={chain.packaging}
              render={(row) =>
                `${row.packaging_code} · ${label(row.status)} · ${row.number_of_packages ?? 0} package(s)`
              }
            />
            <RecordList
              title="Packages"
              rows={chain.packages}
              render={(row) => (
                <span className="flex flex-wrap items-center gap-2">
                  <a className="font-mono text-forest-700 hover:underline" href={row.trace_url} target="_blank" rel="noreferrer">
                    {row.package_code}
                  </a>
                  <Badge size="sm">{label(row.status)}</Badge>
                  <Badge size="sm" variant={row.qr_issued ? 'success' : 'neutral'}>
                    {row.qr_issued ? 'QR issued' : 'No QR yet'}
                  </Badge>
                </span>
              )}
            />
            <RecordList
              title="Distribution"
              rows={chain.distribution}
              render={(row) =>
                `${row.distribution_code} · ${row.package_code} · ${label(row.status)} → ${row.destination}`
              }
            />
            <RecordList
              title="Retailer receipts"
              rows={chain.retailer}
              render={(row) =>
                `${row.distribution_code} · ${row.retailer || 'Retailer'} · received ${formatDateTime(row.received_at)}`
              }
            />
            <p className="text-xs text-ink-muted">
              {trace.transactions?.length || 0} blockchain event(s) recorded for this batch
              {trace.blockchain?.note ? ` — ${trace.blockchain.note}` : '.'}
            </p>
          </>
        ) : null}
      </CardBody>
    </Card>
  );
}

function label(value) {
  return value ? String(value).replace(/_/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase()) : '—';
}

function Fact({ label: title, children }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-ink-muted">{title}</dt>
      <dd className="mt-0.5 text-ink">{children}</dd>
    </div>
  );
}

function RecordList({ title, rows, render }) {
  return (
    <section aria-label={title}>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">{title}</h3>
      {rows?.length ? (
        <ul className="mt-1 space-y-1 text-sm text-ink-soft">
          {rows.map((row) => (
            <li key={row.id || row.distribution_code || row.package_code}>{render(row)}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-sm text-ink-muted">No record yet.</p>
      )}
    </section>
  );
}
