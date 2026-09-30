import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { ClusterManagement } from '@/components/clusters/ClusterManagement';
import { Button } from '@/components/ui/Button';

/**
 * KVIC officer view of cluster management.
 *
 * Assigning a beekeeper to a cluster is the practical link between a verified
 * apiary and the officer responsible for it.
 */
export default function KvicClustersPage() {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'KVIC', to: '/kvic' }, { label: 'Clusters' }]} />
      <PageHeader
        title="Clusters"
        description="Group beekeepers in your district under a coordinator and keep membership current."
        actions={
          <Button to="/kvic/beekeepers" variant="secondary" size="sm">
            Beekeepers
          </Button>
        }
      />
      <ClusterManagement detailBasePath="/kvic/clusters" />
    </div>
  );
}
