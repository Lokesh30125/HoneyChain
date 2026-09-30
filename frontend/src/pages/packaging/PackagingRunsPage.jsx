import { WorkspaceHeader } from '@/components/common/WorkspaceHeader';
import { PackagingWorkspace } from '@/components/packaging/PackagingWorkspace';
import { PACKAGING_VIEW_COPY } from '@/constants/packaging';
import { ROLES } from '@/constants/roles';

/** The runs a packaging unit is working on, and the history of the ones it finished. */
export default function PackagingRunsPage() {
  return (
    <div className="space-y-6">
      <WorkspaceHeader
        title={PACKAGING_VIEW_COPY.runs.title}
        description={PACKAGING_VIEW_COPY.runs.description}
        requiredRoles={[ROLES.PACKAGING_UNIT]}
      />
      <PackagingWorkspace role={ROLES.PACKAGING_UNIT} view="runs" />
    </div>
  );
}
