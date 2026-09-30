import { useParams } from 'react-router-dom';

import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { Button } from '@/components/ui/Button';
import { ClusterView } from '@/components/clusters/ClusterView';

/**
 * Administrator view of one cluster.
 *
 * Same view as the KVIC officer's — the relationship is the relationship — with
 * the administrator's own navigation. An administrator may additionally place a
 * hive into a cluster from the hive screen, which is where the record lives.
 */
export default function AdminClusterDetailPage() {
  const { clusterId } = useParams();

  return (
    <div className="space-y-6">
      <Breadcrumb
        items={[
          { label: 'Administration', to: '/admin' },
          { label: 'Clusters', to: '/admin/clusters' },
          { label: 'Cluster' },
        ]}
      />
      <PageHeader
        title="Cluster"
        description="Members, hives, devices, telemetry and analyses for this cluster — resolved from the stored relationships."
        actions={
          <Button to="/admin/hives" variant="secondary" size="sm">
            Hive registry
          </Button>
        }
      />
      <ClusterView
        clusterId={clusterId}
        afterDeletePath="/admin/clusters"
        hiveDetailBasePath="/admin/hives"
        membersPath="/admin/clusters"
        collectionsPath="/admin/collections"
        batchesPath="/admin/batches"
      />
    </div>
  );
}
