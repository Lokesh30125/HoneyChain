import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { LaboratoryFacilitiesCard } from '@/components/laboratory/LaboratoryFacilitiesCard';
import { ROLES } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';

/** Laboratories registered on the platform, each reused by every test that names it. */
export default function FacilitiesPage() {
  const { user } = useAuth();
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'Laboratory', to: '/laboratory' }, { label: 'Laboratories' }]} />
      <PageHeader
        title="Laboratories"
        description="A facility is registered once and referenced by its tests — never re-created per sample."
      />
      <LaboratoryFacilitiesCard canManage={user?.role === ROLES.LAB_TECHNICIAN || user?.role === ROLES.ADMIN} />
    </div>
  );
}
