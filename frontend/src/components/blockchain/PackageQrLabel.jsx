import { useCallback, useEffect, useState } from 'react';
import { ExternalLink, Printer, QrCode, RefreshCw } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { LoadingState } from '@/components/common/LoadingState';
import * as blockchainService from '@/services/blockchainService';
import { normaliseError } from '@/utils/errors';
import { formatDateTime } from '@/utils/format';

/**
 * A package's QR label.
 *
 * The code is the package's public identity: it resolves to the customer's
 * traceability page for this jar and nothing else. It is issued once — the
 * backend returns the identity that already exists if one does, and records the
 * QR event only the first time — so reprinting a label never invalidates a code
 * that is already on a lid.
 *
 * The label itself comes from the API as an SVG drawn from the link stored on the
 * package record, which is why it can be printed straight from here and why the
 * label and the record can never disagree.
 */
export function PackageQrLabel({ packageId, packageCode, onIssued }) {
  const [qr, setQr] = useState(null);
  const [loading, setLoading] = useState(true);
  const [issuing, setIssuing] = useState(false);
  const [error, setError] = useState(null);
  const [note, setNote] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setQr(await blockchainService.getPackageQr(packageId));
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [packageId]);

  useEffect(() => {
    load();
  }, [load]);

  const issue = async () => {
    setIssuing(true);
    setError(null);
    setNote(null);
    try {
      const issued = await blockchainService.issuePackageQr(packageId);
      setQr(issued);
      // The package record changed on the server (it now carries its QR); let
      // the page holding it re-read it instead of showing the old record.
      onIssued?.(issued);
      setNote(
        issued.event_id
          ? `The label is recorded as ${issued.event_id}${issued.tx_id ? ` and confirmed on the chain (${issued.tx_id.slice(0, 16)}…).` : '; it will be written to the chain by the outbox.'}`
          : 'The label is ready.',
      );
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setIssuing(false);
    }
  };

  const printLabel = () => {
    if (!qr?.svg) return;
    const child = window.open('', 'qr-label', 'width=420,height=560');
    if (!child) return;
    child.document.write(
      `<!doctype html><html><head><title>${packageCode} — QR label</title>` +
        '<style>body{font-family:system-ui,sans-serif;margin:24px;text-align:center}' +
        'svg{width:260px;height:260px}h1{font-size:16px;margin:12px 0 4px}' +
        'p{font-size:12px;color:#555;margin:2px 0;word-break:break-all}</style></head><body>' +
        qr.svg +
        `<h1>${packageCode}</h1>` +
        `<p>QR ID ${qr.qr_id || ''}</p>` +
        `<p>Batch ${qr.batch_code || ''}</p>` +
        `<p>${qr.qr_payload || ''}</p>` +
        '</body></html>',
    );
    child.document.close();
    child.focus();
    child.print();
  };

  const issued = Boolean(qr?.qr_payload);

  return (
    <Card>
      <CardHeader
        title="QR label"
        description="The code on the jar. It resolves to this package's public traceability page — the same page a customer opens by scanning it."
        action={
          <Button size="sm" variant="secondary" leftIcon={<RefreshCw size={15} />} onClick={load} loading={loading}>
            Refresh
          </Button>
        }
      />
      <CardBody className="space-y-4">
        {error ? (
          <Alert variant="warning" title="Unable to load the QR label">
            {error.message}
          </Alert>
        ) : null}
        {note ? <Alert variant="info">{note}</Alert> : null}

        {loading && !qr ? <LoadingState label="Reading the package's label…" /> : null}

        {qr ? (
          issued ? (
            <div className="grid gap-5 sm:grid-cols-[240px_1fr]">
              <div className="rounded-lg border border-sand-300 bg-white p-3">
                {/* The label is the API's own SVG, drawn from the stored link. */}
                <div
                  className="mx-auto h-[200px] w-[200px]"
                  /* eslint-disable-next-line react/no-danger */
                  dangerouslySetInnerHTML={{ __html: qr.svg }}
                />
                <p className="mt-2 text-center font-mono text-xs text-ink">{qr.package_code}</p>
              </div>

              <div className="space-y-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="success" size="sm" icon={<QrCode size={13} />}>
                    QR Generated ✓
                  </Badge>
                  <span className="text-xs text-ink-muted">
                    Issued {qr.generated_at ? formatDateTime(qr.generated_at) : '—'}
                  </span>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
                      Package ID
                    </p>
                    <p className="mt-1 font-mono text-xs">{qr.package_code}</p>
                  </div>
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
                      QR ID
                    </p>
                    <p className="mt-1 font-mono text-xs">{qr.qr_id}</p>
                  </div>
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
                    Resolves to
                  </p>
                  <a
                    className="break-all text-forest-700 underline decoration-honey-400"
                    href={blockchainService.traceUrl(qr.package_code)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {qr.qr_payload}
                  </a>
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
                    Verifications by customers
                  </p>
                  <p className="mt-1 text-ink">
                    {qr.scans} scan{qr.scans === 1 ? '' : 's'}
                    <span className="ml-1 text-xs text-ink-muted">
                      — counted once per package per hour, not once per page refresh.
                    </span>
                  </p>
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
                    Traceability event
                  </p>
                  <p className="mt-1 font-mono text-xs">
                    {qr.event_id || '—'}
                    {qr.tx_id ? ` · ${qr.tx_id.slice(0, 16)}…` : ' · not confirmed yet'}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2 pt-1">
                  <Button size="sm" leftIcon={<Printer size={15} />} onClick={printLabel}>
                    Print label
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    leftIcon={<ExternalLink size={15} />}
                    to={blockchainService.traceUrl(qr.package_code)}
                  >
                    Open verification page
                  </Button>
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-ink-soft">
                This package has no QR identity yet. Issuing one creates the link a customer will
                scan and records a QR event for it — once, for the life of the package.
              </p>
              {/* The customer's requirement in one label: the action that
                  creates the identity, named for what it makes. */}
              <Button loading={issuing} leftIcon={<QrCode size={15} />} onClick={issue}>
                Generate QR
              </Button>
            </div>
          )
        ) : null}
      </CardBody>
    </Card>
  );
}

export default PackageQrLabel;
