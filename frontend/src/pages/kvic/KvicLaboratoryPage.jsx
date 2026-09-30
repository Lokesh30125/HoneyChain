import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { LaboratoryWorkspace } from '@/components/laboratory/LaboratoryWorkspace';
import { ROLES } from '@/constants/roles';

/** Laboratory oversight for a KVIC officer: the same tests, read-only, scoped to their clusters. */
export default function KvicLaboratoryPage({ view = 'tests' }) {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'KVIC', to: '/kvic' }, { label: 'Laboratory' }]} />
      <PageHeader
        title="Laboratory oversight"
        description="What the laboratory measured in the honey from your clusters, and the outcome the platform reached."
      />
      <LaboratoryWorkspace role={ROLES.KVIC_OFFICER} view={view} basePath="/kvic/laboratory" />
    </div>
  );
}
