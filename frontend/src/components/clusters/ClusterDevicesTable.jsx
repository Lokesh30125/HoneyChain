import { useCallback, useEffect, useState } from 'react';
import { Radio } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { DataTable } from '@/components/common/DataTable';
import { normaliseError } from '@/utils/errors';
import { useToast } from '@/hooks/useToast';
import { formatDateTime } from '@/utils/format';
import * as clusterAnalytics from '@/services/clusterAnalyticsService';

const PAGE_SIZE = 10;

const STATUS_VARIANT = {
  ONLINE: 'success',
  WARNING: 'warning',
  OFFLINE: 'danger',
  MAINTENANCE: 'neutral',
};

/**
 * The devices reporting inside the cluster.
 *
 * A device belongs to a hive, never to a cluster: this list resolves the hive
 * and shows it alongside. `sensors_enabled / sensors_total` and the last-seen
 * time are read from the stored rows, so a device that has never sent anything
 * is shown as offline rather than as "no data" with invented numbers.
 */
export function ClusterDevicesTable({ clusterId }) {
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
      const { devices, meta: pageMeta } = await clusterAnalytics.listClusterDevices(clusterId, {
        page,
        pageSize: PAGE_SIZE,
      });
      setRows(devices);
      setMeta(pageMeta);
    } catch (caught) {
      const failure = normaliseError(caught);
      setError(failure);
      setRows([]);
      toast.error('Could not load the cluster device list', failure.message);
    } finally {
      // Always leave the loading state: an empty list must render the empty
      // state, not skeleton rows that never resolve.
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clusterId, page]);

  useEffect(() => {
    load();
  }, [load]);

  const columns = [
    {
      key: 'device_id',
      header: 'Device',
      render: (row) => (
        <div>
          <p className="font-medium text-ink">{row.device_id}</p>
          <p className="text-xs text-ink-muted">{row.device_name}</p>
        </div>
      ),
    },
    {
      key: 'hive_code',
      header: 'Hive',
      render: (row) => row.hive_code || '—',
    },
    {
      key: 'status',
      header: 'Status',
      render: (row) => (
        <Badge variant={STATUS_VARIANT[row.status] || 'neutral'} size="sm">
          {row.status_label || row.status}
        </Badge>
      ),
    },
    {
      key: 'sensors',
      header: 'Sensors',
      render: (row) => `${row.sensors_enabled ?? 0} of ${row.sensors_total ?? 0} enabled`,
    },
    {
      key: 'last_seen',
      header: 'Last seen',
      render: (row) => (row.last_seen ? formatDateTime(row.last_seen) : 'Never'),
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Devices in this cluster"
        description="Paired to hives by their owners. A device is never registered to a cluster directly."
        action={<Radio size={16} className="text-ink-muted" aria-hidden="true" />}
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
          emptyTitle="No devices in this cluster yet"
          emptyDescription="A device appears here once one of these beekeepers pairs it with their hive."
          caption="Devices attached to hives inside the cluster"
        />
      </CardBody>
    </Card>
  );
}

export default ClusterDevicesTable;
