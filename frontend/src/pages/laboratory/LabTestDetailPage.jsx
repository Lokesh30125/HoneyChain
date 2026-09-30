import { useParams } from 'react-router-dom';

import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { LabTestPanel } from '@/components/laboratory/LabTestPanel';
import { ROLES } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';

/**
 * One laboratory test.
 *
 * The technician who measured it, the administrator who may override it and the
 * officer who reads it use the same page; only the actions differ, and the API
 * decides which of those succeed. A beekeeper never reaches this route — their view
 * of a result is the quality summary on their own batch.
 */
export default function LabTestDetailPage() {
  const { testId } = useParams();
  const { user } = useAuth();
  const role = user?.role;
  const canWrite = role === ROLES.LAB_TECHNICIAN || role === ROLES.ADMIN;
  const canOverride = role === ROLES.ADMIN;

  return (
    <div className="space-y-6">
      <Breadcrumb
        items={[
          { label: 'Laboratory', to: role === ROLES.ADMIN ? '/admin/laboratory' : role === ROLES.KVIC_OFFICER ? '/kvic/laboratory' : '/laboratory' },
          { label: 'Test' },
        ]}
      />
      <PageHeader
        title="Laboratory test"
        description="The sample, the measurements recorded against it, and the decision the platform reached."
      />
      <LabTestPanel testId={testId} canWrite={canWrite} canOverride={canOverride} />
    </div>
  );
}
