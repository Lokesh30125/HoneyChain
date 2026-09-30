import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { LaboratoryWorkspace } from '@/components/laboratory/LaboratoryWorkspace';
import { ROLES } from '@/constants/roles';

/** Laboratory across the platform — tests, results and the parameter catalogue behind them. */
export default function AdminLaboratoryPage({ view = 'tests' }) {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'Admin', to: '/admin' }, { label: 'Laboratory' }]} />
      <PageHeader title="Laboratory" description="Every test recorded on the platform, and the reference ranges decisions are made against." />
      <LaboratoryWorkspace role={ROLES.ADMIN} view={view} basePath="/admin/laboratory" />
    </div>
  );
}
