import { Boxes, Droplets, FlaskConical, Factory, Hexagon, Package, Route, Store, User } from 'lucide-react';

import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { formatDateTime } from '@/utils/format';

/**
 * The chain behind one record, read top-down.
 *
 * Every node is a real row the API returned — a package, the packaging run that
 * made it, the batch, the processing run, the laboratory test, the harvest, the
 * hive and the beekeeper behind them all. Nothing is synthesised on the client:
 * if a node is absent from the payload it is absent from the screen, which is how
 * a shop can see that the record it is holding is genuine rather than decorated.
 *
 * The same component renders the chain for a package, a shipment and a
 * laboratory sample, so "traceability" cannot mean three different things.
 */

const KIND_ICONS = {
  PACKAGE: Package,
  PACKAGING: Boxes,
  DISTRIBUTION: Route,
  BATCH: Droplets,
  PROCESSING: Factory,
  LABORATORY: FlaskConical,
  LAB_TEST: FlaskConical,
  SAMPLE: FlaskConical,
  COLLECTION: Droplets,
  HIVE: Hexagon,
  BEEKEEPER: User,
  RETAILER: Store,
};

const KIND_LABELS = {
  PACKAGE: 'Package',
  PACKAGING: 'Packaging run',
  DISTRIBUTION: 'Shipment',
  BATCH: 'Honey batch',
  PROCESSING: 'Processing run',
  LABORATORY: 'Laboratory test',
  LAB_TEST: 'Laboratory test',
  SAMPLE: 'Sample',
  COLLECTION: 'Honey collection',
  HIVE: 'Source hive',
  BEEKEEPER: 'Beekeeper',
  RETAILER: 'Retailer',
};

export function TraceabilityChain({
  nodes = [],
  title = 'Traceability',
  description = 'Where this record came from, read from the records themselves.',
  className = '',
}) {
  if (!nodes.length) {
    return null;
  }

  return (
    <Card className={className}>
      <CardHeader title={title} description={description} icon={<Route size={18} />} />
      <CardBody className="p-0">
        <ol className="divide-y divide-sand-200">
          {nodes.map((node, index) => {
            const kind = String(node.kind || '').toUpperCase();
            const Icon = KIND_ICONS[kind] || Route;
            return (
              <li key={`${kind}-${node.identifier || index}`} className="flex items-start gap-3 px-5 py-3">
                <span className="mt-0.5 flex h-8 w-8 flex-none items-center justify-center rounded-lg bg-honey-50 text-honey-700">
                  <Icon size={16} />
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ink">
                    {node.label || KIND_LABELS[kind] || kind}
                  </p>
                  {node.identifier ? (
                    <p className="font-mono text-xs text-ink-soft">{node.identifier}</p>
                  ) : null}
                  {node.detail ? <p className="mt-0.5 text-xs text-ink-muted">{node.detail}</p> : null}
                  {node.recorded_at ? (
                    <p className="mt-0.5 text-xs text-ink-muted">{formatDateTime(node.recorded_at)}</p>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      </CardBody>
    </Card>
  );
}

export default TraceabilityChain;
