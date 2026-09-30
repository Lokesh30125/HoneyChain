import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { ClusterManagement } from '@/components/clusters/ClusterManagement';
import { Button } from '@/components/ui/Button';

/**
 * Administrator view of KVIC cluster management.
 *
 * Scope is deliberately basic: create, edit, activate/deactivate and manage
 * membership. Cluster analytics belong to a later phase and are not stubbed
 * here with invented figures.
 */
export default function AdminClustersPage() {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'Administration', to: '/admin' }, { label: 'Clusters' }]} />
      <PageHeader
        title="Clusters"
        description="KVIC beekeeping clusters, their coordinators and the beekeepers assigned to them."
        actions={
          <Button to="/admin/beekeepers" variant="secondary" size="sm">
            Beekeepers
          </Button>
        }
      />
      <ClusterManagement detailBasePath="/admin/clusters" />
    </div>
  );
}
