import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Breadcrumb } from '@/components/common/Breadcrumb';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { PackageQrLabel } from '@/components/blockchain/PackageQrLabel';
import { PageHeader } from '@/components/common/PageHeader';
import { TraceabilityChain } from '@/components/common/TraceabilityChain';
import { PACKAGE_STATUS_META } from '@/constants/packaging';
import * as packagingService from '@/services/packagingService';
import { normaliseError } from '@/utils/errors';
import { formatDate, formatDateTime, formatNumber } from '@/utils/format';

/**
 * One package, with its own identity and the chain behind it.
 *
 * A package is where the honey stops being a batch and becomes a jar with a code
 * on it — so this screen shows both halves: what the package itself is (its code,
 * size, type, the date it was packed, its status and what has moved out of it),
 * and the records it descends from, read from the same rows the batch and the
 * packaging screens read.
 */

function Fact({ label, value, hint = null }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="mt-1 text-sm text-ink">{value ?? '—'}</p>
      {hint ? <p className="mt-0.5 text-xs text-ink-muted">{hint}</p> : null}
    </div>
  );
}

export default function PackageInformationPage({
  basePath = '/packaging',
  listPath = '/packaging/stock',
}) {
  const { packageId } = useParams();
  const [record, setRecord] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRecord(await packagingService.getPackage(packageId));
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [packageId]);

  useEffect(() => {
    load();
  }, [load]);

  const statusMeta = record
    ? PACKAGE_STATUS_META[record.status] || { label: record.status_label, variant: 'neutral' }
    : null;

  return (
    <div className="space-y-6">
      <Breadcrumb
        items={[
          { label: 'Packaging', to: basePath },
          { label: 'Packed stock', to: listPath },
          { label: record?.package_code || 'Package' },
        ]}
      />
      <PageHeader
        title="Package information"
        description="One package: what it holds, where it came from and how far it has travelled."
      />

      {error ? <Alert variant={error.status === 404 ? 'warning' : 'error'}>{error.message}</Alert> : null}

      {!record && loading && !error ? (
        <Card>
          <CardHeader title="Package" description="Loading the package register…" />
          <CardBody className="text-sm text-ink-soft" />
        </Card>
      ) : null}

      {record ? (
        <Card>
          <CardHeader
            title={record.package_code}
            description={`${record.batch_code}${record.collection_code ? ` · ${record.collection_code}` : ''}`}
            action={<Badge variant={statusMeta.variant}>{record.status_label || statusMeta.label}</Badge>}
          />
          <CardBody className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Fact
              label="Package size"
              value={`${formatNumber(record.package_size)} ${record.unit_label || record.unit}`}
              hint="The container this package is."
            />
            <Fact
              label="Quantity recorded"
              value={`${formatNumber(record.quantity)} ${record.unit_label || record.unit}`}
            />
            <Fact label="Packaging type" value={record.packaging_type_display || record.packaging_type_label || record.packaging_type} />
            <Fact label="Packed on" value={formatDate(record.packaging_date)} />
            <Fact
              label="Packaging run"
              value={record.packaging_code}
              hint={record.packaging_unit_name || null}
            />
            <Fact
              label="Released for distribution"
              value={record.released_at ? formatDateTime(record.released_at) : 'Not released yet'}
            />
            <Fact
              label="Quantity already shipped"
              value={`${formatNumber(record.dispatched_quantity)} ${record.unit_label || record.unit}`}
              hint={`${record.shipment_count} shipment(s) recorded against it.`}
            />
            <Fact
              label="Quantity still with the packing unit"
              value={`${formatNumber(record.remaining_quantity)} ${record.unit_label || record.unit}`}
            />
            <Fact
              label="Received"
              value={record.delivered_at ? formatDateTime(record.delivered_at) : 'Not received yet'}
              hint={record.delivered_at ? 'Confirmed by the receiving retailer.' : null}
            />
            <Fact label="Beekeeper" value={record.beekeeper_name || '—'} />
            <Fact label="KVIC cluster" value={record.cluster_name || '—'} />
            <Fact label="Created" value={formatDateTime(record.created_at)} />
          </CardBody>
        </Card>
      ) : null}

      {/* The jar's public identity: the code that resolves to this package's
          customer page, issued once and printable from here. */}
      {record ? <PackageQrLabel packageId={record.id} packageCode={record.package_code} onIssued={load} /> : null}

      {record?.traceability?.length ? (
        <TraceabilityChain
          nodes={record.traceability}
          title="Package → Batch → Collection → Hive → Beekeeper"
          description="The chain as it is stored: this package, the run that made it, the batch it carries, the harvest behind the batch and the apiary that produced it."
        />
      ) : null}
    </div>
  );
}
