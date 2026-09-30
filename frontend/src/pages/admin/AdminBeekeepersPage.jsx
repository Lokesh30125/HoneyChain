import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { BeekeeperDirectory } from '@/components/beekeepers/BeekeeperDirectory';
import { Button } from '@/components/ui/Button';

/**
 * Administrator view of the beekeeper directory.
 *
 * Same table, filters and verification flow as the KVIC screen — shared in
 * `BeekeeperDirectory` rather than duplicated — with an administrator-specific
 * framing.
 */
export default function AdminBeekeepersPage() {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'Administration', to: '/admin' }, { label: 'Beekeepers' }]} />
      <PageHeader
        title="Beekeepers"
        description="Every registered apiary, with the verification state a KVIC officer or administrator has recorded."
        actions={
          <>
            <Button to="/admin/clusters" variant="secondary" size="sm">
              Clusters
            </Button>
            <Button to="/admin/users" variant="secondary" size="sm">
              Users
            </Button>
          </>
        }
      />
      <BeekeeperDirectory />
    </div>
  );
}
