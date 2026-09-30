import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { ProcessingWorkspace } from '@/components/processing/ProcessingWorkspace';
import { ROLES } from '@/constants/roles';

/** Processing across the platform — the administrator's view of every run. */
export default function AdminProcessingPage({ view = 'runs' }) {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'Admin', to: '/admin' }, { label: 'Processing' }]} />
      <PageHeader title="Processing" description="Every processing run recorded on the platform, with its measured quantities." />
      <ProcessingWorkspace role={ROLES.ADMIN} view={view} basePath="/admin/processing" />
    </div>
  );
}
