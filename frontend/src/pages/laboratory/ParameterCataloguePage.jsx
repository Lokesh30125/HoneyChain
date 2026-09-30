import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { ParameterCatalogueTable } from '@/components/laboratory/ParameterCatalogueTable';
import { ROLES } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';

/** The parameter catalogue: what can be measured, and what a value is judged against. */
export default function ParameterCataloguePage() {
  const { user } = useAuth();
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'Laboratory', to: '/laboratory' }, { label: 'Reference parameters' }]} />
      <PageHeader
        title="Reference parameters"
        description="Ranges are configuration, not constants: each one is stored with the source it came from."
      />
      <ParameterCatalogueTable canConfigure={user?.role === ROLES.ADMIN} />
    </div>
  );
}
