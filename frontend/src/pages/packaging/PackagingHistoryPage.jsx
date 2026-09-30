import { WorkspaceHeader } from '@/components/common/WorkspaceHeader';
import { PackagingWorkspace } from '@/components/packaging/PackagingWorkspace';
import { PACKAGING_VIEW_COPY } from '@/constants/packaging';
import { ROLES } from '@/constants/roles';

/** Every packaging run ever recorded against a batch — cancelled ones included. */
export default function PackagingHistoryPage() {
  return (
    <div className="space-y-6">
      <WorkspaceHeader
        title={PACKAGING_VIEW_COPY.history.title}
        description={PACKAGING_VIEW_COPY.history.description}
        requiredRoles={[ROLES.PACKAGING_UNIT]}
      />
      <PackagingWorkspace role={ROLES.PACKAGING_UNIT} view="history" />
    </div>
  );
}
