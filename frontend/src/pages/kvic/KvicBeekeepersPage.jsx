import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { BeekeeperDirectory } from '@/components/beekeepers/BeekeeperDirectory';
import { Button } from '@/components/ui/Button';

/**
 * KVIC officer view of the beekeeper directory.
 *
 * Verification is the core job here: review the submitted apiary details, then
 * record a decision with a remark. The decision is appended to the beekeeper's
 * history and written to the audit log.
 */
export default function KvicBeekeepersPage() {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'KVIC', to: '/kvic' }, { label: 'Beekeepers' }]} />
      <PageHeader
        title="Beekeepers"
        description="Review registrations, confirm apiary details and record verification decisions for the beekeepers you oversee."
        actions={
          <Button to="/kvic/clusters" variant="secondary" size="sm">
            Clusters
          </Button>
        }
      />
      <BeekeeperDirectory />
    </div>
  );
}
