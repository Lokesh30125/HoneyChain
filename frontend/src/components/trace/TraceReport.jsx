import { useCallback, useEffect, useState } from 'react';
import {
  Blocks,
  CheckCheck,
  CircleDashed,
  Droplets,
  FlaskConical,
  Factory,
  MapPin,
  Package,
  QrCode,
  Truck,
  User,
} from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { LoadingState } from '@/components/common/LoadingState';
import { eventTypeLabel } from '@/constants/blockchain';
import * as blockchainService from '@/services/blockchainService';
import { normaliseError } from '@/utils/errors';
import { formatDateTime } from '@/utils/format';

/**
 * One package's public traceability report — what a scan resolves to.
 *
 * One implementation, two doors: the anonymous page at `/trace/{code}` and
 * `/verify/{qrId}` renders it, and so does the signed-in consumer's workspace,
 * so a person who scans a jar and a person who types the code into their account
 * read exactly the same record. Nothing here is written by the browser: it is
 * `GET /trace/{code}`, whose fields are an allow-list assembled by the backend,
 * which is why this report can only ever show what a stranger may see — no
 * account, no email, no internal identifier, no note, no document, no telemetry.
 *
 * Stages that have not happened are listed as not reached rather than dressed
 * up, and the page never claims the honey is on the chain while an event is
 * still waiting to be written: "on the chain" is the server's verdict
 * (`synchronized`), never this component's guess.
 */

function Fact({ icon, label, value }) {
  if (value === null || value === undefined || value === '') return null;
  return (
    <div className="flex items-start gap-3">
      <span className="mt-0.5 flex h-8 w-8 flex-none items-center justify-center rounded-lg bg-forest-50 text-forest-700 ring-1 ring-forest-100">
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">{label}</p>
        <p className="mt-0.5 text-sm text-ink">{value}</p>
      </div>
    </div>
  );
}

/**
 * The laboratory's verdict in plain words.
 *
 * The result itself is never re-worded into something better: a failure reads as
 * a failure, a hold as a hold, and an override is a separate line beside it.
 */
function labVerdict(result) {
  switch ((result || '').toUpperCase()) {
    case 'PASS':
      return '✓ Quality Approved';
    case 'FAIL':
      return '✕ Quality Failed';
    case 'HOLD':
    case 'INCONCLUSIVE':
    case 'LAB_HOLD':
      return '⚠ Quality Hold';
    default:
      return result ? `Laboratory status: ${result}` : 'Awaiting the laboratory';
  }
}

const amount = (value, unit) =>
  value === null || value === undefined
    ? null
    : `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 })}${unit ? ` ${unit}` : ''}`;

export function TraceReport({ code, footer = null }) {
  const [trace, setTrace] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    if (!code) {
      setLoading(false);
      setTrace(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setTrace(await blockchainService.getPublicTrace(code));
    } catch (caught) {
      // A failed lookup must not leave the previous package's report on screen
      // under the new code's error.
      setTrace(null);
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [code]);

  useEffect(() => {
    load();
  }, [load]);

  const blockchain = trace?.blockchain || null;
  // "On the chain" is the server's verdict, not the page's: an event whose
  // status is not CONFIRMED has no transaction id to show, and the page must
  // never describe it as though it did.
  const onChain = Boolean(blockchain) && blockchain.synchronized === true;

  return (
    <div className="space-y-6">
      {loading && !trace ? (
        <Card>
          <CardBody>
            <LoadingState label="Looking up this package…" />
          </CardBody>
        </Card>
      ) : null}

      {error ? (
        <Card>
          <CardBody>
            <Alert variant={error.status === 404 ? 'warning' : 'danger'} title="Invalid QR Code">
              Product verification unavailable — {error.message}
            </Alert>
            <p className="mt-3 text-sm text-ink-soft">
              Check the code printed on the label. It looks like <code>HC-PKG-2026-000001</code>, or{' '}
              <code>QR-HC-PKG-2026-000001</code> beside it. If the code is right and this page still
              cannot find it, the package was not recorded by HoneyChain.
            </p>
          </CardBody>
        </Card>
      ) : null}

      {trace && trace.verification && trace.verification.available === false ? (
        <Card>
          <CardBody>
            <Alert variant="warning" title="QR verification is unavailable.">
              {trace.verification.reason ||
                'This code is no longer published, so nothing about the supply chain behind it is shown.'}
            </Alert>
          </CardBody>
        </Card>
      ) : null}

      {trace && (!trace.verification || trace.verification.available !== false) ? (
        <>
          <Card>
            <CardHeader
              title={trace.package.package_code}
              description={`${trace.product.honey} · batch ${trace.product.batch_code}`}
              action={
                <Badge variant={onChain ? 'success' : 'warning'} icon={<Blocks size={13} />}>
                  {onChain
                    ? 'Recorded on the traceability chain'
                    : 'Traceability events are still being written'}
                </Badge>
              }
            />
            <CardBody className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              <Fact
                icon={<Package size={15} />}
                label="Package ID"
                value={trace.package.package_code}
              />
              <Fact icon={<QrCode size={15} />} label="QR ID" value={trace.qr?.qr_id} />
              <Fact
                icon={<Package size={15} />}
                label="Package"
                value={amount(trace.package.quantity, trace.package.unit)}
              />
              <Fact
                icon={<Droplets size={15} />}
                label="Container"
                value={trace.package.packaging_type}
              />
              <Fact
                icon={<Factory size={15} />}
                label="Packed on"
                value={trace.package.packaged_on ? trace.package.packaged_on : null}
              />
              <Fact
                icon={<User size={15} />}
                label="Apiary"
                value={trace.source.beekeeper ? `Producer ${trace.source.beekeeper}` : null}
              />
              <Fact
                icon={<MapPin size={15} />}
                label="Where"
                value={[trace.source.district, trace.source.state].filter(Boolean).join(', ') || null}
              />
              <Fact
                icon={<Blocks size={15} />}
                label="Cluster"
                value={trace.source.cluster || 'Not recorded in a cluster'}
              />
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="The journey of this honey"
              description="Each step is shown as reached only when the record that completes it exists."
            />
            <CardBody>
              <ol className="space-y-3">
                {trace.timeline.map((stage) => (
                  <li key={stage.stage} className="flex items-start gap-3">
                    <span
                      className={`mt-0.5 flex h-7 w-7 flex-none items-center justify-center rounded-full ${
                        stage.reached
                          ? 'bg-forest-50 text-forest-700 ring-1 ring-forest-200'
                          : 'bg-sand-100 text-ink-muted ring-1 ring-sand-300'
                      }`}
                    >
                      {stage.reached ? <CheckCheck size={14} /> : <CircleDashed size={14} />}
                    </span>
                    <div className="min-w-0">
                      <p className={`text-sm ${stage.reached ? 'text-ink' : 'text-ink-muted'}`}>
                        {stage.label}
                      </p>
                      {stage.at ? (
                        <p className="text-xs text-ink-muted">{formatDateTime(stage.at)}</p>
                      ) : null}
                      {stage.detail ? (
                        <p className="mt-0.5 text-xs text-ink-soft">{stage.detail}</p>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ol>
            </CardBody>
          </Card>

          {trace.processing.length || trace.laboratory.length || trace.packaging.packaging_code ? (
            <Card>
              <CardHeader
                title="What was done to it"
                description="Processing, the laboratory's verdict and the packing run — the records behind the summary above."
              />
              <CardBody className="space-y-4">
                {trace.processing.map((run) => (
                  <div key={run.processing_code} className="flex items-start gap-3">
                    <Factory size={15} className="mt-0.5 text-forest-700" />
                    <div>
                      <p className="text-sm text-ink">
                        {run.processing_type || 'Processing'}
                        {run.facility ? ` · ${run.facility}` : ''}
                      </p>
                      <p className="text-xs text-ink-muted">
                        {amount(run.input_quantity, run.unit)} in →{' '}
                        {amount(run.output_quantity, run.unit)} out
                        {run.completed_at ? ` · completed ${formatDateTime(run.completed_at)}` : ''}
                      </p>
                    </div>
                  </div>
                ))}

                {trace.laboratory.map((test) => (
                  <div key={test.test_code} className="flex items-start gap-3">
                    <FlaskConical size={15} className="mt-0.5 text-forest-700" />
                    <div>
                      {/* The verdict, in the words the result deserves — and if an
                          override was used, it is shown *beside* the original
                          result, never in place of it. */}
                      <p className="text-sm text-ink">
                        {labVerdict(test.result)}
                        {test.proceeded_with_risk ? (
                          <span className="ml-2 text-xs font-medium text-status-warning">
                            ⚠ Proceeded With Risk
                          </span>
                        ) : null}
                      </p>
                      <p className="text-xs text-ink-muted">
                        Laboratory test {test.test_code} · measured result{' '}
                        {test.result || test.status}
                      </p>
                      {test.summary ? <p className="text-xs text-ink-soft">{test.summary}</p> : null}
                      {test.completed_at ? (
                        <p className="text-xs text-ink-muted">
                          Completed {formatDateTime(test.completed_at)}
                        </p>
                      ) : null}
                    </div>
                  </div>
                ))}

                {trace.packaging.packaging_code ? (
                  <div className="flex items-start gap-3">
                    <Package size={15} className="mt-0.5 text-forest-700" />
                    <div>
                      <p className="text-sm text-ink">
                        Packed at {trace.packaging.facility || 'the packing unit'}
                      </p>
                      <p className="text-xs text-ink-muted">
                        {amount(trace.packaging.packaged_quantity, trace.package.unit)} in{' '}
                        {trace.packaging.packages_in_run} package(s)
                        {trace.packaging.completed_at
                          ? ` · completed ${formatDateTime(trace.packaging.completed_at)}`
                          : ''}
                      </p>
                    </div>
                  </div>
                ) : null}
              </CardBody>
            </Card>
          ) : null}

          {trace.distribution.length ? (
            <Card>
              <CardHeader
                title="How it reached the shop"
                description="The shipments recorded against this package, from dispatch to receipt."
              />
              <CardBody className="space-y-4">
                {trace.distribution.map((shipment, index) => (
                  <div key={`${shipment.status}-${index}`} className="flex items-start gap-3">
                    <Truck size={15} className="mt-0.5 text-forest-700" />
                    <div>
                      <p className="text-sm text-ink">
                        {shipment.status}
                        {shipment.district ? ` · ${shipment.district}` : ''}
                      </p>
                      <p className="text-xs text-ink-muted">
                        {[shipment.carrier, shipment.tracking_reference].filter(Boolean).join(' · ') ||
                          null}
                      </p>
                      <p className="text-xs text-ink-muted">
                        {shipment.received_at
                          ? `Received by the retailer ${formatDateTime(shipment.received_at)}`
                          : shipment.delivered_at
                            ? `Delivered ${formatDateTime(shipment.delivered_at)}`
                            : shipment.dispatched_at
                              ? `Dispatched ${formatDateTime(shipment.dispatched_at)}`
                              : null}
                      </p>
                    </div>
                  </div>
                ))}
              </CardBody>
            </Card>
          ) : null}

          <Card>
            <CardHeader
              title="Blockchain record"
              description="The events HoneyChain recorded for this package, with their transaction ids. Written as the work happened — nothing on this list is written ahead of the step it describes."
            />
            <CardBody className="space-y-3">
              {blockchain.failed ? (
                <Alert variant="warning">
                  {blockchain.failed} event(s) could not be written to the chain yet. They are
                  recorded, and HoneyChain retries them; this page is showing them exactly as they
                  stand rather than as confirmed.
                </Alert>
              ) : null}
              {blockchain.pending ? (
                <Alert variant="info">
                  {blockchain.pending} event(s) are recorded and waiting to be written to the chain.
                </Alert>
              ) : null}
              {blockchain.skipped ? (
                <Alert variant="info">
                  {blockchain.skipped} event(s) are recorded in HoneyChain and were not written to the
                  chain.
                </Alert>
              ) : null}
              {blockchain.note ? <p className="text-xs text-ink-muted">{blockchain.note}</p> : null}

              <ul className="divide-y divide-sand-100">
                {(blockchain.transactions || []).map((row) => (
                  <li
                    key={row.event_id}
                    className="flex flex-wrap items-center justify-between gap-2 py-2.5"
                  >
                    <div className="min-w-0">
                      <p className="text-sm text-ink">{eventTypeLabel(row.tx_type)}</p>
                      <p className="text-xs text-ink-muted">
                        {row.timestamp ? formatDateTime(row.timestamp) : '—'}
                      </p>
                    </div>
                    <div className="min-w-0 text-right">
                      <Badge variant={row.synchronized ? 'success' : 'warning'} size="sm">
                        {row.synchronized ? 'On the chain' : 'Being written'}
                      </Badge>
                      {row.tx_id ? (
                        <p className="mt-1 font-mono text-xs text-ink-muted" title={row.tx_id}>
                          {row.tx_id.slice(0, 16)}…
                        </p>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>

              <details className="rounded-lg border border-sand-200 p-3">
                <summary className="cursor-pointer text-sm font-medium text-ink">
                  Blockchain Verification Details
                </summary>
                <div className="mt-3 overflow-x-auto">
                  <table className="min-w-full divide-y divide-sand-200 text-xs">
                    <thead>
                      <tr className="text-left uppercase tracking-wide text-ink-muted">
                        <th className="py-2 pr-4 font-medium">Transaction type</th>
                        <th className="py-2 pr-4 font-medium">Transaction id</th>
                        <th className="py-2 pr-4 font-medium">Timestamp</th>
                        <th className="py-2 font-medium">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-sand-100">
                      {(blockchain.transactions || []).map((row) => (
                        <tr key={row.event_id}>
                          <td className="py-2 pr-4 font-mono">{row.tx_type}</td>
                          <td className="py-2 pr-4 break-all font-mono">
                            {row.tx_id || 'Not on the chain yet'}
                          </td>
                          <td className="py-2 pr-4 whitespace-nowrap">
                            {row.timestamp ? formatDateTime(row.timestamp) : '—'}
                          </td>
                          <td className="py-2">{row.synchronized ? 'CONFIRMED' : row.status}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-2 text-xs text-ink-muted">
                  The payloads behind these transactions stay in HoneyChain: this page shows what was
                  written and when, not what the records hold in detail.
                </p>
              </details>

              <p className="text-xs text-ink-muted">
                The chain holds the summary of each step — the identifiers, the quantities and the
                moment. The measurements, notes and documents behind them stay in HoneyChain.
              </p>
            </CardBody>
          </Card>

          <div className="flex flex-wrap items-center justify-between gap-3 pb-8">
            <p className="text-xs text-ink-muted">
              This code has been opened {trace.qr.scans} time{trace.qr.scans === 1 ? '' : 's'}.
            </p>
            {footer}
          </div>
        </>
      ) : null}
    </div>
  );
}

export default TraceReport;
