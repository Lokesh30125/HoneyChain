import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { Badge } from '@/components/ui/Badge';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { DataTable } from '@/components/common/DataTable';
import { normaliseError } from '@/utils/errors';
import { useToast } from '@/hooks/useToast';
import * as clusterAnalytics from '@/services/clusterAnalyticsService';

const PAGE_SIZE = 10;

/**
 * The hives inside the cluster.
 *
 * These are the beekeepers' own hive rows, listed for an officer — opening one
 * leads to the same hive screen the owner uses. Nothing is duplicated on the
 * cluster side, so an edit made by the owner (or by staff on the hive screen)
 * shows up here on the next load.
 */
export function ClusterHivesTable({ clusterId, hiveDetailBasePath, onLoaded }) {
  const navigate = useNavigate();
  const toast = useToast();

  const [rows, setRows] = useState([]);
  const [meta, setMeta] = useState(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { hives, meta: pageMeta } = await clusterAnalytics.listClusterHives(clusterId, {
        page,
        pageSize: PAGE_SIZE,
      });
      setRows(hives);
      setMeta(pageMeta);
      // The overview counters are refreshed by the parent through this callback
      // so the two never disagree about how many hives the cluster holds.
      onLoaded?.(pageMeta?.total_items);
    } catch (caught) {
      const failure = normaliseError(caught);
      setError(failure);
      setRows([]);
      toast.error('Could not load the cluster hive list', failure.message);
    } finally {
      // Without this the table stays a skeleton forever — and a skeleton reads
      // like "still loading", not like "empty". The browser smoke caught exactly
      // that on an empty cluster.
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clusterId, page]);

  useEffect(() => {
    load();
  }, [load]);

  const columns = [
    {
      key: 'hive_code',
      header: 'Hive',
      render: (row) => <span className="font-medium text-ink">{row.hive_code}</span>,
    },
    {
      key: 'location_label',
      header: 'Location',
      render: (row) => row.location_label || [row.village, row.district].filter(Boolean).join(', ') || '—',
    },
    {
      key: 'bee_species',
      header: 'Bee species',
      render: (row) => row.bee_species || 'Not recorded',
    },
    {
      key: 'status_label',
      header: 'Status',
      render: (row) => (
        <Badge variant={row.status === 'ACTIVE' ? 'success' : 'neutral'} size="sm">
          {row.status_label || row.status}
        </Badge>
      ),
    },
    {
      key: 'device',
      header: 'Device',
      render: (row) =>
        row.device_count ? (
          <span className="text-sm text-ink-soft">
            {row.device_count} attached
            {row.primary_device_id ? ` · ${row.primary_device_id}` : ''}
          </span>
        ) : (
          <span className="text-sm text-ink-muted">None yet</span>
        ),
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Hives in this cluster"
        description="Registered by the beekeepers assigned here. Open a hive to see its devices and stored readings."
      />
      <CardBody className="px-0 py-0">
        <DataTable
          columns={columns}
          rows={rows}
          loading={loading}
          error={error}
          onRetry={load}
          meta={meta}
          onPageChange={setPage}
          onRowClick={(row) => navigate(`${hiveDetailBasePath}/${row.id}`)}
          emptyTitle="No hives in this cluster yet"
          emptyDescription="A hive appears here as soon as one of this cluster's beekeepers registers it — nothing has to be copied across."
          caption="Hives inside the cluster"
        />
      </CardBody>
    </Card>
  );
}

export default ClusterHivesTable;
