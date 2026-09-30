import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Package, Wheat } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { DataTable } from '@/components/common/DataTable';
import { COLLECTION_MESSAGES, COLLECTION_STATUS_META, unitLabel } from '@/constants/collection';
import * as collectionService from '@/services/collectionService';
import * as batchService from '@/services/batchService';
import { normaliseError } from '@/utils/errors';
import { formatDate } from '@/utils/format';

/**
 * A cluster's harvest records, inside the cluster screen.
 *
 * Shown through the cluster endpoints (`/clusters/{id}/collections` and
 * `/batches`), which return **the beekeepers' own rows** filtered to this cluster.
 * Nothing is copied per cluster: a collection is stored once, owned by the
 * beekeeper who recorded it, and this panel is a view of it — which is why a
 * change the beekeeper makes appears here the next time the panel loads.
 *
 * Read-only. An officer cannot record, complete or cancel a harvest, and no
 * button here suggests otherwise.
 */
export function ClusterHarvestPanel({ clusterId, collectionsPath, batchesPath }) {
  const [collections, setCollections] = useState([]);
  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Read through the cluster endpoints: the cluster's own scope is resolved
      // by the API from the caller's authorised clusters, never from this screen.
      const [harvests, produced] = await Promise.all([
        collectionService.getClusterCollections(clusterId, { pageSize: 5 }),
        batchService.getClusterBatches(clusterId, { pageSize: 5 }),
      ]);
      setCollections(harvests.collections);
      setBatches(produced.batches);
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [clusterId]);

  useEffect(() => {
    load();
  }, [load]);

  const collectionColumns = [
    {
      key: 'collection_code',
      header: 'Collection',
      render: (row) =>
        collectionsPath ? (
          <Link className="font-medium text-forest-700 hover:underline" to={`${collectionsPath}/${row.id}`}>
            {row.collection_code}
          </Link>
        ) : (
          row.collection_code
        ),
    },
    { key: 'collection_date', header: 'Date', render: (row) => formatDate(row.collection_date) },
    {
      key: 'quantity',
      header: 'Harvested',
      align: 'right',
      render: (row) =>
        `${Number(row.total_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${unitLabel(row.unit)}`,
    },
    {
      key: 'status',
      header: 'Status',
      render: (row) => (
        <Badge variant={(COLLECTION_STATUS_META[row.status] || {}).variant || 'neutral'} size="sm">
          {(COLLECTION_STATUS_META[row.status] || {}).label || row.status}
        </Badge>
      ),
    },
    {
      key: 'beekeeper',
      header: 'Beekeeper',
      render: (row) => row.beekeeper_name || row.beekeeper_code || '—',
    },
  ];

  const batchColumns = [
    {
      key: 'batch_code',
      header: 'Batch',
      render: (row) =>
        batchesPath ? (
          <Link className="font-medium text-forest-700 hover:underline" to={`${batchesPath}/${row.id}`}>
            {row.batch_code}
          </Link>
        ) : (
          row.batch_code
        ),
    },
    { key: 'collection_date', header: 'Harvest date', render: (row) => formatDate(row.collection_date) },
    {
      key: 'quantity',
      header: 'Quantity',
      align: 'right',
      render: (row) =>
        `${Number(row.quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${unitLabel(row.unit)}`,
    },
    { key: 'stage', header: 'Stage', render: (row) => <Badge variant="success" size="sm">{row.status_label || row.status}</Badge> },
  ];

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader
          title="Harvests in this cluster"
          description="Recorded by the cluster's beekeepers — the same rows their owners see."
          icon={<Wheat size={18} aria-hidden="true" />}
          action={
            collectionsPath ? (
              <Button to={`${collectionsPath}?cluster=${clusterId}`} variant="secondary" size="sm">
                View all
              </Button>
            ) : null
          }
        />
        <CardBody>
          <DataTable
            columns={collectionColumns}
            rows={collections}
            loading={loading}
            error={error}
            onRetry={load}
            emptyTitle={COLLECTION_MESSAGES.emptyCollections}
            emptyDescription="A harvest recorded by a member of this cluster appears here — nothing is entered twice."
            caption="Cluster collections"
            skeletonRows={3}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Batches from this cluster"
          description="Created automatically when a member completes a harvest."
          icon={<Package size={18} aria-hidden="true" />}
          action={
            batchesPath ? (
              <Button to={`${batchesPath}?cluster=${clusterId}`} variant="secondary" size="sm">
                View all
              </Button>
            ) : null
          }
        />
        <CardBody>
          <DataTable
            columns={batchColumns}
            rows={batches}
            loading={loading}
            error={error}
            onRetry={load}
            emptyTitle={COLLECTION_MESSAGES.emptyBatches}
            emptyDescription="These appear once a member completes a collection."
            caption="Cluster batches"
            skeletonRows={3}
          />
        </CardBody>
      </Card>
    </div>
  );
}

export default ClusterHarvestPanel;
